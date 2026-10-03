"""Narrow the model's operation vocabulary to legal choices in this scene."""

import re
from typing import Literal

from pydantic import Field, create_model

from .contracts import ActorReply, Check, DomainError, Operation, TurnPlan
from .players import command_player, followers, player_for
from .rulepacks import EXTRA_KINDS, extra_choices, rules_config, validate_extra
from .state_rules import action_choices
from .world import present


def explicit_wait(text):
    if not re.search(r"等待|等候|休息|等.{0,2}[一二两三四五六七八九十\d]", text):
        return None
    matches = re.findall(r"([零一二两三四五六七八九十百\d]+)\s*(小时|分钟|秒钟|秒)", text)
    if not matches:
        return None

    def number(token):
        if token.isdigit():
            return int(token)
        digits = dict(zip("零一二两三四五六七八九", [0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9]))
        value, current = 0, 0
        for char in token:
            if char in digits:
                current = digits[char]
            else:
                value += (current or 1) * {"十": 10, "百": 100}[char]
                current = 0
        return value + current

    return min(1800, sum(number(n) * {"小时": 3600, "分钟": 60, "秒钟": 1, "秒": 1}[u] for n, u in matches))


def choices(state, mode, actor_id=None, whisper_to=None):
    player = player_for(state, actor_id)
    location = state["actor_states"][player]["location_id"]
    nearby = [a for a in present(state, player) if state["actors"][a]["control"] == "npc"
              and (not whisper_to or a == whisper_to)]
    operations = []
    if mode != "act":
        return operations, nearby if mode == "say" else []
    if rules_config(state) and state["actor_states"][player]["resources"].get("hp", 1) <= 0:
        return extra_choices(state, player), []
    destinations = [r["to"] for r in state["locations"][location]["exits"]]
    operations.extend({"kind": "move", "target_id": dest} for dest in destinations)
    operations.extend(
        {"kind": "give", "target_id": actor, "item_id": item["id"]}
        for actor in nearby
        for item in state["items"].values()
        if item["holder_id"] == player and item["quantity"] > 0
    )
    operations.extend(
        {"kind": "reveal", "target_id": f["id"]}
        for f in state["facts"].values()
        if location in f.get("discoverable_at", [])
    )
    repair = state["template"]["mechanics"].get("repair")
    clock = state["clocks"].get(repair["clock_id"]) if repair else None
    if (
        repair
        and location == repair["location_id"]
        and clock["value"] < clock["threshold"]
        and state["items"][repair["tool_id"]]["holder_id"] == repair["actor_id"]
    ):
        operations.append({"kind": "repair", "target_id": repair["clock_id"]})
    for rid, route in state["template"]["mechanics"]["escape_routes"].items():
        if (
            location == route["location_id"]
            and all(state["clocks"][k]["value"] >= v for k, v in route.get("min_clocks", {}).items())
            and all(state["clocks"][k]["value"] <= v for k, v in route.get("max_clocks", {}).items())
            and all(f in state["knowledge"][player] for f in route.get("known_facts", []))
        ):
            operations.append({"kind": "escape", "target_id": rid})
    for challenge in state["template"]["mechanics"].get("challenges", []):
        if (
            challenge["location_id"] == location
            and state["quests"][challenge["quest_id"]]["status"] != "completed"
            and all(f in state["knowledge"][player] for f in challenge["required_facts"])
        ):
            operations.append({"kind": "challenge", "target_id": challenge["id"]})
    speakers = [
        a
        for a, s in state["actor_states"].items()
        if state["actors"][a]["control"] == "npc" and s["location_id"] in [location, *destinations]
    ]
    operations.extend(extra_choices(state, player))
    operations.extend(action_choices(state, player))
    speakers = [a for a in speakers if not (state["actors"][a].get("combatant")
                                          and state["actor_states"][a]["resources"]["hp"] <= 0)]
    return operations, speakers


def plan_schema(state, command):
    """The same Pydantic type constrains provider JSON and validates its response."""
    allowed, speakers = choices(state, command["mode"], command_player(state, command), command.get("whisper_to"))
    variants = []
    for i, op in enumerate(allowed):
        fields = {k: (Literal[v], ...) for k, v in op.items()}
        fields["quantity"] = (int, Field(default=1, ge=1, le=99 if op["kind"] in {"buy", "sell", "take", "give"} else 1))
        if "item_id" not in fields:
            fields["item_id"] = (type(None), None)
        variants.append(create_model(f"SceneOperation{i}", __base__=Operation, **fields))
    item_type = variants[0] if variants else Operation
    for variant in variants[1:]:
        item_type |= variant
    speaker_type = Literal[tuple(speakers)] if speakers else str
    duration = explicit_wait(command["text"]) if command["mode"] in {"act", "wait"} else None
    if command["mode"] == "ooc":
        duration = 0
    can_check = any(
        o["kind"] in {"repair", "challenge"}
        or (o["kind"] == "reveal" and state["facts"][o["target_id"]].get("requires_check"))
        for o in allowed
    )
    return create_model(
        "SceneTurnPlan",
        __base__=TurnPlan,
        operations=(list[item_type], Field(default_factory=list, max_length=1 if variants else 0)),
        speakers=(list[speaker_type], Field(default_factory=list, max_length=2 if speakers else 0)),
        check=(Check | None if can_check else type(None), None),
        time_cost_s=(
            int,
            Field(
                default=duration if duration is not None else 60,
                ge=duration or 0,
                le=duration if duration is not None else 1800,
            ),
        ),
    )


