"""Reproducible regression entry point; live checks use actual configured models."""

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18090")
    parser.add_argument("--live", action="store_true", help="Run Fogharbor and 3 generated-world API cases")
    parser.add_argument("--browser", action="store_true", help="Run both real-model Playwright suites")
    parser.add_argument("--catalog", action="store_true", help="Install and playtest every community starter in Chromium")
    parser.add_argument("--platform", action="store_true", help="Run rules, living-world, portability and cooperative-room browser suites")
    parser.add_argument("--states", action="store_true", help="Run generated state mechanics, editor and replay browser acceptance")
    parser.add_argument("--trades", action="store_true", help="Run human quotes, counteroffers, consent, conservation and backup browser acceptance")
    parser.add_argument("--players", action="store_true", help="Run independent characters, private views and restored multiplayer seats")
    parser.add_argument("--content-presets", action="store_true", help="Real multilingual/lightweight creation and import round trips")
    parser.add_argument("--i18n", action="store_true", help="Global language switching, drafts, imports and real English creation/play")
    parser.add_argument("--opening", action="store_true", help="Live opening/mechanics contrasts and browser repair lifecycle")
    parser.add_argument("--community", action="store_true", help="Real multi-story publishing, recipient tests, file import and play")
    parser.add_argument("--restart", action="store_true", help="Stop/start only this project's managed web service")
    parser.add_argument("--distribution", action="store_true", help="Build/install the backend wheel and test external use/restarts")
    parser.add_argument("--output", default="outputs/validation/suite-" + datetime.datetime.now(datetime.UTC).strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT / "outputs/validation"):
        raise ValueError("Reports must be inside outputs/validation")
    folder.mkdir(parents=True, exist_ok=False)
    (ROOT / 'scratch').mkdir(exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"),
           "PYTHONPYCACHEPREFIX": str(ROOT / ".cache/pycache"), "TMPDIR": str(ROOT / "scratch"),
           "npm_config_cache": str(ROOT / ".cache/npm")}
    py = sys.executable
    checks = [("pytest", [py, "-m", "pytest", "-q"]),
              ("ruff", [py, "-m", "ruff", "check", "src", "tests", "scripts"]),
              ("ui-catalogs", ["node", "--test", "scripts/check_i18n.mjs"]),
              ("build", ["npm", "run", "build", "--", "--outDir", str(folder / "web")])]
    if args.distribution:
        checks.append(("distribution", [py, "scripts/check_distribution.py", "--output", str(folder / "distribution")]))

    def live(name, script):
        checks.append((name, [py, "scripts/" + script, "--url", args.url, "--output", str(folder / name)]))

    if args.live:
        live("fogharbor-api", "check_live.py")
        live("studio-api", "check_studio_api.py")
    if args.browser:
        live("fogharbor-browser", "check_browser.py")
        live("studio-browser", "check_studio_browser.py")
    if args.catalog:
        live("community-catalog", "check_catalog.py")
    if args.platform:
        live("rules-browser", "check_rules_browser.py")
        live("living-world-browser", "check_world_browser.py")
        live("portability-browser", "check_portability_browser.py")
        live("rooms-browser", "check_rooms_browser.py")
        live("library-browser", "check_library_browser.py")
    if args.states or args.platform:
        live("states-browser", "check_states_browser.py")
    if args.players or args.platform:
        live("players-browser", "check_players_browser.py")
    if args.trades or args.platform:
        live("trades-browser", "check_trades_browser.py")
    if args.content_presets:
        live("content-presets", "check_content_presets.py")
    if args.i18n:
        live("locales-browser", "check_locales_browser.py")
        live("i18n-browser", "check_i18n_browser.py")
    if args.community:
        live("community-browser", "check_community_browser.py")
    if args.opening:
        for name, script in [("opening-contrasts", "check_opening_review.py"), ("mechanics-contrasts", "check_content_review.py")]:
            checks.append((name, [py, "scripts/" + script, "--output", str(folder / name)]))
        live("opening-browser", "check_opening_browser.py")
    if args.restart:
        live("restart", "check_restart.py")
    report = {"status": "running", "url": args.url, "checks": []}
    for name, command in checks:
        print("RUN", name, flush=True)
        with (folder / (name + ".log")).open("w") as output:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT, check=False)
        report["checks"].append({"name": name, "status": "passed" if result.returncode == 0 else "failed",
                                 "exit_code": result.returncode, "log": name + ".log"})
        report["status"] = "failed" if any(c["status"] == "failed" for c in report["checks"]) else "running"
        (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(name, report["checks"][-1]["status"], flush=True)
    if report["status"] != "failed":
        report["status"] = "passed"
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(str(folder / "report.json"), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
