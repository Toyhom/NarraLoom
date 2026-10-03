"""A generation-model label baseline on the same router inputs, without invented probabilities."""
import argparse
import asyncio
import hashlib
import json
import statistics
from pathlib import Path
from typing import Literal

from pydantic import create_model

from roleplay_world.contracts import Contract, DomainError
from roleplay_world.gateway import ModelGateway
from roleplay_world.routing import ROUTE_INSTRUCTIONS, move_request

ROOT = Path(__file__).resolve().parents[1]


async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, default=ROOT/'configs/models.local.json')
    p.add_argument('--role', default='game_master')
    p.add_argument('--cases', type=Path, default=ROOT/'examples/decisions/action-routing.jsonl')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    gateway = ModelGateway(json.loads(args.config.read_text()), args.output/'traces')
    cfg = gateway.role_config(args.role); data = args.cases.read_bytes()
    cases = [json.loads(line) for line in data.decode().splitlines() if line]
    report = {'status':'running','routing_instructions_sha256':hashlib.sha256(ROUTE_INSTRUCTIONS.encode()).hexdigest(), 'dataset_sha256':hashlib.sha256(data).hexdigest(),'requested_model':cfg['model'],
              'scope':'Typed classification only, same inputs as System One; not full game-master turns. No probability/calibration claims.', 'rows':[]}
    for case in cases:
        for reverse in (False, True):
            exits = list(reversed(case['exits'])) if reverse else case['exits']
            request = move_request(case['text'],exits); question = request.questions['route']
            schema = create_model('RoutingLabel',__base__=Contract,choice=(Literal[tuple(question.criteria)],...))
            budget = {'calls':0,'repairs':0,'traces':[],'max_calls':1,'max_repairs':0}
            row = {'id':case['id'],'reversed':reverse,'language':case['language'],'expected':case['expected']}
            try:
                result = await gateway.generate(args.role,question.instructions,
                    {'state':request.state,'criteria':question.criteria},schema,case['id']+str(int(reverse)),budget)
                choice = 'defer' if result.choice == 'defer' else exits[int(result.choice.removeprefix('move_'))]['id']
                row.update(choice=choice,correct=choice==case['expected'],duration_s=budget['traces'][-1]['duration_s'],
                           response_model=budget['traces'][-1]['response_model'],usage=budget['traces'][-1]['usage'])
            except DomainError as exc:
                row['error'] = exc.code
            report['rows'].append(row)
            (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    rows = report['rows']; valid = [r for r in rows if 'choice' in r]
    report.update(status='completed',metrics={'cases':len(rows),'valid_responses':len(valid),'failures':len(rows)-len(valid),
        'end_to_end_accuracy':sum(r['correct'] for r in valid)/len(rows),
        'always_defer_accuracy':sum(r['expected']=='defer' for r in rows)/len(rows),
        'latency_p50_s':statistics.median(r['duration_s'] for r in valid) if valid else None,
        'latency_p95_s':sorted(r['duration_s'] for r in valid)[int((len(valid)-1)*.95)] if valid else None,
        'prompt_tokens':sum((r.get('usage') or {}).get('prompt_tokens',0) for r in rows),
        'completion_tokens':sum((r.get('usage') or {}).get('completion_tokens',0) for r in rows)},
        option_order_flips=sum(a['choice']!=b['choice'] for a,b in zip(rows[::2],rows[1::2]) if 'choice' in a and 'choice' in b))
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    asyncio.run(main())
