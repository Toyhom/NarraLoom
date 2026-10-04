import asyncio
import time
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from roleplay_world.app import create_app
from roleplay_world.content import (
    StoryBlueprint,
    WorldBlueprint,
    compile_story,
    story_generation_schema,
    validate_story,
    validate_world,
)
from roleplay_world.contracts import ActorReply, DomainError, Narration, TurnPlan
from roleplay_world.planning import normalize_plan, validate_plan
from roleplay_world.quality import audit_template
from roleplay_world.store import Store


@pytest.fixture
def world_blueprint():
    return WorldBlueprint(
        title="星环小站",
        genre="太空悬疑",
        tone="温暖探索",
        premise="小站居民互相依靠。",
        setting="居民住在旋转的空间站里。",
        locations=[
            {"name": "接驳大厅", "description": "列车停靠的大厅。", "connects_to": [1]},
            {"name": "生态花园", "description": "种着粮食的温室。", "connects_to": [0, 2]},
            {"name": "观测平台", "description": "可以查看星空。", "connects_to": [1]},
        ],
        characters=[
            {
                "name": "林舟",
                "role": "站长",
                "personality": "务实",
                "goal": "保护居民",
                "boundary": "不伤害旅客",
                "location": 0,
                "secret": "藏着一封私人信。",
            },
            {
                "name": "小禾",
                "role": "园丁",
                "personality": "好奇",
                "goal": "培育植物",
                "boundary": "不浪费粮食",
                "location": 1,
                "secret": "养着一只小猫。",
            },
        ],
    )


@pytest.fixture
def story_blueprint():
    return StoryBlueprint(
        title="失去方向的信号",
        synopsis="寻找错乱信号的来源。",
        player_role="维修员",
        opening="大厅里的广播响了两遍。",
        start_location=0,
        starting_item="记录本",
        acts=["从居民处了解异常。", "调查之后选择恢复信号。"],
        clues=[
            {"title": "广播记录", "text": "广播被提前录制。", "location": 0, "known_by": [0]},
            {"title": "天线方向", "text": "天线偏向了温室。", "location": 2, "known_by": [1]},
            {"title": "线路标签", "text": "温室旁有一条备用线路。", "location": 1, "known_by": []},
        ],
        challenges=[
            {
                "title": "检查备用线路",
                "description": "接通备用线路。",
                "location": 1,
                "required_clues": [2],
                "skill": "craft",
                "difficulty": 8,
                "success": "线路接通了。",
                "ending": False,
            },
            {
                "title": "重新校准信号",
                "description": "根据广播记录把接收器指向正确的方向。",
                "location": 2,
                "required_clues": [0],
                "skill": "none",
                "difficulty": 8,
                "success": "居民重新收到了正确信号。",
                "ending": True,
            },
        ],
        pressure_name="信号衰减",
        pressure_event="备用广播开始提醒居民注意。",
    )


@pytest.mark.parametrize("case", ["bad_location", "bad_edge", "disconnected", "duplicate"])
def test_world_validation(world_blueprint, case):
    w = world_blueprint.model_copy(deep=True)
    if case == "bad_location":
        w.characters[0].location = 7
    if case == "bad_edge":
        w.locations[0].connects_to = [7]
    if case == "disconnected":
        w.locations[1].connects_to = [0]
        w.locations[2].connects_to = [2]
    if case == "duplicate":
        w.locations[1].name = w.locations[0].name
    with pytest.raises(DomainError):
        validate_world(w)


@pytest.mark.parametrize("case", ["bad_location", "bad_actor", "bad_clue", "no_ending", "random_only"])
def test_story_validation(world_blueprint, story_blueprint, case):
    s = story_blueprint.model_copy(deep=True)
    if case == "bad_location":
        s.start_location = 7
    if case == "bad_actor":
        s.clues[0].known_by = [7]
    if case == "bad_clue":
        s.challenges[0].required_clues = [7]
    if case == "no_ending":
        s.challenges[1].ending = False
    if case == "random_only":
        s.challenges[1].skill = "craft"
    with pytest.raises(DomainError):
        validate_story(world_blueprint, s)


