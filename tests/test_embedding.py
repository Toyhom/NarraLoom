"""Host configuration, extension and lifetime boundaries for external applications."""

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from roleplay_world.app import create_app
from roleplay_world.config import AppConfig
from roleplay_world.contracts import DomainError
from roleplay_world.engines import Engine, builtin_engines
from roleplay_world.gateway import ModelGateway
from roleplay_world.store import Store


def session(client):
    client.headers["X-CSRF-Token"] = client.post("/api/session").json()["csrf_token"]


def test_explicit_apps_are_isolated_from_process_environment(tmp_path, monkeypatch):
    poisoned = tmp_path / "unrelated-host"
    monkeypatch.setenv("RPW_DATA_ROOT", str(poisoned))
    monkeypatch.setenv("RPW_MODELS_CONFIG", str(poisoned / "missing.json"))
    monkeypatch.setenv("RPW_HEADLESS", "0")
    first = AppConfig(workspace_root=tmp_path / "first")
    second = AppConfig(workspace_root=tmp_path / "second", data_root="saves", output_root="diagnostics")
    with TestClient(create_app(config=first)) as a, TestClient(create_app(config=second)) as b:
        session(a); session(b)
        campaign = a.post("/api/campaigns", json={"player_name": "Host A"}).json()
        assert a.get("/").json()["mode"] == b.get("/").json()["mode"] == "headless"
        assert campaign["id"] not in b.app.state.store.campaigns
        assert a.app.state.gateway.trace_root == first.output_root / "model-traces"
        assert b.app.state.gateway.trace_root == second.output_root / "model-traces"
        assert a.app.state.avatars.root == first.workspace_root
    assert (first.data_root / "journal.jsonl").is_file()
    assert (second.data_root / "journal.jsonl").is_file()
    assert not poisoned.exists()


def test_paths_are_host_supplied_and_missing_explicit_config_fails(tmp_path):
    root = tmp_path / "host"
    external = tmp_path / "external"
    cfg = AppConfig.from_env({"RPW_WORKSPACE": str(root), "RPW_DATA_ROOT": str(external),
                              "RPW_OUTPUT_ROOT": "runs", "RPW_MODELS_CONFIG": "model.json"})
    assert cfg.data_root == external and cfg.output_root == root / "runs"
    with pytest.raises(ValueError, match="Cannot read model configuration"):
        create_app(config=cfg)
    assert not external.exists()
    root.mkdir()
    cfg.models_config.write_text('{"api_key": "do-not-echo-this"')
    with pytest.raises(ValueError) as error:
        create_app(config=cfg)
    assert "do-not-echo-this" not in str(error.value)
    cfg.models_config.write_text("[]")
    with pytest.raises(TypeError):
        create_app(config=cfg)
    with pytest.raises(ValueError):
        AppConfig.from_env({"RPW_HEADLESS": "maybe"})


def test_local_backend_is_used_by_diagnostics_without_http(tmp_path):
    calls = []
    async def invoke(config, payload, headers):
        assert "url" not in config
        calls.append(payload)
        return {"model": "native-fixture", "text": '{"text":"Hello"}'}
    registry = builtin_engines()
    registry.register(Engine("native", frozenset({"generate"}), invoke))
    cfg = AppConfig(workspace_root=tmp_path)
    models = {"default": {"backend": "native", "model": "fixture"}}
    app = create_app(config=cfg, model_config=models, registry=registry)
    models["default"]["model"] = "changed-after-construction"
    with TestClient(app) as client:
        session(client)
        status = client.get("/api/status").json()
        assert status["ready"] is None and status["mode"] == "unprobed"
        modules = client.get("/api/engines").json()["modules"]
        assert next(m for m in modules if m["id"] == "game_master")["configured"]
        result = client.post("/api/settings/provider/check").json()
        assert result["generation_passed"] and result["sample"] == "Hello"
        result = client.post("/api/engines/narrator/check").json()
        assert result["protocol_passed"] and result["sample"] == "Hello"
    assert len(calls) == 2 and all(call["model"] == "fixture" for call in calls)
    assert len(list((cfg.output_root / "model-traces").glob("*.json"))) == 2


