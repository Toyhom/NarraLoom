from copy import deepcopy

import pytest

from roleplay_world.catalog import load_catalog
from roleplay_world.content import StoryBlueprint, WorldBlueprint, compile_story
from roleplay_world.contracts import ActionCommand, ActorReply, DomainError, Operation, TurnPlan
from roleplay_world.journal import digest
from roleplay_world.planning import explicit_goal_plan, normalize_plan, validate_plan
from roleplay_world.rulepacks import RuleSet, extra_choices
from roleplay_world.rules import resolve
from roleplay_world.store import Store
from roleplay_world.world import apply_events, initial_state, project


@pytest.fixture
def game_template():
    pack = load_catalog()["apartment-5c"]
    world = WorldBlueprint.model_validate(pack["world"])
    world.rules = RuleSet.model_validate({
        "system": "d20", "coins": 20, "hp": 20, "damage": 3, "recruitable": [2],
        "items": [{"id": "potion", "name": "恢复药", "kind": "consumable", "price": 3, "power": 8},
                  {"id": "sword", "name": "练习剑", "kind": "weapon", "price": 6, "power": 3},
                  {"id": "armor", "name": "皮甲", "kind": "armor", "price": 5, "power": 2}],
        "starting_items": [{"item_id": "potion", "quantity": 2}, {"item_id": "sword"},
                           {"item_id": "armor", "holder": "loc_0", "quantity": 2}],
        "shops": [{"id": "shop", "name": "补给站", "location": 0,
                   "stock": [{"item_id": "potion", "quantity": 3}, {"item_id": "sword", "quantity": 1}]}],
        "enemies": [{"id": "dummy", "name": "训练傀儡", "location": 1, "hp": 5, "defense": 5,
                     "damage": 3, "reward_coins": 4, "reward_xp": 6}]})
    return compile_story(world, StoryBlueprint.model_validate(pack["story"]), "game")


def act(state, kind, target, item=None, quantity=1, replies=None, seed=1):
    command = {"action_id": f"test_{state['version']}_{kind}", "mode": "act", "text": "执行选定行动"}
    op = Operation(kind=kind, target_id=target, item_id=item, quantity=quantity)
    plan = normalize_plan(state, command, TurnPlan(intent="操作", operations=[op]))
    validate_plan(state, command, plan)
    events, effects, roll = resolve(state, command, plan, replies or {}, seed)
    result = apply_events(state, events, state["version"]+1)
    assert digest(result) == digest(apply_events(state, events, state["version"]+1))
    return result, events, effects, roll


def test_trade_conserves_money_items_stock_and_rejects_overdraw(game_template):
    state = initial_state(game_template, "玩家")
    pc = state["player"]
    bought, _, _, _ = act(state, "buy", "shop", "potion", quantity=2)
    assert bought["actor_states"][pc]["resources"]["coins"] == 14
    assert bought["shops"]["shop"]["stock"][0]["quantity"] == 1
    loot = next(i for i in bought["items"] if i.startswith("loot_"))
    assert bought["items"][loot]["quantity"] == 2
    sold, _, _, _ = act(bought, "sell", "shop", loot)
    assert sold["actor_states"][pc]["resources"]["coins"] == 15
    assert sold["items"][loot]["quantity"] == 1
    assert sold["shops"]["shop"]["stock"][0]["quantity"] == 2
    before = digest(sold)
    with pytest.raises(DomainError):act(sold, "buy", "shop", "potion", quantity=99)
    with pytest.raises(DomainError):act(sold, "sell", "shop", loot, quantity=99)
    assert digest(sold) == before


