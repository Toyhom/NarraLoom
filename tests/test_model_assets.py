import hashlib
import importlib.util
import json
import runpy
import sys
import types
from pathlib import Path

import httpx
import pytest

from roleplay_world import model_assets as assets
from roleplay_world.avatars import AvatarService, vendor_module
from roleplay_world.cli import main


def test_download_cli_dry_run_needs_no_network_or_torch(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(assets, "hf_download", lambda *a: pytest.fail("dry run used network"))
    root = tmp_path / "weights"
    main(["models", "download", "avatar-2d", "--mirror", "--model-root", str(root), "--dry-run"])
    plan = json.loads(capsys.readouterr().out)
    assert plan["endpoint"] == "https://hf-mirror.com"
    assert len(plan["assets"]) == 5 and not root.exists()
    assert all(len(a["revision"]) == 40 for a in plan["assets"] if "repo" in a)


def file_item(body):
    return {"url": "https://example.test/file", "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


@pytest.mark.parametrize("range_supported", [True, False])
def test_resource_resume_or_full_response_and_completed_reuse(tmp_path, range_supported):
    body = b"complete fixed resource"
    target = tmp_path / "model.task"
    target.with_suffix(".task.part").write_bytes(body[:5])
    calls = []

    def handle(request):
        calls.append(request)
        assert request.headers["range"] == "bytes=5-"
        return httpx.Response(206 if range_supported else 200, content=body[5:] if range_supported else body,
                              headers={"Content-Range": f"bytes 5-{len(body)-1}/{len(body)}"})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assets.download_file(file_item(body), target, client=client)
        assets.download_file(file_item(body), target, client=client)
    assert target.read_bytes() == body and len(calls) == 1
    assert not target.with_suffix(".task.part").exists()


def test_bad_resource_does_not_replace_existing_file(tmp_path):
    target = tmp_path / "resource"
    target.write_bytes(b"old")
    with (httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"bad"))) as client,
          pytest.raises(ValueError, match="checksum")):
        assets.download_file(file_item(b"new"), target, client=client)
    assert target.read_bytes() == b"old"


def test_wrong_resume_range_is_rejected(tmp_path):
    target = tmp_path / "file"
    target.with_suffix(".part").write_bytes(b"a")
    with (httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        206, content=b"bc", headers={"Content-Range": "bytes 0-1/3"}))) as client,
          pytest.raises(ValueError, match="byte range")):
        assets.download_file(file_item(b"abc"), target, client=client)
    assert not target.exists()


