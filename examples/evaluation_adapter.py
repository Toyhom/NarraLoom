"""Evaluate a native Python engine with two small contract fixtures.

Replace invoke() with your model integration and label its revision in CONFIG.
This example uses authored constant outputs to demonstrate the evaluation API.
"""

import argparse
import asyncio
import json
from pathlib import Path

from roleplay_world.engines import Engine, builtin_engines
from roleplay_world.evaluation import evaluate


async def invoke(config, payload, headers):
    if 'questions' in payload:
        return {'model': config['model'], 'answers': {'exit': {
            'type': 'choice', 'choice': 'dock', 'probabilities': {'dock': 1.0, 'inn': 0.0}}}}
    return {'model': config['model'], 'text': '{"destination":"dock"}'}


CASES = [
    {'id': 'plan_destination', 'role': 'game_master', 'system': 'Select the requested destination.',
     'data': {'input': 'I walk to the dock.', 'exits': ['dock', 'inn']},
     'output_schema': {'type': 'object', 'properties': {'destination': {'enum': ['dock', 'inn']}},
                       'required': ['destination'], 'additionalProperties': False},
     'expect': {'properties': {'destination': {'const': 'dock'}}, 'required': ['destination']}},
    {'id': 'decide_destination', 'role': 'action_router', 'kind': 'decide',
     'decision': {'state': 'I walk to the dock.', 'questions': {'exit': {
         'type': 'choice', 'instructions': 'Select the requested destination.',
         'criteria': {'dock': 'Dock', 'inn': 'Inn'}}}},
     'expect': {'properties': {'exit': {'properties': {'choice': {'const': 'dock'}}, 'required': ['choice']}},
                'required': ['exit']}},
]

CONFIG = {'providers': {'native': {'backend': 'evaluation_example', 'revision': 'fixture-1'}},
          'bindings': {role: {'provider': 'native', 'model': 'authored-fixture'}
                       for role in ('game_master', 'action_router')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    registry = builtin_engines()
    registry.register(Engine('evaluation_example', frozenset({'generate', 'decide'}), invoke))
    report = asyncio.run(evaluate(CASES, config=CONFIG, registry=registry, output=args.output))
    assert report['metrics']['overall']['passed'] == 2
    print(json.dumps(report['metrics'], indent=2))


if __name__ == '__main__':
    main()
