"""Check three UI languages and retained drafts against a running reference frontend."""

import argparse
import asyncio
import base64
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = {lang: json.loads((ROOT / f'web/src/locales/{lang}.json').read_text()) for lang in ('en', 'zh-CN', 'ja')}
SWITCH = '界面语言 / Interface language'


def label(chinese, locale):
    key = next(k for k, value in CATALOGS['zh-CN'].items() if value.strip() == chinese)
    return CATALOGS[locale][key].strip()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:18090')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT / 'outputs/validation'):
        parser.error('Output must be under outputs/validation')
    folder.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'checks': [], 'errors': []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=['--no-sandbox'])
        context = await browser.new_context(locale='ja-JP', viewport={'width': 1440, 'height': 1000})
        page = await context.new_page()
        page.on('pageerror', lambda error: report['errors'].append(str(error)))
        writes = []
        page.on('request', lambda request: writes.append(request.url) if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} else None)

        async def switch(locale, scope=None):
            count = len(writes)
            await (scope or page.locator('.topbar')).get_by_label(SWITCH, exact=True).select_option(locale)
            await page.wait_for_function('(lang) => document.documentElement.lang === lang', arg=locale)
            await page.wait_for_timeout(150)
            assert len(writes) == count, 'Language switch submitted a write'

        async def picture(name, mobile=False):
            await page.set_viewport_size({'width': 390, 'height': 844} if mobile else {'width': 1440, 'height': 1000})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), name
            await page.screenshot(path=str(folder / f'{name}.png'), full_page=True)

        try:
            await page.goto(args.url)
            await page.locator('.studio-hero').wait_for()
            assert await page.locator('html').get_attribute('lang') == 'ja'
            assert await page.evaluate('getComputedStyle(document.body).backgroundColor') == 'rgb(248, 248, 243)'
            for locale in CATALOGS:
                await switch(locale)
                await page.get_by_role('button', name=label('创建我的世界', locale), exact=True).wait_for()
                await picture('home-' + locale)
                await picture('home-mobile-' + locale, True)
            await page.set_viewport_size({'width': 1440, 'height': 1000})
            await page.get_by_role('button', name=label('创建我的世界', 'ja'), exact=True).click()
            dialog = page.get_by_role('dialog')
            draft = 'A quiet harbor / 静かな港 / 安静的港湾'
            await dialog.get_by_label(label('世界构想', 'ja'), exact=True).fill(draft)
            await dialog.get_by_label(label('创作规模', 'ja'), exact=True).select_option('scene')
            await dialog.get_by_label(label('内容语言', 'ja'), exact=True).select_option('ja')
            for locale in CATALOGS:
                await switch(locale, dialog)
                assert await dialog.get_by_label(label('世界构想', locale), exact=True).input_value() == draft
                assert await dialog.get_by_label(label('内容语言', locale), exact=True).input_value() == 'ja'
                assert await dialog.get_by_label(label('创作规模', locale), exact=True).input_value() == 'scene'
                await picture('creator-' + locale)
                await picture('creator-mobile-' + locale, True)
            await page.set_viewport_size({'width': 1440, 'height': 1000})
            await dialog.locator('.modal-close').click()
            await page.locator('.avatar-studio > details > summary').click()
            await page.get_by_label(label('2D人物描述', 'ja'), exact=True).fill(draft)
            png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aT1cAAAAASUVORK5CYII=')
            await page.get_by_label(label('2D人物参考图', 'ja'), exact=True).set_input_files(
                {'name': 'draft.png', 'mimeType': 'image/png', 'buffer': png})
            for locale in CATALOGS:
                await switch(locale)
                assert await page.get_by_label(label('2D人物描述', locale), exact=True).input_value() == draft
                assert await page.get_by_label(label('2D人物参考图', locale), exact=True).evaluate('(el) => el.files[0].name') == 'draft.png'
            other = await context.new_page()
            await other.goto(args.url)
            await switch('en')
            await other.wait_for_function("document.documentElement.lang === 'en'")
            await switch('ja')
            await other.wait_for_function("document.documentElement.lang === 'ja'")
            await page.reload()
            await page.locator('.studio-hero').wait_for()
            assert await page.locator('html').get_attribute('lang') == 'ja'
            assert not report['errors'], report['errors']
            report.update(status='passed', checks=['Japanese browser default', 'three desktop/mobile languages',
                'light background and no horizontal overflow', 'draft/scale/content-language preservation',
                'selected file and avatar draft preservation', 'switches perform no writes', 'cross-tab sync and reload'])
        except Exception as error:
            report.update(status='failed', failure=str(error))
            await page.screenshot(path=str(folder / 'failure.png'), full_page=True)
            raise
        finally:
            (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
