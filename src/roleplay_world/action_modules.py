"""Host-registered, versioned actions with portable state and recorded outcomes."""

import inspect
import json
import random
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .contracts import Contract, DomainError, Identifier
from .journal import digest
from .json_schema import inline_schema, validator


def bounded(value, maximum=64000):
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False)) > maximum:
        raise ValueError('Action module data exceeds its size limit')
    return value


def schema_check(schema, value):
    error = next(validator(schema).iter_errors(value), None)
    if error:
        raise DomainError('module_schema', 'Action module data does not match its declared schema', 422)
    return value


class ModuleState(Contract):
    public: dict[str, JsonValue] = Field(default_factory=dict)
    actors: dict[Identifier, dict[str, JsonValue]] = Field(default_factory=dict)
    private: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode='after')
    def finite(self):
        bounded(self.model_dump(mode='json'))
        return self


class ModuleSelection(Contract):
    id: Identifier
    engine: Identifier
    version: Identifier
    options: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode='after')
    def finite(self):
        bounded(self.options, 16000)
        return self


class ModuleAction(Contract):
    id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=80)]
    description: Annotated[str, Field(min_length=1, max_length=1000)]
    parameters_schema: dict


class ModuleBinding(ModuleSelection):
    initial: ModuleState
    state_schema: dict
    actions: Annotated[list[ModuleAction], Field(min_length=1, max_length=12)]

    @model_validator(mode='after')
    def contract(self):
        if len({a.id for a in self.actions}) != len(self.actions):
            raise ValueError('Module action IDs must be unique')
        bounded(self.state_schema, 32000)
        schema_check(self.state_schema, self.initial.model_dump(mode='json'))
        for action in self.actions:
            bounded(action.parameters_schema, 16000)
            bounded(inline_schema(action.parameters_schema), 32000)
        return self


class ModuleResult(Contract):
    model_config = ConfigDict(extra='forbid', strict=True)
    state: ModuleState
    resource_deltas: dict[Identifier, Annotated[int, Field(strict=True, ge=-10000, le=10000)]] = Field(default_factory=dict)
    messages: Annotated[list[Annotated[str, Field(min_length=1, max_length=600)]], Field(max_length=6)] = Field(default_factory=list)
    time_cost_s: Annotated[int, Field(strict=True, ge=1, le=1800)] = 60


class ModuleTestStep(Contract):
    action_id: Identifier
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class ModuleTest(Contract):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    steps: Annotated[list[ModuleTestStep], Field(min_length=1, max_length=16)]
    expect: dict
    seed: Annotated[int, Field(strict=True, ge=0, le=2147483647)] = 7

    @model_validator(mode='after')
    def contract(self):
        bounded(self.model_dump(mode='json'))
        if not self.expect:
            raise ValueError('Module tests require an expected state schema')
        validator(self.expect)
        return self


class ModuleReceipt(Contract):
    module_id: Identifier
    binding_sha256: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    actor_id: Identifier
    action_id: Identifier
    parameters: dict[str, JsonValue]
    before_sha256: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    after: ModuleState
    resource_deltas: dict[Identifier, Annotated[int, Field(strict=True, ge=-10000, le=10000)]]
    time_cost_s: Annotated[int, Field(strict=True, ge=1, le=1800)]
    messages: Annotated[list[Annotated[str, Field(min_length=1, max_length=600)]], Field(max_length=6)]

    @model_validator(mode='after')
    def finite_parameters(self):
        bounded(self.parameters, 16000)
        return self


@dataclass(frozen=True)
class ActionSpec:
    id: str
    name: str
    description: str
    parameters: type[BaseModel]


@dataclass(frozen=True)
class ActionModule:
    id: str
    version: str
    options: type[BaseModel]
    state: type[BaseModel]
    actions: tuple[ActionSpec, ...]
    initialize: Callable
    resolve: Callable
    guidance: str
    tests: Callable


def _value(value):
    return value.model_dump(mode='json') if isinstance(value, BaseModel) else deepcopy(value)


