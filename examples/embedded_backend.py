"""A native Python adapter and an embedded API, independent of the reference UI.

This is an explicit deterministic fixture, NOT an AI model. It handles one
Fogharbor action (giving the tools to the captain) to demonstrate the full
schema/validation/commit boundary. Use a real backend for free-form play.

Run: uvicorn embedded_backend:create --factory --app-dir examples --port 18091
Set NARRALOOM_EXAMPLE_WORKSPACE to a private directory for this example.
"""

import json
import os
from pathlib import Path

from roleplay_world.app import create_app
from roleplay_world.config import AppConfig
from roleplay_world.engines import Engine, builtin_engines


async def invoke(config, payload, auth_headers):
    contract = payload["response_format"]["json_schema"]["name"]
    responses = {
        "SceneTurnPlan": {"intent": "Fixture: give tools", "operations": [
            {"kind": "give", "target_id": "npc_captain", "item_id": "item_tools"}],
            "speakers": ["npc_captain"]},
        "SceneActorReply": {"text": "Fixture: I accept the tools.", "reaction": "accept"},
        "ActorReply": {"text": "Fixture: hello."},
        "Narration": {"text": "Fixture: the captain receives the tools.", "suggestions": []},
    }
    if contract not in responses:
        raise ValueError(f"This demonstration adapter does not implement {contract}")
    return {"text": json.dumps(responses[contract]), "model": "example-fixture-v1"}


async def probe(config, auth_headers):
    return {"ready": True, "mode": "test_fixture", "model": "example-fixture-v1"}


def create():
    registry = builtin_engines()
    registry.register(Engine("example_fixture", frozenset({"generate"}), invoke, probe))
    config = AppConfig(workspace_root=Path(os.environ.get("NARRALOOM_EXAMPLE_WORKSPACE", "example-runtime")))
    return create_app(config=config, registry=registry, model_config={
        "default": {"backend": "example_fixture", "model": "example-fixture-v1", "json_schema": True},
    })
