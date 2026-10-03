import asyncio
import json
import random
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import Field
from test_content_preferences import SceneFixture
from test_rulepacks import build_game_template
from test_studio import session, wait_job

from roleplay_world.app import create_app
from roleplay_world.backups import export_campaign, restore_campaign, validate_backup
from roleplay_world.checks import CheckBinding, CheckEngine, CheckInput, CheckResult, builtin_checks
from roleplay_world.config import AppConfig
from roleplay_world.contracts import ActionCommand, Contract, DomainError, TurnPlan
from roleplay_world.journal import digest
from roleplay_world.packages import read_package
from roleplay_world.planning import explicit_goal_plan
from roleplay_world.rules import resolve
from roleplay_world.runtime import Runtime
from roleplay_world.store import Store
from roleplay_world.world import apply_events, initial_state, project


class PoolOptions(Contract):
    dice: int = Field(default=4, strict=True, ge=1, le=20)
    hit: int = Field(default=5, strict=True, ge=2, le=6)


def pool(request, options, rng):
    draws = [rng.randint(1, 6) for _ in range(options.dice)]
    hits = sum(value >= options.hit for value in draws)
    total = hits + request.modifier
    return CheckResult(roll=hits, modifier=request.modifier, total=total, difficulty=request.difficulty,
                       passed=total >= request.difficulty, dice=f'{options.dice}d6 successes',
                       comparison='>=', draws=draws)


def custom_registry(callback=pool):
    registry = builtin_checks()
    registry.register(CheckEngine('pool', 'one', PoolOptions, callback, 'Count successes.',
                                  'Roll the configured dice and count faces at or above hit.'))
    return registry


CUSTOM = {'engine': 'pool', 'version': 'one', 'options': {'dice': 4, 'hit': 5}}
SUM = {'engine': 'sum_dice', 'version': '1', 'options': {'count': 2, 'sides': 6}}


@pytest.fixture
def game_template():
    return build_game_template()


def attack_template(template, binding=None):
    result = deepcopy(template)
    if binding:
        result['mechanics']['checks'] = deepcopy(binding)
    result['mechanics']['rules']['enemies'][0].update(hp=100, defense=7)
    result['actors'][-1]['initial_state'].update(resources={'hp': 100}, resource_limits={'hp': 100})
    player = next(actor for actor in result['actors'] if actor['control'] == 'player')
    player['initial_state']['location_id'] = 'loc_1'
    return result


def attack(state, registry=None, seed=1):
    command = ActionCommand(action_id='strike', expected_world_version=state['version'], text='Attack the training dummy.',
                            selected_operation={'kind': 'attack', 'target_id': 'enemy_dummy'}).model_dump(exclude_none=True)
    plan = explicit_goal_plan(state, command)
    return resolve(state, command, plan, {}, seed, check_registry=registry)


@pytest.mark.parametrize('percentile,expected', [
    (False, {'skill': 'craft', 'purpose': 'Inspect', 'roll': 11, 'modifier': 2,
             'total': 13, 'difficulty': 12, 'passed': True}),
    (True, {'skill': 'craft', 'purpose': 'Inspect', 'roll': 42, 'modifier': 0,
            'total': 42, 'difficulty': 12, 'passed': False, 'dice': 'd100', 'comparison': '<='}),
])
def test_legacy_ability_receipt_shape_and_seed(state, percentile, expected):
    state['actor_states'][state['player']]['skills']['craft'] = 2
    if percentile:
        state['template']['mechanics']['rules'] = {'system': 'd100'}
    plan = TurnPlan(intent='Inspect', check={'skill': 'craft', 'purpose': 'Inspect', 'difficulty': 12})
    events, _, roll = resolve(state, {'action_id': 'inspect', 'text': 'Inspect', 'mode': 'act'}, plan, {}, 7)
    assert roll == expected
    assert next(event['payload'] for event in events if event['type'] == 'check.resolved') == expected


@pytest.mark.parametrize('system,first,counter,success', [('d20', 5, 19, True), ('d100', 18, 73, False)])
def test_legacy_combat_rng_sequence_and_counter_shape(game_template, system, first, counter, success):
    template = attack_template(game_template)
    template['mechanics']['rules']['system'] = system
    _, _, roll = attack(initial_state(template, 'Tester'))
    assert roll['roll'] == first
    assert roll['counterattack'] == {
        'purpose': '训练傀儡反击', 'roll': counter, 'passed': success, 'dice': system,
        'target': 55 if system == 'd100' else 10, 'modifier': 0 if system == 'd100' else 2}
    assert 'engine' not in roll


