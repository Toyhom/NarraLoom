"""Check public guide navigation, local links and translated page coverage."""

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = [*ROOT.glob('README*.md'), ROOT / 'NOTICE.md', ROOT / 'CONTRIBUTING.md',
             ROOT / 'SECURITY.md', ROOT / 'examples/README.md', ROOT / 'resources/community/README.md',
             *sorted((ROOT / 'guides').rglob('*.md'))]
    errors = []
    for path in files:
        source = path.read_text()
        for link in re.findall(r'\]\(([^)\s]+)(?:\s+"[^"]*")?\)', source):
            parsed = urlsplit(link.strip('<>'))
            if parsed.scheme or not parsed.path:
                continue
            target = (path.parent / unquote(parsed.path)).resolve()
            if not target.is_relative_to(ROOT) or not target.exists():
                errors.append(f'{path.relative_to(ROOT)}: missing {link}')
    for guide in (ROOT / 'guides').glob('*.md'):
        for locale in ('zh-CN', 'ja'):
            if not (guide.parent / locale / guide.name).exists():
                errors.append(f'Missing {locale} guide: {guide.name}')
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'Checked {len(files)} public documents and localized guide coverage')


if __name__ == '__main__':
    main()