class ActionRegistry:
    def __init__(self):
        self._modules = {}

    def copy(self):
        registry = ActionRegistry()
        registry._modules = self._modules.copy()
        return registry

    def register(self, module: ActionModule):
        identity = ModuleSelection(id=module.id, engine=module.id, version=module.version)
        key = (identity.engine, identity.version)
        if key in self._modules:
            raise ValueError('Action module version is already registered')
        for model in [module.options, module.state, *[action.parameters for action in module.actions]]:
            if not isinstance(model, type) or not issubclass(model, BaseModel):
                raise TypeError('Action modules require Pydantic options, state and parameter models')
        for callback in [module.initialize, module.resolve, module.tests]:
            if not callable(callback) or inspect.iscoroutinefunction(callback):
                raise TypeError('Action module callbacks must be synchronous pure functions')
        if not module.guidance or not 1 <= len(module.actions) <= 12:
            raise ValueError('Action modules require guidance and 1–12 actions')
        actions = self._actions(module)
        if len({action.id for action in actions}) != len(actions):
            raise ValueError('Action IDs must be unique within a module')
        self._modules[key] = module

    def selections(self, selections):
        values = [self.selection(value)[0] for value in selections]
        if len(values) > 8 or len({value.id for value in values}) != len(values):
            raise DomainError('invalid_action_modules', 'Select up to eight uniquely named action modules', 422)
        return values

    @staticmethod
    def _actions(module):
        return [ModuleAction(id=a.id, name=a.name, description=a.description,
                             parameters_schema=a.parameters.model_json_schema()) for a in module.actions]

    def selection(self, selection):
        value = ModuleSelection.model_validate(_value(selection))
        module = self._modules.get((value.engine, value.version))
        if module is None:
            raise DomainError('action_module_unavailable', f'Action module {value.engine}@{value.version} is unavailable', 422)
        try:
            options = module.options.model_validate(deepcopy(value.options))
            bounded(options.model_dump(mode='json'), 16000)
        except ValueError as exc:
            raise DomainError('invalid_module_options', 'Invalid action module options', 422) from exc
        return value, module, options

    def bind(self, selection):
        value, module, options = self.selection(selection)
        try:
            initial = _value(module.initialize(options))
            typed = module.state.model_validate(deepcopy(initial)).model_dump(mode='json')
            # Repeated initialization is checked before a binding is published.
            again = _value(module.initialize(module.options.model_validate(deepcopy(value.options))))
            if typed != module.state.model_validate(again).model_dump(mode='json'):
                raise ValueError('Initialization is not deterministic')
            return ModuleBinding(**value.model_dump(), initial=ModuleState.model_validate(typed),
                                 state_schema=module.state.model_json_schema(), actions=self._actions(module))
        except (ValueError, TypeError) as exc:
            raise DomainError('invalid_module_initialization', 'Action module initialization failed', 422) from exc

    def validate(self, binding):
        binding = ModuleBinding.model_validate(_value(binding))
        selection = {key: getattr(binding, key) for key in ModuleSelection.model_fields}
        _, module, _ = self.selection(selection)
        if (binding.state_schema != module.state.model_json_schema()
                or [a.model_dump() for a in binding.actions] != [a.model_dump() for a in self._actions(module)]):
            raise DomainError('action_module_contract_changed', 'Action module interface changed without a version change', 422)
        return binding, module

    def validate_template(self, template):
        for binding in validate_bindings(template.get('mechanics', {}).get('action_modules', []),
                                         [actor['id'] for actor in template['actors']]):
            self.validate(binding)

    def test_cases(self, binding):
        binding, module = self.validate(binding)
        cases = [ModuleTest.model_validate(_value(value)) for value in module.tests(
            module.options.model_validate(deepcopy(binding.options)))]
        if not 1 <= len(cases) <= 8:
            raise DomainError('invalid_module_tests', 'Provide one to eight module test routes', 422)
        covered = set()
        actions = {action.id: action.parameters_schema for action in binding.actions}
        for case in cases:
            for step in case.steps:
                if step.action_id not in actions:
                    raise DomainError('invalid_module_tests', 'Test route references an unknown action', 422)
                schema_check(actions[step.action_id], step.parameters)
                covered.add(step.action_id)
        if covered != set(actions):
            raise DomainError('invalid_module_tests', 'Test routes must exercise every module action', 422)
        return cases

    def describe(self):
        return [{'engine': module.id, 'version': module.version, 'guidance': module.guidance,
                 'options_schema': module.options.model_json_schema(),
                 'actions': [action.model_dump() for action in self._actions(module)]}
                for _, module in sorted(self._modules.items())]

    def run(self, binding, state, actor, operation, seed):
        binding, module = self.validate(binding)
        action = next(a for a in module.actions if a.id == operation.action_id)
        context = {'actor_id': actor, 'game_time_s': state['game_time_s'],
                   'actor': deepcopy(state['actors'][actor]), 'actor_state': deepcopy(state['actor_states'][actor]),
                   'module_state': deepcopy(state['action_modules'][binding.id])}
        parameters = operation.parameters or {}
        def invoke():
            value = module.resolve(deepcopy(context), operation.action_id,
                                   action.parameters.model_validate(deepcopy(parameters)),
                                   module.options.model_validate(deepcopy(binding.options)), random.Random(seed))
            result = ModuleResult.model_validate(_value(value))
            module.state.model_validate(result.state.model_dump(mode='json'))
            return result
        try:
            result = invoke()
            if result != invoke():
                raise ValueError('Action module returned different results for identical inputs and seed')
            return result
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError('invalid_module_result', 'Action module resolution failed its contract', 422) from exc


