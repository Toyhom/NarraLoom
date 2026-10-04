# 选择和配置模型

[English](../models.md) · [简体中文](models.md) · [日本語](../ja/models.md)

最简单的设置是通过一个 OpenAI 兼容端点使用一个强大的指令模型。DeepSeek 的 `deepseek-flash` 是一个可用的示例；请使用你的提供商所公布的模型 ID。vLLM、SGLang 和 llama.cpp 端点可以通过相同的协议提供本地检查点。

| 模块 | 有用的模型属性 |
| --- | --- |
| `world_builder`、`story_builder`、`import_builder` | 结构化生成、长上下文、连贯的设定和大纲 |
| `rules_builder`、`state_builder`、`simulation_builder` | 可靠的 JSON、条件和因果推理 |
| `content_reviewer`、`game_master` | 强指令遵循能力以及对当前状态的推理 |
| `character_actor`、`narrator` | 以内容语言呈现的角色语气、对话和散文 |
| `world_actor` | 尊重 NPC 知识和可用行动的有界提议 |
| `action_router` | System One 决策协议；在你的行动分布上测量准确率 |
| `memory_embedding` | BGE-M3 等适合内容语言的文本向量模型；支持本地服务、API 和 Python `embed` 适配器。[记忆配置](../reference/memory.md) |
| 确定性规则 | 引擎代码处理骰子、算术、所有权和持久化 |
| Avatar 呈现 | 单独的图像/绑定创建或导入现成资产；参见 [Avatar](../reference/avatars.md) |

更小的对话模型可以降低成本。请将它们的结构化输出和角色行为与主规划器分开评估。通用小型模型通常需要针对世界生成和复杂规则进行更多测试。

## OpenAI 与 Anthropic 原生 API

在**模型与用量**中选择 **API 协议**：OpenAI Chat Completions、OpenAI Responses 或 Anthropic Messages。填写服务地址、账号可用的模型 ID 和 API 密钥，保存后测试。Responses 的服务地址为 `https://api.openai.com/v1`，Messages 为 `https://api.anthropic.com/v1`。命名服务商也支持此选项，可以分别为创作、规划和对话选择服务。

Anthropic 的 **JSON Schema** 模式通过指定工具返回结构化结果；Object 和提示词模式通过提示词请求 JSON。模型要求使用默认采样设置时，勾选**使用模型的默认温度**。[原生协议配置示例](../../configs/models.native.example.json)和[接口说明](../reference/engines.md#generation-protocols)介绍配置文件和服务商参数。

## 服务器配置

将其保存为 `configs/models.local.json`，并在你的 shell 或服务管理器中私下设置 `RPW_API_KEY`：

```json
{
  "default": {
    "url": "https://api.deepseek.com/v1",
    "model": "deepseek-flash",
    "api_key_env": "RPW_API_KEY",
    "json_object": true,
    "timeout_s": 90
  },
  "roles": {
    "world_builder": {"max_tokens": 6000},
    "story_builder": {"max_tokens": 6000}
  }
}
```

对于本地服务，将 `url` 设置为其可访问地址，例如 `http://127.0.0.1:8000/v1`，并使用其提供的模型名称。URL 是从后端主机访问的。每个角色可以有自己的提供商、模型、超时、输出限制和生成参数。`json_object`、`json_schema` 和基于提示的 JSON 取决于提供商支持；所有结果仍会通过运行时验证。

参考前端在 **模型与用量** 下公开命名提供商和模块绑定。在运行模块检查之前保存设置。空白密钥会为同一端点保留已保存的密钥；移除它会使用显式清除控件。[Engine contracts](../reference/engines.md) 描述了部署文件格式和 Python 扩展 API。

## 可选的 System One / Jev

System One 处理类型化的 `choice`、`noul` 和 `score` 问题。捆绑适配器支持 Jev 风格的决策服务器。以 `configs/models.hybrid.example.json` 作为起点，将其绑定到 `action_router`。

路由默认**关闭**。**Shadow** 会记录分类，而主规划器仍处理该回合。**Auto** 可以在概率和边际阈值通过时路由一个显式的单一移动。请先从 shadow 模式开始，并在启用 auto 之前评估否定、歧义、多步行动和语言变化。阈值是模型输出；请在留出案例上测量实际错误。

本地模型内存取决于权重、上下文、量化和并发。请在单独环境中运行可选推理，在共享相同权重的角色之间共享端点，并遵循你主机的 GPU 调度器。常规 API 后端不需要 GPU 或 Torch。固定的 Jev 设置命令位于 [ENGINES](../reference/engines.md)。

[可选 2D 角色：模型依赖、Linux/WSL2 环境与镜像下载](avatars.md)
