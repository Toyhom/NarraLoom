import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from roleplay_world.app import create_app
from roleplay_world.config import AppConfig
from roleplay_world.contracts import ActionCommand, DomainError
from roleplay_world.embeddings import validate_embeddings
from roleplay_world.engines import Engine, builtin_engines, openai_embed
from roleplay_world.gateway import ModelGateway
from roleplay_world.journal import digest
from roleplay_world.memory import context_memories, retrieve
from roleplay_world.runtime import Runtime
from roleplay_world.semantic_memory import recalled_context
from roleplay_world.settings import MODEL_OWNER, ProviderSettings
from roleplay_world.store import Store
from roleplay_world.world import apply_events, initial_state


def record(eid, audience, text):
    return {'event_id': eid, 'type': 'memory.recorded', 'visibility': {'kind': 'actors', 'actor_ids': audience}, 'payload': {
        'audience': audience, 'text': text, 'category': 'utterance', 'source_event_ids': [eid + '_speech']}}


def seed(template):
    state = initial_state(template, 'Visitor')
    pc = state['player']
    state = apply_events(state, [record('old_promise', [pc, 'npc_captain'], '明天把陶笛送回蓝铃塔。'),
                                 record('hidden', ['npc_captain'], 'SECRET-ORCHID is the private password.')], 1)
    for i in range(120):
        state = apply_events(state, [record(f'weather_{i}', [pc, 'npc_captain'], f'天气记录 {i}')], i + 2)
    return state


class EmbeddingFixture:
    def __init__(self):
        self.calls = []
        self.response_model = 'fixture-v1'

    async def __call__(self, config, payload, headers):
        self.calls.append(deepcopy(payload))
        vectors = [[1., 0., 0.] if any(word in text for word in ('陶笛', 'instrument', '楽器')) else [0., 1., 0.]
                   for text in payload['input']]
        return {'model': self.response_model, 'vectors': vectors, 'usage': {'prompt_tokens': len(vectors)}}


def gateway(folder, callback=None, **policy):
    callback = callback or EmbeddingFixture()
    registry = builtin_engines()
    registry.register(Engine('fixture_vectors', frozenset({'embed'}), callback))
    config = {'providers': {'vectors': {'backend': 'fixture_vectors'}},
              'bindings': {'memory_embedding': {'provider': 'vectors', 'model': 'fixture-v1', 'revision': 'one'}},
              'memory_policy': {'mode': 'hybrid', **policy}}
    return ModelGateway(config, folder, registry=registry), callback


def budget():
    return {'calls': 0, 'traces': []}


@pytest.mark.parametrize('vectors', [[], [[]], [[0., 0.]], [[float('nan')]], [[float('inf')]],
                                    [[True]], [['0.5']], [[1.], [1., 2.]], [[1.], [2.]]])
def test_reject_invalid_embedding_results(vectors):
    with pytest.raises(ValueError):
        validate_embeddings({'model': 'fixture', 'vectors': vectors}, 1)


def test_openai_indices_and_normalization(monkeypatch):
    raw = {'model': 'actual', 'data': [{'index': 1, 'embedding': [0., 4.]}, {'index': 0, 'embedding': [3., 0.]}]}
    def respond(request):
        assert request.url.path == '/v1/embeddings'
        assert json.loads(request.content)['encoding_format'] == 'float'
        assert request.headers['Authorization'] == 'Bearer fixture-only'
        return httpx.Response(200, json=raw)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    async def run():
        result = await openai_embed({'url': 'http://localhost/v1'}, {'input': ['one', 'two'], 'encoding_format': 'float'},
                                   {'Authorization': 'Bearer fixture-only'})
        assert validate_embeddings(result, 2)['vectors'] == [[1., 0.], [0., 1.]]
        raw['data'][1]['index'] = 1
        with pytest.raises(ValueError):
            await openai_embed({'url': 'http://localhost/v1'}, {'input': ['one', 'two'], 'encoding_format': 'float'},
                               {'Authorization': 'Bearer fixture-only'})
    asyncio.run(run())


