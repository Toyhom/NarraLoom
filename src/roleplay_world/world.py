"""Pure world projection and event reducer; no model or network dependencies."""

from copy import deepcopy

from .contracts import DomainError
from .players import player_for


def initial_state(template, player_name):
    t = deepcopy(template)
    player = next(a["id"] for a in t["actors"] if a["control"] == "player")
    actors = {a["id"]: a for a in t["actors"]}
    actors[player]["name"] = player_name
    state = {
        "template": t, "player": player, "version": 0, "game_time_s": 0,
        "actors": actors, "locations": {x["id"]: x for x in t["locations"]},
        "actor_states": {a["id"]: deepcopy(a["initial_state"]) for a in t["actors"]},
        "items": {i["id"]: deepcopy(i) for i in t["items"]},
        "facts": {f["id"]: deepcopy(f) for f in t["facts"]},
        "knowledge": {a["id"]: list(a["initial_knowledge"]) for a in t["actors"]},
        "beliefs": {a["id"]: {f["id"]: deepcopy(f) for f in t["facts"] if f["id"] in a["initial_knowledge"]}
                    for a in t["actors"]},
        "memories": {a["id"]: [] for a in t["actors"]},
        "clocks": {c["id"]: deepcopy(c) for c in t["clocks"]},
        "quests": {q["id"]: deepcopy(q) for q in t["hooks"]},
        "relations": deepcopy(t["relations"]),
    }
    if t["mechanics"].get("rules"):
        state["party"] = [player]
        state["shops"] = {s["id"]: deepcopy(s) for s in t["mechanics"]["rules"]["shops"]}
    if t["mechanics"].get("simulation"):
        from .simulation import initial_simulation

        state["simulation"] = initial_simulation(t["mechanics"]["simulation"])
    if t["mechanics"].get("state_rules"):
        from .state_rules import initial_rules

        state["state_rules"] = initial_rules(t["mechanics"]["state_rules"])
    if t.get("continuity_state"):
        state.update(deepcopy(t["continuity_state"]))
        state["actors"][player]["name"] = player_name
    return state


def present(state, actor_id=None):
    actor_id = actor_id or state["player"]
    location = state["actor_states"][actor_id]["location_id"]
    return [a for a, s in state["actor_states"].items() if s["location_id"] == location
            and not (state["actors"][a].get("combatant") and s["resources"].get("hp", 1) <= 0)]


def fact_text(fact):
    return fact.get("value_labels", {}).get(str(fact["value"]), str(fact["value"]))


def visible(scope, actor_id):
    return scope.get("kind") == "public" or actor_id in scope.get("actor_ids", [])


