"""Resumable campaign trajectories using the normal runtime and durable receipts."""

import asyncio
import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from . import __version__
from .contracts import ActionCommand, Contract, DomainError, Identifier
from .evaluation import (
    _behavior_config,
    _implementation,
    _save,
    _traces,
    _writer,
    canonical,
    fingerprint,
    validator,
)
from .gateway import ModelGateway
from .journal import digest
from .settings import ROLES
from .store import Store, public_commit
from .world import project


class MemoryProbe(Contract):
    query: Annotated[str, Field(min_length=1, max_length=4000)]
    actor_id: Identifier | None = None
    world_version: Annotated[int, Field(strict=True, ge=0)] | None = None
    limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 8
    expect: dict | None = None


class PlaytestStep(Contract):
    id: Identifier
    command: dict
    expect: dict | None = None
    recalls: Annotated[list[MemoryProbe], Field(max_length=8)] = Field(default_factory=list)

    @model_validator(mode='after')
    def valid_command(self):
        if {'action_id', 'expected_world_version'} & self.command.keys():
            raise ValueError('The runner assigns action IDs and expected world versions')
        ActionCommand.model_validate({**self.command, 'action_id': 'validation', 'expected_world_version': 0})
        return self


class PlaytestPlan(Contract):
    format: Literal['narraloom.playtest-1'] = 'narraloom.playtest-1'
    player_name: Annotated[str, Field(min_length=1, max_length=32)] = 'Playtester'
    steps: Annotated[list[PlaytestStep], Field(min_length=1, max_length=1000)]

    @model_validator(mode='after')
    def unique_ids(self):
        if len({step.id for step in self.steps}) != len(self.steps):
            raise ValueError('Playtest steps require unique IDs')
        for index, step in enumerate(self.steps, 1):
            if any(probe.world_version is not None and probe.world_version > index for probe in step.recalls):
                raise ValueError('A recall probe cannot read a future world version')
        return self


