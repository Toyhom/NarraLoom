# 快速开始

[English](../quickstart.md) · [简体中文](quickstart.md) · [日本語](../ja/quickstart.md)

世界、故事和**文字 NPC 人设**都可以通过模型 API 生成，框架后端用 CPU 即可。**从参考图创建新的可动 2D 形象**需要额外的本地模型与 CUDA 显卡；**导入成品形象**只需安装 `avatar` 扩展。完整步骤见 [2D 形象配置与模型下载](avatars.md)。

## 选择系统路线

| 电脑系统 | 后端运行方式 | 创建新的 2D 形象 |
| --- | --- | --- |
| Linux | 下方 Python 安装或 Linux 容器 | x86-64 主机、NVIDIA CUDA 和[创建器配置](avatars.md) |
| Windows | WSL2 Ubuntu，或 Docker Desktop 的 Linux 容器 | 在带 NVIDIA 显卡的 WSL2 中配置并执行创建器 |
| macOS，Intel 或 Apple Silicon | Docker Desktop Linux 容器，或远程 Linux 主机 | 使用 Linux NVIDIA 主机；Mac 浏览器可展示成品形象 |

当前后端使用 Linux 写入锁。Windows 可先执行 `wsl --install -d Ubuntu-24.04`，按提示重启，再在 Ubuntu 终端执行 Linux 步骤。浏览器可运行于上述任一系统。

## Linux / WSL2 安装

使用 Python 3.11+ 和 Node.js 20+，在 Linux 终端执行：

```bash
git clone https://github.com/Toyhom/NarraLoom.git
cd NarraLoom
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[avatar]'
npm ci
npm run build
narraloom serve --workspace . --web-dist web/dist
```

打开 **http://localhost:18090**，可选择英文、简体中文或日文。前台服务按 **Ctrl+C** 停止，重复 `narraloom serve` 命令重新启动。参与开发时可安装 `.[dev]` 获取测试工具。

## macOS / Docker Desktop

安装 Git 和 Docker Desktop，启动 Docker，然后在终端执行。Windows PowerShell 在启用 Linux 容器后也可直接使用这些命令：

```bash
git clone https://github.com/Toyhom/NarraLoom.git
cd NarraLoom
docker build -t narraloom .
docker run -d --name narraloom --hostname narraloom -p 127.0.0.1:18090:18090 -v narraloom-workspace:/workspace narraloom
```

打开 **http://localhost:18090**，通过页面配置 API。镜像包含后端、编译后的前端和成品形象支持，命名卷持久保存存档与设置。一个卷只运行一个容器，重建容器时保持相同 hostname。使用 `docker stop narraloom` 停止、`docker start narraloom` 启动、`docker logs --tail 80 narraloom` 查看日志。首次构建需下载 Python/Node 依赖；GPU 创建器另外在 Linux/WSL2 主机配置。

访问 Docker Desktop 宿主机上的模型服务时，用 `http://host.docker.internal:<port>/v1`。容器中的 `127.0.0.1` 指容器自身。Linux Docker 需要在 `docker run` 增加 `--add-host host.docker.internal:host-gateway`，并让模型服务监听可从该接口访问的地址。

## 使用远程 Linux 主机

在服务器安装并启动后，在自己的 Windows、Mac 或 Linux 电脑执行：

```bash
ssh -N -L 18090:127.0.0.1:18090 user@your-server
```

打开 **http://localhost:18090**。保持转发终端运行；Ctrl+C 只关闭隧道，服务器服务继续运行。

## 连接模型

打开 **模型设置 → 基础连接**，输入兼容 OpenAI 的基础 URL、提供商的准确模型 ID 和你的密钥。本地未认证端点可将密钥留空。选择支持的 JSON 模式，保存，然后测试连接。[模型选择](models.md) 说明了各模块绑定和提供商示例。

浏览器的设置属于其会话。对于服务器范围的默认值，将 `configs/models.example.json` 复制为 `configs/models.local.json`，编辑其端点/模型，并在启动后端之前设置由 `api_key_env` 命名的环境变量。重启以重新加载文件设置。当你的提供商要求时，保留基础 URL 的 `/v1`。

## 创建和游玩

1. 选择 **创建我的世界**。选择单个场景、短篇故事或探索冒险，并设置内容语言。
2. 描述设定，可选地描述第一个故事。生成会创建可编辑的地点、角色和大纲，然后检查并试玩故事。
3. 当其当前修订通过时，命名你的玩家并开始。如果报告失败，检查解释，编辑或请求 AI 修订，然后再次测试。
4. 交谈、调查、移动或等待。引擎记录后果。返回世界以创建另一个故事。

可从首页进入内置的《雾港的最后一班船》。社区初始化内容会成为可编辑副本并运行自己的测试。生成与试跑会调用配置的模型，并按提供商标准计费。

## 仅后端

```bash
python -m pip install .
narraloom serve --workspace /path/to/my-game --models-config /path/to/models.local.json
```

打开 **http://localhost:18090/docs** 查看 API，或从项目目录运行 `python examples/headless.py --world 'A quiet reading room' --preset scene --language en`。该示例保存其会话和待处理请求；`--resume` 继续它们。参见[开发者指南](developers.md)。

对于连接失败，检查端点、模型 ID、认证和 JSON 模式。对于故事测试失败，打开作业报告；成功连接仅确认模型协议。[部署指南](deployment.md) 涵盖恢复和备份。

[参考工作台](workspace.md)
