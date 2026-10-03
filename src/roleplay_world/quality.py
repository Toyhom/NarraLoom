"""Content-derived functional checks and live playthroughs, isolated from player saves."""

import logging
from collections import deque

from .action_modules import ActionRegistry, audit_modules, schema_check, test_view
from .checks import builtin_checks
from .content_preferences import content_text
from .contracts import ActionCommand, ActorReply, TurnPlan
from .journal import digest
from .planning import normalize_plan, validate_plan
from .rulepacks import RuleSet, validate_rules
from .rules import resolve
from .runtime import Runtime
from .state_rules import audit_state_rules, evaluate, test_command
from .store import Store, uid
from .world import apply_events, initial_state, project


def route(template, start, target):
    places = {p["id"]: p for p in template["locations"]}
    queue = deque([(start, [])])
    visited = {start}
    while queue:
        node, path = queue.popleft()
        if node == target:
            return path
        for edge in places[node]["exits"]:
            if edge["to"] not in visited:
                visited.add(edge["to"])
                queue.append((edge["to"], [*path, edge["to"]]))
    raise ValueError("目标地点不可达")


def audit_template(template, *, check_registry=None, action_registry=None):
    """Every clue/goal/route checked from this generated content, no Fogharbor IDs."""
    state = initial_state(template, "自动检查旅人")
    registry = check_registry or builtin_checks()
    registry.validate_template(template)
    registry.verify(template['mechanics'].get('checks'))
    checks = audit_modules(template, action_registry or ActionRegistry())

    def ok(name, detail):
        checks.append({"name": name, "status": "passed", "detail": detail})

    if template['mechanics'].get('checks'):
        ok('检定引擎契约', '技能、攻击和反击的类型、算术与固定种子重复结果通过')

    start = state["actor_states"][state["player"]]["location_id"]
    for place in template["locations"]:
        route(template, start, place["id"])
        route(template, place["id"], start)
    ok("地图连通", f"{len(template['locations'])} 个地点均可到达并返回")
    view = project(state)
    assert all(f["id"] in state["knowledge"][state["player"]] for f in view["known_facts"])
    assert not any(f["id"].startswith("fact_secret_") for f in view["known_facts"])
    ok("秘密与角色视角", "玩家不会在开场取得 NPC 私有秘密")
    version = 0
    for fact in template["facts"]:
        if not fact.get("discoverable_at"):
            continue
        place = fact["discoverable_at"][0]
        state["actor_states"][state["player"]]["location_id"] = place
        command = {"action_id": uid("probe"), "mode": "act", "text": "调查"}
        plan = TurnPlan(intent="调查", operations=[{"kind": "reveal", "target_id": fact["id"]}])
        events, _, _ = resolve(state, command, plan, {}, 7, check_registry=check_registry)
        version += 1
        state = apply_events(state, events, version)
        assert fact["id"] in state["knowledge"][state["player"]]
    clue_count = sum(bool(f.get("discoverable_at")) for f in template["facts"])
    checks.append({"name": "线索可获取", "status": "passed" if clue_count else "skipped",
                   "detail": f"已检查 {clue_count} 条可调查线索"})
    for c in template["mechanics"].get("challenges", []):
        state["actor_states"][state["player"]]["location_id"] = c["location_id"]
        command = {"action_id": uid("probe"), "mode": "act", "text": c["name"]}
        plan = normalize_plan(
            state, command, TurnPlan(intent=c["name"], operations=[{"kind": "challenge", "target_id": c["id"]}])
        )
        validate_plan(state, command, plan)
        # Seed enumeration is only for this isolated test, never a retry of a player's roll.
        for seed in range(100):
            events, _, roll = resolve(state, command, plan, {}, seed, check_registry=check_registry)
            if not roll or roll["passed"]:
                break
        replay1 = apply_events(state, events, state["version"] + 1)
        replay2 = apply_events(state, events, state["version"] + 1)
        assert digest(replay1) == digest(replay2)
        assert replay1["quests"][c["quest_id"]]["status"] == "completed"
        ok("目标可完成：" + c["name"], "前提可满足，事件回放一致")
    # Exercise an actual refusal on a fresh state; the offered object stays owned by the player.
    initial = initial_state(template, "检查旅人")
    npc = next((a for a in initial["actors"] if a != initial["player"]), None)
    item = next((i for i in initial["items"].values() if i["holder_id"] == initial["player"]), None)
    if npc and item:
        initial["actor_states"][initial["player"]]["location_id"] = initial["actor_states"][npc]["location_id"]
        plan = TurnPlan(intent="赠送", operations=[{"kind": "give", "target_id": npc, "item_id": item["id"]}])
        events, _, _ = resolve(
            initial,
            {"action_id": uid("probe"), "mode": "act", "text": "赠送"},
            plan,
            {npc: ActorReply(reaction="refuse", text="请你留着。")},
            1,
            check_registry=check_registry,
        )
        assert apply_events(initial, events, 1)["items"][item["id"]]["holder_id"] == initial["player"]
        ok("拒绝与物品归属", "拒绝后物品仍属于玩家")
    else:
        checks.append({"name": "拒绝与物品归属", "status": "skipped", "detail": "本故事没有可赠送的初始物品"})
    if template["mechanics"].get("rules"):
        checks.extend(audit_rules(template, check_registry=check_registry))
    checks.extend(audit_state_rules(template, check_registry=check_registry))
    return checks