def test_sum_dice_drives_attack_and_counter_without_mutating_baseline(game_template):
    state = initial_state(attack_template(game_template, SUM), 'Tester')
    before = deepcopy(state)
    events, _, roll = attack(state)
    assert roll['draws'] == [2, 5] and roll['total'] == 9 and roll['passed']
    assert roll['counterattack']['draws'] == [1, 3] and not roll['counterattack']['passed']
    assert state == before
    after = apply_events(state, events, 1)
    assert after['actor_states']['enemy_dummy']['resources']['hp'] == 97
    assert after['actor_states'][state['player']]['resources']['hp'] == 20
    assert roll['engine'] == {'id': 'sum_dice', 'version': '1', 'options_sha256': digest(SUM['options'])}
    assert 'options' not in roll['engine']


def test_custom_engine_is_deterministic_and_isolated(game_template):
    calls = []
    def record(request, options, rng):
        calls.append(request.kind)
        return pool(request, options, rng)
    registry = custom_registry(record)
    registry.verify(CUSTOM)
    assert set(calls) == {'ability', 'attack', 'counterattack'}
    state = initial_state(attack_template(game_template, CUSTOM), 'Tester')
    assert attack(state, registry) == attack(state, registry)
    assert state['template']['mechanics']['checks'] == CUSTOM
    with pytest.raises(ValueError, match='already registered'):
        registry.register(CheckEngine('pool', 'one', PoolOptions, pool, 'Description', 'Guidance'))
    copy = registry.copy()
    registry.register(CheckEngine('pool', 'two', PoolOptions, pool, 'Description', 'Guidance'))
    with pytest.raises(DomainError, match='unavailable'):
        copy.binding({**CUSTOM, 'version': 'two'})


@pytest.mark.parametrize('binding', [
    {**CUSTOM, 'version': 'absent'}, {**CUSTOM, 'options': {'dice': 0}},
    {**CUSTOM, 'options': {'dice': True}}, {**CUSTOM, 'options': {'arbitrary': 4}},
])
def test_unavailable_or_invalid_binding_prevents_campaign_write(tmp_path, game_template, binding):
    store = Store(tmp_path, check_registry=custom_registry())
    before = (tmp_path / 'journal.jsonl').read_bytes()
    try:
        with pytest.raises(DomainError):
            store.create_campaign('owner', attack_template(game_template, binding), 'Tester')
        assert not store.campaigns and (tmp_path / 'journal.jsonl').read_bytes() == before
    finally:
        store.close()


def test_result_arithmetic_and_repeatability_are_checked():
    def wrong(request, options, rng):
        result = pool(request, options, rng).model_dump()
        result['passed'] = not result['passed']
        return result
    with pytest.raises(DomainError) as error:
        custom_registry(wrong).verify(CUSTOM)
    assert error.value.code == 'invalid_check_result'
    count = 0
    def varying(request, options, rng):
        nonlocal count
        count += 1
        return CheckResult(roll=count, modifier=2, total=count + 2, difficulty=7,
                           passed=count + 2 >= 7, dice='fixture', comparison='>=')
    with pytest.raises(DomainError) as error:
        custom_registry(varying).verify(CUSTOM)
    assert error.value.code == 'nondeterministic_check_engine'
    async def asynchronous(*args):
        pass
    with pytest.raises(TypeError, match='synchronous'):
        custom_registry(asynchronous)


class Narrator:
    def __init__(self):
        self.calls = 0
    async def generate(self, role, system, data, schema, action_id, budget, validate=None):
        self.calls += 1
        assert role == 'narrator'
        return schema.model_validate({'text': 'The training exchange ends.', 'suggestions': []})


def accepted(store, campaign, name='strike'):
    bid = campaign['main_branch']
    command = ActionCommand(action_id=name, expected_world_version=store.branches[bid]['state']['version'],
                            text='Attack the training dummy.',
                            selected_operation={'kind': 'attack', 'target_id': 'enemy_dummy'})
    action, _ = store.accept(campaign['id'], bid, 'owner', command)
    return action


