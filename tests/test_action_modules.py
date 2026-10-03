import asyncio
import importlib.util
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_content_preferences import SceneFixture, scene
from test_packages import metadata
from test_studio import session, wait_job

from roleplay_world.action_modules import ActionRegistry, ModuleBinding, ModuleReceipt, ModuleState, audit_modules
from roleplay_world.app import create_app
from roleplay_world.backups import export_campaign, restore_campaign, validate_backup
from roleplay_world.content import WorldBlueprint, compile_story
from roleplay_world.continuity import carry_world
from roleplay_world.contracts import ActionCommand, DomainError, Operation
from roleplay_world.json_schema import validator
from roleplay_world.packages import preview_package, read_package
from roleplay_world.planning import explicit_goal_plan, plan_schema, validate_plan
from roleplay_world.players import commit_perspectives, join_player
from roleplay_world.rulepacks import RuleSet
from roleplay_world.rules import resolve
from roleplay_world.runtime import Runtime
from roleplay_world.store import Store
from roleplay_world.world import apply_events, initial_state, project

spec = importlib.util.spec_from_file_location('exploration_example', Path(__file__).parents[1] / 'examples/action_module.py')
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


def registry_with(**changes):
    original = example.make_registry()
    module = original._modules[('example_exploration', '1')]
    registry = ActionRegistry()
    registry.register(replace(module, **changes))
    return registry


def authored(registry=None, *, options=None, rules=False):
    registry = registry or example.make_registry()
    world, story = scene()
    world.action_modules = [registry.bind({**example.SELECTION, 'options': options or {}})]
    if rules:
        world.rules = RuleSet()
    template = compile_story(world, story, 'module_story')
    template['world_ref'] = {'id': 'same_world', 'revision': 1}
    return registry, template


def command(version=0, action='survey', *, selected=True, parameters=None):
    return ActionCommand(action_id=f'module_{action}_{version}', expected_world_version=version,
        text='I survey the terrain and ask Robin about it.' if action == 'survey' else 'I rest my focus.',
        selected_operation=Operation(kind='module', target_id='exploration', action_id=action,
            parameters=parameters if parameters is not None else {'focus': {'subject': 'terrain'}} if action == 'survey' else {})
        if selected else None)


def execute(state, registry, action='survey', parameters=None):
    cmd = command(state['version'], action, parameters=parameters).model_dump(exclude_none=True)
    plan = explicit_goal_plan(state, cmd)
    events, effects, roll = resolve(state, cmd, plan, {}, 3, action_registry=registry)
    return apply_events(state, events, state['version'] + 1), events, effects, roll


def test_typed_nested_parameters_provider_schema_and_deterministic_replay():
    registry, template = authored()
    state = initial_state(template, 'Explorer')
    snapshot = deepcopy(state)
    cmd = command().model_dump(exclude_none=True)
    schema = plan_schema(state, cmd)
    plan = {'intent': 'Survey', 'operations': [cmd['selected_operation']]}
    validator(schema.model_json_schema()).validate(plan)
    accepted = schema.model_validate(plan)
    validate_plan(state, cmd, accepted)
    after, events, effects, roll = execute(state, registry)
    assert state == snapshot and roll is None
    assert after == execute(state, registry)[0]
    assert after == apply_events(state, events, 1)
    assert after['game_time_s'] == 30
    assert after['action_modules']['exploration']['public']['surveys'] == 1
    assert after['action_modules']['exploration']['actors'][state['player']]['focus'] == 2
    assert effects and all(e['visibility']['actor_ids'] == [state['player']] for e in events if e['type'] == 'module.resolved')
    assert audit_modules(template, registry)[0]['status'] == 'passed'


@pytest.mark.parametrize('parameters', [{'focus': {'subject': 'hidden'}}, {'focus': {'arbitrary': True}}, {'unknown': 1}])
def test_invalid_parameters_fail_runtime_and_provider_schema(parameters):
    registry, template = authored()
    state = initial_state(template, 'Explorer')
    cmd = command(parameters=parameters).model_dump(exclude_none=True)
    schema = plan_schema(state, cmd)
    with pytest.raises((DomainError, ValidationError)):
        schema.model_validate({'intent': 'Bad survey', 'operations': [cmd['selected_operation']]})
    with pytest.raises(DomainError):
        execute(state, registry, parameters=parameters)


@pytest.mark.parametrize('parameters', [{'number': float('inf')}, {'text': 'x' * 16001}])
def test_parameters_are_bounded_finite_json(parameters):
    with pytest.raises(ValidationError):
        Operation(kind='module', target_id='exploration', action_id='survey', parameters=parameters)
    registry, template = authored()
    _, events, _, _ = execute(initial_state(template, 'Explorer'), registry)
    payload = next(e['payload'] for e in events if e['type'] == 'module.resolved')
    payload['parameters'] = parameters
    with pytest.raises(ValidationError):
        ModuleReceipt.model_validate(payload)