def test_consumable_equipment_pickup_and_partial_gift(game_template):
    state = initial_state(game_template, "玩家")
    pc = state["player"]
    state["actor_states"][pc]["resources"]["hp"] = 5
    state, _, _, _ = act(state, "use", pc, "gear_0")
    assert state["actor_states"][pc]["resources"]["hp"] == 13
    assert state["items"]["gear_0"]["quantity"] == 1
    state, _, _, _ = act(state, "equip", pc, "gear_1")
    assert state["actor_states"][pc]["equipment"]["weapon"] == "gear_1"
    with pytest.raises(DomainError):act(state, "sell", "shop", "gear_1")
    state, _, _, _ = act(state, "unequip", pc, "gear_1")
    state, _, _, _ = act(state, "sell", "shop", "gear_1")
    assert state["items"]["gear_1"]["quantity"] == 0
    state, _, _, _ = act(state, "take", pc, "gear_2", quantity=1)
    assert state["items"]["gear_2"]["quantity"] == 1
    armor = next(i for i in state["items"].values() if i["holder_id"] == pc and i.get("kind") == "armor")
    state, _, _, _ = act(state, "give", "npc_2", armor["id"], replies={"npc_2": ActorReply(reaction="accept", text="谢谢")})
    assert state["items"][armor["id"]]["holder_id"] == "npc_2"
    assert sum(i["quantity"] for i in state["items"].values() if i.get("catalog_id") == "armor") == 2


def test_party_requires_consent_and_follows_with_independent_state(game_template):
    state = initial_state(game_template, "玩家")
    pc = state["player"]
    refused, _, _, _ = act(state, "recruit", "npc_2", replies={"npc_2": ActorReply(reaction="refuse", text="我留在这里")})
    assert refused["party"] == [pc]
    joined, _, _, _ = act(refused, "recruit", "npc_2", replies={"npc_2": ActorReply(reaction="accept", text="我愿同行")})
    assert joined["party"] == [pc, "npc_2"]
    moved, _, _, _ = act(joined, "move", "loc_1")
    assert moved["actor_states"]["npc_2"]["location_id"] == "loc_1"
    assert joined["actor_states"]["npc_2"]["location_id"] == "loc_0"
    left, _, _, _ = act(moved, "dismiss", "npc_2")
    assert left["party"] == [pc]


@pytest.mark.parametrize("system", ["d20", "d100"])
def test_combat_determinism_reward_once_and_defeat_recovery(game_template, system):
    game_template["mechanics"]["rules"]["system"] = system
    state = initial_state(game_template, "玩家")
    pc = state["player"]
    state, _, _, _ = act(state, "equip", pc, "gear_1")
    state, _, _, _ = act(state, "move", "loc_1")
    won, events, _, roll = act(state, "attack", "enemy_dummy", seed=1)
    assert roll["passed"] and won["actor_states"]["enemy_dummy"]["resources"]["hp"] == 0
    assert won["actor_states"][pc]["resources"]["xp"] == 6
    assert won["actor_states"][pc]["resources"]["coins"] == 24
    assert not any(o["kind"] == "attack" for o in extra_choices(won))
    with pytest.raises(DomainError):act(won, "attack", "enemy_dummy")
    assert digest(won) == digest(apply_events(state, events, won["version"]))
    knocked = deepcopy(state)
    knocked["actor_states"][pc]["resources"]["hp"] = 0
    recovered, _, _, _ = act(knocked, "recover", pc)
    assert recovered["actor_states"][pc]["resources"]["hp"] == 20
    assert recovered["actor_states"][pc]["location_id"] == "loc_0"
    assert recovered["actor_states"][pc]["resources"]["coins"] == 17
    assert recovered["game_time_s"]-knocked["game_time_s"] == 1800


def test_combat_counterattack_and_equipment_affect_damage(game_template):
    game_template["mechanics"]["rules"]["enemies"][0].update(hp=100, attack_bonus=12)
    game_template["actors"][-1]["initial_state"].update(resources={"hp": 100}, resource_limits={"hp": 100})
    state = initial_state(game_template, "玩家")
    state, _, _, _ = act(state, "move", "loc_1")
    after, _, _, roll = act(state, "attack", "enemy_dummy", seed=1)
    assert roll["counterattack"]["passed"]
    assert after["actor_states"][state["player"]]["resources"]["hp"] == 17
    assert after["actor_states"]["enemy_dummy"]["resources"]["hp"] == 97


