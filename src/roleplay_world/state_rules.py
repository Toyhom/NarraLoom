"""Authored state machines: finite typed data, no script interpreter or model writes."""

from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

from .contracts import Contract, DomainError, Identifier
from .players import command_player, player_for

Scalar = StrictBool | StrictInt | Annotated[StrictStr, Field(max_length=80)]
Name = Annotated[str, Field(min_length=1, max_length=60)]


def invalid(message):
    raise DomainError("invalid_state_rules", message, 422)


class StateVariable(Contract):
    id: Identifier
    name: Name
    kind: Literal["integer", "boolean", "enum"] = "integer"
    initial: Scalar = 0
    minimum: Annotated[int, Field(ge=-1000000, le=1000000)] = 0
    maximum: Annotated[int, Field(ge=-1000000, le=1000000)] = 100
    options: Annotated[list[Name], Field(max_length=20)] = Field(default_factory=list)
    visibility: Literal["public", "player", "gm"] = "public"

    @model_validator(mode="after")
    def valid(self):
        if self.minimum > self.maximum or len(set(self.options)) != len(self.options):
            raise ValueError("变量范围或枚举选项无效")
        if not valid_value(self.model_dump(), self.initial):
            raise ValueError("变量初值不符合类型或范围")
        return self


def valid_value(variable, value):
    if variable["kind"] == "integer":
        return type(value) is int and variable["minimum"] <= value <= variable["maximum"]
    if variable["kind"] == "boolean":
        return type(value) is bool
    return type(value) is str and value in variable["options"]


class StateCondition(Contract):
    source: Literal["variable", "resource", "item_count", "location", "knowledge", "quest", "clock", "party", "game_time"]
    key: Identifier | None = None
    actor_id: Identifier = "pc_traveler"
    op: Literal["eq", "ne", "ge", "gt", "le", "lt"] = "eq"
    value: Scalar


class StateEffect(Contract):
    kind: Literal["set", "add", "resource", "clock", "reveal", "message"]
    target: Identifier | None = None
    actor_id: Identifier = "pc_traveler"
    value: Scalar = 0
    text: Annotated[str, Field(max_length=400)] = ""


class StateAction(Contract):
    id: Identifier
    name: Name
    description: Annotated[str, Field(max_length=400)] = ""
    location_id: Identifier | None = None
    when_all: Annotated[list[StateCondition], Field(max_length=12)] = Field(default_factory=list)
    when_any: Annotated[list[StateCondition], Field(max_length=12)] = Field(default_factory=list)
    effects: Annotated[list[StateEffect], Field(min_length=1, max_length=6)]
    once: bool = False
    cooldown_s: Annotated[int, Field(ge=0, le=86400)] = 0
    time_cost_s: Annotated[int, Field(ge=1, le=1800)] = 60


class StateTrigger(Contract):
    id: Identifier
    name: Name
    on: Literal["turn", "move", "reveal", "challenge", "state_action", "attack", "rest", "say", "wait"] = "turn"
    target_id: Identifier | None = None
    when_all: Annotated[list[StateCondition], Field(max_length=12)] = Field(default_factory=list)
    when_any: Annotated[list[StateCondition], Field(max_length=12)] = Field(default_factory=list)
    effects: Annotated[list[StateEffect], Field(min_length=1, max_length=6)]
    once: bool = True
    cooldown_s: Annotated[int, Field(ge=0, le=86400)] = 0

    @model_validator(mode="after")
    def bounded(self):
        if not self.once and self.cooldown_s < 1:
            raise ValueError("重复触发器必须设置至少1秒游戏时间的冷却")
        if self.target_id and self.on in {"turn", "say", "wait"}:
            raise ValueError("此触发类型不使用目标ID")
        return self


class StateTestStep(Contract):
    kind: Literal["state_action", "move", "reveal", "challenge", "attack", "rest", "say", "wait"]
    target_id: Identifier | None = None
    seconds: Annotated[int, Field(ge=1, le=1800)] = 60


class StateScenario(Contract):
    name: Name
    steps: Annotated[list[StateTestStep], Field(min_length=1, max_length=24)]
    expect: Annotated[list[StateCondition], Field(min_length=1, max_length=12)]


class StateRules(Contract):
    variables: Annotated[list[StateVariable], Field(max_length=32)] = Field(default_factory=list)
    actions: Annotated[list[StateAction], Field(max_length=16)] = Field(default_factory=list)
    triggers: Annotated[list[StateTrigger], Field(max_length=24)] = Field(default_factory=list)
    tests: Annotated[list[StateScenario], Field(max_length=12)] = Field(default_factory=list)


