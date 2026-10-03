import asyncio
import time

from fastapi.testclient import TestClient

from roleplay_world.app import create_app
from roleplay_world.contracts import ActorReply, Narration, TurnPlan


class FakeGateway:
    def __init__(self, block=False):
        self.block = block
        self.contexts = []

    async def health(self):
        return {"ready": True, "mode": "test_fixture"}

    async def generate(self, role, system, data, schema, aid, budget, validate=None):
        self.contexts.append((role, data))
        if self.block:
            await asyncio.sleep(30)
        if role == "game_master":
            return TurnPlan(intent="赠送工具", operations=[{"kind": "give", "target_id": "npc_captain", "item_id": "item_tools"}], speakers=["npc_captain"])
        if role == "character_actor":
            return ActorReply(text="谢谢，我收下工具。", reaction="accept")
        return Narration(text="船长接过了你的工具。", suggestions=["我去酒馆"])


def setup(client):
    csrf = client.post("/api/session").json()["csrf_token"]
    client.headers["X-CSRF-Token"] = csrf
    c = client.post("/api/campaigns", json={"player_name": "测试旅人"}).json()
    return c, f'/api/campaigns/{c["id"]}/branches/{c["branch_id"]}'


def wait(client, aid):
    for _ in range(100):
        a = client.get(f"/api/actions/{aid}").json()
        if a["status"] in {"committed", "failed", "cancelled", "interrupted"}:
            return a
        time.sleep(.02)
    raise AssertionError("Action did not finish")


def test_full_pipeline_and_http_ownership(tmp_path):
    gateway = FakeGateway()
    app = create_app(tmp_path / "api", gateway)
    with TestClient(app) as client:
        c, base = setup(client)
        command = {"action_id": "action_api", "expected_world_version": 0, "text": "交出工具"}
        assert client.post(base + "/actions", json=command).status_code == 202
        result = wait(client, "action_api")
        assert result["status"] == "committed", result
        assert client.post(base + "/actions", json=command).json()["result"]["id"] == result["result"]["id"]
        view = client.get(base + "/view").json()
        assert view["world_version"] == 1 and view["inventory"] == []
        assert "warehouse_to_ridge" not in client.get(base + "/export").text
        assert "seed" not in client.get("/api/actions/action_api").text
        npc = next(ctx for role, ctx in gateway.contexts if role == "character_actor")
        assert not any(f["id"] == "fact_smuggler_route" for f in npc["view"]["known_facts"])
        assert client.post("/api/actions/action_api/cancel").json()["error"] == "already_committed"
        fork = client.post(f'/api/campaigns/{c["id"]}/branches', json={"source_branch_id": c["branch_id"], "world_version": 0}).json()
        branch_view = client.get(f'/api/campaigns/{c["id"]}/branches/{fork["id"]}/view').json()
        assert len(branch_view["inventory"]) == 1 and branch_view["history"] == []
        assert client.post(base + "/actions", json={**command, "action_id": "stale"}).status_code == 409
        client.cookies.clear()
        setup(client)
        assert client.get(base + "/view").status_code == 404
        assert client.get("/api/actions/action_api").status_code == 404


def test_cancel_inflight_does_not_commit(tmp_path):
    app = create_app(tmp_path / "api", FakeGateway(block=True))
    with TestClient(app) as client:
        _, base = setup(client)
        r = client.post(base + "/actions", json={"action_id": "cancel_me", "expected_world_version": 0, "text": "交出工具"})
        assert r.status_code == 202
        assert client.post("/api/actions/cancel_me/cancel").json()["status"] == "cancelled"
        time.sleep(.05)
        view = client.get(base + "/view").json()
        assert view["world_version"] == 0 and len(view["inventory"]) == 1


