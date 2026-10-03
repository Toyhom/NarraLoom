"""Image-conditioned full-body concepts through a configurable local image model."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

sys.modules["flash_attn"] = None
import torch
from PIL import Image

from roleplay_avatar.image_runtime import configure_pipeline
from roleplay_avatar.model_metadata import model_metadata
from roleplay_avatar.models import model_options, prompt_text

parser = argparse.ArgumentParser()
parser.add_argument("--model", required=True)
parser.add_argument("--job", type=Path, required=True)
parser.add_argument("--steps", type=int)
args = parser.parse_args()
request = json.loads((args.job / "request.json").read_text())
plan = json.loads((args.job / "plan.json").read_text())
backend = os.environ.get("AVATAR_IMAGE_BACKEND", "flux2")
if backend == "flux2":
    from diffusers import Flux2KleinPipeline

    pipe = Flux2KleinPipeline.from_pretrained(args.model, torch_dtype=torch.bfloat16, local_files_only=True)
    steps = args.steps or 4
    extra = {}
    metadata = model_metadata("image", args.model)
else:
    from diffusers import QwenImageEditPlusPipeline

    pipe = QwenImageEditPlusPipeline.from_pretrained(
        args.model, torch_dtype=torch.bfloat16, local_files_only=True
    )
    steps = args.steps or 30
    extra = {"negative_prompt": " ", "true_cfg_scale": 4.0}
    metadata = model_metadata("image_edit", args.model)
runtime = configure_pipeline(pipe, model_options("image" if backend == "flux2" else "image_edit"))
image = Image.open(args.job / "input.png").convert("RGB")
prompt = (
    "Edit the reference image into a polished, detailed 3D animated character design. "
    "Preserve this exact character's face, hairstyle, colors, outfit and distinctive accessories. "
    "Character notes (identity only, do not illustrate its environment): " + plan["appearance"] + ". "
    "Extend the cropped portrait to show ONE complete full-body character from head to both feet. "
    "Front view, relaxed symmetric A-pose, arms slightly separated from the torso, legs separated. "
    "Centered with generous empty margins, plain light gray studio background, soft even light. "
    "No scenery, no trees, no ground props, no objects touching the body, no text, no collage. "
    "Upgrade sketch lines to smooth volumetric geometry and rich materials suitable for 3D reconstruction."
)
if request.get("presentation", "3d") == "2d":
    prompt = (
        "Create a polished, high-resolution character portrait illustration based on this reference. "
        "Preserve this exact character identity, face, colors, outfit and original artistic style. "
        "Show ONE character from head to waist, front-facing with a relaxed neutral pose. "
        "Both eyes and the single closed mouth must be clearly visible and separate from the nose. "
        "Use clean detailed facial features suitable for expressive 2D animation. "
        "Plain light gray background, generous margin around the head, even lighting. "
        "No props covering the face, no text, no collage. Character details: " + plan["appearance"]
    )
prompt = prompt_text("image_" + request.get("presentation", "3d"), prompt).replace("{appearance}", plan["appearance"])
with torch.inference_mode():
    output = pipe(
        image=[image],
        prompt=prompt,
        num_inference_steps=steps,
        guidance_scale=1.0,
        generator=torch.Generator(device="cpu").manual_seed(request["seed"]),
        width=768,
        height=1024,
        **extra,
    )
output.images[0].save(args.job / "concept.png")
(args.job / "image-generation.json").write_text(
    json.dumps(
        {
            **metadata,
            "runtime": runtime,
            "prompt": prompt,
            "seed": request["seed"],
            "steps": steps,
            "width": 768,
            "height": 1024,
        },
        ensure_ascii=False,
        indent=2,
    )
)
print("CHARACTER_IMAGE_READY", flush=True)
