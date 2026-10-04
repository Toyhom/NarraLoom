"""Check that tracked source excludes local records, credentials and generated output."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PARTS = {'.local', '.cache', 'secrets', 'outputs', 'scratch', 'node_modules', '__pycache__'}
PRIVATE_NAMES = {'WORK_LOG.md', 'READING_LOG.md', 'HANDOFF.md', 'DEPLOYMENT_LOG.md', '.env', '.local.env'}
PATTERNS = {
    'server path': rb'/data/L\d{6,}|/aoss[0-9]{3}(?:/|\b)',
    'private key': rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY',
    'API token': rb'\bsk-[a-zA-Z0-9_-]{20,}',
    'GitHub token': rb'\bgh[pousr]_[a-zA-Z0-9]{25,}',
}


def main():
    names = subprocess.check_output(['git', '-c', f'safe.directory={ROOT}', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    errors = []
    count = 0
    for name in filter(None, names):
        path = ROOT / name
        if not path.is_file():
            continue
        count += 1
        relative = Path(name)
        if relative.parts[0] == 'docs' or PRIVATE_PARTS.intersection(relative.parts) or relative.name in PRIVATE_NAMES:
            errors.append(f'{name}: local material in public source')
        data = path.read_bytes()
        for label, pattern in PATTERNS.items():
            if re.search(pattern, data):
                errors.append(f'{name}: {label}')
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'Checked {count} tracked public files')


if __name__ == '__main__':
    main()
