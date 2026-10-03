"""Freeze twelve illustrative module tasks from the packaged Fogharbor world.

Uses the runtime prompts, projections and scene schemas without opening a store.
Planner assertions are automatic; dialogue and prose are retained for human review.
"""

import argparse
import json
from importlib.resources import files
from pathlib import Path

from roleplay_world import prompts
from roleplay_world.contracts import Narration
from roleplay_world.evaluation import prepare_cases
from roleplay_world.planning import actor_schema, choices, plan_schema
from roleplay_world.world import initial_state, model_view, npc_context


def make_cases():
    template = json.loads(files('roleplay_world').joinpath('builtin/fogharbor.json').read_text())
    state = initial_state(template, 'Traveler')
    player = state['player']
    destination = state['locations'][state['actor_states'][player]['location_id']]['exits'][0]['to']
    destination_name = state['locations'][destination]['name']
    languages = {
        'en': ('English', f'I walk to {destination_name}.', 'Captain, what does your boat need for repairs?'),
        'zh-CN': ('简体中文', f'我走到{destination_name}。', '船长，修船需要什么？'),
        'ja': ('日本語', f'{destination_name}へ歩いていきます。', '船長、船の修理には何が必要ですか？'),
    }
    cases = []
    for locale, (language, move, talk) in languages.items():
        instruction = f'\nWrite free-text output fields in {language}. Keep canonical IDs unchanged.'
        for mode, text in [('act', move), ('say', talk)]:
            command = {'mode': mode, 'text': text}
            context = {
                'player_input': text, 'mode': mode, 'player_view': model_view(state, player, query=text),
                'locations': list(state['locations'].values()), 'mechanics': template['mechanics'],
                'story_outline': template.get('outline', []), 'clocks': list(state['clocks'].values()),
                'item_holders': {key: value['holder_id'] for key, value in state['items'].items()},
                'facts': list(state['facts'].values()),
                'actor_locations': {key: value['location_id'] for key, value in state['actor_states'].items()},
                'allowed_operations': choices(state, mode, player)[0],
            }
            expect = {'properties': {'operations': {'minItems': 1, 'maxItems': 1, 'items': {
                'properties': {'kind': {'const': 'move'}, 'target_id': {'const': destination}},
                'required': ['kind', 'target_id']}}}, 'required': ['operations']} if mode == 'act' else {
                    'properties': {'operations': {'maxItems': 0},
                                   'speakers': {'contains': {'const': 'npc_captain'}}},
                    'required': ['operations', 'speakers']}
            cases.append({'id': f'planner_{mode}_{locale}', 'role': 'game_master',
                          'system': prompts.GM + instruction, 'data': context,
                          'output_schema': plan_schema(state, command).model_json_schema(), 'expect': expect})
        context = npc_context(state, 'npc_captain', talk, [], player)
        context.update(current_observed_effects=[], current_roll=None, invitation=None, audible_replies=[])
        cases.append({'id': f'captain_{locale}', 'role': 'character_actor', 'system': prompts.NPC + instruction,
                      'data': context, 'output_schema': actor_schema(state, 'npc_captain', []).model_json_schema()})
        cases.append({'id': f'narrator_{locale}', 'role': 'narrator', 'system': prompts.NARRATOR + instruction,
                      'data': {'player_input': talk, 'mode': 'say',
                               'player_view': {k: v for k, v in model_view(state, player).items() if k != 'memories'},
                               'effects': [], 'committed_dialogue': [], 'roll': None},
                      'output_schema': Narration.model_json_schema()})
    return prepare_cases(cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cases = make_cases()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        for case in cases:
            handle.write(case.model_dump_json(exclude_none=True) + '\n')
    print(f'Wrote {len(cases)} cases to {args.output}')


if __name__ == '__main__':
    main()
