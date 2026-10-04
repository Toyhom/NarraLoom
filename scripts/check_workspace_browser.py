"""Check task navigation, retained drafts and configured/unprobed model access.

Uses a fresh browser session and the built-in world; makes no model calls.
"""

import argparse
import asyncio
import base64
import json
from pathlib import Path

from browser_navigation import expand, tab
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'checks': [], 'errors': []}
    catalogs = {lang: json.loads((ROOT / f'web/src/locales/{lang}.json').read_text()) for lang in ('en', 'zh-CN', 'ja')}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=['--no-sandbox'])
        context = await browser.new_context(locale='en', viewport={'width': 1440, 'height': 1000})
        page = await context.new_page()
        page.on('pageerror', lambda error: report['errors'].append(str(error)))
        try:
            # Native providers may be configured without supporting model-list probes.
            await page.route('**/api/status', lambda route: route.fulfill(json={
                'ready': None, 'configured': True, 'models': [], 'message': 'Configured, unprobed'}))
            await page.goto(args.url)
            await page.locator('#workspace-tab-worlds').wait_for()
            assert await page.get_by_role('button', name=catalogs['en']['Studio.007'].strip(), exact=True).is_enabled()
            await page.locator('#workspace-tab-worlds').focus()
            for key, selected in [('ArrowRight', 'sessions'), ('End', 'tools'), ('Home', 'worlds'), ('ArrowLeft', 'tools')]:
                await page.keyboard.press(key)
                active = page.locator('#workspace-tab-' + selected)
                assert await active.get_attribute('aria-selected') == 'true'
                assert await active.evaluate('e => e === document.activeElement')
                assert await page.locator('[id^="workspace-panel-"]:visible').count() == 1
            report['checks'].append('Keyboard tabs, panel isolation and configured/unprobed creation access')
            await tab(page, 'workspace', 'avatars')
            await expand(page.locator('.avatar-studio > details'))
            await page.get_by_label(catalogs['en']['AvatarStudio.017'].strip(), exact=True).fill('An original character 原文')
            png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aT1cAAAAASUVORK5CYII=')
            await page.get_by_label(catalogs['en']['AvatarStudio.018'].strip(), exact=True).set_input_files(
                {'name': 'retained.png', 'mimeType': 'image/png', 'buffer': png})
            for lang, catalog in catalogs.items():
                await page.locator('.topbar select').select_option(lang)
                for section in ('worlds', 'sessions', 'community', 'tools', 'avatars'):
                    await tab(page, 'workspace', section)
                    assert await page.locator('[id^="workspace-panel-"]:visible').count() == 1
                    for width in (1440, 390):
                        await page.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
                        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), (lang, section, width)
                    await page.screenshot(path=str(args.output / f'{lang}-{section}-mobile.png'), full_page=True)
                    await page.set_viewport_size({'width': 1440, 'height': 1000})
                assert await page.get_by_label(catalog['AvatarStudio.017'].strip(), exact=True).input_value() == 'An original character 原文'
                assert await page.get_by_label(catalog['AvatarStudio.018'].strip(), exact=True).evaluate('e => e.files[0].name') == 'retained.png'
            report['checks'].append('All five sections at desktop/mobile sizes in three languages; file and text drafts retained')
            await page.locator('.topbar select').select_option('en')
            await page.get_by_role('button', name=catalogs['en']['ProviderPanel.032'].strip(), exact=True).click()
            await page.get_by_label(catalogs['en']['ProviderPanel.004'].strip(), exact=True).fill('unsaved-model')
            await page.get_by_label(catalogs['en']['ProviderPanel.005'].strip(), exact=True).fill('draft-only')
            for section in ('modules', 'usage', 'connection'):
                await tab(page, 'provider', section)
                assert await page.locator('[id^="provider-panel-"]:visible').count() == 1
            assert await page.get_by_label(catalogs['en']['ProviderPanel.004'].strip(), exact=True).input_value() == 'unsaved-model'
            assert await page.get_by_label(catalogs['en']['ProviderPanel.005'].strip(), exact=True).input_value() == 'draft-only'
            await page.locator('.provider-modal .modal-close').click()
            await tab(page, 'workspace', 'worlds')
            await page.get_by_role('button', name=catalogs['en']['Studio.061'].strip(), exact=False).click()
            await page.locator('.composer textarea').wait_for()
            await tab(page, 'inspector', 'memory')
            await expand(page.locator('.note-editor'))
            await page.get_by_label(catalogs['en']['MemoryPanel.016'].strip(), exact=True).fill('A compass for tomorrow.')
            await tab(page, 'inspector', 'actions')
            await tab(page, 'inspector', 'character')
            await tab(page, 'inspector', 'memory')
            assert await page.get_by_label(catalogs['en']['MemoryPanel.016'].strip(), exact=True).input_value() == 'A compass for tomorrow.'
            await page.get_by_role('button', name=catalogs['en']['MemoryPanel.013'].strip(), exact=True).click()
            await page.locator('.turn[data-version="1"]').wait_for()
            await expand(page.locator('.world-explorer'))
            await page.locator('.world-map').wait_for()
            # Long memory content must scroll without collapsing the navigation.
            await page.set_viewport_size({'width': 1440, 'height': 720})
            bounds = await page.locator('.player-sidebar .section-tabs').bounding_box()
            assert bounds and bounds['height'] >= 44, bounds
            await page.locator('.player-sidebar').evaluate('e => e.scrollTop = 0')
            await tab(page, 'inspector', 'character')
            await tab(page, 'inspector', 'memory')
            await page.set_viewport_size({'width': 1440, 'height': 1000})
            await page.screenshot(path=str(args.output / 'play-desktop.png'))
            await page.set_viewport_size({'width': 390, 'height': 844})
            await page.get_by_role('button', name=catalogs['en']['main.023'].strip(), exact=True).click()
            await page.screenshot(path=str(args.output / 'play-mobile.png'))
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            bounds = await page.locator('.player-sidebar .section-tabs').bounding_box()
            assert bounds and bounds['height'] >= 44, bounds
            report['checks'].append('Provider drafts, inspector note drafts, committed note and map preserved')
            assert not report['errors'], report['errors']
            report['status'] = 'passed'
        except Exception as exc:
            report.update(status='failed', failure=str(exc))
            await page.screenshot(path=str(args.output / 'failure.png'), full_page=True)
            raise
        finally:
            (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
