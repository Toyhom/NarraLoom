import asyncio
import copy
import json

import httpx
import pytest

from roleplay_world import evaluation as ev
from roleplay_world.cli import main
from roleplay_world.engines import Engine, EngineRegistry


def case(name='choice', **overrides):
    return {'id': name, 'role': 'game_master', 'system': 'Choose from the visible options.',
            'data': {'options': ['left', 'right']},
            'output_schema': {'type': 'object', 'properties': {'choice': {'type': 'string'}},
                              'required': ['choice'], 'additionalProperties': False},
            'expect': {'properties': {'choice': {'const': 'left'}}, 'required': ['choice']}, **overrides}


def engine(responses):
    seen = []
    async def invoke(config, payload, headers):
        seen.append(copy.deepcopy(payload))
        result = responses[len(seen) - 1]
        if isinstance(result, BaseException):
            raise result
        return copy.deepcopy(result)
    registry = EngineRegistry()
    registry.register(Engine('fixture', frozenset({'generate', 'decide'}), invoke))
    return registry, seen


def response(value='left', usage=None):
    return {'model': 'actual-fixture', 'text': json.dumps({'choice': value}), 'usage': usage}


CONFIG = {'default': {'backend': 'fixture', 'model': 'fixture', 'revision': 'test-1'}}


def run(tmp_path, cases, responses, **kwargs):
    registry, seen = engine(responses)
    report = asyncio.run(ev.evaluate(cases, config=CONFIG, output=tmp_path / 'run', registry=registry, **kwargs))
    return report, seen


def test_gold_is_separate_from_schema_and_repair(tmp_path):
    c = case(expect={'properties': {'choice': {'const': 'SECRET_GOLD_68'}}, 'required': ['choice']})
    report, seen = run(tmp_path, [c], [response(42), response('right')], max_repairs=1)
    assert len(seen) == 2 and 'SECRET_GOLD_68' not in json.dumps(seen)
    assert 'SECRET_GOLD_68' not in ''.join(p.read_text() for p in (tmp_path / 'run/traces').glob('*.json'))
    row = report['rows'][0]
    assert row['status'] == 'assertion_failed' and row['schema_valid'] and row['passed'] is False
    assert row['repairs'] == 1 and row['calls'] == 2
    assert report['metrics']['overall']['pass_rate'] == 0
    assert row['traces'][0]['status'] == 'invalid_output'


def test_schema_valid_wrong_answer_does_not_trigger_gold_repair(tmp_path):
    report, seen = run(tmp_path, [case()], [response('right')], max_repairs=2)
    assert len(seen) == 1 and report['rows'][0]['status'] == 'assertion_failed'


def test_failure_inclusive_metrics_and_usage(tmp_path):
    cases = [case(str(i), expect=None if i == 3 else case()['expect']) for i in range(4)]
    report, _ = run(tmp_path, cases, [response(7, {'prompt_tokens': 9, 'completion_tokens': 2}),
                                    httpx.ConnectError('PRIVATE provider diagnostic'),
                                    response('left', {'input_tokens': 3}),
                                    response('left', {'prompt_tokens': -1, 'completion_tokens': 2})])
    stats = report['metrics']['overall']
    assert stats['cases'] == stats['attempted'] == stats['calls'] == 4
    assert stats['schema_valid_rate'] == .5 and stats['pass_rate'] == 1 / 3
    assert stats['errors'] == 2 and stats['unscored'] == 1
    assert stats['reported_input_tokens'] == 12 and stats['reported_output_tokens'] == 2
    assert stats['calls_without_usage'] == 3 and stats['calls_incomplete'] == 0
    assert 'PRIVATE' not in json.dumps(report)
    assert stats['response_models'] == ['actual-fixture']
    assert report['rows'][3]['passed'] is None
    ev.compare(report, report)


