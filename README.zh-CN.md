# NarraLoom · 叙织

[English](README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md)

**织一个世界，让故事在其中发生。**

NarraLoom 是模块化的故事游戏 AI 框架。描述一个设定，即可生成地点、人物，并在同一个世界创建多个故事。玩家通过交谈和行动推动冒险，引擎持续记录知识、物品、时间与行为后果。

可以独立运行 Python 后端、嵌入自己的应用，也可以通过亮色参考前端体验。创作、主持规划、角色对白、叙述和语义判断分别配置模型，支持本地服务、API 和 Python 适配器。

**了解框架：** [功能图览与说明](guides/zh-CN/features.md) · [快速开始](guides/zh-CN/quickstart.md)

https://github.com/user-attachments/assets/5ae7ff20-89c3-4f7e-bf2c-70475e98be9f

[![NarraLoom 参考前端：世界、动态 NPC 与玩家的故事](media/features/zh-CN/play.jpg)](guides/zh-CN/features.md)

## 从这里开始

| 你的目标 | 文档 |
| --- | --- |
| 配置 API 或本地模型，开始体验 | [快速开始](guides/zh-CN/quickstart.md) |
| 请 Codex 或 Claude Code 帮忙部署 | [AI 辅助安装](guides/zh-CN/ai-setup.md) |
| 创作世界、故事和分享包 | [创作者指南](guides/zh-CN/creators.md) |
| 开发自己的前端或游戏 | [开发者指南](guides/zh-CN/developers.md) · [Python SDK](guides/reference/client.md) |
| 替换模型并比较效果 | [研究者指南](guides/zh-CN/research.md) · [模型选择](guides/zh-CN/models.md) |
| 运行服务、备份和排查问题 | [部署指南](guides/zh-CN/deployment.md) |

## 创作、游玩与扩展

- **一个世界，多个故事。** 可生成单场景、短篇故事或探索冒险，编辑设定与大纲；开局前自动检查，并在隔离存档中用模型试跑。
- **持续的行动后果。** 类型化规则管理移动、物品、资源、时钟和自定义状态。事件日志支持回放、历史分支与恢复。
- **各自的角色视角。** NPC 与玩家分别获得自己的知识和可见历史。多人房间支持独立角色、私语和明确确认的交易。
- **可复用的创作内容。** 导出原生世界与故事包，通过自部署书架分享，安装为可编辑副本并用接收者模型重新测试；同时提供基础角色卡与世界书导入。
- **可替换的引擎。** 逐模块配置生成模型，可选 System One/Jev 判断适配器；算术、归属和事件提交由确定性规则处理。
- **Python 玩法模块。** 扩展行动、角色私有与共享状态，配套自动测试、可携带存档和版本固定。
- **可选的动态 NPC。** 为重要人物绑定可携带的 2D 立绘资源，已提交对白驱动表情、动作和无声字幕表演。
- **三语界面。** 支持英文、简体中文和日文，创作者单独选择世界内容的语言。

## 安装

Linux / Windows WSL2 使用 Python 3.11+ 和 Node.js 20+。macOS 与 Docker Desktop 用户见[容器快速开始](guides/zh-CN/quickstart.md)。文字 NPC 可通过模型 API 生成；从图片生成可动形象另需[本地模型与创建环境](guides/zh-CN/avatars.md)，提供国内镜像下载命令。

```bash
git clone https://github.com/Toyhom/NarraLoom.git
cd NarraLoom
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
npm ci
npm run build
narraloom serve --workspace . --web-dist web/dist
```

打开 **http://localhost:18090**，在“模型与用量”中填写服务地址与模型 ID，保存并测试连接，然后选择“创建我的世界”。[快速开始](guides/zh-CN/quickstart.md)还提供纯后端安装和配置文件用法。

Python 分发名为 `roleplay-world`，导入名为 `roleplay_world`，命令为 `narraloom`。原创框架代码采用 [MIT](LICENSE)；第三方来源与资源条款见 [NOTICE](NOTICE.md)。
