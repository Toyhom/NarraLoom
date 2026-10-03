"""Start/stop only this project's registered CPU web process."""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "outputs/services"
FOLDER.mkdir(parents=True, exist_ok=True)
RECORD = FOLDER / "web.json"


def identity(pid):
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
        cwd = Path(f"/proc/{pid}/cwd").resolve()
        start = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        return start if "roleplay_world.app:create_app" in cmd and cwd == ROOT else None
    except (OSError, IndexError):
        return None


def status():
    d = json.loads(RECORD.read_text()) if RECORD.exists() else {}
    live = bool(d.get("pid") and identity(d["pid"]) == d.get("start"))
    return {**d, "running": live}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["start", "stop", "status"])
    p.add_argument("--port", type=int, default=18090)
    p.add_argument("--headless", action="store_true", help="Serve the API without mounting the browser client")
    args = p.parse_args()
    current = status()
    if args.action == "status":
        print(json.dumps(current, ensure_ascii=False, indent=2))
        return
    if args.action == "stop":
        if current["running"]:
            os.kill(current["pid"], signal.SIGTERM)
            for _ in range(50):
                if identity(current["pid"]) != current["start"]:
                    break
                time.sleep(.1)
            else:
                raise RuntimeError("Web process has not stopped; no forced kill was attempted")
        print("Project web service stopped")
        return
    if current["running"]:
        print(f'Already running at http://127.0.0.1:{current["port"]}')
        return
    env = dict(os.environ)
    if args.headless:
        env["RPW_HEADLESS"] = "1"
    env.update({"PYTHONPATH": str(ROOT / "src"), "PYTHONPYCACHEPREFIX": str(ROOT / ".cache/pycache"),
                "TMPDIR": str(ROOT / "scratch"), "TMP": str(ROOT / "scratch"),
                "TEMP": str(ROOT / "scratch"), "XDG_CACHE_HOME": str(ROOT / ".cache/xdg")})
    with (FOLDER / "web.log").open("ab") as output:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "roleplay_world.app:create_app", "--factory",
                                    "--host", "127.0.0.1", "--port", str(args.port), "--no-access-log"],
                                   cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("Web startup failed; see outputs/services/web.log")
        try:
            with httpx.Client(trust_env=False, timeout=.5) as client:
                r = client.get(f"http://127.0.0.1:{args.port}/healthz")
            if r.status_code == 200 and r.json().get("storage") == "single-writer-journal":
                record = {"pid": process.pid, "start": identity(process.pid), "port": args.port,
                          "owner_uid": os.getuid(), "python": sys.executable}
                RECORD.write_text(json.dumps(record, indent=2) + "\n")
                print(f"Ready: http://127.0.0.1:{args.port}")
                return
        except httpx.HTTPError:
            pass
        time.sleep(.1)
    process.terminate()
    raise RuntimeError("Web startup timed out")


if __name__ == "__main__":
    main()