def test_generation_schema_rejects_nonexistent_actor_before_runtime(world_blueprint, story_blueprint):
    schema = story_generation_schema(world_blueprint)
    payload = story_blueprint.model_dump()
    payload["clues"][0]["known_by"] = [2]
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_every_generated_goal_and_clue_has_an_executable_path(world_blueprint, story_blueprint):
    template = compile_story(world_blueprint, story_blueprint, "story_test")
    checks = audit_template(template)
    assert len(checks) >= 6 and all(c["status"] == "passed" for c in checks)


def test_user_reported_travel_and_question_selects_destination_actor(state):
    command = {"mode": "act", "text": "我去雾灯酒馆打听其它离港方法。"}
    plan = TurnPlan(
        intent="问路", operations=[{"kind": "move", "target_id": "loc_tavern"}], speakers=["npc_captain"]
    )
    plan = normalize_plan(state, command, plan)
    validate_plan(state, command, plan)
    assert plan.speakers == ["npc_keeper"]
    assert plan.operations[0].target_id == "loc_tavern"


class CreativeFixture:
    verification_mode = "test_fixture"

    def __init__(self, w, s, block=False):
        self.w, self.s, self.block = w, s, block

    async def health(self):
        return {"ready": True, "mode": "test_fixture"}

    async def generate(self, role, system, data, schema, aid, budget, validate=None):
        if self.block:
            await asyncio.sleep(30)
        if role == "world_actor":
            return schema.model_validate({"location_id": data["allowed_locations"][0]["id"], "reason": "测试角色留在原地。"})
        if role == "content_reviewer":
            return schema(checks=[])
        if role == "world_builder":
            return self.w.model_copy(deep=True)
        if role == "story_builder":
            return schema.model_validate(self.s.model_dump(exclude_none=True))
        if role == "character_actor":
            return ActorReply(text="你好，欢迎来到这里。", reaction="accept" if data["offered_items"] else "none")
        if role == "narrator":
            return Narration(text="这是明确标记的自动化测试回复。", suggestions=[])
        text = data["player_input"]
        assert data["story_outline"] == self.s.acts, "GM must receive the authored outline"
        assert "story_outline" not in data["player_view"], "GM outline is not player knowledge"
        mode = data["mode"]
        ops = []
        speakers = []
        if mode == "act":
            if "前往" in text:
                target = next(x for x in data["locations"] if x["name"] in text)
                ops = [{"kind": "move", "target_id": target["id"]}]
            elif "调查" in text:
                target = next(f for f in data["facts"] if f.get("name", "NO_NAME") in text)
                ops = [{"kind": "reveal", "target_id": target["id"]}]
            elif "完成" in text:
                target = next(c for c in data["mechanics"]["challenges"] if c["name"] in text)
                ops = [{"kind": "challenge", "target_id": target["id"]}]
        if mode == "say":
            speakers = [a["id"] for a in data["player_view"]["present_actors"] if a["control"] == "npc"][:2]
        plan = TurnPlan(
            intent=text[:120],
            operations=ops,
            speakers=speakers,
            time_cost_s=120 if mode == "wait" else 0 if mode == "ooc" else 30,
        )
        if validate:
            validate(plan)
        return plan


def session(client):
    client.headers["X-CSRF-Token"] = client.post("/api/session").json()["csrf_token"]


def wait_job(client, jid):
    for _ in range(500):
        j = client.get("/api/studio/jobs/" + jid).json()
        if j["status"] in ["ready", "failed", "cancelled", "interrupted"]:
            return j
        time.sleep(0.01)
    raise AssertionError("Creation did not finish")


