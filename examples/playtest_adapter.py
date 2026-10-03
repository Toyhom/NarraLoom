"""Installed Python playtest example with a deterministic fixture adapter."""

import argparse
import asyncio
import json
from importlib.resources import files
from pathlib import Path

from roleplay_world.engines import Engine, builtin_engines
from roleplay_world.playtesting import playtest


async def run(output):
    calls = []
    async def invoke(config, payload, headers):
        name = payload['response_format']['json_schema']['name']
        calls.append(name)
        values = {'SceneTurnPlan': {'intent': 'Give the tools', 'operations': [
            {'kind': 'give', 'target_id': 'npc_captain', 'item_id': 'item_tools'}], 'speakers': ['npc_captain']},
                  'SceneActorReply': {'text': 'I accept the tools.', 'reaction': 'accept'},
                  'Narration': {'text': 'The captain receives the tools.', 'suggestions': []}}
        return {'model': 'playtest-fixture', 'text': json.dumps(values[name])}
    registry = builtin_engines()
    registry.register(Engine('playtest_fixture', frozenset({'generate'}), invoke))
    template = json.loads(files('roleplay_world').joinpath('builtin/fogharbor.json').read_text())
    config = {'default': {'backend': 'playtest_fixture', 'model': 'playtest-fixture', 'json_schema': True}}
    plan = {'steps': [
        {'id': 'give_tools', 'command': {'mode': 'act', 'text': 'I give the tools to the captain.'},
         'expect': {'properties': {'view': {'properties': {'inventory': {'not': {
             'contains': {'properties': {'id': {'const': 'item_tools'}}, 'required': ['id']}}}}}}}},
        {'id': 'note', 'command': {'mode': 'ooc', 'text': 'Record my journal.',
                                 'note_record': {'id': 'tools_note', 'text': 'I gave the tools to the captain.'}},
         'recalls': [{'query': 'tools', 'expect': {'contains': {
             'properties': {'source_id': {'const': 'tools_note'}}, 'required': ['source_id']}}}]},
    ]}
    options = {'config': config, 'output': output, 'registry': registry}
    first = await playtest(template, plan, max_steps=1, **options)
    assert first['status'] == 'checkpointed'
    count = len(calls)
    completed = await playtest(template, plan, resume=True, **options)
    assert completed['status'] == 'completed' and len(calls) == count
    again = await playtest(template, plan, resume=True, **options)
    assert again['metrics'] == completed['metrics'] and len(calls) == count
    print(json.dumps(completed['metrics'], indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(run(parser.parse_args().output))
