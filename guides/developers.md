# Build with NarraLoom

[English](developers.md) · [简体中文](zh-CN/developers.md) · [日本語](ja/developers.md)

The Python backend owns creation, sessions, model orchestration, rules and persistence. React is a reference client of the same HTTP API. Install with `python -m pip install .`, then run `narraloom serve --workspace /path/to/my-game`. Supply `--models-config` for generation and `--web-dist` to mount a built frontend.

## Embed the backend

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

Serve this ASGI application with Uvicorn and one worker. `AppConfig` resolves relative paths against the workspace. Explicit configuration is independent of process-wide `RPW_*` path settings. `model_config={...}` supplies an in-memory configuration. [Architecture](../docs/ARCHITECTURE.md) explains writer ownership and module boundaries.

## Use HTTP or Python

Interactive OpenAPI documentation is at `/docs`; the schema is at `/openapi.json`. Begin with `POST /api/session`, retain the HttpOnly cookie and send its returned CSRF token as `X-CSRF-Token` on writes. A browser frontend should use the same origin or a same-origin reverse proxy.

The async `roleplay_world.client.NarraLoomClient` handles these details. Save its `Session` and each `PreparedRequest` before sending. Reuse that saved request after a timeout or process restart to recover the same job, campaign or action. Execution retries are explicit. See the complete [SDK guide](../docs/CLIENT.md) and [headless example](../examples/headless.py).

A custom frontend follows creation jobs through `GET /api/studio/jobs/{id}`. For play, read the branch view, submit an action with its `expected_world_version`, and follow the action snapshot or SSE endpoint. Display committed narrative and the new view together. Stable machine-readable error codes distinguish stale versions, permission failures and model errors; provider diagnostic text may retain its source language.

## Extend models

Register an `Engine` in `builtin_engines()` and pass `registry=registry` to `create_app`. Its asynchronous invocation receives configuration, a generation or decision payload, and authentication headers. Generation returns `text`, `model` and optional `usage`. An optional `probe` provides transport-specific health checks.

`examples/embedded_backend.py` demonstrates a native Python adapter with a deterministic contract fixture. Your adapter can call a local library or remote service. Keep model proposals inside the supplied schemas. [ENGINES](../docs/ENGINES.md) describes capability validation, budgets and tracing.

Use `gateway=` to replace the whole gateway, or `avatar_factory(store)` to supply presentation services. These hooks leave canonical state commits in the framework. New event types and persistence implementations require versioned changes to the core contracts and replay tests.

## Extend numerical rules

Pass a `CheckRegistry` as `create_app(check_registry=...)` to register deterministic skill, attack and counterattack implementations. A world pins the engine ID, version and options. The backend includes configurable summed dice; [check_engine.py](../examples/check_engine.py) demonstrates a success-count dice pool.

Inspect `GET /api/check-engines`, then set `CreateWorld.check_engine` or edit `WorldBlueprint.check_engine`. Automatic content tests exercise the selected implementation. Receipts retain dice and outcomes for replay, branch history and recovery. The [check-engine reference](../docs/CHECK_ENGINES.md) covers registration, randomness, versioning and native-package dependencies.

## Work on the reference frontend

```bash
python -m pip install -e '.[dev]'
npm ci
npm run dev
```

Vite forwards `/api` to the backend at port 18090. Build with `npm run build`. Catalog keys, parameters and browser preferences are checked by `npm run test:i18n`. See [localization](../docs/I18N.md), [contracts](../docs/CONTRACTS.md) and [testing](../docs/TESTING.md).
