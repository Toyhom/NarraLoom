"""Durable character creation jobs. Workers publish packages only after validation."""

import base64
import hashlib
import io
import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from .languages import Locale


class CreationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=2, max_length=1500)
    image_base64: str = Field(min_length=32, max_length=14_000_000)
    presentation: Literal["2d", "3d"] = "2d"
    locale: Locale = "zh-CN"
    voice_candidates: int = Field(default=5, ge=3, le=8)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_creation_output(package: Path):
    """Publication gate: new portraits must finish the current automatic binding pipeline."""
    from .assets import load_package

    result = load_package(package, require_assets=True)
    if "2d" in result.profile.presentation_modes and result.profile.renderer_2d != "cubism":
        rig = read_json(package / "puppet/rig.json")
        if rig.get("mouth_binding", {}).get("method") != "source-lip-warp-v3":
            raise ValueError("New portraits require the automatic source-lip binding stage")
        generation = read_json(package / "generation.json")
        generation["automatic_features"] = {
            "mouth_binding": "source-lip-warp-v3",
            "performance": "committed-dialogue-text-clock-v1",
            "actions": ["nod", "shake_head", "tilt", "bow", "lean_forward", "lean_back", "sway", "bounce"],
            "manual_asset_edits": False,
        }
        write_json(package / "generation.json", generation)
    return result


