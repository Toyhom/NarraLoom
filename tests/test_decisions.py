import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from pydantic import ValidationError

from roleplay_world.contracts import DomainError
from roleplay_world.decisions import DecisionQuestion, DecisionRequest, validate_response
from roleplay_world.engines import Engine, EngineRegistry, systemone_decide
from roleplay_world.gateway import ModelGateway
from roleplay_world.routing import move_request, route_action
from roleplay_world.settings import MODEL_OWNER, ProviderSettings, Settings


def budget():
    return {'calls': 0, 'repairs': 0, 'traces': [], 'max_calls': 6}


def response(request, select=None, p=0.98):
    choices = list(request.questions['route'].criteria)
    selected = select or choices[0]
    return {'model': 'actual-decision-model', 'answers': {'route': {
        'type': 'choice', 'choice': selected, 'confidence': 0.7,
        'probabilities': {key: p if key == selected else (1-p)/(len(choices)-1) for key in choices}}},
        'usage': {'input_tokens': 40, 'output_tokens': 0}}


def config(mode='auto'):
    return {'default': {'url': 'https://main.invalid/v1', 'model': 'main', 'api_key': 'main-secret'},
            'providers': {'local': {'url': 'http://127.0.0.1:8010/v1', 'backend': 'systemone'}},
            'bindings': {'action_router': {'provider': 'local', 'model': 'jev', 'revision': 'pinned-revision'}},
            'decision_policy': {'mode': mode}}


def gateway(tmp_path, invoke, mode='auto'):
    registry = EngineRegistry()
    registry.register(Engine('systemone', frozenset({'decide'}), invoke))
    return ModelGateway(config(mode), tmp_path/'traces', registry=registry)


def test_response_contract_all_types_and_raw_confidence():
    request = DecisionRequest(state='visible state', questions={
        'route': DecisionQuestion(type='choice', instructions='Pick', criteria={'a': 'A', 'b': 'B'}),
        'yes': DecisionQuestion(type='noul', instructions='True?'),
        'risk': DecisionQuestion(type='score', instructions='Risk?', criteria=['low', 'medium', 'high'])})
    raw = {'model': 'actual', 'answers': {
        'route': {'type': 'choice', 'choice': 'a', 'confidence': 0.6, 'probabilities': {'a': 0.8, 'b': 0.2}},
        'yes': {'type': 'noul', 'noul': 0.7},
        'risk': {'type': 'score', 'score': 1.1, 'legend': {'0': 'low', '1': 'medium', '2': 'high'},
                 'probabilities': {'0': 0.1, '1': 0.7, '2': 0.2}}}}
    answer = validate_response(request, raw)['answers']
    assert answer['route']['confidence'] == 0.6 and answer['route']['p_max'] == 0.8
    assert answer['yes']['probabilities']['no'] == pytest.approx(0.3)
    assert answer['risk']['score'] == 1.1
    mutations = [lambda r: r['answers'].pop('yes'),
                 lambda r: r['answers']['route'].update(choice='b'),
                 lambda r: r['answers']['route'].update(probabilities={'a': 0.8, 'b': 0.3}),
                 lambda r: r['answers']['route'].update(probabilities={'a': float('nan'), 'b': 0.2}),
                 lambda r: r['answers']['route'].update(probabilities={'a': 0.8, 'c': 0.2}),
                 lambda r: r['answers']['risk'].update(score=2),
                 lambda r: r['answers']['yes'].update(noul=True),
                 lambda r: r['answers']['risk'].update(legend={'0': 'high', '1': 'medium', '2': 'low'}),
                 lambda r: r.update(usage={'input_tokens': -1})]
    for mutate in mutations:
        bad = deepcopy(raw); mutate(bad)
        with pytest.raises(ValueError): validate_response(request, bad)
    for criteria in ({'only': 'one'}, ['a', 'b'], {'a': '', 'b': 'b'}):
        with pytest.raises(ValidationError): DecisionQuestion(type='choice', instructions='pick', criteria=criteria)
    with pytest.raises(ValueError): DecisionRequest(state={'bad': float('nan')}, questions=request.questions)


