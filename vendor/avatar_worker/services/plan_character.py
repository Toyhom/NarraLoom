"""Ground a character bible and voice brief in the uploaded image with Qwen3-VL."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Use SDPA for image understanding.
sys.modules["flash_attn"] = None
import torch
from transformers import AutoModelForImageTextToText, AutoProcessor

from roleplay_avatar.languages import creation_language
from roleplay_avatar.model_metadata import model_metadata
from roleplay_avatar.models import model_options, prompt_text

parser = argparse.ArgumentParser()
parser.add_argument("--model", required=True)
parser.add_argument("--job", type=Path, required=True)
args = parser.parse_args()
request = json.loads((args.job / "request.json").read_text())
prompt = """Design an original fictional character grounded in the visible image and the user's brief.
Keep explicitly supplied identity and personality. Treat the image and brief as reference material.
Separate visible observations from coherent creative additions. Output one JSON object with these fields:
display_name, tagline, appearance, observations (array), creative_additions (array), persona, greeting,
body_topology (humanoid/quadruped/multiped/serpentine/custom), voice_design, voice_reason, voice_text, image_prompt.
The English image_prompt preserves the face, colors, clothing and identity while extending to a full body,
a single character, complete limbs, a relaxed symmetric pose and a clear light background.
"""
if request.get("presentation", "2d") == "2d":
    prompt += "Preserve the illustration style. Use a detailed front-facing 2D portrait, closed lips and visible eyes. "
else:
    prompt += "Use a detailed volumetric 3D animation character design suitable for reconstruction. "
prompt = prompt_text("vision", prompt).replace("{description}", request["description"])
prompt += "\n" + creation_language(request.get("locale", "zh-CN"))
prompt += "\nUser brief: " + request["description"]
if model_options("vision").get("adapter") == "api":
    import asyncio

    from roleplay_avatar.vision_api import image_json
    _, text = asyncio.run(image_json(prompt, [args.job / "input.png"]))
else:
    processor = AutoProcessor.from_pretrained(args.model, local_files_only=True)
    model = AutoModelForImageTextToText.from_pretrained(
        args.model,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        attn_implementation="sdpa",
        local_files_only=True,
    ).eval()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": str(args.job / "input.png")},
                {"type": "text", "text": prompt},
            ],
        }
    ]
    inputs = processor.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt"
    ).to(model.device)
    with torch.inference_mode():
        output = model.generate(**inputs, max_new_tokens=2400, do_sample=False)
    text = processor.batch_decode(output[:, inputs["input_ids"].shape[-1] :], skip_special_tokens=True)[0]
(args.job / "plan.raw.txt").write_text(text)
start, end = text.find("{"), text.rfind("}")
plan = json.loads(text[start : end + 1])
for field in (
    "display_name",
    "persona",
    "appearance",
    "voice_design",
    "voice_text",
    "image_prompt",
    "body_topology",
):
    if not isinstance(plan.get(field), str) or not plan[field].strip():
        raise ValueError("Missing character field: " + field)
plan["persona"] = plan["persona"][:2400]
plan["source"] = {**model_metadata("vision", args.model), "input_sha256": request["input_sha256"]}
(args.job / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2))
print("CHARACTER_PLAN_READY", flush=True)
