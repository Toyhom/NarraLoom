"""One model registry for services, creation workers and replaceable agent providers."""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = {
    "roleplay": ("Qwen/Qwen3-8B", ""),
    "vision": ("Qwen/Qwen3-VL-4B-Instruct", "ebb281ec70b05090aa6165b016eac8ec08e71b17"),
    "image": ("black-forest-labs/FLUX.2-klein-4B", "e7b7dc27f91deacad38e78976d1f2b499d76a294"),
    "image_edit": ("Qwen/Qwen-Image-Edit-2511", "6f3ccc0b56e431dc6a0c2b2039706d7d26f22cb9"),
    "mesh": ("VAST-AI/AniGen", "53af954e283b42fcd8d3739a43514196f8093d10"),
    "voice_design": ("Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", "5ecdb67327fd37bb2e042aab12ff7391903235d3"),
    "tts": ("FunAudioLLM/Fun-CosyVoice3-0.5B-2512", "29e01c4e8d000f4bcd70751be16fa94bf3d85a18"),
    "asr": ("openai/whisper-small", "973afd24965f72e36ca33b3055d56a652f456b4d"),
    "audio_face": ("dlp3d/audio2face", "unitalker-v0.4.0/unitalker_v0.4.0_base.onnx"),
    "face_landmarker": ("google/mediapipe/face_landmarker", "float16-1/face_landmarker.task"),
    "segmentation": ("rembg", "birefnet-general.onnx"),
    "normals": ("VAST-AI/AniGen", "53af954e283b42fcd8d3739a43514196f8093d10/ckpts/dsine"),
    "dinov2": ("VAST-AI/AniGen", "53af954e283b42fcd8d3739a43514196f8093d10/ckpts/dinov2"),
    "voice_clone": ("Qwen/Qwen3-TTS-12Hz-1.7B-Base", "fd4b254389122332181a7c3db7f27e918eec64e3"),
}


def configuration():
    path = os.environ.get("AVATAR_MODELS_CONFIG")
    return json.loads(Path(path).expanduser().read_text()) if path else {}


def model_path(role, *, root=None, check=False):
    config = configuration().get("models", {})
    override = os.environ.get("AVATAR_" + role.upper() + "_MODEL_PATH") or config.get(role, {}).get("path")
    base = Path(root or os.environ.get("AVATAR_MODEL_ROOT", ROOT / "models")).expanduser()
    entry = config.get(role, {})
    repo, revision = DEFAULTS.get(role, ("", ""))
    repo, revision = entry.get("repo", repo), entry.get("revision", revision)
    path = Path(os.path.expandvars(override)).expanduser() if override else base / repo / revision
    if check and not path.exists():
        raise FileNotFoundError(f"Model {role} is not installed at {path}")
    return path.resolve()


PROVIDERS = {
    "local": {"backend": "local", "url": "http://127.0.0.1:18110", "api_key_env": "AVATAR_LLM_API_KEY"},
    "openai": {"backend": "openai", "url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"},
    "deepseek": {
        "backend": "openai",
        "url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "backend": "openai",
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
    },
    "anthropic": {
        "backend": "anthropic",
        "url": "https://api.anthropic.com/v1",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "openai-compatible": {
        "backend": "openai",
        "url": "http://127.0.0.1:8000/v1",
        "api_key_env": "AVATAR_LLM_API_KEY",
    },
}
for provider_name, provider_settings in PROVIDERS.items():
    provider_settings["require_key"] = provider_name not in {"local", "openai-compatible"}
PROVIDERS["claude"] = PROVIDERS["anthropic"]


def agent_config(role):
    config = configuration()
    agents = config.get("agents", {})
    providers = {**PROVIDERS, **config.get("providers", {})}
    value = {
        "backend": os.environ.get("AVATAR_LLM_BACKEND", "local"),
        "url": os.environ.get("AVATAR_LLM_URL", "http://127.0.0.1:18110"),
        "model": os.environ.get("AVATAR_LLM_MODEL", "Qwen3-8B"),
        "api_key_env": "AVATAR_LLM_API_KEY",
        "generation": {},
    }
    for layer in (agents.get("default", {}), agents.get(role, {})):
        if "provider" in layer:
            provider = layer["provider"]
            if provider not in providers:
                raise ValueError(f"Unknown model provider: {provider}")
            if provider != value.get("provider"):
                # A provider switch starts with its own routing and protocol settings.
                value = {
                    "api_key_env": "AVATAR_LLM_API_KEY", "require_key": True,
                    **providers[provider], "model": providers[provider].get("model", ""),
                    "generation": {}, "extra_body": {},
                }
        for name in ("generation", "extra_body"):
            value[name] = {**value.get(name, {}), **layer.get(name, {})}
        value.update({k: v for k, v in layer.items() if k not in {"generation", "extra_body"}})
    if value["backend"] not in {"local", "openai", "anthropic", "openai-responses"}:
        raise ValueError(f"Unsupported provider protocol: {value['backend']}")
    if value["backend"] != "local" and not value["model"]:
        raise ValueError(f"Set agents.{role}.model for the selected provider")
    return value


def configured_path(value):
    path = Path(os.path.expandvars(value)).expanduser()
    if not path.is_absolute():
        config = os.environ.get("AVATAR_MODELS_CONFIG")
        path = (Path(config).resolve().parent if config else Path.cwd()) / path
    return path.resolve()


def prompt_text(name, default=""):
    entry = configuration().get("prompts", {}).get(name)
    if isinstance(entry, str):
        return entry
    if entry:
        return configured_path(entry["file"]).read_text(encoding="utf-8")
    path = Path(__file__).parent / "prompt_templates" / (name + ".txt")
    return path.read_text(encoding="utf-8").strip() if path.is_file() else default


def model_options(role):
    return configuration().get("models", {}).get(role, {})