def bindings(state):
    return state['template']['mechanics'].get('action_modules', [])


def planning_mechanics(state):
    mechanics = deepcopy(state['template']['mechanics'])
    if mechanics.get('action_modules'):
        mechanics['action_modules'] = [{key: binding[key] for key in ('id', 'engine', 'version', 'actions')}
                                       for binding in bindings(state)]
    return mechanics


def validate_bindings(values, actors=None):
    parsed = [ModuleBinding.model_validate(_value(value)) for value in values]
    if len(parsed) > 8 or len({value.id for value in parsed}) != len(parsed):
        raise DomainError('invalid_action_modules', 'A world supports up to eight uniquely named action modules', 422)
    if actors is not None and any(set(binding.initial.actors) - set(actors) for binding in parsed):
        raise DomainError('invalid_module_actor', 'Initial module state references an unknown actor', 422)
    return parsed


def project_modules(state, actor):
    return [{'id': binding['id'], 'engine': binding['engine'], 'version': binding['version'],
             'public': deepcopy(state['action_modules'][binding['id']]['public']),
             'personal': deepcopy(state['action_modules'][binding['id']]['actors'].get(actor, {})),
             'actions': deepcopy(binding['actions']) if state['actors'][actor]['control'] == 'player' else []}
            for binding in bindings(state)]


def module_choices(state):
    return [{'kind': 'module', 'target_id': binding['id'], 'action_id': action['id']}
            for binding in bindings(state) for action in binding['actions']]


def parameter_schema(state, module_id, action_id):
    for binding in bindings(state):
        if binding['id'] == module_id:
            for action in binding['actions']:
                if action['id'] == action_id:
                    return action['parameters_schema']
    raise DomainError('unknown_module_action', 'Unknown action module or action', 422)


def validate_operation(state, operation):
    if operation.kind != 'module':
        if operation.action_id is not None or operation.parameters is not None:
            raise DomainError('invalid_module_action', 'Module parameters require a module operation', 422)
        return
    if operation.when != 'always' or operation.item_id is not None or operation.quantity != 1:
        raise DomainError('invalid_module_action', 'Module actions use their declared parameters', 422)
    schema_check(parameter_schema(state, operation.target_id, operation.action_id), operation.parameters or {})