def project(state, actor_id=None):
    # JSON journal frames canonically sort object keys. Restored snapshot maps
    # therefore lose insertion order on restart; presentation must not depend on it.
    # Keep authored order and use stable IDs for later additions, without changing
    # canonical state or any historical replay hash.
    state = dict(state)
    for key, declared in {"actors": "actors", "actor_states": "actors", "locations": "locations",
                          "items": "items", "clocks": "clocks", "quests": "hooks"}.items():
        order = {row["id"]: i for i, row in enumerate(state["template"][declared])}
        state[key] = {aid: state[key][aid] for aid in sorted(state[key], key=lambda aid: (order.get(aid, len(order)), aid))}
    for key in ("notes", "shops"):
        if key in state:
            state[key] = dict(sorted(state[key].items()))
    actor_id = actor_id or state["player"]
    own = state["actor_states"][actor_id]
    loc = state["locations"][own["location_id"]]
    result = {
        "world_version": state["version"], "game_time_s": state["game_time_s"],
        "player_actor_id": actor_id, "player_name": state["actors"][actor_id]["name"],
        "title": state["template"]["title"], "premise": state["template"]["premise"],
        "world_title": state["template"].get("world_title", state["template"]["title"]),
        "player_role": (state["template"].get("player_role", "自由旅人") if actor_id == state["player"]
                        else state["actors"][actor_id].get("public_description", "自由旅人")),
        "location": {"id": loc["id"], "name": loc["name"], "description": loc["description"]},
        "exits": [{"id": e["to"], "name": state["locations"][e["to"]]["name"],
                   "travel_time_s": e["travel_time_s"]} for e in loc["exits"]],
        "present_actors": [{"id": a, "name": state["actors"][a]["name"],
                            "control": state["actors"][a]["control"],
                            "description": state["actors"][a].get("public_description", ""),
                            **({"avatar_id": state["actors"][a]["avatar_id"]} if state["actors"][a].get("avatar_id") else {}),
                            "initial": state["actors"][a]["name"][0]}
                           for a in present(state, actor_id)],
        "inventory": [{"id": i["id"], "name": i["name"], "quantity": i["quantity"]}
                      for i in state["items"].values() if i["holder_id"] == actor_id and i["quantity"] > 0],
        "resources": deepcopy(own["resources"]), "skills": deepcopy(own.get("skills", {})),
        "known_facts": [{"id": f, "text": fact_text(state["beliefs"][actor_id][f])}
                        for f in state["knowledge"][actor_id]],
        "memories": deepcopy(state["memories"][actor_id][-30:]),
        "visible_clocks": [{"id": c["id"], "name": c["name"], "value": c["value"],
                            "threshold": c["threshold"]}
                           for c in state["clocks"].values() if visible(c["visibility"], actor_id)
                           and (not c.get("observe_at") or own["location_id"] in c["observe_at"])],
        "quests": [{"id": q["id"], "name": q["name"], "status": q["status"], "description": q.get("description", "")}
                   for q in state["quests"].values() if q["status"] != "undiscovered"],
        "opportunities": [{"id": c["id"], "name": c["name"], "description": c["description"],
                           "ready": all(f in state["knowledge"][actor_id] for f in c["required_facts"])}
                          for c in state["template"]["mechanics"].get("challenges", [])
                          if c["location_id"] == own["location_id"] and state["quests"][c["quest_id"]]["status"] != "completed"],
    }
    for key in ("content_language", "creation_preset"):
        if key in state["template"]:
            result[key] = state["template"][key]
    if state.get("trades"):
        from .trades import project_trades

        result["trades"] = project_trades(state, actor_id)
    cfg = state["template"]["mechanics"].get("rules")
    if state.get("state_rules"):
        from .state_rules import project_rules

        result["custom_state"] = project_rules(state, actor_id)
    result["notes"] = [{k: deepcopy(n[k]) for k in ("id", "text", "kind", "status", "source_event_ids")}
                       for n in state.get("notes", {}).values() if n["actor_id"] == actor_id]
    result["map"] = [{"id": p["id"], "name": p["name"], "exits": [e["to"] for e in p["exits"]]}
                     for p in state["locations"].values()]
    if state["template"].get("continuity_origin"):
        result["continuity_origin"] = deepcopy(state["template"]["continuity_origin"])
    if state.get("simulation"):
        sim = state["simulation"]
        result["simulation"] = {"paused": sim["paused"], "elapsed_s": sim["elapsed_s"],
                                "next_tick_s": sim["next_tick_s"],
                                "factions": [{"id": f["id"], "name": f["name"], "goal": f["goal"],
                                              "threshold": f["threshold"], **deepcopy(sim["factions"][f["id"]])}
                                             for f in state["template"]["mechanics"]["simulation"]["factions"]]}
    if cfg:
        from .rulepacks import extra_choices

        result["rule_system"] = cfg["system"]
        result["resource_limits"] = deepcopy(own.get("resource_limits", {}))
        result["equipment"] = deepcopy(own.get("equipment", {}))
        result["party"] = [{"id": a, "name": state["actors"][a]["name"]} for a in state.get("party", [])
                           if actor_id == state["player"] or a in present(state, actor_id)]
        result["ground_items"] = [{"id": i["id"], "name": i["name"], "quantity": i["quantity"]}
                                  for i in state["items"].values() if i["holder_id"] == loc["id"] and i["quantity"] > 0]
        result["enemies"] = [{"id": a, "name": state["actors"][a]["name"], "hp": s["resources"]["hp"],
                              "max_hp": s["resource_limits"]["hp"]}
                             for a, s in state["actor_states"].items() if a.startswith("enemy_")
                             and s["location_id"] == loc["id"]]
        result["shops"] = [{**deepcopy(s), "catalog": deepcopy(cfg["items"])} for s in state["shops"].values()
                            if f"loc_{s['location']}" == loc["id"]]
        result["rule_actions"] = extra_choices(state, actor_id) if state["actors"][actor_id]["control"] == "player" else []
    if state["actors"][actor_id]["control"] != "player":
        result["quests"], result["opportunities"] = [], []
    return result


def model_view(state, actor_id=None, query=""):
    from .memory import context_memories

    actor_id = actor_id or state["player"]
    view = project(state, actor_id)
    view["memories"] = context_memories(state, actor_id, query)
    view["notes"] = [{**n, "text": n["text"][:400]} for n in view["notes"] if n["status"] == "open"][-12:]
    return view


