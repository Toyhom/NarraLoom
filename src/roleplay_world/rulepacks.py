"""Declarative game rules: validated content selects mechanics; models never write values."""

import hashlib
import random
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field

from .checks import CheckInput, resolve_check
from .contracts import Contract, DomainError, Identifier
from .players import command_player, followers, human_players, player_for

Label = Annotated[str, Field(min_length=1, max_length=80)]
Amount = Annotated[int, Field(ge=0, le=9999)]


class Gear(Contract):
    id: Identifier
    name: Label
    description: Annotated[str, Field(max_length=500)] = ""
    kind: Literal["ordinary", "consumable", "weapon", "armor"] = "ordinary"
    price: Amount = 0
    power: Annotated[int, Field(ge=0, le=20)] = 0
    restores: Literal["hp", "vitality"] = "hp"


class StartingGear(Contract):
    item_id: Identifier
    quantity: Annotated[int, Field(ge=1, le=99)] = 1
    holder: Annotated[str, Field(pattern=r"^(player|npc_[0-9]+|loc_[0-9]+)$")] = "player"


class Stock(Contract):
    item_id: Identifier
    quantity: Annotated[int, Field(ge=0, le=99)] = 5


class Shop(Contract):
    id: Identifier
    name: Label
    location: Annotated[int, Field(ge=0, le=23)]
    stock: Annotated[list[Stock], Field(max_length=24)] = Field(default_factory=list)
    buyback: bool = True


class Enemy(Contract):
    id: Identifier
    name: Label
    description: Annotated[str, Field(max_length=500)] = ""
    location: Annotated[int, Field(ge=0, le=23)]
    hp: Annotated[int, Field(ge=1, le=200)] = 12
    defense: Annotated[int, Field(ge=5, le=25)] = 10
    attack_bonus: Annotated[int, Field(ge=0, le=12)] = 2
    damage: Annotated[int, Field(ge=1, le=20)] = 3
    reward_coins: Annotated[int, Field(ge=0, le=100)] = 3
    reward_xp: Annotated[int, Field(ge=0, le=100)] = 5


class RuleSet(Contract):
    system: Literal["story-lite", "d20", "d100"] = "story-lite"
    hp: Annotated[int, Field(ge=1, le=200)] = 20
    coins: Amount = 8
    vitality: Annotated[int, Field(ge=1, le=100)] = 10
    attack_bonus: Annotated[int, Field(ge=0, le=12)] = 2
    defense: Annotated[int, Field(ge=5, le=25)] = 10
    damage: Annotated[int, Field(ge=1, le=20)] = 3
    percentile_skill: Annotated[int, Field(ge=1, le=95)] = 60
    party_limit: Annotated[int, Field(ge=1, le=6)] = 4
    recruitable: Annotated[list[int], Field(max_length=32)] = Field(default_factory=list)
    items: Annotated[list[Gear], Field(max_length=64)] = Field(default_factory=list)
    starting_items: Annotated[list[StartingGear], Field(max_length=64)] = Field(default_factory=list)
    shops: Annotated[list[Shop], Field(max_length=16)] = Field(default_factory=list)
    enemies: Annotated[list[Enemy], Field(max_length=24)] = Field(default_factory=list)


def validate_rules(rules, locations, characters):
    if rules is None:
        return
    ids = {g.id for g in rules.items}
    if any(g.kind == "consumable" and g.power <= 0 for g in rules.items):
        raise DomainError("invalid_rules", "消耗品的恢复量必须大于零", 422)
    if len(ids) != len(rules.items) or len({s.id for s in rules.shops}) != len(rules.shops):
        raise DomainError("invalid_rules", "道具和商店 ID 不能重复", 422)
    if len({e.id for e in rules.enemies}) != len(rules.enemies):
        raise DomainError("invalid_rules", "敌人 ID 不能重复", 422)
    if any(s.location >= locations for s in [*rules.shops, *rules.enemies]):
        raise DomainError("invalid_rules", "规则引用了不存在的地点", 422)
    if any(i >= characters or i < 0 for i in rules.recruitable):
        raise DomainError("invalid_rules", "队伍候选人物不存在", 422)
    for shop in rules.shops:
        if len({s.item_id for s in shop.stock}) != len(shop.stock):
            raise DomainError("invalid_rules", "商店库存不能重复", 422)
        if any(s.item_id not in ids for s in shop.stock):
            raise DomainError("invalid_rules", "商店引用了不存在的物品", 422)
    for item in rules.starting_items:
        if item.item_id not in ids:
            raise DomainError("invalid_rules", "初始道具不存在", 422)
        if item.holder.startswith("npc_") and int(item.holder[4:]) >= characters:
            raise DomainError("invalid_rules", "道具持有人不存在", 422)
        if item.holder.startswith("loc_") and int(item.holder[4:]) >= locations:
            raise DomainError("invalid_rules", "道具地点不存在", 422)


