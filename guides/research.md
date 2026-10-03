# Model research and evaluation

[English](research.md) · [简体中文](zh-CN/research.md) · [日本語](ja/research.md)

NarraLoom exposes model responsibilities separately so you can change one module while holding the rest of a story-game system fixed. Useful comparisons include planner accuracy, NPC voice, narration consistency, content generation quality and decision cost.

## Define a comparison

1. Choose one task and one module. Keep the world/story revisions, prompts, rules, initial state and other module settings fixed.
2. Save a baseline configuration and bind the candidate through `providers` and `bindings`, or register a Python engine.
3. Run contract tests, then a model-backed workflow. Record failed outputs, repairs, latency and reported token usage as part of the result.
4. Evaluate new inputs with held-out cases. Use independent playthroughs for subjective writing and playability judgments.

Per-module traces record requested model, response model, deployment revision label, latency and usage. Provider revision labels are metadata supplied by the experimenter. Raw diagnostics may contain story prompts and secrets; select and anonymize data before sharing.

## Evaluate frozen module tasks

Install the research extra with `python -m pip install '.[research]'`. Freeze model inputs once, then reuse them with each configuration:

```bash
python examples/make_evaluation_cases.py --output outputs/evaluation/cases.jsonl
narraloom evaluate --cases outputs/evaluation/cases.jsonl \
  --models-config configs/baseline.local.json --output outputs/evaluation/baseline
narraloom evaluate --cases outputs/evaluation/cases.jsonl \
  --models-config configs/candidate.local.json --output outputs/evaluation/candidate
narraloom compare outputs/evaluation/baseline/report.json \
  outputs/evaluation/candidate/report.json --output outputs/evaluation/comparison.json
```

The example includes twelve tasks across English, Chinese and Japanese. Planner assertions are scored automatically; NPC and narrator outputs support human review. The same API supports generation, System One decisions and registered Python engines. Expected answers stay separate from model requests and repair prompts.

Reports retain failures, repairs, latency and provider-reported tokens, including missing-usage counts. `--resume` continues pending cases while preserving previous results. The [evaluation reference](../docs/EVALUATION.md) covers case format, metrics, recovery and custom adapters.

## Decision models

```bash
python scripts/evaluate_decisions.py   --url http://127.0.0.1:18110/v1   --model YOUR_DECISION_MODEL   --revision YOUR_REVISION   --output outputs/validation/decision-comparison
```

The included diagnostic set has 42 authored Chinese/English cases, each repeated with reversed exit order. Reports include valid responses, end-to-end accuracy, Brier score, calibration bins, automatic coverage/errors, order sensitivity and latency. Create a separate dataset for threshold selection and a held-out set for reporting.

`python scripts/evaluate_generation_router.py --output outputs/validation/generation-comparison` applies the configured generation model to the same routing inputs. Its categorical results support accuracy/latency/token comparisons; generation responses do not supply calibrated probabilities.

## End-to-end behavior

```bash
python scripts/verify.py --distribution
python scripts/check_distribution.py --output outputs/validation/sdk-model-check   --sdk-live --live-models-config configs/models.local.json --secrets-root secrets
```

The live installed-package check creates a world and two stories, runs their automatic tests, plays a turn, restores a backup and verifies request recovery after restart. `scripts/check_longrun.py` exercises longer action sequences; inspect its arguments for the scenario and output directory.

Deterministic replay checks event/persistence behavior. Contract fixtures isolate software boundaries. Actual-model checks measure the chosen model on the exercised tasks. Combine them with human evaluations when assessing dialogue, agency and story quality. [Testing](../docs/TESTING.md) lists focused suites; [engine contracts](../docs/ENGINES.md) describes traces and adapters.

## Resumable campaign tests

Use `narraloom playtest --source story.json --plan plan.json --models-config models.local.json --output outputs/playtests/run` to exercise a complete campaign trajectory. Plans define actions, private scoring assertions and actor-specific memory probes. Checkpoint with `--max-steps`, recover committed actions with `--resume`, and explicitly retry failed execution with `--retry-failed`. See [campaign playtesting](../docs/PLAYTESTING.md) for plan schemas, native adapters and reported usage.
