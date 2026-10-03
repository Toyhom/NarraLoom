# Test the framework

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

## Content tests

Each authored story revision runs structural/reference checks, rule routes and selected actual-model playtests in isolated state. Custom-state routes cover the declared actions/triggers. Opening/mechanics review reports source locations and claims. Failed checks remain attached to the job so a creator can revise and retest.

Contract fixtures validate software behavior independently of model intelligence. Actual-model suites assess the chosen configuration on exercised tasks. Human playthroughs add coverage of prose, player agency and alternate routes.

## CI and documentation

GitHub Actions runs the CPU suite, lint, catalog checks, frontend build, distribution checks and local documentation links. It requires no provider credentials. Schemas should be regenerated from their Python types when contracts change. See [CONTRIBUTING](../CONTRIBUTING.md).