def test_decision_contract_is_used(tmp_path):
    decision = {'id': 'exit', 'role': 'action_router', 'kind': 'decide',
                'decision': {'state': 'I walk to the dock.', 'questions': {
                    'destination': {'type': 'choice', 'instructions': 'Choose the exit.',
                                    'criteria': {'dock': 'Dock', 'inn': 'Inn'}}}},
                'expect': {'properties': {'destination': {'properties': {'choice': {'const': 'dock'}}}}}}
    raw = {'model': 'decision-fixture', 'answers': {'destination': {
        'type': 'choice', 'choice': 'dock', 'probabilities': {'dock': .9, 'inn': .1}}},
        'usage': {'input_tokens': 6, 'output_tokens': 0}}
    registry, seen = engine([raw])
    config = {'providers': {'local': {'backend': 'fixture'}},
              'bindings': {'action_router': {'provider': 'local', 'model': 'decision'}}}
    report = asyncio.run(ev.evaluate([decision], config=config, output=tmp_path / 'run', registry=registry))
    assert report['rows'][0]['status'] == 'passed'
    assert seen[0]['questions'] == decision['decision']['questions']
    assert 'expect' not in seen[0]
    assert report['metrics']['overall']['reported_input_tokens'] == 6


@pytest.mark.parametrize('override', [
    {'role': 'nonexistent'},
    {'output_schema': {'type': 'mistake'}},
    {'output_schema': {'$ref': 'https://example.invalid/schema'}},
    {'output_schema': {'$ref': '#/missing'}},
    {'output_schema': {'$ref': '#/custom', 'custom': {'$ref': 'file:///secret'}}},
    {'output_schema': {'$defs': {'x': {'$id': 'https://example.invalid'}}}},
    {'output_schema': {'$schema': 'http://json-schema.org/draft-07/schema#'}},
    {'data': {'value': float('nan')}},
])
def test_invalid_cases_fail_before_calls(tmp_path, override):
    registry, seen = engine([])
    with pytest.raises(ValueError):
        asyncio.run(ev.evaluate([case(**override)], config=CONFIG, output=tmp_path / 'run', registry=registry))
    assert not seen and not (tmp_path / 'run').exists()


def test_schema_literals_references_and_mutable_cases():
    literal = {'type': 'object', 'const': {'$ref': 'literal text'}}
    ev.FrozenSchema(literal).model_validate({'$ref': 'literal text'})
    schema = {'$defs': {'value': {'type': 'integer'}}, '$ref': '#/$defs/value'}
    assert ev.FrozenSchema(schema).model_validate(3) == 3
    with pytest.raises(ValueError):
        ev.FrozenSchema(schema).model_validate('3')
    c = ev.EvaluationCase.model_validate(case())
    c.id = '../changed'
    with pytest.raises(ValueError):
        ev.prepare_cases([c])
    with pytest.raises(ValueError):
        ev.prepare_cases([case(), case()])


@pytest.mark.parametrize('config', [
    {}, {'default': {'model': 'fixture', 'backend': 'missing'}},
    {'bindings': {'game_master': {'provider': 'absent'}}},
    {'default': {'model': 'fixture', 'backend': 'fixture', 'api_key_file': 'missing'}},
])
def test_preflight_configuration(tmp_path, config):
    registry, seen = engine([])
    with pytest.raises(ValueError):
        asyncio.run(ev.evaluate([case()], config=config, output=tmp_path / 'run', registry=registry,
                                secrets_root=tmp_path / 'secrets'))
    assert not seen


def test_cancel_resume_skips_interrupted_and_completed(tmp_path):
    registry, seen = engine([asyncio.CancelledError(), response()])
    cases = [case('first'), case('second')]
    options = {'config': CONFIG, 'output': tmp_path / 'run', 'registry': registry}
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ev.evaluate(cases, **options))
    saved = json.loads((tmp_path / 'run/report.json').read_text())
    assert saved['status'] == 'interrupted'
    assert [row['status'] for row in saved['rows']] == ['interrupted', 'pending']
    report = asyncio.run(ev.evaluate(cases, resume=True, **options))
    assert len(seen) == 2 and report['status'] == 'completed'
    assert report['metrics']['overall']['pass_rate'] == .5
    asyncio.run(ev.evaluate(cases, resume=True, **options))
    assert len(seen) == 2
    with pytest.raises(ValueError, match='changed'):
        asyncio.run(ev.evaluate([case('first'), case('second', system='Changed')], resume=True, **options))
    changed = {**options, 'config': {'default': {**CONFIG['default'], 'model': 'changed'}}}
    with pytest.raises(ValueError, match='changed'):
        asyncio.run(ev.evaluate(cases, resume=True, **changed))