def test_module_preconditions_and_player_resources():
    registry, template = authored(options={'focus_max': 1, 'vitality_cost': 2}, rules=True)
    state = initial_state(template, 'Explorer')
    player = state['player']
    after, _, _, _ = execute(state, registry)
    assert after['actor_states'][player]['resources']['vitality'] == state['actor_states'][player]['resources']['vitality'] - 2
    with pytest.raises(DomainError) as error:
        execute(after, registry)
    assert error.value.code == 'module_precondition'
    rested, _, _, _ = execute(after, registry, 'rest')
    assert rested['action_modules']['exploration']['actors'][player]['focus'] == 1
    assert rested['actor_states'][player]['resources'] == after['actor_states'][player]['resources']
    audit_modules(template, registry)


def test_unknown_versions_duplicate_bindings_and_changed_contracts():
    registry, template = authored()
    value = deepcopy(template['mechanics']['action_modules'][0])
    with pytest.raises(DomainError):
        registry.selections([example.SELECTION, example.SELECTION])
    value['version'] = 'absent'
    with pytest.raises(DomainError, match='unavailable'):
        registry.validate(value)
    value['version'] = '1'
    value['actions'][0]['name'] = 'Different contract'
    with pytest.raises(DomainError) as error:
        registry.validate(value)
    assert error.value.code == 'action_module_contract_changed'
    template['mechanics']['action_modules'] *= 2
    with pytest.raises(DomainError):
        initial_state(template, 'Explorer')


def test_callback_inputs_are_copied_and_nondeterminism_is_rejected():
    def isolated(context, action, parameters, options, rng):
        result = example.resolve(context, action, parameters, options, rng)
        context['module_state']['private']['draws'] = 987
        context['actor_state']['location_id'] = 'missing'
        return result
    registry, template = authored(registry_with(resolve=isolated))
    state = initial_state(template, 'Explorer')
    before = deepcopy(state)
    execute(state, registry)
    assert state == before
    count = 0
    def unstable(*args):
        nonlocal count
        count += 1
        result = example.resolve(*args)
        result.state.private['draws'] = count
        return result
    with pytest.raises(DomainError) as error:
        execute(state, registry_with(resolve=unstable))
    assert error.value.code == 'invalid_module_result'


@pytest.mark.parametrize('mutation', ['state', 'parameters', 'actor', 'binding', 'before', 'visibility', 'resource', 'extra'])
def test_forged_receipts_fail_generic_replay(mutation):
    registry, template = authored()
    state = initial_state(template, 'Explorer')
    _, events, _, _ = execute(state, registry)
    event = next(e for e in events if e['type'] == 'module.resolved')
    payload = event['payload']
    if mutation == 'state': payload['after']['public']['surveys'] = -1
    if mutation == 'parameters': payload['parameters'] = {'focus': {'subject': 'unknown'}}
    if mutation == 'actor': payload['actor_id'] = 'npc_0'
    if mutation == 'binding': payload['binding_sha256'] = '0' * 64
    if mutation == 'before': payload['before_sha256'] = '0' * 64
    if mutation == 'visibility': event['visibility'] = {'kind': 'public'}
    if mutation == 'resource': payload['resource_deltas'] = {'coins': 100}
    if mutation == 'extra': payload['arbitrary_event'] = 'actor.moved'
    with pytest.raises(DomainError) as error:
        apply_events(state, events, 1)
    assert error.value.code == 'invalid_module_receipt'


def test_private_partitions_and_multiplayer_perspectives():
    registry, template = authored()
    state = initial_state(template, 'Explorer')
    join_player(state, {'type': 'player.joined', 'visibility': {'kind': 'public'},
                        'payload': {'id': 'pc_other', 'name': 'Other player', 'role': 'Visitor'}})
    after, events, effects, _ = execute(state, registry)
    own = project(after)['action_modules'][0]
    other = project(after, 'pc_other')['action_modules'][0]
    npc = project(after, 'npc_0')['action_modules'][0]
    assert own['personal']['focus'] == 2
    assert other['public']['surveys'] == npc['public']['surveys'] == 1
    assert other['personal'] == npc['personal'] == {} and npc['actions'] == []
    assert all('private' not in row and 'draws' not in str(row) for row in (own, other, npc))
    commit = {'id': 'one', 'action_id': 'one', 'version': 1, 'segments': [], 'effects': effects, 'suggestions': [],
              'roll': None, 'player_text': 'Survey', 'mode': 'act', 'game_time_s': 30, 'events': events}
    perspectives = commit_perspectives(state, after, {'actor_id': state['player']}, commit)
    assert 'pc_other' not in perspectives  # No private text becomes another player's history.


