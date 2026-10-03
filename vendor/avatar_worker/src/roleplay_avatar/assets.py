"""Read explicit character packages, without assuming a humanoid skeleton."""

import hashlib
import json
import math
from pathlib import Path

from PIL import Image

from .contracts import CharacterPackage

FILES = (
    "profile",
    "capabilities",
    "rig_map",
    "face_map",
    "motion_manifest",
    "voice_profile",
    "provenance",
    "qa_report",
)


def inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError(f"asset path escapes package: {relative}")
    return path


def cubism_files(root: Path, manifest: str) -> set[str]:
    """Allow only model-declared local files, including motions and textures."""
    parent = Path(manifest).parent
    data = json.loads(inside(root, manifest).read_text())
    if (
        not isinstance(data, dict)
        or data.get("Version") != 3
        or not isinstance(data.get("FileReferences"), dict)
        or not isinstance(data["FileReferences"].get("Moc"), str)
    ):
        raise ValueError("invalid Cubism manifest")
    files = {manifest}

    def walk(value):
        if isinstance(value, str):
            relative = (parent / value).as_posix()
            relative = inside(root, relative).relative_to(root.resolve()).as_posix()
            if not relative.startswith("live2d/"):
                raise ValueError("Cubism files must stay inside live2d")
            files.add(relative)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key not in {"Name", "FadeInTime", "FadeOutTime"}:
                    walk(item)

    walk(data["FileReferences"])
    return files


def load_package(root: Path, require_assets: bool = False) -> CharacterPackage:
    package = CharacterPackage.model_validate(
        {key: json.loads((root / f"{key}.json").read_text(encoding="utf-8")) for key in FILES}
    )
    paths = [package.profile.model] if package.profile.model else []
    portrait = "2d" in package.profile.presentation_modes and package.profile.renderer_2d == "portrait"
    if package.profile.renderer_2d == "cubism":
        paths += sorted(cubism_files(root, package.profile.live2d_model))
    if portrait:
        paths += ["puppet/portrait.png", "puppet/rig.json"]
    paths += [m.file for m in package.motion_manifest.motions.values() if m.file]
    voice = package.voice_profile
    paths += [p for p in (voice.reference_audio, voice.reference_text) if p]
    if package.provenance.generation_record:
        paths.append(package.provenance.generation_record)
    for name in paths:
        path = inside(root, name)
        if require_assets and not path.is_file():
            raise ValueError(f"missing asset: {name}")
    if require_assets:
        if portrait:
            rig = json.loads(inside(root, "puppet/rig.json").read_text())
            if rig.get("renderer") != "deformable-portrait" or rig.get("image") != "portrait.png":
                raise ValueError("unsupported 2D rig")
        if package.profile.package_status == "template_only":
            raise ValueError("template_only is not a playable 3D asset")
        if portrait and rig.get("mouth_binding"):
            binding = rig["mouth_binding"]
            if (
                binding.get("atlas") != "mouth-atlas.png"
                or not inside(root, "puppet/mouth-atlas.png").is_file()
            ):
                raise ValueError("missing mouth atlas")
            portrait_path = inside(root, "puppet/portrait.png")
            if hashlib.sha256(portrait_path.read_bytes()).hexdigest() != binding.get("source_sha256"):
                raise ValueError("mouth atlas belongs to a different portrait")
            with Image.open(portrait_path) as image:
                width, height = image.size
                image.verify()
            roi = binding.get("roi_px", [])
            if (
                len(roi) != 4
                or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in roi)
                or min(roi[:2]) < 0
                or min(roi[2:]) <= 0
                or roi[0] + roi[2] > width
                or roi[1] + roi[3] > height
            ):
                raise ValueError("mouth replacement region is outside the portrait")
            source_lip = binding.get("method") == "source-lip-warp-v3"
            layout = [binding.get(k) for k in ("tile_size", "jaw_steps", "round_steps", "smile_steps")]
            if layout != ([192, 0, 0, 0] if source_lip else [192, 8, 3, 2]):
                raise ValueError("unsupported mouth atlas layout")
            if source_lip:
                curve = binding.get("lip_curve_y_px", [])
                bounds = binding.get("lip_x_px", [])
                if (
                    len(curve) != 33
                    or len(bounds) != 2
                    or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in [*curve, *bounds])
                    or not roi[0] <= bounds[0] < bounds[1] <= roi[0] + roi[2]
                    or not all(roi[1] <= y <= roi[1] + roi[3] for y in curve)
                    or not isinstance(binding.get("max_open_px"), (int, float))
                    or not 0 < binding["max_open_px"] < roi[3]
                ):
                    raise ValueError("invalid source lip geometry")
            with Image.open(inside(root, "puppet/mouth-atlas.png")) as image:
                if image.size != ((384, 192) if source_lip else (1536, 1152)) or image.mode != "RGBA":
                    raise ValueError("invalid mouth atlas image")
                image.verify()
            if not inside(root, "puppet/mouth-generation.json").is_file():
                raise ValueError("mouth generation record missing")
        if package.qa_report.status != "passed" or any(
            state != "passed" for state in package.qa_report.checks.values()
        ):
            raise ValueError("all asset QA checks must pass")
        if not voice.reference_audio:
            raise ValueError("real voice reference is not prepared")
        actual = hashlib.sha256(inside(root, voice.reference_audio).read_bytes()).hexdigest()
        if actual != voice.reference_sha256:
            raise ValueError("reference audio hash mismatch")
    return package


def catalog(root: Path) -> dict[str, CharacterPackage]:
    result = {}
    if not root.is_dir():
        return result
    for path in sorted(root.iterdir()):
        if not path.name.startswith(".") and path.is_dir() and (path / "profile.json").is_file():
            package = load_package(path)
            key = package.profile.character_id
            if key in result:
                raise ValueError(f"duplicate character_id: {key}")
            result[key] = package
    return result