def test_hard_crash_recovers_traces_without_repeating_call(tmp_path):
    report, _ = run(tmp_path, [case()], [response(usage={'prompt_tokens': 5, 'completion_tokens': 2})])
    report['status'] = 'running'
    row = report['rows'][0]
    for field in ('duration_s', 'traces', 'output', 'calls', 'repairs', 'assertions'):
        row.pop(field, None)
    row.update(status='running', schema_valid=False, passed=None)
    (tmp_path / 'run/report.json').write_text(json.dumps(report))
    registry, seen = engine([])
    recovered = asyncio.run(ev.evaluate([case()], config=CONFIG, output=tmp_path / 'run', registry=registry, resume=True))
    assert not seen and recovered['rows'][0]['status'] == 'interrupted'
    assert recovered['metrics']['overall']['calls'] == 1
    assert recovered['metrics']['overall']['reported_input_tokens'] == 5
    assert recovered['metrics']['overall']['calls_incomplete'] == 1
    assert recovered['metrics']['overall']['latency_p50_s'] is None


def test_exclusive_writer_and_output(tmp_path):
    output = tmp_path / 'run'
    with ev._writer(output, False), pytest.raises(ValueError, match='owns'), ev._writer(output, True):
        pytest.fail('second writer acquired lock')
    with pytest.raises(FileExistsError), ev._writer(output, False):
        pytest.fail('existing run was overwritten')


def test_storage_failure_stops_suite(tmp_path, monkeypatch):
    registry, seen = engine([response()])
    def fail(*args):
        raise OSError('disk failed')
    monkeypatch.setattr(ev.ModelGateway, 'record_trace', fail)
    with pytest.raises(OSError):
        asyncio.run(ev.evaluate([case('first'), case('second')], config=CONFIG,
                                output=tmp_path / 'run', registry=registry))
    report = json.loads((tmp_path / 'run/report.json').read_text())
    assert len(seen) == 1 and report['status'] == 'interrupted'
    assert report['rows'][0]['error'] == 'storage_error'
    assert report['metrics']['overall']['calls_incomplete'] == 1


def test_comparison_pairs_failures_and_rejects_changed_workload(tmp_path):
    left, _ = run(tmp_path / 'left', [case()], [response('right')])
    right, _ = run(tmp_path / 'right', [case()], [response()])
    result = ev.compare(left, right)
    assert result['improved'] == 1 and result['regressed'] == 0
    corrupt = copy.deepcopy(right)
    corrupt['rows'][0]['status'] = 'pending'
    with pytest.raises(ValueError):
        ev.compare(left, corrupt)
    corrupt = copy.deepcopy(right)
    corrupt['manifest']['workload']['max_repairs'] = 2
    with pytest.raises(ValueError, match='workloads'):
        ev.compare(left, corrupt)
    corrupt = copy.deepcopy(right)
    corrupt['metrics']['overall']['passed'] = 999
    assert ev.compare(left, corrupt)['candidate']['overall']['passed'] == 1


def test_cli_jsonl_exit_codes_and_compare(tmp_path, monkeypatch, capsys):
    suite, config = tmp_path / 'cases.jsonl', tmp_path / 'models.json'
    suite.write_text(json.dumps(case()) + '\n')
    config.write_text(json.dumps({'default': {'url': 'https://model.invalid/v1', 'model': 'fixture'}}))
    selected = 'left'
    def respond(request):
        event = {'model': 'fixture', 'choices': [{'delta': {'content': json.dumps({'choice': selected})}}]}
        return httpx.Response(200, text='data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n')
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(respond)))
    for name, code in [('good', 0), ('bad', 1)]:
        selected = 'left' if name == 'good' else 'right'
        with pytest.raises(SystemExit) as exit_info:
            main(['evaluate', '--cases', str(suite), '--models-config', str(config), '--output', str(tmp_path / name)])
        assert exit_info.value.code == code
    out = tmp_path / 'comparison.json'
    args = ['compare', str(tmp_path / 'bad/report.json'), str(tmp_path / 'good/report.json'), '--output', str(out)]
    main(args)
    assert json.loads(out.read_text())['improved'] == 1
    with pytest.raises(SystemExit) as exit_info:
        main(args)
    assert exit_info.value.code == 2
    suite.write_text('{invalid json}\n')
    with pytest.raises(ValueError, match='line 1'):
        ev.load_cases(suite)
    assert 'improved' in capsys.readouterr().out
