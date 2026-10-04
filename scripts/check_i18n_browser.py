"""Real browser acceptance of locale changes with actual creation/play and unchanged drafts."""
import argparse
import asyncio
import base64
import json
import re
from pathlib import Path

from browser_navigation import story_tools, tab
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
EN = json.loads((ROOT / 'web/src/locales/en.json').read_text())
ZH = json.loads((ROOT / 'web/src/locales/zh-CN.json').read_text())
SWITCH = '界面语言 / Interface language'


def label(text, lang='en'):
    key = next((k for k, v in ZH.items() if v == text), None)
    if key is None:
        key = next(k for k, v in ZH.items() if v.strip() == text)
    return (EN if lang == 'en' else ZH)[key].strip()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18091')
    parser.add_argument('--output', required=True)
    parser.add_argument('--resume-from')
    args = parser.parse_args()
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT / 'outputs/validation'):
        raise ValueError('Reports belong in project validation outputs')
    folder.mkdir(parents=True, exist_ok=False)
    previous = (ROOT / args.resume_from).resolve() if args.resume_from else None
    report = {'status': 'running', 'mode': 'real_browser_and_models', 'checks': [], 'errors': [], 'jobs': {}}
    if previous:
        prior = json.loads((previous / 'report.json').read_text())
        report['jobs'] = prior.get('jobs', {})
        report['previous_run'] = args.resume_from
        report['previous_failure'] = prior.get('failure')
    writes = []

    def save():
        (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        context = await browser.new_context(locale='en-US', viewport={'width': 1440, 'height': 1000}, **(
            {'storage_state': str(previous / 'session.local.json')} if previous else {}))
        page = await context.new_page()
        page.on('pageerror', lambda e: report['errors'].append(str(e)))
        page.on('request', lambda r: writes.append(r.url) if r.method in {'POST', 'PUT', 'DELETE', 'PATCH'} else None)
        csrf = ''

        async def call(path, body=None, method=None, raw=False):
            response = await context.request.fetch(args.url + path, method=method or ('POST' if body is not None else 'GET'),
                data=body, headers={'X-CSRF-Token': csrf, 'Content-Type': 'application/octet-stream' if raw else 'application/json'})
            assert response.ok, (response.status, await response.text())
            return await response.json()

        async def switch(lang, dialog=False):
            before = len(writes)
            scope = page.get_by_role('dialog') if dialog else page.locator('.topbar')
            await scope.get_by_label(SWITCH, exact=True).select_option(lang)
            await page.wait_for_function('(lang)=>document.documentElement.lang===lang', arg=lang)
            await page.wait_for_timeout(150)
            assert len(writes) == before, 'Switching language performed a write'

        async def shot(name, mobile=False):
            if mobile:
                await page.set_viewport_size({'width': 390, 'height': 844})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'), name + ' overflow'
            if mobile:
                assert await page.locator('.topbar').evaluate('''el=>{
                  const boxes=[...el.children].map(e=>e.getBoundingClientRect()).filter(r=>r.width&&r.height).sort((a,b)=>a.x-b.x);
                  return boxes.every((r,i)=>i===0||r.x>=boxes[i-1].right-1);
                }'''), name + ' overlapping topbar controls'
            await page.screenshot(path=str(folder / (name + '.png')), full_page=not mobile)
            if mobile:
                await page.set_viewport_size({'width': 1440, 'height': 1000})

        async def wait_job(job_id):
            last = None
            for _ in range(600):
                job = await call('/api/studio/jobs/' + job_id)
                state = job['status'], len(job['steps'])
                if state != last:
                    print(job_id, *state, flush=True)
                    last = state
                if job['status'] in {'ready', 'failed', 'interrupted', 'cancelled', 'recovery_required'}:
                    break
                await asyncio.sleep(2)
            (folder / (job_id + '.json')).write_text(json.dumps(job, ensure_ascii=False, indent=2))
            assert job['status'] == 'ready', job.get('error') or job['status']
            return job

        async def drafts(selector):
            return await page.locator(selector).evaluate_all('(els)=>els.map(e=>({value:e.value,checked:e.checked,files:e.files?[...e.files].map(f=>f.name):null}))')

        try:
            await page.goto(args.url)
            await page.evaluate("localStorage.removeItem('rpw-active');localStorage.removeItem('rpw-room')")
            await page.reload()
            await page.locator('.studio-hero').wait_for()
            csrf = (await call('/api/session', {}, 'POST'))['csrf_token']
            await context.storage_state(path=str(folder / 'session.local.json'))
            await switch('en')
            await page.get_by_role('button', name='Create My World', exact=True).wait_for()
            await switch('zh-CN')
            await page.get_by_role('button', name='创建我的世界', exact=True).wait_for()
            other = await context.new_page()
            await other.goto(args.url)
            await switch('en')
            await other.wait_for_function("document.documentElement.lang==='en'")
            await other.close()
            await page.reload()
            await page.get_by_role('button', name='Create My World', exact=True).wait_for()
            report['checks'].append('browser default, persistence and cross-tab synchronization')
            await shot('library-en-mobile', True)

            await page.get_by_role('button', name='Create My World', exact=True).click()
            dialog = page.get_by_role('dialog')
            brief = '暖色的海边修船小屋，玩家和一位名叫 Rowan 的友善修船匠自由交谈。小屋里只有这两人。不要战斗、调查任务或倒计时。'
            await dialog.get_by_label('World idea', exact=True).fill(brief)
            await dialog.get_by_label('Creation scale', exact=True).select_option('scene')
            await dialog.get_by_label('Content language', exact=True).select_option('en')
            await switch('zh-CN', True)
            assert await dialog.get_by_label('世界构想', exact=True).input_value() == brief
            assert await dialog.get_by_label('内容语言', exact=True).input_value() == 'en'
            assert await dialog.get_by_label('创作规模', exact=True).input_value() == 'scene'
            await switch('en', True)
            await shot('creation-en-mobile', True)
            if 'scene' not in report['jobs']:
                async with page.expect_response(lambda r: r.url.endswith('/api/studio/worlds') and r.request.method == 'POST') as response:
                    await dialog.get_by_role('button', name='Generate world and first story', exact=True).click()
                report['jobs']['scene'] = (await (await response.value).json())['id']
                save()
            else:
                await dialog.get_by_role('button', name='Close creation window', exact=True).click()
            existing = await call('/api/studio/jobs/' + report['jobs']['scene'])
            if previous and existing['status'] == 'failed':
                # Explicit recovery acceptance, preserving the failed report and authored content.
                report['retry_of_failed_job'] = existing
                await page.get_by_role('button', name='Continue task', exact=True).click()
            job = await wait_job(report['jobs']['scene'])
            content = await call('/api/studio/stories/' + job['story_id'] + '/export')
            assert content['world']['content_language'] == content['story']['content_language'] == 'en'
            assert not re.search(r'[\u3400-\u9fff]', content['story']['opening'])
            report['checks'].append('English UI creates English scene from Chinese brief; creation drafts preserved')
            (folder / 'scene.local.json').write_text(json.dumps(content, ensure_ascii=False, indent=2))
            await page.reload()
            await page.locator('.studio-world-card').filter(has_text=content['world']['title']).first.click()
            before_library = await call('/api/studio')
            await page.get_by_role('button', name='Edit world', exact=True).click()
            await page.get_by_label('World name', exact=True).fill('手写设定 <em>Keep me</em> 日本語')
            await tab(page, 'editor', 'systems')
            # Exercise previously collapsed controls, without saving any synthetic edits.
            for text in ['加入可运行的进度示例']:
                button = page.get_by_role('button', name=label(text), exact=True)
                if await button.count():
                    await button.click()
            await page.get_by_role('button', name=label('启用可配置规则'), exact=True).click()
            for selector in ['.simulation-editor > label input[type=checkbox]']:
                field = page.locator(selector).first
                if await field.count():
                    await field.check()
            form_values = await drafts('.editor input,.editor textarea,.editor select')
            await switch('zh-CN')
            assert await drafts('.editor input,.editor textarea,.editor select') == form_values
            await switch('en')
            assert await drafts('.editor input,.editor textarea,.editor select') == form_values
            assert await page.get_by_label('World name', exact=True).input_value() == '手写设定 <em>Keep me</em> 日本語'
            await shot('editors-en')
            await shot('editors-en-mobile', True)
            await page.get_by_role('button', name='Discard this edit', exact=True).click()
            assert await call('/api/studio') == before_library
            report['checks'].append('world/state/rule/simulation editor drafts preserved; no canonical edits')

            card = page.locator(f'[data-story-id="{job["story_id"]}"]')
            await story_tools(card)
            await card.get_by_role('button', name='Edit story ' + content['story']['title'], exact=True).click()
            await page.get_by_label('Story opening', exact=True).fill('A hand-written opening. 保留原文。')
            opening_draft = await drafts('.editor input,.editor textarea,.editor select')
            await switch('zh-CN')
            assert await drafts('.editor input,.editor textarea,.editor select') == opening_draft
            await page.get_by_role('button', name='放弃本次编辑', exact=True).click()
            await switch('en')
            assert await call('/api/studio/stories/' + job['story_id'] + '/export') == content
            report['checks'].append('story draft and native export unchanged by locale switches')

            await tab(page, 'workspace', 'tools')
            await page.get_by_label(label('导入角色卡或世界书'), exact=True).set_input_files({
                'name': 'my-scene.json', 'mimeType': 'application/json', 'buffer': json.dumps(content, ensure_ascii=False).encode()})
            await page.locator('.import-preview').wait_for()
            await page.get_by_label('Import adaptation requirements', exact=True).fill('原文を保持してください。Keep original.')
            await switch('zh-CN')
            assert await page.get_by_label('导入改编要求', exact=True).input_value() == '原文を保持してください。Keep original.'
            await switch('en')
            await shot('import-en-mobile', True)
            if 'native' not in report['jobs']:
                async with page.expect_response(lambda r: '/convert' in r.url and r.request.method == 'POST') as response:
                    await page.get_by_role('button', name='Restore and auto-test', exact=True).click()
                report['jobs']['native'] = (await (await response.value).json())['id']
                save()
            restored = await wait_job(report['jobs']['native'])
            native = await call('/api/studio/stories/' + restored['story_id'] + '/export')
            assert native['world'] == content['world'] and native['story'] == content['story']
            report['checks'].append('native import UI and automatic test; content preserved exactly')

            await page.get_by_role('button', name='Models and usage', exact=True).click()
            dialog = page.get_by_role('dialog')
            await dialog.get_by_label('Default model', exact=True).fill('unsaved-model-choice')
            await tab(page, 'provider', 'modules')
            await page.locator('.engine-bindings > summary').click()
            await dialog.get_by_role('button', name='Add provider', exact=True).click()
            await dialog.get_by_label('provider_1 URL', exact=True).fill('http://127.0.0.1:9876/v1')
            await dialog.get_by_label('provider_1 API key', exact=True).fill('draft-only-not-a-real-key')
            values = await drafts('.provider-modal input,.provider-modal select:not([aria-label="'+SWITCH+'"])')
            await switch('zh-CN', True)
            assert await drafts('.provider-modal input,.provider-modal select:not([aria-label="'+SWITCH+'"])') == values
            await switch('en', True)
            await shot('providers-en-mobile', True)
            # Test saved default, not the unsaved synthetic draft.
            async with page.expect_response(lambda r: r.url.endswith('/api/settings/provider/check'), timeout=120000) as response:
                await dialog.get_by_role('button', name='Test saved connection', exact=True).click()
            diagnostic = await (await response.value).json()
            assert diagnostic.get('generation_passed'), diagnostic
            await page.get_by_role('status').filter(has_text='Model list and real JSON').wait_for()
            await switch('zh-CN', True)
            await page.get_by_role('status').filter(has_text='模型列表和真实JSON').wait_for()
            await dialog.get_by_role('button', name='关闭模型设置', exact=True).click()
            await switch('en')
            report['checks'].append('provider drafts and diagnostic status update without resubmitting requests')

            await tab(page, 'workspace', 'avatars')
            await page.locator('.avatar-studio > details > summary').click()
            await page.get_by_label('2D character description', exact=True).fill('Original character description 原文。')
            png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aT1cAAAAASUVORK5CYII=')
            await page.get_by_label('2D character reference image', exact=True).set_input_files({'name': 'draft.png', 'mimeType': 'image/png', 'buffer': png})
            await switch('zh-CN')
            assert await page.get_by_label('2D人物描述', exact=True).input_value() == 'Original character description 原文。'
            assert await page.get_by_label('2D人物参考图', exact=True).evaluate('(e)=>e.files[0].name') == 'draft.png'
            await switch('en')
            report['checks'].append('optional Avatar input and selected file preserved; no GPU job submitted')

            await tab(page, 'workspace', 'worlds')
            # Start the exact tested scene, then switch languages during an actual model action.
            await page.locator('.studio-world-card').filter(has_text=content['world']['title']).first.click()
            card = page.locator(f'[data-story-id="{job["story_id"]}"]')
            async with page.expect_response(lambda r: r.url.endswith('/api/campaigns') and r.request.method == 'POST') as response:
                await card.get_by_role('button', name='Start this story', exact=True).click()
            campaign = await (await response.value).json()
            report['campaign'] = campaign
            base = f"/api/campaigns/{campaign['id']}/branches/{campaign['branch_id']}"
            await page.get_by_label('Your action', exact=True).fill('Hello Rowan. What do you enjoy about working here?')
            async with page.expect_response(lambda r: r.url.endswith('/actions') and r.request.method == 'POST') as response:
                await page.get_by_role('button', name='Continue story', exact=True).click()
            action = await (await response.value).json()
            await switch('zh-CN')
            await page.get_by_label('你的行动', exact=True).fill('未发送的下一步 / unsent next action')
            await switch('en')
            assert await page.get_by_label('Your action', exact=True).input_value() == '未发送的下一步 / unsent next action'
            await page.locator('.turn[data-version="1"]').wait_for(timeout=180000)
            view = await call(base + '/view')
            assert view['world_version'] == 1 and view['history'][0]['action_id'] == action['id']
            assert view['content_language'] == 'en'
            assert not re.search(r'[\u3400-\u9fff]', ''.join(s['text'] for s in view['history'][0]['segments']))
            await switch('zh-CN')
            assert await call(base + '/view') == view
            await switch('en')
            assert await call(base + '/view') == view
            assert await page.get_by_label('Your action', exact=True).input_value() == '未发送的下一步 / unsent next action'
            await shot('play-en')
            await shot('play-en-mobile', True)
            await page.get_by_role('button', name='Branch from turn 1', exact=True).click()
            await page.locator('#branch-name').fill('My branch 分支')
            await switch('zh-CN', True)
            assert await page.locator('#branch-name').input_value() == 'My branch 分支'
            await page.get_by_role('button', name='关闭分支窗口', exact=True).click()
            await switch('en')
            report['checks'].append('live English action commits once across switches; draft/view/branch form preserved')

            await page.get_by_role('button', name=label('协作冒险'), exact=True).click()
            dialog = page.get_by_role('dialog')
            await dialog.get_by_label('Seat name', exact=True).fill('Harper 原名')
            await switch('zh-CN', True)
            assert await dialog.get_by_label('席位名称', exact=True).input_value() == 'Harper 原名'
            await switch('en', True)
            await dialog.get_by_label('Room mode', exact=True).select_option('independent_characters')
            await dialog.get_by_role('button', name='Create room for current adventure', exact=True).click()
            await page.locator('.room-layout').wait_for()
            await page.get_by_label('Room action', exact=True).fill('A room draft 原文。')
            await switch('zh-CN')
            assert await page.get_by_label('房间行动', exact=True).input_value() == 'A room draft 原文。'
            await switch('en')
            await shot('room-en')
            await shot('room-en-mobile', True)
            report['checks'].append('room creation, character name and room draft preserved')
            assert not report['errors'], report['errors']
            report['status'] = 'passed'
        except Exception as exc:
            report.update(status='failed', failure=str(exc))
            await page.screenshot(path=str(folder / 'failure.png'), full_page=True)
            raise
        finally:
            await context.storage_state(path=str(folder / 'session.local.json'))
            save()
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
