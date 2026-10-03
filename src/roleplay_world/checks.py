"""Versioned, host-registered deterministic checks shared by skills and combat."""

import inspect
import json
import random
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import Contract, DomainError, Identifier
from .journal import digest


class CheckBinding(Contract):
    engine: Identifier
    version: Identifier
    options: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def bounded(self):
        if len(json.dumps(self.options, allow_nan=False, ensure_ascii=False)) > 16000:
            raise ValueError('Check options exceed 16000 characters')
        return self


class CheckInput(Contract):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    kind: Literal['ability', 'attack', 'counterattack']
    skill: Identifier
    purpose: Annotated[str, Field(min_length=1, max_length=240)]
    difficulty: Annotated[int, Field(ge=1, le=1000)]
    modifier: Annotated[int, Field(ge=-1000, le=1000)]
    comparison: Literal['>=', '<='] = '>='


class CheckResult(Contract):
    model_config = ConfigDict(extra='forbid', strict=True)
    roll: Annotated[int, Field(ge=-1000000, le=1000000)]
    modifier: Annotated[int, Field(ge=-1000, le=1000)]
    total: Annotated[int, Field(ge=-1001000, le=1001000)]
    difficulty: Annotated[int, Field(ge=1, le=1000)]
    passed: bool
    dice: Annotated[str, Field(min_length=1, max_length=80)]
    comparison: Literal['>=', '<=']
    draws: Annotated[list[Annotated[int, Field(strict=True, ge=-1000000, le=1000000)]], Field(max_length=100)] = Field(default_factory=list)

    @model_validator(mode='after')
    def arithmetic(self):
        success = self.total >= self.difficulty if self.comparison == '>=' else self.total <= self.difficulty
        if self.total != self.roll + self.modifier or self.passed != success:
            raise ValueError('Check arithmetic and success must agree')
        return self


@dataclass(frozen=True)
class CheckEngine:
    id: str
    version: str
    options: type[BaseModel]
    resolve: Callable[[CheckInput, BaseModel, random.Random], CheckResult]
    description: str
    guidance: str


class CheckRegistry:
    def __init__(self):
        self._engines = {}

    def register(self, engine: CheckEngine):
        identity = CheckBinding(engine=engine.id, version=engine.version)
        key = (identity.engine, identity.version)
        if key in self._engines:
            raise ValueError('Check engine version is already registered')
        if not isinstance(engine.options, type) or not issubclass(engine.options, BaseModel):
            raise TypeError('Check engine options must be a Pydantic model')
        if not callable(engine.resolve) or not engine.description or not engine.guidance:
            raise ValueError('Check engines require a resolver, description and authoring guidance')
        if inspect.iscoroutinefunction(engine.resolve):
            raise TypeError('Check resolvers must be synchronous deterministic functions')
        self._engines[key] = engine

    def copy(self):
        registry = CheckRegistry()
        registry._engines = self._engines.copy()
        return registry

    def binding(self, binding):
        if binding is None:
            return None
        try:
            value = CheckBinding.model_validate(binding.model_dump() if isinstance(binding, CheckBinding) else deepcopy(binding))
        except ValueError as exc:
            raise DomainError('invalid_check_binding', 'Invalid check engine binding', 422) from exc
        engine = self._engines.get((value.engine, value.version))
        if engine is None:
            raise DomainError('check_engine_unavailable', f'Check engine {value.engine}@{value.version} is unavailable', 422)
        try:
            options = engine.options.model_validate(deepcopy(value.options))
            CheckBinding(engine=engine.id, version=engine.version, options=options.model_dump(mode='json'))
        except ValueError as exc:
            raise DomainError('invalid_check_options', f'Invalid options for {value.engine}@{value.version}', 422) from exc
        return engine, options

    def validate_template(self, template):
        self.binding(template.get('mechanics', {}).get('checks'))

    def verify(self, binding):
        if binding is None:
            return
        self.binding(binding)
        for kind in ('ability', 'attack', 'counterattack'):
            request = CheckInput(kind=kind, skill='craft' if kind == 'ability' else 'attack',
                                 purpose='Check contract verification', difficulty=7, modifier=2)
            for seed in (0, 1, 23):
                left = self.run(binding, request, random.Random(seed))
                right = self.run(binding, request, random.Random(seed))
                if left != right:
                    raise DomainError('nondeterministic_check_engine', 'Check engine changed its result for the same input and seed', 422)

    def describe(self):
        return [{'id': engine.id, 'version': engine.version, 'description': engine.description,
                 'guidance': engine.guidance, 'options_schema': engine.options.model_json_schema()}
                for _, engine in sorted(self._engines.items())]

    def guidance(self, binding):
        resolved = self.binding(binding)
        if resolved is None:
            return None
        engine, options = resolved
        return {'engine': engine.id, 'version': engine.version, 'options': options.model_dump(mode='json'),
                'guidance': engine.guidance}

    def run(self, binding, request, rng):
        engine, options = self.binding(binding)
        request = CheckInput.model_validate(request.model_dump() if isinstance(request, CheckInput) else request)
        try:
            result = engine.resolve(request, options, rng)
            result = CheckResult.model_validate(result.model_dump() if isinstance(result, CheckResult) else result)
            if result.difficulty != request.difficulty or result.modifier != request.modifier:
                raise ValueError('A check engine changed the supplied difficulty or modifier')
        except Exception as exc:
            raise DomainError('invalid_check_result', f'Check engine {engine.id}@{engine.version} failed', 422) from exc
        return {'skill': request.skill, 'purpose': request.purpose, **result.model_dump(),
                'engine': {'id': engine.id, 'version': engine.version, 'options_sha256': digest(
                    binding.options if isinstance(binding, CheckBinding) else binding.get('options', {}))}}