def audit_rules(template, *, check_registry=None):
    """Exercise each authored catalog/foe in isolated preconditions, without charging an API."""
    cfg = RuleSet.model_validate(template["mechanics"]["rules"])
    npc_count = sum(a["id"].startswith("npc_") for a in template["actors"])
    validate_rules(cfg, len(template["locations"]), npc_count)
    base = initial_state(template, "规则检查旅人")
    pc = base["player"]

    def exercise(state, kind, target, item=None, replies=None):
        command = {"action_id": uid("rules_probe"), "mode": "act", "text": "自动检查"}
        plan = normalize_plan(state, command, TurnPlan(
            intent="自动检查", operations=[{"kind": kind, "target_id": target, "item_id": item}]))
        validate_plan(state, command, plan)
        events, _, _ = resolve(state, command, plan, replies or {}, 3, check_registry=check_registry)
        after = apply_events(state, events, state["version"]+1)
        assert digest(after) == digest(apply_events(state, events, state["version"]+1))
        return after

    traded = 0
    for shop in cfg.shops:
        for stock in shop.stock:
            if stock.quantity == 0:
                continue
            state = initial_state(template, "检查交易")
            own = state["actor_states"][pc]
            own["location_id"] = f"loc_{shop.location}"
            own["resources"]["coins"] = 10000
            gear = next(g for g in cfg.items if g.id == stock.item_id)
            bought = exercise(state, "buy", shop.id, gear.id)
            assert bought["actor_states"][pc]["resources"]["coins"] == 10000-gear.price
            received = next(i for i in bought["items"].values() if i["id"] not in state["items"])
            assert received["quantity"] == 1 and received["catalog_id"] == gear.id
            actual = next(s for s in bought["shops"][shop.id]["stock"] if s["item_id"] == gear.id)
            assert actual["quantity"] == stock.quantity-1
            if gear.kind in {"weapon", "armor"}:
                equipped = exercise(bought, "equip", pc, received["id"])
                assert equipped["actor_states"][pc]["equipment"][gear.kind] == received["id"]
            elif gear.kind == "consumable":
                baseline = 1 if gear.restores == "hp" else 0
                if bought["actor_states"][pc]["resource_limits"][gear.restores] > baseline:
                    bought["actor_states"][pc]["resources"][gear.restores] = baseline
                    used = exercise(bought, "use", pc, received["id"])
                    assert used["actor_states"][pc]["resources"][gear.restores] > baseline
                    assert used["items"][received["id"]]["quantity"] == 0
            traded += 1
    for enemy in cfg.enemies:
        state = initial_state(template, "检查战斗")
        state["actor_states"][pc]["location_id"] = f"loc_{enemy.location}"
        after = exercise(state, "attack", "enemy_"+enemy.id)
        assert 0 <= after["actor_states"][pc]["resources"]["hp"] <= cfg.hp
        assert 0 <= after["actor_states"]["enemy_"+enemy.id]["resources"]["hp"] <= enemy.hp
    for index in cfg.recruitable:
        state = initial_state(template, "检查队伍")
        npc = f"npc_{index}"
        state["actor_states"][pc]["location_id"] = state["actor_states"][npc]["location_id"]
        if cfg.party_limit > 1:
            refused = exercise(state, "recruit", npc, replies={npc: ActorReply(reaction="refuse", text="暂不同行。")})
            assert npc not in refused["party"]
    return [{"name": "冒险规则与确定性回放", "status": "passed",
             "detail": f"{len(cfg.items)} 件道具引用、{traded} 项独立交易/装备/消耗检查、{len(cfg.enemies)} 个敌人的单轮战斗、同行拒绝；使用隔离前提，不代表全战役平衡"}]


