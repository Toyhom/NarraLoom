"""Host-installed exploration mechanics with typed actions and portable state.

Run: python examples/action_module.py --output example-runtime/module-check
Serve: uvicorn action_module:create --factory --app-dir examples
Set NARRALOOM_MODULE_WORKSPACE and NARRALOOM_MODULE_MODELS_CONFIG for serving.
"""

import argparse
import asyncio
import json
import os
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from roleplay_world.action_modules import (
    ActionModule,
    ActionRegistry,
    ActionSpec,
    ModuleResult,
    ModuleState,
    audit_modules,
)
from roleplay_world.app import create_app
from roleplay_world.backups import export_campaign, restore_campaign
from roleplay_world.config import AppConfig
from roleplay_world.contracts import ActionCommand, Contract, DomainError, Identifier
from roleplay_world.journal import digest
from roleplay_world.runtime import Runtime
from roleplay_world.store import Store


class Options(Contract):
    focus_max: Annotated[int, Field(strict=True, ge=1, le=12)] = 3
    vitality_cost: Annotated[int, Field(strict=True, ge=0, le=3)] = 0


class PublicState(Contract):
    surveys: Annotated[int, Field(strict=True, ge=0, le=100000)] = 0


class PersonalState(Contract):
    focus: Annotated[int, Field(strict=True, ge=0, le=12)]
    last_location: str = ''
    last_roll: Annotated[int, Field(strict=True, ge=0, le=6)] = 0


class PrivateState(Contract):
    draws: Annotated[int, Field(strict=True, ge=0, le=100000)] = 0


class ExpeditionState(ModuleState):
    public: PublicState = Field(default_factory=PublicState)
    actors: dict[Identifier, PersonalState] = Field(default_factory=dict)
    private: PrivateState = Field(default_factory=PrivateState)


class SurveyFocus(Contract):
    subject: Literal['terrain', 'weather'] = 'terrain'


class Survey(Contract):
    focus: SurveyFocus = Field(default_factory=SurveyFocus)


class Rest(Contract):
    pass


def initialize(options):
    return ExpeditionState()


def resolve(context, action_id, parameters, options, rng):
    state = ExpeditionState.model_validate(context['module_state'])
    actor = context['actor_id']
    personal = state.actors.setdefault(actor, PersonalState(focus=options.focus_max))
    deltas = {}
    if action_id == 'survey':
        if personal.focus < 1:
            raise DomainError('module_precondition', 'Rest before making another survey.', 422)
        if options.vitality_cost:
            own = context['actor_state']
            if ('vitality' not in own.get('resource_limits', {})
                    or own['resources'].get('vitality', 0) < options.vitality_cost):
                raise DomainError('module_precondition', 'Surveying requires bounded vitality from an adventure rule set.', 422)
            deltas['vitality'] = -options.vitality_cost
        personal.focus -= 1
        personal.last_location = context['actor_state']['location_id']
        personal.last_roll = rng.randint(1, 6)
        state.public.surveys += 1
        state.private.draws += 1
        message = f'{parameters.focus.subject} survey recorded; quality {personal.last_roll}/6; focus {personal.focus}.'
    else:
        personal.focus = options.focus_max
        message = f'You rest and restore focus to {personal.focus}.'
    return ModuleResult(state=ModuleState.model_validate(state.model_dump(mode='json')),
                        resource_deltas=deltas, messages=[message], time_cost_s=30)


def contract_tests(options):
    # These expectations belong to the host test runner and never enter prompts.
    return [{'name': 'Survey and rest', 'steps': [
        {'action_id': 'survey', 'parameters': {'focus': {'subject': 'terrain'}}},
        {'action_id': 'rest', 'parameters': {}}],
        'expect': {'properties': {'module_state': {'properties': {
            'public': {'properties': {'surveys': {'const': 1}}, 'required': ['surveys']},
            'actors': {'minProperties': 1, 'additionalProperties': {
                'properties': {'focus': {'const': options.focus_max}}, 'required': ['focus']}},
            'private': {'properties': {'draws': {'const': 1}}, 'required': ['draws']},
        }, 'required': ['public', 'actors', 'private']}}, 'required': ['module_state']}}]


def make_registry():
    registry = ActionRegistry()
    registry.register(ActionModule(
        id='example_exploration', version='1', options=Options, state=ExpeditionState,
        actions=(ActionSpec('survey', 'Survey', 'Record a terrain or weather survey in the current location. Costs one focus.', Survey),
                 ActionSpec('rest', 'Rest', 'Restore personal exploration focus.', Rest)),
        initialize=initialize, resolve=resolve,
        guidance='Exploration progress with shared survey counts, personal focus and recorded d6 quality. '
                 'Works in scene and adventure worlds. Enable vitality_cost with bounded adventure resources.',
        tests=contract_tests))
    return registry


SELECTION = {'id': 'exploration', 'engine': 'example_exploration', 'version': '1', 'options': {}}


def create():
    return create_app(config=AppConfig(
        workspace_root=Path(os.environ.get('NARRALOOM_MODULE_WORKSPACE', 'example-runtime')),
        models_config=os.environ.get('NARRALOOM_MODULE_MODELS_CONFIG'),
        secrets_root=os.environ.get('NARRALOOM_MODULE_SECRETS_ROOT'),
    ), action_registry=make_registry())


async def run(output):
    class NarratorFixture:
        async def generate(self, role, system, data, schema, aid, budget, validate=None):
            assert role == 'narrator'
            return schema(text='The exploration action is complete.', suggestions=[])

    registry = make_registry()
    template = json.loads(files('roleplay_world').joinpath('builtin/fogharbor.json').read_text())
    template['mechanics']['action_modules'] = [registry.bind(SELECTION).model_dump(mode='json')]
    checks = audit_modules(template, registry)
    store = Store(output / 'data', action_registry=registry)
    runtime = Runtime(store, NarratorFixture())
    try:
        campaign = store.create_campaign('tester', template, 'Explorer')
        for index, step in enumerate(registry.test_cases(template['mechanics']['action_modules'][0])[0].steps):
            action, _ = store.accept(campaign['id'], campaign['main_branch'], 'tester', ActionCommand(
                action_id=f'exploration_{index}', expected_world_version=index, text=step.action_id,
                selected_operation={'kind': 'module', 'target_id': 'exploration',
                                    'action_id': step.action_id, 'parameters': step.parameters}))
            await runtime.run(action['id'])
            assert action['status'] == 'committed', action.get('error')
        expected = digest(store.branches[campaign['main_branch']]['state'])
        backup = export_campaign(store, campaign['id'], 'tester')
    finally:
        await runtime.close()
        store.close()
    replay = Store(output / 'data')
    try:
        assert digest(replay.branches[campaign['main_branch']]['state']) == expected
        branch = replay.fork(campaign['id'], campaign['main_branch'], 'tester', 1, 'Another survey')
        assert branch['state']['action_modules']['exploration']['public']['surveys'] == 1
        restored = restore_campaign(replay, 'reader', json.dumps(backup))
        assert digest(replay.branches[restored['branch_id']]['state']) == expected
    finally:
        replay.close()
    result = {'status': 'passed', 'checks': checks, 'committed_actions': 2,
              'plugin_free_replay_fork_restore': True, 'state_sha256': expected}
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(run(parser.parse_args().output))
