# Model research and evaluation

[English](research.md) · [简体中文](zh-CN/research.md) · [日本語](ja/research.md)

NarraLoom exposes model responsibilities separately so you can change one module while holding the rest of a story-game system fixed. Useful comparisons include planner accuracy, NPC voice, narration consistency, content generation quality and decision cost.

## Define a comparison

1. Choose one task and one module. Keep the world/story revisions, prompts, rules, initial state and other module settings fixed.
2. Save a baseline configuration and bind the candidate through `providers` and `bindings`, or register a Python engine.
3. Run contract tests, then a model-backed workflow. Record failed outputs, repairs, latency and reported token usage as part of the result.
4. Evaluate new inputs with held-out cases. Use independent playthroughs for subjective writing and playability judgments.

Per-module traces record requested model, response model, deployment revision label, latency and usage. Provider revision labels are metadata supplied by the experimenter. Raw diagnostics may contain story prompts and secrets; select and anonymize data before sharing.

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
