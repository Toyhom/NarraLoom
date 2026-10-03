"""Design distinct voice candidates from the image-grounded character bible."""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from roleplay_avatar.languages import LANGUAGES, VOICE_RECORDING, VOICE_VARIATIONS
from roleplay_avatar.model_metadata import model_metadata

parser = argparse.ArgumentParser()
parser.add_argument("--model", required=True)
parser.add_argument("--job", type=Path, required=True)
args = parser.parse_args()
plan = json.loads((args.job / "plan.json").read_text())
request = json.loads((args.job / "request.json").read_text())
folder = args.job / "voice"
folder.mkdir(exist_ok=True)
model = Qwen3TTSModel.from_pretrained(
    args.model, device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa"
)
records = []
locale = request.get("locale", "zh-CN")
variants = VOICE_VARIATIONS[locale][: request.get("voice_candidates", 5)]

for index, variation in enumerate(variants):
    seed = request["seed"] + index * 17
    instruction = " ".join((plan["voice_design"], variation, VOICE_RECORDING[locale]))
    torch.manual_seed(seed)
    started = time.monotonic()
    waves, rate = model.generate_voice_design(
        text=plan["voice_text"],
        language=LANGUAGES[locale],
        instruct=instruction,
        max_new_tokens=1400,
        do_sample=True,
        temperature=0.8,
    )
    wave = np.asarray(waves[0], dtype=np.float32)
    if wave.ndim != 1 or not np.isfinite(wave).all() or len(wave) < rate * 3:
        raise ValueError("Voice candidate is empty, invalid or too short")
    rms = float(np.sqrt(np.mean(wave**2)))
    if rms < 0.005:
        raise ValueError("Voice candidate is nearly silent")
    path = folder / f"candidate_{index + 1}.wav"
    sf.write(path, wave, rate, subtype="PCM_16")
    records.append(
        {
            "candidate": index + 1,
            "seed": seed,
            "prompt": instruction,
            "text": plan["voice_text"],
            "duration_s": len(wave) / rate,
            "rms": rms,
            "clipping_fraction": float(np.mean(np.abs(wave) >= 0.999)),
            "generation_s": time.monotonic() - started,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )
    print("VOICE_CANDIDATE_READY", index + 1, flush=True)
# Technical recommendation only; the product exposes every candidate for audition.
selected = min(records, key=lambda r: (r["clipping_fraction"], abs(r["rms"] - 0.12)))
(folder / "reference.wav").write_bytes((folder / f"candidate_{selected['candidate']}.wav").read_bytes())
(folder / "reference.txt").write_text(plan["voice_text"], encoding="utf-8")
(folder / "candidates.json").write_text(
    json.dumps(
        {
            "candidates": records,
            "selected": selected["candidate"],
            "selection_method": "signal_quality; user audition available",
            **model_metadata("voice_design", args.model),
        },
        ensure_ascii=False,
        indent=2,
    )
)