def compile_packs(world_pack, story_pack=None):
    combined = {k: [] for k in ("variables", "actions", "triggers", "tests")}
    for scope, pack in (("world", world_pack), ("story", story_pack)):
        if pack:
            for key, rows in pack.model_dump().items():
                combined[key].extend({**row, "scope": scope} for row in rows)
    for key in ("variables", "actions", "triggers"):
        ids = [v["id"] for v in combined[key]]
        if len(ids) != len(set(ids)):
            invalid("世界与故事中的" + key + "标识不能重复")
    return combined


def validate_authoring(world, story=None):
    from .rulepacks import attach_rules

    if not world.state_rules and not (story and story.state_rules):
        return
    t = {"actors": [{"id": "pc_traveler", "control": "player", "initial_state": {"resources": {}}},
                    *[{"id": f"npc_{i}", "control": "npc", "initial_state": {"resources": {}}}
                      for i in range(len(world.characters))]],
         "locations": [{"id": f"loc_{i}"} for i in range(len(world.locations))],
         "facts": [{"id": "fact_setting"}, *[{"id": f"fact_secret_{i}"} for i in range(len(world.characters))]],
         "items": [{"id": "item_start"}] if story and story.starting_item else [], "hooks": [], "clocks": [], "relations": [], "mechanics": {}}
    if story:
        t["facts"].extend({"id": f"fact_clue_{i}"} for i in range(len(story.clues)))
        if story.pressure_name:
            t["facts"].append({"id": "fact_pressure"})
        t["hooks"] = [{"id": f"quest_{i}"} for i in range(len(story.challenges))]
        t["mechanics"]["challenges"] = [{"id": f"challenge_{i}"} for i in range(len(story.challenges))]
        t["clocks"] = [{"id": "clock_pressure"}] if story.pressure_name else []
    attach_rules(t, world.rules)
    validate_pack(compile_packs(world.state_rules, story.state_rules if story else None), t)


