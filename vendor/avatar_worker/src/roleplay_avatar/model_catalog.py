"""Hardware guidance, pinned model downloads and reusable deployment configurations."""

import fnmatch
import hashlib
import json
import os
from pathlib import Path

DATA = Path(__file__).parent / "data/models.json"
PRESETS = {
    "compact": {"roleplay": "qwen3-4b", "asr": "whisper-small", "tts": "cosyvoice3"},
    "balanced": {"roleplay": "qwen3-8b", "asr": "whisper-large-v3-turbo", "tts": "cosyvoice3"},
    "quality": {"roleplay": "qwen3-32b", "asr": "whisper-large-v3", "tts": "cosyvoice3"},
    "showcase": {"roleplay": "coser-70b", "asr": "whisper-large-v3-turbo", "tts": "cosyvoice3"},
}
CREATION = {"vision": "qwen3-vl-4b", "image": "flux2-klein-4b", "voice_design": "qwen-voice-design"}


def catalog():
    return json.loads(DATA.read_text())["models"]


def selected_models(selection, creation=False):
    models = catalog()
    if selection in models:
        return {models[selection]["role"]: selection}
    if selection not in PRESETS:
        raise ValueError(f"Unknown model or preset: {selection}")
    selected = dict(PRESETS[selection])
    if selection == "showcase":
        selected["controller"] = "qwen3-8b"
    if creation:
        selected.update(CREATION)
        if selection in {"quality", "showcase"}:
            selected["vision"] = "qwen3-vl-32b"
            selected["image_edit"] = "qwen-image-edit-2511"
    return selected


def recommend(vram_gib, gpus=1):
    if gpus >= 3 and vram_gib >= 80:
        preset = "showcase"
    elif gpus >= 2 and vram_gib >= 80:
        preset = "quality"
    elif vram_gib >= 40:
        preset = "balanced"
    elif vram_gib >= 24:
        preset = "compact"
    else:
        return {
            "preset": "api",
            "reason": "Use hosted LLMs; run speech on a separate service or device.",
            "preview": "CPU replay runs without model downloads.",
        }
    return {
        "preset": preset,
        "models": selected_models(preset),
        "reason": "Budget for concurrent chat, speech and ASR. Character creation runs as a separate job.",
    }


def download_plan(selection, root, endpoint, creation=False):
    entries = catalog()
    result = []
    for role, name in selected_models(selection, creation).items():
        entry = entries[name]
        result.append(
            {
                **entry,
                "role": role,
                "id": name,
                "path": str(Path(root).expanduser().resolve() / entry["repo"] / entry["revision"]),
                "endpoint": endpoint,
            }
        )
    return result


def patterns(entry):
    if entry.get("layout") == "diffusers":
        return ["*/*", "*.json", "*.md", "LICENSE*", "*.txt", ".gitattributes"]
    if entry.get("layout") == "anigen-inference":
        return ["*.md", "LICENSE*", "ckpts/anigen/*", "ckpts/dinov2/*", "ckpts/dsine/*"]
    # Complete Transformers + CosyVoice runtime files; skip duplicate framework exports.
    return None


