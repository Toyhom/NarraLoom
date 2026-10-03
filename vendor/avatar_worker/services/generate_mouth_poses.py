"""Evaluate local image-model mouth keyposes while retaining the source portrait."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.modules["flash_attn"] = None
import torch
from diffusers import Flux2KleinPipeline
from PIL import Image

p = argparse.ArgumentParser()
p.add_argument("--model", required=True)
p.add_argument("--output", type=Path, required=True)
p.add_argument("--package", type=Path, help="Single generated character package")
p.add_argument("--characters", nargs="+", help="Existing character IDs to prepare")
args = p.parse_args()
root = Path(__file__).resolve().parents[1]
args.output.mkdir(parents=True, exist_ok=True)
pipe = Flux2KleinPipeline.from_pretrained(args.model, torch_dtype=torch.bfloat16, local_files_only=True)
pipe.enable_model_cpu_offload()
poses = {
    "closed": "a small clearly visible gently closed mouth with a single clean horizontal lip line BELOW the nose, neutral expression",
    "open": "one naturally open talking mouth saying AH, visible dark oral cavity and subtle upper teeth, relaxed lips",
    "round": "one small rounded talking mouth saying OO, lips gently puckered",
    "smile": "one cheerful smiling mouth, slightly open, a subtle upper row of teeth",
}
packages = [args.package] if args.package else [root / "characters" / cid for cid in (args.characters or [])]
if not packages:
    raise ValueError("Specify --package or --characters")
for package in packages:
    cid = json.loads((package / "profile.json").read_text())["character_id"]
    folder = args.output / cid
    folder.mkdir(exist_ok=True)
    source = package / "puppet"
    rig = json.loads((source / "rig.json").read_text())
    image = Image.open(source / "portrait.png").convert("RGBA")
    background = Image.new("RGBA", image.size, (240, 244, 237, 255))
    background.alpha_composite(image)
    image = background.convert("RGB")
    lm = rig["landmarks"]
    w, h = image.size
    f = lm["face_width"] * w
    cx = lm["mouth"][0] * w
    ey = (lm["left_eye"][1] + lm["right_eye"][1]) / 2 * h
    box = (round(cx - f * 0.85), round(ey - f * 0.6), round(cx + f * 0.85), round(ey + f * 1.1))
    crop = image.crop(box).resize((768, 768), Image.Resampling.LANCZOS)
    crop.save(folder / "reference.png")
    prompts = {}
    for i, (pose, instruction) in enumerate(poses.items()):
        prompt = (
            "Edit only the mouth of this exact character to show "
            + instruction
            + ". Match the exact art style and linework of the reference. Keep the lip contour thin and understated, with no added lipstick, no thick human lips or glossy lip highlights. For an illustrated character keep the mouth in the same flat illustration style. Preserve the nose, eyes, face shape, colors, texture and identity exactly. ONE mouth only. Keep a straight frontal head pose. This is a single close-up face, not a collage. No text, no other changes."
        )
        prompts[pose] = prompt
        with torch.inference_mode():
            result = pipe(
                image=[crop],
                prompt=prompt,
                num_inference_steps=4,
                guidance_scale=1.0,
                generator=torch.Generator(device="cpu").manual_seed(701 + i),
                width=768,
                height=768,
            )
        result.images[0].save(folder / (pose + ".png"))
        print("MOUTH_POSE_READY", cid, pose, flush=True)
    (folder / "record.json").write_text(
        json.dumps(
            {
                "model": "black-forest-labs/FLUX.2-klein-4B",
                "revision": Path(args.model).name,
                "source": "puppet/portrait.png",
                "source_sha256": hashlib.sha256((source / "portrait.png").read_bytes()).hexdigest(),
                "crop_box": box,
                "poses": poses,
                "prompts": prompts,
                "steps": 4,
                "guidance_scale": 1.0,
                "seeds": [701, 702, 703, 704],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
