# Set up optional 2D characters

[English](avatars.md) · [简体中文](zh-CN/avatars.md) · [日本語](ja/avatars.md)

This is an opt-in presentation module. Complete the [text-first quick start](quickstart.md) first; install the components below when adding a portrait.

## Choose what you need

| Feature | Models and hardware |
| --- | --- |
| Generate textual NPCs, worlds and stories | Your configured text model API, or your own inference service; the framework backend runs on CPU |
| Display an imported finished 2D character | `python -m pip install '.[avatar]'`, a CPU backend and a WebGL browser |
| Create a new animated portrait from a reference image | The source worker, local weights below and an NVIDIA CUDA GPU on Linux / WSL2 |

Import a native world package containing a finished portrait, then select it in the world’s character editor. To generate a new portrait, enable **Add an animated 2D portrait (optional)** during world creation, or upload a reference under **Character assets** and bind the result later. Portrait generation runs in the background while text creation and play continue.

## Host requirements

The bundled creator targets **x86-64 Linux or Windows WSL2**, Python **3.11**, an NVIDIA driver compatible with CUDA 12.6 and a CUDA-capable GPU. Use a **24 GiB GPU and 64 GiB system RAM** as a planning starting point for the default 4B image route; actual peaks depend on image size and offload. Stages run sequentially. Lower-memory configurations need their own checks. Reserve roughly **70 GB** for weights, four environments, caches and temporary assets; inspect available space before installation.

Windows users install WSL2 and an NVIDIA Windows driver with WSL support, then run the commands in Ubuntu's shell. `nvidia-smi` inside WSL must see the GPU. Keep the checkout and environments in the Linux filesystem. On macOS, use the CPU [container setup](quickstart.md), import ready portraits, or open the whole framework on a Linux GPU host through an SSH tunnel. The stock creator uses CUDA; an Apple Silicon MPS creator adapter is not included. A remote creator with a separate backend can be integrated through `avatar_factory`; there is no built-in remote-creator URL switch.

For Ubuntu, install these OS libraries before creating the environments:

```bash
sudo apt-get update
sudo apt-get install -y git python3-venv libgomp1 libsndfile1 libportaudio2 sox
```

Install Python 3.11 separately if the OS supplies another version. For example, use a dedicated Conda Python 3.11 environment and use its Python below. On a shared host, follow its environment placement and GPU scheduler rules.

## Model set

| Role | Download | Work |
| --- | --- | --- |
| `vision` | Qwen/Qwen3-VL-4B-Instruct | Understand the reference and create an appearance/personality brief |
| `image` | black-forest-labs/FLUX.2-klein-4B | Portrait and mouth poses; model CPU offload by default |
| `voice_design` | Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign | Voice references required by the current character package |
| `face_landmarker` | MediaPipe Face Landmarker | Facial landmarks on CPU |
| `segmentation` | BiRefNet-general ONNX | Foreground extraction on CPU |

The reference stage plays **silent subtitles and portrait animation**. Its creation package currently also produces voice references, so VoiceDesign is part of this preset. This 2D route skips 3D mesh generation and needs no AniGen, CosyVoice or Whisper weights. Optional Qwen-Image-Edit-2511 can replace portrait expansion through the model configuration; FLUX is still used for mouth poses. [Model paths and adapters](reference/avatars.md) cover customization.

## Download

Run in the checkout's activated backend environment:

```bash
python -m pip install -e '.[avatar,download]'
narraloom models list
narraloom models download avatar-2d --model-root ./models --dry-run
narraloom models download avatar-2d --model-root ./models --mirror
```

Use a larger disk or an existing shared model root instead of `./models` when appropriate. `--mirror` selects **https://hf-mirror.com** for Hugging Face repositories. Omit it for Hugging Face, or use `--endpoint https://your-hf-endpoint.example`. Each model is pinned to a commit. Interrupted downloads resume when rerun; completed files are checked against metadata and weight SHA-256 hashes. FLUX uses the Diffusers layout without the duplicate root weight file. A single role such as `vision` can replace `avatar-2d` in the command. `--dry-run` lists exact destinations without downloads.

The downloader sends no stored Hugging Face token by default. If access requires a token, set it privately and explicitly add `--token-env HF_TOKEN`; this sends it to your selected HF endpoint. Accept any model access terms through the upstream service first.

MediaPipe downloads from Google and BiRefNet from the rembg GitHub release; the HF mirror does not proxy these resources. For another reachable source, write `resource-urls.local.json` mapping `face_landmarker` and/or `segmentation` to your URLs, then pass `--resource-urls resource-urls.local.json`. The expected hashes stay fixed. You can also copy verified files to the paths printed by `--dry-run`; rerunning skips complete auxiliary files. If a model file fails verification, remove the named damaged file and rerun.

## Install and connect the creator

The installer creates **four separate environments** under your chosen root. Existing unrelated environments are preserved. It installs only the 2D dependencies, checks imports and saves each environment's installed package list. Git access is needed for the pinned Qwen3-TTS source. CUDA wheels use the PyTorch index; the HF mirror setting affects model weights, not Python packages.

```bash
python scripts/install_avatar_envs.py --env-root ./.venvs/avatar --dry-run
python scripts/install_avatar_envs.py --env-root ./.venvs/avatar
narraloom models configure avatar-2d --model-root ./models --env-root ./.venvs/avatar --runner local
narraloom models check
narraloom serve --workspace . --web-dist web/dist
```

The installer must be run with Python 3.11, or receive `--python /absolute/path/to/python3.11`. Use `--only vision`, `--only face`, `--only portrait` or `--only qwen` to install one environment. `models check` checks files and executable paths without loading weights; a successful creation validates GPU inference and the final assets.

`models configure` writes `configs/avatar.local.json` and `configs/avatar-models.local.json`, including absolute paths and the current backend interpreter. It preserves existing configuration; edit those files to reuse existing weights/interpreters. `runner: local` serializes jobs on the host's visible GPU. On hosts with GPUQ, select `--runner gpuq` and submit under the project owner. Other schedulers use the executor extension. Restart the backend after changing these files. Source creation uses the checkout as its workspace; independently installed wheels serve imported assets.

## Check a creation

Use a clear, front-facing reference: PNG/JPEG/WebP, at least 128 pixels per side, at most 24 million pixels and 10 MB. Create one portrait, inspect the job status, bind the ready asset to an NPC, and start a scene containing that NPC. The stage should show the portrait and animate when committed dialogue arrives. Check failed stages under `outputs/creations/<job-id>/`; retry the existing job after correcting its environment or resource. GPU queue time and model loading contribute to creation time. Keeping an existing portrait avoids those generation costs during ordinary play.

The download/configuration CLI also works from an installed backend with its `download` extra. The creator environment installer and worker are source-checkout tools. [Roleplay Avatar](https://github.com/Toyhom/RoleplayAvatar) supplies the pinned worker; [NOTICE](../NOTICE.md) records source and model terms.
