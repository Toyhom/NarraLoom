import asyncio
import json

import pytest
from pydantic import ValidationError

from roleplay_world.backups import export_campaign, restore_campaign
from roleplay_world.catalog import load_catalog
from roleplay_world.content import StoryBlueprint, WorldBlueprint, compile_story, validate_story
from roleplay_world.content_review import (
    ContentReview,
    TextRepairs,
    assess_content,
    repair_schema,
    repair_text,
    review_schema,
    review_story,
    validate_review,
)
from roleplay_world.continuity import carry_world
from roleplay_world.contracts import ActionCommand, DomainError, Operation, TurnPlan
from roleplay_world.journal import digest
from roleplay_world.planning import explicit_goal_plan
from roleplay_world.rulepacks import RuleSet
from roleplay_world.rules import resolve
from roleplay_world.runtime import Runtime
from roleplay_world.state_rules import StateRules, action_choices, audit_state_rules
from roleplay_world.store import Store
from roleplay_world.world import apply_events, initial_state, project


def condition(key, value, op="eq", source="variable"):
    return {"source": source, "key": key, "op": op, "value": value}


@pytest.fixture
def authored():
    original = load_catalog()["apartment-5c"]
    world = WorldBlueprint.model_validate(original["world"])
    story = StoryBlueprint.model_validate(original["story"])
    world.rules = RuleSet(coins=10)
    world.characters[0].location = story.start_location
    world.state_rules = StateRules.model_validate({"variables": [{"id": "renown", "name": "世界声誉"}]})
    story.state_rules = StateRules.model_validate({
        "variables": [
            {"id": "progress", "name": "调查进展", "maximum": 3},
            {"id": "unlocked", "name": "私人突破", "kind": "boolean", "initial": False, "visibility": "player"},
            {"id": "hidden", "name": "幕后路线", "kind": "enum", "initial": "sealed", "options": ["sealed", "active"], "visibility": "gm"}],
        "actions": [
            {"id": "study", "name": "整理笔记", "time_cost_s": 10,
             "effects": [{"kind": "add", "target": "progress", "value": 1}, {"kind": "set", "target": "hidden", "value": "active"}]},
            {"id": "claim", "name": "登记发现", "once": True, "time_cost_s": 10,
             "when_all": [condition("progress", 2, "ge")], "when_any": [condition("hidden", "active")],
             "effects": [{"kind": "resource", "target": "coins", "value": 3}, {"kind": "add", "target": "renown", "value": 1}]}],
        "triggers": [{"id": "breakthrough", "name": "突破", "when_all": [condition("progress", 2, "ge")],
                      "effects": [{"kind": "set", "target": "unlocked", "value": True},
                                  {"kind": "message", "text": "玩家单独发现星环密码。"},
                                  {"kind": "message", "actor_id": "npc_0", "text": "站长收到私人暗号。"}]}],
        "tests": [{"name": "整理并登记", "steps": [{"kind": "state_action", "target_id": "study"},
                {"kind": "state_action", "target_id": "study"}, {"kind": "state_action", "target_id": "claim"}],
                   "expect": [condition("progress", 2), condition("unlocked", True), condition("renown", 1)]}]})
    return world, story


def compile_authored(authored):
    return compile_story(*authored, "state_story")


def act(state, target="study", mode="act", seconds=10):
    command = ActionCommand(action_id=f"act_{state['version']}_{target}", expected_world_version=state["version"],
        mode=mode, text="执行已选行动", selected_operation={"kind": "state_action", "target_id": target} if mode == "act" else None)
    cmd = command.model_dump()
    plan = explicit_goal_plan(state, cmd) or TurnPlan(intent=cmd["text"], time_cost_s=seconds)
    events, effects, _ = resolve(state, cmd, plan, {}, 7)
    result = apply_events(state, events, state["version"]+1)
    assert digest(result) == digest(apply_events(state, events, state["version"]+1))
    return result, events, effects