def validate_pack(cfg, template):
    """Validate references against the compiled entities, before content is published."""
    variables = {v["id"]: v for v in cfg["variables"]}
    actors = {a["id"]: a for a in template["actors"]}
    locations = {p["id"] for p in template["locations"]}
    facts = {f["id"] for f in template["facts"]}
    quests = {q["id"] for q in template["hooks"]}
    clocks = {c["id"] for c in template["clocks"]}
    catalog = {i["id"] for i in template["mechanics"].get("rules", {}).get("items", [])}
    item_ids = {i["id"] for i in template["items"]} | catalog
    resources = {a: set(v["initial_state"].get("resource_limits", {})) for a, v in actors.items()}
    actions = {a["id"] for a in cfg["actions"]}
    challenge_ids = {c["id"] for c in template["mechanics"].get("challenges", [])}

    def condition(c, scope):
        source, key, value = c["source"], c["key"], c["value"]
        if c["actor_id"] not in actors:
            invalid("条件引用了不存在的人物：" + c["actor_id"])
        expected = int
        if source == "variable":
            v = variables.get(key)
            if not v or (scope == "world" and v["scope"] != "world"):
                invalid("条件引用了不存在或不属于世界的变量：" + str(key))
            expected = {"integer": int, "boolean": bool, "enum": str}[v["kind"]]
            if expected is str and value not in v["options"]:
                invalid("枚举条件使用了未声明的选项")
        elif source == "resource":
            if key not in resources[c["actor_id"]]:
                invalid("资源条件需要该人物已启用的资源：" + str(key))
        elif source == "item_count":
            if key not in item_ids or (scope == "world" and key == "item_start"):
                invalid("物品条件引用不存在或故事专用的物品")
        elif source == "location":
            expected = str
            if value not in locations or key is not None:
                invalid("地点条件的value必须是地点ID，key留空")
        elif source == "knowledge":
            expected = bool
            if key not in facts or (scope == "world" and key not in {"fact_setting", *[f"fact_secret_{i}" for i in range(len(actors)-1)]}):
                invalid("知识条件引用不存在或故事专用的事实")
        elif source == "quest":
            expected = str
            if scope == "world" or key not in quests or value not in {"available", "completed", "undiscovered"}:
                invalid("任务条件引用无效；世界规则不能依赖某个故事的任务")
        elif source == "clock":
            if scope == "world" or key not in clocks:
                invalid("时钟条件引用无效；故事时钟需要放在故事规则中")
        elif source == "party":
            expected = bool
            if key not in actors or not template["mechanics"].get("rules"):
                invalid("同行条件需要启用冒险规则并选择现有人物")
        elif source == "game_time" and key is not None:
            invalid("游戏时间条件不使用key")
        if type(value) is not expected or (expected is not int and c["op"] not in {"eq", "ne"}):
            invalid("条件值类型或比较方式不匹配：" + source)

    for group in ("actions", "triggers"):
        for row in cfg[group]:
            scope = row["scope"]
            if group == "actions" and row["location_id"] and row["location_id"] not in locations:
                invalid("行动引用了不存在的地点")
            if group == "triggers" and row["target_id"]:
                targets = {"move": locations, "reveal": facts, "challenge": challenge_ids, "state_action": actions,
                           "attack": {a for a in actors if a.startswith("enemy_")}, "rest": {"pc_traveler"}}
                if row["target_id"] not in targets.get(row["on"], set()):
                    invalid("触发器的事件目标不存在")
                if scope == "world" and (row["on"] in {"reveal", "challenge"} or row["on"] == "state_action"
                                         and not any(a["id"] == row["target_id"] and a["scope"] == "world" for a in cfg["actions"])):
                    invalid("世界触发器不能依赖故事目标")
            for c in row["when_all"] + row["when_any"]:
                condition(c, scope)
            for e in row["effects"]:
                kind, target = e["kind"], e["target"]
                if e["actor_id"] not in actors:
                    invalid("效果引用不存在的人物")
                if kind in {"set", "add"}:
                    v = variables.get(target)
                    if not v or (scope == "world" and v["scope"] != "world"):
                        invalid("效果引用不存在或故事专用的变量")
                    if kind == "set" and not valid_value(v, e["value"]):
                        invalid("设定值不符合变量类型或范围")
                    if kind == "add" and (v["kind"] != "integer" or type(e["value"]) is not int or abs(e["value"]) > 1000000):
                        invalid("增减效果只能使用有界整数")
                elif kind == "resource":
                    if target not in resources[e["actor_id"]] or type(e["value"]) is not int or abs(e["value"]) > 1000:
                        invalid("资源效果需要已启用的资源及-1000至1000的整数变化")
                elif kind == "clock":
                    if scope == "world" or target not in clocks or type(e["value"]) is not int or not 0 <= e["value"] <= 100:
                        invalid("时钟效果需要现有故事时钟与0至100的整数增量")
                elif kind == "reveal":
                    if target not in facts or scope == "world" and target.startswith(("fact_clue_", "fact_pressure")):
                        invalid("揭示效果引用不存在或故事专用的事实")
                elif kind == "message" and (target is not None or not e["text"].strip()):
                    invalid("消息效果需要文字，target留空")
                if kind != "message" and e["text"]:
                    invalid("附加文字请使用独立message效果并指定接收人物")
    for test in cfg["tests"]:
        for c in test["expect"]:
            condition(c, test["scope"])
        for step in test["steps"]:
            targets = {"state_action": actions, "move": locations, "reveal": facts, "challenge": challenge_ids,
                       "attack": {a for a in actors if a.startswith("enemy_")}, "rest": {"pc_traveler"}}
            if step["kind"] in {"wait", "say"}:
                if step["target_id"] is not None:
                    invalid("等待测试不使用目标ID")
            elif step["target_id"] not in targets[step["kind"]]:
                invalid("验收步骤引用不存在的目标")


def config(state):
    return state["template"]["mechanics"].get("state_rules")


def initial_rules(cfg):
    return {"values": {v["id"]: deepcopy(v["initial"]) for v in cfg["variables"]}, "actions": {}, "triggers": {}}


def evaluate(state, c):
    source, key, actor = c["source"], c["key"], c["actor_id"]
    if actor not in state["actors"]:
        return False
    if source == "variable":
        actual = state["state_rules"]["values"][key]
    elif source == "resource":
        actual = state["actor_states"][actor]["resources"][key]
    elif source == "item_count":
        actual = sum(i["quantity"] for i in state["items"].values() if i["holder_id"] == actor
                     and (i["id"] == key or i.get("catalog_id") == key))
    elif source == "location":
        actual = state["actor_states"][actor]["location_id"]
    elif source == "knowledge":
        actual = key in state["knowledge"][actor]
    elif source == "quest":
        actual = state["quests"][key]["status"]
    elif source == "clock":
        actual = state["clocks"][key]["value"]
    elif source == "party":
        actual = key in state.get("party", [])
    else:
        actual = state["game_time_s"]
    value = c["value"]
    if c["op"] == "eq":
        return type(actual) is type(value) and actual == value
    if c["op"] == "ne":
        return type(actual) is not type(value) or actual != value
    return {"ge": lambda: actual >= value, "gt": lambda: actual > value,
            "le": lambda: actual <= value, "lt": lambda: actual < value}[c["op"]]()