def test_backend_probe_and_capability_checks(tmp_path):
    calls = []
    async def invoke(*args):
        raise AssertionError("Health must not run inference")
    async def probe(config, headers):
        calls.append(config["model"])
        return {"ready": True, "mode": "local-test"}
    registry = builtin_engines()
    registry.register(Engine("native", frozenset({"generate"}), invoke, probe))
    registry.register(Engine("classifier", frozenset({"decide"}), invoke))
    cfg = AppConfig(workspace_root=tmp_path)
    with TestClient(create_app(config=cfg, registry=registry,
                              model_config={"default": {"backend": "native", "model": "fixture"}})) as client:
        session(client)
        assert client.get("/api/status").json() == {"ready": True, "mode": "local-test"}
        bad = {"url": "http://localhost:1", "model": "test", "providers": {
            "local": {"url": "http://localhost:1", "backend": "classifier"}},
            "bindings": {"game_master": {"provider": "local", "model": "test"}}}
        assert client.put("/api/settings/provider", json=bad).json()["error"] == "engine_capability"
    assert calls == ["fixture"]
    with pytest.raises(ValueError, match="not both"):
        create_app(config=cfg, gateway=object(), registry=registry)


def test_failed_startup_releases_writer_and_can_retry(tmp_path):
    cfg = AppConfig(workspace_root=tmp_path)
    def fail(store):
        raise RuntimeError("adapter initialization failed")
    with pytest.raises(RuntimeError, match="adapter initialization failed"), TestClient(
        create_app(config=cfg, avatar_factory=fail)
    ):
        pass
    with TestClient(create_app(config=cfg)) as client:
        assert client.get("/healthz").status_code == 200
        with pytest.raises(OSError):
            Store(cfg.data_root)
    restored = Store(cfg.data_root)
    restored.close()


def test_secrets_are_scoped_to_explicit_host_and_symlinks_checked(tmp_path, monkeypatch):
    monkeypatch.delenv("RPW_API_KEY", raising=False)
    private = tmp_path / "private"
    private.mkdir()
    key = private / "provider.key"
    key.write_text("fixture-key")
    gateway = ModelGateway({}, tmp_path / "traces", secrets_root=private)
    for value in ("provider.key", "secrets/provider.key", str(key)):
        assert gateway.auth_headers({"api_key_file": value}) == {"Authorization": "Bearer fixture-key"}
    outside = tmp_path / "outside.key"
    outside.write_text("unrelated-key")
    (private / "link.key").symlink_to(outside)
    for value in ("../outside.key", str(outside), "link.key"):
        with pytest.raises(DomainError):
            gateway.auth_headers({"api_key_file": value})
    assert not list((tmp_path / "traces").iterdir())


def test_external_reference_frontend_is_optional_and_has_same_api(tmp_path):
    cfg = AppConfig(workspace_root=tmp_path / "host", web_dist=tmp_path / "custom-web", headless=False)
    cfg.web_dist.mkdir()
    (cfg.web_dist / "assets").mkdir()
    (cfg.web_dist / "assets/test.js").write_text("window.frameworkTest=true")
    (cfg.web_dist / "index.html").write_text("<title>Reference client</title>")
    with TestClient(create_app(config=cfg)) as client:
        schema = client.get("/openapi.json").json()
        assert "Reference client" in client.get("/").text
        assert client.get("/assets/test.js").status_code == 200
    with TestClient(create_app(config=replace(cfg, headless=True))) as client:
        assert client.get("/").json()["mode"] == "headless"
        assert client.get("/assets/test.js").status_code == 404
        assert client.get("/openapi.json").json() == schema


def test_corrupt_settings_startup_closes_store(tmp_path):
    cfg = AppConfig(workspace_root=tmp_path)
    settings = cfg.data_root / "provider-settings"
    settings.mkdir(parents=True)
    path = settings / "broken.json"
    path.write_text("invalid")
    with pytest.raises(json.JSONDecodeError), TestClient(create_app(config=cfg)):
        pass
    path.unlink()
    with TestClient(create_app(config=cfg)) as client:
        assert client.get("/healthz").status_code == 200