def test_failed_state_review_preserves_editable_draft_and_retry_does_not_regenerate(
    tmp_path, monkeypatch, world_blueprint, story_blueprint
):
    generated, reviews = [], []

    class StateCreator(CreativeFixture):
        async def generate(self, role, system, data, schema, aid, budget, validate=None):
            generated.append(role)
            if role == "state_builder":
                result = schema.model_validate({
                    "variables": [{"id": "progress", "name": "校准进度", "initial": 0}],
                    "actions": [{"id": "inspect", "name": "校准检查", "effects": [{"kind": "add", "target": "progress", "value": 1}]}],
                    "tests": [{"name": "校准路线", "steps": [{"kind": "state_action", "target_id": "inspect"}],
                               "expect": [{"source": "variable", "key": "progress", "value": 1}]}]})
                validate(result)
                return result
            return await super().generate(role, system, data, schema, aid, budget, validate)

    async def review(world, story, generate, jid, *, repair=False):
        reviews.append(repair)
        if len(reviews) == 1:
            raise DomainError("content_inconsistent", "需要调整目标文字", 422)
        if repair:
            story.opening = "已校准的开场文字。"
        return story, {"status": "passed", "mode": "model_assisted_review", "repair_rounds": int(repair)}

    monkeypatch.setattr("roleplay_world.studio.review_story", review)
    with TestClient(create_app(tmp_path/"draft", StateCreator(world_blueprint, story_blueprint))) as client:
        session(client)
        job = client.post("/api/studio/worlds", json={"prompt": "生成一个星环小站世界", "custom_states": True}).json()
        failed = wait_job(client, job["id"])
        assert failed["status"] == "failed" and failed["story_id"]
        draft = client.get("/api/studio").json()["stories"][0]
        assert draft["content"]["state_rules"]["variables"][0]["id"] == "progress"
        assert client.post("/api/campaigns", json={"story_id": draft["id"], "player_name": "测试"}).status_code == 409
        assert client.post("/api/studio/jobs/"+job["id"]+"/retry").status_code == 200
        assert wait_job(client, job["id"])["status"] == "ready"
        assert all(generated.count(role) == 1 for role in ("world_builder", "story_builder", "state_builder"))
        saved = client.get("/api/studio").json()["stories"][0]
        assert saved["content"]["opening"] == "已校准的开场文字。"
        campaign = client.post("/api/campaigns", json={"story_id": saved["id"], "player_name": "测试"}).json()
        view = client.get(f"/api/campaigns/{campaign['id']}/branches/{campaign['branch_id']}/view").json()
        assert view["opening"] == "已校准的开场文字。"
        saved["content"]["opening"] = "作者亲自编辑的开场。"
        edited = client.put("/api/studio/stories/"+saved["id"], json={"expected_revision": saved["revision"], "content": saved["content"]}).json()
        assert wait_job(client, edited["id"])["status"] == "ready"
        assert reviews == [True, True, False]
        assert client.get("/api/studio").json()["stories"][0]["content"]["opening"] == "作者亲自编辑的开场。"


def test_creation_multiple_stories_edits_export_ownership_and_pinned_campaign(
    tmp_path, world_blueprint, story_blueprint
):
    app = create_app(tmp_path / "api", CreativeFixture(world_blueprint, story_blueprint))
    with TestClient(app) as client:
        session(client)
        job = client.post("/api/studio/worlds", json={"prompt": "生成一个星环小站世界"}).json()
        result = wait_job(client, job["id"])
        assert result["status"] == "ready", result
        data = client.get("/api/studio").json()
        w, s = data["worlds"][0], data["stories"][0]
        assert s["test_report"]["status"] == "passed"
        campaign = client.post("/api/campaigns", json={"story_id": s["id"], "player_name": "阿青"}).json()
        view_url = f"/api/campaigns/{campaign['id']}/branches/{campaign['branch_id']}/view"
        before = client.get(view_url).json()
        w["content"]["title"] = "星环小站第二版"
        assert (
            client.put(
                "/api/studio/worlds/" + w["id"], json={"expected_revision": 1, "content": w["content"]}
            ).status_code
            == 200
        )
        assert (
            client.put(
                "/api/studio/worlds/" + w["id"], json={"expected_revision": 1, "content": w["content"]}
            ).status_code
            == 409
        )
        second = client.post(
            "/api/studio/worlds/" + w["id"] + "/stories", json={"prompt": "发生另一件新的事情"}
        ).json()
        assert wait_job(client, second["id"])["status"] == "ready"
        data = client.get("/api/studio").json()
        assert len(data["stories"]) == 2
        assert data["stories"][0]["world_revision"] == 1 and data["stories"][1]["world_revision"] == 2
        assert client.get(view_url).json() == before
        export = client.get("/api/studio/stories/" + s["id"] + "/export").json()
        assert export["scope"] == "creator_story" and export["world"]["title"] == "星环小站"
        revised = deepcopy(s["content"])
        revised["title"] = "信号归来"
        edited = client.put(
            "/api/studio/stories/" + s["id"], json={"expected_revision": 1, "content": revised}
        ).json()
        assert wait_job(client, edited["id"])["status"] == "ready"
        assert client.get(view_url).json() == before
        client.cookies.clear()
        session(client)
        assert client.get("/api/studio").json()["worlds"] == []
        assert client.get("/api/studio/jobs/" + job["id"]).status_code == 404
        assert client.post("/api/campaigns", json={"story_id": s["id"]}).status_code == 404
        assert client.get("/api/studio/stories/" + s["id"] + "/export").status_code == 404


