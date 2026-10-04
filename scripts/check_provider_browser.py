"""Check protocol selection, three languages and saved settings on a test workspace.

Uses a fresh browser session and placeholder credentials; makes no model calls.
"""

import argparse
import asyncio
import json
from pathlib import Path

from browser_navigation import module, tab
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'errors': [], 'checks': []}
    catalogs = {locale: {key: value.strip() for key, value in json.loads((ROOT / f'web/src/locales/{locale}.json').read_text()).items()} for locale in ('en', 'zh-CN', 'ja')}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=['--no-sandbox'])
        page = await browser.new_page(locale='en-US', viewport={'width': 1440, 'height': 1100})
        page.on('pageerror', lambda error: report['errors'].append(str(error)))
        try:
            await page.goto(args.url)
            await page.get_by_role('button', name=catalogs['en']['ProviderPanel.032'], exact=True).click()
            dialog = page.get_by_role('dialog')
            await dialog.get_by_label(catalogs['en']['provider.protocol'], exact=True).select_option('anthropic')
            await dialog.get_by_label(catalogs['en']['ProviderPanel.028'], exact=True).fill('https://provider.invalid/v1')
            await dialog.get_by_label(catalogs['en']['ProviderPanel.004'], exact=True).fill('fixture-model')
            await dialog.get_by_label(catalogs['en']['ProviderPanel.005'], exact=True).fill('test-browser-key')
            await dialog.locator('summary').filter(has_text=catalogs['en']['provider.generation']).click()
            await dialog.get_by_label(catalogs['en']['provider.omit_temperature'], exact=True).check()
            for locale, catalog in catalogs.items():
                await dialog.get_by_label('界面语言 / Interface language', exact=True).select_option(locale)
                assert await dialog.get_by_label(catalog['provider.protocol'], exact=True).input_value() == 'anthropic'
                assert await dialog.get_by_label(catalog['provider.omit_temperature'], exact=True).is_checked()
                assert await dialog.get_by_label(catalog['ProviderPanel.005'], exact=True).input_value() == 'test-browser-key'
                await page.screenshot(path=str(args.output / f'{locale}.png'), full_page=True)
                report['checks'].append('locale-' + locale)
            await dialog.get_by_label('界面语言 / Interface language', exact=True).select_option('en')

            async def save():
                async with page.expect_response(lambda r: r.url.endswith('/api/settings/provider') and r.request.method == 'PUT') as response:
                    await dialog.get_by_role('button', name=catalogs['en']['ProviderPanel.010'], exact=True).click()
                result = await response.value
                assert result.status == 200
                value = await result.json()
                assert 'test-browser-key' not in json.dumps(value)
                return value

            value = await save()
            assert value['backend'] == 'anthropic' and value['has_key'] and value['omit_temperature']
            await dialog.get_by_label(catalogs['en']['provider.protocol'], exact=True).select_option('openai-responses')
            value = await save()
            assert value['backend'] == 'openai-responses' and not value['has_key']
            await tab(page, 'provider', 'modules')
            await dialog.locator('.engine-bindings > summary').click()
            await dialog.get_by_role('button', name=catalogs['en']['EngineBindings.017'], exact=True).click()
            await dialog.get_by_label('provider_1 backend').select_option('anthropic')
            await module(page, 'narrator')
            await dialog.get_by_label('narrator provider').select_option('provider_1')
            await dialog.get_by_label('narrator model', exact=True).fill('fixture-narrator')
            assert await dialog.get_by_label('action_router provider').locator('option[value="provider_1"]').count() == 0
            value = await save()
            assert value['providers']['provider_1']['backend'] == 'anthropic'
            assert value['bindings']['narrator']['provider'] == 'provider_1'
            await page.set_viewport_size({'width': 390, 'height': 844})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            await page.screenshot(path=str(args.output / 'mobile.png'), full_page=True)
            await page.reload()
            await page.get_by_role('button', name=catalogs['en']['ProviderPanel.032'], exact=True).click()
            assert await page.get_by_label(catalogs['en']['provider.protocol'], exact=True).input_value() == 'openai-responses'
            assert not report['errors'], report['errors']
            report.update(status='passed', checks=report['checks'] + ['protocol-save', 'credential-reset', 'module-compatibility', 'mobile', 'reload'])
        except Exception as exc:
            report.update(status='failed', failure=str(exc))
            await page.screenshot(path=str(args.output / 'failure.png'), full_page=True)
            raise
        finally:
            (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
