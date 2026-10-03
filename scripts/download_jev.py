"""Download a pinned Jev-Style release without loading code or creating HF locks on model storage."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
REVISIONS = {'0.8B': 'b023d1f9c7858fbf01504577a3bfc349ea5c7385',
             '2B': '5bad2d53ae04e832e2b30aa2a89bec76ec03deec'}
FILES = {'LICENSE', 'NOTICE', 'README.md', 'chat_template.jinja', 'config.json', 'generation_config.json',
         'jev_style_decision.py', 'readout_config.json', 'release_config.json', 'requirements.txt',
         'tokenizer.json', 'tokenizer_config.json', 'model.safetensors.index.json'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--size', choices=REVISIONS, default='0.8B')
    p.add_argument('--model-root', type=Path, required=True)
    args = p.parse_args()
    repo = f'chaoliangUNSW/Jev-Style-{args.size}-Decision-v3'; revision = REVISIONS[args.size]
    folder = args.model_root/repo/revision
    folder.mkdir(parents=True, exist_ok=True)
    locks = ROOT/'scratch/jev-download'; locks.mkdir(parents=True, exist_ok=True)
    # Coordination state stays in the project, not on object storage.
    with (locks/(args.size+'.lock')).open('w') as lock, httpx.Client(follow_redirects=True, timeout=120) as client:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        url = f'https://huggingface.co/{repo}/resolve/{revision}/'
        manifest_response = client.get(url+'manifest.json'); manifest_response.raise_for_status()
        manifest = manifest_response.json()
        receipt_path = folder/'narraloom-download.json'
        receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {'repo': repo, 'revision': revision, 'files': {}}
        for name, info in manifest['files'].items():
            if '/' in name or (name not in FILES and not name.endswith('.safetensors')):
                continue
            path = folder/name
            if receipt['files'].get(name) == info and path.exists() and path.stat().st_size == info['bytes']:
                print('reuse', name, flush=True); continue
            print('download', name, info['bytes'], flush=True)
            digest = hashlib.sha256(); length = 0
            with client.stream('GET', url+name) as response, path.open('wb') as output:
                response.raise_for_status()
                for chunk in response.iter_bytes(1024*1024):
                    output.write(chunk); digest.update(chunk); length += len(chunk)
            if length != info['bytes'] or digest.hexdigest() != info['sha256']:
                raise RuntimeError(f'Integrity mismatch for {name}; no ready receipt written for this file')
            receipt['files'][name] = info
            receipt_path.write_text(json.dumps(receipt, indent=2))
        (folder/'manifest.json').write_text(manifest_response.text)
        receipt['complete'] = True; receipt_path.write_text(json.dumps(receipt, indent=2))
        print(folder, flush=True)


if __name__ == '__main__':
    main()
