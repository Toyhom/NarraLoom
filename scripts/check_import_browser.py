"""Browser import, loss-report review, model playtest and playable restore."""

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18091')
    parser.add_argument('--source', required=True, help='Native world/story JSON export to import')
    parser.add_argument('--output', default='outputs/validation/import-browser')
    args = parser.parse_args()
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT / 'outputs/validation'):
        raise ValueError('Output outside validation folder')
    folder.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'mode': 'live_models', 'errors': []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page(locale='zh-CN', viewport={'width': 1440, 'height': 1080})
        page.on('pageerror', lambda e: report['errors'].append(str(e)))
        try:
            await page.goto(args.url)
            await page.get_by_label('导入角色卡或世界书').set_input_files(str(ROOT / args.source))
            await page.get_by_role('button', name='还原并自动测试', exact=True).wait_for()
            await page.locator('.import-studio').screenshot(path=str(folder / 'preview.png'))
            async with page.expect_response(lambda r: r.url.endswith('/convert') and r.request.method == 'POST') as info:
                await page.get_by_role('button', name='还原并自动测试', exact=True).click()
            response = await info.value
            assert response.status == 202, await response.text()
            job = await response.json()
            for _ in range(600):
                job = await (await page.request.get(args.url + '/api/studio/jobs/' + job['id'])).json()
                if job['status'] in {'ready', 'failed', 'cancelled', 'interrupted', 'recovery_required'}:
                    break
                await asyncio.sleep(2)
            (folder / 'job.json').write_text(json.dumps(job, ensure_ascii=False, indent=2))
            assert job['status'] == 'ready', job.get('error')
            assert any(s['input'].startswith('我前往') for s in job['steps'])
            assert any(s['input'].startswith('我仔细调查') for s in job['steps'])
            await page.reload()
            story = page.locator('[data-story-id="' + job['story_id'] + '"]')
            await story.locator('.conversion-report summary').click()
            assert await story.locator('.conversion-row').count() > 0
            await page.set_viewport_size({'width': 390, 'height': 844})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.locator('.import-studio').screenshot(path=str(folder / 'mobile.png'))
            await page.set_viewport_size({'width': 1440, 'height': 1080})
            async with page.expect_download() as download:
                await story.get_by_role('link', name='导出故事', exact=False).click()
            await (await download.value).save_as(str(folder / 'export.json'))
            exported = json.loads((folder / 'export.json').read_text())
            assert exported == json.loads((ROOT / args.source).read_text())
            await story.get_by_role('button', name='开始这个故事', exact=True).click()
            await page.get_by_label('你的行动').fill('我向室友打招呼，问今晚大家有什么安排。')
            await page.get_by_role('button', name='继续故事', exact=True).click()
            await page.locator('.turn[data-version="1"]').wait_for(timeout=185000)
            await page.screenshot(path=str(folder / 'adventure.png'))
            assert not report['errors'], report['errors']
            report.update(status='passed', live_steps=len(job['steps']), loss_report_visible=True,
                          native_roundtrip_exact=True, mobile_overflow=False, playable=True)
        except Exception as exc:
            report.update(status='failed', error=str(exc)[:1000])
            await page.screenshot(path=str(folder / 'failure.png'), full_page=True)
            raise
        finally:
            (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
            await browser.close()
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