def test_cancel_creation_and_recover_job_status(tmp_path, world_blueprint, story_blueprint):
    root = tmp_path / "api"
    with TestClient(create_app(root, CreativeFixture(world_blueprint, story_blueprint, True))) as client:
        session(client)
        j = client.post("/api/studio/worlds", json={"prompt": "生成一个新的小世界"}).json()
        assert client.post("/api/studio/jobs/" + j["id"] + "/cancel").json()["status"] == "cancelled"
        assert client.get("/api/studio").json()["worlds"] == []
    store = Store(root)
    assert store.jobs[j["id"]]["status"] == "cancelled"
    store.close()


def test_full_queue_rejects_edit_without_changing_revision(tmp_path, world_blueprint, story_blueprint):
    gateway = CreativeFixture(world_blueprint, story_blueprint)
    with TestClient(create_app(tmp_path / "api", gateway)) as client:
        session(client)
        first = client.post("/api/studio/worlds", json={"prompt": "星环小站的冒险世界"}).json()
        assert wait_job(client, first["id"])["status"] == "ready"
        story = client.get("/api/studio").json()["stories"][0]
        gateway.block = True
        cancelled = client.post("/api/studio/worlds", json={"prompt": "取消后准备重试的世界"}).json()
        client.post("/api/studio/jobs/" + cancelled["id"] + "/cancel")
        for _ in range(2):
            assert client.post("/api/studio/worlds", json={"prompt": "占据队列的创作任务"}).status_code == 202
        changed = deepcopy(story["content"])
        changed["title"] = "本次不应保存"
        response = client.put("/api/studio/stories/" + story["id"],
                              json={"expected_revision": 1, "content": changed})
        assert response.status_code == 409
        assert client.get("/api/studio").json()["stories"][0] == story
        assert client.post("/api/studio/jobs/" + cancelled["id"] + "/retry").status_code == 409


def test_immediate_creation_retry_keeps_replacement_task(tmp_path, world_blueprint, story_blueprint):
    from roleplay_world.studio import Studio

    async def scenario():
        store = Store(tmp_path / "state")
        gateway = CreativeFixture(world_blueprint, story_blueprint, True)
        studio = Studio(store, gateway, tmp_path / "playtest")
        try:
            job = studio.submit("owner", "world", "一个新世界")
            jid = job["id"]
            await asyncio.sleep(0)
            studio.cancel(jid, "owner")
            gateway.block = False
            studio.retry(jid, "owner")
            replacement = studio.tasks[jid]
            await asyncio.wait_for(replacement, 10)
            assert store.jobs[jid]["status"] == "ready"
            assert len(store.worlds) == 1 and len(store.stories) == 1
        finally:
            await studio.close()
            store.close()

    asyncio.run(scenario())


def test_creation_uncertain_write_requires_recovery(tmp_path, monkeypatch):
    import os

    store = Store(tmp_path / "state")
    job = {"id": "test_job", "owner": "owner", "status": "queued"}
    store.studio_save("jobs", job)
    original = os.fsync

    def fail(fd):
        if fd == store.journal.fd:
            raise OSError("injected creation write uncertainty")
        return original(fd)

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(DomainError, match="待确认"):
        store.studio_save("jobs", {**job, "status": "ready"})
    assert store.jobs[job["id"]]["status"] == "recovery_required"
    store.close()
    monkeypatch.setattr(os, "fsync", original)
    restored = Store(tmp_path / "state")
    assert restored.jobs[job["id"]]["status"] == "ready"
    restored.close()


