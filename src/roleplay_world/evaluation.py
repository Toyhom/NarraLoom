"""Frozen, resumable module evaluations through the normal model gateway.

Requires the optional research extra. Evaluation expectations stay outside model
prompts and schema repair. Results and raw traces belong to the caller's workspace.
"""

import asyncio
import copy
import fcntl
import hashlib
import json
import math
import os
import statistics
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import unquote

from pydantic import Field, model_validator

from . import __version__
from .contracts import Contract, DomainError, Identifier
from .decisions import DecisionRequest
from .gateway import ModelGateway
from .settings import DECISION_ROLES, ROLES


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def validator(schema):
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry
        from referencing.exceptions import NoSuchResource
    except ImportError as exc:
        raise ValueError('Install the research extra from the checkout: python -m pip install ".[research]"') from exc

    # Visit schema positions only: a literal in const/enum/examples can contain
    # any key, including $ref, without becoming a schema reference.
    maps = {'$defs', 'definitions', 'properties', 'patternProperties', 'dependentSchemas'}
    single = {'additionalProperties', 'unevaluatedProperties', 'propertyNames', 'items',
              'additionalItems', 'unevaluatedItems', 'contains', 'not', 'if', 'then', 'else'}
    arrays = {'allOf', 'anyOf', 'oneOf', 'prefixItems'}
    visited = set()

    def references(value, root=False):
        if isinstance(value, dict):
            if id(value) in visited:
                return
            visited.add(id(value))
            if not root and '$id' in value:
                raise ValueError('Evaluation schemas use one document; nested $id is unsupported')
            if '$schema' in value and value['$schema'] != 'https://json-schema.org/draft/2020-12/schema':
                raise ValueError('Evaluation schemas use JSON Schema Draft 2020-12')
            for key, child in value.items():
                if key in {'$ref', '$dynamicRef'}:
                    if not isinstance(child, str) or (child != '#' and not child.startswith('#/')):
                        raise ValueError('Evaluation schemas support document-local JSON Pointer references only')
                    target = schema
                    try:
                        for token in unquote(child[2:]).split('/') if child != '#' else []:
                            token = token.replace('~1', '/').replace('~0', '~')
                            target = target[int(token)] if isinstance(target, list) else target[token]
                    except (KeyError, IndexError, ValueError, TypeError) as exc:
                        raise ValueError('Evaluation schema has an unresolved local reference') from exc
                    try:
                        Draft202012Validator.check_schema(target)
                    except Exception as exc:
                        raise ValueError('Evaluation reference does not point to a schema') from exc
                    references(target, root=target is schema)
                elif key in maps and isinstance(child, dict):
                    for subschema in child.values():
                        references(subschema)
                elif key in single:
                    references(child)
                elif key in arrays and isinstance(child, list):
                    for subschema in child:
                        references(subschema)

    references(schema, root=True)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise ValueError('Invalid evaluation JSON Schema') from exc
    def no_remote(uri):
        raise NoSuchResource(ref=uri)

    return Draft202012Validator(schema, registry=Registry(retrieve=no_remote))


class EvaluationCase(Contract):
    format: Literal['narraloom.eval-case-1'] = 'narraloom.eval-case-1'
    id: Identifier
    role: Identifier
    kind: Literal['generate', 'decide'] = 'generate'
    system: Annotated[str, Field(max_length=60000)] = ''
    data: dict = Field(default_factory=dict)
    output_schema: dict | None = None
    decision: DecisionRequest | None = None
    expect: dict | None = None

    @model_validator(mode='after')
    def shape(self):
        if self.kind == 'generate':
            if self.role not in ROLES or self.output_schema is None or self.decision is not None:
                raise ValueError('Generation cases require a generation role and output_schema')
        elif self.role not in DECISION_ROLES or self.decision is None or self.output_schema is not None or self.system or self.data:
            raise ValueError('Decision cases require a decision role/request and no generation fields')
        if len(canonical(self.model_dump(mode='json'))) > 500000:
            raise ValueError('Evaluation case exceeds 500000 characters')
        return self


