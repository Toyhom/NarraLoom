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

使用 Uvicorn 和单个 worker 来服务这个 ASGI 应用。`AppConfig` 会相对于工作区解析相对路径。显式配置独立于进程范围的 `RPW_*` 路径设置。`model_config={...}` 提供内存中的配置。[架构](../../docs/ARCHITECTURE.md) 说明了写入方所有权和模块边界。

## 使用 HTTP 或 Python

交互式 OpenAPI 文档位于 `/docs`；schema 位于 `/openapi.json`。从 `POST /api/session` 开始，保留 HttpOnly cookie，并在写入时将返回的 CSRF token 作为 `X-CSRF-Token` 发送。浏览器前端应使用同源或同源反向代理。

异步的 `roleplay_world.client.NarraLoomClient` 会处理这些细节。在发送前保存其 `Session` 和每个 `PreparedRequest`。在超时或进程重启后复用已保存的请求，以恢复同一个 job、campaign 或 action。执行重试是显式的。请参阅完整的 [SDK 指南](../../docs/CLIENT.md) 和 [无头示例](../../examples/headless.py)。

自定义前端通过 `GET /api/studio/jobs/{id}` 跟踪创建 job。对于游玩，读取分支视图，使用其 `expected_world_version` 提交 action，并跟踪 action 快照或 SSE 端点。将已提交的叙事和新视图一起显示。稳定的机器可读错误码可区分过期版本、权限失败和模型错误；provider 诊断文本可能保留其源语言。

## 扩展模型

在 `builtin_engines()` 中注册一个 `Engine`，并将 `registry=registry` 传给 `create_app`。它的异步调用会接收配置、生成或决策 payload，以及认证 headers。生成会返回 `text`、`model` 和可选的 `usage`。可选的 `probe` 提供传输特定的健康检查。

`examples/embedded_backend.py` 演示了一个带有确定性 contract fixture 的原生 Python 适配器。你的适配器可以调用本地库或远程服务。将模型提案保持在所提供的 schema 内。[ENGINES](../../docs/ENGINES.md) 描述了能力验证、预算和追踪。

使用 `gateway=` 替换整个 gateway，或使用 `avatar_factory(store)` 提供展示服务。这些 hook 将规范状态提交保留在框架中。新的事件类型和持久化实现需要对核心 contract 和重放测试进行版本化更改。

## 开发参考前端

```bash
python -m pip install -e '.[dev]'
npm ci
npm run dev
```

Vite 将 `/api` 转发到端口 18090 上的后端。使用 `npm run build` 构建。Catalog 键、参数和浏览器偏好由 `npm run test:i18n` 检查。请参阅 [本地化](../../docs/I18N.md)、[contracts](../../docs/CONTRACTS.md) 和 [测试](../../docs/TESTING.md)。
