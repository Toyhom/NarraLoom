"""Serve the reviewed Jev-Style adapter, optionally run the framework's HTTP evaluation and exit.

Shared-server GPU invocation must run through GPUQ under the project owner.
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import threading
import time
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REVISION = 'ef86def93c4b8c775523bea6812784a36b2b6d8a'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True, help='Reviewed upstream checkout')
    p.add_argument('--model-root', type=Path, required=True)
    p.add_argument('--size', choices=['0.8B', '2B'], default='0.8B')
    p.add_argument('--port', type=int, default=18110)
    p.add_argument('--device', choices=['cpu', 'cuda'], default='cuda')
    p.add_argument('--dtype', choices=['float32', 'bfloat16'], default='float32')
    p.add_argument('--cuda-graphs', action='store_true')
    p.add_argument('--evaluate-output', type=Path)
    p.add_argument('--keep-serving', action='store_true')
    p.add_argument('--max-runtime-s', type=int, default=1800)
    args = p.parse_args()
    from download_jev import REVISIONS
    source = args.source.resolve(); revision = REVISIONS[args.size]
    pin = json.loads((ROOT/'resources/jev-style-source-pin.json').read_text())
    if pin['revision'] != SOURCE_REVISION:
        raise ValueError('Unexpected upstream source revision')
    actual = {str(path.relative_to(source)) for path in (source/'jev_style').rglob('*.py')}
    if actual != set(pin['files']):
        raise ValueError('Upstream Python source file set differs from reviewed pin')
    for name, expected_hash in pin['files'].items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest() != expected_hash:
            raise ValueError('Upstream source differs from reviewed pin: '+name)
    folder = args.model_root/f'chaoliangUNSW/Jev-Style-{args.size}-Decision-v3'/revision
    receipt = json.loads((folder/'narraloom-download.json').read_text())
    if receipt.get('revision') != revision or not receipt.get('complete'):
        raise ValueError('Run download_jev.py first')
    for name, info in receipt['files'].items():
        if (folder/name).stat().st_size != info['bytes']:
            raise ValueError('Incomplete model file: '+name)
    # Review pin and small runtime hash, without re-hashing complete shared weights on every launch.
    runtime_hash = hashlib.sha256((folder/'jev_style_decision.py').read_bytes()).hexdigest()
    if runtime_hash != receipt['files']['jev_style_decision.py']['sha256']:
        raise ValueError('Runtime differs from verified pinned download')
    sys.path.insert(0, str(source))
    from jev_style.adapter import build_adapter
    from jev_style.server import create_app
    versions = {name: version(name) for name in ('torch', 'transformers', 'tokenizers', 'numpy')}
    if args.size == '2B':
        from packaging.version import Version
        if Version(versions['transformers']) < Version('5.17.0'):
            raise RuntimeError("The pinned 2B cache runtime needs Transformers >=5.17; install the project's [jev] extra in this model environment")
    print("Loading pinned runtime and weights", versions, flush=True)
    started = time.monotonic()
    adapter = build_adapter('torch', release=args.size.lower(), model_dir=folder,
                            device=args.device, dtype=args.dtype, cuda_graphs=args.cuda_graphs)
    import torch
    evidence = {'source_revision': SOURCE_REVISION, 'model_revision': revision, 'runtime_sha256': runtime_hash,
                'node': os.environ.get('GPUQ_NODE'), 'job': os.environ.get('GPUQ_JOB_REF'),
                'torch': torch.__version__, 'packages': versions, 'python': sys.version.split()[0], 'dtype': args.dtype, 'cuda_graphs': args.cuda_graphs,
                'load_s': time.monotonic()-started, 'gpu': torch.cuda.get_device_name() if args.device == 'cuda' else None,
                'gpu_allocated_bytes': torch.cuda.memory_allocated() if args.device == 'cuda' else 0}
    print(json.dumps(evidence), flush=True)
    server = uvicorn.Server(uvicorn.Config(create_app(adapter, ext_dir=None), host='127.0.0.1', port=args.port, log_level='warning'))
    worker = threading.Thread(target=server.run, daemon=True)
    worker.start()
    deadline = time.monotonic()+30
    while not server.started:
        if not worker.is_alive() or time.monotonic() > deadline:
            raise RuntimeError('Server did not start')
        time.sleep(0.1)
    timer = threading.Timer(args.max_runtime_s, lambda: setattr(server, 'should_exit', True)); timer.daemon = True; timer.start()
    try:
        if args.evaluate_output:
            from evaluate_decisions import evaluate
            params = SimpleNamespace(url=f'http://127.0.0.1:{args.port}/v1', model=adapter.model_id, revision=revision,
                key_env='NARRALOOM_DECISION_KEY', cases=ROOT/'examples/decisions/action-routing.jsonl',
                output=args.evaluate_output, min_probability=0.95, min_margin=0.5)
            # Protocol smoke includes all three question types, separate from routing quality.
            smoke = httpx.post(params.url+'/systemone', json={'model': adapter.model_id, 'state': 'The door is closed.',
                'questions': {'closed': {'type': 'noul', 'instructions': 'Is the door closed?'},
                              'risk': {'type': 'score', 'instructions': 'How dangerous is this scene?',
                                       'criteria': ['calm', 'uncertain', 'dangerous']}}}, timeout=90, trust_env=False)
            smoke.raise_for_status()
            from roleplay_world.decisions import DecisionRequest, validate_response
            validate_response(DecisionRequest.model_validate({k:v for k,v in json.loads(smoke.request.content).items() if k != 'model'}), smoke.json())
            asyncio.run(evaluate(params))
            (args.evaluate_output/'deployment.json').write_text(json.dumps(evidence, indent=2))
            (args.evaluate_output/'protocol-smoke.json').write_text(json.dumps(smoke.json(), indent=2))
        if args.keep_serving or not args.evaluate_output:
            print('Serving until stopped or max-runtime expires', flush=True)
            worker.join()
    finally:
        server.should_exit = True; worker.join(timeout=10); timer.cancel()
        adapter.worker.shutdown(wait=True)


if __name__ == '__main__':
    main()
