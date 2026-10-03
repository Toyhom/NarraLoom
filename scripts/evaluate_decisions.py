"""Evaluate a configured System One engine on frozen bilingual routing cases (no game writes)."""
import argparse
import asyncio
import hashlib
import json
import statistics
from pathlib import Path

from roleplay_world.contracts import DomainError
from roleplay_world.gateway import ModelGateway
from roleplay_world.routing import ROUTE_INSTRUCTIONS, move_request

ROOT = Path(__file__).resolve().parents[1]


def metrics(rows, total):
    valid = [r for r in rows if 'choice' in r]
    automatic = [r for r in valid if r['accepted']]
    bins = [[r for r in valid if min(int(r['p_max']*10), 9) == i] for i in range(10)]
    return {'cases': total, 'always_defer_accuracy': sum(r['expected'] == 'defer' for r in rows)/total if total else None, 'valid_responses': len(valid), 'failures': total-len(valid),
            'accuracy': sum(r['correct'] for r in valid)/len(valid) if valid else None,
            'end_to_end_accuracy': sum(r['correct'] for r in valid)/total if total else None,
            'brier': statistics.mean(r['brier'] for r in valid) if valid else None,
            'ece_10_bins': sum(len(b)*abs(statistics.mean(r['p_max'] for r in b)-statistics.mean(r['correct'] for r in b))
                               for b in bins if b)/len(valid) if valid else None,
            'automatic_moves': len(automatic), 'automatic_coverage': len(automatic)/total if total else 0,
            'automatic_errors': sum(not r['correct'] for r in automatic),
            'latency_p50_s': statistics.median(r['duration_s'] for r in valid) if valid else None,
            'latency_p95_s': sorted(r['duration_s'] for r in valid)[int((len(valid)-1)*0.95)] if valid else None}


async def evaluate(args):
    output = Path(args.output); output.mkdir(parents=True, exist_ok=False)
    data = Path(args.cases).read_bytes(); cases = [json.loads(line) for line in data.decode().splitlines() if line]
    cfg = {'providers': {'candidate': {'url': args.url, 'backend': 'systemone', 'timeout_s': 30,
                                      'api_key_env': args.key_env}},
           'bindings': {'action_router': {'provider': 'candidate', 'model': args.model, 'revision': args.revision}}}
    gateway = ModelGateway(cfg, output/'traces')
    report = {'schema_version': '1.0', 'status': 'running', 'routing_instructions_sha256':hashlib.sha256(ROUTE_INSTRUCTIONS.encode()).hexdigest(), 'dataset_sha256': hashlib.sha256(data).hexdigest(),
              'requested_model': args.model, 'deployment_revision_label': args.revision,
              'thresholds': {'min_probability': args.min_probability, 'min_margin': args.min_margin},
              'scope': '42 authored bilingual diagnostic cases, each repeated with reversed exit order; not independent user acceptance or a calibrated benchmark',
              'rows': []}
    for case in cases:
        for reversed_order in (False, True):
            exits = list(reversed(case['exits'])) if reversed_order else case['exits']
            request = move_request(case['text'], exits)
            b = {'calls': 0, 'traces': [], 'max_calls': 1}
            row = {'id': case['id'], 'language': case['language'], 'category': case['category'],
                   'reversed': reversed_order, 'expected': case['expected']}
            try:
                result = await gateway.decide('action_router', request, case['id']+str(int(reversed_order)), b)
                answer = result['answers']['route']; key = answer['choice']
                label = 'defer' if key == 'defer' else exits[int(key.removeprefix('move_'))]['id']
                expected_key = 'defer' if case['expected'] == 'defer' else next(f'move_{i}' for i,e in enumerate(exits) if e['id'] == case['expected'])
                row.update(choice=label, correct=label == case['expected'], p_max=answer['p_max'], margin=answer['margin'],
                           response_model=result['model'], probabilities=answer['probabilities'],
                           accepted=key != 'defer' and answer['p_max'] >= args.min_probability and answer['margin'] >= args.min_margin,
                           brier=sum((p-float(k == expected_key))**2 for k,p in answer['probabilities'].items()),
                           duration_s=b['traces'][-1]['duration_s'])
            except DomainError as exc:
                row['error'] = exc.code
            report['rows'].append(row)
            (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    report['metrics'] = metrics(report['rows'], len(report['rows']))
    report['languages'] = {lang: metrics([r for r in report['rows'] if r['language'] == lang],
                                       sum(r['language'] == lang for r in report['rows'])) for lang in ('en','zh-CN')}
    pairs = [report['rows'][i:i+2] for i in range(0,len(report['rows']),2)]
    report['option_order_flips'] = sum(a.get('choice') != b.get('choice') for a,b in pairs if 'choice' in a and 'choice' in b)
    report['status'] = 'completed'  # Completion is not an accuracy pass.
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k,v in report.items() if k != 'rows'}, ensure_ascii=False, indent=2), flush=True)
    return report


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', required=True, help='System One base URL, including /v1')
    p.add_argument('--model', required=True)
    p.add_argument('--revision', default='')
    p.add_argument('--key-env', default='NARRALOOM_DECISION_KEY')
    p.add_argument('--cases', default=str(ROOT/'examples/decisions/action-routing.jsonl'))
    p.add_argument('--output', required=True)
    p.add_argument('--min-probability', type=float, default=0.95)
    p.add_argument('--min-margin', type=float, default=0.5)
    return p.parse_args()


if __name__ == '__main__':
    asyncio.run(evaluate(arguments()))
