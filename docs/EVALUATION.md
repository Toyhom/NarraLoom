# Evaluate replaceable modules

The `roleplay_world.evaluation` API and installed `narraloom evaluate` command run frozen tasks through the regular model gateway. Generation roles and the `action_router` decision role use their configured local services, APIs or native Python adapters. Evaluations write their own reports and traces without creating campaigns or changing game state.

## Run and compare

Install from the checkout with `python -m pip install '.[research]'`. Development installations already include this extra. Prepare two model configurations using the [provider format](ENGINES.md), then run:

```bash
python examples/make_evaluation_cases.py --output outputs/evaluation/cases.jsonl
narraloom evaluate --cases outputs/evaluation/cases.jsonl \
  --models-config configs/baseline.local.json --secrets-root secrets \
  --output outputs/evaluation/baseline
narraloom evaluate --cases outputs/evaluation/cases.jsonl \
  --models-config configs/candidate.local.json --secrets-root secrets \
  --output outputs/evaluation/candidate
narraloom compare outputs/evaluation/baseline/report.json \
  outputs/evaluation/candidate/report.json --output outputs/evaluation/comparison.json
```

The example freezes twelve English, Chinese and Japanese tasks from the packaged Fogharbor world, using runtime prompts, scene schemas and projected context. Six planner tasks have explicit assertions; six NPC/narrator tasks retain prose for human review. Keep the generated file unchanged across configurations. Extend these illustrative tasks with held-out worlds and situations suited to your research question.

`--repeats 3` schedules three independent calls per case. `--max-repairs 1` allows one schema-repair attempt for generation; decision responses use the System One validation contract without repair. Defaults are one repetition and zero repairs. Exit codes are `0` for valid outputs with all scored assertions passed, `1` for case failures, and `2` for invalid configuration/input. Unscored outputs contribute to schema validity only.

## Case format

The JSONL file contains one object per line. The [case schema](../schemas/EvaluationCase.schema.json) defines the envelope. A generation case includes a task, its model-visible output contract and optional private scoring assertions:

```json
{
  "format": "narraloom.eval-case-1",
  "id": "dock_request",
  "kind": "generate",
  "role": "game_master",
  "system": "Choose the destination requested by the player.",
  "data": {"input": "I walk to the dock.", "exits": ["dock", "inn"]},
  "output_schema": {
    "type": "object",
    "properties": {"destination": {"enum": ["dock", "inn"]}},
    "required": ["destination"],
    "additionalProperties": false
  },
  "expect": {
    "properties": {"destination": {"const": "dock"}},
    "required": ["destination"]
  }
}
```

`output_schema` and `expect` use JSON Schema Draft 2020-12. Document-local JSON Pointer references such as `#/$defs/Operation` are supported. Schemas are self-contained; references to external resources and nested `$id` scopes are rejected before calls. `format` annotations follow the validator's default annotation behavior. Express checks with `type`, `required`, `const`, `enum`, numeric bounds and other validation keywords.

The gateway receives `system`, `data` and `output_schema`. Only output-contract failures can enter schema repair. `expect` is checked after the gateway returns and stays out of both the original request and repair prompts. A schema-valid wrong answer is retained as `assertion_failed`.

A decision case sets `kind: "decide"`, `role: "action_router"` and a `decision` object matching [DecisionRequest](../schemas/DecisionRequest.schema.json). Its optional `expect` applies to the validated `answers` dictionary. [evaluation_adapter.py](../examples/evaluation_adapter.py) includes both case types.

Frozen evaluation validates JSON structure and authored assertions. Domain checks that depend on live world transitions remain in the runtime and its playtests. For prose, record human ratings of knowledge consistency, voice, agency and usefulness alongside case IDs.

For complete action sequences, use [`narraloom playtest`](PLAYTESTING.md). It executes the runtime against a native world/story export, checks projected results and recalled sources, and resumes from durable campaign receipts.

## Python engines

```python
from roleplay_world.evaluation import evaluate, load_cases

report = await evaluate(
    load_cases("cases.jsonl"),
    config=model_config,
    registry=my_engine_registry,
    output="outputs/evaluation/native-run",
    secrets_root="secrets",
    repeats=2,
    max_repairs=0,
)
```

Run `python examples/evaluation_adapter.py --output outputs/evaluation/adapter` for a complete native-engine example. It uses authored constant responses to demonstrate generation and decision contracts. Replace its `invoke()` with your model implementation. The [engine guide](ENGINES.md) documents adapter inputs and outputs. Record a new provider `revision` whenever weights, adapter implementation or deployment settings change; native callable implementations and remote weights are identified by this caller-supplied label.

## Reports and recovery

Each output directory contains `report.json`, a writer lock and raw gateway `traces/`. Reports contain outputs, per-case statuses and aggregate metrics. Traces retain model inputs and responses for inspection. Treat these files as research data and review them before sharing.

| Field | Meaning |
| --- | --- |
| `schema_valid_rate` | Valid outputs divided by all scheduled cases, including errors and interruptions |
| `pass_rate` | Passed assertions divided by all scored scheduled cases; `null` when there are none |
| `calls`, `repairs` | Gateway attempts and schema repairs, including failed attempts |
| `latency_p50_s`, `latency_p95_s` | Per-case elapsed latency, including repairs and failed attempts with known duration |
| `reported_input_tokens`, `reported_output_tokens` | Sums of valid provider-reported token counts |
| `calls_without_usage` | Calls with missing, partial or invalid usage reports |
| `calls_incomplete` | Cases with incomplete attempt accounting, including hard-crash recovery |
| `response_models` | Model identifiers returned by the provider |

Token totals cover reported usage. Missing counters and interrupted calls can leave usage or billing unknown. Report scheduled/attempted counts, unknown-usage counts and repair settings alongside rates and latency.

Results are saved atomically before and after each case. `--resume` continues pending rows in the same directory after validating the suite, model configuration, repair budget and framework implementation. Terminal rows, including failures and interruptions, are retained. A hard crash leaves its active row marked interrupted on recovery; existing trace files recover known attempts, while `calls_incomplete` marks the accounting gap. To repeat a failed or interrupted call, start a new output directory. Rotate credentials without changing the behavior fingerprint; changing the model, revision or task requires a new run.

`compare` requires completed reports with the same suite, repetition count, repair budget and framework implementation. It recomputes metrics from rows and pairs statuses and pass results. Configuration digests identify each run; per-case inputs have their own digests. These checks support controlled comparisons; use repeated runs and independent tasks when drawing conclusions about model quality.