def load_cases(path):
    path = Path(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Evaluation suite exceeds 16 MiB')
    cases = []
    for line, text in enumerate(path.read_text().splitlines(), 1):
        if text.strip():
            try:
                cases.append(EvaluationCase.model_validate_json(text))
            except ValueError as exc:
                raise ValueError(f'Invalid evaluation case on line {line}') from exc
    return prepare_cases(cases)


def prepare_cases(cases):
    # A caller can mutate a Pydantic instance after construction. Serializing
    # and validating again also gives dict and object inputs identical JSON types.
    cases = [EvaluationCase.model_validate_json(canonical(
        case.model_dump(mode='json') if isinstance(case, EvaluationCase) else case)) for case in cases]
    if not 1 <= len(cases) <= 1000 or len({case.id for case in cases}) != len(cases):
        raise ValueError('A suite requires 1–1000 cases with unique IDs')
    for case in cases:
        for schema in (case.output_schema, case.expect):
            if schema is not None:
                validator(schema)
    return cases


class FrozenSchema:
    """The gateway's schema protocol backed by an authored JSON Schema."""

    __name__ = 'EvaluationOutput'

    def __init__(self, schema):
        self.schema = copy.deepcopy(schema)
        self.validator = validator(self.schema)

    def model_json_schema(self):
        return copy.deepcopy(self.schema)

    def model_validate(self, value):
        canonical(value)  # Reject non-finite JSON before passing it to assertions.
        error = next(self.validator.iter_errors(value), None)
        if error:
            raise ValueError(f'Output schema failed at /{"/".join(map(str, error.absolute_path))}: {error.validator}')
        return value


def _behavior_config(config):
    # Rotate authentication without changing an experiment. Store only a digest
    # of the remaining settings; URLs and provider-specific bodies stay private.
    return {key: value for key, value in config.items() if key not in {'api_key', 'api_key_file', 'api_key_env'}}


def _implementation():
    root = Path(__file__).parent
    data = b''.join(path.name.encode() + b'\0' + path.read_bytes() for path in sorted(root.glob('*.py')))
    return hashlib.sha256(data).hexdigest()


def _save(path, report):
    temporary = path.with_suffix('.next')
    with temporary.open('w') as handle:
        handle.write(canonical(report) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


TRACE_FIELDS = {'role', 'model', 'response_model', 'call', 'duration_s', 'provider', 'backend', 'revision', 'status', 'error'}


def _traces(values):
    result = []
    for value in values:
        trace = {key: value[key] for key in TRACE_FIELDS if key in value}
        usage = value.get('usage')
        fields = {'prompt_tokens', 'completion_tokens', 'input_tokens', 'output_tokens'}
        if not isinstance(usage, dict) or not any(key in usage for key in fields):
            trace['usage'] = None
        elif any(type(usage[key]) is not int or usage[key] < 0 for key in fields if key in usage):
            trace.update(usage=None, usage_valid=False)
        else:
            trace['usage'] = {key: usage[key] for key in fields if key in usage}
        result.append(trace)
    return result


def _identity(row):
    return {key: row[key] for key in ('id', 'role', 'repeat', 'scored', 'input_sha256')}


@contextmanager
def _writer(output, resume):
    output.mkdir(parents=True, exist_ok=resume)
    with (output / '.evaluation.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Another evaluator owns this output directory') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def summarize(rows):
    def group(values):
        attempted = [row for row in values if row['status'] not in {'pending', 'running'}]
        expected = [row for row in values if row['scored']]
        durations = sorted(row['duration_s'] for row in attempted if 'duration_s' in row)
        traces = [trace for row in values for trace in row.get('traces', [])]
        usage = [trace.get('usage') for trace in traces]
        return {
            'cases': len(values), 'attempted': len(attempted),
            'schema_valid': sum(row['schema_valid'] for row in values),
            'schema_valid_rate': sum(row['schema_valid'] for row in values) / len(values),
            'scored_cases': len(expected), 'passed': sum(row['passed'] is True for row in expected),
            'pass_rate': sum(row['passed'] is True for row in expected) / len(expected) if expected else None,
            'errors': sum(row['status'] == 'error' for row in values),
            'assertion_failed': sum(row['status'] == 'assertion_failed' for row in values),
            'unscored': sum(row['status'] == 'unscored' for row in values),
            'pending': sum(row['status'] in {'pending', 'running'} for row in values),
            'interrupted': sum(row['status'] == 'interrupted' for row in values),
            'calls': sum(row.get('calls', 0) for row in values),
            'repairs': sum(row.get('repairs', 0) for row in values),
            'latency_p50_s': statistics.median(durations) if durations else None,
            'latency_p95_s': durations[max(0, math.ceil(len(durations) * .95) - 1)] if durations else None,
            'reported_input_tokens': sum(u.get('prompt_tokens', u.get('input_tokens', 0)) for u in usage if u),
            'reported_output_tokens': sum(u.get('completion_tokens', u.get('output_tokens', 0)) for u in usage if u),
            'calls_without_usage': sum(not u or not ({'prompt_tokens', 'input_tokens'} & u.keys())
                                       or not ({'completion_tokens', 'output_tokens'} & u.keys()) for u in usage)
                                   + sum(max(0, row.get('calls', 0) - len(row.get('traces', []))) for row in values),
            'calls_incomplete': sum(row.get('calls_incomplete', False) for row in values),
            'response_models': sorted({trace['response_model'] for trace in traces if trace.get('response_model')}),
        }
    return {'overall': group(rows), 'roles': {
        role: group([row for row in rows if row['role'] == role]) for role in sorted({row['role'] for row in rows})}}


def _check_report(report, *, completed=False):
    """Reject incomplete or structurally inconsistent persisted results."""
    try:
        if report['format'] != 'narraloom.eval-report-1' or report['status'] not in {'running', 'interrupted', 'completed'}:
            raise ValueError()
        rows = report['rows']
        if not isinstance(rows, list) or not 1 <= len(rows) <= 20000:
            raise ValueError()
        workload = report['manifest']['workload']
        for digest in (report['manifest']['configuration_sha256'], workload['suite_sha256'],
                       workload['implementation_sha256']):
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError()
        if type(workload['repeats']) is not int or not 1 <= workload['repeats'] <= 20:
            raise ValueError()
        if type(workload['max_repairs']) is not int or not 0 <= workload['max_repairs'] <= 2:
            raise ValueError()
        identities = set()
        for row in rows:
            identity = (row['id'], row['repeat'])
            if identity in identities or type(row['repeat']) is not int or not 0 <= row['repeat'] < workload['repeats']:
                raise ValueError()
            identities.add(identity)
            if type(row['scored']) is not bool or type(row['schema_valid']) is not bool:
                raise ValueError()
            if row['status'] not in {'pending', 'running', 'passed', 'assertion_failed', 'unscored', 'error', 'interrupted'}:
                raise ValueError()
            valid = row['status'] in {'passed', 'assertion_failed', 'unscored'}
            if row['schema_valid'] != valid or (valid and 'output' not in row):
                raise ValueError()
            expected = (row['status'] == 'passed') if row['scored'] and row['status'] not in {'pending', 'running'} else None
            if row['passed'] is not expected or (row['status'] == 'unscored' and row['scored']):
                raise ValueError()
            if row['status'] in {'passed', 'assertion_failed'} and not row['scored']:
                raise ValueError()
            if any(type(row.get(key, 0)) is not int or row.get(key, 0) < 0 for key in ('calls', 'repairs')):
                raise ValueError()
            if 'duration_s' in row and (type(row['duration_s']) not in {int, float}
                                       or not math.isfinite(row['duration_s']) or row['duration_s'] < 0):
                raise ValueError()
            if not isinstance(row.get('traces', []), list):
                raise TypeError()
            if any(not isinstance(t, dict) for t in row.get('traces', [])):
                raise ValueError()
            if row.get('calls', 0) < len(row.get('traces', [])):
                raise ValueError()
            for trace in row.get('traces', []):
                if any(key in trace and not isinstance(trace[key], str)
                       for key in TRACE_FIELDS - {'call', 'duration_s', 'response_model'}):
                    raise ValueError()
                if trace.get('response_model') is not None and not isinstance(trace['response_model'], str):
                    raise TypeError()
                usage = trace.get('usage')
                if usage is not None and (not isinstance(usage, dict)
                                          or any(type(v) is not int or v < 0 for v in usage.values())):
                    raise ValueError()
            if (completed or report['status'] == 'completed') and row['status'] in {'pending', 'running'}:
                raise ValueError()
        if completed and report['status'] != 'completed':
            raise ValueError()
        canonical(report)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Invalid or incomplete evaluation report') from exc


async def evaluate(cases, *, config, output, secrets_root=None, registry=None, repeats=1, max_repairs=0, resume=False):
    """Evaluate frozen module inputs; resume skips all terminal rows, including failures.

    A cancelled or crash-interrupted call is retained as interrupted. Pending rows
    can continue on explicit resume. Repeating an interrupted call requires a new run.
    """
    cases = prepare_cases(cases)
    if type(repeats) is not int or not 1 <= repeats <= 20 or type(max_repairs) is not int or not 0 <= max_repairs <= 2:
        raise ValueError('repeats must be 1–20 and max_repairs must be 0–2')
    output = Path(output).resolve()
    with _writer(output, resume):
        gateway = ModelGateway(copy.deepcopy(config), output / 'traces', registry=registry, secrets_root=secrets_root)
        try:
            role_configs = {case.role: gateway.role_config(case.role) for case in cases}
            for case in cases:
                cfg = role_configs[case.role]
                if not gateway.configured(case.role):
                    raise ValueError(f'Unconfigured module: {case.role}')
                gateway.registry.require(cfg.get('backend', 'systemone' if case.kind == 'decide' else 'openai'), case.kind)
                gateway.auth_headers(cfg)
        except (DomainError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError('Invalid model configuration or engine capability') from exc
        workload = {'suite_sha256': fingerprint([case.model_dump(mode='json') for case in cases]),
                    'framework_version': __version__, 'implementation_sha256': _implementation(),
                    'repeats': repeats, 'max_repairs': max_repairs}
        manifest = {'workload': workload, 'configuration_sha256': fingerprint({
            role: _behavior_config(cfg) for role, cfg in role_configs.items()})}
        rows = [{'id': case.id, 'role': case.role, 'repeat': repeat, 'scored': case.expect is not None,
                 'status': 'pending', 'schema_valid': False, 'passed': None,
                 'input_sha256': fingerprint(case.model_dump(mode='json', exclude={'expect'}))}
                for repeat in range(repeats) for case in cases]
        path = output / 'report.json'
        if resume:
            report = json.loads(path.read_text())
            _check_report(report)
            if (report.get('format') != 'narraloom.eval-report-1' or report.get('manifest') != manifest
                    or [_identity(row) for row in report['rows']] != [_identity(row) for row in rows]):
                raise ValueError('Evaluation workload or model configuration changed; use a new output directory')
            for index, row in enumerate(report['rows']):
                if row['status'] == 'running':
                    traces = [json.loads(path.read_text()) for path in sorted((output / 'traces').glob(
                        f'eval_{index:05d}_{row["id"]}-*.json'))]
                    row.update(status='interrupted', error='previous_process_interrupted', calls_incomplete=True,
                               traces=_traces(traces), calls=max((trace['call'] for trace in traces), default=0),
                               passed=False if row['scored'] else None)
        else:
            report = {'format': 'narraloom.eval-report-1', 'manifest': manifest, 'status': 'running', 'rows': rows}

        def save(status):
            report.update(status=status, metrics=summarize(report['rows']))
            _save(path, report)

        save('running')
        for index, row in enumerate(report['rows']):
            if row['status'] != 'pending':
                continue
            case = cases[index % len(cases)]
            budget = {'calls': 0, 'repairs': 0, 'traces': [], 'max_calls': 1 + max_repairs, 'max_repairs': max_repairs}
            row['status'] = 'running'
            save('running')
            started = time.monotonic()
            interrupted = False
            try:
                action_id = f'eval_{index:05d}_{case.id}'
                if case.kind == 'generate':
                    result = await gateway.generate(case.role, case.system, copy.deepcopy(case.data),
                                                    FrozenSchema(case.output_schema), action_id, budget)
                else:
                    result = (await gateway.decide(case.role, case.decision.model_copy(deep=True), action_id, budget))['answers']
                # Expectations are evaluated after gateway/schema repair has ended.
                row.update(schema_valid=True, output=result)
                if case.expect is None:
                    row['status'] = 'unscored'
                else:
                    failures = list(validator(case.expect).iter_errors(result))
                    row.update(status='assertion_failed' if failures else 'passed', passed=not failures,
                               assertions=[{'path': list(error.absolute_path), 'keyword': error.validator} for error in failures])
            except (asyncio.CancelledError, OSError) as exc:
                row.update(status='interrupted', error='cancelled' if isinstance(exc, asyncio.CancelledError) else 'storage_error',
                           passed=False if row['scored'] else None)
                interrupted = True
                raise
            except Exception as exc:  # noqa: BLE001 -- adapter failures are retained per trial
                row.update(status='error', passed=False if row['scored'] else None,
                           error=exc.code if isinstance(exc, DomainError) else type(exc).__name__)
            finally:
                row.update(duration_s=round(time.monotonic() - started, 6), calls=budget['calls'],
                           repairs=budget['repairs'], traces=_traces(budget['traces']),
                           calls_incomplete=budget['calls'] != len(budget['traces']))
                save('interrupted' if interrupted else 'running')
        save('completed')
        return report


def compare(baseline, candidate):
    """Pair completed reports with identical tasks, expectations and repair budgets."""
    for report in (baseline, candidate):
        _check_report(report, completed=True)
    if baseline['manifest']['workload'] != candidate['manifest']['workload']:
        raise ValueError('Evaluation workloads differ')
    if not baseline['rows'] or [_identity(row) for row in baseline['rows']] != [_identity(row) for row in candidate['rows']]:
        raise ValueError('Evaluation rows differ')
    left, right = summarize(baseline['rows']), summarize(candidate['rows'])
    changes = []
    for before, after in zip(baseline['rows'], candidate['rows']):
        changes.append({'id': before['id'], 'role': before['role'], 'repeat': before['repeat'],
                        'baseline_status': before['status'], 'candidate_status': after['status'],
                        'baseline_passed': before['passed'], 'candidate_passed': after['passed']})
    return {'format': 'narraloom.eval-comparison-1', 'workload': baseline['manifest']['workload'],
            'baseline_configuration_sha256': baseline['manifest']['configuration_sha256'],
            'candidate_configuration_sha256': candidate['manifest']['configuration_sha256'],
            'baseline': left, 'candidate': right, 'pairs': changes,
            'improved': sum(pair['candidate_passed'] is True and pair['baseline_passed'] is False for pair in changes),
            'regressed': sum(pair['baseline_passed'] is True and pair['candidate_passed'] is False for pair in changes)}