class InspectGateway(SceneFixture):
    def __init__(self, *, fail_narration=False):
        super().__init__()
        self.fail_narration = fail_narration

    async def generate(self, role, system, data, schema, aid, budget, validate=None):
        if role == 'game_master' and data['mode'] == 'act':
            self.calls.append((role, system, deepcopy(data)))
            assert 'initial' not in data['mechanics']['action_modules'][0]
            result = schema(intent='Survey the terrain', speakers=['npc_0'], operations=[
                command().selected_operation.model_dump(exclude_none=True)])
            if validate:
                validate(result)
            return result
        if role == 'character_actor':
            assert data['current_observed_effects'] == []
            assert data['view']['action_modules'][0]['personal'] == {}
            assert 'draws' not in json.dumps(data) and 'quality ' not in json.dumps(data)
        if role == 'narrator':
            assert 'draws' not in json.dumps(data)
            if self.fail_narration:
                raise RuntimeError('Fixture outage')
        return await super().generate(role, system, data, schema, aid, budget, validate)


def test_model_planning_npc_privacy_and_prepared_retry_without_plugin(tmp_path):
    async def run():
        registry, template = authored()
        store = Store(tmp_path, action_registry=registry)
        campaign = store.create_campaign('owner', template, 'Explorer')
        cmd = command(selected=False)
        action, _ = store.accept(campaign['id'], campaign['main_branch'], 'owner', cmd)
        gateway = InspectGateway(fail_narration=True)
        runtime = Runtime(store, gateway)
        await runtime.run(action['id'])
        assert action['status'] == 'failed' and 'prepared' in action
        assert store.branches[campaign['main_branch']]['state']['version'] == 0
        await runtime.close()
        store.close()
        # Prepared outcomes recover without invoking the module a second time.
        store = Store(tmp_path)
        gateway = InspectGateway()
        runtime = Runtime(store, gateway)
        runtime.retry(action['id'], 'owner')
        await asyncio.gather(*runtime.tasks.values())
        assert store.actions[action['id']]['status'] == 'committed'
        assert [row[0] for row in gateway.calls] == ['narrator']
        before = deepcopy(store.branches[campaign['main_branch']]['state'])
        again, fresh = store.accept(campaign['id'], campaign['main_branch'], 'owner', cmd)
        assert not fresh and again['commit_id']
        raw = json.dumps(export_campaign(store, campaign['id'], 'owner'))
        validate_backup(raw)
        restored = restore_campaign(store, 'reader', raw)
        assert store.branches[restored['branch_id']]['state'] == before
        fork = store.fork(campaign['id'], campaign['main_branch'], 'owner', 1, 'Retained outcome')
        assert fork['state'] == before
        new, _ = store.accept(campaign['id'], campaign['main_branch'], 'owner', command(1))
        count = len(gateway.calls)
        await runtime.run(new['id'])
        assert new['status'] == 'failed' and len(gateway.calls) == count
        assert store.branches[campaign['main_branch']]['state'] == before
        await runtime.close()
        store.close()
    asyncio.run(run())


def test_cancellation_discards_module_changes(tmp_path):
    async def run():
        class BlockedNarrator:
            async def generate(self, *args, **kwargs):
                entered.set()
                await asyncio.Event().wait()
        entered = asyncio.Event()
        registry, template = authored()
        store = Store(tmp_path, action_registry=registry)
        try:
            campaign = store.create_campaign('owner', template, 'Explorer')
            baseline = deepcopy(store.branches[campaign['main_branch']]['state'])
            action, _ = store.accept(campaign['id'], campaign['main_branch'], 'owner', command())
            runtime = Runtime(store, BlockedNarrator())
            runtime.start(action['id'])
            await asyncio.wait_for(entered.wait(), 5)
            runtime.cancel(action['id'], 'owner')
            await runtime.close()
            assert action['status'] == 'cancelled'
            assert store.branches[campaign['main_branch']]['state'] == baseline
        finally:
            store.close()
    asyncio.run(run())


def test_same_world_story_continuation_keeps_module_state():
    registry, template = authored()
    after, _, _, _ = execute(initial_state(template, 'Explorer'), registry)
    source = {'id': 'source', 'state': after}
    target = carry_world(template, source, {'id': 'campaign', 'player_name': 'Explorer'}, 1)
    assert initial_state(target, 'Explorer')['action_modules'] == after['action_modules']
    changed = deepcopy(template)
    changed['mechanics']['action_modules'][0]['options'] = {'focus_max': 5}
    with pytest.raises(DomainError) as error:
        carry_world(changed, source, {'id': 'campaign', 'player_name': 'Explorer'}, 1)
    assert error.value.code == 'incompatible_modules'


