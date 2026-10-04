# Runnable examples

- [headless.py](headless.py): create a world/story, run automatic tests, start a campaign and act through the public Python SDK. Saves sessions and pending requests; `--resume` recovers work and `--retry` explicitly retries execution.
- [embedded_backend.py](embedded_backend.py): embed FastAPI with a custom Python model adapter. The adapter is an explicitly deterministic fixture demonstrating the contracts for one action.
- [decisions/action-routing.jsonl](decisions/action-routing.jsonl): authored Chinese/English diagnostic cases for optional decision routing. Evaluation repeats them with reversed exit order.
- [make_evaluation_cases.py](make_evaluation_cases.py): freeze twelve multilingual planner, NPC and narrator tasks using packaged world data and runtime contracts.
- [evaluation_adapter.py](evaluation_adapter.py): run generation and decision fixtures through a registered Python engine using the installed evaluation API.

- [check_engine.py](check_engine.py): register a deterministic dice pool for skills and combat, verify its contract, and run an embedded backend that exposes it to world creators.
- [transformer_embedding.py](transformer_embedding.py): serve a local embedding model through an OpenAI-compatible endpoint or register its native `embed` adapter. See [memory retrieval](../guides/reference/memory.md).

See the [developer guide](../guides/developers.md) and [research guide](../guides/research.md) for configuration and evaluation.

- [make_playtest_plan.py](make_playtest_plan.py): generate an editable long-dialogue plan from a native story export.
- [playtest_adapter.py](playtest_adapter.py): run, checkpoint and resume a campaign with a native fixture adapter.

- [action_module.py](action_module.py): register survey/rest actions with typed parameters, personal and shared state, automatic test routes and plugin-free replay.
