"""Live model, multi-session browser and portable package acceptance."""
import argparse
import asyncio
import json
from pathlib import Path

from browser_navigation import tab
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
LABELS = {lang: json.loads((ROOT / f'web/src/locales/{lang}.json').read_text()) for lang in ('en', 'zh-CN')}
SWITCH = '界面语言 / Interface language'


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18091')
    parser.add_argument('--output', required=True)
    parser.add_argument('--creator-session', type=Path)
    parser.add_argument('--reuse-creation', type=Path, help='Reuse two already-completed source creation jobs; retain prior failures')
    parser.add_argument('--avatar-id', help='Optional owned existing render asset; no GPU creation is performed')
    args = parser.parse_args()
    previous = json.loads((args.reuse_creation / 'report.json').read_text()) if args.reuse_creation else None
    if previous and not args.creator_session:
        args.creator_session = args.reuse_creation / 'creator-session.local.json'
    out = (ROOT / args.output).resolve()
    if not out.is_relative_to(ROOT / 'outputs/validation'):
        raise ValueError('Reports belong in project validation outputs')
    out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'mode': 'real_models_and_browser', 'checks': [], 'jobs': [], 'page_errors': [],
              'avatar_mode': 'existing_asset_with_explicit_test_metadata' if args.avatar_id else 'none'}

    def save():
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        creator = await browser.new_context(locale='en-US', viewport={'width': 1440, 'height': 1000},
            **({'storage_state': str(args.creator_session)} if args.creator_session else {}))
        reader = await browser.new_context(locale='en-US', viewport={'width': 1440, 'height': 1000})
        offline = await browser.new_context(locale='zh-CN', viewport={'width': 390, 'height': 844})
        tokens = {}
        for context in (creator, reader, offline):
            response = await context.request.post(args.url + '/api/session')
            tokens[context] = (await response.json())['csrf_token']
        for context,name in [(creator,'creator'),(reader,'reader'),(offline,'file-recipient')]:
            await context.storage_state(path=str(out / (name + '-session.local.json')))
        page = await creator.new_page();other = await reader.new_page();file_page = await offline.new_page()
        for p in (page, other, file_page):
            p.on('pageerror', lambda e: report['page_errors'].append(str(e)))

        async def api(context, path, body=None, method=None):
            response = await context.request.fetch(args.url + path, method=method or ('POST' if body is not None else 'GET'),
                data=body, headers={'X-CSRF-Token': tokens[context], 'Content-Type': 'application/json'})
            assert response.ok, (response.status, await response.text())
            return await response.json()

        async def job_done(context, job):
            previous = None
            for _ in range(600):
                job = await api(context, '/api/studio/jobs/' + job['id'])
                state = job['status'], len(job['steps'])
                if state != previous:
                    print(job['id'], *state, flush=True);previous = state
                if job['status'] in {'ready', 'failed', 'cancelled', 'interrupted', 'recovery_required'}:
                    break
                await asyncio.sleep(2)
            report['jobs'].append(job);save()
            assert job['status'] == 'ready', job
            return job

        async def all_tests(context):
            library = await api(context, '/api/studio')
            for job in library['jobs']:
                await job_done(context, job)
            return await api(context, '/api/studio')

        async def screenshot(p, name):
            assert await p.evaluate('document.documentElement.scrollWidth<=innerWidth+1'), name + ' overflow'
            await p.screenshot(path=str(out / (name + '.png')), full_page=True)

        try:
            if previous:
                source_jobs = [j for j in previous['jobs'] if j['kind'] in {'world', 'story'}]
                assert len(source_jobs) >= 2
                first = await job_done(creator, source_jobs[0])
                await job_done(creator, source_jobs[1])
                report['reused_creation'] = str(args.reuse_creation)
            else:
                job = await api(creator, '/api/studio/worlds', {'prompt': 'A warm neighborhood art studio. One patient resident artist named Jun chats with visitors. Only one room, no danger, tasks or deadlines.',
                    'story_prompt': 'A visitor stops by to talk about painting. Keep it open-ended.', 'creation_preset': 'scene', 'content_language': 'en',
                    **({'avatar_id': args.avatar_id} if args.avatar_id else {})})
                first = await job_done(creator, job)
                await job_done(creator, await api(creator, f"/api/studio/worlds/{first['world_id']}/stories", {
                    'prompt': 'A second visit to chat about favorite colors. An open conversation in the existing room, with Jun present.',
                    'creation_preset': 'scene', 'content_language': 'en'}))
            original = await api(creator, f"/api/studio/stories/{first['story_id']}/export")
            await creator.storage_state(path=str(out / 'creator-session.local.json'))
            report['checks'].append('Two stories automatically generated and tested in one world with real models')
            await page.goto(args.url);await page.locator('.studio-world-card').first.wait_for()
            await page.locator('.studio-world-card').filter(has=page.get_by_role('heading', name=original['world']['title'], exact=True)).click()
            await page.get_by_role('button', name=LABELS['en']['community.create'], exact=True).click()
            modal = page.get_by_role('dialog');await modal.get_by_label(LABELS['en']['community.field.slug'], exact=True).fill('art-studio')
            await modal.get_by_label(LABELS['en']['community.field.author'], exact=True).fill('Acceptance Creator')
            await modal.get_by_label(LABELS['en']['community.field.license'], exact=True).fill('CC-BY-4.0')
            await modal.get_by_label(LABELS['en']['community.field.summary'], exact=True).fill('Two friendly visits to an art studio.')
            await modal.get_by_label(LABELS['en']['community.field.tags'], exact=True).fill('art, everyday')
            await modal.get_by_label(LABELS['en']['community.field.model_notes'], exact=True).fill('Tested with DeepSeek Flash; any capable structured-output model can be configured.')
            before = await modal.locator('input,textarea,select').evaluate_all('(els)=>els.map(e=>[e.value,e.checked])')
            await modal.get_by_label(SWITCH, exact=True).select_option('zh-CN')
            assert await modal.get_by_label(LABELS['zh-CN']['community.field.tags'], exact=True).input_value() == 'art, everyday'
            await modal.get_by_label(SWITCH, exact=True).select_option('en')
            assert await modal.locator('input,textarea,select').evaluate_all('(els)=>els.map(e=>[e.value,e.checked])') == before
            await screenshot(page, 'package-dialog')
            async with page.expect_response(lambda r: r.url.endswith('/api/studio/packages') and r.request.method == 'POST') as result:
                await modal.get_by_role('button', name=LABELS['en']['community.build'], exact=True).click()
            response = await result.value;assert response.status == 201, await response.text()
            pack = await response.json();pid = pack['id'];report['package_id'] = pid;save()
            assert pack['visibility'] == 'private' and len(pack['stories']) == 2
            assert pack['metadata']['tags'] == ['art', 'everyday']
            assert (await reader.request.get(args.url + f'/api/community/{pid}/download')).status == 404
            owned = page.locator(f'[data-owned-package="{pid}"]');await owned.wait_for()
            async with page.expect_download() as download:
                await owned.get_by_role('link', name=LABELS['en']['community.download'], exact=True).click()
            path = out / 'art-studio.narraloom.zip';await (await download.value).save_as(path)
            raw = path.read_bytes()
            async with page.expect_response(lambda r: r.url.endswith('/visibility') and r.request.method == 'PUT') as visibility:
                await owned.get_by_label(LABELS['en']['community.visibility'], exact=True).select_option('listed')
            assert (await visibility.value).status == 200
            shelf = await api(reader, '/api/community?q=art&language=en&tag=everyday')
            assert shelf['total'] == 1 and 'owner' not in shelf['items'][0]
            for actor in original['world']['characters']:
                assert actor['secret'] not in json.dumps(shelf, ensure_ascii=False)
            report['checks'].append('Creator UI builds immutable private multi-story package; metadata-only discovery; explicit listing; original licenses/notes retained')

            await other.goto(args.url + '?package=' + pid)
            shared = other.locator('#shared-package .community-card');await shared.wait_for()
            assert await shared.locator('input[type=checkbox]:checked').count() == 2
            async with other.expect_response(lambda r: r.url.endswith(f'/community/{pid}/install') and r.request.method == 'POST') as installed:
                await shared.get_by_role('button', name=LABELS['en']['community.install'], exact=True).click()
            install = await (await installed.value).json();reader_library = await all_tests(reader)
            assert len(reader_library['worlds']) == 1 and len(reader_library['stories']) == 2
            assert all(s['test_report']['mode'] == 'live_models' for s in reader_library['stories'])
            assert all(s['origin']['package']['sha256'] == pack['sha256'] for s in reader_library['stories'])
            again = await api(reader, f'/api/community/{pid}/install', {})
            assert again['id'] == install['id']
            assert len((await api(reader, '/api/studio'))['stories']) == 2
            if args.avatar_id:
                aid = reader_library['worlds'][0]['content']['characters'][0]['avatar_id']
                assert aid != args.avatar_id
                assert (await reader.request.get(args.url + f'/api/avatars/{aid}/files/puppet/portrait.png')).status == 200
                assert (await creator.request.get(args.url + f'/api/avatars/{aid}/files/puppet/portrait.png')).status == 404
            report['checks'].append('Independent recipient installs one world/two stories; both retest with recipient models; repeat installation deduplicates; asset ownership remapped')

            assert not await other.evaluate("new URLSearchParams(location.search).has('package')")
            await other.reload();card = other.locator(f'[data-story-id="{install["story_id"]}"]');await card.wait_for()
            await card.get_by_role('button', name=LABELS['en']['Studio.137'], exact=True).click()
            await other.locator('.adventure').wait_for()
            if args.avatar_id:
                await other.locator('.npc-theater canvas[data-ready="true"]').wait_for(timeout=45000)
            # Use the ordinary backend action endpoint while the real browser renders the result.
            active = await other.evaluate("JSON.parse(localStorage.getItem('rpw-active'))")
            current = await api(reader, f"/api/campaigns/{active['cid']}/branches/{active['bid']}/view")
            action = await api(reader, f"/api/campaigns/{active['cid']}/branches/{active['bid']}/actions", {
                'action_id': 'package_dialogue', 'expected_world_version': current['world_version'], 'mode': 'say', 'text': 'Hello Jun, which color do you enjoy painting with?'})
            for _ in range(120):
                state = await api(reader, '/api/actions/' + action['id'])
                if state['status'] in {'committed','failed','cancelled'}:break
                await asyncio.sleep(2)
            assert state['status'] == 'committed', state
            await other.reload();await other.locator('.turn[data-version="1"]').wait_for(timeout=15000)
            if args.avatar_id:
                await other.wait_for_function("Number(document.querySelector('.npc-theater canvas')?.dataset.frames)>10", timeout=30000)
                report['avatar_frames'] = await other.locator('.npc-theater canvas').get_attribute('data-frames')
            await screenshot(other, 'recipient-play')
            report['checks'].append('Recipient starts and continues its own campaign; shared-page query no longer interrupts reload; imported 2D renders committed dialogue')

            # Withdraw first, then prove file portability to a third independent session.
            mine = (await api(creator, '/api/studio/packages'))[0]
            await api(creator, f'/api/studio/packages/{pid}/visibility', {'expected_revision': mine['revision'], 'visibility': 'withdrawn'}, 'PUT')
            assert (await reader.request.get(args.url + f'/api/community/{pid}/download')).status == 404
            assert (await api(reader, f"/api/campaigns/{active['cid']}/branches/{active['bid']}/view"))['world_version'] == 1
            await file_page.goto(args.url)
            await tab(file_page, 'workspace', 'community')
            await file_page.get_by_label(LABELS['zh-CN']['community.upload'], exact=True).set_input_files(path)
            local = file_page.locator(f'[data-package-id="{pack["sha256"]}"]');await local.wait_for()
            await local.locator('input[type=checkbox]').nth(1).uncheck()
            await screenshot(file_page, 'file-preview-mobile')
            async with file_page.expect_response(lambda r: '/api/studio/packages/import?' in r.url) as imported:
                await local.get_by_role('button', name=LABELS['zh-CN']['community.install'], exact=True).click()
            assert (await imported.value).status == 202
            portable = await all_tests(offline)
            assert len(portable['worlds']) == len(portable['stories']) == 1
            assert portable['stories'][0]['content'] == original['story']
            assert path.read_bytes() == raw
            for context,name in [(creator,'creator'),(reader,'reader'),(offline,'file-recipient')]:
                await context.storage_state(path=str(out / (name + '-session.local.json')))
            report['checks'].append('Withdrawal blocks new downloads but leaves recipient save intact; downloaded ZIP previews/installs one selected story in a third session after withdrawal')
            assert not report['page_errors'], report['page_errors']
            report['status'] = 'passed'
        except BaseException as exc:
            report.update(status='failed', failure=str(exc));await page.screenshot(path=str(out/'creator-failure.png'),full_page=True);await other.screenshot(path=str(out/'recipient-failure.png'),full_page=True)
            raise
        finally:
            save();await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
