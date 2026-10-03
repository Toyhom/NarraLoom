"""Register model mouth keyposes and morph one replacement region, never overlay a second mouth."""

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from PIL import Image
from scipy.spatial import Delaunay

LIP_IDS = [61, 40, 37, 0, 267, 270, 291, 321, 314, 17, 84, 91, 78, 81, 13, 311, 308, 402, 14, 178]


def landmarks(detector, image):
    found = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(image.convert("RGB"))))
    if not found.face_landmarks:
        raise ValueError("No measured face in a mouth keypose")
    face = found.face_landmarks[0]
    wh = np.array(image.size)
    pts = np.array([[face[i].x, face[i].y] for i in LIP_IDS]) * wh
    eyes = (
        np.array(
            [
                [np.mean([face[i].x for i in ids]), np.mean([face[i].y for i in ids])]
                for ids in [[33, 133], [362, 263]]
            ]
        )
        * wh
    )
    return pts, eyes


def mouth_contrast(image, rig):
    a = np.asarray(image.convert("RGB"))
    gray = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    lm = rig["landmarks"]
    # The rig's active mouth moves after binding. Inspect the immutable source
    # contours, so rebinding never changes the closed-mouth decision by itself.
    inner = lm.get("contours", {}).get("lip_inner", [])
    original_mouth = np.mean(np.array(inner)[[2, 6]], axis=0) if len(inner) == 8 else lm["mouth"]
    x, y = np.array(original_mouth) * image.size
    corners = np.array(lm.get("mouth_corners", []))
    w = (
        float(np.linalg.norm((corners[1] - corners[0]) * image.size))
        if corners.shape == (2, 2)
        else rig["mouth_width_px"]
    )
    band = gray[
        max(0, int(y - w * 0.09)) : int(y + w * 0.09) + 1, max(0, int(x - w * 0.4)) : int(x + w * 0.4) + 1
    ]
    ring = gray[
        max(0, int(y + w * 0.16)) : int(y + w * 0.30) + 1, max(0, int(x - w * 0.4)) : int(x + w * 0.4) + 1
    ]
    return float(np.median(ring) - np.percentile(band, 15))


def warp_patch(image, source, target, triangles, size):
    output = np.zeros((size, size, 3), np.float32)
    for tri in triangles:
        a = source[tri].astype(np.float32)
        b = target[tri].astype(np.float32)
        if abs(cv2.contourArea(a)) < 0.005 or abs(cv2.contourArea(b)) < 0.005:
            continue
        matrix = cv2.getAffineTransform(a, b)
        warped = cv2.warpAffine(
            image, matrix, (size, size), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101
        )
        mask = np.zeros((size, size), np.uint8)
        cv2.fillConvexPoly(mask, np.round(b).astype(np.int32), 1)
        output[mask != 0] = warped[mask != 0]
    return output