def load_source(path):
    """Compile a native single-story export without changing its authored content."""
    from .content import StoryBlueprint, WorldBlueprint, compile_story

    path = Path(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Playtest source exceeds 16 MiB')
    source = json.loads(path.read_text())
    return compile_story(WorldBlueprint.model_validate(source['world']), StoryBlueprint.model_validate(source['story']),
                         'playtest_source', origin=source.get('origin'))


def load_plan(path):
    path = Path(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Playtest plan exceeds 16 MiB')
    return PlaytestPlan.model_validate_json(path.read_text())


def assertions(expected, actual):
    if expected is None:
        return None
    return [{'path': '/' + '/'.join(map(str, error.absolute_path)), 'rule': error.validator}
            for error in validator(expected).iter_errors(actual)]


def metrics(report, trace_root):
    traces = _traces([json.loads(path.read_text()) for path in sorted(trace_root.glob('*.json'))])
    usage = [trace.get('usage') for trace in traces]
    rows = report['steps']
    return {'steps': len(rows), 'committed': sum(row.get('committed', False) for row in rows),
            'scored': sum(row['scored'] for row in rows),
            'passed': sum(row.get('passed') is True for row in rows),
            'failed_assertions': sum(row.get('passed') is False for row in rows),
            'execution_failures': sum(len(row.get('failures', [])) for row in rows),
            'steps_with_incomplete_attempt_accounting': sum(row.get('calls_incomplete', False) for row in rows),
            'model_calls': len(traces),
            'model_errors': sum(trace.get('status') != 'ok' for trace in traces),
            'reported_input_tokens': sum(u.get('prompt_tokens', u.get('input_tokens', 0)) for u in usage if u),
            'reported_output_tokens': sum(u.get('completion_tokens', u.get('output_tokens', 0)) for u in usage if u),
            'calls_with_incomplete_usage': sum(not u or not ({'prompt_tokens', 'input_tokens'} & u.keys())
                                               or not ({'completion_tokens', 'output_tokens'} & u.keys()) for u in usage),
            'response_models': sorted({t['response_model'] for t in traces if t.get('response_model')})}


async def playtest(template, plan, *, config, output, secrets_root=None, registry=None, check_registry=None,
                   resume=False, retry_failed=False, max_steps=None):
    """Run a frozen trajectory in its own Store; model expectations never enter prompts.

    Resume recovers committed actions. Failed/interrupted execution additionally
    requires retry_failed=True. max_steps checkpoints after that many new steps.
    """
    from .runtime import Runtime

    plan = PlaytestPlan.model_validate_json(canonical(plan.model_dump(mode='json') if isinstance(plan, PlaytestPlan) else plan))
    template = json.loads(canonical(template))
    if max_steps is not None and (type(max_steps) is not int or max_steps < 1):
        raise ValueError('max_steps must be a positive integer')
    if retry_failed and not resume:
        raise ValueError('retry_failed requires resume')
    for step in plan.steps:
        for expected in [step.expect, *[probe.expect for probe in step.recalls]]:
            if expected is not None:
                validator(expected)
    output = Path(output).resolve()
    with _writer(output, resume):
        gateway = ModelGateway(deepcopy(config), output / 'traces', registry=registry, secrets_root=secrets_root)
        role_configs = {role: _behavior_config(gateway.role_config(role)) for role in [*ROLES, 'action_router', 'memory_embedding']}
        manifest = {'template_sha256': fingerprint(template), 'plan_sha256': fingerprint(plan.model_dump(mode='json')),
                    'configuration_sha256': fingerprint({'roles': role_configs, 'memory_policy': config.get('memory_policy'),
                                                          'decision_policy': config.get('decision_policy')}),
                    'framework_version': __version__, 'implementation_sha256': _implementation()}
        path = output / 'report.json'
        if resume:
            report = json.loads(path.read_text())
            if report.get('format') != 'narraloom.playtest-report-1' or report.get('manifest') != manifest:
                raise ValueError('Playtest content, plan, implementation or model configuration changed; use a new output')
            if [row['id'] for row in report['steps']] != [step.id for step in plan.steps]:
                raise ValueError('Playtest report step identities changed')
        else:
            report = {'format': 'narraloom.playtest-report-1', 'manifest': manifest, 'status': 'running',
                      'steps': [{'id': step.id, 'status': 'pending', 'scored': step.expect is not None or
                                 any(probe.expect is not None for probe in step.recalls)} for step in plan.steps]}

        def save(status):
            report.update(status=status, metrics=metrics(report, gateway.trace_root))
            _save(path, report)

        save('running')
        store = Store(output / 'data', check_registry=check_registry)
        runtime = Runtime(store, gateway)
        try:
            campaign = store.create_campaign('playtest', template, plan.player_name, request_key='playtest_campaign',
                                             request_hash=fingerprint({'template': template, 'name': plan.player_name}))
            bid = campaign['main_branch']
            report.update(campaign_id=campaign['id'], branch_id=bid)
            finished = 0
            for index, (step, row) in enumerate(zip(plan.steps, report['steps'], strict=True)):
                aid = f'playtest_{index:04d}'
                command = ActionCommand.model_validate({**step.command, 'action_id': aid, 'expected_world_version': index})
                if row['status'] == 'completed':
                    action = store.actions.get(aid)
                    if not action or action['status'] != 'committed' or row['state_sha256'] != digest(store.state_at(bid, index + 1)):
                        raise ValueError('Playtest report and journal disagree')
                    continue
                if max_steps is not None and finished >= max_steps:
                    save('checkpointed')
                    return report
                row.update(status='running')
                save('running')
                started = time.monotonic()
                action, created = store.accept(campaign['id'], bid, 'playtest', command, actor_id=command.actor_id)
                if action['status'] == 'interrupted':
                    row['calls_incomplete'] = True
                if action['status'] != 'committed':
                    if created:
                        await runtime.run(aid)
                    elif action['status'] in {'failed', 'interrupted'} and retry_failed:
                        runtime.retry(aid, 'playtest')
                        await runtime.tasks[aid]
                    else:
                        row.update(status='execution_failed', committed=False)
                        save('execution_failed')
                        return report
                    action = store.actions[aid]
                row['duration_s'] = row.get('duration_s', 0) + time.monotonic() - started
                if action['status'] != 'committed':
                    row.setdefault('failures', []).append({'status': action['status'], 'duration_s': row['duration_s']})
                    if action['status'] == 'interrupted':
                        row['calls_incomplete'] = True
                    row.update(status='execution_failed', committed=False)
                    save('execution_failed')
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError()
                    return report
                state = store.state_at(bid, index + 1)
                row.update(committed=True, state_sha256=digest(state))
                actual = {'result': public_commit(action['result'], command.actor_id, state['player']),
                          'view': project(state, command.actor_id)}
                row.update(observed=actual, assertions=assertions(step.expect, actual))
                # Checkpoint each read-only probe so continuation does not repeat completed model calls.
                probes = row.setdefault('recalls', [])
                for number, probe in enumerate(step.recalls):
                    if number < len(probes):
                        continue
                    snapshot = state if probe.world_version is None else store.state_at(bid, probe.world_version)
                    actor = probe.actor_id or snapshot['player']
                    budget = {'calls': 0, 'max_calls': 12, 'traces': []}
                    async with asyncio.timeout(180):
                        found = await gateway.memory.recall(snapshot, actor, probe.query, f'{aid}_recall_{number}', budget,
                                                            limit=probe.limit, scope=f'{bid}@{snapshot["version"]}')
                    probes.append({'records': found, 'diagnostics': budget['traces'],
                                   'assertions': assertions(probe.expect, found)})
                    save('running')
                errors = [*(row['assertions'] or []), *[e for p in probes for e in (p['assertions'] or [])]]
                row.update(status='completed', passed=not errors if row['scored'] else None)
                finished += 1
                save('running')
            expected = digest(store.branches[bid]['state'])
            await runtime.close()
            store.close()
            store = Store(output / 'data', check_registry=check_registry)
            if digest(store.branches[bid]['state']) != expected:
                raise ValueError('Restart replay differs from the committed state')
            report['replay'] = {'status': 'passed', 'world_version': store.branches[bid]['state']['version'],
                                'state_sha256': expected}
            save('failed' if any(row.get('passed') is False for row in report['steps']) else 'completed')
            return report
        except BaseException as exc:
            report['last_error'] = exc.code if isinstance(exc, DomainError) else type(exc).__name__
            save('interrupted' if isinstance(exc, asyncio.CancelledError) else 'error')
            raise
        finally:
            await runtime.close()
            store.close()