def test_state_chain_scope_one_time_reward_clamp_and_replay(authored):
    template = compile_authored(authored)
    assert len(audit_state_rules(template)) == 2
    start = initial_state(template, "玩家")
    assert "claim" not in {a["target_id"] for a in action_choices(start)}
    one, _, _ = act(start)
    two, events, effects = act(one)
    assert two["state_rules"]["values"]["unlocked"] is True
    assert "站长收到私人暗号" not in str(effects)
    assert "幕后路线" not in str(effects)
    assert len({e["event_id"] for e in events}) == len(events)
    assert {v["id"] for v in project(two)["custom_state"]["variables"]} == {"renown", "progress", "unlocked"}
    npc = project(two, "npc_0")
    assert {v["id"] for v in npc["custom_state"]["variables"]} == {"renown", "progress"}
    assert "星环密码" not in str(npc)
    claimed, _, _ = act(two, "claim")
    assert claimed["actor_states"][claimed["player"]]["resources"]["coins"] == 13
    with pytest.raises(DomainError):
        act(claimed, "claim")
    for _ in range(4):
        claimed, _, _ = act(claimed)
    assert claimed["state_rules"]["values"]["progress"] == 3
    assert claimed["state_rules"]["triggers"]["breakthrough"]["count"] == 1
    assert start["state_rules"]["values"]["progress"] == 0


@pytest.mark.parametrize("bad", [
    {"source": "variable", "key": "missing", "value": 0},
    {"source": "variable", "key": "unlocked", "value": 1},
    {"source": "variable", "key": "unlocked", "op": "ge", "value": True},
    {"source": "variable", "key": "hidden", "value": "unknown"},
    {"source": "resource", "key": "coins", "actor_id": "npc_0", "value": 1},
    {"source": "location", "key": None, "value": "loc_99"},
    {"source": "quest", "key": "quest_99", "value": "completed"},
    {"source": "knowledge", "key": "fact_missing", "value": True},
])
def test_invalid_references_and_condition_types_fail_before_save(authored, bad):
    world, story = authored
    value = story.state_rules.model_dump()
    value["actions"][0]["when_all"] = [bad]
    story.state_rules = StateRules.model_validate(value)
    with pytest.raises(DomainError):
        validate_story(world, story)


@pytest.mark.parametrize("change", ["bool_integer", "enum_initial", "repeat_cooldown", "effect_range", "world_story_ref", "duplicate"])
def test_invalid_types_bounds_cycles_and_cross_scope(authored, change):
    world, story = authored
    pack = story.state_rules.model_dump()
    if change == "bool_integer": pack["variables"][0]["initial"] = True
    elif change == "enum_initial": pack["variables"][2]["initial"] = "missing"
    elif change == "repeat_cooldown": pack["triggers"][0]["once"] = False
    elif change == "effect_range": pack["actions"][0]["effects"][0] = {"kind": "set", "target": "progress", "value": 999}
    elif change == "duplicate": pack["variables"][0]["id"] = "renown"
    elif change == "world_story_ref": world.state_rules = StateRules.model_validate(pack)
    with pytest.raises((ValidationError, DomainError)):
        story.state_rules = StateRules.model_validate(pack)
        compile_story(world, story, "invalid")


def test_declared_route_failure_and_missing_coverage_not_certified(authored):
    world, story = authored
    story.state_rules.tests[0].expect[0].value = 3
    with pytest.raises(DomainError, match="预期"):
        audit_state_rules(compile_authored(authored))
    story.state_rules.tests = []
    with pytest.raises(DomainError, match="覆盖"):
        audit_state_rules(compile_story(world, story, "uncovered"))