def test_invalid_callback_preserves_state_and_avoids_narration(tmp_path, game_template):
    def wrong(*args):
        return {'passed': True}
    store = Store(tmp_path, check_registry=custom_registry(wrong))
    try:
        campaign = store.create_campaign('owner', attack_template(game_template, CUSTOM), 'Tester')
        before = deepcopy(store.branches[campaign['main_branch']]['state'])
        action = accepted(store, campaign)
        gateway = Narrator()
        asyncio.run(Runtime(store, gateway).run(action['id']))
        assert action['status'] == 'failed' and gateway.calls == 0
        assert store.branches[campaign['main_branch']]['state'] == before
    finally:
        store.close()


def test_committed_custom_checks_replay_restore_and_fork_without_plugin(tmp_path, game_template):
    calls = []
    def record(request, options, rng):
        calls.append(request.kind)
        return pool(request, options, rng)
    store = Store(tmp_path / 'source', check_registry=custom_registry(record))
    campaign = store.create_campaign('owner', attack_template(game_template, CUSTOM), 'Tester')
    action = accepted(store, campaign)
    asyncio.run(Runtime(store, Narrator()).run(action['id']))
    assert action['status'] == 'committed'
    saved = deepcopy(store.branches[campaign['main_branch']]['state'])
    backup = export_campaign(store, campaign['id'], 'owner')
    count = len(calls)
    store.close()
    replay = Store(tmp_path / 'source')
    restored = Store(tmp_path / 'restored')
    try:
        assert replay.branches[campaign['main_branch']]['state'] == saved and len(calls) == count
        branch = replay.fork(campaign['id'], campaign['main_branch'], 'owner', 0, 'Before combat')
        assert branch['state']['actor_states']['enemy_dummy']['resources']['hp'] == 100
        copied = restore_campaign(restored, 'owner', json.dumps(backup))
        assert project(restored.branches[copied['branch_id']]['state']) == project(saved)
        pending = accepted(replay, campaign, 'missing')
        narrator = Narrator()
        asyncio.run(Runtime(replay, narrator).run(pending['id']))
        assert pending['status'] == 'failed' and narrator.calls == 0
        assert replay.branches[campaign['main_branch']]['state'] == saved
        forged = deepcopy(backup)
        check = next(event for event in forged['branches'][0]['commits'][0]['events'] if event['type'] == 'check.resolved')
        check['payload']['passed'] = not check['payload']['passed']
        forged['sha256'] = digest({key: value for key, value in forged.items() if key != 'sha256'})
        with pytest.raises(DomainError) as error:
            validate_backup(json.dumps(forged))
        assert error.value.code == 'invalid_backup'
    finally:
        replay.close()
        restored.close()


def test_interrupt_after_resolution_reuses_prepared_outcome(tmp_path, game_template):
    calls = []
    def record(request, options, rng):
        calls.append(request.kind)
        return pool(request, options, rng)
    store = Store(tmp_path, check_registry=custom_registry(record))
    campaign = store.create_campaign('owner', attack_template(game_template, CUSTOM), 'Tester')
    action = accepted(store, campaign)
    async def exercise():
        entered = asyncio.Event()
        class WaitingNarrator(Narrator):
            async def generate(self, *args, **kwargs):
                entered.set()
                await asyncio.Event().wait()
        runtime = Runtime(store, WaitingNarrator())
        task = asyncio.create_task(runtime.run(action['id']))
        await entered.wait()
        expected = deepcopy(action['prepared']['roll'])
        count = len(calls)
        task.cancel()
        await task
        assert action['status'] == 'interrupted'
        assert store.branches[campaign['main_branch']]['state']['version'] == 0
        runtime.gateway = Narrator()
        store.update(action['id'], status='accepted')
        await runtime.run(action['id'])
        assert action['status'] == 'committed' and action['result']['roll'] == expected
        assert len(calls) == count
    try:
        asyncio.run(exercise())
    finally:
        store.close()


