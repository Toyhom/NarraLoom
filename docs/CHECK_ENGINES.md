# Deterministic check engines

Check engines resolve skill checks, attacks and counterattacks through one interface. A world pins a host-registered engine and its version. Models choose legal actions; the check engine receives typed numerical inputs and a seeded random generator. Its recorded result drives the existing rules and narration.

## Select an engine

The standard backend includes `sum_dice@1`. Supply a binding to `POST /api/studio/worlds` or the `CreateWorld` SDK type:

```json
{
  "prompt": "A coastal workshop with repair tasks and a safe training area. Use 2d6 checks with thresholds 7–10.",
  "rules_mode": "d20",
  "creation_preset": "story",
  "content_language": "en",
  "check_engine": {
    "engine": "sum_dice",
    "version": "1",
    "options": {"count": 2, "sides": 6, "comparison": ">="}
  }
}
```

`WorldBlueprint.check_engine` stores the same binding, so authors can edit it through the world API. Each story pins its world revision; existing campaigns retain their original binding. `GET /api/check-engines` lists installed versions, option schemas and authoring guidance. The reference frontend displays the recorded dice, totals and success. Configure the binding through the backend interfaces.

`sum_dice` accepts 1–32 dice with 2–100 sides and a `>=` or `<=` comparison. It sums all faces, adds the supplied modifier and compares the total with the supplied difficulty. The base rule pack supplies combat bonuses, enemy defense and counterattack thresholds. Choose these values for the selected dice scale. Percentile rule packs supply zero modifiers and percentage thresholds.

Worlds with an omitted binding retain the established d20/d100 behavior. The binding also works in lightweight worlds with authored skill challenges and no equipment or combat rule pack.

## Register a Python implementation

```python
from roleplay_world.app import create_app
from roleplay_world.checks import CheckEngine, CheckResult, builtin_checks
from roleplay_world.contracts import Contract

class Options(Contract):
    pass

def resolve(request, options, rng):
    faces = [rng.randint(1, 6), rng.randint(1, 6)]
    value = max(faces)
    total = value + request.modifier
    return CheckResult(
        roll=value, modifier=request.modifier, total=total,
        difficulty=request.difficulty, passed=total >= request.difficulty,
        dice="best of 2d6", comparison=">=", draws=faces,
    )

registry = builtin_checks()
registry.register(CheckEngine(
    "best_two", "1", Options, resolve,
    "Keep the higher face of two d6s.",
    "Set skill targets on a 1–6 scale plus the actor modifier.",
))
app = create_app(check_registry=registry, model_config=my_models)
```

The host supplies `my_models` using the normal model configuration. A complete dice-pool implementation is in [check_engine.py](../examples/check_engine.py). Run its contract example with `python examples/check_engine.py --output outputs/check-example.json`.

To run its embedded backend, set `NARRALOOM_RULES_WORKSPACE`, `NARRALOOM_RULES_MODELS_CONFIG` and, when needed, `NARRALOOM_RULES_SECRETS_ROOT`, then use `uvicorn check_engine:create --factory --app-dir examples`. It registers `example_pool@1`, which counts successful d6 faces before adding the supplied modifier.

## Contract

| Input or output | Meaning |
| --- | --- |
| `CheckInput.kind` | `ability`, `attack` or `counterattack` |
| `skill`, `purpose` | Stable skill ID and the authored purpose |
| `difficulty`, `modifier` | Numerical values supplied by the surrounding rules |
| `rng` | A `random.Random` instance owned by this resolution; attack and counterattack consume the same sequence |
| `CheckResult.roll` | Score before its modifier: a sum, selected face or success count |
| `total`, `passed` | Must match `roll + modifier` and the declared `>=`/`<=` comparison |
| `dice`, `draws` | Display label and recorded faces |

Callbacks are synchronous pure functions. Use the supplied `rng` and return the same result for the same request, options and RNG state. Input models are frozen; options are validated on separate copies. Difficulty and modifier remain those supplied by the rules. The framework validates result types and arithmetic before applying consequences.

`registry.verify(binding)` exercises all three check kinds with repeated fixed seeds. World creation and automatic content tests run this contract check. Authoring models receive the engine's guidance, and normal content tests exercise authored goals and combat. Add distribution, edge-case and gameplay tests for your own algorithms and thresholds.

Use a new version whenever an algorithm or its option defaults change. A registry can hold several versions of one engine; duplicate ID/version registration fails. Each store copies its host registry at startup. Existing campaigns can retain an older implementation while new worlds select a newer version.

## Persistence and sharing

Committed receipts contain the engine ID, version, option digest, score and dice faces. Replay checks arithmetic and the world's pinned identity, then applies recorded events. Views, history, branches and backup restore remain readable when the plugin is absent. New actions require the matching engine before model calls. A retry after a prepared resolution reuses its recorded result.

Native packages preserve the binding, declare the `check_engine` capability and expose the required ID/version in preview. Packages containing the new field declare a minimum framework version of 0.16.0. Recipients can import the data, install the matching engine in their host application and rerun content tests. Original world and story text stay intact.

Custom checks extend numerical adjudication within the existing action/event system. New operation types, event reducers, combat turn structures and persistence backends have their own core contracts. See [rules](RULES.md), [state rules](STATE_RULES.md), [contracts](CONTRACTS.md) and [testing](TESTING.md).
