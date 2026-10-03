# 快速开始

[English](../quickstart.md) · [简体中文](quickstart.md) · [日本語](../ja/quickstart.md)

基于 API 的配置可在 CPU 机器上运行该框架。本地模型配置将同一后端连接到你的推理服务器。开始时为所有生成模块使用一个能力足够的指令模型；在第一个可运行的故事之后再为不同模块分别配置模型。

## 安装

使用 Python 3.11+，对于参考前端，使用 Node.js 20+：

```bash
git clone https://github.com/Toyhom/NarraLoom.git
cd NarraLoom
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
npm ci
npm run build
narraloom serve --workspace . --web-dist web/dist
```

在 Windows 上，在 PowerShell 中使用 `.venv\Scripts\Activate.ps1` 激活。打开 **http://localhost:18090**。语言选择器提供英语、简体中文和日语。

## 连接模型

打开 **模型与用量**，输入兼容 OpenAI 的基础 URL、提供商的准确模型 ID 和你的密钥。本地未认证端点可将密钥留空。选择支持的 JSON 模式，保存，然后测试连接。[模型选择](models.md) 说明了各模块绑定和提供商示例。

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
