"""Build the static demonstration player from final, checksum-pinned media."""

import argparse
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'media/demo'
    for name in ('index.html', 'demo.js', 'demo.css'):
        shutil.copyfile(source / name, folder / name)
    for locale in ('en', 'zh-CN', 'ja'):
        shutil.copyfile(ROOT / f'media/poster-{locale}.jpg', folder / f'poster-{locale}.jpg')
    for asset in json.loads((source / 'assets.json').read_text()):
        with urllib.request.urlopen(asset['url'], timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != asset['sha256']:
            raise ValueError(f"Media checksum mismatch: {asset['file']}")
        (folder / asset['file']).write_bytes(data)
    print(f'Built demonstration player: {folder}')


if __name__ == '__main__':
    main()