def test_host_test_routes_require_coverage_and_enforce_expectations():
    _, template = authored()
    binding = template['mechanics']['action_modules'][0]
    def incomplete(options):
        value = example.contract_tests(options)
        value[0]['steps'] = value[0]['steps'][:1]
        return value
    with pytest.raises(DomainError, match='every'):
        registry_with(tests=incomplete).test_cases(binding)
    def wrong(options):
        value = example.contract_tests(options)
        value[0]['expect'] = {'const': 'unreachable result'}
        return value
    with pytest.raises(DomainError) as error:
        audit_modules(template, registry_with(tests=wrong))
    assert error.value.code == 'module_schema'


def test_module_binding_rejects_remote_schemas_and_invalid_actor_references():
    _, template = authored()
    binding = deepcopy(template['mechanics']['action_modules'][0])
    binding['actions'][0]['parameters_schema'] = {'$ref': 'https://example.invalid/schema.json'}
    with pytest.raises(ValueError):
        ModuleBinding.model_validate(binding)
    template['mechanics']['action_modules'][0]['initial']['actors']['unknown'] = {'focus': 1}
    with pytest.raises(DomainError) as error:
        initial_state(template, 'Explorer')
    assert error.value.code == 'invalid_module_actor'
    with pytest.raises(ValidationError):
        ModuleState(public={'value': float('nan')})


def test_studio_api_automatic_module_routes_package_dependency_and_idempotency(tmp_path):
    registry = example.make_registry()
    gateway = SceneFixture()
    with TestClient(create_app(tmp_path / 'source', gateway, action_registry=registry)) as client:
        session(client)
        description = client.get('/api/action-modules').json()[0]
        assert description['engine'] == 'example_exploration'
        assert 'state_schema' not in description  # Private schema defaults belong to the host.
        invalid = client.post('/api/studio/worlds', json={'prompt': 'A quiet field station', 'creation_preset': 'scene',
                             'action_modules': [{**example.SELECTION, 'version': 'absent'}]})
        assert invalid.status_code == 422 and not gateway.calls
        request = {'prompt': 'A quiet field station', 'creation_preset': 'scene',
                   'request_id': 'create_with_module', 'action_modules': [example.SELECTION]}
        response = client.post('/api/studio/worlds', json=request)
        assert response.status_code == 202, response.text
        ready = wait_job(client, response.json()['id'])
        assert ready['status'] == 'ready', ready.get('error')
        assert client.post('/api/studio/worlds', json=request).json()['id'] == ready['id']
        changed = {**request, 'action_modules': [{**example.SELECTION, 'options': {'focus_max': 4}}]}
        assert client.post('/api/studio/worlds', json=changed).status_code == 409
        assert any(c['name'].startswith('Action module model route:') for c in ready['checks'])
        package = client.post('/api/studio/packages', json={
            'metadata': metadata(), 'stories': [{'id': ready['story_id'], 'revision': 1}]}).json()
        raw = client.get(f'/api/community/{package["id"]}/download').content
    parsed = read_package(raw)
    assert parsed['manifest']['engine_minimum'] == '0.19.0'
    assert 'action_modules' in parsed['manifest']['capabilities']
    assert preview_package(parsed)['action_modules'] == [{k: example.SELECTION[k] for k in ('id', 'engine', 'version')}]
    # Parsing/importing content never needs module code. Executing it does.
    world = WorldBlueprint.model_validate(parsed['payload']['world'])
    assert world.action_modules[0].engine == 'example_exploration'
    recipient_gateway = SceneFixture()
    with TestClient(create_app(tmp_path / 'recipient', recipient_gateway)) as client:
        session(client)
        imported = client.post('/api/studio/packages/import', content=raw)
        assert imported.status_code == 202, imported.text
        job = wait_job(client, imported.json()['id'])
        assert job['status'] == 'failed' and 'unavailable' in job['error']
        assert not recipient_gateway.calls
        assert client.get('/api/studio').json()['worlds'][0]['content']['action_modules']


def test_old_selected_operation_keeps_its_request_shape():
    original = {'schema_version': '0.1.0', 'action_id': 'legacy', 'expected_world_version': 0,
                'mode': 'act', 'text': 'Move', 'selected_operation': {'kind': 'move', 'target_id': 'loc_0',
                'when': 'always', 'quantity': 1}}
    assert ActionCommand.model_validate(original).model_dump(exclude_none=True) == original
