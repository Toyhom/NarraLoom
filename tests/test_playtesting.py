import asyncio
import json

import pytest

from roleplay_world.engines import Engine, builtin_engines
from roleplay_world.playtesting import playtest
from roleplay_world.store import Store

CONFIG = {'default': {'backend': 'test_playtest', 'model': 'contract-fixture', 'json_schema': True}}


def adapter(*, fail_at=None):
    calls = []
    async def invoke(config, payload, headers):
        calls.append(payload)
        if len(calls) == fail_at:
            raise RuntimeError('fixture failure')
        name = payload['response_format']['json_schema']['name']
        responses = {'SceneTurnPlan': {'intent': 'chat', 'operations': [], 'speakers': ['npc_captain'], 'time_cost_s': 30},
                     'SceneActorReply': {'text': 'I remember the old bell.', 'reaction': 'none'},
                     'ActorReply': {'text': 'I remember the old bell.'},
                     'Narration': {'text': 'Time passes.', 'suggestions': []}}
        return {'model': 'contract-fixture', 'text': json.dumps(responses[name]),
                'usage': {'prompt_tokens': 20, 'completion_tokens': 10}}
    registry = builtin_engines()
    registry.register(Engine('test_playtest', frozenset({'generate'}), invoke))
    return registry, calls


def plan(count=3):
    return {'steps': [{'id': f'turn_{i}', 'command': {'mode': 'say', 'text': 'Captain, let us talk about the weather.'}}
                      for i in range(count)]}


def run(template, plan, tmp_path, registry, **options):
    return asyncio.run(playtest(template, plan, config=CONFIG, output=tmp_path / 'run', registry=registry, **options))


def test_checkpoint_resume_recovers_commits_without_model_repetition(template, tmp_path):
    registry, calls = adapter()
    report = run(template, plan(), tmp_path, registry, max_steps=2)
    assert report['status'] == 'checkpointed' and report['metrics']['committed'] == 2
    count = len(calls)
    report = run(template, plan(), tmp_path, registry, resume=True)
    assert len(calls) > count
    assert report['status'] == 'completed' and report['replay']['world_version'] == 3
    count = len(calls)
    again = run(template, plan(), tmp_path, registry, resume=True)
    assert len(calls) == count and again['metrics'] == report['metrics']
    with pytest.raises(ValueError, match='changed'):
        run(template, plan(4), tmp_path, registry, resume=True)


def test_gold_never_enters_model_input_and_wrong_answers_are_retained(template, tmp_path):
    registry, calls = adapter()
    p = plan(2)
    p['steps'][0]['expect'] = {'properties': {'result': {'properties': {'segments': {
        'contains': {'properties': {'text': {'const': 'UNSEEN_GOLD_28'}}, 'required': ['text']}}}}}}
    p['steps'][1]['expect'] = {'properties': {'view': {'properties': {'world_version': {'const': 2}}}}}
    report = run(template, p, tmp_path, registry)
    assert report['status'] == 'failed' and report['metrics']['committed'] == 2
    assert report['steps'][0]['passed'] is False and report['steps'][1]['passed'] is True
    assert 'UNSEEN_GOLD_28' not in json.dumps(calls)
    assert report['metrics']['reported_input_tokens'] == len(calls) * 20


def test_private_and_historical_memory_probes_do_not_change_world(template, tmp_path):
    registry, _calls = adapter()
    p = plan(1)
    p['steps'][0]['command']['text'] = 'The name of my secret pet is PET-WILLOW-28.'
    p['steps'][0]['recalls'] = [
        {'query': 'PET-WILLOW-28', 'actor_id': 'npc_captain', 'expect': {'minItems': 1}},
        {'query': 'PET-WILLOW-28', 'actor_id': 'npc_captain', 'world_version': 0, 'expect': {'maxItems': 0}},
        {'query': 'PET-WILLOW-28', 'actor_id': 'npc_keeper', 'expect': {'maxItems': 0}},
    ]
    report = run(template, p, tmp_path, registry)
    assert report['status'] == 'completed' and report['replay']['world_version'] == 1
    assert len(report['steps'][0]['recalls']) == 3


