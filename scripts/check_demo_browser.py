"""Verify video loading, playback, seeking and mobile layout in three languages."""

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'checks': [], 'errors': []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=['--no-sandbox'])
        page = await browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda error: report['errors'].append(str(error)))
        try:
            for locale in ('en', 'zh-CN', 'ja'):
                response = await page.goto(args.url.rstrip('/') + '/?lang=' + locale)
                assert response.status == 200
                await page.wait_for_function("document.querySelector('video').readyState >= 1 || document.querySelector('video').error", timeout=60000)
                video = page.locator('video')
                metadata = await video.evaluate('v => ({duration:v.duration, width:v.videoWidth, height:v.videoHeight, src:v.currentSrc, error:v.error?.message})')
                assert not metadata.get('error'), metadata
                assert 50 <= metadata['duration'] <= 52 and metadata['width'] == 1920 and metadata['height'] == 1080, metadata
                assert any(metadata['src'].endswith(f'narraloom-{locale}.' + ext) for ext in ('mp4', 'webm')), metadata
                assert await page.locator('html').get_attribute('lang') == locale
                assert await video.get_attribute('controls') is not None
                assert await video.get_attribute('playsinline') is not None
                await video.evaluate('async v => { v.muted=true; await v.play(); }')
                await page.wait_for_function("document.querySelector('video').currentTime > 0.2")
                await video.evaluate('v => { v.pause(); v.currentTime=30; }')
                await page.wait_for_function("!document.querySelector('video').seeking && document.querySelector('video').currentTime >= 30")
                frame_time = await video.evaluate('''async v => {
                    await v.play();
                    const time = await new Promise(resolve => v.requestVideoFrameCallback((_, frame) => resolve(frame.mediaTime)));
                    v.pause(); return time;
                }''')
                assert frame_time >= 29.9, frame_time
                await page.screenshot(path=str(args.output / f'{locale}-desktop.png'), full_page=True)
                await page.set_viewport_size({'width': 390, 'height': 844})
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                await video.evaluate('async v => { await v.play(); }')
                await page.wait_for_function("document.querySelector('video').currentTime > 30.2")
                await page.screenshot(path=str(args.output / f'{locale}-mobile.png'), full_page=True)
                await page.set_viewport_size({'width': 1440, 'height': 1000})
                report['checks'].append({'locale': locale, 'play': 'passed', 'seek': 'passed', 'mobile': 'passed', **metadata})
            assert not report['errors'], report['errors']
            report['status'] = 'passed'
        except Exception as exc:
            report.update(status='failed', failure=str(exc))
            raise
        finally:
            (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
