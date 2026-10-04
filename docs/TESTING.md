# Test the framework

`tests/test_native_providers.py` exercises Responses and Messages wire formats,
authentication, schema repairs, usage, stream completion, refusal, cancellation
and rollback. Distribution verification runs the same tests against the installed
wheel outside the source tree. These are protocol fixtures. Use module connection
checks and model-backed playtests to evaluate a configured provider's real models.
`python scripts/check_provider_browser.py --url http://localhost:18090 --output outputs/validation/provider-browser`
checks the reference client's three languages, protocol settings, key reset and
module bindings on a running test workspace using a fresh browser session.

The published demonstration player uses MP4 and WebM sources. Its deployment runs
`scripts/check_demo_browser.py` in Chromium to verify all three languages, decoded
frames after seeking, desktop/mobile playback and layout before publishing.

Install the development dependencies and frontend packages:

```bash
python -m pip install -e '.[dev]'
npm ci
python scripts/verify.py --distribution
```

The default suite runs Python regression tests, Ruff, interface catalog tests, TypeScript and an isolated Vite build. `--distribution` builds and installs a wheel outside the checkout's import path, runs an external adapter/client and checks restart recovery. Reports are written under `outputs/validation` and each command returns nonzero on failure.

## Model-backed acceptance

Configure an actual provider. Use an isolated workspace for acceptance campaigns and restart checks. Install Chromium with `python -m playwright install chromium` when using browser suites.

```bash
python scripts/check_distribution.py --output outputs/validation/sdk-live   --sdk-live --live-models-config configs/models.local.json --secrets-root secrets
python scripts/verify.py --live --browser --url http://localhost:18090
python scripts/check_locales_browser.py --url http://localhost:18090   --output outputs/validation/locales
```

The installed live SDK flow creates one world and two stories, executes automatic playtests and a player turn, restores a backup, restarts at the same URL and recovers saved requests. Its own server/store are isolated. Browser flows use actual API responses and can consume provider tokens.

| Focus | Entry point |
| --- | --- |
| Authoring and normal play | `--live --browser` |
| Community starter copies | `--catalog` |
| Rules, living worlds and cooperation | `--platform` |
| Custom state | `--states` |
| Independent players and trades | `--players --trades` |
| Scale/content language | `--content-presets` |
| Opening and mechanics review | `--opening` |
| Native multi-story packages | `--community` |
| Existing bilingual live workflow | `--i18n` |

These flags extend `scripts/verify.py`; individual `check_*` scripts expose their parameters with `--help`. Optional Avatar browser checks require an owned prepared asset or explicitly configured creator service.

## Module evaluations

`narraloom evaluate` runs authored JSONL tasks through the configured gateway. Reports include failed responses, schema repairs, assertion results, latency and incomplete usage accounting. `narraloom compare` pairs completed runs of the same workload. See [EVALUATION](EVALUATION.md) for the installed CLI and Python API. Distribution checks exercise native generation/decision adapters and report comparison outside the source import path.

## Memory retrieval

The installed [`narraloom playtest`](PLAYTESTING.md) command runs creator-authored trajectories with durable checkpoint/retry, per-step assertions and actor/historical-memory probes. `examples/make_playtest_plan.py` supplies a 100-turn starting point. Distribution checks exercise the Python runner outside the checkout with a native adapter, inventory assertions and restart recovery.

`tests/test_semantic_memory.py` checks vector protocols, actor/branch isolation, caching, limits and cancellation. The [memory guide](MEMORY.md) includes a local service and a fixed multilingual recall comparison. To run that comparison, actual-model dialogue and restart recovery from an independently installed wheel:

```bash
python scripts/check_distribution.py --output outputs/validation/memory-wheel \
  --memory-live --live-models-config configs/models.local.json --secrets-root secrets \
  --embedding-url http://127.0.0.1:18112/v1 --embedding-model BAAI/bge-m3
```

## Content tests

The installed check-engine acceptance uses a real provider to create a world and two stories, run a skill check and combat, exchange a native package, and verify restart recovery with the plugin absent:

```bash
python scripts/check_distribution.py --output outputs/validation/check-engine-live \
  --checks-live --live-models-config configs/models.local.json --secrets-root secrets
```

The example host installs [a dice-pool engine](../examples/check_engine.py). Unit coverage also checks legacy d20/d100 results, invalid callbacks, pinned versions, prepared-result retries and tampered backup receipts.

The [action-module example](../examples/action_module.py) supplies survey/rest mechanics and host-authored test routes. The distribution suite runs its standalone contracts and plugin-free replay. This real-provider check adds automatic creation, English/Japanese/Chinese action requests, story continuation, content-package exchange and process restart:

```bash
python scripts/check_distribution.py --output outputs/validation/action-module-live \
  --modules-live --live-models-config configs/models.local.json --secrets-root secrets
```

Each authored story revision runs structural/reference checks, rule routes and selected actual-model playtests in isolated state. Custom-state routes cover the declared actions/triggers. Opening/mechanics review reports source locations and claims. Failed checks remain attached to the job so a creator can revise and retest.

Contract fixtures validate software behavior independently of model intelligence. Actual-model suites assess the chosen configuration on exercised tasks. Human playthroughs add coverage of prose, player agency and alternate routes.

## CI and documentation

GitHub Actions runs the CPU suite, lint, catalog checks, frontend build, distribution checks and local documentation links. It requires no provider credentials. Schemas should be regenerated from their Python types when contracts change. See [CONTRIBUTING](../CONTRIBUTING.md).
