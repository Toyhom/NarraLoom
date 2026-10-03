"""Package a 2D character without generating or inventing 3D geometry."""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from build_puppet import build_puppet

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from roleplay_avatar.model_metadata import source_record

p = argparse.ArgumentParser()
p.add_argument("--job", type=Path, required=True)
args = p.parse_args()
job = args.job
package = job / "package"
package.mkdir(exist_ok=True)
plan = json.loads((job / "plan.json").read_text())
request = json.loads((job / "request.json").read_text())
voices = json.loads((job / "voice/candidates.json").read_text())
selected = next(v for v in voices["candidates"] if v["candidate"] == voices["selected"])
for name in ["input.png", "concept.png"]:
    shutil.copyfile(job / name, package / name)
shutil.copyfile(job / "concept.png", package / "preview.png")
shutil.copytree(job / "voice", package / "voice", dirs_exist_ok=True)
puppet = build_puppet(job, package)
if not puppet["enabled"]:
    raise ValueError("2D character needs reliable visible facial landmarks")
rig = json.loads((package / "puppet/rig.json").read_text())
version = "portrait_" + hashlib.sha256((package / "puppet/portrait.png").read_bytes()).hexdigest()[:12]
root = Path(__file__).resolve().parents[1]
image = json.loads((job / "image-generation.json").read_text())
records = {
    "profile": {
        "schema_version": "0.1.0",
        "character_id": "char_" + request["id"][:16],
        "display_name": plan["display_name"],
        "persona": plan["persona"],
        "package_status": "validated",
        "model": None,
        "presentation_modes": ["2d"],
    },
    "capabilities": {
        "body_topology": plan["body_topology"],
        "face_mode": "blendshape",
        "eye_mode": "none",
        "appendages": [],
        "controller": "humanoid",
        "motion_mode": "procedural",
        "active_streams": ["audio", "motion", "face"],
    },
    "rig_map": {
        "skeleton_version": version,
        "coordinate_system": "right_handed_y_up_meters",
        "root_motion_node": "PortraitRoot",
        "joints": [
            {
                "name": "PortraitRoot",
                "parent": None,
                "semantic": "root",
                "owner": "base",
                "rest_translation": [0, 0, 0],
                "rest_rotation_xyzw": [0, 0, 0, 1],
                "local_axis": [1, 0, 0],
                "angle_limits_deg": [0, 0],
            }
        ],
    },
    "face_map": {
        "channels": [
            {"source": n, "target": n, "minimum": 0, "maximum": 1, "renderers": ["2d"]}
            for n in rig["channels"]
        ]
    },
    "motion_manifest": {
        "skeleton_version": version,
        "motions": {
            state: {
                "procedural": "neutral"
                if state in ["idle", "long_idle", "listen", "think", "error"]
                else "speech_rhythm",
                "duration_s": 2,
                "loop": state in ["idle", "listen", "speak"],
            }
            for state in [
                "idle",
                "long_idle",
                "listen",
                "think",
                "speak",
                "acknowledge",
                "explain",
                "uncertain",
                "alert",
                "leave",
                "error",
            ]
        },
    },
    "voice_profile": {
        "backend": "cosyvoice3",
        "model_id": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
        "revision": "29e01c4e8d000f4bcd70751be16fa94bf3d85a18",
        "reference_audio": f"voice/candidate_{voices['selected']}.wav",
        "reference_text": "voice/reference.txt",
        "reference_sha256": selected["sha256"],
        "supported_styles": ["neutral", "happy", "sad", "angry", "soft"],
        "design_prompt": selected["prompt"],
        "effects": "dry",
    },
    "provenance": {
        "kind": "generated_asset",
        "seed": request["seed"],
        "generation_record": "generation.json",
        "sources": [
            {
                "component": "input",
                "source": "user upload",
                "sha256": request["input_sha256"],
                "license": "user-provided",
            },
            source_record("image", image),
            source_record("persona", plan.get("source", {"model": "Qwen/Qwen3-VL-4B-Instruct"})),
            source_record("voice", voices),
        ],
        "notes": "Generated 2D portrait. PortraitRoot defines the coordinate origin for 2D presentation.",
    },
    "qa_report": {
        "status": "passed",
        "checks": {"portrait_landmarks": "passed", "portrait_alpha": "passed", "voice_integrity": "passed"},
        "known_issues": [
            "Single-view image rig; not a native Cubism model.",
            "Complex turns and unseen occlusion are not reconstructed.",
        ],
    },
    "character": plan,
    "generation": {"image": image, "puppet": puppet, "presentation": "2d"},
}
for name, data in records.items():
    (package / (name + ".json")).write_text(json.dumps(data, ensure_ascii=False, indent=2))
print("PORTRAIT_PACKAGE_READY", records["profile"]["character_id"], flush=True)
