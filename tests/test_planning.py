import pytest
from pydantic import ValidationError

from roleplay_world.contracts import DomainError, TurnPlan
from roleplay_world.planning import explicit_wait, plan_schema, validate_plan


def test_scene_schema_blocks_talk_as_movement_and_wrong_entity(state):
    talk = {"mode": "say", "text": "问候船长"}
    with pytest.raises(ValidationError):
        plan_schema(state, talk).model_validate({"intent": "交谈", "operations": [{"kind": "move", "target_id": "npc_captain"}]})
    act = {"mode": "act", "text": "出发"}
    with pytest.raises(ValidationError):
        plan_schema(state, act).model_validate({"intent": "出发", "operations": [{"kind": "move", "target_id": "npc_captain"}]})
    with pytest.raises(DomainError, match="发言"):
        validate_plan(state, act, TurnPlan(intent="交谈", speakers=["npc_keeper"]))


def test_wait_duration_is_arithmetic_not_model_guess(state):
    command = {"mode": "wait", "text": "我留在码头等待三十分钟。"}
    assert explicit_wait(command["text"]) == 1800
    assert explicit_wait("等待两分钟三十秒") == 150
    assert explicit_wait("我询问船长三十分钟前的事") is None
    schema = plan_schema(state, command)
    with pytest.raises(ValidationError):
        schema.model_validate({"intent": "等待", "time_cost_s": 180})
    assert schema.model_validate({"intent": "等待", "time_cost_s": 1800}).time_cost_s == 1800
