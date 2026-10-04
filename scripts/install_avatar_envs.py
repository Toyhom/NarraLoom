"""Install the four isolated Linux/WSL2 environments used by the 2D creator."""

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("vision", "face", "portrait", "qwen")
IMPORTS = {
    "vision": "from transformers import AutoModelForImageTextToText; from diffusers import Flux2KleinPipeline",
    "face": "import mediapipe; import cv2; from scipy.spatial import Delaunay",
    "portrait": "from rembg import new_session; import onnxruntime",
    "qwen": "from qwen_tts import Qwen3TTSModel; import soundfile",
}


def install(env_root, base_python, kinds, *, dry_run=False):
    env_root, base_python = Path(env_root).expanduser().resolve(), Path(base_python).expanduser().absolute()
    if not dry_run:
        if sys.platform != "linux" or platform.machine() not in {"x86_64", "AMD64"}:
            raise ValueError("Use an x86-64 Linux or WSL2 host with an NVIDIA GPU")
        subprocess.run([str(base_python), "-c", "import sys; assert sys.version_info[:2] == (3, 11), 'Use Python 3.11'"],
                       check=True)
    # Validate every target before changing any environment.
    for kind in kinds:
        prefix = env_root / kind
        marker = prefix / ".narraloom-avatar-env"
        if prefix.exists() and (not marker.is_file() or marker.read_text().strip() != kind):
            raise ValueError(f"Existing environment is not owned by this installer: {prefix}")
    plan = []
    for kind in kinds:
        prefix = env_root / kind
        py = str(prefix / "bin/python")
        commands = [[py, "-m", "pip", "install", "pip==25.3", "setuptools==79.0.1", "wheel"]]
        if kind in {"vision", "qwen"}:
            commands.append([py, "-m", "pip", "install", "torch==2.8.0", "torchvision==0.23.0",
                             "torchaudio==2.8.0", "--index-url", "https://download.pytorch.org/whl/cu126"])
        commands.append([py, "-m", "pip", "install", "-r", str(ROOT / "requirements/avatar" / (kind + ".txt"))])
        if kind == "face":
            commands.append([py, "-m", "pip", "install", "mediapipe==0.10.21", "--no-deps"])
        commands.append([py, "-c", IMPORTS[kind]])
        plan.append({"kind": kind, "prefix": str(prefix), "commands": commands})
        if dry_run:
            continue
        cache = ROOT / ".cache/avatar-install"
        (cache / "tmp").mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PIP_CACHE_DIR": str(cache / "pip"), "TMPDIR": str(cache / "tmp")}
        if not prefix.exists():
            subprocess.run([str(base_python), "-m", "venv", str(prefix)], check=True, env=env)
            (prefix / ".narraloom-avatar-env").write_text(kind + "\n")
        for command in commands:
            subprocess.run(command, check=True, env=env, cwd=ROOT)
        freeze = subprocess.check_output([py, "-m", "pip", "freeze"], env=env, text=True)
        (prefix / ".narraloom-avatar-installed.txt").write_text(freeze)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable), help="Python 3.11 interpreter")
    parser.add_argument("--only", choices=KINDS, action="append", help="Install selected environments")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.env_root, args.python, args.only or KINDS, dry_run=args.dry_run), indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