def test_paraphrase_recall_cache_sources_and_lexical_default(tmp_path, template):
    state = seed(template)
    before = digest(state)
    gw, embed = gateway(tmp_path)
    async def run():
        query = 'Where should the borrowed instrument be taken?'
        assert not retrieve(state, state['player'], query)
        b = budget()
        found = await gw.memory.recall(state, state['player'], query, 'first', b, limit=1)
        assert found[0]['source_id'] == 'old_promise'
        assert found[0]['source_event_ids'] == ['old_promise_speech']
        assert found[0]['certainty'] == 'said_or_observed'
        assert b['calls'] == 0  # Auxiliary calls leave the narrative budget intact.
        assert all('SECRET-ORCHID' not in str(call) for call in embed.calls)
        count = len(embed.calls)
        assert found == await gw.memory.recall(state, state['player'], query, 'cached', budget(), limit=1)
        assert len(embed.calls) == count
        assert 'old_promise' not in json.dumps(b['traces']) and query not in json.dumps(b['traces'])
        gw.config['memory_policy']['mode'] = 'lexical'
        assert await recalled_context(gw, state, state['player'], query, 'off', budget()) == context_memories(state, state['player'], query)
        assert len(embed.calls) == count and digest(state) == before
    asyncio.run(run())


def test_actor_belief_branch_and_cache_owner_isolation(tmp_path, template):
    state = seed(template)
    gw, embed = gateway(tmp_path)
    pc = state['player']
    state['facts'][state['knowledge'][pc][0]]['value'] = 'GM-ONLY-TRUTH'
    async def run():
        await gw.memory.recall(state, pc, 'instrument', 'pc', budget())
        assert 'GM-ONLY-TRUTH' not in str(embed.calls) and 'SECRET-ORCHID' not in str(embed.calls)
        early = initial_state(template, 'Visitor')
        found = await gw.memory.recall(early, pc, 'instrument', 'fork', budget())
        assert 'old_promise' not in {row['source_id'] for row in found}
        before = len(embed.calls)
        await gw.memory.recall(state, 'npc_captain', 'instrument', 'npc', budget())
        assert 'SECRET-ORCHID' in str(embed.calls[before:])
        before = len(embed.calls)
        token = MODEL_OWNER.set('different_owner')
        try:
            await gw.memory.recall(state, pc, 'instrument', 'other_owner', budget())
        finally:
            MODEL_OWNER.reset(token)
        assert len(embed.calls) > before
        before = len(embed.calls)
        gw.config['bindings']['memory_embedding']['revision'] = 'two'
        await gw.memory.recall(state, pc, 'instrument', 'new_revision', budget())
        assert len(embed.calls) > before
    asyncio.run(run())


def test_cache_hits_are_scoped_to_actor_and_explicit_branch(tmp_path, template):
    gw, embed = gateway(tmp_path)
    state = seed(template)
    async def run():
        for actor, branch in ((state['player'], 'main'), ('npc_captain', 'main'), (state['player'], 'sibling')):
            b = budget()
            before = len(embed.calls)
            await gw.memory.recall(state, actor, 'instrument', 'scoped', b, scope=branch)
            assert len(embed.calls) > before and b['traces'][-1]['retrieval']['cache_hits'] == 0
        before = len(embed.calls)
        await gw.memory.recall(state, state['player'], 'instrument', 'warm', budget(), scope='main')
        assert len(embed.calls) == before
    asyncio.run(run())


