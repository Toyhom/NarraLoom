import json

import pytest

from roleplay_world.contracts import ActorReply, DomainError, TurnPlan
from roleplay_world.journal import digest
from roleplay_world.rules import resolve
from roleplay_world.world import apply_events, npc_context, project


def give_plan():
    return TurnPlan(intent="赠送工具", time_cost_s=60,
                    operations=[{"kind": "give", "target_id": "npc_captain", "item_id": "item_tools"}],
                    speakers=["npc_captain"])


def cmd(text="给船长工具"):
    return {"action_id": "a1", "text": text, "mode": "act"}


def test_transfer_replay_and_npc_knowledge(state):
    before = digest(state)
    events, effects, roll = resolve(state, cmd(), give_plan(),
                                   {"npc_captain": ActorReply(text="谢谢，我愿意收下。", reaction="accept")}, 1)
    after = apply_events(state, events, 1)
    assert digest(state) == before
    assert after["items"]["item_tools"]["holder_id"] == "npc_captain"
    assert after["clocks"]["clock_repair"]["value"] == 1
    assert after["relations"][0]["dimensions"]["trust"] == 1
    assert project(after)["inventory"] == []
    assert "trust" not in json.dumps(project(after))
    assert after["knowledge"]["npc_engineer"] == state["knowledge"]["npc_engineer"]
    assert roll is None and effects
    with pytest.raises(DomainError):
        resolve(after, cmd(), give_plan(), {"npc_captain": ActorReply(text="收下", reaction="accept")}, 1)


def test_refused_trade_has_no_transfer(state):
    events, _, _ = resolve(state, cmd(), give_plan(),
                           {"npc_captain": ActorReply(text="先留着吧。", reaction="refuse")}, 1)
    after = apply_events(state, events, 1)
    assert after["items"]["item_tools"]["holder_id"] == state["player"]
    assert after["clocks"]["clock_repair"]["value"] == 0


def test_secret_filtered_from_player_and_other_npc(state):
    assert "warehouse_to_ridge" not in json.dumps(project(state))
    assert "走私者" not in json.dumps(npc_context(state, "npc_captain", "你好", []), ensure_ascii=False)
    assert "走私者" in json.dumps(npc_context(state, "npc_keeper", "你好", []), ensure_ascii=False)
    plan = TurnPlan(intent="偷看秘密", operations=[{"kind": "reveal", "target_id": "fact_smuggler_route"}])
    with pytest.raises(DomainError):
        resolve(state, cmd(), plan, {}, 1)


def test_unknown_npc_cannot_reveal_secret(state):
    with pytest.raises(DomainError):
        resolve(state, cmd(), TurnPlan(intent="聊天"),
                {"npc_captain": ActorReply(text="我知道", reveal_fact_ids=["fact_smuggler_route"])}, 1)


def test_npc_can_share_clock_fact_from_its_current_turn_preview(state):
    from roleplay_world.planning import actor_schema

    fact = 'fact_tide_rising'
    for actor in [state['player'], 'npc_captain']:
        state['knowledge'][actor].remove(fact)
        state['beliefs'][actor].pop(fact)
    state['clocks']['clock_tide']['value'] = 3
    state['game_time_s'] = 590
    plan = TurnPlan(intent='Talk while the tide changes', time_cost_s=30)
    command = {**cmd(), 'mode': 'say'}
    preview, _, _ = resolve(state, command, plan, {}, 1)
    observed = apply_events(state, preview, 1)
    reply = actor_schema(observed, 'npc_captain', []).model_validate(
        {'text': 'The tide is high now.', 'reaction': 'none', 'reveal_fact_ids': [fact]})
    events, _, _ = resolve(state, command, plan, {'npc_captain': reply}, 1)
    final = apply_events(state, events, 1)
    assert final['beliefs'][state['player']][fact]['value'] == 'high_tide'
    assert digest(final) == digest(observed)


def test_movement_and_tide_are_persistent(state):
    plan = TurnPlan(intent="去灯塔", operations=[{"kind": "move", "target_id": "loc_lighthouse"}])
    events, _, _ = resolve(state, cmd(), plan, {}, 1)
    state = apply_events(state, events, 1)
    assert state["game_time_s"] == 300
    plan = TurnPlan(intent="等待半小时", time_cost_s=1800)
    events, _, _ = resolve(state, cmd(), plan, {}, 1)
    state = apply_events(state, events, 2)
    assert state["clocks"]["clock_tide"]["value"] == 4
    assert state["facts"]["fact_tide_rising"]["value"] == "high_tide"
    events, _, _ = resolve(state, cmd(), plan, {}, 1)
    assert not any(e["type"] == "fact.updated" for e in events)


def test_roll_reuses_seed_and_failed_check_does_not_reveal(state):
    state["actor_states"][state["player"]]["location_id"] = "loc_warehouse"
    plan = TurnPlan(intent="观察脚印", check={"skill": "observation", "difficulty": 20, "purpose": "观察脚印"},
                    operations=[{"kind": "reveal", "target_id": "fact_wet_tracks", "when": "success"}])
    e1, _, r1 = resolve(state, cmd(), plan, {}, 1)
    e2, _, r2 = resolve(state, cmd(), plan, {}, 1)
    assert r1 == r2 and not r1["passed"]
    assert e1 == e2 and not any(e["type"] == "knowledge.learned" for e in e1)


def test_ooc_cannot_change_world(state):
    with pytest.raises(DomainError):
        resolve(state, {**cmd(), "mode": "ooc"}, give_plan(), {}, 1)
    events, _, _ = resolve(state, {**cmd(), "mode": "ooc"}, TurnPlan(intent="解释规则"), {}, 1)
    assert events == []


def test_changed_truth_does_not_update_absent_npc_beliefs(state):
    event = {"event_id": "repair_finished", "type": "fact.updated",
             "payload": {"fact_id": "fact_ship_damaged", "before": "needs_repair", "after": "repaired"}}
    updated = apply_events(state, [event], 1)
    assert updated["facts"]["fact_ship_damaged"]["value"] == "repaired"
    engineer = project(updated, "npc_engineer")
    assert next(f for f in engineer["known_facts"] if f["id"] == "fact_ship_damaged")["text"] == "码头的小船漏水，仍需要修理。"
    assert not any(c["id"] == "clock_repair" for c in engineer["visible_clocks"])