def eligible(state, row, group, actor_id=None):
    log = state["state_rules"][group].get(row["id"])
    if log and (row["once"] or state["game_time_s"] - log["last_time_s"] < row["cooldown_s"]):
        return False
    if group == "actions" and row["location_id"] and row["location_id"] != state["actor_states"][player_for(state, actor_id)]["location_id"]:
        return False
    return all(evaluate(state, c) for c in row["when_all"]) and (
        not row["when_any"] or any(evaluate(state, c) for c in row["when_any"])) and payable(state, row)


def payable(state, row):
    # Account for ordered credits/costs without copying a potentially long campaign.
    values = {}
    for effect in row["effects"]:
        if effect["kind"] != "resource":
            continue
        key = (effect["actor_id"], effect["target"])
        own = state["actor_states"][key[0]]
        before = values.get(key, own["resources"][key[1]])
        if before + effect["value"] < 0:
            return False
        values[key] = min(own["resource_limits"][key[1]], before + effect["value"])
    return True


def scope_for(variable, player):
    return {"kind": "public"} if variable["visibility"] == "public" else (
        {"kind": "actors", "actor_ids": [player]} if variable["visibility"] == "player" else {"kind": "gm_only"})


def display_value(value):
    return ("已开启" if value else "未开启") if type(value) is bool else str(value)


def execute(state, row, group, action_id, offset=0, viewer_id=None):
    """Return a pure candidate batch. All writes have authored causes and before values."""
    from .world import apply_events, fact_text, visible

    state = deepcopy(state)
    viewer_id = player_for(state, viewer_id)
    events, texts = [], []
    variables = {v["id"]: v for v in config(state)["variables"]}
    private = {"kind": "gm_only"}

    def emit(kind, payload, visibility=private, text=None):
        nonlocal state
        event = {"event_id": f"{action_id}_sr{offset + len(events)}", "type": kind,
                 "visibility": visibility, "payload": payload,
                 "cause": {"kind": group, "id": row["id"]}}
        state = apply_events(state, [event], state["version"])
        events.append(event)
        if text and visible(visibility, viewer_id):
            texts.append(text)

    for effect in row["effects"]:
        kind, target, value, actor = (effect[k] for k in ("kind", "target", "value", "actor_id"))
        audience = {"kind": "actors", "actor_ids": [actor]}
        if kind in {"set", "add"}:
            v = variables[target]
            before = state["state_rules"]["values"][target]
            after = value if kind == "set" else max(v["minimum"], min(v["maximum"], before + value))
            if before != after:
                emit("state.variable_changed", {"id": target, "before": before, "after": after},
                     scope_for(v, state["player"]), f'{v["name"]}：{display_value(before)} → {display_value(after)}')
        elif kind == "resource":
            own = state["actor_states"][actor]
            before = own["resources"][target]
            if before + value < 0:
                invalid("当前资源不足，无法完成此行动")
            after = min(own["resource_limits"][target], before + value)
            if before != after:
                emit("resource.changed", {"actor_id": actor, "resource": target, "before": before, "after": after},
                     audience, f'{ {"hp": "生命", "coins": "金币", "xp": "经验", "vitality": "体力"}.get(target, target)}：{before} → {after}')
        elif kind == "clock":
            clock = state["clocks"][target]
            before, after = clock["value"], min(clock["threshold"], clock["value"] + value)
            if before != after:
                emit("clock.advanced", {"clock_id": target, "before": before, "after": after}, clock["visibility"],
                     f'{clock["name"]}：{before} → {after}')
        elif kind == "reveal":
            fact = state["facts"][target]
            if state["beliefs"][actor].get(target) != fact:
                emit("knowledge.learned", {"actor_id": actor, "fact_id": target, "snapshot": deepcopy(fact)},
                     audience, "获知：" + fact_text(fact))
        elif kind == "message":
            emit("state.message", {"actor_id": actor, "text": effect["text"]}, audience, effect["text"])
    before = deepcopy(state["state_rules"][group].get(row["id"]))
    after = {"count": (before["count"] if before else 0) + 1, "last_time_s": state["game_time_s"]}
    emit("state.rule_fired", {"group": group, "id": row["id"], "before": before, "after": after})
    return events, texts


