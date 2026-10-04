"""Configure and test a real embedding provider through the three-language frontend."""

import argparse
import asyncio
import json
from pathlib import Path

from browser_navigation import module, tab
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def run(args):
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    catalogs = {locale: {key: value.strip() for key, value in json.loads((ROOT / f'web/src/locales/{locale}.json').read_text()).items()}
                for locale in ('en', 'zh-CN', 'ja')}
    report = {'status': 'running', 'errors': [], 'checks': []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page(locale='en', viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda error: report['errors'].append(str(error)))
        try:
            await page.goto(args.url)
            await page.get_by_role('button', name=catalogs['en']['ProviderPanel.032'], exact=True).click()
            await page.get_by_label(catalogs['en']['ProviderPanel.028'], exact=True).fill('http://127.0.0.1:9/v1')
            await page.get_by_label(catalogs['en']['ProviderPanel.004'], exact=True).fill('generation-configured-separately')
            await tab(page, 'provider', 'modules')
            await page.locator('.engine-bindings > summary').click()
            await page.get_by_role('button', name=catalogs['en']['EngineBindings.017'], exact=True).click()
            await page.get_by_label('provider_1 backend', exact=True).select_option('openai_embedding')
            await page.get_by_label('provider_1 URL', exact=True).fill(args.embedding_url)
            await module(page, 'memory_embedding')
            await page.get_by_label('memory_embedding provider', exact=True).select_option('provider_1')
            await page.get_by_label('memory_embedding model', exact=True).fill(args.embedding_model)
            await page.get_by_label('Memory retrieval mode', exact=True).select_option('hybrid')
            assert await page.get_by_label('game_master provider', exact=True).locator('option[value="provider_1"]').count() == 0
            for locale in catalogs:
                await page.get_by_role('dialog').get_by_label('界面语言 / Interface language', exact=True).select_option(locale)
                await page.get_by_role('heading', name=catalogs[locale]['ProviderPanel.001'], exact=True).wait_for()
                assert await page.get_by_label('memory_embedding model', exact=True).input_value() == args.embedding_model
                assert await page.get_by_label('Memory retrieval mode', exact=True).input_value() == 'hybrid'
                await page.set_viewport_size({'width': 390, 'height': 844})
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                await page.screenshot(path=str(folder / f'memory-{locale}.png'), full_page=True)
                await page.set_viewport_size({'width': 1440, 'height': 1000})
            report['checks'].append('trilingual_drafts_capability_filter_and_mobile_layout')
            await page.get_by_role('dialog').get_by_label('界面语言 / Interface language', exact=True).select_option('en')
            async with page.expect_response(lambda response: response.url.endswith('/api/settings/provider') and response.request.method == 'PUT') as response:
                await page.get_by_role('button', name=catalogs['en']['ProviderPanel.010'], exact=True).click()
            saved = await (await response.value).json()
            assert saved['memory_policy']['mode'] == 'hybrid'
            section = page.locator('.module-binding').filter(has=page.get_by_label('memory_embedding model', exact=True))
            async with page.expect_response(lambda response: response.url.endswith('/api/engines/memory_embedding/check'), timeout=120000) as response:
                await section.get_by_role('button', name=catalogs['en']['EngineBindings.010'], exact=True).click()
            report['diagnostic'] = await (await response.value).json()
            assert report['diagnostic']['protocol_passed'], report['diagnostic']
            report['checks'].append('saved_provider_real_embedding_protocol_check')
            await page.reload()
            await page.get_by_role('button', name=catalogs['en']['ProviderPanel.032'], exact=True).click()
            await tab(page, 'provider', 'modules')
            await page.locator('.engine-bindings > summary').click()
            assert await page.get_by_label('Memory retrieval mode', exact=True).input_value() == 'hybrid'
            await page.get_by_label('provider_1 backend', exact=True).select_option('openai')
            assert await page.get_by_label('memory_embedding provider', exact=True).input_value() == ''
            async with page.expect_response(lambda response: response.url.endswith('/api/settings/provider') and response.request.method == 'PUT') as response:
                await page.get_by_role('button', name=catalogs['en']['ProviderPanel.010'], exact=True).click()
            saved = await (await response.value).json()
            assert saved['memory_policy']['mode'] == 'lexical' and 'memory_embedding' not in saved['bindings']
            assert not report['errors']
            report['checks'].append('reload_and_provider_capability_change')
            report['status'] = 'passed'
        except BaseException as exc:
            report.update(status='failed', error_type=type(exc).__name__)
            await page.screenshot(path=str(folder / 'failure.png'), full_page=True)
            raise
        finally:
            (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            await browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--embedding-url', required=True)
    parser.add_argument('--embedding-model', required=True)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    main()
