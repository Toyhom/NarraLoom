import asyncio
import json

import httpx
from pydantic import BaseModel, model_validator

from roleplay_world.contracts import TurnPlan
from roleplay_world.gateway import ModelGateway


def test_provider_json_mode_and_private_auth_not_in_traces(tmp_path, monkeypatch):
    monkeypatch.setenv("RPW_TEST_API_KEY", "private-test-key")
    seen=[]

    def respond(request):
        seen.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer private-test-key"
        data={"model":"provider-resolved-model","choices":[{"delta":{"content":'{"intent":"等待"}'}}],
              "usage":{"prompt_tokens":10,"completion_tokens":4}}
        return httpx.Response(200,text="data: "+json.dumps(data)+"\n\ndata: [DONE]\n\n")

    original=httpx.AsyncClient
    monkeypatch.setattr("roleplay_world.gateway.httpx.AsyncClient",
                        lambda **kwargs: original(**kwargs,transport=httpx.MockTransport(respond)))
    gateway=ModelGateway({"default":{"url":"https://model.invalid","model":"flash","json_object":True,
                         "api_key_env":"RPW_TEST_API_KEY","max_tokens":1800}},tmp_path)
    budget={"calls":0,"repairs":0,"traces":[]}
    asyncio.run(gateway.generate("game_master","JSON",{},TurnPlan,"private",budget))
    assert seen[0]['response_format']=={'type':'json_object'} and seen[0]['max_tokens']==1800
    assert budget['traces'][0]['response_model']=='provider-resolved-model'
    assert all('private-test-key' not in p.read_text() for p in tmp_path.glob('*.json'))


def test_structured_repair_receives_concrete_validation_error(tmp_path, monkeypatch):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        plan = {"intent": "交谈", "operations": [{"kind": "say", "target_id": "npc_captain"}]}
        if len(requests) > 1:
            plan["operations"] = []
        raw = json.dumps(plan)
        # Two SSE content blocks exercise incremental decoding.
        chunks = [raw[:20], raw[20:]]
        body = "".join("data: " + json.dumps({"choices": [{"delta": {"content": x}}]}) + "\n\n" for x in chunks)
        return httpx.Response(200, text=body + "data: [DONE]\n\n", headers={"Content-Type": "text/event-stream"})

    original = httpx.AsyncClient
    monkeypatch.setattr("roleplay_world.gateway.httpx.AsyncClient",
                        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)))
    gateway = ModelGateway({"default": {"url": "https://model.invalid/v1", "model": "test"}}, tmp_path)
    budget = {"calls": 0, "repairs": 0, "traces": []}
    result = asyncio.run(gateway.generate("game_master", "test", {}, TurnPlan, "a1", budget))
    assert result.operations == []
    assert budget["calls"] == 2 and budget["repairs"] == 1
    assert "literal_error" in requests[1]["messages"][-1]["content"]


def test_custom_validator_error_is_serialized_and_repaired(tmp_path, monkeypatch):
    class Result(BaseModel):
        value: int

        @model_validator(mode="after")
        def positive(self):
            if self.value < 1:
                raise ValueError("Value must be positive")
            return self

    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        raw = json.dumps({"value": 0 if len(requests) == 1 else 1})
        body = "data: " + json.dumps({"choices": [{"delta": {"content": raw}}]}) + "\n\ndata: [DONE]\n\n"
        return httpx.Response(200, text=body)

    original = httpx.AsyncClient
    monkeypatch.setattr("roleplay_world.gateway.httpx.AsyncClient",
                        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)))
    gateway = ModelGateway({"default": {"url": "https://model.invalid", "model": "test"}}, tmp_path)
    budget = {"calls": 0, "repairs": 0, "traces": []}
    result = asyncio.run(gateway.generate("content_reviewer", "test", {}, Result, "validator", budget))
    assert result.value == 1 and budget["calls"] == 2 and budget["repairs"] == 1
    assert "Value must be positive" in requests[1]["messages"][-1]["content"]


def test_research_trace_keeps_prompt_and_schema_private(tmp_path):
    from roleplay_world.engines import Engine, EngineRegistry
    async def invoke(config, payload, headers):
        return {'model':'actual','text':'{"intent":"Wait"}'}
    registry = EngineRegistry(); registry.register(Engine('fixture',frozenset({'generate'}),invoke))
    gateway = ModelGateway({'default':{'url':'http://local.invalid/v1','model':'fixture','backend':'fixture'}},tmp_path,registry=registry)
    budget = {'calls':0,'repairs':0,'traces':[]}
    asyncio.run(gateway.generate('game_master','PRIVATE SYSTEM',{'secret':'PRIVATE CONTEXT'},TurnPlan,'trace',budget))
    raw = json.loads(next(tmp_path.glob('*.json')).read_text())
    assert raw['system_prompt']=='PRIVATE SYSTEM' and raw['output_schema']==TurnPlan.model_json_schema()
    assert 'PRIVATE' not in json.dumps(budget['traces'])
    assert 'output_schema' not in budget['traces'][0]