def resolve_module(state, operation, actor, seed, registry, emit):
    validate_operation(state, operation)
    binding = next(b for b in bindings(state) if b['id'] == operation.target_id)
    registry = registry or ActionRegistry()
    result = registry.run(binding, state, actor, operation, seed)
    payload = {'module_id': binding['id'], 'binding_sha256': digest(binding), 'actor_id': actor,
               'action_id': operation.action_id, 'parameters': deepcopy(operation.parameters or {}),
               'before_sha256': digest(state['action_modules'][binding['id']]),
               'after': result.state.model_dump(mode='json'), 'resource_deltas': result.resource_deltas,
               'time_cost_s': result.time_cost_s, 'messages': result.messages}
    event = emit('module.resolved', payload, audience=[actor])
    for message in result.messages:
        emit('memory.recorded', {'audience': [actor], 'text': message, 'category': 'outcome',
                                'source_event_ids': [event['event_id']], 'world_version': state['version'] + 1},
             audience=[actor])
    return result.messages, result.time_cost_s


def reduce_module(state, event):
    """Replay validates stored data and scoped resource effects without plugin code."""
    try:
        payload = ModuleReceipt.model_validate(event['payload']).model_dump(mode='json')
        binding = next(b for b in bindings(state) if b['id'] == payload['module_id'])
        actor = payload['actor_id']
        if (state['actors'][actor]['control'] != 'player'
                or event['visibility'] != {'kind': 'actors', 'actor_ids': [actor]}
                or payload['binding_sha256'] != digest(binding)
                or payload['before_sha256'] != digest(state['action_modules'][binding['id']])):
            raise ValueError('Receipt identity or precondition differs')
        schema_check(parameter_schema(state, binding['id'], payload['action_id']), payload['parameters'])
        result = ModuleResult.model_validate({key: payload[key] for key in ModuleResult.model_fields if key != 'state'}
                                            | {'state': ModuleState.model_validate(payload['after'])})
        schema_check(binding['state_schema'], result.state.model_dump(mode='json'))
        if set(result.state.actors) - set(state['actors']):
            raise ValueError('Unknown actor in module state')
        current = state['actor_states'][actor]
        for resource, delta in result.resource_deltas.items():
            if resource not in current['resources']:
                raise ValueError('Unknown actor resource')
            after = current['resources'][resource] + delta
            if not 0 <= after <= current.get('resource_limits', {}).get(resource, 999999 if resource == 'coins' else -1):
                raise ValueError('Resource result exceeds actor limits')
            current['resources'][resource] = after
        state['action_modules'][binding['id']] = result.state.model_dump(mode='json')
    except (ValueError, KeyError, TypeError, StopIteration, DomainError) as exc:
        raise DomainError('invalid_module_receipt', 'Invalid action module receipt', 422) from exc


def test_view(state, binding_id):
    """Host-side assertions can inspect all three state partitions."""
    return {'module_state': deepcopy(state['action_modules'][binding_id]),
            'actor_state': deepcopy(state['actor_states'][state['player']])}


def audit_modules(template, registry):
    from .contracts import Operation, TurnPlan
    from .planning import validate_plan
    from .rules import resolve
    from .world import apply_events, initial_state

    checks = []
    for binding in template['mechanics'].get('action_modules', []):
        cases = registry.test_cases(binding)
        for case in cases:
            state = initial_state(template, 'Module tester')
            for index, step in enumerate(case.steps):
                command = {'action_id': f'module_probe_{index}', 'mode': 'act', 'text': case.name}
                operation = Operation(kind='module', target_id=binding['id'],
                                      action_id=step.action_id, parameters=step.parameters)
                plan = TurnPlan(intent=case.name, operations=[operation])
                validate_plan(state, command, plan)
                events, _, _ = resolve(state, command, plan, {}, case.seed, action_registry=registry)
                after = apply_events(state, events, state['version'] + 1)
                if digest(after) != digest(apply_events(state, events, state['version'] + 1)):
                    raise DomainError('module_replay', 'Action module replay differs', 422)
                state = after
            schema_check(case.expect, test_view(state, binding['id']))
        checks.append({'name': 'Action module: ' + binding['id'], 'status': 'passed',
                       'detail': f'{len(cases)} host test routes; all declared actions, seeded resolution and event replay'})
    return checks
