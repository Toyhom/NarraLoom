"""Bounded story-lite rules. The model selects actions; code owns consequences."""

import hashlib
import random
from copy import deepcopy

from .content_preferences import content_language, content_text
from .contracts import DomainError
from .players import command_player, followers, human_players
from .rulepacks import EXTRA_KINDS, resolve_extra, rules_config
from .state_rules import advance_triggers, resolve_action
from .world import apply_events, fact_text, present


def resolve(state, command, plan, replies, seed):
    state = deepcopy(state)
    player = command_player(state, command)
    events, effects = [], []

    def text(zh, en):
        return content_text(content_language(state), zh, en)

    def emit(kind, payload, text=None, audience=None):
        nonlocal state
        if audience is None and len(human_players(state)) > 1:
            if kind == "actor.moved":
                audience = [a for a, own in state["actor_states"].items()
                            if own["location_id"] in {payload["from_location"], payload["to_location"]}]
            elif kind == "item.transferred":
                audience = present(state, player)
        event = {"event_id": f'{command["action_id"]}_e{len(events) + 1}', "type": kind,
                 "visibility": {"kind": "actors", "actor_ids": audience or [player]}, "payload": payload}
        state = apply_events(state, [event], state["version"])
        events.append(event)
        if text:
            effects.append(text)
        return event

    def fail(message):
        raise DomainError("invalid_plan", message, 422)

    def know(actor, fact_id, snapshot=None):
        if fact_id not in state["facts"]:
            fail("不存在的线索")
        snapshot = deepcopy(snapshot or state["facts"][fact_id])
        belief = state["beliefs"][actor].get(fact_id)
        if not belief or belief["value"] != snapshot["value"]:
            emit("knowledge.learned", {"actor_id": actor, "fact_id": fact_id, "snapshot": snapshot},
                 text("获知：", "Learned: ") + fact_text(snapshot) if actor == player else None,
                 audience=[actor])

    if command["mode"] == "ooc":
        if plan.operations or plan.check:
            fail("游戏外讨论不能修改世界")
        return [], [], None

    roll = None
    if plan.check:
        c = plan.check
        modifier = state["actor_states"][player].get("skills", {}).get(c.skill, 0)
        percentile = (rules_config(state) or {}).get("system") == "d100"
        if percentile:
            modifier = 0
        value = random.Random(seed).randint(1, 100 if percentile else 20)
        roll = {"skill": c.skill, "purpose": c.purpose, "roll": value, "modifier": modifier,
                "total": value + modifier, "difficulty": c.difficulty,
                "passed": value <= c.difficulty if percentile else value + modifier >= c.difficulty}
        if percentile:
            roll.update(dice="d100", comparison="<=")
        emit("check.resolved", roll,
             f'{c.purpose}：{"d100" if percentile else "d20"} {value} + {modifier} = {value + modifier}，目标 {c.difficulty}，'
             + ("成功" if roll["passed"] else "未通过"))

    moving = [o for o in plan.operations if o.kind == "move"]
    if len(moving) > 1 or (moving and len(plan.operations) > 1):
        fail("移动与其它有后果的操作请分步进行")
    time_cost = max(1, plan.time_cost_s)
    for op in plan.operations:
        if op.when != "always":
            if roll is None:
                fail("条件操作缺少检定")
            if (op.when == "success") != roll["passed"]:
                continue
        own = state["actor_states"][player]
        if op.kind == "state_action":
            batch, custom_effects, time_cost = resolve_action(state, op, command["action_id"], player)
            state = apply_events(state, batch, state["version"])
            events.extend(batch)
            effects.extend(custom_effects)
        elif op.kind in EXTRA_KINDS:
            previous_count = len(events)
            witnesses = present(state, player)
            result = resolve_extra(state, command, op, replies, seed, emit)
            time_cost = result.get("time_cost", time_cost)
            roll = result.get("roll", roll)
            effects.extend(result.get("effects", []))
            if len(human_players(state)) > 1 and len(events) > previous_count:
                # Public mechanics have observable consequences without sharing the
                # actor's prose, intentions, private balance or hidden inventory.
                labels = {"take": "拾取", "use": "使用", "equip": "装备", "unequip": "卸下",
                          "buy": "购买", "sell": "出售", "attack": "攻击", "rest": "休息", "recover": "接受救治",
                          "recruit": "邀请同行", "dismiss": "结束同行"}
                item = state["items"].get(op.item_id) or next(
                    (i for i in rules_config(state)["items"] if i["id"] == op.item_id), {})
                target = state["actors"].get(op.target_id, {})
                text = state["actors"][player]["name"]+labels[op.kind]
                text += item.get("name", "") if op.item_id else target.get("name", "") if op.kind in {"attack", "recruit", "dismiss"} else ""
                if op.kind in {"take", "buy", "sell"}:
                    text += f" ×{op.quantity}"
                if op.kind == "attack":
                    text += "，命中" if roll["passed"] else "，未命中"
                observation = emit("action.observed", {"actor_id": player, "text": text}, audience=witnesses)
                emit("memory.recorded", {"audience": witnesses, "text": text, "category": "outcome",
                                         "source_event_ids": [observation["event_id"]],
                                         "world_version": state["version"]+1}, audience=witnesses)
        elif op.kind == "move":
            route = next((r for r in state["locations"][own["location_id"]]["exits"]
                          if r["to"] == op.target_id), None)
            if not route:
                fail("当前位置没有通向该地点的路线")
            time_cost = route["travel_time_s"]
            emit("actor.moved", {"actor_id": player, "from_location": own["location_id"],
                                 "to_location": op.target_id}, text("来到", "Arrived at ") + state["locations"][op.target_id]["name"])
            for follower in followers(state, player):
                if follower != player:
                    emit("actor.moved", {"actor_id": follower,
                                         "from_location": state["actor_states"][follower]["location_id"],
                                         "to_location": op.target_id})
        elif op.kind == "give":
            if op.target_id not in present(state, player) or state["actors"][op.target_id]["control"] != "npc":
                fail("只能将物品交给在场 NPC")
            item = state["items"].get(op.item_id)
            if not item or item["holder_id"] != player:
                fail("你没有持有这件物品")
            reply = replies.get(op.target_id)
            if not reply or reply.reaction != "accept":
                effects.append(f'{state["actors"][op.target_id]["name"]}没有接受，{item["name"]}仍在你的背包里')
                continue
            count = op.quantity if rules_config(state) else item["quantity"]
            if count < item["quantity"]:
                emit("item.quantity_changed", {"item_id": item["id"], "before": item["quantity"],
                                               "after": item["quantity"]-count})
                given = deepcopy(item)
                given.update(id="gift_"+hashlib.sha256(command["action_id"].encode()).hexdigest()[:20],
                             quantity=count, holder_id=op.target_id)
                emit("item.created", {"item": given}, f'交给{state["actors"][op.target_id]["name"]}：{item["name"]} ×{count}')
            else:
                emit("item.transferred", {"item_id": item["id"], "from_holder": player,
                                          "to_holder": op.target_id},
                     f'将{item["name"]}交给{state["actors"][op.target_id]["name"]}')
            relation = next((r for r in state["relations"]
                             if r["from_actor"] == op.target_id and r["to_actor"] == player), None)
            if relation and "trust" in relation["dimensions"]:
                trust = relation["dimensions"]["trust"]
                emit("relation.changed", {"from_actor": op.target_id, "to_actor": player,
                                          "dimension": "trust", "before": trust, "after": min(10, trust + 1)},
                     audience=[op.target_id])
            mechanic = state["template"]["mechanics"].get("repair")
            if mechanic and item["id"] == mechanic["tool_id"] and op.target_id == mechanic["actor_id"]:
                clock = state["clocks"][mechanic["clock_id"]]
                if clock["value"] == 0:
                    emit("clock.advanced", {"clock_id": clock["id"], "before": 0, "after": 1}, "修船进展 +1")
        elif op.kind == "reveal":
            fact = state["facts"].get(op.target_id)
            if not fact:
                fail("未知的事实 ID")
            sources = [actor for actor, reply in replies.items()
                       if actor in present(state, player) and op.target_id in reply.reveal_fact_ids
                       and op.target_id in state["knowledge"][actor]]
            at = own["location_id"] in fact.get("discoverable_at", [])
            if not sources and not at:
                fail("该线索没有可用的观察或角色来源")
            if at and fact.get("requires_check") and not (roll and roll["passed"]):
                continue
            know(player, op.target_id, state["beliefs"][sources[0]][op.target_id] if sources else None)
        elif op.kind == "repair":
            mechanic = state["template"]["mechanics"]["repair"]
            clock = state["clocks"][mechanic["clock_id"]]
            if (op.target_id != mechanic["clock_id"] or own["location_id"] != mechanic["location_id"]
                    or state["items"][mechanic["tool_id"]]["holder_id"] != mechanic["actor_id"]):
                fail("修船需要在码头，并先让船长取得工具")
            if clock["value"] >= clock["threshold"]:
                fail("船已经修好，不需要重复修理")
            if not roll or not roll["passed"]:
                effects.append("这次修补没有完成，工具和已有进展保留")
                continue
            time_cost = max(time_cost, 180)
            emit("clock.advanced", {"clock_id": clock["id"], "before": clock["value"],
                                    "after": min(clock["threshold"], clock["value"] + 1)}, "修船进展 +1")
        elif op.kind == "challenge":
            challenge = next((c for c in state["template"]["mechanics"].get("challenges", [])
                              if c["id"] == op.target_id), None)
            if not challenge or own["location_id"] != challenge["location_id"]:
                fail("请先到目标所在地点")
            if state["quests"][challenge["quest_id"]]["status"] == "completed":
                fail("这个目标已经完成")
            if any(f not in state["knowledge"][player] for f in challenge["required_facts"]):
                fail("还需要调查相关线索")
            if challenge["skill"] != "none" and not (roll and roll["passed"]):
                effects.append(text("本次尝试未完成目标，已掌握的线索仍然保留，可以尝试其他方法", "This attempt did not complete the goal. You retain the evidence and may try another approach."))
            else:
                emit("quest.updated", {"quest_id": challenge["quest_id"], "status": "completed"}, challenge["success"])
                for resource in ("coins", "xp"):
                    amount = challenge.get("reward_"+resource, 0)
                    if amount:
                        own = state["actor_states"][player]
                        before = own["resources"][resource]
                        after = min(own["resource_limits"][resource], before+amount)
                        emit("resource.changed", {"actor_id": player, "resource": resource,
                                                  "before": before, "after": after},
                             f"任务奖励：{'金币' if resource == 'coins' else '经验'} +{after-before}")
                if challenge["ending"]:
                    effects.append(text("你完成了这个故事的一种结局；仍可以继续探索或从历史创建新分支", "You reached one ending. You can keep exploring or branch from an earlier choice."))
        elif op.kind == "escape":
            routes = state["template"]["mechanics"]["escape_routes"]
            route = routes.get(op.target_id)
            if not route or own["location_id"] != route["location_id"]:
                fail("当前位置无法从这条路线离开")
            for clock_id, minimum in route.get("min_clocks", {}).items():
                if state["clocks"][clock_id]["value"] < minimum:
                    fail("这条离开路线还没有准备好")
            for clock_id, maximum in route.get("max_clocks", {}).items():
                if state["clocks"][clock_id]["value"] > maximum:
                    fail("涨潮已封住这条路线，可以寻找其它出路")
            if any(f not in state["knowledge"][player] for f in route.get("known_facts", [])):
                fail("你还没有找到这条路线")
            emit("quest.updated", {"quest_id": "hook_departure", "status": "completed"}, route["ending"])

    for actor, reply in replies.items():
        if actor not in present(state, player):
            continue
        for fact_id in reply.reveal_fact_ids:
            if fact_id not in state["knowledge"][actor]:
                fail("NPC 不能透露自己不知道的事实")
            know(player, fact_id, state["beliefs"][actor][fact_id])

    before_time = state["game_time_s"]
    emit("time.advanced", {"before_s": before_time, "after_s": before_time + time_cost})
    for clock in list(state["clocks"].values()):
        if clock["kind"] == "time":
            ticks = (before_time + time_cost) // clock["interval_s"] - before_time // clock["interval_s"]
            after = min(clock["threshold"], clock["value"] + ticks)
            if after != clock["value"]:
                emit("clock.advanced", {"clock_id": clock["id"], "before": clock["value"], "after": after},
                     clock["name"] + text("推进至 ", " advanced to ") + f"{after}/{clock['threshold']}")
    def thresholds():
        for trigger in state["template"]["mechanics"]["thresholds"]:
            clock = state["clocks"][trigger["clock_id"]]
            fact = state["facts"][trigger["fact_id"]]
            if clock["value"] >= clock["threshold"] and fact["value"] != trigger["value"]:
                emit("fact.updated", {"fact_id": fact["id"], "before": fact["value"], "after": trigger["value"]})
                know(player, fact["id"])
                for actor in present(state, player):
                    if actor != player:
                        know(actor, fact["id"])
                effects.append(fact_text(state["facts"][fact["id"]]))

    thresholds()
    if len(events) > 32:
        fail("本次变化太多，请把行动拆成几步")
    triggered, triggered_effects = advance_triggers(state, command, plan, len(events))
    state = apply_events(state, triggered, state["version"])
    events.extend(triggered)
    effects.extend(triggered_effects)
    if triggered:
        thresholds()
    return events, effects, roll