def test_hf_pinned_metadata_hash_verification_and_explicit_auth(tmp_path, monkeypatch):
    item = assets.CATALOG["vision"]
    body = b"{\"model\": true}"
    weights = b"synthetic weights"
    seen = []
    files = [types.SimpleNamespace(rfilename="config.json", size=len(body), lfs=None,
                                 blob_id=hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()),
             types.SimpleNamespace(rfilename="model.safetensors", size=len(weights), blob_id=None,
                                   lfs={"sha256": hashlib.sha256(weights).hexdigest()})]

    class Api:
        def __init__(self, **kwargs):
            seen.append(kwargs)
        def model_info(self, repo, **kwargs):
            assert kwargs["revision"] == item["revision"]
            return types.SimpleNamespace(sha=item["revision"], siblings=files)

    original_download = assets.download_file
    requests = []
    def handle(request):
        requests.append(request)
        assert request.method == "GET"
        assert "authorization" not in request.headers
        assert item["revision"] in str(request.url)
        return httpx.Response(200, content=body if request.url.path.endswith("config.json") else weights)
    def fetch(item, path, **kwargs):
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            original_download(item, path, client=client, **kwargs)
    monkeypatch.setattr(assets, "download_file", fetch)
    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(HfApi=Api))
    assets.hf_download(item, tmp_path, "https://hf-mirror.com", False)
    assert all(call["token"] is False for call in seen)
    assert len(requests) == 2
    assert (tmp_path / ".narraloom-download.json").is_file()
    files[1].lfs["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="checksum mismatch"):
        assets.hf_download(item, tmp_path, "https://hf-mirror.com", False)


def test_configuration_matches_worker_and_preserves_existing_settings(tmp_path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/avatar_worker.py").touch()
    root, env_root = tmp_path / "weights", tmp_path / "envs"
    result = assets.configure(root, env_root, tmp_path, runner="gpuq")
    config = json.loads(Path(result["worker_config"]).read_text())
    assert config["runner"] == "gpuq"
    monkeypatch.setenv("AVATAR_MODELS_CONFIG", result["models_config"])
    models = vendor_module("models")
    for role, item in assets.CATALOG.items():
        assert models.model_path(role) == assets.destination(root, item)
    original = Path(result["worker_config"]).read_bytes()
    assert not assets.check(tmp_path)["ready"]
    with pytest.raises(ValueError, match="exists"):
        assets.configure(root, env_root, tmp_path)
    assert Path(result["worker_config"]).read_bytes() == original


@pytest.mark.parametrize("runner", ["local", "gpuq"])
def test_service_respects_configured_runner(tmp_path, runner):
    service = AvatarService(None, {"enabled": True, "runner": runner}, workspace_root=tmp_path)
    assert service.executor.runner == runner
    with pytest.raises(ValueError, match="runner"):
        AvatarService(None, {"enabled": True, "runner": "unknown"}, workspace_root=tmp_path)


@pytest.mark.parametrize("runner", ["local", "gpuq"])
def test_worker_bootstrap_preserves_scheduler_guard(tmp_path, monkeypatch, runner):
    root = Path(__file__).resolve().parents[1]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    worker = scripts / "avatar_worker.py"
    worker.write_text((root / "scripts/avatar_worker.py").read_text())
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs/avatar.local.json").write_text(json.dumps({
        "runner": runner, "python": sys.executable, "env": {"AVATAR_MODEL_ROOT": str(tmp_path / "models")}}))
    monkeypatch.setattr(sys, "argv", [str(worker), str(tmp_path / "outputs/creations/job")])
    monkeypatch.delenv("GPUQ_JOB_ID", raising=False)
    calls = []
    monkeypatch.setattr("os.execve", lambda *args: calls.append(args))
    monkeypatch.chdir(root)
    if runner == "gpuq":
        with pytest.raises(RuntimeError, match="GPUQ"):
            runpy.run_path(str(worker))
        assert not calls
        monkeypatch.setenv("GPUQ_JOB_ID", "test")
    runpy.run_path(str(worker))
    assert calls[0][2]["AVATAR_CREATION_RUNNER"] == runner
    assert (tmp_path / "scratch").is_dir()


def test_installer_dry_run_and_existing_environment_protection(tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts/install_avatar_envs.py"
    spec = importlib.util.spec_from_file_location("avatar_installer", path)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    plan = installer.install(tmp_path, sys.executable, installer.KINDS, dry_run=True)
    assert len(plan) == 4 and not (tmp_path / "vision").exists()
    assert "portrait" in {item["kind"] for item in plan}
    (tmp_path / "vision").mkdir()
    with pytest.raises(ValueError, match="not owned"):
        installer.install(tmp_path, sys.executable, installer.KINDS, dry_run=True)


def test_published_vendor_catalog_is_complete_and_matches_pin():
    import subprocess
    root = Path(__file__).resolve().parents[1]
    catalog = vendor_module("model_catalog")
    metadata = vendor_module("model_metadata")
    assert catalog.catalog()["qwen3-vl-4b"]["repo"] == assets.CATALOG["vision"]["repo"]
    assert metadata.model_metadata("vision")["model"]
    pin = json.loads((root / "vendor/avatar_worker/UPSTREAM.json").read_text())
    relative = "src/roleplay_avatar/data/models.json"
    path = root / "vendor/avatar_worker" / relative
    assert assets.digest(path) == pin["files"][relative]
    result = subprocess.run(["git", "-c", f"safe.directory={root}", "check-ignore", str(path)],
                            cwd=root, capture_output=True, check=False)
    assert result.returncode == 1
