"""Reuse a completed project Avatar to verify independent-room rendering and privacy."""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', default='http://127.0.0.1:18092')
    p.add_argument('--reuse', type=Path, required=True, help='Earlier check_avatar_browser evidence with report.json and session.local.json')
    p.add_argument('--output', default='outputs/validation/room-avatar-browser')
    args = p.parse_args()
    folder = (ROOT/args.output).resolve()
    if not folder.is_relative_to(ROOT/'outputs/validation'):
        raise ValueError('Invalid evidence directory')
    folder.mkdir(parents=True, exist_ok=False)
    previous = json.loads((args.reuse/'report.json').read_text())
    report = {'status': 'running', 'mode': 'existing_avatar_real_deepseek', 'new_gpu_generation': False, 'errors': []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        host = await browser.new_page(locale='zh-CN', viewport={'width': 1440, 'height': 1000}, storage_state=str(args.reuse/'session.local.json'))
        guest = await browser.new_page(locale='zh-CN', viewport={'width': 1440, 'height': 1000})
        for page in (host, guest):
            page.on('pageerror', lambda e: report['errors'].append(str(e)))

        async def get(page, path):
            response = await page.request.get(args.url+path)
            assert response.ok, await response.text()
            return await response.json()

        async def post(page, path, data):
            csrf = (await (await page.request.post(args.url+'/api/session')).json())['csrf_token']
            response = await page.request.post(args.url+path, data=data, headers={'X-CSRF-Token': csrf})
            assert response.ok, await response.text()
            return await response.json()

        async def ready(page):
            await page.wait_for_function("document.querySelector('[aria-label=房间行动]')?.disabled===false", timeout=20000)

        async def say(page, text, target=''):
            await ready(page)
            await page.get_by_label('房间行动方式', exact=True).select_option('say')
            await page.get_by_label('对谁说', exact=True).select_option(target)
            await page.get_by_label('房间行动', exact=True).fill(text)
            async with page.expect_response(lambda r: r.url.endswith('/actions') and r.request.method == 'POST') as info:
                await page.get_by_role('button', name='提交我的行动', exact=True).click()
            response = await info.value; action = await response.json()
            assert response.status == 202, action
            for _ in range(240):
                action = await get(page, f'/api/rooms/{rid}/actions/'+action['id'])
                if action['status'] not in {'accepted', 'planning', 'characters', 'narrating'}: break
                await asyncio.sleep(.5)
            assert action['status'] == 'committed', action
            await page.locator(f'.turn[data-version="{action["result"]["version"]}"]').wait_for(timeout=20000)
            return action

        try:
            await host.goto(args.url)
            original_avatar = await get(host, '/api/avatars/'+previous['avatar_id'])
            assert original_avatar['state'] == 'ready'
            campaign = await post(host, '/api/campaigns', {'story_id': previous['story_id'], 'player_name': '同行测试旅人'})
            room = await post(host, '/api/rooms', {'campaign_id': campaign['id'], 'branch_id': campaign['branch_id'], 'mode': 'independent_characters', 'name': '舞台房主'})
            rid = room['id']; report.update(room_id=rid, campaign=campaign, avatar_id=previous['avatar_id'])
            await host.evaluate('(id)=>localStorage.setItem("rpw-room",id)', rid)
            await host.reload(); await host.locator('.room-shell').wait_for()
            release_session = asyncio.Event()
            async def delayed_session(route):
                await release_session.wait()
                await route.continue_()
            await guest.route('**/api/session', delayed_session)
            await guest.goto(args.url)
            assert await guest.get_by_role('button', name='协作冒险', exact=True).is_disabled()
            release_session.set()
            await guest.get_by_role('button', name='协作冒险', exact=True).click()
            await guest.unroute('**/api/session', delayed_session)
            report['startup_controls_ready'] = True
            await guest.get_by_label('席位名称', exact=True).fill('舞台客人')
            await guest.get_by_label('邀请口令', exact=True).fill(room['invite_code'])
            async with guest.expect_response(lambda r: r.url.endswith('/api/rooms/join') and r.request.method=='POST') as joined:
                await guest.get_by_role('button', name='加入协作房间', exact=True).click()
            assert (await joined.value).ok, await (await joined.value).text()
            await guest.locator('.room-shell').wait_for()
            for page in (host, guest):
                await page.locator('canvas[data-ready="true"]').wait_for(timeout=120000)
            view = await get(guest, '/api/rooms/'+rid)
            npc = next(a for a in view['state']['present_actors'] if a.get('avatar_id') == previous['avatar_id'])
            base = f"/api/rooms/{rid}/avatars/{previous['avatar_id']}"
            assert (await guest.request.get(args.url+'/api/avatars/'+previous['avatar_id'])).status == 404
            assert (await guest.request.get(args.url+'/api/avatars/'+previous['avatar_id']+'/files/profile.json')).status == 404
            profile = await get(guest, base+'/files/profile.json')
            assert set(profile) == {'character_id'}
            state_before = (await get(host, '/api/settings/usage'))['calls']
            public = await say(host, npc['name']+'，请轻轻点头，告诉我们你最喜欢这座港口的什么。')
            for page in (host, guest):
                await page.wait_for_function('(id)=>document.querySelector(".npc-theater canvas")?.dataset.commit===id && Number(document.querySelector(".npc-theater canvas")?.dataset.frames)>10 && Number(document.querySelector(".npc-theater canvas")?.dataset.mouth)>.1', arg=public['result']['id'], timeout=45000)
            report['host_motion'] = await host.locator('.npc-theater canvas').evaluate('(c)=>({...c.dataset})')
            report['guest_motion'] = await guest.locator('.npc-theater canvas').evaluate('(c)=>({...c.dataset})')
            report['public_dialogue'] = public['result']['segments']
            await guest.screenshot(path=str(folder/'guest-desktop.png'), full_page=True)
            before_history = (await get(guest, '/api/rooms/'+rid))['state']['history']
            private = await say(host, '红珊瑚暗语：请仅私下回答我，眼下你最在意的事情是什么？', npc['id'])
            assert (await get(guest, '/api/rooms/'+rid))['state']['history'] == before_history
            assert (await get(guest, f'/api/rooms/{rid}/actions/'+private['id']))['result'] is None
            await guest.wait_for_timeout(2200)
            assert await guest.locator('.npc-theater canvas').get_attribute('data-commit') == public['result']['id']
            assert '红珊瑚暗语' not in await guest.locator('.room-shell').inner_text()
            await guest.set_viewport_size({'width': 390, 'height': 844})
            await guest.screenshot(path=str(folder/'guest-mobile.png'), full_page=True)
            assert await guest.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            await host.get_by_role('button', name='交给舞台客人', exact=True).click()
            await ready(guest)
            await guest.route('**/api/rooms/*/avatars/*/files/puppet/rig.json', lambda route: route.abort())
            await guest.get_by_role('button', name='收起2D人物', exact=True).click()
            await guest.get_by_role('button', name='展开2D人物', exact=True).click()
            await guest.locator('.npc-stage-caption').filter(has_text='形象暂时不可用').wait_for(timeout=30000)
            continued = await say(guest, npc['name']+'，我想听你说说今天港口的生活。')
            assert any(s['kind'] == 'dialogue' for s in continued['result']['segments'])
            await guest.unroute_all(behavior='wait')
            await guest.get_by_role('button', name='收起2D人物', exact=True).click()
            await guest.get_by_role('button', name='展开2D人物', exact=True).click()
            await guest.locator('canvas[data-ready="true"]').wait_for(timeout=45000)
            # After leaving the scene, scoped resources are revoked as well as hidden in the UI.
            await guest.get_by_role('button', name='伙伴、角色与手记', exact=True).click()
            await ready(guest)
            view = await get(guest, '/api/rooms/'+rid)
            destination = view['state']['exits'][0]
            await guest.locator('.room-personal').get_by_role('button', name=destination['name'], exact=True).click()
            for _ in range(240):
                view = await get(guest, '/api/rooms/'+rid)
                if view['state']['location']['id'] == destination['id']: break
                await asyncio.sleep(.5)
            assert view['state']['location']['id'] == destination['id']
            assert (await guest.request.get(args.url+base+'/files/profile.json')).status == 404
            await guest.wait_for_timeout(2200)
            assert await guest.locator('.npc-theater').count() == 0
            report['model_calls'] = (await get(host, '/api/settings/usage'))['calls']-state_before
            assert report['model_calls'] > 0
            assert not report['errors'], report['errors']
            report.update(status='passed', private_stage_unchanged=True, scoped_permissions=True, resource_failure_keeps_story=True, mobile_overflow=False)
        except Exception as exc:
            report.update(status='failed', failure=str(exc))
            await guest.screenshot(path=str(folder/'failure.png'), full_page=True)
            raise
        finally:
            (folder/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
            for who, page in [('host', host), ('guest', guest)]:
                await page.context.storage_state(path=str(folder/(who+'-session.local.json')))
            await browser.close()
    print(json.dumps({k:v for k,v in report.items() if k != 'public_dialogue'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
