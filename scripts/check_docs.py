"""Check public guide navigation, local links and translated page coverage."""

import argparse
import ast
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def api_routes():
    methods = {'get', 'post', 'put', 'delete', 'patch', 'head', 'options'}
    routes = set()
    for node in ast.walk(ast.parse((ROOT / 'src/roleplay_world/app.py').read_text())):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == 'app'
                    and decorator.func.attr in methods and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)):
                routes.add((decorator.func.attr.upper(), decorator.args[0].value, node.name))
    return routes



def markdown_anchors(source):
    anchors = set(re.findall(r'<a\s+(?:id|name)="([^"]+)"', source))
    seen = {}
    for heading in re.findall(r'^#{1,6} (.+)$', source, re.MULTILINE):
        slug = re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-')
        suffix = seen.get(slug, 0)
        anchors.add(slug + (f'-{suffix}' if suffix else ''))
        seen[slug] = suffix + 1
    return anchors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-api', action='store_true', help='Update the HTTP API table from application routes')
    args = parser.parse_args()
    api_page = ROOT / 'guides/reference/api.md'
    routes = api_routes()
    if args.write_api:
        header = '| Method | Route | Handler |'
        intro = api_page.read_text().split(header)[0]
        rows = ['| `' + method + '` | `' + route + '` | `' + handler + '` |'
                for method, route, handler in sorted(routes, key=lambda item: (item[1], item[0]))]
        api_page.write_text(intro + header + '\n| --- | --- | --- |\n' + '\n'.join(rows) + '\n')
    files = [*ROOT.glob('README*.md'), ROOT / 'NOTICE.md', ROOT / 'CONTRIBUTING.md',
             ROOT / 'SECURITY.md', ROOT / 'AGENTS.md', ROOT / '.github/PULL_REQUEST_TEMPLATE.md',
             ROOT / 'media/README.md', ROOT / 'vendor/avatar_worker/ADAPTER.md',
             ROOT / 'examples/README.md', ROOT / 'resources/community/README.md',
             *sorted((ROOT / 'guides').rglob('*.md'))]
    errors = []
    documented = set(re.findall(r'\| `(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)` \| `([^`]+)` \| `([^`]+)`',
                                api_page.read_text()))
    if documented != routes:
        errors.append(f'HTTP API table differs from runtime routes: missing={sorted(routes-documented)}, '
                      f'stale={sorted(documented-routes)}; run python scripts/check_docs.py --write-api')
    example_count = 0
    for path in files:
        source = path.read_text()
        for language, body in re.findall(r'^```(json|python)\n(.*?)^```', source, re.MULTILINE | re.DOTALL):
            example_count += 1
            try:
                if language == 'json':
                    json.loads(body)
                else:
                    compile(body, str(path), 'exec', flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            except (ValueError, SyntaxError) as exc:
                errors.append(f'{path.relative_to(ROOT)}: invalid {language} example: {exc}')
        for script in re.findall(r'(?:python3?|bash|node)\s+((?:scripts|examples)/[\w./-]+\.(?:py|sh|mjs))', source):
            if not (ROOT / script).is_file():
                errors.append(f'{path.relative_to(ROOT)}: missing command script {script}')
        for link in re.findall(r'\]\(([^)\s]+)(?:\s+"[^"]*")?\)', source):
            parsed = urlsplit(link.strip('<>'))
            if parsed.scheme or not parsed.path:
                continue
            target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
            if not target.is_relative_to(ROOT) or not target.exists():
                errors.append(f'{path.relative_to(ROOT)}: missing {link}')
            elif parsed.fragment and target.suffix == '.md' and unquote(parsed.fragment) not in markdown_anchors(target.read_text()):
                errors.append(f'{path.relative_to(ROOT)}: missing anchor {link}')
    for guide in (ROOT / 'guides').glob('*.md'):
        for locale in ('zh-CN', 'ja'):
            if not (guide.parent / locale / guide.name).exists():
                errors.append(f'Missing {locale} guide: {guide.name}')
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'Checked {len(files)} public documents, {len(routes)} API routes, {example_count} code examples and localized guides')


if __name__ == '__main__':
    main()
