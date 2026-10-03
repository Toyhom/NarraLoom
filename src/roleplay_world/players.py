"""Explicit player principals; the canonical world's original player never changes."""

from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field

from .contracts import Contract, DomainError, Identifier


class PlayerProfile(Contract):
    id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=32)]
    role: Annotated[str, Field(min_length=1, max_length=80)] = "同行旅人"
    initialization_version: Literal["1"] | None = None


def player_for(state, actor_id=None):
    actor_id = actor_id or state["player"]
    if state["actors"].get(actor_id, {}).get("control") != "player":
        raise DomainError("invalid_player", "这个人物不是可操控的玩家角色", 403)
    return actor_id


def command_player(state, command):
    return player_for(state, command.get("actor_id"))


def human_players(state):
    return sorted((aid for aid, actor in state["actors"].items() if actor["control"] == "player"),
                  key=lambda aid: (aid != state["player"], aid))


def followers(state, actor_id=None):
    actor_id = player_for(state, actor_id)
    return [a for a in state.get("party", []) if state["actors"][a]["control"] == "npc"
            and state.get("companion_leaders", {}).get(a, state["player"]) == actor_id]


def heard_by(state, command):
    from .world import present

    player = command_player(state, command)
    target = command.get("whisper_to")
    if target:
        if (command["mode"] != "say" or target == player or target not in present(state, player)
                or command.get("note_record") or command.get("simulation_control") or command.get("selected_operation")):
            raise DomainError("invalid_whisper", "私语只能在说话模式下向同场的另一人物发送", 422)
        return [player, target]
    return present(state, player)


def join_player(state, event):
    """Reducer for a human joining; no request can supply resources or knowledge."""
    from .world import visible

    profile = PlayerProfile.model_validate(event["payload"])
    if (not profile.id.startswith("pc_") or profile.id in state["actors"] or len(human_players(state)) >= 6
            or event["visibility"] != {"kind": "public"}):
        raise DomainError("invalid_player_join", "人物已存在、席位已满或加入事件不合法", 422)
    original = next(a for a in state["template"]["actors"] if a["id"] == state["player"])
    actor = deepcopy(original)
    actor.update(id=profile.id, name=profile.name, public_description=profile.role,
                 persona={"role": profile.role}, goals=["由参与者自己决定行动"], boundaries=["不能由模型代替做出选择"])
    actor.pop("avatar_id", None)
    own = deepcopy(original["initial_state"])
    # Only common catalog gear is replicated; unique plot props stay with their
    # original holder. Joining never copies a live player's acquired inventory.
    items = [deepcopy(i) for i in state["template"]["items"]
             if i["holder_id"] == state["player"] and i.get("catalog_id")]
    mapping = {}
    for index, item in enumerate(items):
        item_id = "gear_"+profile.id+"_"+str(index)
        mapping[item["id"]] = item_id
        item.update(id=item_id, holder_id=profile.id)
        if item_id in state["items"]:
            raise DomainError("invalid_player_join", "新人物的装备ID冲突", 422)
        state["items"][item_id] = item
    if "equipment" in own:
        own["equipment"] = {slot: mapping.get(item) for slot, item in own["equipment"].items()}
    known = [fid for fid, fact in state["facts"].items() if visible(fact.get("visibility", {}), profile.id)]
    if profile.initialization_version == "1":
        # Restored snapshot maps are sorted by the journal serializer. New joins
        # must produce the same knowledge array before and after recovery. Keep
        # legacy unversioned events byte-compatible with their recorded hashes.
        known.sort()
    actor.update(initial_state=deepcopy(own), initial_knowledge=known)
    state["actors"][profile.id] = actor
    state["actor_states"][profile.id] = own
    state["knowledge"][profile.id] = known
    state["beliefs"][profile.id] = {fid: deepcopy(state["facts"][fid]) for fid in known}
    state["memories"][profile.id] = []


HISTORY_KEYS = ("id", "action_id", "version", "segments", "effects", "suggestions", "roll", "player_text", "mode", "game_time_s")


def commit_perspectives(before, after, command, commit):
    """Capture observations at commit time, without disclosing another PC's prose."""
    from .world import fact_text, visible

    player = command_player(before, command)
    result = {player: {k: deepcopy(commit[k]) for k in HISTORY_KEYS}}
    for actor in human_players(after):
        if actor == player:
            continue
        segments, effects = [], []
        for event in commit["events"]:
            kind, payload = event["type"], event["payload"]
            public_announcement = kind == "announcement.recorded" and payload["fact"]["visibility"]["kind"] == "public"
            if not visible(event["visibility"], actor) and not public_announcement:
                continue
            text = None
            if kind == "speech.recorded":
                speaker = payload["speaker_id"]
                segments.append({"kind": "dialogue", "speaker_id": speaker,
                                 "speaker_name": after["actors"][speaker]["name"], "text": payload["text"],
                                 **{k: payload[k] for k in ("emotion", "gesture", "private") if k in payload}})
            elif kind == "player.joined":
                text = payload["name"]+"以"+payload["role"]+"的身份加入了冒险。"
            elif kind.startswith("trade."):
                from .trades import describe

                offer = after["trades"][payload["offer"]["id"] if kind == "trade.proposed" else payload["id"]]
                text = describe(after, offer, "pending" if kind == "trade.proposed" else payload["status"])
            elif kind == "action.observed":
                text = payload.get("text")
            elif kind == "actor.moved":
                text = after["actors"][payload["actor_id"]]["name"]+"前往"+after["locations"][payload["to_location"]]["name"]
            elif kind == "item.transferred":
                text = after["items"][payload["item_id"]]["name"]+"交给了"+after["actors"][payload["to_holder"]]["name"]
            elif kind == "knowledge.learned" and payload["actor_id"] == actor:
                text = "获知："+fact_text(payload.get("snapshot", after["facts"][payload["fact_id"]]))
            elif kind == "state.message" and payload["actor_id"] == actor:
                text = payload["text"]
            elif kind == "state.variable_changed":
                from .state_rules import config, display_value

                variable = next(v for v in config(after)["variables"] if v["id"] == payload["id"])
                text = variable["name"]+"："+display_value(payload["before"])+" → "+display_value(payload["after"])
            elif public_announcement:
                text = fact_text(payload["fact"])
            elif kind == "resource.changed" and payload["actor_id"] == actor:
                text = {"hp": "生命", "coins": "金币", "vitality": "体力", "xp": "经验"}.get(payload["resource"], payload["resource"])
                text += f"：{payload['before']} → {payload['after']}"
            if text:
                effects.append(text)
        if segments or effects:
            result[actor] = {**{k: deepcopy(commit[k]) for k in ("id", "action_id", "version", "mode", "game_time_s")},
                             "segments": segments, "effects": effects, "suggestions": [], "roll": None, "player_text": ""}
    for view in result.values():
        view.update(actor_id=player, actor_name=before["actors"][player]["name"])
    if any(e["type"] == "speech.recorded" and e["payload"].get("private") for e in commit["events"]):
        result[player]["private"] = True
    return result
