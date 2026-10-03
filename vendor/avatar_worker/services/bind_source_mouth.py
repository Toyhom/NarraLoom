"""Bind the source lip contour and one generated cavity as continuously warped layers.

The neutral outline always comes from the same image. No independent rounded or
smiling lip textures are mixed, and no closed line is composited across a cavity.
"""

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def build(package: Path):
    folder = package / "puppet"
    rig = json.loads((folder / "rig.json").read_text())
    old = rig["mouth_binding"]
    if old.get("method") == "source-lip-warp-v3":
        raise ValueError("Already bound; rebuild from the keypose atlas first")
    source_hash = hashlib.sha256((folder / "portrait.png").read_bytes()).hexdigest()
    if old.get("source_sha256") != source_hash:
        raise ValueError("Source portrait changed; regenerate its keypose binding first")
    original = Image.open(folder / "portrait.png").convert("RGBA")
    canonical = original.copy()
    atlas = Image.open(folder / old["atlas"]).convert("RGBA")
    ox, oy, ow, oh = old["roi_px"]
    if old["missing_source_mouth_repaired"]:
        canonical.alpha_composite(
            atlas.crop((0, 0, 192, 192)).resize((round(ow), round(oh))), (round(ox), round(oy))
        )
        cx, cy = np.array(rig["landmarks"]["mouth"]) * original.size
        width = rig["mouth_width_px"]
        x0, x1 = cx - width * 0.5, cx + width * 0.5
        ymin, ymax = cy - width * 0.16, cy + width * 0.16
    else:
        lip = np.array(rig["landmarks"]["contours"]["lip_outer"]) * original.size
        x0, x1 = lip[[0, 6], 0]
        width = x1 - x0
        ymin, ymax = lip[:, 1].min() - width * 0.06, lip[:, 1].max() + width * 0.06
    # Locate the connected drawn lip, including its true corners. A humanoid
    # landmark window can miss a creature's lip by several pixels.
    gray = cv2.cvtColor(np.array(canonical.convert("RGB")), cv2.COLOR_RGB2GRAY).astype(np.float32)
    cx = (x0 + x1) / 2
    guess_y = (ymin + ymax) / 2
    left = max(0, int(cx - width * 0.7))
    right = min(original.width, int(cx + width * 0.7) + 1)
    top = max(0, int(guess_y - width * 0.28))
    bottom = min(original.height, int(guess_y + width * 0.38) + 1)
    search = gray[top:bottom, left:right]
    if old["missing_source_mouth_repaired"]:
        mask = (search < np.median(search) - 32).astype(np.uint8)
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
        candidates = [
            i
            for i in range(1, count)
            if stats[i, cv2.CC_STAT_WIDTH] > width * 0.7 and stats[i, cv2.CC_STAT_HEIGHT] < width * 0.45
        ]
        if not candidates:
            raise ValueError("No connected source lip line; manual binding needed")
        component = min(candidates, key=lambda i: abs(centroids[i][1] + top - guess_y))
        yy, xx = np.where(labels == component)
        x0, x1 = float(xx.min() + left), float(xx.max() + left)
        width = x1 - x0
        xs = np.arange(int(x0), int(x1) + 1)
        ys = np.array([np.median(yy[xx == x - left]) + top for x in xs])
    else:
        # Skin illumination varies across a face. An absolute dark threshold
        # would truncate the brighter half of a softly painted lip.
        xs = np.arange(int(x0), int(x1) + 1)
        ys = np.array([float(np.argmin(gray[int(ymin) : int(ymax) + 1, x]) + int(ymin)) for x in xs])
    ys = cv2.GaussianBlur(ys.reshape(1, -1), (5, 1), 1).ravel()
    curve_x = np.linspace(x0, x1, 33)
    curve_y = np.interp(curve_x, xs, ys)
    cy = float(np.mean(curve_y))
    cx = float((x0 + x1) / 2)
    rx, ry = max(0, int(cx - width * 0.85)), max(0, int(cy - width * 0.65))
    rw, rh = min(original.width - rx, int(width * 1.7) + 2), min(original.height - ry, int(width * 1.3) + 2)
    neutral = canonical.crop((rx, ry, rx + rw, ry + rh)).resize((192, 192), Image.Resampling.LANCZOS)
    # Extract the cavity from one actual generated AH pose. Thresholding locates
    # its dark interior; contour ownership remains with the source image above.
    opened = np.array(atlas.crop((7 * 192, 0, 8 * 192, 192)).convert("RGB"))
    luminance = cv2.cvtColor(opened, cv2.COLOR_RGB2GRAY)
    mask = (luminance < 65).astype(np.uint8)
    mask[:24] = 0
    mask[168:] = 0
    mask[:, :24] = 0
    mask[:, 168:] = 0
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    candidates = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] > 15]
    if not candidates:
        raise ValueError("No measurable generated mouth cavity")
    component = max(candidates, key=lambda i: stats[i, cv2.CC_STAT_AREA])
    x, y, w, h, _ = stats[component]
    cavity = (
        Image.fromarray(opened)
        .crop((x + w * 0.14, y + h * 0.10, x + w * 0.86, y + h * 0.92))
        .resize((192, 192), Image.Resampling.LANCZOS)
        .convert("RGBA")
    )
    packed = Image.new("RGBA", (384, 192))
    packed.paste(neutral, (0, 0))
    packed.paste(cavity, (192, 0))
    packed.save(folder / "mouth-atlas.png")
    rig["version"] = 3
    rig["mouth_binding"] = {
        "method": "source-lip-warp-v3",
        "atlas": "mouth-atlas.png",
        "roi_px": [rx, ry, rw, rh],
        "tile_size": 192,
        "jaw_steps": 0,
        "round_steps": 0,
        "smile_steps": 0,
        "lip_x_px": [float(x0), float(x1)],
        "lip_curve_y_px": curve_y.tolist(),
        "max_open_px": float(width * 0.34),
        "source_sha256": source_hash,
        "missing_source_mouth_repaired": old["missing_source_mouth_repaired"],
        "source_mouth_contrast": old["source_mouth_contrast"],
        "model": old["model"],
        "cavity_crop_px": [int(x), int(y), int(w), int(h)],
    }
    rig["landmarks"]["mouth"] = [cx / original.width, cy / original.height]
    rig["mouth_width_px"] = float(width)
    rig["provenance"]["mouth_keyposes"] = (
        "Source ink contour + one FLUX AH cavity; continuous inverse lip/skin warp, no keypose crossfade"
    )
    (folder / "rig.json").write_text(json.dumps(rig, ensure_ascii=False, indent=2))
    print("SOURCE_LIP_BOUND", package.name, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--package", type=Path, required=True)
    build(p.parse_args().package)
