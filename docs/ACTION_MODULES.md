# Custom action modules

Action modules add Python gameplay rules to an embedded NarraLoom host. A module declares typed parameters, portable state and deterministic action handlers. Worlds pin the implementation ID, version and options. The normal runtime handles model planning, narration, commits, cancellation, branches and recovery.

The [exploration example](../examples/action_module.py) adds terrain/weather surveys and rest. Surveys consume personal focus, record a seeded d6 quality and increment shared progress. Its optional vitality cost uses an adventure world's existing bounded resource.

## Install and register

```bash
python -m pip install .
python examples/action_module.py --output example-runtime/module-check
NARRALOOM_MODULE_WORKSPACE=example-runtime \
NARRALOOM_MODULE_MODELS_CONFIG=/path/to/models.local.json \
uvicorn action_module:create --factory --app-dir examples --port 18090
```

The standalone check uses a narrator fixture, runs declared rule tests, commits two actions, and verifies replay, forks and backup restoration after reopening without the module implementation.

An embedded application registers `ActionModule` objects in an `ActionRegistry`, then supplies `create_app(action_registry=registry)`. The same registry can be passed to `Store`, `quality.playtest` and the Python `playtesting.playtest` runner. The host installs Python implementations and their dependencies; native content packages carry versioned data contracts.

`GET /api/action-modules` returns the installed engine IDs, versions, guidance, options schemas and action descriptors. Choose modules through `CreateWorld.action_modules`:

```json
{
  "prompt": "A quiet field station beside a forest",
  "creation_preset": "scene",
  "content_language": "en",
  "action_modules": [{
    "id": "exploration",
    "engine": "example_exploration",
    "version": "1",
    "options": {"focus_max": 3, "vitality_cost": 0}
  }]
}
```

The host validates the selections before generation. It initializes and snapshots the selected bindings into the generated world; stories inherit that world revision. `registry.bind(selection)` produces the same `ModuleBinding` for programmatic authoring. Bindings include the initial state and action/state schemas. Change the version when an implementation or contract changes.

## Module interface

| Field | Contract |
| --- | --- |
| `id`, `version` | Stable identifiers using letters, digits, `_` and `-` |
| `options` | Pydantic configuration model |
| `state` | Pydantic model matching the `ModuleState` partitions |
| `actions` | One to twelve `ActionSpec(id, name, description, parameters)` definitions |
| `initialize(options)` | Initial JSON-compatible module state |
| `resolve(context, action_id, parameters, options, rng)` | A `ModuleResult` or equivalent dictionary |
| `guidance` | Host-facing explanation of the mechanics and suitable world settings |
| `tests(options)` | One to eight `ModuleTest` routes covering all declared actions |

Callbacks are synchronous pure functions. Use the supplied `random.Random` for randomness. Initialization and resolution are each repeated with copied inputs to check identical results. Model inference belongs in the asynchronous model adapters that propose typed actions.

Resolution receives the acting player's ID, actor definition and state, current game time, and the module's own full state. Parameter and options values are instances of the registered Pydantic models. Raise `DomainError` with a stable code for an unmet gameplay precondition.

`ModuleResult` contains:

- `state`: the replacement state of this binding, validated against its pinned schema.
- `resource_deltas`: integer changes to existing bounded resources of the acting player.
- `messages`: up to six outcome messages addressed to that player, each up to 600 characters.
- `time_cost_s`: the committed duration, from 1 to 1,800 seconds.

Each world supports up to eight uniquely named bindings. A binding has at most 16,000 characters of options and 64,000 characters of state. Parameters are finite JSON objects bounded to 16,000 characters; parameter schemas use finite document-local references. Keep action names/descriptions and parameter choices suitable for player-facing discovery.

## Perspectives

State has three partitions:

| Partition | Readers |
| --- | --- |
| `public` | All characters and players |
| `actors[actor_id]` | The named actor and host |
| `private` | Host callbacks, creator exports and full backups |

Player projections expose `action_modules=[{id,engine,version,public,personal,actions}]`. NPC projections receive their own public/personal data. Planning receives action descriptors and the acting player's projection; private initial state and options stay out of turn-planning context. Outcome messages enter only the acting player's memories and narration. Module authors control the content they put in each partition and message.

Joining players start with an empty personal partition. Modules can initialize it on their first action, as the example does. Story continuation carries state when both stories pin the same world revision and identical bindings.

## Natural language and direct actions

The planner receives available module actions with their parameter schemas. A custom frontend can also send a selected operation through the ordinary action endpoint or Python SDK:

```json
{
  "action_id": "survey_1",
  "expected_world_version": 0,
  "mode": "act",
  "text": "I survey the terrain.",
  "selected_operation": {
    "kind": "module",
    "target_id": "exploration",
    "action_id": "survey",
    "parameters": {"focus": {"subject": "terrain"}}
  }
}
```

The module owns its random checks and duration. The reference frontend's text box can use these actions once the host has bound them to the world. Custom frontends may render controls from the descriptors and parameter schemas.

## Automatic tests and recovery

Each `ModuleTest` has a name, seed, up to sixteen action steps and an `expect` JSON Schema. The assertion is applied to `{module_state, actor_state}` in isolated state. The host test runner exercises every declared action and validates replay. Story creation also runs the first route of each binding through the normal runtime and model narration, using that route's seed. Assertion schemas stay outside model prompts.

New actions require the pinned module version. A `module.resolved` event records the binding digest, prior-state digest, parameters, materialized state, resource deltas and messages. Replay validates this receipt from its stored contracts. Reading, branching and restoring committed saves works without installing module code. Prepared outcomes can resume narration without rerunning a callback. Cancellation before commit leaves canonical state unchanged.

Packages preview each binding's ID, engine and version. Snapshots containing `action_modules` require NarraLoom 0.19.0 or newer. Recipients install the matching host module before testing and playing imported content. Missing implementations report `action_module_unavailable` while the imported draft remains editable.

Run `python -m pytest -q tests/test_action_modules.py` for focused regressions and `python scripts/verify.py --distribution` for installation checks. [Testing](TESTING.md) describes real-provider acceptance. Custom event types and persistence backends remain versioned core interfaces.