def test_failed_partial_index_and_model_revision_change_are_reported(tmp_path, template):
    state = seed(template)
    gw, embed = gateway(tmp_path, max_calls=1)
    async def run():
        b = budget()
        await gw.memory.recall(state, state['player'], 'instrument', 'bounded', b)
        assert not embed.calls and b['traces'][-1]['error'] == 'embedding_budget'
        gw.config['memory_policy'].update(max_calls=12, failure='error')
        await gw.memory.recall(state, state['player'], 'instrument', 'fill', budget())
        embed.response_model = 'changed-unpinned-model'
        with pytest.raises(DomainError) as error:
            await gw.memory.recall(state, state['player'], 'a new query', 'changed', budget())
        assert error.value.code == 'embedding_revision_changed' and not gw.memory.cache
        gw.config['memory_policy'].update(max_chunks=2, failure='lexical')
        b = budget()
        assert await gw.memory.recall(state, state['player'], '陶笛', 'limit', b) == retrieve(state, state['player'], '陶笛', 8, 4800)
        assert b['traces'][-1]['error'] == 'memory_corpus_limit'
    asyncio.run(run())


def test_invalid_vectors_fallback_and_cancellation_propagate(tmp_path, template):
    state = seed(template)
    async def invalid(*args):
        return {'model': 'broken', 'vectors': [[0.]]}
    gw, _ = gateway(tmp_path / 'invalid', invalid)
    async def run():
        b = budget()
        assert await gw.memory.recall(state, state['player'], '陶笛', 'bad', b) == retrieve(state, state['player'], '陶笛', 8, 4800)
        assert b['traces'][-1]['error'] == 'invalid_embedding_output'
        entered = asyncio.Event()
        async def wait(*args):
            entered.set()
            await asyncio.Event().wait()
        cancellable, _ = gateway(tmp_path / 'cancel', wait)
        b = budget()
        pending = asyncio.create_task(cancellable.memory.recall(state, state['player'], 'instrument', 'cancel', b))
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert b['traces'][-1]['status'] == 'cancelled'
        assert b['traces'][0]['status'] == 'cancelled'
        assert not cancellable.memory.cache
    asyncio.run(run())


def test_long_record_chunks_context_batching_and_cache_bounds(tmp_path, template):
    state = initial_state(template, 'Visitor')
    state = apply_events(state, [record('long_record', [state['player']], '前言。' * 600 + '陶笛存在柜子里。')], 1)
    gw, embed = gateway(tmp_path)
    gw.config['providers']['vectors']['context_chars'] = 1000
    async def run():
        found = await gw.memory.recall(state, state['player'], 'instrument', 'chunks', budget(), limit=1, char_budget=900)
        assert found[0]['source_id'] == 'long_record' and '陶笛' in found[0]['text']
        assert len(found[0]['text']) <= 900
        assert len(embed.calls) > 1
        assert all(len(json.dumps(call, ensure_ascii=False)) <= 1000 for call in embed.calls)
        for index in range(2100):
            gw.memory.put(('test', str(index)), [1.] * 1024)
        assert len(gw.memory.cache) <= 2048 and gw.memory.floats <= 2097152
    asyncio.run(run())


def test_noisy_keywords_cannot_crowd_out_semantic_candidates(tmp_path, template):
    state = initial_state(template, 'Visitor')
    pc = state['player']
    state = apply_events(state, [record('agreement', [pc], '明天把陶笛送回蓝铃塔。'),
                                 *[record(f'noise_{i}', [pc], f'The weather at the dock today, number {i}') for i in range(100)]], 1)
    async def embedding(config, payload, headers):
        return {'model': 'fixture', 'vectors': [[1., 0.] if '陶笛' in text or 'instrument' in text else [.4, .9]
                                               for text in payload['input']]}
    gw, _ = gateway(tmp_path, embedding)
    async def run():
        found = await gw.memory.recall(state, pc, 'Where is the instrument?', 'noise', budget(), limit=5)
        assert 'agreement' in {row['source_id'] for row in found}
    asyncio.run(run())