def action_choices(state, actor_id=None):
    actor_id = player_for(state, actor_id)
    if not config(state) or state["actor_states"][actor_id]["resources"].get("hp", 1) <= 0:
        return []
    choices = []
    for row in config(state)["actions"]:
        if eligible(state, row, "actions", actor_id):
            choices.append({"kind": "state_action", "target_id": row["id"]})
    return choices


def resolve_action(state, op, action_id, actor_id=None):
    if {"kind": "state_action", "target_id": op.target_id} not in action_choices(state, actor_id):
        invalid("当前不能执行这个自定义行动，请刷新场景")
    if op.quantity != 1 or op.item_id is not None or op.when != "always":
        invalid("自定义行动不接受额外数量、物品或条件")
    row = next(a for a in config(state)["actions"] if a["id"] == op.target_id)
    events, texts = execute(state, row, "actions", action_id, viewer_id=actor_id)
    return events, ["完成：" + row["name"], *texts], row["time_cost_s"]


def advance_triggers(state, command, plan, offset=0):
    from .world import apply_events

    if not config(state) or command["mode"] == "ooc":
        return [], []
    events, texts, fired = [], [], set()
    # Three ordered passes allow short chains, never recursive evaluation.
    for _ in range(3):
        changed = False
        for row in config(state)["triggers"]:
            if row["id"] in fired or not eligible(state, row, "triggers"):
                continue
            if row["on"] != "turn" and not (
                row["on"] in {"say", "wait"} and command["mode"] == row["on"] or
                any(o.kind == row["on"] and (not row["target_id"] or o.target_id == row["target_id"]) for o in plan.operations)
            ):
                continue
            batch, visible_texts = execute(state, row, "triggers", command["action_id"], offset + len(events),
                                          viewer_id=command_player(state, command))
            if len(events) + len(batch) > 96:
                invalid("本轮触发效果超过96项，请拆分条件或降低同时触发数量")
            state = apply_events(state, batch, state["version"])
            events.extend(batch)
            texts.extend(visible_texts)
            fired.add(row["id"])
            changed = True
        if not changed:
            break
    return events, texts


def project_rules(state, actor):
    from .world import visible

    cfg = config(state)
    variables = [{"id": v["id"], "name": v["name"], "kind": v["kind"], "minimum": v["minimum"],
                  "maximum": v["maximum"], "value": state["state_rules"]["values"][v["id"]]}
                 for v in cfg["variables"] if visible(scope_for(v, state["player"]), actor)]
    allowed = {a["target_id"] for a in action_choices(state, actor)} if state["actors"][actor]["control"] == "player" else set()
    actions = [{"id": a["id"], "name": a["name"], "description": a["description"]}
               for a in cfg["actions"] if a["id"] in allowed]
    return {"variables": variables, "actions": actions}


def reduce_event(state, event):
    """Validate authored provenance during replay as well as arithmetic preconditions."""
    p, kind = event["payload"], event["type"]
    cfg = config(state)
    if not cfg or "state_rules" not in state:
        invalid("存档缺少声明式状态配置")
    cause = event.get("cause", {})
    group = cause.get("kind")
    row = next((r for r in cfg.get(group, []) if r.get("id") == cause.get("id")), None) if group in {"actions", "triggers"} else None
    if not row:
        invalid("状态事件缺少已声明的来源")
    if kind == "state.variable_changed":
        v = next((v for v in cfg["variables"] if v["id"] == p["id"]), None)
        allowed = False
        if v and type(p["before"]) is type(state["state_rules"]["values"].get(p["id"])) and state["state_rules"]["values"].get(p["id"]) == p["before"]:
            for e in row["effects"]:
                if e["target"] == p["id"] and e["kind"] in {"set", "add"}:
                    expected = e["value"] if e["kind"] == "set" else max(v["minimum"], min(v["maximum"], p["before"] + e["value"]))
                    allowed |= type(expected) is type(p["after"]) and expected == p["after"]
        if not allowed or not valid_value(v, p["after"]) or event["visibility"] != scope_for(v, state["player"]):
            invalid("状态变化来源、范围或前提不一致")
        state["state_rules"]["values"][p["id"]] = deepcopy(p["after"])
    elif kind == "state.rule_fired":
        before = state["state_rules"][group].get(row["id"])
        if (p["group"] != group or p["id"] != row["id"] or p["before"] != before
                or p["after"] != {"count": (before["count"] if before else 0)+1, "last_time_s": state["game_time_s"]}
                or before and (row["once"] or state["game_time_s"] - before["last_time_s"] < row["cooldown_s"])):
            invalid("触发次数或冷却前提不一致")
        state["state_rules"][group][row["id"]] = deepcopy(p["after"])
    elif kind == "state.message":
        if not any(e["kind"] == "message" and e["text"] == p["text"] and e["actor_id"] == p["actor_id"] for e in row["effects"]):
            invalid("消息不是已声明效果")
        if event["visibility"] != {"kind": "actors", "actor_ids": [p["actor_id"]]}:
            invalid("消息接收者不一致")
        state["memories"][p["actor_id"]].append({"event_id": event["event_id"], "text": p["text"],
                                                "game_time_s": state["game_time_s"], "category": "state_effect",
                                                "source_event_ids": [event["event_id"]]})
    else:
        invalid("不支持的状态事件")


