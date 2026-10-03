"""Component integration: real project Avatar assets, fixture metadata, no GPU job or canonical write."""
import argparse
import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18091')
    parser.add_argument('--reuse', type=Path, required=True, help='Completed i18n browser acceptance folder')
    parser.add_argument('--avatar-dir', type=Path, required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    folder = (ROOT / args.output).resolve()
    package = args.avatar_dir.resolve()
    if not folder.is_relative_to(ROOT / 'outputs/validation') or not package.is_relative_to(ROOT / 'characters'):
        raise ValueError('Use project-local evidence and avatar assets')
    folder.mkdir(parents=True, exist_ok=False)
    previous = json.loads((args.reuse / 'report.json').read_text())
    campaign = previous['campaign']
    base = f"/api/campaigns/{campaign['id']}/branches/{campaign['branch_id']}"
    report = {'status': 'running', 'mode': 'avatar_component_fixture_real_assets', 'new_gpu_generation': False,
              'fixture_scope': 'Inject avatar metadata only into the browser view; canonical server view stays unchanged',
              'asset_requests': [], 'errors': []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        context = await browser.new_context(locale='en', storage_state=str(args.reuse / 'session.local.json'), viewport={'width': 1440, 'height': 1000})
        page = await context.new_page()
        page.on('pageerror', lambda e: report['errors'].append(str(e)))
        before = await (await context.request.get(args.url + base + '/view')).json()
        npc = next(a for a in before['present_actors'] if a['control'] == 'npc')
        assert any(s.get('speaker_id') == npc['id'] for s in before['history'][-1]['segments'])

        async def view_fixture(route):
            response = await route.fetch()
            value = await response.json()
            for actor in value['present_actors']:
                if actor['id'] == npc['id']:
                    actor['avatar_id'] = 'locale_fixture'
            await route.fulfill(response=response, json=value)

        async def assets(route):
            suffix = route.request.url.split('/api/avatars/locale_fixture', 1)[1]
            report['asset_requests'].append(suffix)
            if not suffix:
                await route.fulfill(json={'id': 'locale_fixture', 'state': 'ready', 'progress': 100})
                return
            relative = suffix.removeprefix('/files/')
            path = (package / relative).resolve()
            assert path.is_relative_to(package) and path.is_file()
            await route.fulfill(path=path)

        await page.route('**' + base + '/view', view_fixture)
        await page.route(re.compile(r'/api/avatars/locale_fixture(?:/.*)?$'), assets)
        await page.add_init_script('localStorage.removeItem("rpw-room");localStorage.setItem("rpw-active",'+json.dumps(json.dumps({'cid': campaign['id'], 'bid': campaign['branch_id']}))+');localStorage.setItem("narraloom.locale","en");')
        try:
            await page.goto(args.url)
            await page.locator('canvas[data-ready="true"]').wait_for(timeout=30000)
            await page.wait_for_function("Number(document.querySelector('.npc-theater canvas')?.dataset.frames)>10", timeout=30000)
            await page.evaluate("window.localeCanvas=document.querySelector('.npc-theater canvas')")
            initial_requests = len(report['asset_requests'])
            # Presentation is bounded to 16 s; after it ends a locale switch must not replay it.
            await page.wait_for_timeout(17000)
            evidence = await page.locator('.npc-theater canvas').evaluate('(c)=>({...c.dataset})')
            for locale in ('zh-CN', 'en'):
                await page.locator('.topbar').get_by_label('界面语言 / Interface language').select_option(locale)
                await page.wait_for_timeout(500)
                assert await page.evaluate("window.localeCanvas===document.querySelector('.npc-theater canvas')")
                assert await page.locator('.npc-theater canvas').evaluate('(c)=>({...c.dataset})') == evidence
                assert len(report['asset_requests']) == initial_requests
            await page.screenshot(path=str(folder / 'avatar-en.png'), full_page=True)
            await page.set_viewport_size({'width': 390, 'height': 844})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            await page.screenshot(path=str(folder / 'avatar-en-mobile.png'))
            after = await (await context.request.get(args.url + base + '/view')).json()
            assert after == before
            report.update(status='passed', unchanged_canonical_view=True, no_asset_reload=True, no_animation_replay=True, evidence=evidence)
            assert not report['errors']
        except Exception as exc:
            report.update(status='failed', failure=str(exc))
            await page.screenshot(path=str(folder / 'failure.png'), full_page=True)
            raise
        finally:
            (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
