"""Check optional portrait creation in all interface languages using protocol fixtures.

Runs on a test workspace. Captures authoring requests without generating content or
submitting GPU jobs; the backend text-only lifecycle is covered by test_studio.py.
"""

import argparse
import asyncio
import base64
import json
from pathlib import Path

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aT1cAAAAASUVORK5CYII=')


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'checks': [], 'errors': []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=['--no-sandbox'])
        page = None
        try:
            for locale in ('en', 'zh-CN', 'ja'):
                labels = json.loads((ROOT / f'web/src/locales/{locale}.json').read_text())
                context = await browser.new_context(locale=locale, viewport={'width': 1280, 'height': 1000})
                page = await context.new_page()
                page.on('pageerror', lambda error: report['errors'].append(str(error)))
                capabilities = {'available': False, 'status': 200, 'upload_status': 202}
                captured = {'worlds': [], 'avatars': []}

                async def avatar_route(route, _request, *, captured=captured, capabilities=capabilities):
                    if route.request.method == 'GET':
                        await route.fulfill(json=[{'id': 'avatar_existing', 'name': 'Existing portrait',
                            'description': 'Protocol fixture', 'state': 'queued', 'stage': 'queued', 'progress': 0}])
                    else:
                        captured['avatars'].append(route.request.post_data_json)
                        await route.fulfill(status=capabilities['upload_status'], json={'id': 'avatar_new'} if capabilities['upload_status'] == 202
                            else {'error': {'code': 'avatar_unavailable', 'message': 'Creator unavailable'}})

                async def world_route(route, _request, *, captured=captured):
                    captured['worlds'].append(route.request.post_data_json)
                    await route.fulfill(status=202, json={'id': 'fixture_world', 'status': 'queued'})

                await page.route('**/api/status', lambda route: route.fulfill(json={
                    'ready': True, 'configured': True, 'models': [], 'message': 'Protocol fixture'}))
                await page.route('**/api/avatars', avatar_route)
                await page.route('**/api/avatars/capabilities', lambda route, _request, *, capabilities=capabilities: route.fulfill(
                    status=capabilities['status'], json={'available': capabilities['available']}))
                await page.route('**/api/studio/worlds', world_route)
                await page.goto(args.url)
                await page.locator('.topbar select').select_option(locale)
                checkbox = page.get_by_label(labels['avatar.enable'], exact=True)
                file_input = page.get_by_label(labels['Studio.070'], exact=True)
                picker = page.get_by_label(labels['AvatarStudio.013'], exact=True)

                async def open_form(page=page, labels=labels, checkbox=checkbox):
                    await page.get_by_role('button', name=labels['Studio.007'].strip(), exact=True).click()
                    await expect(checkbox).not_to_be_checked()
                    await page.get_by_label(labels['Studio.082'], exact=True).fill('A small orbital station with two friends.')

                async def submit(expected_avatar, uploads=0, page=page, captured=captured):
                    before = len(captured['avatars'])
                    async with page.expect_response(lambda response: response.url.endswith('/api/studio/worlds')
                                                    and response.request.method == 'POST'):
                        await page.locator('.creation-modal button[type=submit]').click()
                    await expect(page.locator('.creation-modal')).to_have_count(0)
                    assert captured['worlds'][-1]['avatar_id'] == expected_avatar, captured
                    assert len(captured['avatars']) == before + uploads, captured

                await open_form()
                await expect(file_input).to_be_hidden()
                await page.screenshot(path=str(args.output / f'{locale}-creation.png'), full_page=True)
                await submit(None)
                report['checks'].append(f'{locale}: default text-only creation sends no portrait request')

                await open_form()
                await checkbox.check()
                await expect(file_input).to_be_disabled()
                await page.set_viewport_size({'width': 390, 'height': 844})
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                bounds = await checkbox.bounding_box()
                assert bounds and bounds['width'] <= 24 and bounds['height'] <= 24, bounds
                await checkbox.scroll_into_view_if_needed()
                await page.screenshot(path=str(args.output / f'{locale}-portrait-mobile.png'), full_page=True)
                await page.set_viewport_size({'width': 1280, 'height': 1000})
                await picker.select_option('avatar_existing')
                await submit('avatar_existing')
                report['checks'].append(f'{locale}: existing portrait works without a creator')

                capabilities.update(available=True)
                await open_form()
                await checkbox.check()
                await expect(file_input).to_be_enabled()
                await file_input.set_input_files({'name': 'draft.png', 'mimeType': 'image/png', 'buffer': PNG})
                await checkbox.uncheck()
                await checkbox.check()
                assert await file_input.evaluate('e => e.files[0].name') == 'draft.png'
                await checkbox.uncheck()
                await submit(None)
                report['checks'].append(f'{locale}: disabling a retained image draft creates text only')

                await open_form()
                await checkbox.check()
                await expect(file_input).to_be_enabled()
                await file_input.set_input_files({'name': 'unused.png', 'mimeType': 'image/png', 'buffer': PNG})
                await picker.select_option('avatar_existing')
                assert await file_input.evaluate('e => e.files.length') == 0
                await submit('avatar_existing')
                report['checks'].append(f'{locale}: choosing an existing portrait clears the upload')

                await open_form()
                await checkbox.check()
                await expect(file_input).to_be_enabled()
                await picker.select_option('avatar_existing')
                await file_input.set_input_files({'name': 'selected.png', 'mimeType': 'image/png', 'buffer': PNG})
                await expect(picker).to_have_value('')
                await submit('avatar_new', uploads=1)
                assert captured['avatars'][-1]['image_base64'] == base64.b64encode(PNG).decode()
                report['checks'].append(f'{locale}: opting in submits the new portrait and binds its ID')

                capabilities['upload_status'] = 503
                await open_form()
                await checkbox.check()
                await expect(file_input).to_be_enabled()
                await file_input.set_input_files({'name': 'offline.png', 'mimeType': 'image/png', 'buffer': PNG})
                world_count = len(captured['worlds'])
                await page.locator('.creation-modal button[type=submit]').click()
                await expect(page.locator('.creation-modal [role=alert]')).to_be_visible()
                assert len(captured['worlds']) == world_count
                await checkbox.uncheck()
                await submit(None)
                report['checks'].append(f'{locale}: failed image submission can continue as text without losing the brief')

                capabilities.update(available=False, status=503)
                await open_form()
                await checkbox.check()
                await expect(file_input).to_be_disabled()
                await checkbox.uncheck()
                await submit(None)
                report['checks'].append(f'{locale}: a capabilities failure does not block text creation')
                await page.screenshot(path=str(args.output / f'{locale}.png'))
                await context.close()
            assert not report['errors'], report['errors']
            report['status'] = 'passed'
        except Exception as exc:
            report.update(status='failed', failure=str(exc))
            if page and not page.is_closed():
                await page.screenshot(path=str(args.output / 'failure.png'), full_page=True)
            raise
        finally:
            (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
