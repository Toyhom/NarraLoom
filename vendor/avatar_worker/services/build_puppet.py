"""Create a portable 2D puppet from generated artwork and measured facial landmarks."""

import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.modules["cupy"] = None
from rembg import new_session, remove

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from roleplay_avatar.models import model_path


def build_puppet(job, package):
    job, package = Path(job), Path(package)
    if not (job / "face-landmarks-mp.json").is_file():
        return {"enabled": False, "reason": "No concept landmark analysis available"}
    found = json.loads((job / "face-landmarks-mp.json").read_text()).get("concept", {})
    if not found.get("landmark_validated"):
        return {"enabled": False, "reason": "No reliable landmarks on the concept image"}
    original = Image.open(job / "concept.png").convert("RGB")
    segmentation = model_path("segmentation", check=True)
    os.environ["U2NET_HOME"] = str(segmentation.parent)
    if segmentation.name != "birefnet-general.onnx":
        raise ValueError("BiRefNet adapter expects a directory containing birefnet-general.onnx")
    cutout = remove(original, session=new_session("birefnet-general", providers=["CPUExecutionProvider"]))
    destination = package / "puppet"
    destination.mkdir(exist_ok=True)
    cutout.save(destination / "portrait.png")
    w, h = original.size
    mouth = np.array(found["mouth"]) * [w, h]
    points = np.array(found.get("mouth_corners", []))
    mouth_width = (
        float(abs(points[1, 0] - points[0, 0]) * w)
        if points.shape == (2, 2)
        else found["face_width"] * w * 0.3
    )
    # Appearance remains in the portrait; a later stage registers generated mouth keyposes.
    ix, iy = np.clip(mouth.astype(int), [0, 0], [w - 1, h - 1])
    pixels = np.asarray(original)
    skin = np.median(pixels[max(0, iy - 20) : max(1, iy - 8), max(0, ix - 12) : min(w, ix + 12)], axis=(0, 1))
    rig = {
        "version": 1,
        "renderer": "deformable-portrait",
        "image": "portrait.png",
        "width": w,
        "height": h,
        "landmarks": found,
        "mouth_width_px": mouth_width,
        "skin_color": [int(x) for x in skin],
        "channels": [
            "jaw_open",
            "mouth_round",
            "mouth_wide",
            "blink",
            "happy",
            "sad",
            "angry",
            "soft",
            "brow_up",
            "eye_squint",
        ],
        "provenance": {
            "art": "generated concept image",
            "segmentation": "BiRefNet general",
            "landmarks": "MediaPipe FaceLandmarker",
            "rig": "bounded image mesh; mouth keypose binding prepared separately; not a Cubism moc3",
        },
    }
    (destination / "rig.json").write_text(json.dumps(rig, ensure_ascii=False, indent=2))
    return {"enabled": True, "renderer": rig["renderer"], "rig": "puppet/rig.json"}
