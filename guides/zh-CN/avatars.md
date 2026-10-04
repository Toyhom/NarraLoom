# 配置可选的 2D 角色形象

[English](../avatars.md) · [简体中文](avatars.md) · [日本語](../ja/avatars.md)

## 按需要选择

| 功能 | 模型与硬件 |
| --- | --- |
| 生成文字人设、世界与故事 | 已配置的文本模型 API 或自己的推理服务；框架后端可用 CPU |
| 展示导入的成品 2D 角色 | `python -m pip install '.[avatar]'`、CPU 后端和支持 WebGL 的浏览器 |
| 从参考图创建新的可动立绘 | 源码中的创建器、下表的本地权重，以及 Linux / WSL2 上的 NVIDIA CUDA 显卡 |

导入带成品立绘的原生世界包后，可以把形象绑定给世界角色。创建新形象时，在世界的角色设置中上传参考图，等待创建任务完成，再选择就绪的形象。文字角色与可动形象分别生成。

## 系统与硬件

内置创建器面向 **x86-64 Linux 或 Windows WSL2**，使用 **Python 3.11**、兼容 CUDA 12.6 的 NVIDIA 驱动和显卡。默认 4B 图像路线建议先按 **24 GiB 显存、64 GiB 内存**规划；实际峰值取决于图像尺寸和卸载设置，各阶段依次运行。更小显存需要自行验证。建议为权重、四个环境、缓存及临时素材预留约 **70 GB**，安装前检查目标盘空间。

Windows 用户先安装 WSL2 和支持 WSL 的 NVIDIA Windows 驱动，在 Ubuntu 终端执行后续命令；WSL 内的 `nvidia-smi` 应能看到显卡。代码与环境放在 Linux 文件系统内。macOS 用户可使用[快速开始中的 CPU 容器](quickstart.md)、导入成品立绘，或通过 SSH 转发访问 Linux GPU 服务器上的完整框架。当前创建器使用 CUDA，尚无 Apple Silicon MPS 创建适配器。开发者可用 `avatar_factory` 接入独立远程创建服务；当前没有内置的远程创建 URL 开关。

Ubuntu 先安装这些系统依赖：

```bash
sudo apt-get update
sudo apt-get install -y git python3-venv libgomp1 libsndfile1 libportaudio2 sox
```

若系统 Python 不是 3.11，另装 Python 3.11，例如创建专用的 Conda Python 3.11 环境，再用其解释器执行安装。共享服务器请遵守当地的环境目录与 GPU 调度规定。

## 模型清单

| 角色 | 下载资源 | 用途 |
| --- | --- | --- |
| `vision` | Qwen/Qwen3-VL-4B-Instruct | 理解参考图，生成外貌与人设描述 |
| `image` | black-forest-labs/FLUX.2-klein-4B | 立绘与嘴型，默认启用模型 CPU 卸载 |
| `voice_design` | Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign | 生成当前角色包要求的声音参考 |
| `face_landmarker` | MediaPipe Face Landmarker | CPU 人脸关键点检测 |
| `segmentation` | BiRefNet-general ONNX | CPU 前景分割 |

参考前端采用**无声字幕与立绘动画**。当前创建包仍会生成声音参考，因此预设包含 VoiceDesign。2D 路线跳过三维网格，无需下载 AniGen、CosyVoice 或 Whisper 权重。可通过配置改用 Qwen-Image-Edit-2511 生成立绘；嘴型阶段仍使用 FLUX。替换方法见[形象适配器参考](../reference/avatars.md)。

## 下载模型

在项目目录、已激活的后端环境中运行：

```bash
python -m pip install -e '.[avatar,download]'
narraloom models list
narraloom models download avatar-2d --model-root ./models --dry-run
narraloom models download avatar-2d --model-root ./models --mirror
```

可把 `./models` 换成空间充足的磁盘或现有共享模型目录。`--mirror` 对 Hugging Face 仓库使用国内镜像 **https://hf-mirror.com**；去掉该参数则使用官方站，也可用 `--endpoint https://your-hf-endpoint.example` 指定兼容端点。各模型固定到具体提交，重复命令可续传；下载后校验文件元数据及权重 SHA-256。FLUX 只下载 Diffusers 布局，避免根目录的重复权重。可将 `avatar-2d` 换成 `vision` 等单项角色名。`--dry-run` 只列出准确路径与版本。

默认不发送本机保存的 Hugging Face token。确实需要授权时，私下设置环境变量，并显式增加 `--token-env HF_TOKEN`，凭据会发给所选 HF 端点。需要接受的模型访问条款请先在上游完成。

MediaPipe 来自 Google，BiRefNet 来自 rembg 的 GitHub Release，HF 镜像不代理这两项资源。若连接不通，可创建 `resource-urls.local.json`，将 `face_landmarker` 和/或 `segmentation` 映射到可访问的文件 URL，再增加 `--resource-urls resource-urls.local.json`；固定校验值仍然生效。也可以按 `--dry-run` 的路径放入已校验的文件，重复运行会复用完整辅助文件。模型文件校验失败时，删除报错指出的损坏文件后重试。

## 安装并连接创建器

安装脚本在指定目录下建立**四个独立环境**，保留已有的其他环境。它只安装 2D 所需依赖，检查导入，并记录各环境的已安装包。Qwen3-TTS 固定版本源码需通过 Git 获取；CUDA wheel 来自 PyTorch 下载站。HF 镜像参数只作用于模型权重。

```bash
python scripts/install_avatar_envs.py --env-root ./.venvs/avatar --dry-run
python scripts/install_avatar_envs.py --env-root ./.venvs/avatar
narraloom models configure avatar-2d --model-root ./models --env-root ./.venvs/avatar --runner local
narraloom models check
narraloom serve --workspace . --web-dist web/dist
```

请使用 Python 3.11 运行安装器，或传入 `--python /absolute/path/to/python3.11`。可用 `--only vision`、`--only face`、`--only portrait`、`--only qwen` 单独安装一个环境。`models check` 检查文件与解释器路径，不加载权重；成功创建角色才验证了 GPU 推理与最终素材。

`models configure` 创建 `configs/avatar.local.json` 与 `configs/avatar-models.local.json`，写入绝对路径及当前后端解释器。已有配置会保留，可手动编辑来复用现成权重和环境。`runner: local` 在本机可见显卡上串行运行任务；装有 GPUQ 的共享主机使用 `--runner gpuq`，由项目所属账号提交。其他调度器通过执行器扩展接入。修改配置后重启后端。源码创建器要求以该项目目录作为工作区；独立安装的 wheel 可展示导入的成品形象。

## 验收一次创建

选清晰正脸参考图：PNG/JPEG/WebP，每边至少 128 像素、不超过 2400 万像素和 10 MB。创建一个形象，检查任务状态，将完成的素材绑定给 NPC，并进入包含该 NPC 的场景；确认立绘显示，已提交对白能够驱动动画。失败阶段日志位于 `outputs/creations/<job-id>/`，修正环境或资源后重试已有任务。排队和模型加载计入创建耗时；平时游玩可直接使用已完成形象。

下载与配置命令也包含在安装包中，下载功能使用 `download` 扩展；环境安装器和创建 worker 随源码提供。固定版本 worker 来自 [Roleplay Avatar](https://github.com/Toyhom/RoleplayAvatar)，来源和资源条款见 [NOTICE](../../NOTICE.md)。
