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
                await page.wait_for_function("Number(document.querySelector('video').dataset.duration) > 0")
                expected = float(await video.get_attribute('data-duration'))
                assert abs(metadata['duration'] - expected) < 1 and metadata['width'] == 1920 and metadata['height'] == 1080, metadata
                chapters = await page.locator('#chapters button').evaluate_all('els => els.map(e => Number(e.dataset.time))')
                assert len(chapters) >= 8 and chapters == sorted(set(chapters)) and chapters[0] == 0
                ranged = await page.request.get(metadata['src'], headers={'Range': 'bytes=0-31'})
                assert ranged.status == 206 and ranged.headers['content-type'].startswith('video/'), ranged.headers
                assert len(await ranged.body()) == 32
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
                for index in (len(chapters) // 2, len(chapters) - 1):
                    await page.locator('#chapters button').nth(index).click()
                    await page.wait_for_function('(t) => !document.querySelector("video").seeking && Math.abs(document.querySelector("video").currentTime-t)<1', arg=chapters[index])
                    decoded = await video.evaluate('''async v => {
                        await v.play();
                        const time = await new Promise(resolve => v.requestVideoFrameCallback((_, frame) => resolve(frame.mediaTime)));
                        v.pause(); return time;
                    }''')
                    assert decoded >= chapters[index] - 0.1
                await page.locator('.transcript summary').click()
                assert await page.locator('#transcript p').count() >= 40
                transcript_time = await page.locator('#transcript button').nth(1).inner_text()
                minutes, seconds = map(int, transcript_time.split(':'))
                await page.locator('#transcript button').nth(1).click()
                await page.wait_for_function('t => !document.querySelector("video").seeking && Math.abs(document.querySelector("video").currentTime-t)<1', arg=minutes * 60 + seconds)
                await page.locator('.transcript summary').click()
                await video.evaluate('v => { v.textTracks[0].mode="hidden"; }')
                await page.wait_for_function('document.querySelector("video").textTracks[0].cues?.length >= 40')
                await page.screenshot(path=str(args.output / f'{locale}-desktop.png'), full_page=True)
                await page.set_viewport_size({'width': 390, 'height': 844})
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                mobile_start = await video.evaluate('v => v.currentTime')
                await video.evaluate('async v => { await v.play(); }')
                await page.wait_for_function("t => document.querySelector('video').currentTime > t + 0.2", arg=mobile_start)
                await video.evaluate('v => v.pause()')
                await page.screenshot(path=str(args.output / f'{locale}-mobile.png'), full_page=True)
                await page.set_viewport_size({'width': 1440, 'height': 1000})
                formats = []
                for extension, media_type in (('mp4', 'video/mp4; codecs="avc1.640028, mp4a.40.2"'), ('webm', 'video/webm; codecs="vp9, opus"')):
                    if not await video.evaluate('(v, type) => v.canPlayType(type)', media_type):
                        continue
                    await video.evaluate('(v, src) => { v.src=src; v.load(); }', f'narraloom-{locale}.{extension}')
                    await page.wait_for_function('document.querySelector("video").readyState >= 1')
                    await video.evaluate('(v, t) => { v.currentTime=t; }', expected - 5)
                    await page.wait_for_function('!document.querySelector("video").seeking')
                    decoded = await video.evaluate('''async v => {
                        await v.play();
                        const time = await new Promise(resolve => v.requestVideoFrameCallback((_, frame) => resolve(frame.mediaTime)));
                        v.pause(); return time;
                    }''')
                    assert decoded >= expected - 5.1, (extension, decoded)
                    formats.append(extension)
                assert 'webm' in formats
                report['checks'].append({'locale': locale, 'play': 'passed', 'seek': 'passed', 'mobile': 'passed', 'chapter_seek': 'passed', 'range_requests': 'passed', 'subtitles': 'passed', 'decoded_formats': formats, **metadata})
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