def build(folder, package, detector):
    source = package / "puppet"
    rig = json.loads((source / "rig.json").read_text())
    portrait = Image.open(source / "portrait.png").convert("RGBA")
    record = json.loads((folder / "record.json").read_text())
    source_hash = hashlib.sha256((source / "portrait.png").read_bytes()).hexdigest()
    if record.get("source_sha256", source_hash) != source_hash:
        raise ValueError("Portrait changed since mouth generation; regenerate its mouth keyposes")
    box = np.array(record["crop_box"])
    factor = (box[2] - box[0]) / 768
    reference = Image.open(folder / "reference.png").convert("RGB")
    ref_lips, ref_eyes = landmarks(detector, reference)
    contrast = mouth_contrast(portrait, rig)
    missing = contrast < 18
    names = ["closed", "open", "round", "smile"]
    images = [Image.open(folder / (n + ".png")).convert("RGB") for n in names]
    if not missing:
        images[0] = reference
    detected = [landmarks(detector, im) for im in images]
    # Align the eyes first. Only the resulting mouth region is ever transferred.
    aligned = []
    points = []
    for image, (lips, eyes) in zip(images, detected, strict=True):
        src = np.vstack([eyes, eyes.mean(0) + [0, np.linalg.norm(eyes[1] - eyes[0])]])
        dst = np.vstack([ref_eyes, ref_eyes.mean(0) + [0, np.linalg.norm(ref_eyes[1] - ref_eyes[0])]])
        matrix = cv2.getAffineTransform(src.astype(np.float32), dst.astype(np.float32))
        aligned.append(cv2.warpAffine(np.array(image), matrix, (768, 768), borderMode=cv2.BORDER_REFLECT_101))
        points.append(lips @ matrix[:, :2].T + matrix[:, 2])
    anchor = (points[0][0] + points[0][6]) / 2
    for i in range(1, 4):
        corners = (points[i][0] + points[i][6]) / 2
        translation = anchor - corners
        aligned[i] = cv2.warpAffine(
            aligned[i],
            np.float32([[1, 0, translation[0]], [0, 1, translation[1]]]),
            (768, 768),
            borderMode=cv2.BORDER_REFLECT_101,
        )
        points[i] += translation
    all_points = np.concatenate(points)
    # Include the original lip line in the replacement footprint when it exists.
    if not missing:
        all_points = np.concatenate([all_points, ref_lips])
    low = all_points.min(0)
    high = all_points.max(0)
    span = high - low
    extent = span * np.array([1.35, 1.55])
    center = (low + high) / 2
    left, top = center - extent / 2
    size = 192
    crop_matrix = np.float32(
        [[size / extent[0], 0, -left * size / extent[0]], [0, size / extent[1], -top * size / extent[1]]]
    )
    patches = [
        cv2.warpAffine(im, crop_matrix, (size, size), borderMode=cv2.BORDER_REFLECT_101).astype(np.float32)
        for im in aligned
    ]
    coordinates = [(p - [left, top]) * size / extent for p in points]
    anchors = np.array(
        [
            [0, 0],
            [size / 2, 0],
            [size - 1, 0],
            [size - 1, size / 2],
            [size - 1, size - 1],
            [size / 2, size - 1],
            [0, size - 1],
            [0, size / 2],
        ],
        np.float32,
    )
    coordinates = [np.vstack([p, anchors]) for p in coordinates]
    triangles = Delaunay(np.mean(coordinates, axis=0)).simplices
    region = np.zeros((size, size), np.uint8)
    hull = cv2.convexHull(np.concatenate([p[:12] for p in coordinates]).astype(np.float32))
    cv2.fillConvexPoly(region, np.round(hull).astype(np.int32), 255)
    region = cv2.dilate(region, np.ones((9, 9), np.uint8))
    alpha = cv2.GaussianBlur(region, (13, 13), 2.5).astype(np.float32) / 255
    # Some edits invent nostrils above a smiling lip. Preserve that part of the
    # source face: only a narrow margin above the measured neutral upper lip
    # belongs to this replacement region.
    neutral_width = np.linalg.norm(points[0][6] - points[0][0])
    guard_y = (points[0][:12, 1].min() - neutral_width * 0.18 - top) * size / extent[1]
    alpha *= np.clip((np.arange(size)[:, None] - guard_y) / 5, 0, 1)
    original_patch = cv2.warpAffine(
        np.array(reference), crop_matrix, (size, size), borderMode=cv2.BORDER_REFLECT_101
    ).astype(np.float32)
    # Match the local skin around the lip mask, without copying a changed nose or jaw.
    border = (alpha > 0.02) & (alpha < 0.45)
    for i in range(4):
        delta = np.median(original_patch[border] - patches[i][border], axis=0)
        patches[i] = np.clip(patches[i] + delta, 0, 255)
    atlas = np.zeros((size * 6, size * 8, 4), np.uint8)
    for smile in range(2):
        for rounded in range(3):
            r = rounded / 2
            for opened in range(8):
                a = opened / 7
                weights = np.array([1 - a, a * (1 - r) * (1 - smile), a * r, a * (1 - r) * smile])
                target = sum(w * p for w, p in zip(weights, coordinates, strict=True))
                # Morph geometry from closed to open; do not dissolve a closed
                # lip line over an open cavity (it looks like a second mouth).
                texture_weights = (
                    np.array([1, 0, 0, 0])
                    if opened == 0
                    else np.array([0, (1 - r) * (1 - smile), r, (1 - r) * smile])
                )
                pixels = sum(
                    w * warp_patch(im, p, target, triangles, size)
                    for w, im, p in zip(texture_weights, patches, coordinates, strict=True)
                    if w > 0
                )
                tile = np.dstack([np.clip(pixels, 0, 255).astype(np.uint8), (alpha * 255).astype(np.uint8)])
                row = smile * 3 + rounded
                atlas[row * size : (row + 1) * size, opened * size : (opened + 1) * size] = tile
    Image.fromarray(atlas).save(source / "mouth-atlas.png")
    roi = [
        float(box[0] + left * factor),
        float(box[1] + top * factor),
        float(extent[0] * factor),
        float(extent[1] * factor),
    ]
    rig.update(
        version=2,
        mouth_binding={
            "method": "registered image-keypose morph atlas",
            "atlas": "mouth-atlas.png",
            "roi_px": roi,
            "tile_size": size,
            "jaw_steps": 8,
            "round_steps": 3,
            "smile_steps": 2,
            "source_mouth_contrast": contrast,
            "missing_source_mouth_repaired": missing,
            "model": record["model"],
            "source_sha256": hashlib.sha256((source / "portrait.png").read_bytes()).hexdigest(),
        },
    )
    # Bind the mouth to the measured neutral keypose, including repaired mouths.
    anchor_world = box[:2] + anchor * factor
    rig["landmarks"]["mouth"] = (anchor_world / portrait.size).tolist()
    rig["mouth_width_px"] = float(np.linalg.norm(points[0][6] - points[0][0]) * factor)
    rig["provenance"]["mouth_keyposes"] = (
        "FLUX.2 klein edits, MediaPipe eye/lip registration, piecewise-affine interpolation; local replacement only"
    )
    (source / "rig.json").write_text(json.dumps(rig, ensure_ascii=False, indent=2))
    (source / "mouth-generation.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
    # Export a visual QA sheet of actual composited closed/intermediate/open/round/smile states.
    sheet = Image.new("RGB", (size * 5, size), "white")
    roi_box = tuple(round(x) for x in [roi[0], roi[1], roi[0] + roi[2], roi[1] + roi[3]])
    base = portrait.crop(roi_box).resize((size, size)).convert("RGBA")
    for i, (row, col) in enumerate([(0, 0), (0, 3), (0, 7), (2, 7), (3, 7)]):
        combined = base.copy()
        combined.alpha_composite(
            Image.fromarray(atlas[row * size : (row + 1) * size, col * size : (col + 1) * size])
        )
        sheet.paste(combined, (i * size, 0))
    sheet.save(folder / "bound-mouths.png")
    print("MOUTH_ATLAS_READY", package.name, json.dumps(rig["mouth_binding"]), flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--study", type=Path, required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--characters", type=Path)
    group.add_argument("--package", type=Path)
    p.add_argument("--model", required=True)
    args = p.parse_args()
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=args.model, delegate=mp.tasks.BaseOptions.Delegate.CPU
        ),
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
    )
    with mp.tasks.vision.FaceLandmarker.create_from_options(options) as detector:
        if args.package:
            cid = json.loads((args.package / "profile.json").read_text())["character_id"]
            build(args.study / cid, args.package, detector)
        else:
            for folder in sorted(args.study.glob("char_*")):
                build(folder, args.characters / folder.name, detector)


if __name__ == "__main__":
    main()
