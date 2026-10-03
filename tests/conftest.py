import json
from pathlib import Path

import pytest

from roleplay_world.world import initial_state


@pytest.fixture
def template():
    path = Path(__file__).resolve().parents[1] / "src/roleplay_world/builtin/fogharbor.json"
    return json.loads(path.read_text())


@pytest.fixture
def state(template):
    return initial_state(template, "林")
