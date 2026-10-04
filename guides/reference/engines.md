# Model engines

[Model selection](../models.md) explains useful model properties for each module. The gateway separates generation, semantic decisions, deterministic rules and presentation.

## Bind modules

`configs/models.example.json` supplies one default OpenAI-compatible endpoint. `configs/models.hybrid.example.json` shows named `providers`, per-module `bindings`, deployment revision labels and decision policy. Unbound generation roles inherit the default and `roles` overrides. `action_router` requires an explicit decision binding.

Providers own their credentials. Use `api_key_env` or `api_key_file` inside `secrets_root`. In the browser, save before checking modules; a changed endpoint does not inherit a saved credential. The deployment-file JSON controls are `json_object` / `json_schema`; the settings API uses `json_mode: object|schema|prompt`.

## Generation protocols

Select a transport with `backend` on the default provider or a named provider:

| Backend | Base URL example | Generation path | Authentication |
| --- | --- | --- | --- |
| `openai` | `https://api.deepseek.com/v1` | `/chat/completions` | Bearer key |
| `openai-responses` | `https://api.openai.com/v1` | `/responses` | Bearer key |
| `anthropic` | `https://api.anthropic.com/v1` | `/messages` | `x-api-key`, API version `2023-06-01` |

Use the model ID available in your account or local service. All three transports support independent module bindings and the same validation/repair pipeline. The reference frontend offers the protocol selector for both the default model and named providers.

Responses maps the system prompt to `instructions`, repair history to `input`, token limits to `max_output_tokens`, and JSON settings to `text.format`. Schema mode uses `strict: false` to retain application schemas with defaults, optional fields and dictionaries; the gateway validates the original schema after generation. The adapter requires a completed response and excludes reasoning and refusal blocks from generated content.

Anthropic separates `system` from `messages`. Schema mode requests one forced `emit_result` tool with the application's full input schema and reads its JSON arguments. The adapter returns those arguments for validation. Object and prompt modes request JSON in the system prompt. The response must finish with `message_stop` and a matching stop reason. Token-limit stops, refusals and incomplete streams fail before world state commits. Reported usage retains cache counters and counts input, cache creation and cache reads in total prompt tokens.

Set `generation: {"temperature": null}` to omit temperature for models that require their own sampling defaults. `generation` also supports `top_p`, `seed`, `frequency_penalty` and `presence_penalty` when the selected provider accepts them; a null value omits that parameter. The browser exposes **Use the model’s default temperature**. Provider-specific parameters such as Responses `reasoning` go in `extra_body`. Routing fields, messages, stream settings, token limits and result tools are owned by the gateway. DeepSeek's `thinking` option belongs to the Chat provider and is cleared when switching protocols in the reference frontend.

Example configuration: [models.native.example.json](../../configs/models.native.example.json). `POST /api/engines/{module}/check` exercises the configured protocol and model. Anthropic readiness is established by this generation check; its adapter does not enumerate account models.

Protocol references: [Responses streaming](https://developers.openai.com/api/docs/guides/streaming-responses), [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Messages streaming](https://platform.claude.com/docs/en/build-with-claude/streaming), [Anthropic tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview).

## Python adapters

```python
from roleplay_world.engines import Engine, builtin_engines
from roleplay_world.app import create_app

async def invoke(config, payload, auth_headers):
    # Call your inference library/service and return its serialized JSON output.
    result = await my_model.generate(payload)
    return {"text": result.text, "model": result.model, "usage": result.usage}

registry = builtin_engines()
registry.register(Engine("my_backend", frozenset({"generate"}), invoke))
# Select backend="my_backend" and a model ID in model_config.
app = create_app(registry=registry, model_config=my_configuration)
```

The snippet illustrates the adapter interface; `my_model` and `my_configuration` are supplied by the host. [embedded_backend.py](../../examples/embedded_backend.py) is a runnable deterministic fixture. Native Python backends need no HTTP URL. An optional async `probe(config, auth_headers)` adds transport-specific readiness; otherwise status reports `ready: null, mode: unprobed`.

`invoke(config, payload, auth_headers)` returns generation `{text,model,usage?}` or a System One decision response according to its declared capability. The gateway manages cancellation, timeout, context/output bounds, call/repair budgets, validation and traces. The request's actual schema may be narrowed to the current scene.

`ModelGateway.generate(role, system, data, schema, action_id, budget, validate=None)` and `decide(role, DecisionRequest, action_id, budget)` are asynchronous. Pass a full custom gateway through `create_app(gateway=...)`; `registry` and `gateway` are mutually exclusive.

## System One / Jev

The `systemone` transport calls `/v1/systemone`. A request includes `state` and named questions of type `choice`, `noul` or `score`. Responses must match the exact question/options, contain finite normalized probabilities and select a maximal choice. The framework supports up to 16 questions and 32 options per question, subject to backend limits.

The bundled movement router receives action text and adjacent exit IDs/names. `defer` handles uncertain or unsupported inputs. Modes are `off`, `shadow` and `auto`; default is off. Shadow records a decision while using the planner. Auto accepts a single movement only when both top probability and margin meet thresholds, then uses normal rules and commits. Other actions and failures return to the main planner. Cancellation propagates.

Jev-style is an optional implementation of this protocol. Its pinned source and runtime hashes are in [resources/jev-style-source-pin.json](../../resources/jev-style-source-pin.json). Evaluate your checkpoint in shadow mode before enabling automatic routing. The included small checkpoints require task-specific validation; probabilities alone do not establish accuracy.

### Local setup

Use a dedicated inference environment and model directory:

```bash
python -m pip install '.[jev]'
git clone https://github.com/lawrence3699/jev-style.git third_party/jev-style
git -C third_party/jev-style checkout ef86def93c4b8c775523bea6812784a36b2b6d8a
python scripts/download_jev.py --size 0.8B --model-root /path/to/models
python scripts/serve_jev.py --source third_party/jev-style   --model-root /path/to/models --size 0.8B --port 18110 --max-runtime-s 3600
```

The runner validates the pinned Python source and runtime hashes. `--size 2B` selects the other pinned checkpoint; `--device cpu` is available. On shared GPU hosts, submit this command through the host's scheduler and preserve its assigned CUDA visibility. The runtime limit stops only this optional model service. [Research](../research.md) covers evaluation and generation-model comparisons.

## Memory embeddings

The `embed` capability supplies vectors through a native Python adapter or the `openai_embedding` transport (`POST /embeddings`). An explicit `memory_embedding` binding selects the model. Hybrid recall uses only the current actor's branch records and retains source IDs. See [memory retrieval](memory.md) for configuration, local Transformers inference, caching and read-only recall APIs.

## Diagnostics

`GET /api/engines` describes registered capabilities and effective module metadata. `POST /api/engines/{module}/check` makes a typed test call. `POST /api/decisions/action_router` evaluates a decision without changing a world. Owner-scoped action diagnostics and usage expose model IDs, elapsed time, routing and reported token counts. Raw traces in the configured output directory may include prompts and authored secrets.