def test_named_endpoints_do_not_inherit_credentials_and_old_configs_work(tmp_path):
    settings = Settings(tmp_path/'settings', config())
    payload = ProviderSettings(url='https://default.invalid/v1', model='main', api_key='top-secret',
        providers={'local': {'url': 'http://127.0.0.1:8010/v1', 'backend': 'systemone', 'api_key': 'local-secret'},
                   'creative': {'url': 'https://creative.invalid/v1', 'backend': 'openai'}},
        bindings={'action_router': {'provider': 'local', 'model': 'jev'},
                  'narrator': {'provider': 'creative', 'model': 'poet'}}, decision_policy={'mode': 'shadow'})
    public = settings.save('one', payload)
    assert 'secret' not in json.dumps(public)
    token = MODEL_OWNER.set('one')
    try:
        gw = ModelGateway({}, tmp_path/'traces', settings)
        assert gw.auth_headers(gw.role_config('narrator')) == {}
        assert gw.auth_headers(gw.role_config('action_router')) == {'Authorization': 'Bearer local-secret'}
        assert gw.auth_headers(gw.role_config('game_master')) == {'Authorization': 'Bearer top-secret'}
        payload.providers['local'].api_key = ''
        settings.save('one', payload)
        assert gw.auth_headers(gw.role_config('action_router'))
        payload.providers['local'].url = 'http://127.0.0.1:8011/v1'
        settings.save('one', payload)
        assert gw.auth_headers(gw.role_config('action_router')) == {}
    finally:
        MODEL_OWNER.reset(token)
    # Legacy per-role endpoints also cannot leak the deployment key.
    gw = ModelGateway({'default': config()['default'], 'roles': {'narrator': {'url': 'http://localhost:8020/v1'}}}, tmp_path/'old')
    assert gw.auth_headers(gw.role_config('narrator')) == {}
    assert gw.role_config('game_master')['model'] == 'main'
    for override in ({'bindings': {'narrator': {'provider': 'local', 'model': 'jev'}}},
                     {'bindings': {'action_router': {'provider': 'missing', 'model': 'jev'}}}):
        with pytest.raises(ValidationError): ProviderSettings.model_validate({**payload.model_dump(), **override})


def test_router_commits_only_validated_move_without_secret_context(state, tmp_path):
    calls = []
    async def invoke(cfg, payload, headers):
        assert headers == {}  # no main provider key
        calls.append(payload)
        assert set(payload['state']) == {'player_input', 'exits'}
        return response(DecisionRequest.model_validate({k: v for k, v in payload.items() if k != 'model'}))
    gw = gateway(tmp_path, invoke)
    command = {'mode': 'act', 'text': 'I go to the lighthouse.'}
    before = deepcopy(state); b = budget()
    plan = asyncio.run(route_action(gw, state, command, 'route_one', b))
    assert plan.operations[0].kind == 'move' and plan.check is None
    assert state == before and b['calls'] == 1 and b['max_calls'] == 7
    assert b['traces'][0]['response_model'] == 'actual-decision-model'
    assert b['traces'][0]['routing']['outcome'] == 'accepted'
    assert 'context' not in b['traces'][0]
    assert len(calls) == 1


@pytest.mark.parametrize('mode,p,selected,reason', [
    ('off', 0.99, None, None), ('shadow', 0.99, None, 'shadow'),
    ('auto', 0.55, None, 'uncertain'), ('auto', 0.99, 'defer', 'deferred')])
def test_routing_abstention_and_shadow(state, tmp_path, mode, p, selected, reason):
    async def invoke(cfg, payload, headers):
        return response(DecisionRequest.model_validate({k: v for k, v in payload.items() if k != 'model'}), selected, p)
    b = budget()
    assert asyncio.run(route_action(gateway(tmp_path, invoke, mode), state,
                                   {'mode': 'act', 'text': 'Maybe leave?'}, 'abstain', b)) is None
    if reason: assert b['traces'][0]['routing']['outcome'] == reason
    else: assert b['calls'] == 0


def test_protocol_failure_fallback_consumes_call_and_cancellation_propagates(state, tmp_path):
    async def invalid(*args): return {'answers': {}}
    gw = gateway(tmp_path, invalid); b = budget()
    assert asyncio.run(route_action(gw, state, {'mode': 'act', 'text': 'Go.'}, 'bad', b)) is None
    assert b['calls'] == 1 and b['traces'][0]['routing']['reason'] == 'invalid_decision_output'
    assert b['traces'][0]['status'] == 'failed'
    async def cancelled(*args): raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(route_action(gateway(tmp_path, cancelled), state, {'mode': 'act', 'text': 'Go.'}, 'cancel', budget()))


