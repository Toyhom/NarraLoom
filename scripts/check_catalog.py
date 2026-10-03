"""Browser + live-model acceptance for every installed community adaptation."""

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18090')
    parser.add_argument('--output', default='outputs/validation/community-catalog')
    args = parser.parse_args()
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT / 'outputs/validation'):
        raise ValueError('Output must be inside outputs/validation')
    folder.mkdir(parents=True, exist_ok=True)
    report = {'status': 'running', 'mode': 'live_models', 'packs': [], 'page_errors': []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        context = await browser.new_context(viewport={'width': 1440, 'height': 1080}, locale='zh-CN', accept_downloads=True)
        page = await context.new_page()
        page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
        try:
            await page.goto(args.url)
            await page.locator('[data-catalog-id]').first.wait_for()
            catalog = await (await page.request.get(args.url + '/api/catalog')).json()
            assert len(catalog) >= 3
            await page.locator('.catalog-section').screenshot(path=str(folder / 'catalog-desktop.png'))
            for pack in catalog:
                item = page.locator(f'[data-catalog-id="{pack["id"]}"]')
                await item.get_by_text('阅读改编说明', exact=True).click()
                assert await item.get_by_role('link').get_attribute('href') == pack['source']['url']
                async with page.expect_response(lambda r: r.url.endswith('/install') and r.request.method == 'POST') as info:
                    await item.get_by_role('button', name='加入我的世界并测试', exact=True).click()
                response = await info.value
                assert response.status == 202, await response.text()
                job = await response.json()
                previous = None
                for _ in range(600):
                    job = await (await page.request.get(args.url + '/api/studio/jobs/' + job['id'])).json()
                    status = (job['status'], len(job.get('steps', [])))
                    if status != previous:
                        print(pack['id'], *status, job.get('error') or '', flush=True)
                        previous = status
                    (folder / (pack['id'] + '-job.json')).write_text(json.dumps(job, ensure_ascii=False, indent=2))
                    if job['status'] in {'ready', 'failed', 'cancelled', 'interrupted', 'recovery_required'}:
                        break
                    await asyncio.sleep(2)
                assert job['status'] == 'ready', job
                library = await (await page.request.get(args.url + '/api/studio')).json()
                story = next(s for s in library['stories'] if s['id'] == job['story_id'])
                assert story['test_report']['mode'] == 'live_models'
                assert story['origin']['id'] == pack['id']
                # A repeat click retrieves the same copy; it must not erase edits or duplicate worlds.
                async with page.expect_response(lambda r: r.url.endswith('/install') and r.request.method == 'POST') as info:
                    await item.get_by_role('button', name='加入我的世界并测试', exact=True).click()
                assert (await (await info.value).json())['id'] == job['id']
                exported = await (await page.request.get(args.url + '/api/studio/stories/' + story['id'] + '/export')).json()
                assert 'Permission is hereby granted' in exported['origin']['source']['license_text']
                assert exported['origin']['source']['commit'] == pack['source']['commit']
                report['packs'].append({'id': pack['id'], 'status': 'passed', 'live_steps': len(job['steps']),
                                        'origin_retained': True, 'duplicate_install': 'same_job'})
                (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            await page.reload()
            await page.locator('.studio-world-card').nth(len(catalog)-1).wait_for()
            assert await page.locator('.studio-world-card').count() == len(catalog)
            await page.set_viewport_size({'width': 390, 'height': 844})
            await page.locator('.catalog-section').screenshot(path=str(folder / 'catalog-mobile.png'))
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.set_viewport_size({'width': 1440, 'height': 1080})
            await page.locator('.studio-world-card').last.click()
            card = page.locator('.studio-story-card').first
            await card.get_by_role('button', name='开始这个故事', exact=True).click()
            await page.get_by_label('你的行动').wait_for()
            await page.get_by_label('你的行动').fill('我向在场的人打招呼，想了解眼下的情况。')
            await page.get_by_role('button', name='继续故事', exact=True).click()
            await page.locator('.turn[data-version="1"]').wait_for(timeout=185000)
            await page.screenshot(path=str(folder / 'starter-adventure.png'))
            assert not report['page_errors'], report['page_errors']
            report.update(status='passed', mobile_overflow=False, reload=True, playable_campaign=True)
        except Exception as exc:
            report.update(status='failed', error=str(exc)[:1500])
            await page.screenshot(path=str(folder / 'failure.png'), full_page=True)
            raise
        finally:
            (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            await browser.close()
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
