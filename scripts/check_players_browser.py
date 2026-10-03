"""Three independent browsers, real model dialogue, private views and restored seats."""
import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18091')
    parser.add_argument('--output', default='outputs/validation/players-browser')
    parser.add_argument('--restart', action='store_true', help='Also restart only this project’s idle managed service')
    args = parser.parse_args()
    folder = (ROOT/args.output).resolve()
    if not folder.is_relative_to(ROOT/'outputs/validation'):
        raise ValueError('Reports must stay within project validation outputs')
    folder.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'mode': 'real_models', 'page_errors': [], 'actions': []}
    requests = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        pages = [await browser.new_page(locale='zh-CN', viewport={'width': 1440, 'height': 1000}) for _ in range(5)]
        host, guest, third, restored_host, restored_guest = pages
        for page in pages:
            page.on('pageerror', lambda e: report['page_errors'].append(str(e)))

        async def get(page, path):
            response = await page.request.get(args.url+path)
            assert response.ok, await response.text()
            return await response.json()

        async def post(page, path, payload=None):
            csrf = (await (await page.request.post(args.url+'/api/session')).json())['csrf_token']
            response = await page.request.post(args.url+path, data=payload, headers={'X-CSRF-Token': csrf})
            assert response.ok, await response.text()
            return await response.json()

        async def room(page, rid):
            return await get(page, '/api/rooms/'+rid)

        async def editable(page):
            await page.wait_for_function("!document.querySelector('[aria-label=房间行动]')?.disabled", timeout=20000)

        async def join(page, code, name, create=True):
            await page.goto(args.url)
            await page.get_by_role('button', name='协作冒险', exact=True).click()
            await page.get_by_label('席位名称', exact=True).fill(name)
            await page.get_by_label('角色身份', exact=True).fill('寻找往事的旅行者')
            await page.get_by_label('邀请口令', exact=True).fill(code)
            if not create:
                await page.get_by_label('首次加入时创建角色', exact=True).uncheck()
            async with page.expect_response(lambda r: r.url.endswith('/api/rooms/join') and r.request.method == 'POST') as info:
                await page.get_by_role('button', name='加入协作房间', exact=True).click()
            result = await (await info.value).json()
            assert result.get('id'), result
            await page.locator('.room-shell').wait_for()
            return result

        async def committed(page, rid, response, text):
            action = await response.json()
            assert response.status == 202, action
            for _ in range(250):
                action = await get(page, f'/api/rooms/{rid}/actions/'+action['id'])
                if action['status'] in {'committed', 'failed', 'cancelled', 'interrupted', 'recovery_required'}:
                    break
                await asyncio.sleep(.75)
            assert action['status'] == 'committed', action
            await page.locator(f'.turn[data-version="{action["result"]["version"]}"]').wait_for(timeout=15000)
            report['actions'].append({'id': action['id'], 'text': text, 'version': action['result']['version']})
            requests.append((page, rid, response.request.post_data_json, action))
            print('committed', action['result']['version'], text, flush=True)
            return action

        async def say(page, rid, text, whisper=None, mode='say'):
            await editable(page)
            await page.get_by_label('房间行动方式', exact=True).select_option(mode)
            if mode == 'say':
                await page.get_by_label('对谁说', exact=True).select_option(whisper or '')
            await page.get_by_label('房间行动', exact=True).fill(text)
            async with page.expect_response(lambda r: r.url.endswith('/actions') and r.request.method == 'POST') as info:
                await page.get_by_role('button', name='提交我的行动', exact=True).click()
            return await committed(page, rid, await info.value, text)

        try:
            await host.goto(args.url)
            await host.get_by_role('button', name='体验内置雾港故事', exact=False).click()
            await host.locator('.story-toolbar').wait_for()
            campaigns = await get(host, '/api/campaigns'); campaign = campaigns[-1]
            cid, bid = campaign['id'], campaign['main_branch']
            await host.get_by_role('button', name='协作冒险', exact=True).click()
            await host.get_by_label('席位名称', exact=True).fill('小舟')
            await host.get_by_label('房间模式', exact=True).select_option('independent_characters')
            async with host.expect_response(lambda r: r.url.endswith('/api/rooms') and r.request.method == 'POST') as info:
                await host.get_by_role('button', name='为当前冒险创建房间', exact=True).click()
            original = await (await info.value).json(); rid = original['id']; primary = original['state']['player_actor_id']
            report.update(room_id=rid, campaign_id=cid, branch_id=bid)
            await host.get_by_label('房间邀请口令', exact=True).wait_for()
            joined = await join(guest, original['invite_code'], '小灯'); pc = joined['state']['player_actor_id']
            await join(third, original['invite_code'], '小石')
            assert pc != primary and not joined['state']['inventory']
            await host.get_by_role('button', name='交给小灯', exact=True).click()
            public = await say(guest, rid, '船长您好，我是小灯。想请教修船最需要什么，请只回答我的问题。')
            assert any(s['kind'] == 'dialogue' for s in public['result']['segments'])
            assert any(s.get('speaker_id') == pc for c in (await room(host, rid))['state']['history'] for s in c['segments'])
            await editable(guest)
            await guest.locator('.note-editor summary').click()
            await guest.get_by_label('手记内容', exact=True).fill('紫月银钥：只属于小灯的调查计划。')
            async with guest.expect_response(lambda r: r.url.endswith('/actions') and r.request.method == 'POST') as info:
                await guest.get_by_role('button', name='保存手记', exact=True).click()
            private_note = await committed(guest, rid, await info.value, '私人手记')
            assert '紫月银钥' not in json.dumps(await room(host, rid), ensure_ascii=False)
            assert (await get(host, f'/api/rooms/{rid}/actions/'+private_note['id']))['result'] is None
            before_usage = (await get(host, '/api/settings/usage'))['calls']
            whisper = await say(guest, rid, '白羽纸船：这是只告诉小舟的约定。', primary)
            assert (await get(host, '/api/settings/usage'))['calls'] == before_usage
            assert '白羽纸船' in json.dumps((await room(host, rid))['state']['history'], ensure_ascii=False)
            assert '白羽纸船' not in json.dumps(await room(third, rid), ensure_ascii=False)
            assert (await get(third, f'/api/rooms/{rid}/actions/'+whisper['id']))['result'] is None
            private_npc = await say(guest, rid, '橙灯细语：船长，请私下告诉我你最担心什么。', 'npc_captain')
            assert any(s.get('speaker_id') == 'npc_captain' for s in private_npc['result']['segments'])
            assert '橙灯细语' not in json.dumps(await room(host, rid), ensure_ascii=False)
            start = (await room(guest, rid))['state']['location']['name']
            destination = (await room(guest, rid))['state']['exits'][0]
            await editable(guest)
            async with guest.expect_response(lambda r: r.url.endswith('/actions') and r.request.method == 'POST') as info:
                await guest.locator('.room-personal').get_by_role('button', name=destination['name'], exact=True).click()
            await committed(guest, rid, await info.value, '独立移动')
            assert (await room(host, rid))['state']['location']['name'] == start
            await host.get_by_role('button', name='收回行动权', exact=True).click()
            remote = await say(host, rid, '青松铃铛：我留在这里，与大家商量下一步。')
            assert (await get(guest, f'/api/rooms/{rid}/actions/'+remote['id']))['result'] is None
            await host.get_by_role('button', name='交给小灯', exact=True).click()
            await editable(guest)
            async with guest.expect_response(lambda r: r.url.endswith('/actions') and r.request.method == 'POST') as info:
                await guest.locator('.room-personal').get_by_role('button', name=start, exact=True).click()
            await committed(guest, rid, await info.value, '返回场景')
            assert '青松铃铛' not in json.dumps(await room(guest, rid), ensure_ascii=False)
            before = await room(guest, rid)
            await guest.reload(); await guest.locator(f'[data-player="{pc}"]').wait_for()
            assert (await room(guest, rid))['state'] == before['state']
            await guest.locator('.memory-panel details').first.locator('summary').first.click()
            await guest.get_by_label('检索往事', exact=True).fill('白羽纸船')
            await guest.get_by_role('button', name='搜索往事', exact=True).click()
            await guest.locator('.memory-result').filter(has_text='白羽纸船').first.wait_for()
            async with guest.expect_download() as info:
                await guest.get_by_role('link', name='导出我的经历', exact=False).click()
            download = await info.value; await download.save_as(folder/'guest-perspective.json')
            exported = (folder/'guest-perspective.json').read_text()
            assert '紫月银钥' in exported and '青松铃铛' not in exported
            await host.screenshot(path=str(folder/'host-desktop.png'), full_page=True)
            await guest.screenshot(path=str(folder/'guest-desktop.png'), full_page=True)
            await guest.set_viewport_size({'width': 390, 'height': 844})
            await guest.screenshot(path=str(folder/'guest-mobile.png'), full_page=True)
            assert await guest.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            await guest.get_by_role('button', name='伙伴、角色与手记', exact=True).click()
            assert await guest.locator('.room-seats').is_visible()
            assert await guest.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            await guest.get_by_role('button', name='收起伙伴与角色面板', exact=True).click()
            fork = await post(host, f'/api/campaigns/{cid}/branches', {'source_branch_id': bid, 'world_version': before['world_version'], 'title': '多人备份分支'})
            assert fork['id'] != bid
            backup = await get(host, '/api/campaigns/'+cid+'/backup')
            await restored_host.goto(args.url)
            restored = await post(restored_host, '/api/backups/restore', backup)
            new_room = await post(restored_host, '/api/rooms', {'campaign_id': restored['id'], 'branch_id': restored['branch_id'], 'name': '新房主', 'mode': 'independent_characters'})
            await restored_host.evaluate('(id)=>localStorage.setItem("rpw-room",id)', new_room['id'])
            await restored_host.reload(); await restored_host.get_by_label('房间邀请口令', exact=True).wait_for()
            new_seat = await join(restored_guest, new_room['invite_code'], '恢复席位', create=False)
            assert new_seat['state'] is None
            member = restored_host.locator('.room-member').filter(has_text='恢复席位')
            await member.locator('summary').click()
            await member.get_by_label('分配给恢复席位', exact=True).select_option(pc)
            await member.get_by_role('button', name='确认分配给恢复席位', exact=True).click()
            await restored_guest.locator(f'[data-player="{pc}"]').wait_for(timeout=15000)
            assert (await room(restored_guest, new_room['id']))['state'] == before['state']
            await restored_host.get_by_role('button', name='交给恢复席位', exact=True).click()
            await say(restored_guest, new_room['id'], '备份恢复后，我继续与船长交谈。', 'npc_captain')
            if args.restart:
                pairs = [(host, rid), (guest, rid), (third, rid), (restored_host, new_room['id']), (restored_guest, new_room['id'])]
                snapshots = [await room(page, room_id) for page, room_id in pairs]
                (folder/'before-restart.json').write_text(json.dumps(snapshots, ensure_ascii=False, indent=2))
                for index, (page, _) in enumerate(pairs):
                    await page.context.storage_state(path=str(folder/f'restart-session-{index}.local.json'))
                record = json.loads((ROOT/'outputs/services/web.json').read_text())
                assert args.url.rstrip('/') == f"http://127.0.0.1:{record['port']}", 'Restart requires the managed service'
                assert Path(f"/proc/{record['pid']}/cwd").resolve() == ROOT
                journal = ROOT/'data/journal.jsonl'; prefix = journal.read_bytes()
                statuses, jobs = {}, {}
                def visit(body):
                    kind = body['kind']
                    if kind == 'action.accepted':
                        statuses[body['action']['id']] = body['action']['status']
                    elif kind == 'action.updated' and 'status' in body['patch']:
                        statuses[body['id']] = body['patch']['status']
                    elif kind == 'world.committed':
                        statuses[body['action_id']] = 'committed'
                    elif kind == 'room.member_joined':
                        statuses[body['action']['id']] = 'committed'
                    elif kind == 'studio.saved' and body['collection'] == 'jobs':
                        jobs[body['value']['id']] = body['value']['status']
                    elif kind == 'studio.batch_saved':
                        for item in body['items']:
                            visit({'kind': 'studio.saved', **item})
                for line in prefix.splitlines():
                    visit(json.loads(line)['body'])
                assert not any(v in {'accepted','planning','characters','narrating'} for v in statuses.values()), 'Service has active actions'
                assert not any(v in {'queued','generating_world','generating_story','testing'} for v in jobs.values()), 'Service has active creation jobs'
                for operation in ('stop', 'start'):
                    await asyncio.to_thread(subprocess.run, [sys.executable, 'scripts/manage.py', operation, '--port', str(record['port'])], cwd=ROOT, check=True)
                actual = [await room(page, room_id) for page, room_id in pairs]
                (folder/'after-restart.json').write_text(json.dumps(actual, ensure_ascii=False, indent=2))
                for index, ((page, room_id), expected) in enumerate(zip(pairs, snapshots, strict=True)):
                    assert actual[index] == expected, f'View {index} changed across restart; see before/after-restart.json'
                    await page.reload(); await page.locator('.room-shell').wait_for()
                for page, room_id, payload, previous in requests:
                    response = await post(page, f'/api/rooms/{room_id}/actions', payload)
                    assert response['status'] == 'committed' and response['result'] == previous['result']
                assert journal.read_bytes().startswith(prefix)
                report.update(real_restart=True, preserved_journal_bytes=len(prefix), repeated_action_receipts=len(requests))
            await guest.context.storage_state(path=str(folder/'guest-session.local.json'))
            await host.context.storage_state(path=str(folder/'host-session.local.json'))
            report['host_usage'] = await get(host, '/api/settings/usage')
            assert report['host_usage']['calls'] > 0
            assert (await get(guest, '/api/settings/usage'))['calls'] == 0
            assert not report['page_errors'], report['page_errors']
            report.update(status='passed', restored_campaign=restored, independent_identity=True, private_history=True,
                          mobile_overflow=False, backup_rebind=True, reload=True, human_whisper_model_calls=0)
        except Exception as exc:
            report.update(status='failed', failure=str(exc))
            await guest.screenshot(path=str(folder/'failure.png'), full_page=True)
            raise
        finally:
            (folder/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
            await browser.close()
    print(json.dumps({k:v for k,v in report.items() if k!='actions'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