@pytest.mark.parametrize("key", ["apartment-5c", "emberback", "lantern-barrow"])
def test_community_install_test_gate_idempotency_origin_and_recovery(tmp_path, key):
    from roleplay_world.catalog import load_catalog

    pack = load_catalog()[key]
    gateway = CreativeFixture(WorldBlueprint.model_validate(pack["world"]),
                              StoryBlueprint.model_validate(pack["story"]), True)
    root = tmp_path / key
    with TestClient(create_app(root, gateway)) as client:
        session(client)
        public = next(p for p in client.get("/api/catalog").json() if p["id"] == key)
        assert "world" not in public and "story" not in public
        assert all(c["secret"] not in str(public) for c in pack["world"]["characters"])
        first = client.post(f"/api/studio/catalog/{key}/install")
        assert first.status_code == 202
        job = first.json()
        assert client.post(f"/api/studio/catalog/{key}/install").json()["id"] == job["id"]
        assert len(client.get("/api/studio").json()["worlds"]) == 1
        assert client.post("/api/campaigns", json={"story_id": job["story_id"]}).status_code == 409
        client.post("/api/studio/jobs/" + job["id"] + "/cancel")
        gateway.block = False
        client.post("/api/studio/jobs/" + job["id"] + "/retry")
        result = wait_job(client, job["id"])
        assert result["status"] == "ready", result
        exported = client.get("/api/studio/stories/" + job["story_id"] + "/export").json()
        assert exported["origin"]["source"]["commit"] == pack["source"]["commit"]
        assert "Permission is hereby granted" in exported["origin"]["source"]["license_text"]
        campaign = client.post("/api/campaigns", json={"story_id": job["story_id"]}).json()
        view_url = f"/api/campaigns/{campaign['id']}/branches/{campaign['branch_id']}/view"
        view = client.get(view_url).json()
        assert not any(c["secret"] in str(view) for c in pack["world"]["characters"])
        world_copy = client.get("/api/studio").json()["worlds"][0]
        world_copy["content"]["title"] = "我修改后的世界名称"
        edited = client.put("/api/studio/worlds/" + job["world_id"],
                            json={"expected_revision": 1, "content": world_copy["content"]})
        assert edited.status_code == 200, edited.text
        assert client.post(f"/api/studio/catalog/{key}/install").json()["id"] == job["id"]
        library = client.get("/api/studio").json()
        assert len(library["worlds"]) == 1
        assert library["worlds"][0]["content"]["title"] == "我修改后的世界名称"
        assert library["worlds"][0]["revision"] == 2
        assert library["stories"][0]["world_revision"] == 1
        assert client.get(view_url).json() == view
        saved_library = client.get("/api/studio").json()
        cookies = dict(client.cookies)
        client.cookies.clear()
        session(client)
        assert client.get("/api/studio/stories/" + job["story_id"] + "/export").status_code == 404
    with TestClient(create_app(root, gateway)) as client:
        client.cookies.update(cookies)
        session(client)
        assert client.post(f"/api/studio/catalog/{key}/install").json()["id"] == job["id"]
        assert client.get("/api/studio").json() == saved_library
        assert client.get(view_url).json() == view


def test_community_batch_uncertain_write_recovers_whole_install(tmp_path, monkeypatch):
    import os

    from roleplay_world.catalog import install, load_catalog
    from roleplay_world.studio import Studio

    root = tmp_path / "state"
    store = Store(root)
    studio = Studio(store, None, tmp_path / "runs")
    original = os.fsync

    def fail(fd):
        if fd == store.journal.fd:
            raise OSError("injected install uncertainty")
        return original(fd)

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(DomainError, match="待确认"):
        install(studio, "owner", load_catalog()["emberback"])
    assert not studio.tasks
    store.close()
    monkeypatch.setattr(os, "fsync", original)
    restored = Store(root)
    assert len(restored.worlds) == len(restored.stories) == len(restored.jobs) == 1
    restored_studio = Studio(restored, None, tmp_path / "runs")
    job = install(restored_studio, "owner", load_catalog()["emberback"])
    assert job["status"] == "interrupted" and not restored_studio.tasks
    restored.close()


def test_community_source_snapshots_match_pinned_manifests():
    import hashlib
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "resources/community"
    for source in root.glob("*/SOURCE.json"):
        manifest = json.loads(source.read_text())
        assert len(manifest["sha"]) == 40 and manifest["license"] == "MIT"
        assert "Permission is hereby granted" in (source.parent / "LICENSE").read_text()
        for entry in manifest["files"]:
            raw = (source.parent / entry["path"]).read_bytes()
            assert len(raw) == entry["bytes"] and hashlib.sha256(raw).hexdigest() == entry["sha256"]