def test_runtime_cancel_during_recall_never_commits(tmp_path, template):
    store = Store(tmp_path / 'store')
    campaign = store.create_campaign('owner', template, 'Visitor')
    bid = campaign['main_branch']
    action, _ = store.accept(campaign['id'], bid, 'owner', ActionCommand(
        action_id='cancel_recall', expected_world_version=0, mode='say', text='Ask about the instrument.'))
    before = digest(store.branches[bid]['state'])
    async def run():
        entered = asyncio.Event()
        async def pending(*args):
            entered.set()
            await asyncio.Event().wait()
        gw, _ = gateway(tmp_path / 'traces', pending)
        task = asyncio.create_task(Runtime(store, gw).run(action['id']))
        await entered.wait()
        task.cancel()
        await task
        assert action['status'] == 'interrupted' and digest(store.branches[bid]['state']) == before
    try:
        asyncio.run(run())
    finally:
        store.close()


def test_api_recall_is_authorized_read_only_and_setting_capabilities(tmp_path, template):
    embed = EmbeddingFixture()
    registry = builtin_engines()
    registry.register(Engine('fixture_vectors', frozenset({'embed'}), embed))
    gw, _ = gateway(tmp_path / 'config', embed)
    app = create_app(config=AppConfig(workspace_root=tmp_path / 'host'), model_config=gw.config, registry=registry)
    with TestClient(app) as client:
        client.headers['X-CSRF-Token'] = client.post('/api/session').json()['csrf_token']
        campaign = client.post('/api/campaigns', json={}).json()
        cid, bid = campaign['id'], campaign['branch_id']
        state = app.state.store.branches[bid]['state']
        action, _ = app.state.store.accept(cid, bid, app.state.store.campaigns[cid]['owner'],
                                         ActionCommand(action_id='seed', expected_world_version=0, text='fixture'))
        app.state.store.commit(action['id'], [record('old_promise', [state['player']], '明天把陶笛送回蓝铃塔。')], [], [], [], None)
        journal = app.state.store.journal.path.read_bytes() if hasattr(app.state.store.journal, 'path') else (tmp_path / 'host/data/journal.jsonl').read_bytes()
        response = client.post(f'/api/campaigns/{cid}/branches/{bid}/recall', json={'query': 'instrument', 'limit': 1})
        assert response.status_code == 200, response.text
        assert response.json()['records'][0]['source_id'] == 'old_promise'
        assert response.json()['world_version'] == 1
        assert (tmp_path / 'host/data/journal.jsonl').read_bytes() == journal
        assert client.post('/api/engines/memory_embedding/check').json()['protocol_passed']
        client.cookies.clear()
        assert client.post(f'/api/campaigns/{cid}/branches/{bid}/recall', json={'query': 'instrument'}).status_code in {401, 403}
    with pytest.raises(ValueError):
        ProviderSettings(url='http://localhost/v1', model='main', providers={'p': {'backend': 'openai', 'url': 'http://localhost/v1'}},
                         bindings={'memory_embedding': {'provider': 'p', 'model': 'wrong'}})
    with pytest.raises(ValueError):
        ProviderSettings(url='http://localhost/v1', model='main', memory_policy={'mode': 'hybrid'})


