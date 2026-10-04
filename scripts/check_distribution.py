"""Build/install the wheel and verify its backend outside the source import path.

No virtualenv or dependencies are modified. The existing Python dependencies
are reused; the wheel is installed into a private target under the report.
Optional --live-models-config uses a real provider in the isolated installed app.
"""

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live-models-config", type=Path)
    parser.add_argument("--secrets-root", type=Path)
    parser.add_argument("--sdk-live", action="store_true", help="Use SDK creation/play/restart acceptance for the real-provider check")
    parser.add_argument('--checks-live', action='store_true', help='Generate, play, share and restart with a native dice-pool engine')
    parser.add_argument('--modules-live', action='store_true', help='Generate, play, share and restart with an external action module')
    parser.add_argument('--memory-live', action='store_true', help='Compare actual embeddings and verify model-backed recall')
    parser.add_argument('--embedding-url')
    parser.add_argument('--embedding-model')
    args = parser.parse_args()
    if sum((args.sdk_live, args.checks_live, args.memory_live, args.modules_live)) > 1:
        parser.error('Select one live acceptance workflow per run')
    if args.modules_live and not args.live_models_config:
        parser.error('--modules-live requires --live-models-config')
    if args.sdk_live and not args.live_models_config:
        parser.error("--sdk-live requires --live-models-config")
    if args.checks_live and (not args.live_models_config or args.sdk_live):
        parser.error('--checks-live requires --live-models-config and runs separately from --sdk-live')
    if args.memory_live and (not args.live_models_config or not args.embedding_url or not args.embedding_model or not args.secrets_root
                             or args.sdk_live or args.checks_live):
        parser.error('--memory-live requires model configuration, embedding URL/model, and runs separately from other live checks')
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT / "outputs/validation"):
        parser.error("Reports must be inside outputs/validation")
    folder.mkdir(parents=True, exist_ok=False)
    target, workspace = folder / "installed", folder / "host"
    workspace.mkdir()
    report = {"status": "running", "checks": [], "mode": "installed-wheel-fixture"}
    env = {k: v for k, v in os.environ.items() if not k.startswith("RPW_") and k != "PYTHONPATH"}
    env.update(PYTHONNOUSERSITE="1", PYTHONPYCACHEPREFIX=str(ROOT / ".cache/pycache"),
               TMPDIR=str(ROOT / "scratch"), PIP_CACHE_DIR=str(ROOT / ".cache/pip"))

    def save():
        (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    def run(name, command, cwd=workspace):
        with (folder / f"{name}.log").open("w") as log:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
        if result.returncode:
            raise RuntimeError(f"{name} failed; see {name}.log")
        report["checks"].append(name); save()

    @contextmanager
    def server(name, command, port=0):
        # Hold a socket and pass its descriptor, eliminating port-selection races.
        with socket.socket() as listener, (folder / f"{name}.log").open("w") as log:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", port))
            listener.listen(128)
            port = listener.getsockname()[1]
            if command[2:4] == ["roleplay_world", "serve"]:
                # Installed CLI owns its listening socket; close the reservation
                # immediately before launch and verify the child stays alive.
                listener.close()
                command = [*command, "--port", str(port)]
                inherited = ()
            else:
                command = [*command, "--fd", str(listener.fileno())]
                inherited = (listener.fileno(),)
            process = subprocess.Popen(command, cwd=workspace, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, pass_fds=inherited)
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False) as client:
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise RuntimeError(f"{name} exited; see its log")
                        try:
                            if client.get("/healthz").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(.1)
                    else:
                        raise TimeoutError(f"{name} startup timed out")
                    assert client.get("/").json()["mode"] == "headless"
                    yield client, str(client.base_url)
            finally:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=20)

    def request(client, method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def connect(client, cookie=None):
        if cookie:
            client.cookies.update(cookie)
        client.headers["X-CSRF-Token"] = request(client, "POST", "/api/session")["csrf_token"]

    try:
        run("build-wheel", [sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps",
                            "--no-build-isolation", "--wheel-dir", str(folder / "wheel")])
        wheel, = (folder / "wheel").glob("*.whl")
        report["wheel_sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            assert "roleplay_world/builtin/fogharbor.json" in names
            assert sum(n.startswith("roleplay_world/builtin/starters/") for n in names) == 3
            assert any(n.endswith("entry_points.txt") for n in names)
            assert not any("models.local" in n or "/secrets/" in n for n in names)
        run("install-wheel", [sys.executable, "-m", "pip", "install", str(wheel), "--no-deps",
                              "--no-compile", "--target", str(target)])
        env["PYTHONPATH"] = str(target)
        # This independent process asserts the actual module location, not merely
        # whether an editable source install happens to answer an HTTP request.
        run("import-origin", [sys.executable, "-c",
            ("import pathlib,roleplay_world; "
            "p=pathlib.Path(roleplay_world.__file__).resolve(); "
            "assert p.is_relative_to(pathlib.Path(__import__('sys').argv[1])); print(p)"), str(target)])
        run("console-entry", [str(target / "bin/narraloom"), "--version"])
        run("model-download-plan", [str(target / "bin/narraloom"), "models", "download", "avatar-2d",
                                    "--model-root", str(workspace / "weights"), "--mirror", "--dry-run"])
        assert not (workspace / "weights").exists()
        # Copy protocol tests outside the checkout so imports resolve to this wheel.
        shutil.copyfile(ROOT / 'tests/test_native_providers.py', workspace / 'test_native_providers.py')
        (workspace / 'pytest.ini').write_text('[pytest]\n')
        run('native-provider-protocols', [sys.executable, '-m', 'pytest', '-q', '-c', str(workspace / 'pytest.ini'),
                                        str(workspace / 'test_native_providers.py'), '--basetemp', str(folder / 'provider-tmp')])
        # Research tools use only the installed package and the host's optional
        # research dependency, with no backend process or game storage.
        for example in ('make_evaluation_cases', 'evaluation_adapter', 'check_engine', 'playtest_adapter', 'action_module'):
            shutil.copyfile(ROOT / f'examples/{example}.py', workspace / f'{example}.py')
        run('evaluation-cases', [sys.executable, str(workspace / 'make_evaluation_cases.py'),
                                 '--output', str(workspace / 'cases.jsonl')])
        run('evaluation-native', [sys.executable, str(workspace / 'evaluation_adapter.py'),
                                  '--output', str(workspace / 'evaluation')])
        run('evaluation-compare', [str(target / 'bin/narraloom'), 'compare',
                                   str(workspace / 'evaluation/report.json'), str(workspace / 'evaluation/report.json'),
                                   '--output', str(workspace / 'comparison.json')])
        run('check-engine-contract', [sys.executable, str(workspace / 'check_engine.py'),
                                      '--output', str(workspace / 'check-engine.json')])
        run('playtest-resume', [sys.executable, str(workspace / 'playtest_adapter.py'),
                               '--output', str(workspace / 'playtest')])
        run('action-module-contract', [sys.executable, str(workspace / 'action_module.py'),
                                       '--output', str(workspace / 'action-module')])
        cli = [sys.executable, "-m", "roleplay_world", "serve", "--workspace", str(workspace)]
        with server("cli-start", cli) as (client, _):
            connect(client)
            cookie = dict(client.cookies)
            campaign = request(client, "POST", "/api/campaigns", json={"player_name": "Wheel tester"})
            base = f'/api/campaigns/{campaign["id"]}/branches/{campaign["branch_id"]}'
            initial = request(client, "GET", base + "/view")
            schema = request(client, "GET", "/openapi.json")
            assert initial["world_version"] == 0 and len(initial["inventory"]) == 1
            assert client.get("/assets/missing.js").status_code == 404
        report["checks"].append("installed-cli-headless-and-packaged-world")
        shutil.copyfile(ROOT / "examples/embedded_backend.py", workspace / "embedded_backend.py")
        env["NARRALOOM_EXAMPLE_WORKSPACE"] = str(workspace)
        embedded = [sys.executable, "-m", "uvicorn", "embedded_backend:create", "--factory", "--app-dir", str(workspace)]
        with server("custom-adapter", embedded) as (client, fixture_url):
            connect(client, cookie)
            assert request(client, "GET", base + "/view") == initial
            assert request(client, "GET", "/openapi.json") == schema
            command = {"action_id": "wheel_" + uuid.uuid4().hex, "expected_world_version": 0,
                       "text": "I give the repair tools to the captain."}
            request(client, "POST", base + "/actions", json=command)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                result = request(client, "GET", "/api/actions/" + command["action_id"])
                if result["status"] in {"committed", "failed", "cancelled"}:
                    break
                time.sleep(.05)
            assert result["status"] == "committed", result
            final = request(client, "GET", base + "/view")
            assert final["world_version"] == 1 and final["inventory"] == []
            run("sdk-fixture", [sys.executable, str(ROOT / "scripts/check_sdk.py"), "--url", fixture_url,
                                "--output", str(folder / "sdk-fixture"), "--fixture"])
            traces = list((workspace / "outputs/model-traces").glob("*.json"))
            assert traces and all(json.loads(p.read_text())["backend"] == "example_fixture" for p in traces)
        report["checks"].append("external-native-adapter-validates-and-commits")
        journal = (workspace / "data/journal.jsonl").read_bytes()
        with server("cli-replay", cli, httpx.URL(fixture_url).port) as (client, _):
            connect(client, cookie)
            assert request(client, "GET", base + "/view") == final
            repeated = request(client, "POST", base + "/actions", json=command)
            assert repeated["result"] == result["result"]
            assert request(client, "GET", "/api/status")["ready"] is False
            run("sdk-restart", [sys.executable, str(ROOT / "scripts/check_sdk.py"), "--url", fixture_url,
                                "--output", str(folder / "sdk-fixture"), "--resume"])
        assert (workspace / "data/journal.jsonl").read_bytes() == journal
        assert list((workspace / "outputs/model-traces").glob("*.json")) == traces
        report["checks"].append("process-restart-replay-and-idempotency-without-model")
        if args.live_models_config and not args.checks_live and not args.memory_live and not args.modules_live:
            live_args = [*cli, "--data-root", "live-data", "--output-root", "live-output",
                         "--models-config", str(args.live_models_config.resolve())]
            if args.secrets_root:
                live_args += ["--secrets-root", str(args.secrets_root.resolve())]
            with server("live-installed-backend", live_args) as (_, url):
                if args.sdk_live:
                    run("sdk-live", [sys.executable, str(ROOT / "scripts/check_sdk.py"), "--url", url,
                                     "--output", str(folder / "sdk-live")])
                else:
                    run("live-api", [sys.executable, str(ROOT / "scripts/check_live.py"), "--url", url,
                                     "--output", str(folder / "live-api")])
                    run("live-studio", [sys.executable, str(ROOT / "scripts/check_studio_api.py"), "--url", url,
                                        "--worlds", "1", "--output", str(folder / "live-studio")])
            if args.sdk_live:
                with server("sdk-live-restart", [*cli, "--data-root", "live-data", "--output-root", "live-output"],
                            httpx.URL(url).port) as (_, restarted):
                    run("sdk-live-recovery", [sys.executable, str(ROOT / "scripts/check_sdk.py"), "--url", restarted,
                                              "--output", str(folder / "sdk-live"), "--resume"])
            report["live_mode"] = "real-provider"
        if args.checks_live:
            check_workspace = workspace / 'check-engine-live'
            env['NARRALOOM_RULES_WORKSPACE'] = str(check_workspace)
            env['NARRALOOM_RULES_MODELS_CONFIG'] = str(args.live_models_config.resolve())
            if args.secrets_root:
                env['NARRALOOM_RULES_SECRETS_ROOT'] = str(args.secrets_root.resolve())
            check_args = [sys.executable, '-m', 'uvicorn', 'check_engine:create', '--factory', '--app-dir', str(workspace)]
            script = [sys.executable, str(ROOT / 'scripts/check_check_engine.py')]
            with server('check-engine-live', check_args) as (_, url):
                run('check-engine-live-sdk', [*script, '--url', url, '--output', str(folder / 'check-engine-live-sdk')])
            # Load the committed history with neither the plugin nor a model service.
            clean_cli = [sys.executable, '-m', 'roleplay_world', 'serve', '--workspace', str(check_workspace)]
            with server('check-engine-restart', clean_cli, httpx.URL(url).port) as (_, restarted):
                run('check-engine-recovery', [*script, '--url', restarted,
                                              '--output', str(folder / 'check-engine-live-sdk'), '--resume'])
            report['live_mode'] = 'real-provider-with-native-check-engine'
        if args.modules_live:
            module_workspace = workspace / 'action-module-live'
            env['NARRALOOM_MODULE_WORKSPACE'] = str(module_workspace)
            env['NARRALOOM_MODULE_MODELS_CONFIG'] = str(args.live_models_config.resolve())
            if args.secrets_root:
                env['NARRALOOM_MODULE_SECRETS_ROOT'] = str(args.secrets_root.resolve())
            module_args = [sys.executable, '-m', 'uvicorn', 'action_module:create', '--factory', '--app-dir', str(workspace)]
            script = [sys.executable, str(ROOT / 'scripts/check_action_module.py')]
            with server('action-module-live', module_args) as (_, url):
                run('action-module-live-sdk', [*script, '--url', url, '--output', str(folder / 'action-module-live-sdk')])
            clean_cli = [sys.executable, '-m', 'roleplay_world', 'serve', '--workspace', str(module_workspace)]
            with server('action-module-restart', clean_cli, httpx.URL(url).port) as (_, restarted):
                run('action-module-recovery', [*script, '--url', restarted,
                                               '--output', str(folder / 'action-module-live-sdk'), '--resume'])
            report['live_mode'] = 'real-provider-with-external-action-module'
        if args.memory_live:
            run('memory-live', [sys.executable, str(ROOT / 'scripts/check_semantic_memory.py'),
                                '--models-config', str(args.live_models_config.resolve()),
                                '--secrets-root', str(args.secrets_root.resolve()),
                                '--embedding-url', args.embedding_url, '--embedding-model', args.embedding_model,
                                '--output', str(folder / 'memory-live')])
            report['live_mode'] = 'real-provider-with-embedding-recall'
        report["status"] = "passed"
    except BaseException as exc:
        report.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        save()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
