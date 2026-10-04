"""Real model/browser checks of native preservation, explicit repair and pinned campaigns."""
import argparse
import asyncio
import json
from pathlib import Path

from browser_navigation import story_tools, tab
from check_opening_review import baseline
from playwright.async_api import async_playwright

from roleplay_world.content import StoryBlueprint, WorldBlueprint
from roleplay_world.content_review import opening_scene

ROOT = Path(__file__).resolve().parents[1]
SWITCH = '界面语言 / Interface language'
LABELS = {lang: json.loads((ROOT / f'web/src/locales/{lang}.json').read_text()) for lang in ('en', 'zh-CN')}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18091')
    parser.add_argument('--output', required=True)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT / 'outputs/validation'):
        raise ValueError('Reports belong in project validation outputs')
    folder.mkdir(parents=True, exist_ok=False)
    world, story = baseline()
    story.opening = 'You stand in the Window Room. Nobody else is here; you are alone.'
    raw = args.source.read_bytes() if args.source else json.dumps({'world': world.model_dump(), 'story': story.model_dump()}).encode()
    source = json.loads(raw)
    initial = opening_scene(WorldBlueprint.model_validate(source['world']), StoryBlueprint.model_validate(source['story']))
    report = {'status': 'running', 'mode': 'live_models_and_browser', 'checks': [], 'jobs': [], 'page_errors': []}

    def save():
        (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        context = await browser.new_context(locale='en-US', viewport={'width': 1440, 'height': 1000})
        page = await context.new_page()
        page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
        csrf = ''

        async def call(path, body=None, method=None):
            response = await context.request.fetch(args.url + path, method=method or ('POST' if body is not None else 'GET'),
                data=body, headers={'X-CSRF-Token': csrf, 'Content-Type': 'application/json'})
            assert response.ok, (response.status, await response.text())
            return await response.json()

        async def wait_job(job, expected):
            previous = None
            for _ in range(600):
                job = await call('/api/studio/jobs/' + job['id'])
                status = job['status'], len(job['steps'])
                if status != previous:
                    print(job['id'], *status, flush=True)
                    previous = status
                if job['status'] in {'ready', 'failed', 'cancelled', 'interrupted', 'recovery_required'}:
                    break
                await asyncio.sleep(2)
            report['jobs'].append(job)
            save()
            assert job['status'] == expected, job.get('error') or job['status']
            return job

        async def select_card(sid):
            await page.reload()
            card = page.locator(f'[data-story-id="{sid}"]')
            await card.wait_for()
            await card.locator('.quality-report > summary').click()
            return card

        async def shot(name, mobile=False):
            if mobile:
                await page.set_viewport_size({'width': 390, 'height': 844})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'), name + ' overflow'
            await page.screenshot(path=str(folder / (name + '.png')), full_page=not mobile)
            if mobile:
                await page.set_viewport_size({'width': 1440, 'height': 1000})

        async def repair(card, sid):
            await story_tools(card)
            async with page.expect_response(lambda r: r.url.endswith(f'/stories/{sid}/repair') and r.request.method == 'POST') as pending:
                await card.get_by_role('button', name='AI repair and retest:', exact=False).click()
            response = await pending.value
            assert response.status == 202, await response.text()
            return await wait_job(await response.json(), 'ready')

        try:
            await page.goto(args.url)
            await page.locator('.studio-hero').wait_for()
            csrf = (await call('/api/session', {}, 'POST'))['csrf_token']
            await context.storage_state(path=str(folder / 'session.local.json'))
            await page.get_by_label(SWITCH, exact=True).select_option('en')
            await tab(page, 'workspace', 'tools')
            async with page.expect_response(lambda r: '/api/studio/imports?filename=' in r.url) as uploaded:
                await page.get_by_label(LABELS['en']['ImportStudio.014'], exact=True).set_input_files(
                    {'name': 'opening-source.json', 'mimeType': 'application/json', 'buffer': raw})
            upload = await (await uploaded.value).json()
            async with page.expect_response(lambda r: r.url.endswith('/convert') and r.request.method == 'POST') as converted:
                await page.get_by_role('button', name=LABELS['en']['ImportStudio.011'], exact=True).click()
            failed = await wait_job(await (await converted.value).json(), 'failed')
            sid = failed['story_id']
            exported = await call(f'/api/studio/stories/{sid}/export')
            assert exported['world'] == source['world'] and exported['story'] == source['story']
            card = await select_card(sid)
            await card.locator('[data-review-status="failed"] blockquote').first.wait_for()
            assert await card.get_by_role('button', name=LABELS['en']['Studio.137'], exact=True).is_disabled()
            await shot('failed-import-en')
            await page.get_by_label(SWITCH, exact=True).select_option('zh-CN')
            await card.get_by_role('heading', name=LABELS['zh-CN']['review.title'], exact=True).wait_for()
            await card.scroll_into_view_if_needed()
            await shot('failed-import-zh-mobile', True)
            await page.get_by_label(SWITCH, exact=True).select_option('en')
            report['checks'].append('Native source preserved; model-detected contradiction blocks launch and is visible in both UI languages')

            ready = await repair(card, sid)
            assert ready['story_revision'] == 2
            repaired = await call(f'/api/studio/stories/{sid}/export')
            assert repaired['world'] == source['world']
            assert repaired['story']['opening'] != source['story']['opening']
            assert opening_scene(WorldBlueprint.model_validate(repaired['world']), StoryBlueprint.model_validate(repaired['story'])) == initial
            assert repaired['origin']['text_revisions'][0]['changes']
            card = await select_card(sid)
            await card.get_by_text(LABELS['en']['review.applied'], exact=True).wait_for()
            await card.locator('.review-comparison').first.wait_for()
            await card.scroll_into_view_if_needed()
            await shot('applied-repair-en')
            await shot('applied-repair-en-mobile', True)
            (folder / 'repaired.local.json').write_text(json.dumps(repaired, ensure_ascii=False, indent=2))
            report['checks'].append('Explicit click creates revision 2; live repaired text passes automatic playtest; canonical scene unchanged; before/after audit exported')

            campaign = await call('/api/campaigns', {'story_id': sid, 'player_name': 'Repair test visitor'})
            path = f"/api/campaigns/{campaign['id']}/branches/{campaign['branch_id']}/view"
            pinned = await call(path)
            # Deliberately inject a contradiction into an author edit to test the
            # public lifecycle. No generated source file is edited by this test.
            content = {**repaired['story'], 'opening': source['story']['opening']}
            edited = await call(f'/api/studio/stories/{sid}', {'expected_revision': 2, 'content': content}, 'PUT')
            await wait_job(edited, 'failed')
            card = await select_card(sid)
            again = await repair(card, sid)
            assert again['story_revision'] == 4
            assert await call(path) == pinned
            final = await call(f'/api/studio/stories/{sid}/export')
            assert len(final['origin']['text_revisions']) == 2
            original = await context.request.get(args.url + f"/api/studio/imports/{upload['id']}/original")
            assert await original.body() == raw
            if args.source:
                assert args.source.read_bytes() == raw
            report['checks'].append('Author edit fails review; second explicit repair creates revision 4; old campaign and original download remain unchanged')

            retest = await call(f'/api/studio/stories/{sid}/test', {})
            await wait_job(retest, 'ready')
            card = await select_card(sid)
            assert await page.locator('.creation-progress').count() == 0, 'Superseded failures still demand recovery'
            await card.locator('.review-history > summary').click()
            assert await card.locator('.review-history .review-change').count() >= 2
            report['checks'].append('Explicit retest re-reviews; saved AI revision history survives and remains visible')

            # Presentation-only fixture, clearly separate from live-model work:
            # a failed repair must label unsaved candidates, never accepted edits.
            library = await call('/api/studio')
            row = next(s for s in library['stories'] if s['id'] == sid)
            fixture = {'status': 'failed', 'changes_applied': False, 'repair_rounds': 2, 'issues': [],
                       'changes': [{'path': '/story/opening', 'before': '<script>source</script>', 'after': '<em>candidate</em>'}]}
            row['test_report']['semantic_review'] = fixture
            async def fixture_route(route):
                await route.fulfill(json=library)
            await page.route('**/api/studio', fixture_route)
            card = await select_card(sid)
            await card.get_by_text(LABELS['en']['review.unapplied'], exact=True).wait_for()
            assert await card.locator('.semantic-review script,.semantic-review em').count() == 0
            await shot('unapplied-candidate-presentation-fixture')
            await page.unroute('**/api/studio', fixture_route)
            report['checks'].append('Presentation fixture: unsaved candidates labeled explicitly and HTML-like prose rendered as text')
            assert not report['page_errors'], report['page_errors']
            report['status'] = 'passed'
        except BaseException as exc:
            report.update(status='failed', failure=str(exc))
            await page.screenshot(path=str(folder / 'failure.png'), full_page=True)
            raise
        finally:
            save()
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