def test_cooldown_ooc_and_atomic_budget_limits(authored):
    world, story = authored
    story.state_rules.actions[0].cooldown_s = 30
    state = initial_state(compile_story(world, story, "cooldown"), "玩家")
    state, _, _ = act(state)
    with pytest.raises(DomainError): act(state)
    ooc, events, _ = act(state, mode="ooc", seconds=1800)
    assert not events and ooc["game_time_s"] == state["game_time_s"]
    state, _, _ = act(state, mode="wait", seconds=20)
    state, _, _ = act(state)
    assert state["state_rules"]["values"]["progress"] == 2
    base = story.state_rules.triggers[0].model_dump()
    base.update(when_all=[], effects=[{"kind": "message", "text": "公开通知"}]*6)
    pack = story.state_rules.model_dump()
    pack["triggers"] = [{**base, "id": f"burst_{i}"} for i in range(24)]
    story.state_rules = StateRules.model_validate(pack)
    before = initial_state(compile_story(world, story, "bounded"), "玩家")
    fingerprint = digest(before)
    with pytest.raises(DomainError, match="96"):
        act(before)
    assert digest(before) == fingerprint


def test_resource_payment_atomic_and_forged_event_rejected(authored):
    _, story = authored
    pack = story.state_rules.model_dump()
    pack["actions"][0]["effects"].append({"kind": "resource", "target": "coins", "value": -100})
    story.state_rules = StateRules.model_validate(pack)
    state = initial_state(compile_authored(authored), "玩家")
    assert not action_choices(state)
    with pytest.raises(DomainError): act(state)
    assert state["state_rules"]["values"]["progress"] == 0
    forged = {"event_id": "fake", "type": "state.variable_changed", "cause": {"kind": "actions", "id": "study"},
              "payload": {"id": "progress", "before": 0, "after": 3}, "visibility": {"kind": "public"}}
    with pytest.raises(DomainError): apply_events(state, [forged], 1)


def test_trigger_clock_threshold_and_knowledge_commit_in_same_turn(authored):
    _, story = authored
    pack = story.state_rules.model_dump()
    pack["triggers"] = [{"id": "deadline", "name": "提前到来的期限", "effects": [
        {"kind": "clock", "target": "clock_pressure", "value": 6},
        {"kind": "reveal", "target": "fact_clue_0", "actor_id": "npc_0"}]}]
    story.state_rules = StateRules.model_validate(pack)
    before = initial_state(compile_authored(authored), "玩家")
    after, _, _ = act(before)
    assert after["facts"]["fact_pressure"]["value"] == "arrived"
    assert "fact_pressure" in after["knowledge"][after["player"]]
    assert "fact_clue_0" in after["knowledge"]["npc_0"]


class Gateway:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def generate(self, role, system, data, schema, aid, budget, validate=None):
        self.calls.append((role, data))
        if self.fail:
            raise DomainError("test_failure", "模型暂时不可用")
        if role == "character_actor":
            return schema(reaction="none", text="我在这里。")
        if role == "narrator":
            return schema(text="你完成了当前行动。", suggestions=[])
        raise AssertionError(role)


