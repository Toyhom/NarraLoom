"""Native Responses and Messages transports for typed generation.

Wire formats follow the OpenAI Responses and Anthropic Messages specifications.
The gateway validates every result against the original application schema.
"""

import codecs
import json

import httpx

from .contracts import DomainError


def fail(code='model_protocol'):
    messages = {
        'model_protocol': 'The provider returned an invalid generation stream',
        'model_incomplete': 'The provider stopped before completing its response',
        'model_refusal': 'The provider declined this generation request',
        'model_error': 'The provider could not complete this generation request',
        'model_output_limit': 'The provider response exceeded its output budget',
    }
    raise DomainError(code, messages[code], 502)


async def events(response, config):
    # Bound all bytes, including reasoning and metadata, before SSE line buffering.
    from .engines import sse_events

    async def lines():
        decoder = codecs.getincrementaldecoder('utf-8')()
        pending, size = '', 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > config.get('stream_bytes', 8 * 1024 * 1024):
                fail('model_output_limit')
            pending += decoder.decode(chunk)
            while '\n' in pending:
                line, pending = pending.split('\n', 1)
                yield line.removesuffix('\r')
        pending += decoder.decode(b'', final=True)
        if pending:
            yield pending.removesuffix('\r')

    try:
        async for data in sse_events(lines()):
            item = json.loads(data)
            if not isinstance(item, dict) or not isinstance(item.get('type'), str):
                fail()
            yield item
    except (UnicodeError, ValueError, TypeError):
        fail()


def bounded(text, config):
    if not isinstance(text, str):
        fail()
    if len(text) > config.get('output_chars', 22000):
        fail('model_output_limit')
    return text