def test_systemone_http_payload_and_bounded_response(monkeypatch):
    original = httpx.AsyncClient
    def handle(request):
        assert str(request.url) == 'http://localhost:8765/v1/systemone'
        assert request.headers['authorization'] == 'Bearer only-this-provider'
        assert json.loads(request.content)['state'] == 'test'
        return httpx.Response(200, json={'model': 'jev', 'answers': {}})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    result = asyncio.run(systemone_decide({'url': 'http://localhost:8765/v1'}, {'state': 'test'},
                                        {'Authorization': 'Bearer only-this-provider'}))
    assert result['model'] == 'jev'


def test_registry_rejects_capability_mismatch_before_call(tmp_path):
    async def never(*args): raise AssertionError('should not call')
    registry = EngineRegistry(); engine = Engine('special', frozenset({'decide'}), never)
    registry.register(engine)
    with pytest.raises(ValueError): registry.register(engine)
    with pytest.raises(DomainError): registry.require('special', 'generate')
    gw = ModelGateway({'default': {'backend': 'special', 'url': 'http://localhost/v1', 'model': 'jev'}}, tmp_path, registry=registry)
    with pytest.raises(DomainError): asyncio.run(gw.generate('narrator', '', {}, DecisionRequest, 'capability', budget()))


def test_move_prompt_handles_order_without_world_truth():
    exits = [{'id': 'north', 'name': '门'}, {'id': 'south', 'name': '门'}]
    request = move_request('If the guard agrees, leave.', exits)
    assert list(request.questions['route'].criteria) == ['move_0', 'move_1', 'defer']
    assert 'conditions' in request.questions['route'].instructions


def test_routed_runtime_idempotency_replay_and_decision_endpoint_ownership(tmp_path, template):
    from fastapi.testclient import TestClient

    from roleplay_world.app import create_app
    from roleplay_world.contracts import ActionCommand
    from roleplay_world.journal import digest
    from roleplay_world.runtime import Runtime
    from roleplay_world.store import Store

    calls = []
    async def decide(cfg, payload, headers):
        calls.append('decision')
        return response(DecisionRequest.model_validate({k: v for k, v in payload.items() if k != 'model'}))
    async def generate(cfg, payload, headers):
        calls.append('generation')
        assert '只' in payload['messages'][0]['content']  # narrator receives the usual schema contract
        return {'model': 'narrator', 'text': '{"text":"You arrive at the next location.","suggestions":[]}', 'usage': None}
    gw = gateway(tmp_path, decide)
    gw.registry.register(Engine('openai', frozenset({'generate'}), generate))
    folder = tmp_path/'store'; store = Store(folder)
    campaign = store.create_campaign('owner', template, 'Traveler'); bid = campaign['main_branch']
    cmd = ActionCommand(action_id='routed', expected_world_version=0, text='I walk to the next exit.')
    store.accept(campaign['id'], bid, 'owner', cmd)
    asyncio.run(Runtime(store, gw).run('routed'))
    assert store.actions['routed']['status'] == 'committed', store.actions['routed']
    assert calls == ['decision', 'generation']
    assert store.actions['routed']['traces'][0]['routing']['outcome'] == 'accepted'
    expected = digest(store.branches[bid]['state']); store.close()
    restored = Store(folder)
    assert digest(restored.branches[bid]['state']) == expected
    assert restored.accept(campaign['id'], bid, 'owner', cmd)[1] is False
    assert calls == ['decision', 'generation']; restored.close()
    with TestClient(create_app(tmp_path/'api')) as client:
        assert client.get('/api/engines').status_code == 401
        client.headers['X-CSRF-Token'] = client.post('/api/session').json()['csrf_token']
        modules = client.get('/api/engines').json()['modules']
        assert len(modules) == 13
        embedding = next(module for module in modules if module['id'] == 'memory_embedding')
        assert embedding['capability'] == 'embed' and not embedding['configured']
        main = next(m for m in modules if m['id'] == 'game_master')
        assert main['backend'] == 'openai' and main['provider'] == 'default'
        assert client.post('/api/decisions/not_a_module', json=move_request('Go', [{'id': 'one', 'name': 'One'}]).model_dump()).status_code == 404
        cfg = ProviderSettings(url='http://default.invalid/v1', model='main',
            providers={'local': {'url': 'http://localhost:8010/v1', 'backend': 'systemone'}},
            bindings={'action_router': {'provider': 'local', 'model': 'jev'}})
        assert client.put('/api/settings/provider', json=cfg.model_dump()).status_code == 200
        assert next(m for m in client.get('/api/engines').json()['modules'] if m['id'] == 'action_router')['configured']
        client.cookies.clear(); client.headers['X-CSRF-Token'] = client.post('/api/session').json()['csrf_token']
        assert not next(m for m in client.get('/api/engines').json()['modules'] if m['id'] == 'action_router')['configured']