class SumDiceOptions(Contract):
    count: Annotated[int, Field(strict=True, ge=1, le=32)] = 2
    sides: Annotated[int, Field(strict=True, ge=2, le=100)] = 6
    comparison: Literal['>=', '<='] = '>='


def sum_dice(request, options, rng):
    draws = [rng.randint(1, options.sides) for _ in range(options.count)]
    value = sum(draws)
    total = value + request.modifier
    return CheckResult(roll=value, modifier=request.modifier, total=total, difficulty=request.difficulty,
                       passed=total >= request.difficulty if options.comparison == '>=' else total <= request.difficulty,
                       dice=f'{options.count}d{options.sides}', comparison=options.comparison, draws=draws)


def builtin_checks():
    registry = CheckRegistry()
    registry.register(CheckEngine(
        'sum_dice', '1', SumDiceOptions, sum_dice,
        'Sum independently rolled dice and add the supplied skill or attack modifier.',
        'Use count × sides dice, then add the actor modifier. For 2d6 with >=, typical thresholds are 7–10. '
        'For other dice or <=, choose thresholds for that range. Enemy defense and authored challenge difficulty '
        'use the same scale. The engine determines dice, totals and success.'))
    return registry


def resolve_check(state, request, rng, registry=None):
    """Use the pinned custom engine or preserve the legacy die sequence and result."""
    binding = state['template']['mechanics'].get('checks')
    if binding is not None:
        return (registry or builtin_checks()).run(binding, request, rng)
    percentile = request.comparison == '<='
    value = rng.randint(1, 100 if percentile else 20)
    total = value + request.modifier
    return {'skill': request.skill, 'purpose': request.purpose, 'roll': value, 'modifier': request.modifier,
            'total': total, 'difficulty': request.difficulty,
            'passed': total <= request.difficulty if percentile else total >= request.difficulty,
            'dice': 'd100' if percentile else 'd20', 'comparison': request.comparison}


def validate_receipt(state, receipt):
    """Replay checks arithmetic and the pinned identity without invoking plugins."""
    binding = state['template']['mechanics'].get('checks')
    if binding is None and 'engine' not in receipt:
        return
    try:
        selected = CheckBinding.model_validate(binding)
        expected = {'id': selected.engine, 'version': selected.version, 'options_sha256': digest(selected.options)}
        if receipt.get('engine') != expected:
            raise ValueError('Check receipt engine differs from the world binding')
        CheckResult.model_validate({key: receipt[key] for key in CheckResult.model_fields})
    except (ValueError, KeyError, TypeError) as exc:
        raise DomainError('invalid_check_receipt', 'Check receipt identity or arithmetic is invalid', 422) from exc