def usage_counts(usage, *, anthropic=False):
    if usage is None:
        return None
    if not isinstance(usage, dict):
        fail()
    usage = dict(usage)
    for key in ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'):
        if key in usage and (type(usage[key]) is not int or usage[key] < 0):
            fail()
    if anthropic:
        usage['prompt_tokens'] = sum(usage.get(k, 0) for k in (
            'input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
        usage['completion_tokens'] = usage.get('output_tokens', 0)
    return usage


def request_options(payload, excluded):
    return {key: value for key, value in payload.items() if key not in excluded and value is not None}


def responses_request(payload):
    body = request_options(payload, {'messages', 'max_tokens', 'stream_options', 'response_format'})
    body.update(
        instructions='\n\n'.join(m['content'] for m in payload['messages'] if m['role'] == 'system'),
        input=[dict(m) for m in payload['messages'] if m['role'] != 'system'],
        max_output_tokens=payload['max_tokens'],
    )
    formatting = payload.get('response_format', {})
    if formatting.get('type') == 'json_schema':
        # Keep defaults/optional fields and dictionaries from application schemas.
        # Provider strict mode has a narrower schema subset; validation is local.
        value = {'type': 'json_schema', **formatting['json_schema'], 'strict': False}
        body['text'] = {**body.get('text', {}), 'format': value}
    elif formatting.get('type') == 'json_object':
        body['text'] = {**body.get('text', {}), 'format': {'type': 'json_object'}}
    return body


def completed_text(response, config):
    if not isinstance(response, dict) or response.get('status') != 'completed':
        fail('model_incomplete')
    output = response.get('output')
    if not isinstance(output, list):
        fail()
    text = ''
    for item in output:
        if not isinstance(item, dict):
            fail()
        if item.get('type') == 'reasoning':
            continue
        if (item.get('type') != 'message' or item.get('role') != 'assistant'
                or item.get('status') != 'completed' or not isinstance(item.get('content'), list)):
            fail()
        for part in item['content']:
            if not isinstance(part, dict):
                fail()
            if part.get('type') == 'refusal':
                fail('model_refusal')
            if part.get('type') != 'output_text':
                fail()
            text = bounded(text + bounded(part.get('text'), config), config)
    if not text:
        fail()
    return text


async def responses_generate(config, payload, headers):
    raw = ''
    async with (
        httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(config.get('timeout_s', 90), connect=5)) as client,
        client.stream('POST', config['url'].rstrip('/') + '/responses',
                      json=responses_request(payload), headers=headers) as response,
    ):
        response.raise_for_status()
        async for item in events(response, config):
            kind = item['type']
            if kind == 'response.output_text.delta':
                raw = bounded(raw + bounded(item.get('delta'), config), config)
            elif kind.startswith('response.refusal.'):
                fail('model_refusal')
            elif kind in {'error', 'response.failed'}:
                fail('model_error')
            elif kind == 'response.incomplete':
                fail('model_incomplete')
            elif kind == 'response.completed':
                result = item.get('response')
                text = completed_text(result, config)
                if raw and raw != text:
                    fail()
                return {'text': text, 'model': result.get('model') or config['model'],
                        'usage': usage_counts(result.get('usage'))}
    fail('model_incomplete')


def messages_request(payload):
    body = request_options(payload, {'messages', 'response_format', 'stream_options'})
    body.update(system='\n\n'.join(m['content'] for m in payload['messages'] if m['role'] == 'system'),
                messages=[dict(m) for m in payload['messages'] if m['role'] != 'system'])
    schema = payload.get('response_format', {}).get('json_schema')
    if schema:
        # Forced result tool accepts ordinary JSON Schema, including optional
        # fields and dictionaries. It serializes a result; no tool is executed.
        body['tools'] = [{'name': 'emit_result', 'description': 'Return the requested structured result',
                          'input_schema': schema['schema']}]
        body['tool_choice'] = {'type': 'tool', 'name': 'emit_result', 'disable_parallel_tool_use': True}
    return body


async def messages_generate(config, payload, headers):
    body = messages_request(payload)
    tool_mode = body.get('tool_choice', {}).get('name') == 'emit_result'
    blocks, started, stop, usage = {}, False, None, {}
    response_model, output_size = config['model'], 0
    async with (
        httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(config.get('timeout_s', 90), connect=5)) as client,
        client.stream('POST', config['url'].rstrip('/') + '/messages', json=body, headers=headers) as response,
    ):
        response.raise_for_status()
        async for item in events(response, config):
            kind = item['type']
            if kind == 'ping':
                continue
            if kind == 'error':
                fail('model_error')
            if kind == 'message_start':
                message = item.get('message')
                if started or not isinstance(message, dict) or message.get('role') != 'assistant':
                    fail()
                started = True
                response_model = message.get('model') or response_model
                usage.update(usage_counts(message.get('usage')) or {})
                continue
            if not started:
                fail()
            if kind == 'content_block_start':
                index, block = item.get('index'), item.get('content_block')
                if type(index) is not int or index != len(blocks) or not isinstance(block, dict) or stop:
                    fail()
                block_type = block.get('type')
                if block_type not in {'text', 'tool_use', 'thinking', 'redacted_thinking'}:
                    fail()
                if block_type == 'tool_use' and (not tool_mode or block.get('name') != 'emit_result'
                                                or any(b['type'] == 'tool_use' for b in blocks.values())):
                    fail()
                text = bounded(block.get('text', '') if block_type == 'text' else '', config)
                blocks[index] = {'type': block_type, 'text': text, 'closed': False, 'input': block.get('input', {})}
                output_size += len(text)
            elif kind in {'content_block_delta', 'content_block_stop'}:
                index = item.get('index')
                if type(index) is not int or index not in blocks or blocks[index]['closed'] or stop:
                    fail()
                block = blocks[index]
                if kind == 'content_block_stop':
                    block['closed'] = True
                else:
                    delta = item.get('delta')
                    if not isinstance(delta, dict):
                        fail()
                    delta_type = delta.get('type')
                    expected = {'text': {'text_delta', 'citations_delta'}, 'tool_use': {'input_json_delta'},
                                'thinking': {'thinking_delta', 'signature_delta'}, 'redacted_thinking': set()}
                    if delta_type not in expected[block['type']]:
                        fail()
                    if delta_type in {'text_delta', 'input_json_delta'}:
                        text = bounded(delta.get('text' if delta_type == 'text_delta' else 'partial_json'), config)
                        block['text'] += text
                        output_size += len(text)
            elif kind == 'message_delta':
                delta = item.get('delta')
                if not isinstance(delta, dict):
                    fail()
                reason = delta.get('stop_reason')
                if reason:
                    if stop or any(not b['closed'] for b in blocks.values()):
                        fail()
                    stop = reason
                usage.update(usage_counts(item.get('usage')) or {})
            elif kind == 'message_stop':
                if stop == 'refusal':
                    fail('model_refusal')
                if stop not in ({'tool_use'} if tool_mode else {'end_turn', 'stop_sequence'}):
                    fail('model_incomplete')
                if any(not b['closed'] for b in blocks.values()):
                    fail()
                chosen = [b for b in blocks.values() if b['type'] == ('tool_use' if tool_mode else 'text')]
                if not chosen:
                    fail()
                text = ''.join(b['text'] or (json.dumps(b['input']) if tool_mode else '') for b in chosen)
                return {'text': bounded(text, config), 'model': response_model,
                        'usage': usage_counts(usage or None, anthropic=True)}
            else:
                fail()
            if output_size > config.get('output_chars', 22000):
                fail('model_output_limit')
    fail('model_incomplete')