def download(entry, *, token_env=None):
    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError:
        raise RuntimeError("Install the download extra: python -m pip install -e '.[download]'") from None
    endpoint = entry["endpoint"]
    # Explicit token selection keeps personal HF tokens away from mirror domains.
    token = os.environ.get(token_env) if token_env else False
    if token_env and not token:
        raise ValueError(f"Set {token_env} before downloading this model")
    api = HfApi(endpoint=endpoint, token=token)
    info = api.model_info(entry["repo"], revision=entry["revision"], files_metadata=True)
    if info.sha != entry["revision"]:
        raise ValueError("Download endpoint returned a different revision")
    path = Path(entry["path"])
    allow = patterns(entry)
    ignore = []
    if entry["adapter"] in {"transformers-causal", "transformers-image-text", "whisper"}:
        ignore = ["*.gguf", "*.h5", "*.msgpack", "*.onnx", "onnx/*", "original/*"]
        if any(item.rfilename.endswith(".safetensors") for item in info.siblings):
            ignore += ["pytorch_model*.bin"]
    snapshot_download(
        entry["repo"],
        revision=entry["revision"],
        endpoint=endpoint,
        token=token,
        local_dir=path,
        allow_patterns=allow,
        ignore_patterns=ignore,
    )
    verified = []
    for item in info.siblings:
        file = path / item.rfilename
        if not file.resolve().is_relative_to(path.resolve()):
            raise ValueError("Invalid snapshot path")
        selected = (allow is None or any(fnmatch.fnmatch(item.rfilename, p) for p in allow)) and not any(
            fnmatch.fnmatch(item.rfilename, p) for p in ignore
        )
        if not selected:
            continue
        if not file.is_file():
            raise ValueError("Missing snapshot file: " + item.rfilename)
        if item.size is not None and file.stat().st_size != item.size:
            raise ValueError("Incorrect file size: " + item.rfilename)
        sha = item.lfs.sha256 if item.lfs else None
        if sha:
            with file.open("rb") as handle:
                actual = hashlib.file_digest(handle, "sha256").hexdigest()
            if actual != sha:
                raise ValueError("SHA256 mismatch: " + item.rfilename)
        verified.append({"file": item.rfilename, "size": item.size, "sha256": sha})
    (path / ".avatar-download.json").write_text(
        json.dumps(
            {
                "repo": entry["repo"],
                "revision": info.sha,
                "endpoint": endpoint,
                "files": verified,
            },
            indent=2,
        )
        + "\n"
    )
    return str(path)


def preset_config(preset, root, creation=False, *, engine=None, inference_python=None):
    plan = download_plan(preset, root, "https://huggingface.co", creation)
    config = {
        "models": {p["role"]: {k: p[k] for k in ("path", "repo", "revision", "adapter")} for p in plan},
        "agents": {"default": {"provider": "local"}},
        "prompts": {},
    }
    if preset == "showcase":
        config["agents"].update(
            {
                "default": {"provider": "local", "url": "http://127.0.0.1:18110", "model": "Qwen3-8B"},
                "roleplay": {
                    "provider": "local",
                    "url": "http://127.0.0.1:18112",
                    "model": "CoSER-70B",
                    "output_mode": "actor_director",
                    "generation": {"temperature": 0.7, "top_p": 0.9, "max_tokens": 280,
                                   "repetition_penalty": 1.05},
                },
            }
        )
        config["models"]["roleplay"].update(device_map="balanced", context=8192)
    if engine:
        from .inference import EngineConfig, launch_plan

        config["inference"] = {}
        roles = ["controller", "roleplay"] if preset == "showcase" else ["roleplay"]
        for role in roles:
            if role not in config["models"]:
                raise ValueError("An inference engine preset needs a roleplay model")
            entry = {
                "engine": engine, "served_model": "avatar-" + role,
                "port": 18112 if role == "roleplay" and preset == "showcase" else 18110,
                "context": 8192, "tensor_parallel": 2 if preset == "showcase" and role == "roleplay" else 1,
                "gpu_memory_utilization": 0.9 if preset in {"quality", "showcase"} and role == "roleplay" else 0.5,
                "max_sequences": 4, "max_batch_tokens": 2048, "prefix_caching": True, "chunked_prefill": True,
            }
            if "qwen3" in config["models"][role]["repo"].lower():
                entry["template_kwargs"] = {"enable_thinking": False}
            if inference_python:
                entry["python"] = inference_python
            if engine == "vllm":
                entry["extra_args"] = ["--compilation-config", '{"mode":0,"cudagraph_mode":"FULL_DECODE_ONLY"}']
                if entry["tensor_parallel"] > 1:
                    entry["extra_args"].append("--disable-custom-all-reduce")
            config["inference"][role] = entry
            provider = launch_plan(role, config=EngineConfig(**entry), model=config["models"][role]["path"])["agent"]
            key = "roleplay" if preset == "showcase" and role == "roleplay" else "default"
            config["agents"][key].update(provider)
    return config
