"""One resumable GPU worker; heavyweight stages use isolated environments sequentially."""

import fcntl
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from roleplay_avatar.creation import read_json, validate_creation_output, write_json
from roleplay_avatar.models import model_path

ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = Path(os.environ.get("AVATAR_WORK_ROOT", ROOT)).resolve()
folder = Path(sys.argv[1]).resolve()
if not folder.is_relative_to(WORK_ROOT / "outputs/creations") or not (folder / "request.json").is_file():
    raise ValueError("Invalid worker request directory")
request = read_json(folder / "request.json")
# Standalone workers share one GPU by default. Keep waiting jobs cancellable
# while avoiding concurrent model loads on that GPU. GPUQ owns cluster placement.
local_lock = None
if os.environ.get("AVATAR_CREATION_RUNNER") == "local":
    local_lock = (folder.parent / "worker.lock").open("a")
    fcntl.flock(local_lock, fcntl.LOCK_EX)
status = read_json(folder / "status.json")
roles = {
    "Qwen/Qwen3-VL-4B-Instruct": "vision",
    "black-forest-labs/FLUX.2-klein-4B": "image",
    "Qwen/Qwen-Image-Edit-2511": "image_edit",
    "VAST-AI/AniGen": "mesh",
    "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign": "voice_design",
    "face_landmarker": "face_landmarker",
}
models = {name: model_path(role) for name, role in roles.items()}
voice_entry = {"repo_id": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"}


def update(stage, progress, state="running", **kwargs):
    if state != "failed":
        status.pop("error", None)
        status.pop("error_type", None)
    status.update(stage=stage, progress=progress, state=state, updated_at=time.time(), **kwargs)
    write_json(folder / "status.json", status)
    print("CREATION_STAGE", stage, progress, flush=True)


stages = [
    (
        "understanding",
        5,
        "AVATAR_VISION_PYTHON",
        "plan_character.py",
        "Qwen/Qwen3-VL-4B-Instruct",
        "plan.json",
    ),
    (
        "illustrating",
        20,
        "AVATAR_VISION_PYTHON",
        "expand_character.py",
        "black-forest-labs/FLUX.2-klein-4B"
        if os.environ.get("AVATAR_IMAGE_BACKEND", "flux2") == "flux2"
        else "Qwen/Qwen-Image-Edit-2511",
        "concept.png",
    ),
    ("modeling", 45, "AVATAR_ASSET_PYTHON", "generate_mesh.py", "VAST-AI/AniGen", "model.glb"),
    (
        "landmarking",
        60,
        "AVATAR_FACE_PYTHON",
        "face_landmarks.py",
        "face_landmarker",
        "face-landmarks-mp.json",
    ),
    ("refining", 65, "AVATAR_ASSET_PYTHON", "refine_face_texture.py", None, "texture-refinement.json"),
    (
        "rigging",
        70,
        "AVATAR_VISION_PYTHON",
        "describe_rig.py",
        "Qwen/Qwen3-VL-4B-Instruct",
        "rig-analysis.json",
    ),
    (
        "voicing",
        78,
        "AVATAR_QWEN_PYTHON",
        "character_voices.py",
        voice_entry["repo_id"],
        "voice/candidates.json",
    ),
]
portrait_only = request.get("presentation", "3d") == "2d"
if portrait_only:
    stages = [stage for stage in stages if stage[0] not in {"modeling", "refining", "rigging"}]
try:
    for stage, progress, environment, script, model, witness in stages:
        if (folder / "cancel").exists():
            raise InterruptedError("cancelled")
        update(stage, progress)
        marker = folder / "stages" / (stage + ".json")
        if marker.is_file() and (folder / witness).is_file():
            continue
        with (folder / f"{stage}.log").open("a") as log:
            subprocess.run(
                [
                    os.environ[environment],
                    str(ROOT / "services" / script),
                    *(["--model", str(models[model])] if model else []),
                    "--job",
                    str(folder),
                ],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
        if not (folder / witness).is_file():
            raise RuntimeError("Worker completed without its output")
        write_json(marker, {"stage": stage, "completed_at": time.time()})
    update("packaging", 94)
    with (folder / "packaging.log").open("a") as log:
        subprocess.run(
            [
                (os.environ.get("AVATAR_PORTRAIT_PYTHON") or os.environ["AVATAR_ASSET_PYTHON"])
                if portrait_only
                else os.environ["AVATAR_ASSET_PYTHON"],
                str(ROOT / "services" / ("package_portrait.py" if portrait_only else "package_character.py")),
                "--job",
                str(folder),
            ],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
    package = folder / "package"
    if "2d" in read_json(package / "profile.json").get("presentation_modes", []):
        update("mouth_design", 96)
        cid = read_json(package / "profile.json")["character_id"]
        pose_record = folder / "mouth-poses" / cid / "record.json"
        if not pose_record.is_file():
            with (folder / "mouth-design.log").open("a") as log:
                subprocess.run(
                    [
                        os.environ["AVATAR_VISION_PYTHON"],
                        str(ROOT / "services/generate_mouth_poses.py"),
                        "--model",
                        str(models["black-forest-labs/FLUX.2-klein-4B"]),
                        "--package",
                        str(package),
                        "--output",
                        str(folder / "mouth-poses"),
                    ],
                    cwd=ROOT,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
        if (folder / "cancel").exists():
            raise InterruptedError("cancelled")
        update("mouth_binding", 98)
        with (folder / "mouth-binding.log").open("a") as log:
            subprocess.run(
                [
                    os.environ["AVATAR_FACE_PYTHON"],
                    str(ROOT / "services/build_mouth_atlas.py"),
                    "--model",
                    str(models["face_landmarker"]),
                    "--package",
                    str(package),
                    "--study",
                    str(folder / "mouth-poses"),
                ],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
            subprocess.run(
                [
                    os.environ["AVATAR_FACE_PYTHON"],
                    str(ROOT / "services/bind_source_mouth.py"),
                    "--package",
                    str(package),
                ],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
        generation = read_json(package / "generation.json")
        generation["mouth_binding"] = read_json(package / "puppet/rig.json")["mouth_binding"]
        write_json(package / "generation.json", generation)
    validate_creation_output(package)
    if (folder / "cancel").exists():
        raise InterruptedError("cancelled")
    cid = "char_" + request["id"][:16]
    target = WORK_ROOT / "characters" / cid
    if not target.exists():
        # Same filesystem: readers never observe a partially copied character package.
        temporary = WORK_ROOT / "characters" / (".pending_" + cid)
        shutil.copytree(package, temporary, dirs_exist_ok=True)
        os.rename(temporary, target)
    update("complete", 100, "ready", character_id=cid)
except InterruptedError:
    update(status["stage"], status["progress"], "cancelled")
except Exception as exc:
    update(
        status["stage"],
        status["progress"],
        "failed",
        error="此步骤未完成。已保留输入与完成的步骤，可修复后继续。",
        error_type=type(exc).__name__,
    )
    raise