def test_runtime_retry_cancel_restart_fork_backup_and_world_continuity(authored, tmp_path):
    template = compile_authored(authored)
    template["world_ref"] = {"id": "world_1", "revision": 1, "fingerprint": "same"}
    store = Store(tmp_path/"source")
    campaign = store.create_campaign("owner", template, "玩家")
    cid, bid = campaign["id"], campaign["main_branch"]
    cmd = ActionCommand(action_id="first", expected_world_version=0, text="我整理笔记。",
                        selected_operation={"kind": "state_action", "target_id": "study"})
    action, _ = store.accept(cid, bid, "owner", cmd)
    asyncio.run(Runtime(store, Gateway(fail=True)).run(action["id"]))
    assert action["status"] == "failed" and store.branches[bid]["state"]["version"] == 0
    store.update(action["id"], status="accepted")
    asyncio.run(Runtime(store, Gateway()).run(action["id"]))
    assert action["status"] == "committed"
    again, fresh = store.accept(cid, bid, "owner", cmd)
    assert not fresh and again["commit_id"] == action["commit_id"]
    cancel, _ = store.accept(cid, bid, "owner", cmd.model_copy(update={"action_id": "cancel", "expected_world_version": 1}))
    runtime = Runtime(store, Gateway())
    runtime.cancel(cancel["id"], "owner")
    asyncio.run(runtime.run(cancel["id"]))
    assert store.branches[bid]["state"]["state_rules"]["values"]["progress"] == 1
    branch = store.fork(cid, bid, "owner", 0, "之前")
    assert branch["state"]["state_rules"]["values"]["progress"] == 0
    for aid, selected in [("second", "study"), ("third", "claim")]:
        a, _ = store.accept(cid, bid, "owner", cmd.model_copy(update={"action_id": aid,
                    "expected_world_version": store.branches[bid]["state"]["version"],
                    "selected_operation": Operation(kind="state_action", target_id=selected)}))
        asyncio.run(Runtime(store, Gateway()).run(a["id"]))
        assert a["status"] == "committed"
    expected = digest(store.branches[bid]["state"])
    continuation = carry_world(template, store.branches[bid], campaign, 3)
    carried = initial_state(continuation, "玩家")
    assert carried["state_rules"]["values"] == {"renown": 1, "progress": 0, "unlocked": False, "hidden": "sealed"}
    assert not carried["state_rules"]["actions"]
    backup = json.dumps(export_campaign(store, cid, "owner"))
    store.close()
    reopened = Store(tmp_path/"source")
    assert digest(reopened.branches[bid]["state"]) == expected
    target = Store(tmp_path/"target")
    restored = restore_campaign(target, "new_owner", backup)
    assert digest(target.branches[restored["branch_id"]]["state"]) == expected
    assert restore_campaign(target, "new_owner", backup)["existing"]
    target.close(); reopened.close()


def test_npc_observes_own_state_not_player_private_trigger(authored, tmp_path):
    _, story = authored
    story.state_rules.variables[0].initial = 2
    store = Store(tmp_path)
    campaign = store.create_campaign("owner", compile_authored(authored), "玩家")
    aid, _ = store.accept(campaign["id"], campaign["main_branch"], "owner", ActionCommand(
        action_id="talk", expected_world_version=0, mode="say", text="你好。"))
    store.update(aid["id"], plan=TurnPlan(intent="问候", speakers=["npc_0"]).model_dump())
    gateway = Gateway()
    asyncio.run(Runtime(store, gateway).run(aid["id"]))
    assert aid["status"] == "committed"
    npc = next(data for role, data in gateway.calls if role == "character_actor")
    narration = next(data for role, data in gateway.calls if role == "narrator")
    assert "星环密码" not in str(npc) and "私人突破" not in str(npc)
    assert "站长收到私人暗号" in str(npc)
    assert "站长收到私人暗号" not in str(narration)
    assert "幕后路线" not in str(narration)
    store.close()


def test_semantic_repair_only_changes_whitelisted_text_and_preserves_original(authored):
    world, story = authored
    before = story.model_dump()
    repairs = TextRepairs(patches=[{"path": "/story/state_rules/variables/1/name", "text": "校准完成"},
                                  {"path": "/story/challenges/0/description", "text": "依据已知线索调查眼前的装置。"}])
    repaired = repair_text(world, story, repairs)
    assert repaired.state_rules.variables[1].name == "校准完成"
    expected = story.model_dump()
    expected["state_rules"]["variables"][1]["name"] = "校准完成"
    expected["challenges"][0]["description"] = "依据已知线索调查眼前的装置。"
    assert repaired.model_dump() == expected and story.model_dump() == before
    for path in ("/story/state_rules/variables/0/initial", "/story/state_rules/actions/0/effects/0/value", "/story/clues/0/text", "/story/starting_item"):
        with pytest.raises(DomainError, match="不能改写规则"):
            repair_text(world, story, TextRepairs(patches=[{"path": path, "text": "999"}]))
        with pytest.raises(ValidationError):
            repair_schema(story)(patches=[{"path": path, "text": "999"}])
    repair_schema(story).model_validate(repairs.model_dump())
    assert not ContentReview(checks=[{"verdict": "pass", "kind": "unmodeled_dependency", "path": "/challenges/1",
                                     "explanation": "线索是证据，不要求持有实物。"}]).issues