def validate_plan(state, command, plan):
    player = command_player(state, command)
    allowed, _ = choices(state, command["mode"], player, command.get("whisper_to"))
    location = state["actor_states"][player]["location_id"]
    target = command.get("whisper_to")
    if target and (command["mode"] != "say" or target == player or target not in present(state, player)):
        raise DomainError("invalid_whisper", "私语必须选择同场的另一人物，并使用说话模式", 422)
    moving = [o for o in plan.operations if o.kind == "move"]
    if len(plan.operations) > 1:
        raise DomainError("invalid_plan", "每次行动只执行一个有后果的操作，请分步进行", 422)
    if moving and (len(plan.operations) != 1 or moving[0].when != "always"):
        raise DomainError("invalid_plan", "移动必须单独执行，且 when=always", 422)
    for op in plan.operations:
        value = {"kind": op.kind, "target_id": op.target_id}
        if op.item_id is not None:
            value["item_id"] = op.item_id
        if value not in allowed:
            raise DomainError("invalid_plan", "操作不在 allowed_operations 中；不能用移动代替交谈", 422)
        validate_extra(state, op, player)
        if op.kind == "give" and op.quantity > state["items"][op.item_id]["quantity"]:
            raise DomainError("invalid_quantity", "持有的物品数量不足", 422)
        if op.quantity != 1 and op.kind not in {"buy", "sell", "take", "give"}:
            raise DomainError("invalid_quantity", "此操作不支持批量数量", 422)
        if op.when != "always" and not plan.check:
            raise DomainError("invalid_plan", "条件操作需要检定", 422)
        if op.kind == "repair" and (not plan.check or plan.check.skill != "craft"):
            raise DomainError("invalid_plan", "修理需要 craft 检定", 422)
    if moving:
        location = moving[0].target_id
    if any(
        a not in state["actor_states"] or state["actors"][a]["control"] != "npc"
        or (target and a != target)
        or (state["actor_states"][a]["location_id"] != location and not (moving and a in followers(state, player)))
        for a in plan.speakers
    ):
        raise DomainError("invalid_plan", "只能选择行动后所在地点的 NPC 发言", 422)
    if command["mode"] != "act" and plan.check:
        raise DomainError("invalid_plan", "普通交流、等待和游戏外讨论不掷骰", 422)
    if plan.operations and all(o.kind in {"give", "move"} for o in plan.operations) and plan.check:
        raise DomainError("invalid_plan", "交付已有物品或沿已知路线移动不需要检定，check 应为 null", 422)


def normalize_plan(state, command, plan):
    """Speaker selection is presentation metadata; authoritative presence is code-owned."""
    player = command_player(state, command)
    location = state["actor_states"][player]["location_id"]
    moves = [op for op in plan.operations if op.kind == "move"]
    if moves:
        location = moves[0].target_id
    available = [
        a for a, s in state["actor_states"].items() if state["actors"][a]["control"] == "npc"
        and (not command.get("whisper_to") or a == command["whisper_to"])
        and (s["location_id"] == location or (moves and a in followers(state, player)))
    ]
    requested = list(plan.speakers)
    plan.speakers = [a for a in dict.fromkeys(requested) if a in available]
    if requested and not plan.speakers:
        plan.speakers = available[:2]
    if command["mode"] in {"ooc", "wait"}:
        plan.speakers = []
    if not any(o.kind in {"repair", "reveal", "challenge"} for o in plan.operations):
        plan.check = None
    for op in plan.operations:
        if op.kind == "challenge":
            challenge = next(
                (c for c in state["template"]["mechanics"].get("challenges", []) if c["id"] == op.target_id), None
            )
            if challenge:
                plan.check = (
                    None
                    if challenge["skill"] == "none"
                    else Check(
                        skill=challenge["skill"], difficulty=challenge["difficulty"], purpose=challenge["name"]
                    )
                )
        if op.kind in {"move", "give", "challenge", "state_action", *EXTRA_KINDS}:
            op.when = "always"
    return plan


def actor_schema(state, actor, offered, consent=False):
    known = state["knowledge"][actor]
    fact = Literal[tuple(known)] if known else str
    return create_model(
        "SceneActorReply",
        __base__=ActorReply,
        reaction=(Literal["accept", "refuse"] if offered or consent else Literal["none"], ...),
        reveal_fact_ids=(list[fact], Field(default_factory=list, max_length=min(2, len(known)))),
    )


def explicit_goal_plan(state, command):
    """Bind an explicit selection of an authored goal before free-language planning."""
    if command.get("selected_operation"):
        if command["mode"] != "act":
            raise DomainError("invalid_plan", "规则选择只能作为行动提交", 422)
        operation = Operation.model_validate(command["selected_operation"])
        plan = normalize_plan(state, command, TurnPlan(intent=command["text"][:240], operations=[operation]))
        validate_plan(state, command, plan)
        return plan
    if command["mode"] != "act":
        return None
    match = re.match(r"我(?:尝试|决定)完成「([^」]+)」", command["text"])
    if not match:
        return None
    allowed, _ = choices(state, "act", command_player(state, command))
    for goal in state["template"]["mechanics"].get("challenges", []):
        op = {"kind": "challenge", "target_id": goal["id"]}
        if match[1] == goal["name"] and op in allowed:
            return normalize_plan(state, command, TurnPlan(intent=goal["name"], time_cost_s=120, operations=[op]))
    return None