def test_explicit_retry_keeps_failed_attempts_and_prepared_plan(template, tmp_path):
    registry, calls = adapter(fail_at=2)
    report = run(template, plan(2), tmp_path, registry)
    assert report['status'] == 'execution_failed' and report['metrics']['committed'] == 0
    count = len(calls)
    report = run(template, plan(2), tmp_path, registry, resume=True)
    assert report['status'] == 'execution_failed' and len(calls) == count
    report = run(template, plan(2), tmp_path, registry, resume=True, retry_failed=True)
    assert report['status'] == 'completed' and report['metrics']['execution_failures'] == 1
    assert report['metrics']['model_errors'] == 1
    # The original accepted plan survives the failed NPC response.
    assert sum(p['response_format']['json_schema']['name'] == 'SceneTurnPlan' for p in calls) == 2


def test_committed_journal_survives_missing_report_checkpoint(template, tmp_path):
    registry, calls = adapter()
    report = run(template, plan(), tmp_path, registry, max_steps=1)
    report['steps'][0] = {'id': 'turn_0', 'status': 'running', 'scored': False}
    (tmp_path / 'run/report.json').write_text(json.dumps(report))
    count = len(calls)
    report = run(template, plan(), tmp_path, registry, resume=True, max_steps=1)
    assert len(calls) == count and report['metrics']['committed'] == 1
    assert report['steps'][0]['status'] == 'completed'


def test_interrupted_receipt_requires_explicit_retry(template, tmp_path):
    registry, calls = adapter()
    run(template, plan(2), tmp_path, registry, max_steps=1)
    from roleplay_world.contracts import ActionCommand
    store = Store(tmp_path / 'run/data')
    campaign = store.campaigns['playtest_campaign']
    store.accept(campaign['id'], campaign['main_branch'], 'playtest', ActionCommand(
        action_id='playtest_0001', expected_world_version=1, **plan(2)['steps'][1]['command']))
    store.close()
    count = len(calls)
    report = run(template, plan(2), tmp_path, registry, resume=True)
    assert report['status'] == 'execution_failed' and len(calls) == count
    report = run(template, plan(2), tmp_path, registry, resume=True, retry_failed=True)
    assert report['status'] == 'completed'


def test_invalid_assertions_and_future_probes_fail_before_calls(template, tmp_path):
    registry, calls = adapter()
    p = plan(1)
    p['steps'][0]['expect'] = {'$ref': 'https://example.invalid/private'}
    with pytest.raises(ValueError):
        run(template, p, tmp_path, registry)
    p['steps'][0].pop('expect')
    p['steps'][0]['recalls'] = [{'query': 'test', 'world_version': 2}]
    with pytest.raises(ValueError):
        run(template, p, tmp_path, registry)
    assert not calls and not (tmp_path / 'run').exists()


def test_cancelled_probe_resumes_committed_action_without_repeating_it(template, tmp_path):
    async def scenario():
        registry, calls = adapter()
        entered = asyncio.Event()
        embeddings = []
        async def embed(config, payload, headers):
            embeddings.append(payload)
            if len(embeddings) == 1:
                entered.set()
                await asyncio.Event().wait()
            return {'model': 'embedding-fixture', 'vectors': [[1., 0.] for _ in payload['input']]}
        registry.register(Engine('embed_fixture', frozenset({'embed'}), embed))
        config = {**CONFIG, 'providers': {'memory': {'backend': 'embed_fixture'}},
                  'bindings': {'memory_embedding': {'provider': 'memory', 'model': 'embedding-fixture'}},
                  'memory_policy': {'mode': 'hybrid'}}
        p = {'steps': [{'id': 'note', 'command': {'mode': 'ooc', 'text': 'Remember.',
                      'note_record': {'id': 'bell', 'text': 'The bell is stored in the chest.'}},
                       'recalls': [{'query': 'bell'}]}]}
        options = {'config': config, 'output': tmp_path / 'run', 'registry': registry}
        task = asyncio.create_task(playtest(template, p, **options))
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        saved = json.loads((tmp_path / 'run/report.json').read_text())
        assert saved['status'] == 'interrupted' and saved['metrics']['committed'] == 1
        report = await playtest(template, p, resume=True, **options)
        assert report['status'] == 'completed' and report['replay']['world_version'] == 1
        assert not calls and len(embeddings) == 2
    asyncio.run(scenario())