def test_command(step, state, aid):
    from .contracts import ActionCommand

    mode = step["kind"] if step["kind"] in {"wait", "say"} else "act"
    op = None if mode != "act" else {"kind": step["kind"], "target_id": step["target_id"]}
    if step["kind"] == "state_action":
        label = next(a["name"] for a in config(state)["actions"] if a["id"] == step["target_id"])
        text = "我决定" + label + "。"
    elif mode == "wait":
        text = f"我等待{step['seconds']}秒。"
    elif mode == "say":
        text = "我向在场的人问候，聊聊目前的情况。"
    else:
        labels = {"move": "locations", "reveal": "facts", "challenge": "quests", "attack": "actors", "rest": "actors"}
        key = step["target_id"].replace("challenge_", "quest_") if step["kind"] == "challenge" else step["target_id"]
        label = state[labels[step["kind"]]][key].get("name", key)
        text = {"move": "我前往", "reveal": "我调查", "challenge": "我完成", "attack": "我攻击", "rest": "我在安全处休息，恢复体力："}[step["kind"]] + label + "。"
    return ActionCommand(action_id=aid, expected_world_version=state["version"], mode=mode, text=text,
                         selected_operation=op)


def audit_state_rules(template):
    from .contracts import TurnPlan
    from .journal import digest
    from .planning import explicit_goal_plan
    from .rules import resolve
    from .world import apply_events, initial_state

    cfg = template["mechanics"].get("state_rules")
    if not cfg:
        return []
    validate_pack(cfg, template)
    checks, coverage = [], {"actions": set(), "triggers": set()}
    for i, test in enumerate(cfg["tests"]):
        state = initial_state(template, "状态验收旅人")
        for j, step in enumerate(test["steps"]):
            cmd = test_command(step, state, f"state_test_{i}_{j}").model_dump()
            try:
                plan = explicit_goal_plan(state, cmd) or TurnPlan(intent=cmd["text"], time_cost_s=step["seconds"])
                events, _, _ = resolve(state, cmd, plan, {}, 7)
            except DomainError as exc:
                invalid(f"状态路线「{test['name']}」第{j+1}步（{cmd['text']}）：{exc.message}")
            after = apply_events(state, events, state["version"]+1)
            assert digest(after) == digest(apply_events(state, events, state["version"]+1)), "状态回放不一致"
            for event in events:
                if event["type"] == "state.rule_fired":
                    coverage[event["payload"]["group"]].add(event["payload"]["id"])
            state = after
        if not all(evaluate(state, c) for c in test["expect"]):
            invalid("状态验收未达到预期：" + test["name"])
        checks.append({"name": "状态路线：" + test["name"], "status": "passed",
                       "detail": f"隔离初始状态执行{len(test['steps'])}步，检查{len(test['expect'])}项结果及确定性回放"})
    for group, covered in coverage.items():
        missing = {r["id"] for r in cfg[group]} - covered
        if missing:
            invalid("状态测试没有实际覆盖" + group + "：" + "、".join(sorted(missing)))
    checks.append({"name": "自定义状态覆盖", "status": "passed",
                   "detail": f"{len(cfg['variables'])}个变量、{len(coverage['actions'])}个行动、{len(coverage['triggers'])}个触发器；覆盖作者声明路线，不证明所有组合"})
    return checks
