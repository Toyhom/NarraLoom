"""One bounded, cancellable model pipeline per action; commit is synchronous."""

import asyncio
import logging
from copy import deepcopy

from . import prompts
from .content_preferences import content_language, content_text, language_prompt
from .contracts import DomainError, Narration, TurnPlan
from .memory import note_event
from .planning import actor_schema, choices, explicit_goal_plan, normalize_plan, plan_schema, validate_plan
from .players import command_player, heard_by, human_players
from .routing import route_action
from .rules import resolve
from .simulation import advance_world, control_event
from .world import apply_events, model_view, npc_context, visible

log = logging.getLogger(__name__)


class Runtime:
    def __init__(self, store, gateway):
        self.store, self.gateway = store, gateway
        self.tasks = {}
        self.semaphore = asyncio.Semaphore(2)

    def start(self, action_id):
        task = asyncio.create_task(self.run(action_id))
        self.tasks[action_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(action_id, None))

    def cancel(self, action_id, owner):
        self.store.require_writable()
        a = self.store.action(action_id, owner)
        if a["status"] == "committed":
            raise DomainError("already_committed", "结果已经保存；停止查看不会撤销世界变化")
        if a["status"] != "cancelled":
            self.store.update(action_id, status="cancelled")
            if action_id in self.tasks:
                self.tasks[action_id].cancel()

    def retry(self, action_id, owner):
        self.store.require_writable()
        a = self.store.action(action_id, owner)
        if a["status"] not in {"failed", "interrupted"}:
            raise DomainError("cannot_retry", "只有失败或中断的行动可以重试")
        b = self.store.branches[a["branch_id"]]
        if b["state"]["version"] != a["command"]["expected_world_version"]:
            raise DomainError("stale_world_version", "世界已改变，请发起新的行动")
        if any(x["branch_id"] == a["branch_id"] and x["id"] != action_id
               and x["status"] in {"accepted", "planning", "characters", "narrating"}
               for x in self.store.actions.values()):
            raise DomainError("branch_busy", "已有另一个行动进行中")
        self.store.update(action_id, status="accepted", error=None)
        self.start(action_id)

    async def close(self):
        for task in list(self.tasks.values()):
            task.cancel()
        await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)

    async def run(self, aid):
        budget = {"calls": 0, "repairs": 0, "traces": [], "max_calls": 6}
        try:
            async with self.semaphore, asyncio.timeout(180):
                a = self.store.actions[aid]
                budget["traces"] = deepcopy(a.get("traces", []))
                if a["status"] == "cancelled":
                    return
                state = deepcopy(self.store.branches[a["branch_id"]]["state"])
                command = a["command"]
                player = command_player(state, command)
                audience = heard_by(state, command)  # Validate private targets before any model call or early commit.
                human_exchange = command["mode"] == "say" and len(human_players(state)) > 1 and not any(
                    state["actors"][actor]["control"] == "npc" for actor in audience)
                self.store.update(aid, status="planning")
                if command.get("trade"):
                    from .trades import resolve_trade

                    events, text = resolve_trade(state, command)
                    self.store.commit(aid, events, [{"kind": "note", "text": text}], [], [], None)
                    return
                def text(zh, en):
                    return content_text(content_language(state), zh, en)

                if command.get("simulation_control"):
                    event = control_event(state, command)
                    self.store.commit(aid, [event], [{"kind": "note", "text": text("暂停世界主动运行", "World simulation paused") if event["payload"]["after"] else text("恢复世界主动运行", "World simulation resumed")}], [], [], None)
                    return
                if command.get("note_record"):
                    event = note_event(state, command)
                    self.store.commit(aid, [event], [{"kind": "note", "text": text("更新手记：", "Journal updated: ")+event["payload"]["text"]}],
                                      [], [], None)
                    return
                if "prepared" in a:
                    prepared = deepcopy(a["prepared"])
                else:
                    if a.get("plan"):
                        plan = normalize_plan(state, command, TurnPlan.model_validate(a["plan"]))
                        validate_plan(state, command, plan)
                    elif (plan := explicit_goal_plan(state, command)) is not None:
                        self.store.update(aid, plan=plan.model_dump())
                    elif human_exchange:
                        plan = TurnPlan(intent="玩家之间交谈", operations=[], speakers=[], time_cost_s=30)
                        self.store.update(aid, plan=plan.model_dump())
                    elif (plan := await route_action(self.gateway, state, command, aid, budget)) is not None:
                        self.store.update(aid, plan=plan.model_dump(), traces=budget["traces"])
                    else:
                        context = {"player_input": command["text"], "mode": command["mode"],
                                   "player_view": model_view(state, player, query=command["text"]), "locations": list(state["locations"].values()),
                                   "mechanics": state["template"]["mechanics"],
                                   "story_outline": state["template"].get("outline", []),
                                   "clocks": list(state["clocks"].values()),
                                   "item_holders": {k: v["holder_id"] for k, v in state["items"].items()},
                                   "facts": list(state["facts"].values()),
                                   "actor_locations": {k: v["location_id"] for k, v in state["actor_states"].items()}}
                        context["allowed_operations"] = choices(state, command["mode"], player, command.get("whisper_to"))[0]
                        if command.get("whisper_to"):
                            context["private_recipient"] = command["whisper_to"]
                        plan = await self.gateway.generate("game_master", prompts.GM + language_prompt(content_language(state)), context,
                            plan_schema(state, command), aid, budget,
                            validate=lambda p: validate_plan(state, command, normalize_plan(state, command, p)))
                        plan = normalize_plan(state, command, plan)
                        validate_plan(state, command, plan)
                        self.store.update(aid, plan=plan.model_dump(), traces=budget["traces"])
                    npc_state = deepcopy(state)
                    observed_effects, observed_roll = [], None
                    if not any(op.kind in {"give", "recruit"} for op in plan.operations):
                        preview_events, observed_effects, observed_roll = resolve(state, command, plan, {}, a["seed"])
                        npc_state = apply_events(state, preview_events, state["version"])
                    for op in plan.operations:
                        if op.kind == "move":
                            if op.target_id not in [r["to"] for r in state["locations"][
                                    state["actor_states"][player]["location_id"]]["exits"]]:
                                raise DomainError("invalid_plan", "模型提出了不存在的相邻路线", 422)
                            npc_state["actor_states"][player]["location_id"] = op.target_id
                    audience = heard_by(npc_state, command)
                    speakers = [actor for actor in dict.fromkeys(plan.speakers) if actor in audience
                                and state["actors"][actor]["control"] == "npc"]
                    for op in plan.operations:
                        if op.kind in {"give", "recruit"} and op.target_id not in speakers:
                            speakers.insert(0, op.target_id)
                    speakers = speakers[:2]
                    if any(actor not in audience or state["actors"][actor]["control"] != "npc" for actor in speakers):
                        raise DomainError("invalid_plan", "模型选择了不在场的发言者", 422)
                    replies = {}
                    self.store.update(aid, status="characters")
                    for actor in speakers:
                        offers = [{"id": op.item_id, "name": state["items"][op.item_id]["name"], "quantity": op.quantity}
                                  for op in plan.operations if op.kind == "give" and op.target_id == actor
                                  and op.item_id in state["items"]]
                        context = npc_context(npc_state, actor, command["text"], offers, player)
                        context["current_observed_effects"] = observed_effects
                        if state["template"]["mechanics"].get("state_rules") or len(human_players(state)) > 1:
                            # The player's effect text may contain player-only variable values.
                            # NPCs receive their own projected candidate state and addressed notices.
                            context["current_observed_effects"] = [e["payload"]["text"] for e in preview_events
                                if (e["type"] == "state.message" and e["payload"]["actor_id"] == actor
                                    or e["type"] == "action.observed" and "text" in e["payload"])
                                and visible(e["visibility"], actor)] if not any(
                                    op.kind in {"give", "recruit"} for op in plan.operations) else []
                        context["current_roll"] = observed_roll
                        consent = any(op.kind == "recruit" and op.target_id == actor for op in plan.operations)
                        context["invitation"] = "玩家邀请你加入同行队伍，接受或拒绝由你决定" if consent else None
                        context["audible_replies"] = [{"speaker": state["actors"][k]["name"], "text": r.text}
                                                      for k, r in replies.items()]
                        replies[actor] = await self.gateway.generate("character_actor", prompts.NPC + language_prompt(content_language(state)), context,
                                                                    actor_schema(npc_state, actor, offers, consent), aid, budget)
                    events, effects, roll = resolve(state, command, plan, replies, a["seed"])
                    segments = []
                    if command["mode"] == "say" and (len(human_players(state)) > 1 or command.get("whisper_to")):
                        events.extend([
                            {"event_id": aid+"_player_speech", "type": "speech.recorded",
                             "visibility": {"kind": "actors", "actor_ids": audience},
                             "payload": {"speaker_id": player, "text": command["text"], "private": bool(command.get("whisper_to"))}},
                            {"event_id": aid+"_player_memory", "type": "memory.recorded",
                             "visibility": {"kind": "actors", "actor_ids": audience},
                             "payload": {"audience": audience, "category": "utterance",
                                         "world_version": state["version"]+1, "source_event_ids": [aid+"_player_speech"],
                                         "text": state["actors"][player]["name"]+text("说：", " says: ")+command["text"]}}])
                    for actor, reply in replies.items():
                        segments.append({"kind": "dialogue", "speaker_id": actor,
                                         "speaker_name": state["actors"][actor]["name"], "text": reply.text,
                                         "emotion": reply.emotion, "gesture": reply.gesture})
                        event_id = f"{aid}_speech_{actor}"
                        events.append({"event_id": event_id, "type": "speech.recorded",
                                       "visibility": {"kind": "actors", "actor_ids": audience},
                                       "payload": {"speaker_id": actor, "text": reply.text,
                                                   "emotion": reply.emotion, "gesture": reply.gesture,
                                                   "private": bool(command.get("whisper_to"))}})
                        events.append({"event_id": f"{aid}_memory_{actor}", "type": "memory.recorded",
                                       "visibility": {"kind": "actors", "actor_ids": audience},
                                       "payload": {"audience": audience,
                                                   "category": "utterance", "source_event_ids": [event_id],
                                                   "world_version": state["version"]+1,
                                                   "text": f'{state["actors"][player]["name"]}：{command["text"]}\n'
                                                   +state["actors"][actor]["name"]+text("说：", " says: ")+reply.text}})
                    if command["mode"] != "ooc":
                        # Factual outcomes are separate from what someone merely said.
                        events.append({"event_id": aid + "_outcome", "type": "memory.recorded",
                                       "visibility": {"kind": "actors", "actor_ids": [player]},
                                       "payload": {"audience": [player],
                                                   "category": "outcome", "world_version": state["version"]+1,
                                                   "source_event_ids": [e["event_id"] for e in events
                                                                        if e["type"] not in {"memory.recorded", "speech.recorded"}],
                                                   "text": text("玩家提出：", "Player requested: ") + command["text"] + text("；引擎裁定：", "; Resolved outcome: ") + ("; ".join(effects) or text("没有物品或任务变化", "No inventory or quest changes"))}})
                    candidate = apply_events(state, events, state["version"] + 1)
                    autonomous, world_effects = await advance_world(
                        state, candidate, command, list(replies), self.gateway, budget,
                        a.get("autonomous"), lambda proposal: self.store.update(aid, autonomous=proposal),
                    )
                    events.extend(autonomous)
                    effects.extend(world_effects)
                    if autonomous:
                        candidate = apply_events(candidate, autonomous, state["version"]+1)
                    prepared = {"events": events, "effects": effects, "roll": roll,
                                "segments": segments, "view": model_view(candidate, player, query=command["text"]),
                                "narration_required": bool(plan.operations) or bool(world_effects)
                                or any(e["type"] == "fact.updated" for e in events)
                                or bool(effects) and any(e["type"].startswith("state.") for e in events)}
                    self.store.update(aid, prepared=prepared)
                self.store.update(aid, status="narrating")
                if human_exchange:
                    # Another human supplies their own response on their turn.
                    segments = [{"kind": "note", "text": text("私语已送达。", "Whisper delivered.") if command.get("whisper_to") else text("你向在场的人说了这句话。", "You spoke to the people present.")}]
                    suggestions = []
                elif prepared["segments"] and not prepared.get("narration_required", bool(prepared["effects"])):
                    # A pure exchange already has its own voice. Avoid asking another
                    # model to invent a second answer for the same NPC.
                    segments = prepared["segments"]
                    language = content_language(state)
                    if language.lower().split("-")[0] in {"zh", "en"}:
                        suggestions = [text("我仔细观察周围。", "I look around carefully."), *[
                            text("我前往", "I go to ") + e["name"] + text("。", ".")
                            for e in prepared["view"]["exits"]]][:3]
                    else:
                        suggestions = state["template"].get("opening_suggestions", [])[:3]
                else:
                    narration_view = {k: v for k, v in prepared["view"].items() if k != "memories"}
                    narration = await self.gateway.generate("narrator", prompts.NARRATOR + language_prompt(content_language(state)),
                        {"player_input": command["text"], "mode": command["mode"],
                         "player_view": narration_view, "effects": prepared["effects"],
                         "committed_dialogue": prepared["segments"],
                         "roll": prepared["roll"]}, Narration, aid, budget)
                    segments = [{"kind": "narration", "text": narration.text}, *prepared["segments"]]
                    suggestions = narration.suggestions
                self.store.update(aid, traces=budget["traces"])
                self.store.commit(aid, prepared["events"], segments, prepared["effects"],
                                  suggestions, prepared["roll"])
        except asyncio.CancelledError:
            a = self.store.actions[aid]
            if a["status"] not in {"cancelled", "committed", "recovery_required"}:
                self.store.update(aid, status="interrupted")
        except Exception as exc:
            log.exception("Action %s failed", aid)
            a = self.store.actions[aid]
            if a["status"] not in {"cancelled", "committed"} and not self.store.journal.poisoned:
                message = exc.message if isinstance(exc, DomainError) else "本轮暂时未能完成，世界没有改变，可以重试"
                self.store.update(aid, status="failed", error=message, traces=budget["traces"])
