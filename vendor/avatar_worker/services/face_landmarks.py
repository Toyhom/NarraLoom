"""MediaPipe face landmarks on full-body character renders and expanded concepts."""

import argparse
import json
from pathlib import Path

import mediapipe as mp
import numpy as np
from PIL import Image, ImageDraw


def locate(detector, path, output):
    image = Image.open(path).convert("RGB")
    width, height = image.size
    landmarks = None
    crops = [
        (0, 0, width, height),
        (int(width * 0.22), int(height * 0.02), int(width * 0.78), int(height * 0.42)),
    ]
    for crop in crops:
        cut = image.crop(crop).resize((768, round((crop[3] - crop[1]) * 768 / (crop[2] - crop[0]))))
        result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(cut)))
        if result.face_landmarks:
            candidate = result.face_landmarks[0]
            if all(0 <= candidate[i].x <= 1 and 0 <= candidate[i].y <= 1 for i in [10, 152, 61, 291]):
                landmarks = candidate
                break
    if landmarks is None:
        return {"detected": False}

    def point(ids):
        x = sum(landmarks[i].x for i in ids) / len(ids)
        y = sum(landmarks[i].y for i in ids) / len(ids)
        return [(crop[0] + x * (crop[2] - crop[0])) / width, (crop[1] + y * (crop[3] - crop[1])) / height]

    eyes = sorted([point([33, 133]), point([362, 263])], key=lambda p: p[0])
    points = {
        "left_eye": eyes[0],
        "right_eye": eyes[1],
        "mouth": point([13, 14]),
        "forehead": point([10]),
        "chin": point([152]),
    }
    cheeks = [point([234]), point([454])]
    points["face_width"] = abs(cheeks[0][0] - cheeks[1][0])
    if not (points["mouth"][1] > max(e[1] for e in eyes) and points["face_width"] > 0.025):
        return {"detected": False, "reason": "inconsistent detected geometry"}
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    for name, p in points.items():
        if name == "face_width":
            continue
        x, y = p[0] * width, p[1] * height
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill="red")
        draw.text((x + 5, y), name, fill="red")
    overlay.save(output)
    contours = {
        "lip_outer": [61, 40, 37, 0, 267, 270, 291, 321, 314, 17, 84, 91],
        "lip_inner": [78, 81, 13, 311, 308, 402, 14, 178],
        "eye_left": [33, 160, 158, 133, 153, 144],
        "eye_right": [362, 385, 387, 263, 373, 380],
        "brow_left": [70, 63, 105, 66, 107],
        "brow_right": [336, 296, 334, 293, 300],
        "face_oval": [
            10,
            338,
            297,
            332,
            284,
            251,
            389,
            356,
            454,
            323,
            361,
            288,
            397,
            365,
            379,
            378,
            400,
            377,
            152,
            148,
            176,
            149,
            150,
            136,
            172,
            58,
            132,
            93,
            234,
            127,
            162,
            21,
            54,
            103,
            67,
            109,
        ],
    }
    points["contours"] = {name: [point([i]) for i in indices] for name, indices in contours.items()}
    points["mouth_corners"] = sorted([point([61]), point([291])], key=lambda p: p[0])
    points["nose"] = point([1])
    return {
        "detected": True,
        "landmark_method": "mediapipe-face-landmarker",
        "landmark_validated": True,
        "detection_threshold": 0.5,
        "presence_threshold": 0.5,
        **points,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--job", type=Path, required=True)
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
        found = {}
        for key, name in [("concept", "concept.png"), ("front", "mesh-front.png"), ("back", "mesh-back.png")]:
            found[key] = (
                locate(detector, args.job / name, args.job / f"landmarks-{key}.png")
                if (args.job / name).is_file()
                else {"detected": False, "reason": "view not requested"}
            )
    (args.job / "face-landmarks-mp.json").write_text(json.dumps(found, indent=2))
    print(json.dumps(found), flush=True)


if __name__ == "__main__":
    main()