def test_runtime_passes_recalled_sources_to_planner_and_actor_then_replays(tmp_path, template):
    gw, embed = gateway(tmp_path / 'traces')
    seen = []
    async def generate(role, system, data, schema, action_id, budget, validate=None):
        seen.append((role, deepcopy(data)))
        if role == 'game_master':
            return schema.model_validate({'intent': 'Ask about the instrument', 'speakers': ['npc_captain']})
        if role == 'character_actor':
            return schema.model_validate({'reaction': 'none', 'text': 'Return it to Bluebell Tower.'})
        return schema.model_validate({'text': 'The captain recalls the arrangement.', 'suggestions': []})
    gw.generate = generate
    store = Store(tmp_path / 'store')
    campaign = store.create_campaign('owner', template, 'Visitor')
    bid = campaign['main_branch']
    pc = store.branches[bid]['state']['player']
    setup, _ = store.accept(campaign['id'], bid, 'owner', ActionCommand(action_id='history', expected_world_version=0, text='fixture'))
    store.commit(setup['id'], [record('old_promise', [pc, 'npc_captain'], '明天把陶笛送回蓝铃塔。'),
                              *[record(f'filler_{i}', [pc, 'npc_captain'], f'天气记录 {i}') for i in range(120)]], [], [], [], None)
    command = ActionCommand(action_id='ask', expected_world_version=1, text='Where should the instrument go?', mode='say')
    action, _ = store.accept(campaign['id'], bid, 'owner', command)
    asyncio.run(Runtime(store, gw).run(action['id']))
    assert action['status'] == 'committed', action.get('error')
    for role, context in seen:
        if role in {'game_master', 'character_actor'}:
            view = context['player_view' if role == 'game_master' else 'view']
            assert 'old_promise' in {row['source_id'] for row in view['memories'] if 'similarity' in row}
    assert {'game_master', 'character_actor'} == {role for role, _ in seen}
    final = digest(store.branches[bid]['state'])
    store.close()
    with_calls = len(embed.calls)
    restored = Store(tmp_path / 'store')
    assert digest(restored.branches[bid]['state']) == final and len(embed.calls) == with_calls
    assert restored.accept(campaign['id'], bid, 'owner', command)[1] is False
    restored.close()


def test_room_recall_uses_member_perspective_and_host_provider(tmp_path):
    gw, embed = gateway(tmp_path / 'traces')
    app = create_app(config=AppConfig(workspace_root=tmp_path / 'host'), model_config=gw.config, registry=gw.registry)
    with TestClient(app) as client:
        client.headers['X-CSRF-Token'] = client.post('/api/session').json()['csrf_token']
        host_cookie, host_csrf = dict(client.cookies), client.headers['X-CSRF-Token']
        c = client.post('/api/campaigns', json={}).json()
        room = client.post('/api/rooms', json={'campaign_id': c['id'], 'branch_id': c['branch_id'],
                                              'mode': 'independent_characters'}).json()
        client.cookies.clear()
        client.headers['X-CSRF-Token'] = client.post('/api/session').json()['csrf_token']
        guest = client.post('/api/rooms/join', json={'code': room['invite_code'], 'name': 'Guest'}).json()
        actor = guest['state']['player_actor_id']
        store = app.state.store
        state = store.branches[c['branch_id']]['state']
        host = store.campaigns[c['id']]['owner']
        # Give only the guest this historical observation, through a committed event.
        pending, _ = store.accept(c['id'], c['branch_id'], host, ActionCommand(
            action_id='guest_memory', expected_world_version=state['version'], text='Fixture history'))
        store.commit(pending['id'], [record('guest_instrument', [actor], '陶笛在塔里。')], [], [], [], None)
        # The guest's invalid embedding endpoint must never receive room history.
        guest_config = ProviderSettings(url='http://localhost/v1', model='unused')
        import hashlib
        guest_owner = hashlib.sha256(client.cookies.get('rpw_session').encode()).hexdigest()
        app.state.settings.save(guest_owner, guest_config)
        path = f'/api/rooms/{room["id"]}/recall'
        result = client.post(path, json={'query': 'instrument', 'limit': 1})
        assert result.status_code == 200, result.text
        assert result.json()['records'][0]['source_id'] == 'guest_instrument'
        assert embed.calls and app.state.settings.report(host)['calls'] > 0
        assert app.state.settings.report(guest_owner)['calls'] == 0
        client.cookies.clear()
        client.cookies.update(host_cookie)
        client.headers['X-CSRF-Token'] = host_csrf
        found = client.post(path, json={'query': 'instrument'}).json()['records']
        assert 'guest_instrument' not in {row['source_id'] for row in found}
        client.cookies.clear()
        client.headers['X-CSRF-Token'] = client.post('/api/session').json()['csrf_token']
        assert client.post(path, json={'query': 'instrument'}).status_code == 404
