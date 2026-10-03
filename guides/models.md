# Choose and configure models

[English](models.md) · [简体中文](zh-CN/models.md) · [日本語](ja/models.md)

The simplest setup uses one strong instruction model through an OpenAI-compatible endpoint. DeepSeek's `deepseek-flash` is a working example; use the model IDs advertised by your provider. vLLM, SGLang and llama.cpp endpoints can serve local checkpoints through the same protocol.

| Module | Useful model properties |
| --- | --- |
| `world_builder`, `story_builder`, `import_builder` | Structured generation, long context, coherent settings and outlines |
| `rules_builder`, `state_builder`, `simulation_builder` | Reliable JSON, conditions and causal reasoning |
| `content_reviewer`, `game_master` | Strong instruction following and reasoning about current state |
| `character_actor`, `narrator` | Character voice, dialogue and prose in the content language |
| `world_actor` | Bounded proposals that respect NPC knowledge and available actions |
| `action_router` | System One decision protocol; measured accuracy on your action distribution |
| Deterministic rules | Engine code handles dice, arithmetic, ownership and persistence |
| Avatar presentation | Separate image/rig creation or imported ready assets; see [Avatar](../docs/AVATARS.md) |

Smaller dialogue models can reduce cost. Evaluate their structured outputs and character behavior separately from the main planner. A general small model usually needs more testing for world generation and complex rules.

## Server configuration

Save this as `configs/models.local.json`, and set `RPW_API_KEY` privately in your shell or service manager:

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

For a local service, set `url` to its reachable address, such as `http://127.0.0.1:8000/v1`, and use its served model name. URLs are reached from the backend host. Each role may have its own provider, model, timeout, output limit and generation parameters. `json_object`, `json_schema` and prompt-based JSON depend on provider support; all results still pass runtime validation.

The reference frontend exposes named providers and module bindings under **Models & usage**. Save settings before running a module check. A blank key preserves a saved key for the same endpoint; removing it uses the explicit clear control. [Engine contracts](../docs/ENGINES.md) describes the deployment-file format and Python extension API.

## Optional System One / Jev

System One handles typed `choice`, `noul` and `score` questions. The bundled adapter supports Jev-style decision servers. Bind it to `action_router` with `configs/models.hybrid.example.json` as a starting point.

Routing defaults to **off**. **Shadow** records classifications while the main planner still handles the turn. **Auto** can route an explicit single movement when probability and margin thresholds pass. Start in shadow mode and evaluate negation, ambiguity, multi-step actions and language variation before enabling auto. Thresholds are model outputs; measure actual errors on held-out cases.

Local model memory depends on weights, context, quantization and concurrency. Run optional inference in a separate environment, share endpoints between roles using the same weights, and follow your host's GPU scheduler. The regular API backend needs no GPU or Torch. Pinned Jev setup commands are in [ENGINES](../docs/ENGINES.md).