def test_csrf_and_input_bounds(tmp_path):
    with TestClient(create_app(tmp_path / "api", FakeGateway())) as client:
        assert client.post("/api/campaigns", json={}).status_code == 403
        _, base = setup(client)
        assert client.post("/api/campaigns", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.post(base + "/actions", json={"action_id": "xx", "expected_world_version": 0, "text": "x" * 1801}).status_code == 422
        assert client.post("/api/campaigns", content="x" * 25000).status_code == 413


def test_pure_dialogue_keeps_one_character_voice(tmp_path):
    class ChatGateway(FakeGateway):
        async def generate(self, role, system, data, schema, aid, budget, validate=None):
            if role == "game_master":
                return TurnPlan(intent="交谈", time_cost_s=30, speakers=["npc_captain"])
            if role == "character_actor":
                return ActorReply(text="船需要修好，我正在想办法。")
            raise AssertionError("Pure dialogue must not invent a second NPC answer")

    with TestClient(create_app(tmp_path / "api", ChatGateway())) as client:
        _, base = setup(client)
        client.post(base + "/actions", json={"action_id": "chat_only", "expected_world_version": 0,
                                             "mode": "say", "text": "船长你好"})
        action = wait(client, "chat_only")
        assert action["status"] == "committed"
        assert action["result"]["segments"] == [{"kind": "dialogue", "speaker_id": "npc_captain",
                                                 "speaker_name": "岚船长", "text": "船需要修好，我正在想办法。",
                                                 "emotion": "neutral", "gesture": "none"}]
        assert action["result"]["effects"] == []
        assert len(client.get(base + "/view").json()["inventory"]) == 1


def test_memory_notes_projection_can_be_resubmitted_and_is_owned(tmp_path):
    gateway = FakeGateway(block=True)
    with TestClient(create_app(tmp_path / 'notes', gateway)) as client:
        _, base = setup(client)
        command = {'action_id':'memo_first','expected_world_version':0,'mode':'ooc','text':'记录',
                   'note_record':{'id':'note_1','text':'蓝铃守约','kind':'commitment'}}
        assert client.post(base+'/actions',json=command).status_code == 202
        assert wait(client,'memo_first')['status'] == 'committed'
        found = client.get(base+'/memories',params={'q':'蓝铃'}).json()['records']
        assert found[0]['kind'] == 'commitment'
        note = client.get(base+'/view').json()['notes'][0]
        note['status'] = 'done'
        command.update(action_id='memo_second',expected_world_version=1,note_record=note)
        assert client.post(base+'/actions',json=command).status_code == 202
        assert wait(client,'memo_second')['status'] == 'committed'
        assert not gateway.contexts
        assert client.get(base+'/memories',params={'q':'x'*241}).status_code == 422
        client.cookies.clear();setup(client)
        assert client.get(base+'/memories').status_code == 404


def test_clock_only_dialogue_does_not_invent_second_response(tmp_path):
    class DialogueGateway(FakeGateway):
        async def generate(self, role, system, data, schema, aid, budget, validate=None):
            self.contexts.append((role, data))
            if role == 'game_master':
                return TurnPlan(intent='询问约定',time_cost_s=600,operations=[],speakers=['npc_captain'])
            if role == 'character_actor':
                return ActorReply(text='我们的暗号是青瓷风铃。',reaction='none')
            raise AssertionError('A passive clock tick must not trigger a second conversational response')
    gateway=DialogueGateway()
    app=create_app(tmp_path/'dialogue',gateway)
    with TestClient(app) as client:
        campaign,base=setup(client)
        state=app.state.store.branches[campaign['branch_id']]['state']
        # Use authored clock values from the fogharbor template, crossing a partial tick only.
        interval=min(c['interval_s'] for c in state['clocks'].values() if c['kind']=='time')
        class TickGateway(DialogueGateway):
            async def generate(self, role, system, data, schema, aid, budget, validate=None):
                if role=='game_master':
                    return TurnPlan(intent='询问约定',time_cost_s=interval,operations=[],speakers=['npc_captain'])
                return await super().generate(role,system,data,schema,aid,budget,validate)
        app.state.runtime.gateway=TickGateway()
        client.post(base+'/actions',json={'action_id':'clock_dialogue','expected_world_version':0,'mode':'say','text':'之前的暗号是什么？'})
        action=wait(client,'clock_dialogue')
        assert action['status']=='committed',action
        assert [s['kind'] for s in action['result']['segments']]==['dialogue']
        assert '青瓷风铃' in action['result']['segments'][0]['text']
