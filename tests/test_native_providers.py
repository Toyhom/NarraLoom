"""Protocol fixtures; these tests make no commercial-provider requests."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files

import httpx
import pytest

from roleplay_world.contracts import ActionCommand, DomainError, TurnPlan
from roleplay_world.gateway import ModelGateway
from roleplay_world.journal import digest
from roleplay_world.runtime import Runtime
from roleplay_world.settings import ProviderSettings, Settings
from roleplay_world.store import Store

BACKENDS = ('openai-responses', 'anthropic')


def response_events(text='{"intent":"Wait"}', terminal=True):
    result = [{'type': 'response.reasoning_summary_text.delta', 'delta': 'private reasoning'},
              {'type': 'response.output_text.delta', 'delta': text}]
    if terminal:
        result.append({'type': 'response.completed', 'response': {
            'status': 'completed', 'model': 'resolved-model', 'usage': {'input_tokens': 12, 'output_tokens': 5},
            'output': [{'type': 'reasoning', 'summary': []}, {'type': 'message', 'role': 'assistant',
                        'status': 'completed', 'content': [{'type': 'output_text', 'text': text}]}]}})
    return result


def message_events(text='{"intent":"Wait"}', terminal=True, tool=False):
    block = {'type': 'tool_use', 'name': 'emit_result', 'id': 'result-1', 'input': {}} if tool else {'type': 'text', 'text': ''}
    delta = {'type': 'input_json_delta', 'partial_json': text} if tool else {'type': 'text_delta', 'text': text}
    result = [
        {'type': 'message_start', 'message': {'role': 'assistant', 'model': 'resolved-model', 'content': [],
            'usage': {'input_tokens': 12, 'output_tokens': 1, 'cache_creation_input_tokens': 3, 'cache_read_input_tokens': 4}}},
        {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': ''}},
        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': 'private reasoning'}},
        {'type': 'content_block_stop', 'index': 0},
        {'type': 'content_block_start', 'index': 1, 'content_block': block},
        {'type': 'content_block_delta', 'index': 1, 'delta': delta},
        {'type': 'content_block_stop', 'index': 1},
        {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use' if tool else 'end_turn'}, 'usage': {'output_tokens': 5}},
    ]
    if terminal:
        result.append({'type': 'message_stop'})
    return result


def wire(events):
    return ''.join('data: ' + json.dumps(e, ensure_ascii=False) + '\r\n\r\n' for e in events).encode()


def provider(tmp_path, monkeypatch, backend, handler, **options):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    return ModelGateway({'default': {'backend': backend, 'url': 'https://provider.invalid/v1',
        'model': 'requested-model', 'api_key': 'fixture-private-key', **options}}, tmp_path / 'traces')


def generate(gateway, budget=None):
    return gateway.generate('game_master', 'Return JSON', {'text': '待つ'}, TurnPlan, 'protocol',
                            budget if budget is not None else {'calls': 0, 'repairs': 0, 'traces': []})


@pytest.mark.parametrize('backend', BACKENDS)
@pytest.mark.parametrize('mode', ('schema', 'object', 'prompt'))
def test_request_and_complete_response(tmp_path, monkeypatch, backend, mode):
    seen = []

    def handler(request):
        body = json.loads(request.content); seen.append(body)
        assert body['model'] == 'requested-model' and body['stream'] is True
        assert 'temperature' not in body and 'stream_options' not in body and 'response_format' not in body
        if backend == 'anthropic':
            assert request.url.path == '/v1/messages'
            assert request.headers['x-api-key'] == 'fixture-private-key' and 'authorization' not in request.headers
            assert request.headers['anthropic-version'] == '2023-06-01'
            assert 'Schema' in body['system'] and body['messages'][0]['role'] == 'user'
            assert body['max_tokens'] == 1800
            if mode == 'schema':
                assert body['tools'][0]['input_schema'] == TurnPlan.model_json_schema()
                assert body['tool_choice']['name'] == 'emit_result'
            else:
                assert 'tools' not in body
            items = message_events(tool=mode == 'schema')
        else:
            assert request.url.path == '/v1/responses'
            assert request.headers['authorization'] == 'Bearer fixture-private-key' and 'x-api-key' not in request.headers
            assert 'Schema' in body['instructions'] and body['input'][0]['role'] == 'user'
            assert body['max_output_tokens'] == 1800 and 'max_tokens' not in body
            if mode == 'schema':
                assert body['text']['format']['schema'] == TurnPlan.model_json_schema()
                assert body['text']['format']['strict'] is False
            elif mode == 'object':
                assert body['text']['format'] == {'type': 'json_object'}
            else:
                assert 'text' not in body
            items = response_events()
        return httpx.Response(200, content=wire(items))

    gateway = provider(tmp_path, monkeypatch, backend, handler, max_tokens=1800, generation={'temperature': None},
                       json_schema=mode == 'schema', json_object=mode == 'object')
    budget = {'calls': 0, 'repairs': 0, 'traces': []}
    assert asyncio.run(generate(gateway, budget)).intent == 'Wait'
    assert len(seen) == 1 and budget['traces'][0]['response_model'] == 'resolved-model'
    usage = budget['traces'][0]['usage']
    assert usage['input_tokens'] == 12 and usage['output_tokens'] == 5
    if backend == 'anthropic':
        assert usage['prompt_tokens'] == 19 and usage['completion_tokens'] == 5
    raw = next((tmp_path / 'traces').glob('*.json')).read_text()
    assert 'fixture-private-key' not in raw and 'private reasoning' not in raw


@pytest.mark.parametrize('backend', BACKENDS)
def test_native_schema_repairs_keep_conversation(tmp_path, monkeypatch, backend):
    requests = []

    def handler(request):
        body = json.loads(request.content); requests.append(body)
        text = '{"intent":"Wait","operations":[{"kind":"say"}]}' if len(requests) == 1 else '{"intent":"Wait"}'
        events = response_events(text) if backend == 'openai-responses' else message_events(text, tool=True)
        return httpx.Response(200, content=wire(events))

    gateway = provider(tmp_path, monkeypatch, backend, handler, json_schema=True)
    budget = {'calls': 0, 'repairs': 0, 'traces': []}
    assert asyncio.run(generate(gateway, budget)).operations == []
    assert budget['calls'] == 2 and budget['repairs'] == 1
    history = requests[1]['input' if backend == 'openai-responses' else 'messages']
    assert history[-2]['role'] == 'assistant' and 'say' in history[-2]['content']
    assert 'literal_error' in history[-1]['content']


@pytest.mark.parametrize('backend', BACKENDS)
@pytest.mark.parametrize('failure', ('truncated', 'limit', 'refusal', 'error', 'malformed', 'oversized', 'wire_limit'))
def test_native_failures_are_traced_and_never_repaired(tmp_path, monkeypatch, backend, failure):
    events = response_events() if backend == 'openai-responses' else message_events()
    expected = {'truncated': 'model_incomplete', 'limit': 'model_incomplete', 'refusal': 'model_refusal',
                'error': 'model_error', 'malformed': 'model_protocol', 'oversized': 'model_output_limit',
                'wire_limit': 'model_output_limit'}[failure]
    if failure == 'truncated':
        events.pop()
    elif failure in {'limit', 'refusal'}:
        if backend == 'anthropic':
            events[-2]['delta']['stop_reason'] = 'max_tokens' if failure == 'limit' else 'refusal'
        elif failure == 'limit':
            events[-1] = {'type': 'response.incomplete'}
        else:
            events[-1] = {'type': 'response.refusal.delta', 'delta': 'refused'}
    elif failure == 'error':
        events = [{'type': 'error', 'error': {'message': 'fixture-private-key'}}]
    data = b'data: not-json\n\n' if failure == 'malformed' else wire(events)
    options = {'output_chars': 2} if failure == 'oversized' else {'stream_bytes': 10} if failure == 'wire_limit' else {}
    gateway = provider(tmp_path, monkeypatch, backend, lambda request: httpx.Response(200, content=data), **options)
    budget = {'calls': 0, 'repairs': 0, 'traces': []}
    with pytest.raises(DomainError) as error:
        asyncio.run(generate(gateway, budget))
    assert error.value.code == expected
    assert budget['calls'] == 1 and budget['repairs'] == 0
    assert budget['traces'][0]['error'] == expected
    assert 'fixture-private-key' not in json.dumps(budget['traces'])


@pytest.mark.parametrize('backend', BACKENDS)
def test_cancel_closes_response_and_traces_cancellation(tmp_path, monkeypatch, backend):
    async def check():
        waiting = asyncio.Event()

        class Stream(httpx.AsyncByteStream):
            closed = False

            async def __aiter__(self):
                yield wire(response_events(terminal=False) if backend == 'openai-responses' else message_events(terminal=False))
                waiting.set()
                await asyncio.Event().wait()

            async def aclose(self):
                self.closed = True

        stream = Stream()
        gateway = provider(tmp_path, monkeypatch, backend, lambda req: httpx.Response(200, stream=stream))
        budget = {'calls': 0, 'repairs': 0, 'traces': []}
        task = asyncio.create_task(generate(gateway, budget))
        await waiting.wait(); task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed and budget['traces'][0]['status'] == 'cancelled'

    asyncio.run(check())


@pytest.mark.parametrize('backend', BACKENDS)
def test_truncated_narration_leaves_world_unchanged(tmp_path, monkeypatch, backend):
    events = response_events('{"text":"Done","suggestions":[]}', terminal=False) if backend == 'openai-responses' else message_events('{"text":"Done","suggestions":[]}', terminal=False)
    gateway = provider(tmp_path, monkeypatch, backend, lambda req: httpx.Response(200, content=wire(events)))
    store = Store(tmp_path / 'store')
    try:
        template = json.loads(files('roleplay_world').joinpath('builtin/fogharbor.json').read_text())
        campaign = store.create_campaign('owner', template, 'Traveler'); branch = campaign['main_branch']
        before = digest(store.branches[branch]['state'])
        command = ActionCommand(action_id='native-truncated', expected_world_version=0, mode='wait', text='Wait')
        action, _ = store.accept(campaign['id'], branch, 'owner', command)
        asyncio.run(Runtime(store, gateway).run(action['id']))
        assert store.actions[action['id']]['status'] == 'failed'
        assert digest(store.branches[branch]['state']) == before
    finally:
        store.close()


def test_protocol_change_drops_credentials_and_provider_options(tmp_path):
    settings = Settings(tmp_path / 'settings', {})
    settings.save('owner', ProviderSettings(url='https://provider.invalid/v1', model='one', api_key='private'))
    settings.save('owner', ProviderSettings(backend='anthropic', url='https://provider.invalid/v1', model='two', omit_temperature=True))
    cfg = settings.effective('owner')['default']
    assert cfg['api_key'] == '' and cfg['extra_body'] == {} and cfg['generation'] == {'temperature': None}
    assert settings.public('owner')['backend'] == 'anthropic'
    gateway = ModelGateway({'default': {'url': 'https://provider.invalid/v1', 'model': 'one', 'api_key': 'private',
                                       'extra_body': {'thinking': {'type': 'disabled'}}},
                            'roles': {'narrator': {'backend': 'anthropic'}}}, tmp_path / 'traces')
    config = gateway.role_config('narrator')
    assert 'api_key' not in config and 'extra_body' not in config
    assert gateway.auth_headers(config) == {'anthropic-version': '2023-06-01'}


@pytest.mark.parametrize('key', ('model', 'messages', 'stream', 'response_format', 'input', 'tools'))
def test_provider_extensions_cannot_override_result_contract(tmp_path, key):
    gateway = ModelGateway({'default': {'model': 'x', 'url': 'https://provider.invalid', 'extra_body': {key: 'override'}}}, tmp_path)
    with pytest.raises(DomainError) as error:
        asyncio.run(generate(gateway))
    assert error.value.code == 'model_config'


@pytest.mark.parametrize('fault', ('wrong_tool', 'duplicate_tool', 'open_block', 'wrong_delta', 'missing_start', 'bad_usage'))
def test_messages_rejects_invalid_result_sequences(tmp_path, monkeypatch, fault):
    items = message_events(tool=True)
    if fault == 'wrong_tool':
        items[4]['content_block']['name'] = 'another_tool'
    elif fault == 'duplicate_tool':
        items.insert(7, {'type': 'content_block_start', 'index': 2,
                         'content_block': {'type': 'tool_use', 'name': 'emit_result', 'input': {}}})
    elif fault == 'open_block':
        items.pop(6)
    elif fault == 'wrong_delta':
        items[5]['delta'] = {'type': 'text_delta', 'text': '{"intent":"Wait"}'}
    elif fault == 'missing_start':
        items.pop(0)
    else:
        items[0]['message']['usage']['input_tokens'] = '12'
    gateway = provider(tmp_path, monkeypatch, 'anthropic', lambda req: httpx.Response(200, content=wire(items)), json_schema=True)
    with pytest.raises(DomainError) as error:
        asyncio.run(generate(gateway))
    assert error.value.code == 'model_protocol'


@pytest.mark.parametrize('fault', ('changed_text', 'missing_message', 'tool_output', 'unfinished_message'))
def test_responses_requires_completed_matching_text(tmp_path, monkeypatch, fault):
    items = response_events()
    output = items[-1]['response']['output']
    if fault == 'changed_text':
        output[-1]['content'][0]['text'] = '{"intent":"Run"}'
    elif fault == 'missing_message':
        output.pop()
    elif fault == 'tool_output':
        output[-1] = {'type': 'function_call', 'name': 'unexpected'}
    else:
        output[-1]['status'] = 'incomplete'
    gateway = provider(tmp_path, monkeypatch, 'openai-responses', lambda req: httpx.Response(200, content=wire(items)))
    with pytest.raises(DomainError) as error:
        asyncio.run(generate(gateway))
    assert error.value.code == 'model_protocol'


@pytest.mark.parametrize('backend', BACKENDS)
def test_utf8_stream_boundaries_and_comments(tmp_path, monkeypatch, backend):
    items = response_events('{"intent":"調べる / 查看"}') if backend == 'openai-responses' else message_events('{"intent":"調べる / 查看"}')

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for value in b': keepalive\r\n\r\n' + wire(items):
                yield bytes([value])

    gateway = provider(tmp_path, monkeypatch, backend, lambda req: httpx.Response(200, stream=Stream()))
    assert asyncio.run(generate(gateway)).intent == '調べる / 查看'


@pytest.mark.parametrize('backend', BACKENDS)
def test_native_protocol_over_real_http(tmp_path, backend):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            seen.append((self.path, dict(self.headers), payload))
            items = response_events('{"intent":"調べる / 查看"}') if backend == 'openai-responses' else message_events('{"intent":"調べる / 查看"}', tool=True)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            data = wire(items)
            for start in range(0, len(data), 7):
                chunk = data[start:start + 7]
                self.wfile.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
                self.wfile.flush()
            self.wfile.write(b'0\r\n\r\n'); self.wfile.flush()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        gateway = ModelGateway({'default': {'backend': backend, 'url': f'http://127.0.0.1:{server.server_port}/v1',
            'model': 'fixture', 'json_schema': True, 'api_key': 'wire-key'}}, tmp_path)
        assert asyncio.run(generate(gateway)).intent == '調べる / 查看'
        path, headers, payload = seen[0]
        assert path == ('/v1/responses' if backend == 'openai-responses' else '/v1/messages')
        assert headers['Authorization' if backend == 'openai-responses' else 'x-api-key'] == ('Bearer wire-key' if backend == 'openai-responses' else 'wire-key')
        assert payload['stream'] is True
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=5)


def test_messages_keeps_unreported_usage_distinct_from_zero(tmp_path, monkeypatch):
    items = message_events()
    items[0]['message'].pop('usage')
    items[-2].pop('usage')
    gateway = provider(tmp_path, monkeypatch, 'anthropic', lambda req: httpx.Response(200, content=wire(items)))
    budget = {'calls': 0, 'repairs': 0, 'traces': []}
    asyncio.run(generate(gateway, budget))
    assert budget['traces'][0]['usage'] is None
