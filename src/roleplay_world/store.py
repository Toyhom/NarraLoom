"""All mutable world state is reconstructed from validated journal records."""

import secrets
import time
import uuid
from copy import deepcopy

from .checks import builtin_checks
from .contracts import ActionCommand, DomainError
from .journal import Journal, digest
from .players import HISTORY_KEYS, command_player, commit_perspectives, human_players, player_for
from .world import apply_events, initial_state


def uid(prefix):
    return prefix + "_" + uuid.uuid4().hex[:20]


class Store:
    def __init__(self, root, *, check_registry=None):
        self.check_registry = (check_registry or builtin_checks()).copy()
        self.journal = Journal(root)
        self.campaigns, self.branches, self.actions = {}, {}, {}
        self.worlds, self.stories, self.jobs, self.imports = {}, {}, {}, {}
        self.avatars, self.rooms = {}, {}
        self.publications = {}
        for frame in self.journal.records:
            self._apply(frame["body"])
        for action in self.actions.values():
            if action["status"] in {"accepted", "planning", "characters", "narrating"}:
                action["status"] = "interrupted"
        for job in self.jobs.values():
            if job["status"] in {"queued", "generating_world", "generating_story", "testing"}:
                job["status"] = "interrupted"

    def close(self):
        self.journal.close()

    def record(self, record):
        self.require_writable()
        try:
            self.journal.append(record)
        except Exception as exc:
            if not self.journal.poisoned:
                raise
            # A complete frame may exist even though fsync raised. Do not claim rollback.
            for action in self.actions.values():
                if action["status"] in {"accepted", "planning", "characters", "narrating"}:
                    action.update(status="recovery_required", error="存档写入状态待确认，请恢复服务后查询")
            for job in self.jobs.values():
                if job["status"] in {"queued", "generating_world", "generating_story", "testing"}:
                    job.update(status="recovery_required", error="创作存档写入状态待确认，请恢复服务后查询")
            raise DomainError("recovery_required", "存档写入状态待确认，请恢复服务后查询", 503) from exc
        self._apply(record)

    def require_writable(self):
        if self.journal.poisoned:
            raise DomainError("recovery_required", "存档需要恢复，暂时只能查看已有故事", 503)

    def _apply(self, r):
        kind = r["kind"]
        if kind == "room.member_joined":
            self._apply({"kind": "action.accepted", "action": r["action"]})
            self._apply({"kind": "world.committed", "action_id": r["action"]["id"], "commit": r["commit"]})
            self._apply({"kind": "studio.saved", "collection": "rooms", "value": r["room"]})
        elif kind == "studio.batch_saved":
            for item in r["items"]:
                self._apply({"kind": "studio.saved", **item})
        elif kind == "studio.saved":
            getattr(self, r["collection"])[r["value"]["id"]] = deepcopy(r["value"])
        elif kind == "campaign.restored":
            self.campaigns[r["campaign"]["id"]] = deepcopy(r["campaign"])
            for branch in r["branches"]:
                self.branches[branch["id"]] = deepcopy(branch)
        elif kind == "campaign.created":
            c = deepcopy(r["campaign"])
            self.campaigns[c["id"]] = c
            state = initial_state(c["template"], c["player_name"])
            self.branches[c["main_branch"]] = {
                "id": c["main_branch"], "campaign_id": c["id"], "title": "主线", "parent_id": None,
                "fork_version": 0, "base_state": state, "state": deepcopy(state), "commits": [],
            }
        elif kind == "branch.created":
            source = self.branches[r["source"]]
            state = self.state_at(r["source"], r["version"])
            self.branches[r["id"]] = {"id": r["id"], "campaign_id": source["campaign_id"],
                                       "title": r["title"], "parent_id": r["source"],
                                       "fork_version": r["version"], "base_state": state,
                                       "state": deepcopy(state),
                                       "commits": deepcopy([c for c in source["commits"]
                                                            if c["version"] <= r["version"]])}
        elif kind == "action.accepted":
            self.actions[r["action"]["id"]] = deepcopy(r["action"])
        elif kind == "action.updated":
            self.actions[r["id"]].update(deepcopy(r["patch"]))
        elif kind == "world.committed":
            a = self.actions[r["action_id"]]
            b = self.branches[a["branch_id"]]
            c = deepcopy(r["commit"])
            if b["state"]["version"] + 1 != c["version"]:
                raise RuntimeError("Non-contiguous world commit")
            state = apply_events(b["state"], c["events"], c["version"])
            if digest(state) != c["state_hash"]:
                raise RuntimeError("World reducer disagrees with recorded state")
            b["state"] = state
            b["commits"].append(c)
            a.update({"status": "committed", "commit_id": c["id"], "result": c})
        else:
            raise RuntimeError("Unknown journal record")

    def create_campaign(self, owner, template, name, *, request_key=None, request_hash=None):
        c = {"id": request_key or uid("campaign"), "owner": owner, "template": deepcopy(template), "player_name": name,
             "main_branch": uid("branch"), "created_at": time.time()}
        if request_key is not None:
            from .idempotency import receipt
            existing = receipt(self.campaigns, request_key, owner, request_hash)
            if existing is not None:
                return existing
            c["request_hash"] = request_hash
        self.check_registry.validate_template(template)
        self.record({"kind": "campaign.created", "campaign": c})
        return c

    def studio_get(self, collection, key, owner):
        value = getattr(self, collection).get(key)
        if not value or value["owner"] != owner:
            raise DomainError("not_found", "没有找到这个创作内容", 404)
        return value

    def studio_save(self, collection, value):
        if collection not in {"worlds", "stories", "jobs", "imports", "avatars", "rooms", "publications"}:
            raise ValueError("Invalid studio collection")
        self.record({"kind": "studio.saved", "collection": collection, "value": value})
        return getattr(self, collection)[value["id"]]

    def studio_save_batch(self, items):
        if any(collection not in {"worlds", "stories", "jobs", "imports", "avatars", "rooms", "publications"} for collection, _ in items):
            raise ValueError("Invalid studio collection")
        self.record({"kind": "studio.batch_saved",
                     "items": [{"collection": name, "value": value} for name, value in items]})

    def campaign(self, cid, owner):
        c = self.campaigns.get(cid)
        if not c or c["owner"] != owner:
            raise DomainError("not_found", "没有找到这段冒险", 404)
        return c

    def branch(self, cid, bid, owner):
        self.campaign(cid, owner)
        b = self.branches.get(bid)
        if not b or b["campaign_id"] != cid:
            raise DomainError("not_found", "没有找到这个故事分支", 404)
        return b

    def state_at(self, bid, version):
        b = self.branches[bid]
        if version < b["fork_version"] or version > b["state"]["version"]:
            raise DomainError("invalid_version", "请选择这个分支上已有的存档点", 422)
        state = deepcopy(b["base_state"])
        for c in b["commits"]:
            if b["fork_version"] < c["version"] <= version:
                state = apply_events(state, c["events"], c["version"])
        return state

    def fork(self, cid, bid, owner, version, title):
        self.branch(cid, bid, owner)
        self.state_at(bid, version)
        new_id = uid("branch")
        self.record({"kind": "branch.created", "id": new_id, "source": bid, "version": version, "title": title})
        return self.branches[new_id]

    def accept(self, cid, bid, owner, command, submitter=None, room_id=None, actor_id=None):
        b = self.branch(cid, bid, owner)
        actor = player_for(b["state"], actor_id)
        if command.actor_id and command.actor_id != actor:
            raise DomainError("player_permission", "不能替其他参与者操控角色", 403)
        # Keep the byte-level request shape of legacy commands without optional extensions.
        value = command.model_dump(exclude_none=True)
        aid = command.action_id
        old_command = self.actions.get(aid, {}).get("command")
        needs_actor = bool(old_command.get("actor_id")) if old_command is not None else bool(actor_id or len(human_players(b["state"])) > 1)
        if needs_actor or command.actor_id:
            value["actor_id"] = actor
        if aid in self.actions:
            old = self.actions[aid]
            if (old["owner"] != owner or old["branch_id"] != bid or old["request_hash"] != digest(value)
                    or old.get("submitter") != submitter or old.get("room_id") != room_id):
                raise DomainError("action_id_conflict", "请求编号已用于另一个行动")
            return old, False
        if command.expected_world_version != b["state"]["version"]:
            raise DomainError("stale_world_version", "世界已有变化，请刷新后行动")
        if any(a["branch_id"] == bid and a["status"] in {"accepted", "planning", "characters", "narrating"}
               for a in self.actions.values()):
            raise DomainError("branch_busy", "这一轮仍在进行，可以等待或取消")
        a = {"id": aid, "campaign_id": cid, "branch_id": bid, "owner": owner, "command": value,
             "request_hash": digest(value), "seed": secrets.randbits(63), "status": "accepted",
             "created_at": time.time(), "traces": []}
        if room_id:
            a.update(submitter=submitter, room_id=room_id)
        self.record({"kind": "action.accepted", "action": a})
        return self.actions[aid], True

    def action(self, aid, owner):
        a = self.actions.get(aid)
        if not a or a["owner"] != owner:
            raise DomainError("not_found", "没有找到这个行动", 404)
        return a

    def update(self, aid, **patch):
        self.record({"kind": "action.updated", "id": aid, "patch": patch})

    def commit(self, aid, events, segments, effects, suggestions, roll):
        a = self.actions[aid]
        b = self.branches[a["branch_id"]]
        if a["status"] not in {"accepted", "planning", "characters", "narrating"}:
            raise DomainError("action_not_active", "该行动已经结束")
        if b["state"]["version"] != a["command"]["expected_world_version"]:
            raise DomainError("stale_world_version", "世界版本已改变")
        c = self.build_commit(a, events, segments, effects, suggestions, roll)
        # No await between checking cancellation and appending this atomic commit frame.
        self.record({"kind": "world.committed", "action_id": aid, "commit": c})
        return c

    def build_commit(self, action, events, segments, effects, suggestions, roll):
        a = action
        b = self.branches[a["branch_id"]]
        version = b["state"]["version"] + 1
        state = apply_events(b["state"], events, version)
        c = {"id": uid("commit"), "action_id": a["id"], "version": version, "events": events,
             "state_hash": digest(state), "segments": segments, "effects": effects,
             "suggestions": suggestions, "roll": roll, "player_text": a["command"]["text"],
             "mode": a["command"]["mode"], "created_at": time.time(), "game_time_s": state["game_time_s"]}
        if len(human_players(state)) > 1:
            c.update(primary_actor_id=state["player"], actor_id=command_player(b["state"], a["command"]),
                     perspectives=commit_perspectives(b["state"], state, a["command"], c))
        return c

    def join_room_player(self, room, event):
        """Membership and the new playable actor become durable in one frame."""
        branch = self.branches[room["branch_id"]]
        old = self.rooms[room["id"]]
        if (branch["campaign_id"] != room["campaign_id"] or self.campaigns[room["campaign_id"]]["owner"] != room["owner"]
                or old["closed"] or old["revision"] + 1 != room["revision"]
                or room["members"][:-1] != old["members"]
                or room["members"][-1].get("actor_id") != event["payload"]["id"]
                or any(a["branch_id"] == branch["id"] and a["status"] in {"accepted", "planning", "characters", "narrating"}
                       for a in self.actions.values())):
            raise DomainError("room_busy", "房间或行动已有变化，请刷新后加入", 409)
        aid = uid("join")
        command = ActionCommand(action_id=aid, expected_world_version=branch["state"]["version"], mode="ooc",
                                text=event["payload"]["name"]+"加入了冒险。").model_dump(exclude_none=True)
        action = {"id": aid, "campaign_id": room["campaign_id"], "branch_id": room["branch_id"], "owner": room["owner"],
                  "command": command, "request_hash": digest(command), "seed": 0, "status": "accepted",
                  "created_at": time.time(), "traces": [], "room_id": room["id"], "system_action": "player_joined"}
        commit = self.build_commit(action, [event], [{"kind": "note", "text": command["text"]}], [], [], None)
        self.record({"kind": "room.member_joined", "action": action, "commit": commit, "room": room})


def public_commit(commit, actor_id=None, primary_id=None):
    if "perspectives" in commit:
        return deepcopy(commit["perspectives"].get(actor_id or commit["primary_actor_id"]))
    if actor_id and primary_id and actor_id != primary_id:
        return None
    return {k: deepcopy(commit[k]) for k in HISTORY_KEYS}


def public_history(commits, actor_id, primary_id):
    return [view for commit in commits if (view := public_commit(commit, actor_id, primary_id)) is not None]


def public_action(action, actor_id=None, primary_id=None):
    r = {k: action[k] for k in ["id", "campaign_id", "branch_id", "status", "created_at"]}
    if "error" in action:
        r["error"] = action["error"]
    if "result" in action:
        r["result"] = public_commit(action["result"], actor_id, primary_id)
    return r