@pytest.mark.parametrize("always_fail", [False, True])
def test_semantic_review_rechecks_repairs_and_stops_on_persistent_mismatch(authored, always_fail):
    world, story = authored
    calls = []

    async def generate(role, system, data, schema, jid, validator):
        if schema.__name__ == "DirectClaims":
            return schema(claims=[{"index": 0, "explicit": True, "reason": "Fixture confirms candidate"}])
        calls.append(role)
        if role == "content_reviewer":
            return ContentReview(checks=[{"verdict": "fix", "kind": "unsupported_item", "path": "/story/state_rules/variables/1/name",
                        "quote": data["story"]["state_rules"]["variables"][1]["name"],
                        "explanation": "物品持有不能由开关代替"}]) if always_fail or len(calls) == 1 else ContentReview()
        patches = TextRepairs(patches=[{"path": "/story/state_rules/variables/1/name", "text": "校准完成"}])
        validator(patches)
        return patches

    if always_fail:
        with pytest.raises(DomainError, match="内容与机制不一致"):
            asyncio.run(review_story(world, story, generate, "test", repair=True))
        assert calls.count("content_reviewer") == 3 and calls.count("state_builder") == 2
    else:
        changed, report = asyncio.run(review_story(world, story, generate, "test", repair=True))
        assert changed.state_rules.variables[1].name == "校准完成"
        assert report["repair_rounds"] == 1
        assert report["previous_issue_kinds"] == ["unsupported_item"]
    assert story.state_rules.variables[1].name == "私人突破"


def test_review_requires_literal_evidence_and_real_text_path():
    data = {"story": {"actions": [{"text": "钥匙的位置已经确认。"}]}}
    finding = {"verdict": "fix", "kind": "unsupported_item", "path": "/story/actions/0/text",
               "quote": "钥匙的位置", "explanation": "Fixture evidence validation only"}
    validate_review(ContentReview(checks=[finding]), data)
    with pytest.raises(ValidationError):
        review_schema(data)(checks=[{**finding, "path": "/story/actions/0"}])
    for change in ({"quote": "钥匙落入你的手中"}, {"quote": ""}, {"path": "/story/actions/-1/text"},
                   {"path": "/story/actions/0"}, {"path": "story.actions[0].text"}, {"path": "/story/missing"}):
        with pytest.raises(DomainError, match="审核"):
            validate_review(ContentReview(checks=[{**finding, **change}]), data)


@pytest.mark.parametrize("verdict", ["confirmed", "rejected", "missing_index"])
def test_review_entailment_cannot_omit_candidates_or_repair_rejected_advice(authored, verdict):
    world, story = authored

    async def generate(role, system, data, schema, jid, validator):
        if schema.__name__ == "DirectClaims":
            result = schema(claims=[{"index": 1 if verdict == "missing_index" else 0,
                                    "explicit": verdict == "confirmed", "reason": "独立核对依据"}])
        else:
            result = schema(checks=[{"verdict": "fix", "kind": "unsupported_item",
                                    "path": "/story/state_rules/variables/1/name", "quote": "私人突破",
                                    "explanation": "待核对意见"}])
        validator(result)
        return result

    if verdict == "missing_index":
        with pytest.raises(DomainError, match="恰好核对一次"):
            asyncio.run(assess_content(world, story, generate, "test"))
    else:
        review, rejected = asyncio.run(assess_content(world, story, generate, "test"))
        assert len(review.issues) == (verdict == "confirmed")
        assert len(rejected) == (verdict == "rejected")
        if rejected:
            assert rejected[0]["reason"] == "独立核对依据"