async def playtest(template, gateway, root, progress, *, check_registry=None, action_registry=None):
    mode = getattr(gateway, "verification_mode", "live_models")
    checks = audit_template(template, check_registry=check_registry, action_registry=action_registry)
    language = template.get("content_language", "zh-CN")
    def text(zh, en):
        return content_text(language, zh, en)
    await progress(checks)
    store = Store(root, check_registry=check_registry, action_registry=action_registry)
    runtime = Runtime(store, gateway)
    c = store.create_campaign("autotest", template, text("自动试跑旅人", "Playtest traveler"))
    cid, bid = c["id"], c["main_branch"]
    live_steps = []

    async def turn(text, mode="act", assertion=None, selected_operation=None, seed=None):
        state = store.branches[bid]["state"]
        command = ActionCommand(action_id=uid("qa"), expected_world_version=state["version"], mode=mode, text=text,
                                selected_operation=selected_operation)
        a, _ = store.accept(cid, bid, "autotest", command)
        if seed is not None:
            store.update(a['id'], seed=seed)
        await runtime.run(a["id"])
        a = store.actions[a["id"]]
        if a["status"] != "committed":
            raise ValueError(a.get("error", "模型行动未完成"))
        state = store.branches[bid]["state"]
        if assertion:
            assertion(state)
        same, fresh = store.accept(cid, bid, "autotest", command)
        assert not fresh and same["commit_id"] == a["commit_id"]
        live_steps.append(
            {"input": text, "version": state["version"], "status": "passed", "effects": a["result"]["effects"]}
        )
        await progress(checks, live_steps)

    def at(state, place):
        assert state["actor_states"][state["player"]]["location_id"] == place, "自然语言移动没有到达指定地点"

    async def travel(target):
        state = store.branches[bid]["state"]
        start = state["actor_states"][state["player"]]["location_id"]
        for place in route(template, start, target):
            name = state["locations"][place]["name"]
            await turn(text(f"我前往{name}，向那里的人打听消息。", f"I go to {name} and ask the people there for news."), assertion=lambda s, p=place: at(s, p))

    try:
        await turn(text("我向在场的人打招呼，问这里有什么需要我帮忙的。",
                        "I greet the people here and ask if they need any help."), "say")
        ending = next((c for c in template["mechanics"]["challenges"] if c["ending"] and c["skill"] == "none"), None)
        current = store.branches[bid]["state"]["actor_states"][store.branches[bid]["state"]["player"]]["location_id"]
        destination = next((p["id"] for p in template["locations"] if p["id"] != current), None)
        if destination:
            await travel(destination)
        sample_clue = next((f["id"] for f in template["facts"] if f.get("discoverable_at")), None)
        clues = ([sample_clue] if sample_clue else []) + (ending["required_facts"] if ending else [])
        for fid in dict.fromkeys(clues):
            fact = next(f for f in template["facts"] if f["id"] == fid)
            await travel(fact["discoverable_at"][0])

            def learned(s, fact_id=fid):
                assert fact_id in s["knowledge"][s["player"]], "调查没有产生预期的线索发现"

            await turn(text(f"我仔细调查这里的「{fact['name']}」，寻找相关线索。",
                            f"I carefully investigate {fact['name']} here, looking for evidence."), assertion=learned)
        if ending:
            await travel(ending["location_id"])

            def completed(s):
                assert s["quests"][ending["quest_id"]]["status"] == "completed", "目标没有实际完成"

            await turn(text(f"我决定完成「{ending['name']}」：{ending['description']}",
                            f"I decide to complete {ending['name']}: {ending['description']}"), assertion=completed)
        else:
            await turn(text("我仔细观察周围，暂不做决定。", "I look around carefully without making a decision."))
            checks.append({"name": "结局路线", "status": "skipped", "detail": "开放式故事未声明任务或结局"})
        before = store.branches[bid]["state"]["game_time_s"]
        await turn(text("游戏外：简单解释我刚才的行动。", "Out of character: briefly explain my last action."), "ooc")
        assert store.branches[bid]["state"]["game_time_s"] == before
        await turn(text("我等待两分钟。", "I wait for two minutes."), "wait")
        assert store.branches[bid]["state"]["game_time_s"] == before + 120
        branch = store.fork(cid, bid, "autotest", 0, "自动检查分支")
        assert branch["state"]["game_time_s"] == 0
        scenarios = template["mechanics"].get("state_rules", {}).get("tests", [])
        if scenarios:
            bid = branch["id"]
            scenario = scenarios[0]
            for step in scenario["steps"]:
                cmd = test_command(step, store.branches[bid]["state"], uid("qa_state"))
                await turn(cmd.text, cmd.mode, selected_operation=cmd.selected_operation)
            assert all(evaluate(store.branches[bid]["state"], c) for c in scenario["expect"]), "真实状态路线没有达到作者声明结果"
            checks.append({"name": "自定义状态真实模型路线", "status": "passed",
                           "detail": f"真实模型执行首条声明路线「{scenario['name']}」，其余路线由确定性规则检查覆盖"})
        for binding in template['mechanics'].get('action_modules', []):
            branch = store.fork(cid, c['main_branch'], 'autotest', 0, 'Module test: ' + binding['id'])
            bid = branch['id']
            scenario = store.action_registry.test_cases(binding)[0]
            for step in scenario.steps:
                await turn(scenario.name, selected_operation={
                    'kind': 'module', 'target_id': binding['id'],
                    'action_id': step.action_id, 'parameters': step.parameters}, seed=scenario.seed)
            schema_check(scenario.expect, test_view(store.branches[bid]['state'], binding['id']))
            checks.append({'name': 'Action module model route: ' + binding['id'], 'status': 'passed',
                           'detail': 'First host route executed through runtime, narration and idempotent receipts'})
        checks.append(
            {
                "name": "真实模型端到端",
                "status": "passed",
                "detail": f"{len(live_steps)} 次实际行动；按内容测试可用的转场/线索/结局。所有故事检查交流、游戏外、等待、去重与分支。",
            }
        )
        return {"status": "passed", "checks": checks, "steps": live_steps, "mode": mode, "content_language": language}
    except Exception as exc:
        logging.getLogger(__name__).exception("Content playtest failed")
        checks.append({"name": "真实模型端到端", "status": "failed", "detail": str(exc)[:300]})
        return {"status": "failed", "checks": checks, "steps": live_steps, "mode": mode, "content_language": language}
    finally:
        await runtime.close()
        store.close()