def npc_context(state, actor_id, player_text, offered_items, player_id=None):
    actor = state["actors"][actor_id]
    context = {"character": {k: actor[k] for k in ["id", "name", "persona", "goals", "boundaries"]},
               "view": model_view(state, actor_id, player_text), "player_name": state["actors"][player_for(state, player_id)]["name"],
               "player_input": player_text, "offered_items": offered_items}
    repair = state["template"]["mechanics"].get("repair")
    if repair and repair["actor_id"] == actor_id:
        # The responsible NPC knows their own public procedure. Do not send the
        # player's hidden inventory, all GM mechanics or other people's balances.
        context["known_procedures"] = ["修船必须在"+state["locations"][repair["location_id"]]["name"]
            +"进行，需先将"+state["items"][repair["tool_id"]]["name"]+"交给你，再由玩家进行修理检定。"
            +"仅有交谈或玩家持有工具不满足交付前提；这份规则不表示工具已交付或船已修好。"]
    return context


def apply_events(state, events, new_version):
    state = deepcopy(state)
    for event in events:
        kind, p = event["type"], event["payload"]
        if kind.startswith("trade."):
            from .trades import reduce_trade

            reduce_trade(state, event)
        elif kind == "player.joined":
            from .players import join_player

            join_player(state, event)
        elif kind.startswith("state."):
            from .state_rules import reduce_event

            reduce_event(state, event)
        elif kind == "announcement.recorded":
            fact = p["fact"]
            if fact["id"] in state["facts"] or fact["visibility"].get("kind") != "public":
                raise DomainError("invalid_event", "公告事实重复或不可公开")
            state["facts"][fact["id"]] = deepcopy(fact)
            for actor in state["actors"]:
                state["knowledge"][actor].append(fact["id"])
                state["beliefs"][actor][fact["id"]] = deepcopy(fact)
        elif kind == "fact.created":
            fact = p["fact"]
            if fact["id"] in state["facts"] or len(state["facts"]) >= 256:
                raise DomainError("invalid_event", "事实重复或超过世界容量")
            state["facts"][fact["id"]] = deepcopy(fact)
        elif kind == "location.created":
            location, anchor = p["location"], p["connect_from"]
            if location["id"] in state["locations"] or anchor not in state["locations"] or len(state["locations"]) >= 48:
                raise DomainError("invalid_event", "新地点重复或连接非法")
            if location["exits"] != [{"to": anchor, "travel_time_s": 120}]:
                raise DomainError("invalid_event", "新地点连接必须为双向相邻路线")
            state["locations"][location["id"]] = deepcopy(location)
            state["locations"][anchor]["exits"].append({"to": location["id"], "travel_time_s": 120})
        elif kind == "actor.created":
            actor = p["actor"]
            if (actor["id"] in state["actors"] or actor["control"] != "npc" or len(state["actors"]) >= 80
                    or actor["initial_state"]["location_id"] not in state["locations"]
                    or any(f not in state["facts"] for f in actor["initial_knowledge"])):
                raise DomainError("invalid_event", "新人物重复或引用非法")
            state["actors"][actor["id"]] = deepcopy(actor)
            state["actor_states"][actor["id"]] = deepcopy(actor["initial_state"])
            state["knowledge"][actor["id"]] = list(actor["initial_knowledge"])
            state["beliefs"][actor["id"]] = {f: deepcopy(state["facts"][f]) for f in actor["initial_knowledge"]}
            state["memories"][actor["id"]] = []
        elif kind == "simulation.advanced":
            if state["simulation"] != p["before"] or p["after"]["elapsed_s"] < p["before"]["elapsed_s"]:
                raise DomainError("invalid_event", "世界推进前提不一致")
            state["simulation"] = deepcopy(p["after"])
        elif kind == "simulation.paused":
            if state["simulation"]["paused"] != p["before"]:
                raise DomainError("invalid_event", "世界运行状态前提不一致")
            state["simulation"]["paused"] = p["after"]
        elif kind == "actor.moved":
            current = state["actor_states"][p["actor_id"]]
            if current["location_id"] != p["from_location"]:
                raise DomainError("invalid_event", "地点前提不一致")
            current["location_id"] = p["to_location"]
        elif kind == "item.transferred":
            item = state["items"][p["item_id"]]
            if item["holder_id"] != p["from_holder"]:
                raise DomainError("invalid_event", "物品归属前提不一致")
            item["holder_id"] = p["to_holder"]
            # A transferred item cannot remain equipped by the previous holder.
            equipment = state["actor_states"].get(p["from_holder"], {}).get("equipment", {})
            for slot in equipment:
                if equipment[slot] == p["item_id"]:
                    equipment[slot] = None
        elif kind == "resource.changed":
            actor = state["actor_states"][p["actor_id"]]
            if (actor["resources"].get(p["resource"]) != p["before"]
                    or not 0 <= p["after"] <= actor.get("resource_limits", {}).get(p["resource"], 999999 if p["resource"] == "coins" else -1)):
                raise DomainError("invalid_event", "资源前提或范围不一致")
            actor["resources"][p["resource"]] = p["after"]
        elif kind == "item.quantity_changed":
            item = state["items"][p["item_id"]]
            if item["quantity"] != p["before"] or not 0 <= p["after"] <= 9999:
                raise DomainError("invalid_event", "物品数量前提不一致")
            item["quantity"] = p["after"]
        elif kind == "item.created":
            item = p["item"]
            if item["id"] in state["items"] or not 1 <= item["quantity"] <= 9999:
                raise DomainError("invalid_event", "新物品重复或数量非法")
            state["items"][item["id"]] = deepcopy(item)
        elif kind == "equipment.changed":
            actor = state["actor_states"][p["actor_id"]]
            item = state["items"].get(p["after"])
            if (actor["equipment"].get(p["slot"]) != p["before"] or p["slot"] not in {"weapon", "armor"}
                    or (p["after"] is not None and (not item or item["holder_id"] != p["actor_id"]
                    or item["quantity"] <= 0 or item.get("kind") != p["slot"]))):
                raise DomainError("invalid_event", "装备前提不一致")
            actor["equipment"][p["slot"]] = p["after"]
        elif kind == "shop.stock_changed":
            stock = next(s for s in state["shops"][p["shop_id"]]["stock"] if s["item_id"] == p["item_id"])
            if stock["quantity"] != p["before"] or not 0 <= p["after"] <= 9999:
                raise DomainError("invalid_event", "库存前提不一致")
            stock["quantity"] = p["after"]
        elif kind == "party.changed":
            actor = p["actor_id"]
            leader = player_for(state, p.get("leader_id"))
            if actor == state["player"] or state["actors"][actor]["control"] != "npc":
                raise DomainError("invalid_event", "无效的队伍成员")
            if p["join"]:
                if actor in state["party"] or len(state["party"]) >= state["template"]["mechanics"]["rules"]["party_limit"]:
                    raise DomainError("invalid_event", "队伍已满或成员重复")
                state["party"].append(actor)
                if "leader_id" in p:
                    state.setdefault("companion_leaders", {})[actor] = leader
            else:
                if actor not in state["party"] or state.get("companion_leaders", {}).get(actor, state["player"]) != leader:
                    raise DomainError("invalid_event", "角色未加入队伍")
                state["party"].remove(actor)
                if "companion_leaders" in state:
                    state["companion_leaders"].pop(actor, None)
        elif kind == "clock.advanced":
            clock = state["clocks"][p["clock_id"]]
            if clock["value"] != p["before"] or not 0 <= p["after"] <= clock["threshold"]:
                raise DomainError("invalid_event", "时钟前提不一致")
            clock["value"] = p["after"]
        elif kind == "relation.changed":
            relation = next(r for r in state["relations"]
                            if r["from_actor"] == p["from_actor"] and r["to_actor"] == p["to_actor"])
            if relation["dimensions"][p["dimension"]] != p["before"]:
                raise DomainError("invalid_event", "关系前提不一致")
            relation["dimensions"][p["dimension"]] = p["after"]
        elif kind == "time.advanced":
            if state["game_time_s"] != p["before_s"]:
                raise DomainError("invalid_event", "时间前提不一致")
            state["game_time_s"] = p["after_s"]
        elif kind == "knowledge.learned":
            known = state["knowledge"][p["actor_id"]]
            if p["fact_id"] not in known:
                known.append(p["fact_id"])
            state["beliefs"][p["actor_id"]][p["fact_id"]] = deepcopy(p.get("snapshot", state["facts"][p["fact_id"]]))
        elif kind == "fact.updated":
            f = state["facts"][p["fact_id"]]
            if f["value"] != p["before"]:
                raise DomainError("invalid_event", "事实前提不一致")
            f["value"] = p["after"]
        elif kind == "quest.updated":
            state["quests"][p["quest_id"]]["status"] = p["status"]
        elif kind == "memory.recorded":
            for actor_id in p["audience"]:
                entry = {"event_id": event["event_id"], "text": p["text"], "game_time_s": state["game_time_s"]}
                # Optional fields only on new events preserve historical replay hashes.
                for key in ("category", "source_event_ids", "world_version"):
                    if key in p:
                        entry[key] = deepcopy(p[key])
                state["memories"][actor_id].append(entry)
        elif kind == "note.updated":
            if p["actor_id"] not in state["actors"] or p["status"] not in {"open", "done", "archived"}:
                raise DomainError("invalid_event", "手记记录无效")
            state.setdefault("notes", {})[p["id"]] = deepcopy(p)
        elif kind == 'check.resolved':
            from .checks import validate_receipt
            validate_receipt(state, p)
        elif kind in {"speech.recorded", "action.observed"}:
            pass
        else:
            raise DomainError("unknown_event", "不支持的事件类型")
    state["version"] = new_version
    return state
