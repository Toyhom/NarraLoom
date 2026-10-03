"""A host-installed dice pool, usable from an embedded backend or contract check.

Run with Uvicorn: check_engine:create --factory --app-dir examples
NARRALOOM_RULES_WORKSPACE selects saves; NARRALOOM_RULES_MODELS_CONFIG selects models.
"""

import argparse
import json
import os
import random
from pathlib import Path
from typing import Annotated

from pydantic import Field

from roleplay_world.app import create_app
from roleplay_world.checks import CheckEngine, CheckInput, CheckResult, builtin_checks
from roleplay_world.config import AppConfig
from roleplay_world.contracts import Contract


class PoolOptions(Contract):
    count: Annotated[int, Field(strict=True, ge=1, le=20)] = 6
    hit_at: Annotated[int, Field(strict=True, ge=2, le=6)] = 5


def roll_pool(request, options, rng):
    faces = [rng.randint(1, 6) for _ in range(options.count)]
    hits = sum(face >= options.hit_at for face in faces)
    total = hits + request.modifier
    return CheckResult(roll=hits, modifier=request.modifier, total=total,
                       difficulty=request.difficulty, passed=total >= request.difficulty,
                       dice=f'{options.count}d6 successes', comparison='>=', draws=faces)


def make_registry():
    registry = builtin_checks()
    registry.register(CheckEngine(
        'example_pool', '1', PoolOptions, roll_pool,
        'Roll d6s, count faces at or above hit_at, then add the supplied modifier.',
        'The result is a success count plus the actor skill/attack modifier. With 6 dice and hit_at=5, '
        'the expected success count is 2. Use authored ability thresholds 2–4 and enemy defense 5; '
        'these are success-count targets, rather than sums of dice. Give players a nonrandom route to an ending.'))
    return registry


def create():
    config = AppConfig(
        workspace_root=Path(os.environ.get('NARRALOOM_RULES_WORKSPACE', 'example-runtime')),
        models_config=os.environ.get('NARRALOOM_RULES_MODELS_CONFIG'),
        secrets_root=os.environ.get('NARRALOOM_RULES_SECRETS_ROOT'),
    )
    return create_app(config=config, check_registry=make_registry())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    binding = {'engine': 'example_pool', 'version': '1', 'options': {'count': 6, 'hit_at': 5}}
    registry = make_registry()
    registry.verify(binding)
    samples = [registry.run(binding, CheckInput(kind='ability', skill='craft', purpose='Sample check',
                                               modifier=1, difficulty=3), random.Random(seed)) for seed in range(3)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        handle.write(json.dumps({'status': 'passed', 'samples': samples}, ensure_ascii=False, indent=2) + '\n')
    print(f'Check engine contract passed: {args.output}')


if __name__ == '__main__':
    main()