def test_usage_keeps_providers_separate_and_does_not_price_local_as_default(tmp_path):
    settings = Settings(tmp_path, {})
    settings.save('owner', ProviderSettings(url='http://default.invalid/v1', model='same', input_price=10))
    for provider in ('default', 'local'):
        settings.record_usage('owner', {'role': 'action_router', 'provider': provider, 'model': 'same',
                                      'duration_s': 1, 'usage': {'input_tokens': 100, 'output_tokens': 0}})
    report = settings.report('owner')
    assert len(report['models']) == 2 and report['estimate'] == 0.001
    assert report['unpriced_provider_calls'] == 1


def test_headless_api_has_no_frontend_dependency(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from roleplay_world.app import create_app
    monkeypatch.setenv('RPW_HEADLESS', '1')
    with TestClient(create_app(tmp_path/'headless')) as client:
        assert client.get('/').json()['mode'] == 'headless'
        assert client.get('/openapi.json').json()['info']['title'] == 'NarraLoom'
        assert client.get('/assets/nonexistent.js').status_code == 404


def test_retry_keeps_original_decision_and_does_not_repeat_it(tmp_path, template):
    from roleplay_world.contracts import ActionCommand
    from roleplay_world.runtime import Runtime
    from roleplay_world.store import Store
    calls = []
    async def decide(cfg, payload, headers):
        calls.append('decision')
        return response(DecisionRequest.model_validate({k:v for k,v in payload.items() if k != 'model'}))
    async def generate(cfg, payload, headers):
        calls.append('generation')
        if calls.count('generation') == 1:
            raise httpx.ConnectError('unavailable fixture')
        return {'model':'actual', 'text':'{"text":"You arrive.","suggestions":[]}'}
    gw = gateway(tmp_path, decide)
    gw.registry.register(Engine('openai', frozenset({'generate'}), generate))
    store = Store(tmp_path/'store'); campaign = store.create_campaign('owner', template, 'Traveler')
    store.accept(campaign['id'], campaign['main_branch'], 'owner', ActionCommand(action_id='retry', expected_world_version=0, text='Go.'))
    runtime = Runtime(store, gw)
    asyncio.run(runtime.run('retry'))
    assert store.actions['retry']['status'] == 'failed'
    assert store.branches[campaign['main_branch']]['state']['version'] == 0
    async def retry():
        runtime.retry('retry', 'owner')
        await runtime.tasks['retry']
    asyncio.run(retry())
    assert store.actions['retry']['status'] == 'committed'
    assert calls == ['decision','generation','generation']
    assert [t['role'] for t in store.actions['retry']['traces']] == ['action_router','narrator','narrator']
    store.close()


def test_http_decision_budget_allows_document_context_without_changing_action_limit(tmp_path):
    from fastapi.testclient import TestClient

    from roleplay_world import __version__
    from roleplay_world.app import create_app

    with TestClient(create_app(tmp_path/'decision-budget')) as client:
        client.headers['X-CSRF-Token'] = client.post('/api/session').json()['csrf_token']
        payload = {'state':'A'*30000,'questions':{'supported':{'type':'noul','instructions':'Does the input contain B?'}}}
        result = client.post('/api/decisions/action_router',json=payload)
        assert result.status_code == 503 and result.json()['error'] == 'decision_unconfigured'
        assert client.post('/api/campaigns',content='A'*30000).status_code == 413
        assert client.get('/healthz').json()['version'] == client.get('/openapi.json').json()['info']['version'] == __version__