def test_rule_events_roundtrip_store_branch_and_selected_action_idempotency(tmp_path, game_template):
    store = Store(tmp_path)
    c = store.create_campaign("owner", game_template, "玩家")
    cid, bid = c["id"], c["main_branch"]
    command = ActionCommand(action_id="selected_buy", expected_world_version=0, text="购买两份恢复药",
                            selected_operation={"kind": "buy", "target_id": "shop", "item_id": "potion", "quantity": 2})
    a, _ = store.accept(cid, bid, "owner", command)
    plan = explicit_goal_plan(store.branches[bid]["state"], a["command"])
    events, effects, roll = resolve(store.branches[bid]["state"], a["command"], plan, {}, a["seed"])
    store.commit(a["id"], events, [], effects, [], roll)
    saved = deepcopy(project(store.branches[bid]["state"]))
    fork = store.fork(cid, bid, "owner", 0, "购买前")
    assert fork["state"]["actor_states"]["pc_traveler"]["resources"]["coins"] == 20
    assert not store.accept(cid, bid, "owner", command)[1]
    store.close()
    replay = Store(tmp_path)
    assert project(replay.branches[bid]["state"]) == saved
    assert not replay.accept(cid, bid, "owner", command)[1]
    replay.close()


def test_legacy_action_hash_remains_identical_without_selected_operation(tmp_path, template):
    store = Store(tmp_path)
    c = store.create_campaign("owner", template, "玩家")
    command = ActionCommand(action_id="old", expected_world_version=0, text="你好")
    a, _ = store.accept(c["id"], c["main_branch"], "owner", command)
    assert "selected_operation" not in a["command"]
    expected = {"schema_version": "0.1.0", "action_id": "old", "expected_world_version": 0,
                "mode": "act", "text": "你好"}
    assert a["request_hash"] == digest(expected)
    store.close()


def test_generated_content_rule_audit(game_template):
    from roleplay_world.quality import audit_template
    checks = audit_template(game_template)
    assert checks[-1]['name'] == '冒险规则与确定性回放'
    assert all(c['status'] == 'passed' for c in checks)


def test_recovery_moves_followers_and_pickup_has_effect(game_template):
    state = initial_state(game_template, '玩家')
    state, _, effects, _ = act(state, 'take', state['player'], 'gear_2', quantity=1)
    assert any('拾取' in effect for effect in effects)
    state['party'].append('npc_2')
    state['actor_states'][state['player']]['location_id'] = 'loc_1'
    state['actor_states']['npc_2']['location_id'] = 'loc_1'
    state['actor_states'][state['player']]['resources']['hp'] = 0
    state, _, _, _ = act(state, 'recover', state['player'])
    assert state['actor_states']['npc_2']['location_id'] == 'loc_0'


def test_rules_generation_choice_and_zero_effect_validation():
    from pydantic import ValidationError

    from roleplay_world.content import CreateWorld, world_generation_schema
    from roleplay_world.rulepacks import validate_rules
    assert CreateWorld(prompt='一个繁忙的集市', rules_mode='d100').rules_mode == 'd100'
    with pytest.raises(ValidationError):
        CreateWorld(prompt='一个繁忙的集市', rules_mode='javascript')
    assert world_generation_schema().model_json_schema()['properties']['rules']['type'] == 'null'
    with pytest.raises(DomainError):
        validate_rules(RuleSet(items=[{'id':'empty','name':'空药','kind':'consumable'}]), 4, 3)


def test_goal_reward_once_and_no_failed_reward(game_template):
    goal = game_template['mechanics']['challenges'][-1]
    goal.update(reward_coins=7, reward_xp=9, skill='none')
    state = initial_state(game_template, '玩家')
    state['actor_states'][state['player']]['location_id'] = goal['location_id']
    for fid in goal['required_facts']:
        state['knowledge'][state['player']].append(fid)
        state['beliefs'][state['player']][fid] = deepcopy(state['facts'][fid])
    after, _, _, _ = act(state, 'challenge', goal['id'])
    assert after['actor_states'][state['player']]['resources']['coins'] == 27
    assert after['actor_states'][state['player']]['resources']['xp'] == 9
    with pytest.raises(DomainError):
        act(after, 'challenge', goal['id'])
    game_template['mechanics']['challenges'][-1]['skill'] = 'craft'
    game_template['mechanics']['challenges'][-1]['difficulty'] = 100
    state = initial_state(game_template, '玩家')
    state['actor_states'][state['player']]['location_id'] = goal['location_id']
    for fid in goal['required_facts']:
        state['knowledge'][state['player']].append(fid)
        state['beliefs'][state['player']][fid] = deepcopy(state['facts'][fid])
    after, _, _, roll = act(state, 'challenge', goal['id'])
    assert not roll['passed'] and after['actor_states'][state['player']]['resources']['xp'] == 0