def test_api_creation_pins_binding_and_validates_before_generation(tmp_path):
    app = create_app(config=AppConfig(workspace_root=tmp_path), gateway=SceneFixture())
    with TestClient(app) as client:
        session(client)
        assert client.get('/api/check-engines').json()[0]['id'] == 'sum_dice'
        bad = client.post('/api/studio/worlds', json={'prompt': 'A quiet seaside workshop', 'check_engine': CUSTOM})
        assert bad.status_code == 422 and bad.json()['error'] == 'check_engine_unavailable'
        assert not app.state.store.jobs
        request = {'prompt': 'A quiet seaside workshop', 'creation_preset': 'scene',
                   'content_language': 'en', 'request_id': 'custom_checks', 'check_engine': SUM}
        job = client.post('/api/studio/worlds', json=request).json()
        done = wait_job(client, job['id'])
        assert done['status'] == 'ready', done.get('error')
        world = app.state.store.worlds[done['world_id']]
        assert world['content']['check_engine'] == SUM
        assert any(check['name'] == '检定引擎契约' for check in done['checks'])
        campaign = client.post('/api/campaigns', json={'story_id': done['story_id'], 'player_name': 'Tester'}).json()
        assert app.state.store.campaigns[campaign['id']]['template']['mechanics']['checks'] == SUM
        assert client.post('/api/studio/worlds', json=request).json()['id'] == job['id']
        changed = {**request, 'check_engine': {**SUM, 'options': {'count': 3, 'sides': 6}}}
        assert client.post('/api/studio/worlds', json=changed).status_code == 409


def test_engine_and_options_are_recorded_as_data_only():
    binding = CheckBinding.model_validate(CUSTOM)
    assert binding.model_dump() == CUSTOM
    with pytest.raises(ValueError):
        CheckBinding(engine='../module', version='one')
    with pytest.raises(ValueError):
        CheckBinding(engine='pool', version='one', options={'value': float('inf')})
    result = custom_registry().run(binding, CheckInput(kind='ability', skill='craft', purpose='Inspect',
                                                     difficulty=3, modifier=1), random.Random(1))
    assert result['engine']['options_sha256'] == digest(CUSTOM['options'])


def test_package_preserves_engine_dependency_and_recipient_can_install_then_retest(tmp_path):
    with TestClient(create_app(config=AppConfig(workspace_root=tmp_path / 'source'),
                              gateway=SceneFixture(), check_registry=custom_registry())) as client:
        session(client)
        job = client.post('/api/studio/worlds', json={
            'prompt': 'A seaside workshop', 'creation_preset': 'scene', 'check_engine': CUSTOM}).json()
        ready = wait_job(client, job['id'])
        assert ready['status'] == 'ready', ready.get('error')
        story = client.app.state.store.stories[ready['story_id']]
        response = client.post('/api/studio/packages', json={
            'metadata': {'slug': 'workshop', 'release': '1.0.0', 'title': 'Workshop', 'summary': 'A quiet visit.',
                         'author': 'Fixture author', 'license': 'CC0-1.0'},
            'stories': [{'id': story['id'], 'revision': story['revision']}]})
        assert response.status_code == 201, response.text
        package = response.json()
        raw = client.get(f'/api/community/{package["id"]}/download').content
    parsed = read_package(raw)
    assert parsed['payload']['world']['check_engine'] == CUSTOM
    assert parsed['manifest']['engine_minimum'] == '0.19.0'  # World snapshot includes the action_modules field.
    assert 'check_engine' in parsed['manifest']['capabilities']
    class CountingFixture(SceneFixture):
        def __init__(self):
            super().__init__()
            self.count = 0
        async def generate(self, *args, **kwargs):
            self.count += 1
            return await super().generate(*args, **kwargs)
    gateway = CountingFixture()
    config = AppConfig(workspace_root=tmp_path / 'recipient')
    with TestClient(create_app(config=config, gateway=gateway)) as client:
        session(client)
        preview = client.post('/api/studio/packages/preview', content=raw).json()
        assert preview['check_engine'] == {'engine': 'pool', 'version': 'one'}
        imported = client.post('/api/studio/packages/import', content=raw).json()
        failed = wait_job(client, imported['id'])
        assert failed['status'] == 'failed' and 'pool@one' in failed['error']
        assert gateway.count == 0
        assert client.post('/api/campaigns', json={'story_id': imported['story_id']}).status_code == 409
        cookie = dict(client.cookies)
    with TestClient(create_app(config=config, gateway=gateway, check_registry=custom_registry())) as client:
        client.cookies.update(cookie)
        session(client)
        retried = client.post(f'/api/studio/jobs/{imported["id"]}/retry')
        assert retried.status_code == 200
        ready = wait_job(client, imported['id'])
        assert ready['status'] == 'ready', ready.get('error')
        saved = client.app.state.store.stories[imported['story_id']]
        assert saved['world_content'] == parsed['payload']['world']
        assert client.post('/api/campaigns', json={'story_id': imported['story_id']}).status_code == 201
