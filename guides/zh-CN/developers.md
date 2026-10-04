# 使用 NarraLoom 构建

[English](../developers.md) · [简体中文](developers.md) · [日本語](../ja/developers.md)

Python 后端负责创建、会话、模型编排、规则和持久化。React 是同一 HTTP API 的参考客户端。使用 `python -m pip install .` 安装，然后运行 `narraloom serve --workspace /path/to/my-game`。提供 `--models-config` 用于生成，提供 `--web-dist` 以挂载构建好的前端。

## 嵌入后端

```python
from pathlib import Path
from roleplay_world.app import create_app
from roleplay_world.config import AppConfig

app = create_app(config=AppConfig(
    workspace_root=Path("/path/to/my-game"),
    data_root=Path("saves"),
    output_root=Path("diagnostics"),
    models_config=Path("models.local.json"),
))
```

使用 Uvicorn 和单个 worker 来服务这个 ASGI 应用。`AppConfig` 会相对于工作区解析相对路径。显式配置独立于进程范围的 `RPW_*` 路径设置。`model_config={...}` 提供内存中的配置。[架构](../reference/architecture.md) 说明了写入方所有权和模块边界。

## 使用 HTTP 或 Python

交互式 OpenAPI 文档位于 `/docs`；schema 位于 `/openapi.json`。从 `POST /api/session` 开始，保留 HttpOnly cookie，并在写入时将返回的 CSRF token 作为 `X-CSRF-Token` 发送。浏览器前端应使用同源或同源反向代理。

异步的 `roleplay_world.client.NarraLoomClient` 会处理这些细节。在发送前保存其 `Session` 和每个 `PreparedRequest`。在超时或进程重启后复用已保存的请求，以恢复同一个 job、campaign 或 action。执行重试是显式的。请参阅完整的 [SDK 指南](../reference/client.md) 和 [无头示例](../../examples/headless.py)。

自定义前端通过 `GET /api/studio/jobs/{id}` 跟踪创建 job。对于游玩，读取分支视图，使用其 `expected_world_version` 提交 action，并跟踪 action 快照或 SSE 端点。将已提交的叙事和新视图一起显示。稳定的机器可读错误码可区分过期版本、权限失败和模型错误；provider 诊断文本可能保留其源语言。

## 扩展模型

在 `builtin_engines()` 中注册一个 `Engine`，并将 `registry=registry` 传给 `create_app`。它的异步调用会接收配置、生成或决策 payload，以及认证 headers。生成会返回 `text`、`model` 和可选的 `usage`。可选的 `probe` 提供传输特定的健康检查。

`examples/embedded_backend.py` 演示了一个带有确定性 contract fixture 的原生 Python 适配器。你的适配器可以调用本地库或远程服务。将模型提案保持在所提供的 schema 内。[ENGINES](../reference/engines.md) 描述了能力验证、预算和追踪。

使用 `gateway=` 替换整个 gateway，或使用 `avatar_factory(store)` 提供展示服务。这些 hook 将规范状态提交保留在框架中。新的事件类型和持久化实现需要对核心 contract 和重放测试进行版本化更改。

## 扩展数值检定

通过 `create_app(check_registry=...)` 传入 `CheckRegistry`，注册技能、攻击和反击的确定性判定算法。世界会固定引擎 ID、版本和参数。后端内置可配置的多骰求和；[check_engine.py](../../examples/check_engine.py) 展示按成功骰数量判定的骰池插件。

查询 `GET /api/check-engines` 后，可设置 `CreateWorld.check_engine`，或编辑 `WorldBlueprint.check_engine`。内容自动测试会验证所选实现，提交记录保存骰面和结果，供重放、分支及恢复使用。[检定引擎文档](../reference/check-engines.md) 说明注册接口、随机数、版本固定和内容包依赖。

## 添加玩法行动

在 `ActionRegistry` 中注册 `ActionModule`，通过 `create_app(action_registry=...)` 注入后端。模块声明参数类型、公开／角色私有／宿主私有状态、使用固定种子的规则和验收路线。创建世界时设置 `CreateWorld.action_modules`，其故事会继承对应绑定；自然语言规划和 SDK 直接选择行动都经过同一提交流程。

[探索模块示例](../../examples/action_module.py) 展示调查与休息玩法，可直接作为外部插件安装。内容自动测试会运行模块路线；提交后的结果支持回放、分支和备份恢复，读取旧记录时无需安装插件。[行动模块文档](../reference/action-modules.md) 说明回调、角色视角、内容包依赖及自定义前端接入。

## 扩展记忆检索

将 `memory_embedding` 绑定到 `openai_embedding` 本地服务或 API，也可以注册能力为 `embed` 的 Python `Engine`。设置 `memory_policy.mode=hybrid` 后，规划和 NPC 上下文会使用语义召回。自定义前端可调用 `client.recall(...)`，获取保留来源的记忆记录。[记忆接口文档](../reference/memory.md) 说明向量契约、角色视角、预算、缓存及可运行的 Transformers 适配器。

## 开发参考前端

```bash
python -m pip install -e '.[dev]'
npm ci
npm run dev
```

Vite 将 `/api` 转发到端口 18090 上的后端。使用 `npm run build` 构建。Catalog 键、参数和浏览器偏好由 `npm run test:i18n` 检查。请参阅 [本地化](../reference/i18n.md)、[contracts](../reference/contracts.md) 和 [测试](../reference/testing.md)。