def attach_rules(template, rules):
    """Only newly compiled worlds receive rules state. Historical templates are unchanged."""
    if rules is None:
        return template
    t = template
    t["mechanics"]["rules"] = rules.model_dump()
    player = next(a for a in t["actors"] if a["control"] == "player")
    own = player["initial_state"]
    own["resources"].update(hp=rules.hp, coins=rules.coins, vitality=rules.vitality, xp=0)
    own["resource_limits"] = {"hp": rules.hp, "coins": 999999, "vitality": rules.vitality, "xp": 999999}
    own["equipment"] = {"weapon": None, "armor": None}
    catalog = {g.id: g.model_dump() for g in rules.items}
    for i, item in enumerate(rules.starting_items):
        gear = deepcopy(catalog[item.item_id])
        gear.update(id=f"gear_{i}", catalog_id=item.item_id, quantity=item.quantity,
                    holder_id=player["id"] if item.holder == "player" else item.holder)
        t["items"].append(gear)
    for npc in t["actors"]:
        if npc["control"] == "npc":
            t["relations"].append({"from_actor": npc["id"], "to_actor": player["id"], "dimensions": {"trust": 0}})
    for enemy in rules.enemies:
        t["actors"].append({"id": "enemy_"+enemy.id, "name": enemy.name, "control": "npc", "combatant": True,
                            "public_description": enemy.description, "persona": {"personality": enemy.description},
                            "goals": ["保护自己与领地"], "boundaries": ["不会替玩家行动"], "initial_knowledge": [],
                            "initial_state": {"location_id": f"loc_{enemy.location}", "resources": {"hp": enemy.hp},
                                              "resource_limits": {"hp": enemy.hp}}})
    return t


def rules_config(state):
    return state["template"]["mechanics"].get("rules")


def extra_choices(state, actor_id=None):
    cfg = rules_config(state)
    if not cfg:
        return []
    pc = player_for(state, actor_id)
    own = state["actor_states"][pc]
    loc = own["location_id"]
    choices = []
    if own["resources"].get("hp", 1) <= 0:
        return [{"kind": "recover", "target_id": pc}]
    for item in state["items"].values():
        if item["quantity"] <= 0:
            continue
        if item["holder_id"] == loc:
            choices.append({"kind": "take", "target_id": pc, "item_id": item["id"]})
        if item["holder_id"] != pc:
            continue
        if item.get("kind") == "consumable":
            resource = item["restores"]
            if own["resources"][resource] < own["resource_limits"][resource]:
                choices.append({"kind": "use", "target_id": pc, "item_id": item["id"]})
        if item.get("kind") in {"weapon", "armor"} and own["equipment"].get(item["kind"]) != item["id"]:
            choices.append({"kind": "equip", "target_id": pc, "item_id": item["id"]})
        elif item["id"] in own["equipment"].values():
            choices.append({"kind": "unequip", "target_id": pc, "item_id": item["id"]})
    for shop in state.get("shops", {}).values():
        if f"loc_{shop['location']}" != loc:
            continue
        for stock in shop["stock"]:
            gear = next(g for g in cfg["items"] if g["id"] == stock["item_id"])
            if stock["quantity"] > 0 and own["resources"]["coins"] >= gear["price"]:
                choices.append({"kind": "buy", "target_id": shop["id"], "item_id": gear["id"]})
        if shop["buyback"]:
            stocked = {s["item_id"] for s in shop["stock"]}
            choices.extend({"kind": "sell", "target_id": shop["id"], "item_id": item["id"]}
                           for item in state["items"].values() if item["holder_id"] == pc and item["quantity"] > 0
                           and item.get("catalog_id") in stocked and item.get("price", 0) > 0)
    foes = [a for a, s in state["actor_states"].items() if s["location_id"] == loc
            and a.startswith("enemy_") and s["resources"]["hp"] > 0]
    choices.extend({"kind": "attack", "target_id": a} for a in foes)
    if not foes:
        choices.append({"kind": "rest", "target_id": pc})
    for index in cfg["recruitable"]:
        npc = f"npc_{index}"
        if npc in followers(state, pc):
            choices.append({"kind": "dismiss", "target_id": npc})
        elif npc not in state.get("party", []) and state["actor_states"][npc]["location_id"] == loc and len(state.get("party", [pc])) < cfg["party_limit"]:
            choices.append({"kind": "recruit", "target_id": npc})
    return choices


EXTRA_KINDS = {"take", "use", "equip", "unequip", "buy", "sell", "attack", "rest", "recover", "recruit", "dismiss"}


