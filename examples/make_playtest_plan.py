"""Write a configurable dialogue-memory trajectory for a native story export.

The English example prompts intentionally paraphrase the final recall question.
Edit the resulting JSON to author actions, languages and assertions for your game.
"""

import argparse
import json
from pathlib import Path

from roleplay_world.playtesting import load_source
from roleplay_world.world import initial_state, present


def memory_plan(template, turns=100):
    if not 20 <= turns <= 1000:
        raise ValueError('Choose 20–1000 turns')
    state = initial_state(template, 'Traveler')
    npc = next((actor for actor in present(state) if state['actors'][actor]['control'] == 'npc'), None)
    if npc is None:
        raise ValueError('This example requires an NPC at the opening; author a plan to move or meet one first')
    name = state['actors'][npc]['name']
    topics = ['the morning weather', 'a favorite breakfast', 'quiet paths nearby', 'caring for window plants',
              'housework on rainy days', 'interesting sounds', 'snacks worth sharing', 'favorite books']
    steps = []
    for index in range(turns):
        if index == 0:
            text = (f'{name}, please remember this account: I stored my piccolo inside the walnut cabinet on '
                    'the second floor of Bluebell Tower. I will collect it after the festival.')
        elif index == turns - 1:
            text = (f'{name}, where did I say I had put that small wind instrument for safekeeping when '
                    'we first met? Please give the place, floor and container.')
        else:
            text = f'{name}, what are your thoughts about {topics[(index - 1) % len(topics)]} today?'
        step = {'id': f'turn_{index + 1:03d}', 'command': {'mode': 'say', 'text': text}}
        if index == turns - 1:
            # Author content-language-specific assertions after generating this example.
            step['recalls'] = [{'query': 'Where was the wind instrument stored for safekeeping?',
                               'actor_id': npc, 'limit': 8,
                               'expect': {'contains': {'properties': {'text': {'pattern': 'Bluebell Tower'}},
                                                       'required': ['text']}}},
                              {'query': 'Bluebell Tower', 'actor_id': npc, 'world_version': 0,
                               'expect': {'not': {'contains': {'properties': {'text': {'pattern': 'Bluebell Tower'}},
                                                               'required': ['text']}}}}]
        steps.append(step)
    return {'format': 'narraloom.playtest-1', 'player_name': 'Traveler', 'steps': steps}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--turns', type=int, default=100)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = memory_plan(load_source(args.source), args.turns)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        handle.write(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