class CreationStore:
    def __init__(self, root, runner=None):
        self.root = Path(root)
        self.jobs = self.root / "outputs/creations"
        self.jobs.mkdir(parents=True, exist_ok=True)
        self.runner = runner or os.environ.get("AVATAR_CREATION_RUNNER", "disabled")
        self._checks = {}
        self._lock = threading.Lock()

    def folder(self, job_id):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("invalid creation ID")
        folder = self.jobs / job_id
        if not folder.is_dir():
            raise FileNotFoundError(job_id)
        return folder

    def create(self, request, job_id=None):
        if self.runner not in {"gpuq", "local"}:
            raise RuntimeError("Character worker is not configured")
        raw = base64.b64decode(request.image_base64, validate=True)
        if len(raw) > 10_000_000:
            raise ValueError("图片不得超过 10 MB")
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("请上传 PNG、JPEG 或 WebP 图片")
                if image.width * image.height > 24_000_000 or min(image.size) < 128:
                    raise ValueError("图片须至少 128 像素，且不超过 2400 万像素")
                image.load()
                normalized = ImageOps.exif_transpose(image).convert("RGB")
                normalized.thumbnail((1536, 1536))
        except (UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise ValueError("无法读取图片") from exc
        job_id = job_id or uuid.uuid4().hex
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("invalid creation ID")
        if (self.jobs / job_id).exists():
            return self.get(job_id)
        folder = self.jobs / job_id
        folder.mkdir()
        normalized.save(folder / "input.png")
        write_json(
            folder / "request.json",
            {
                "id": job_id,
                "description": request.description,
                "presentation": request.presentation,
                "locale": request.locale,
                "voice_candidates": request.voice_candidates,
                "seed": request.seed,
                "input_sha256": hashlib.sha256((folder / "input.png").read_bytes()).hexdigest(),
            },
        )
        write_json(
            folder / "status.json",
            {
                "id": job_id,
                "state": "queued",
                "stage": "queued",
                "progress": 0,
                "created_at": time.time(),
                "updated_at": time.time(),
            },
        )
        self.submit(folder)
        return self.get(job_id)

    def submit(self, folder):
        command = ["bash", str(self.root / "scripts/create_character.sh"), str(folder)]
        try:
            if self.runner == "gpuq":
                result = subprocess.run(
                    [
                        "gpuq",
                        "submit",
                        "--node",
                        "auto",
                        "--gpus",
                        os.environ.get("AVATAR_CREATION_GPUS", "1"),
                        "--name",
                        "roleplay-world-avatar-" + folder.name,
                        "--",
                        *command,
                    ],
                    cwd=self.root,
                    text=True,
                    capture_output=True,
                    timeout=45,
                    check=True,
                )
                ref = result.stdout.strip()
                if not re.fullmatch(r"system-\d+:[a-f0-9]{12}", ref):
                    raise RuntimeError("Unexpected GPUQ receipt")
                write_json(folder / "runner.json", {"kind": "gpuq", "ref": ref})
            else:
                with (folder / "worker.log").open("a") as log:
                    process = subprocess.Popen(
                        command,
                        cwd=self.root,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                write_json(folder / "runner.json", {"kind": "local", "pid": process.pid})
        except Exception:
            # Do not automatically repeat an ambiguous submission.
            state = read_json(folder / "status.json")
            state.update(state="submission_error", error="任务提交未确认，请检查工作进程记录后重试。")
            write_json(folder / "status.json", state)
            raise

    def recover_receipt(self, folder):
        """Find an accepted job after a lost receipt; never infer absence from a timeout."""
        receipt = folder / "runner.json"
        if receipt.exists() or self.runner != "gpuq":
            return receipt.exists()
        try:
            result = subprocess.run(["gpuq", "list", "--mine", "--json", "--search",
                                     "roleplay-world-avatar-" + folder.name[:10], "--page-size", "200"],
                                    cwd=self.root, text=True, capture_output=True, timeout=8, check=True)
            listing = json.loads(result.stdout)
            matches = [job for job in listing.get("jobs", [])
                       if str(folder) in job.get("command", [])]
            if len(matches) == 1:
                write_json(receipt, {"kind": "gpuq", "ref": matches[0]["id"]})
                state = read_json(folder / "status.json")
                if state["state"] == "submission_error":
                    state.update(state="queued", error=None, updated_at=time.time())
                    write_json(folder / "status.json", state)
                return True
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        return False

    def get(self, job_id):
        folder = self.folder(job_id)
        state = read_json(folder / "status.json")
        if state["state"] == "submission_error":
            self.recover_receipt(folder)
            state = read_json(folder / "status.json")
        published = self.root / "characters" / ("char_" + job_id[:16])
        if state["state"] != "ready" and published.is_dir():
            validate_creation_output(published)
            state.update(state="ready", stage="complete", progress=100, error=None,
                         character_id=published.name, updated_at=time.time())
            write_json(folder / "status.json", state)
        if state["state"] in {"queued", "running"} and (folder / "runner.json").is_file():
            with self._lock:
                should_check = time.monotonic() - self._checks.get(job_id, 0) > 15
                if should_check:
                    self._checks[job_id] = time.monotonic()
            if should_check:
                runner = read_json(folder / "runner.json")
                terminal = False
                try:
                    if runner["kind"] == "gpuq":
                        result = subprocess.run(
                            ["gpuq", "show", runner["ref"]],
                            cwd=self.root,
                            text=True,
                            capture_output=True,
                            timeout=5,
                            check=True,
                        )
                        terminal = json.loads(result.stdout)["state"] not in {"queued", "running", "stopping"}
                    elif runner["kind"] == "local":
                        terminal = not Path(f"/proc/{runner['pid']}").is_dir()
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass  # A temporarily unreachable scheduler is not a failed job.
                latest = read_json(folder / "status.json")
                if (
                    terminal
                    and latest["state"] in {"queued", "running"}
                    and time.time() - latest["updated_at"] > 30
                ):
                    latest.update(
                        state="failed",
                        error="工作进程已退出。已完成的步骤仍然保留，可以继续生成。",
                        updated_at=time.time(),
                    )
                    write_json(folder / "status.json", latest)
                state = latest
        state["description"] = read_json(folder / "request.json")["description"]
        if (folder / "input.png").is_file():
            state["image_url"] = f"/api/creations/{job_id}/files/input.png"
        for filename, key in (("concept.png", "concept_url"), ("preview.png", "preview_url")):
            if (folder / filename).is_file():
                state[key] = f"/api/creations/{job_id}/files/{filename}"
        if (folder / "plan.json").is_file():
            state["plan"] = read_json(folder / "plan.json")
        if (folder / "voice/candidates.json").is_file():
            state["voices"] = read_json(folder / "voice/candidates.json")
        return state

    def list(self):
        folders = sorted(self.jobs.glob("*/status.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [self.get(p.parent.name) for p in folders[:100]]

    def cancel(self, job_id):
        folder = self.folder(job_id)
        state = self.get(job_id)
        if state["state"] in {"ready", "failed", "cancelled"}:
            return self.get(job_id)
        (folder / "cancel").touch()
        # GPUQ cancellation reaches the complete subprocess group on its actual node.
        runner_path = folder / "runner.json"
        if not runner_path.exists() and not self.recover_receipt(folder):
            raise ValueError("Submission receipt remains unknown; cancellation requested but not confirmed")
        if runner_path.exists():
            runner = read_json(runner_path)
            if runner["kind"] == "gpuq":
                subprocess.run(
                    ["gpuq", "cancel", runner["ref"]],
                    cwd=self.root,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
            elif runner["kind"] == "local":
                pid = runner["pid"]
                try:
                    cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
                    if folder.name.encode() in cmd and b"create_character" in cmd:
                        os.killpg(pid, signal.SIGTERM)
                except (FileNotFoundError, ProcessLookupError):
                    pass
        state.update(state="cancelled", updated_at=time.time())
        write_json(folder / "status.json", state)
        return self.get(job_id)

    def retry(self, job_id):
        folder = self.folder(job_id)
        state = self.get(job_id)
        if state["state"] not in {"failed", "cancelled"}:
            raise ValueError("Only confirmed failed or cancelled jobs can resume")
        if not (folder / "runner.json").exists() and not self.recover_receipt(folder):
            raise ValueError("Cannot retry without confirming previous worker exit")
        if (folder / "runner.json").exists():
            runner = read_json(folder / "runner.json")
            if runner["kind"] == "gpuq":
                result = subprocess.run(
                    ["gpuq", "show", runner["ref"]],
                    cwd=self.root,
                    text=True,
                    capture_output=True,
                    timeout=30,
                    check=True,
                )
                if json.loads(result.stdout)["state"] in {"running", "queued", "stopping"}:
                    raise ValueError("Previous worker is still stopping")
            elif runner["kind"] == "local":
                try:
                    cmd = Path(f"/proc/{runner['pid']}/cmdline").read_bytes()
                    if folder.name.encode() in cmd and b"create_character" in cmd:
                        raise ValueError("Previous worker is still stopping")
                except FileNotFoundError:
                    pass
        (folder / "cancel").unlink(missing_ok=True)
        state.update(state="queued", error=None, updated_at=time.time())
        write_json(folder / "status.json", state)
        self.submit(folder)
        return self.get(job_id)