def test_failed_creation_retries_from_saved_world(tmp_path, world_blueprint, story_blueprint):
    class InterruptedCreator(CreativeFixture):
        fail = True

        async def generate(self, role, *args, **kwargs):
            if role == "story_builder" and self.fail:
                raise DomainError("model_unavailable", "测试注入：故事服务暂时断开", 503)
            return await super().generate(role, *args, **kwargs)

    gateway = InterruptedCreator(world_blueprint, story_blueprint)
    root = tmp_path / "api"
    with TestClient(create_app(root, gateway)) as client:
        session(client)
        j = client.post("/api/studio/worlds", json={"prompt": "星环小站的新故事"}).json()
        failed = wait_job(client, j["id"])
        assert failed["status"] == "failed"
        wid = failed["world_id"]
        assert wid
        assert len(client.get("/api/studio").json()["worlds"]) == 1
        gateway.fail = False
        assert client.post("/api/studio/jobs/" + j["id"] + "/retry").status_code == 200
        ready = wait_job(client, j["id"])
        assert ready["status"] == "ready", ready
        assert ready["world_id"] == wid and len(client.get("/api/studio").json()["worlds"]) == 1
    restored = Store(root)
    assert restored.jobs[j["id"]]["status"] == "ready"
    assert len(restored.worlds) == 1 and len(restored.stories) == 1
    restored.close()


def test_failed_playtest_cannot_be_started_and_can_recover(tmp_path, world_blueprint, story_blueprint):
    class FailedPlayer(CreativeFixture):
        fail = True

        async def generate(self, role, *args, **kwargs):
            if role == "game_master" and self.fail:
                raise DomainError("model_unavailable", "测试注入：行动模型断开", 503)
            return await super().generate(role, *args, **kwargs)

    gateway = FailedPlayer(world_blueprint, story_blueprint)
    with TestClient(create_app(tmp_path / "api", gateway)) as client:
        session(client)
        j = client.post("/api/studio/worlds", json={"prompt": "星环小站的调查故事"}).json()
        failed = wait_job(client, j["id"])
        assert failed["status"] == "failed"
        sid = failed["story_id"]
        assert client.post("/api/campaigns", json={"story_id": sid}).status_code == 409
        story = client.get("/api/studio").json()["stories"][0]
        assert story["test_report"]["status"] == "failed"
        gateway.fail = False
        client.post("/api/studio/jobs/" + j["id"] + "/retry")
        assert wait_job(client, j["id"])["status"] == "ready"
        assert client.post("/api/campaigns", json={"story_id": sid}).status_code == 201


def test_shutdown_job_can_resume_without_losing_owner(tmp_path, world_blueprint, story_blueprint):
    root = tmp_path / "api"
    with TestClient(create_app(root, CreativeFixture(world_blueprint, story_blueprint, True))) as client:
        session(client)
        j = client.post("/api/studio/worlds", json={"prompt": "星环小站的冒险世界"}).json()
        cookies = dict(client.cookies)
    with TestClient(create_app(root, CreativeFixture(world_blueprint, story_blueprint))) as client:
        client.cookies.update(cookies)
        session(client)
        assert client.get("/api/studio/jobs/" + j["id"]).json()["status"] == "interrupted"
        client.post("/api/studio/jobs/" + j["id"] + "/retry")
        assert wait_job(client, j["id"])["status"] == "ready"


def test_old_quality_run_cannot_certify_new_story_revision(tmp_path, world_blueprint, story_blueprint):
    import threading

    release = threading.Event()

    class BlockingPlayer(CreativeFixture):
        async def generate(self, role, *args, **kwargs):
            if role == "game_master":
                while not release.is_set():
                    await asyncio.sleep(0.01)
            return await super().generate(role, *args, **kwargs)

    gateway = BlockingPlayer(world_blueprint, story_blueprint)
    with TestClient(create_app(tmp_path / "api", gateway)) as client:
        session(client)
        first = client.post("/api/studio/worlds", json={"prompt": "星环小站的冒险世界"}).json()
        for _ in range(300):
            lib = client.get("/api/studio").json()
            if lib["stories"]:
                break
            time.sleep(0.01)
        story = lib["stories"][0]
        changed = deepcopy(story["content"])
        changed["title"] = "不同的新版本"
        second = client.put(
            "/api/studio/stories/" + story["id"], json={"expected_revision": 1, "content": changed}
        ).json()
        release.set()
        assert wait_job(client, first["id"])["status"] == "failed"
        assert wait_job(client, second["id"])["status"] == "ready"
        stored = client.get("/api/studio").json()["stories"][0]
        assert stored["revision"] == 2 and stored["test_report"]["revision"] == 2