def validate_extra(state, op, actor_id=None):
    if op.kind not in EXTRA_KINDS:
        return
    pc = player_for(state, actor_id)
    choices = extra_choices(state, pc)
    value = {"kind": op.kind, "target_id": op.target_id}
    if op.item_id is not None:
        value["item_id"] = op.item_id
    if value not in choices:
        raise DomainError("invalid_rules_action", "此操作的地点、资源或对象条件不满足", 422)
    own = state["actor_states"][pc]
    if op.kind in {"sell", "take"}:
        item = state["items"][op.item_id]
        if op.quantity > item["quantity"]:
            raise DomainError("invalid_quantity", "物品数量不足", 422)
        if op.kind == "sell" and item["id"] in own["equipment"].values():
            raise DomainError("equipped_item", "当前装备不能出售，请先换下", 422)
    if op.kind == "buy":
        stock = next(s for s in state["shops"][op.target_id]["stock"] if s["item_id"] == op.item_id)
        gear = next(g for g in rules_config(state)["items"] if g["id"] == op.item_id)
        if op.quantity > stock["quantity"] or op.quantity * gear["price"] > own["resources"]["coins"]:
            raise DomainError("stock_or_coins", "购买数量超过库存或可用金币", 422)


def resolve_extra(state, command, op, replies, seed, emit, *, check_registry=None):
    """Resolve one atomic operation from its baseline; emit applies checked events in order."""
    pc = command_player(state, command)
    validate_extra(state, op, pc)
    cfg = rules_config(state)
    own = state["actor_states"][pc]
    item = state["items"].get(op.item_id)
    allowed = {"kind": op.kind, "target_id": op.target_id}
    if op.item_id is not None:
        allowed["item_id"] = op.item_id
    if allowed not in extra_choices(state, pc):
        raise DomainError("invalid_rules_action", "当前条件下不能执行该规则操作", 422)
    if op.quantity != 1 and op.kind not in {"buy", "sell", "take"}:
        raise DomainError("invalid_quantity", "这个操作每轮只能执行一次", 422)

    def resource(actor, key, value, text=None):
        before = state["actor_states"][actor]["resources"][key]
        limit = state["actor_states"][actor]["resource_limits"][key]
        if not 0 <= value <= limit:
            raise DomainError("resource_limit", "资源不足或超过上限", 422)
        emit("resource.changed", {"actor_id": actor, "resource": key, "before": before, "after": value}, text)

    def quantity(value, after):
        if not 0 <= after <= 9999:
            raise DomainError("invalid_quantity", "物品数量不足或超限", 422)
        emit("item.quantity_changed", {"item_id": value["id"], "before": value["quantity"], "after": after})

    def receive(gear, count, text=None):
        value = deepcopy(gear)
        key = hashlib.sha256((command["action_id"]+gear["id"]).encode()).hexdigest()[:20]
        value.update(id="loot_"+key, catalog_id=gear.get("catalog_id", gear["id"]), holder_id=pc, quantity=count)
        emit("item.created", {"item": value}, text)

    if op.kind == "take":
        if op.quantity > item["quantity"]:
            raise DomainError("invalid_quantity", "地上的物品数量不足", 422)
        if op.quantity == item["quantity"]:
            emit("item.transferred", {"item_id": item["id"], "from_holder": item["holder_id"], "to_holder": pc},
                 f"拾取{item['name']} ×{op.quantity}")
        else:
            quantity(item, item["quantity"]-op.quantity)
            receive(item, op.quantity, f"拾取{item['name']} ×{op.quantity}")
    elif op.kind == "use":
        key = item["restores"]
        resource(pc, key, min(own["resource_limits"][key], own["resources"][key]+item["power"]),
                 f"使用{item['name']}，恢复{key}")
        quantity(item, item["quantity"]-1)
    elif op.kind in {"equip", "unequip"}:
        slot = item["kind"]
        emit("equipment.changed", {"actor_id": pc, "slot": slot, "before": own["equipment"].get(slot),
                                   "after": item["id"] if op.kind == "equip" else None},
             ("装备" if op.kind == "equip" else "卸下")+item["name"])
    elif op.kind in {"buy", "sell"}:
        shop = state["shops"][op.target_id]
        if op.kind == "buy":
            gear = next(g for g in cfg["items"] if g["id"] == op.item_id)
            stock = next(s for s in shop["stock"] if s["item_id"] == op.item_id)
            if stock["quantity"] < op.quantity:
                raise DomainError("stock_limit", "库存不足", 422)
            cost = gear["price"]*op.quantity
            resource(pc, "coins", own["resources"]["coins"]-cost, f"支付{cost}金币，购买{gear['name']} ×{op.quantity}")
            receive(gear, op.quantity)
            after = stock["quantity"]-op.quantity
        else:
            if op.quantity > item["quantity"]:
                raise DomainError("invalid_quantity", "持有的数量不足", 422)
            if item["id"] in own["equipment"].values():
                raise DomainError("equipped_item", "先换下装备再出售", 422)
            stock = next(s for s in shop["stock"] if s["item_id"] == item["catalog_id"])
            earned = max(1, item["price"]//2)*op.quantity
            resource(pc, "coins", own["resources"]["coins"]+earned, f"出售{item['name']} ×{op.quantity}，获得{earned}金币")
            quantity(item, item["quantity"]-op.quantity)
            after = stock["quantity"]+op.quantity
        emit("shop.stock_changed", {"shop_id": shop["id"], "item_id": stock["item_id"],
                                    "before": stock["quantity"], "after": after})
    elif op.kind in {"rest", "recover"}:
        for key in ["hp", "vitality"]:
            resource(pc, key, own["resource_limits"][key], "休息后恢复"+key)
        if op.kind == "recover":
            lost = min(own["resources"]["coins"], 3)
            resource(pc, "coins", own["resources"]["coins"]-lost, f"脱险并接受救治，花费{lost}金币")
            start = next(a for a in state["template"]["actors"] if a["control"] == "player")["initial_state"]["location_id"]
            if start != own["location_id"]:
                emit("actor.moved", {"actor_id": pc, "from_location": own["location_id"], "to_location": start}, "回到起点养伤")
                for follower in followers(state, pc):
                    place = state["actor_states"][follower]["location_id"]
                    if follower != pc and place != start:
                        emit("actor.moved", {"actor_id": follower, "from_location": place, "to_location": start})
        return {"time_cost": 1800}
    elif op.kind in {"recruit", "dismiss"}:
        if op.kind == "recruit" and (op.target_id not in replies or replies[op.target_id].reaction != "accept"):
            return {"effects": [state["actors"][op.target_id]["name"]+"暂未同意同行"]}
        emit("party.changed", {"actor_id": op.target_id, "join": op.kind == "recruit",
                              **({"leader_id": pc} if len(human_players(state)) > 1 else {})},
             state["actors"][op.target_id]["name"]+("加入队伍" if op.kind == "recruit" else "离开队伍"))
    elif op.kind == "attack":
        enemy = next(e for e in cfg["enemies"] if "enemy_"+e["id"] == op.target_id)
        rng = random.Random(seed)
        weapon = state["items"].get(own["equipment"].get("weapon"), {})
        armor = state["items"].get(own["equipment"].get("armor"), {})
        percentile = cfg["system"] == "d100"
        modifier = 0 if percentile else cfg["attack_bonus"]
        target = cfg["percentile_skill"] if percentile else enemy["defense"]
        roll = resolve_check(state, CheckInput(kind='attack', skill='attack', purpose='攻击'+enemy['name'],
                             modifier=modifier, difficulty=target, comparison='<=' if percentile else '>='),
                             rng, check_registry)
        die, passed = roll['roll'], roll['passed']
        emit("check.resolved", roll, f"{roll['purpose']}：{roll['dice']} {die}+{modifier}，目标{target}，"+("命中" if passed else "未命中"))
        hp = state["actor_states"][op.target_id]["resources"]["hp"]
        if passed:
            hp = max(0, hp-cfg["damage"]-weapon.get("power", 0))
            resource(op.target_id, "hp", hp, f"{enemy['name']}生命降至{hp}")
        if hp <= 0:
            resource(pc, "coins", own["resources"]["coins"]+enemy["reward_coins"], f"击败{enemy['name']}")
            resource(pc, "xp", own["resources"]["xp"]+enemy["reward_xp"], f"经验 +{enemy['reward_xp']}")
        else:
            defense = cfg["defense"]+armor.get("power", 0)
            counter = resolve_check(state, CheckInput(kind='counterattack', skill='attack', purpose=enemy['name']+'反击',
                                    modifier=0 if percentile else enemy['attack_bonus'],
                                    difficulty=max(5, 55-armor.get('power', 0)*5) if percentile else defense,
                                    comparison='<=' if percentile else '>='), rng, check_registry)
            retaliation, hit = counter['roll'], counter['passed']
            receipt = {key: counter[key] for key in ('purpose', 'roll', 'passed', 'dice', 'modifier')}
            receipt['target'] = counter['difficulty']
            if state['template']['mechanics'].get('checks'):
                receipt.update(counter)
            emit("check.resolved", receipt, f"{enemy['name']}反击掷骰{retaliation}，"+("命中" if hit else "未命中"))
            roll["counterattack"] = receipt
            if hit:
                resource(pc, "hp", max(0, own["resources"]["hp"]-enemy["damage"]), f"受到{enemy['damage']}点伤害")
        return {"roll": roll, "time_cost": 30}
    return {}