def test_explicit_goal_selection_obeys_prerequisites(world_blueprint, story_blueprint):
    from roleplay_world.planning import explicit_goal_plan
    from roleplay_world.world import initial_state

    state = initial_state(compile_story(world_blueprint, story_blueprint, "story_goal"), "玩家")
    state["actor_states"][state["player"]]["location_id"] = "loc_2"
    command = {"mode": "act", "text": "我决定完成「重新校准信号」：根据广播记录把接收器指向正确的方向。"}
    assert explicit_goal_plan(state, command) is None
    state["knowledge"][state["player"]].append("fact_clue_0")
    plan = explicit_goal_plan(state, command)
    assert plan.operations[0].kind == "challenge" and plan.operations[0].target_id == "challenge_1"
    assert plan.check is None
    assert explicit_goal_plan(state, {"mode": "say", "text": command["text"]}) is None
    assert explicit_goal_plan(state, {"mode": "act", "text": "我不想完成「重新校准信号」"}) is None


def test_npc_schema_does_not_allow_invented_knowledge(state):
    from roleplay_world.planning import actor_schema

    schema = actor_schema(state, "npc_captain", False)
    with pytest.raises(ValidationError):
        schema.model_validate({"reaction": "none", "text": "一个秘密", "reveal_fact_ids": ["fact_smuggler_route"]})
    with pytest.raises(ValidationError):
        schema.model_validate({"reaction": "accept", "text": "收下了", "reveal_fact_ids": []})


def test_generated_endings_cannot_omit_a_reachable_nondice_route(world_blueprint, story_blueprint):
    schema = story_generation_schema(world_blueprint)
    data = story_blueprint.model_dump()
    data["challenges"][1]["ending"] = False
    with pytest.raises(ValidationError):
        schema.model_validate(data)
    data["challenges"][1]["ending"] = True
    data["challenges"][1]["skill"] = "agility"
    with pytest.raises(ValidationError):
        schema.model_validate(data)


def test_text_creation_dialogue_and_second_story_without_avatar_dependencies(
    tmp_path, monkeypatch, world_blueprint, story_blueprint
):
    import builtins

    from roleplay_world.config import AppConfig
    original_import = builtins.__import__
    def text_only(name, *args, **kwargs):
        if name.split('.')[0] in {'PIL', 'torch', 'transformers', 'huggingface_hub', 'roleplay_avatar'}:
            raise AssertionError('Text workflow imported an optional image/model dependency: ' + name)
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', text_only)
    app = create_app(config=AppConfig(workspace_root=tmp_path), gateway=CreativeFixture(world_blueprint, story_blueprint))
    with TestClient(app) as client:
        session(client)
        assert client.get('/api/avatars/capabilities').json()['available'] is False
        created = client.post('/api/studio/worlds', json={'prompt': 'Create a text-only orbital station world.'})
        assert created.status_code == 202
        job = wait_job(client, created.json()['id'])
        assert job['status'] == 'ready', job
        world = client.get('/api/studio').json()['worlds'][0]
        assert all(not npc.get('avatar_id') for npc in world['content']['characters'])
        campaign = client.post('/api/campaigns', json={'story_id':job['story_id'], 'player_name':'Visitor'}).json()
        base = f"/api/campaigns/{campaign['id']}/branches/{campaign['branch_id']}"
        response = client.post(base + '/actions', json={'action_id':'text_only_dialogue',
            'expected_world_version':0, 'mode':'say', 'text':'Hello, what is happening here?'})
        assert response.status_code == 202
        from test_api import wait
        action = wait(client, response.json()['id'])
        assert action['status'] == 'committed', action
        assert any(segment['kind'] == 'dialogue' for segment in action['result']['segments'])
        next_story = client.post(f"/api/studio/worlds/{world['id']}/stories", json={'prompt':'Another day at the station.'})
        assert wait_job(client, next_story.json()['id'])['status'] == 'ready'
        assert client.get('/api/avatars').json() == []
