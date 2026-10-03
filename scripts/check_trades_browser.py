"""Three browser trade negotiation, real model continuation and restorable consent."""
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
    parser.add_argument('--output', default='outputs/validation/trades-browser')
    parser.add_argument('--restart', action='store_true')
    args = parser.parse_args()
    folder = (ROOT/args.output).resolve()
    if not folder.is_relative_to(ROOT/'outputs/validation'):
        raise ValueError('Invalid evidence path')
    folder.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'mode': 'real_models', 'page_errors': [], 'actions': []}
    requests = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        host, guest, third, restored_host, restored_guest = [await browser.new_page(locale='zh-CN', viewport={'width': 1440, 'height': 1000}) for _ in range(5)]
        pages = [host, guest, third, restored_host, restored_guest]
        for page in pages:
            page.on('pageerror', lambda e: report['page_errors'].append(str(e)))

        async def get(page, path):
            response = await page.request.get(args.url+path)
            assert response.ok, await response.text()
            return await response.json()

        async def post(page, path, data=None):
            csrf = (await (await page.request.post(args.url+'/api/session')).json())['csrf_token']
            response = await page.request.post(args.url+path, data=data, headers={'X-CSRF-Token': csrf})
            assert response.ok, await response.text()
            return await response.json()

        async def room(page):
            return await get(page, '/api/rooms/'+rid)

        async def ready(page):
            await page.wait_for_function("document.querySelector('[aria-label=房间行动]')?.disabled===false", timeout=20000)

        async def click_action(page, button):
            await ready(page)
            usage_before = (await get(host, '/api/settings/usage'))['calls']
            async with page.expect_response(lambda r: r.url.endswith('/actions') and r.request.method == 'POST') as info:
                await button.click()
            response = await info.value
            action = await response.json()
            assert response.status == 202, action
            for _ in range(240):
                action = await get(page, '/api/rooms/'+rid+'/actions/'+action['id'])
                if action['status'] not in {'accepted', 'planning', 'characters', 'narrating'}:
                    break
                await asyncio.sleep(.5)
            assert action['status'] == 'committed', action
            if response.request.post_data_json['command'].get('trade'):
                assert (await get(host, '/api/settings/usage'))['calls'] == usage_before
                report['trade_model_calls'] = 0
            requests.append((page, response.request.post_data_json, action))
            await page.locator(f'.turn[data-version="{action["result"]["version"]}"]').wait_for(timeout=15000)
            report['actions'].append({'id': action['id'], 'version': action['result']['version']})
            print('Committed trade/scenario step', action['result']['version'], flush=True)
            await ready(page)
            return action

        async def handoff(who):
            h = await room(host)
            if h['turn'] != h['me']:
                async with host.expect_response(lambda r: r.url.endswith('/control') and r.request.method == 'POST') as response:
                    await host.get_by_role('button', name='收回行动权', exact=True).click()
                assert (await response.value).ok
                await ready(host)
            if who != host:
                async with host.expect_response(lambda r: r.url.endswith('/control') and r.request.method == 'POST') as response:
                    await host.get_by_role('button', name='交给小灯', exact=True).click()
                assert (await response.value).ok
            # A previously enabled guest composer is not evidence that handoff finished.
            await ready(who)

        async def propose(page, target, item=False, coins=0, request_coins=0):
            await handoff(page)
            await page.get_by_role('button', name='提出交易', exact=True).click()
            await page.get_by_label('交易对象', exact=True).select_option(target)
            if item:
                await page.get_by_label('交出修理工具数量', exact=True).fill('1')
            await page.get_by_label('交出金币', exact=True).fill(str(coins))
            await page.get_by_label('索取金币', exact=True).fill(str(request_coins))
            action = await click_action(page, page.get_by_role('button', name='发送报价', exact=True))
            values = (await room(page))['state']['trades']
            offer = next(o for o in values if o['created_version'] == action['result']['version'])
            return offer['id']

        async def response(page, oid, label):
            await handoff(page)
            return await click_action(page, page.locator('[data-offer="'+oid+'"]').get_by_role('button', name=label, exact=True))

        async def join(page, code, name, create=True):
            await page.goto(args.url)
            await page.get_by_role('button', name='协作冒险', exact=True).click()
            await page.get_by_label('席位名称', exact=True).fill(name)
            await page.get_by_label('邀请口令', exact=True).fill(code)
            if not create:
                await page.get_by_label('首次加入时创建角色', exact=True).uncheck()
            async with page.expect_response(lambda r: r.url.endswith('/api/rooms/join') and r.request.method == 'POST') as info:
                await page.get_by_role('button', name='加入协作房间', exact=True).click()
            value = await (await info.value).json()
            assert value.get('id'), value
            await page.locator('.room-shell').wait_for()
            return value

        try:
            await host.goto(args.url)
            await host.get_by_role('button', name='体验内置雾港故事', exact=False).click()
            await host.locator('.story-toolbar').wait_for()
            campaign = (await get(host, '/api/campaigns'))[-1]
            cid, bid = campaign['id'], campaign['main_branch']
            await host.get_by_role('button', name='协作冒险', exact=True).click()
            await host.get_by_label('房间模式', exact=True).select_option('independent_characters')
            await host.get_by_label('席位名称', exact=True).fill('小舟')
            async with host.expect_response(lambda r: r.url.endswith('/api/rooms') and r.request.method == 'POST') as info:
                await host.get_by_role('button', name='为当前冒险创建房间', exact=True).click()
            original = await (await info.value).json(); rid = original['id']; pc = original['state']['player_actor_id']
            g = await join(guest, original['invite_code'], '小灯'); guest_id = g['state']['player_actor_id']
            await join(third, original['invite_code'], '旁观者')
            report.update(room_id=rid, campaign_id=cid, branch_id=bid)
            initial = [(await room(p))['state'] for p in (host, guest)]
            usage = (await get(host, '/api/settings/usage'))['calls']
            first = await propose(host, guest_id, item=True, request_coins=3)
            assert (await room(host))['state']['inventory'] == initial[0]['inventory']
            assert not (await room(third))['state']['trades']
            await handoff(guest)
            await guest.locator('[data-offer="'+first+'"]').get_by_role('button', name='还价换物', exact=True).click()
            await guest.get_by_label('交出金币', exact=True).fill('4')
            counter_action = await click_action(guest, guest.get_by_role('button', name='发送还价', exact=True))
            counter = next(o for o in (await room(guest))['state']['trades'] if o['created_version'] == counter_action['result']['version'])
            await response(host, counter['id'], '接受并成交')
            assert (await room(host))['state']['resources']['coins'] == 12
            assert (await room(guest))['state']['resources']['coins'] == 4
            assert (await room(guest))['state']['inventory'][0]['id'] == 'item_tools'
            assert not (await room(host))['state']['inventory']
            rejected = await propose(guest, pc, item=True)
            await response(host, rejected, '拒绝报价')
            assert (await room(guest))['state']['inventory'][0]['id'] == 'item_tools'
            withdrawn = await propose(host, guest_id, coins=2)
            await response(host, withdrawn, '撤回报价')
            gift = await propose(guest, pc, item=True)
            state = (await room(guest))['state']; start = state['location']['name']; destination = state['exits'][0]
            await click_action(guest, guest.locator('.room-personal').get_by_role('button', name=destination['name'], exact=True))
            await handoff(host)
            await host.locator('[data-offer="'+gift+'"]').get_by_text('暂不能成交', exact=False).wait_for()
            assert await host.locator('[data-offer="'+gift+'"]').get_by_role('button', name='接受并成交', exact=True).is_disabled()
            await handoff(guest)
            await click_action(guest, guest.locator('.room-personal').get_by_role('button', name=start, exact=True))
            await response(host, gift, '接受并成交')
            assert (await room(host))['state']['inventory'][0]['id'] == 'item_tools'
            # Movement used the real narrator; all financial commands themselves have no traces.
            for page, payload, receipt in requests:
                if payload['command'].get('trade'):
                    current = await post(page, '/api/rooms/'+rid+'/actions', payload)
                    assert current['result'] == receipt['result']
            pending_id = await propose(host, guest_id, coins=1)
            snapshot = (await room(guest))['state']
            await guest.reload(); await guest.locator('.trade-panel').wait_for()
            assert (await room(guest))['state'] == snapshot
            await host.screenshot(path=str(folder/'host-desktop.png'), full_page=True)
            await guest.set_viewport_size({'width': 390, 'height': 844})
            await guest.screenshot(path=str(folder/'guest-mobile.png'), full_page=True)
            assert await guest.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            # Restore consent without retroactively granting any browser a guest character.
            await post(host, f'/api/campaigns/{cid}/branches', {'source_branch_id': bid, 'world_version': snapshot['world_version'], 'title': '交易待确认'})
            backup = await get(host, '/api/campaigns/'+cid+'/backup')
            restored = await post(restored_host, '/api/backups/restore', backup)
            rr = await post(restored_host, '/api/rooms', {'campaign_id': restored['id'], 'branch_id': restored['branch_id'], 'name': '恢复房主', 'mode': 'independent_characters'})
            seat = await join(restored_guest, rr['invite_code'], '恢复参与者', create=False)
            assert seat['state'] is None
            await post(restored_host, '/api/rooms/'+rr['id']+'/control', {'expected_revision': seat['revision'], 'operation': 'assign', 'member_id': seat['me'], 'actor_id': guest_id})
            restored_view = await get(restored_guest, '/api/rooms/'+rr['id'])
            assert restored_view['state'] == snapshot
            await post(restored_host, '/api/rooms/'+rr['id']+'/control', {'expected_revision': restored_view['revision'], 'operation': 'pass', 'member_id': seat['me']})
            restored_view = await get(restored_guest, '/api/rooms/'+rr['id'])
            restored_action = await post(restored_guest, '/api/rooms/'+rr['id']+'/actions', {'expected_revision': restored_view['revision'], 'command': {'action_id': 'restore_trade_'+rid, 'expected_world_version': snapshot['world_version'], 'mode': 'act', 'text': '确认恢复的报价', 'trade': {'kind': 'accept', 'offer_id': pending_id}}})
            for _ in range(100):
                restored_action = await get(restored_guest, '/api/rooms/'+rr['id']+'/actions/'+restored_action['id'])
                if restored_action['status'] == 'committed': break
                await asyncio.sleep(.1)
            assert restored_action['status'] == 'committed'
            assert next(o for o in (await room(guest))['state']['trades'] if o['id'] == pending_id)['status'] == 'pending'
            await handoff(host)
            await host.get_by_label('房间行动方式', exact=True).select_option('say')
            await host.get_by_label('房间行动', exact=True).fill('船长，我刚与同伴完成交易，工具又回到我手中。接下来修船需要做什么？请只说明，先不要接过工具。')
            dialogue = await click_action(host, host.get_by_role('button', name='提交我的行动', exact=True))
            assert any(s['kind'] == 'dialogue' for s in dialogue['result']['segments'])
            assert (await room(host))['state']['inventory'][0]['id'] == 'item_tools'
            report['dialogue'] = dialogue['result']['segments']
            report['host_usage'] = await get(host, '/api/settings/usage')
            assert report['host_usage']['calls'] > usage
            assert (await get(guest, '/api/settings/usage'))['calls'] == 0
            if args.restart:
                pairs = [(host, rid), (guest, rid), (third, rid), (restored_host, rr['id']), (restored_guest, rr['id'])]
                snapshots = [await get(page, '/api/rooms/'+room_id) for page, room_id in pairs]
                (folder/'before-restart.json').write_text(json.dumps(snapshots, ensure_ascii=False, indent=2))
                record = json.loads((ROOT/'outputs/services/web.json').read_text())
                assert args.url.rstrip('/') == f"http://127.0.0.1:{record['port']}"
                journal = ROOT/'data/journal.jsonl'; prefix = journal.read_bytes()
                statuses, jobs = {}, {}
                def visit(body):
                    kind = body['kind']
                    if kind == 'action.accepted': statuses[body['action']['id']] = body['action']['status']
                    elif kind == 'action.updated' and 'status' in body['patch']: statuses[body['id']] = body['patch']['status']
                    elif kind == 'world.committed': statuses[body['action_id']] = 'committed'
                    elif kind == 'room.member_joined': statuses[body['action']['id']] = 'committed'
                    elif kind == 'studio.saved' and body['collection'] == 'jobs': jobs[body['value']['id']] = body['value']['status']
                    elif kind == 'studio.batch_saved':
                        for item in body['items']: visit({'kind': 'studio.saved', **item})
                for line in prefix.splitlines(): visit(json.loads(line)['body'])
                assert not any(v in {'accepted','planning','characters','narrating'} for v in statuses.values())
                assert not any(v in {'queued','generating_world','generating_story','testing'} for v in jobs.values())
                for operation in ('stop', 'start'):
                    await asyncio.to_thread(subprocess.run, [sys.executable, 'scripts/manage.py', operation, '--port', str(record['port'])], cwd=ROOT, check=True)
                actual = [await get(page, '/api/rooms/'+room_id) for page, room_id in pairs]
                (folder/'after-restart.json').write_text(json.dumps(actual, ensure_ascii=False, indent=2))
                assert actual == snapshots, 'Room views changed across restart'
                for page, payload, receipt in requests:
                    assert (await post(page, '/api/rooms/'+rid+'/actions', payload))['result'] == receipt['result']
                assert journal.read_bytes().startswith(prefix)
                report.update(real_restart=True, preserved_journal_bytes=len(prefix), repeated_action_receipts=len(requests))
            for index, page in enumerate(pages):
                await page.context.storage_state(path=str(folder/f'session-{index}.local.json'))
            assert not report['page_errors']
            report.update(status='passed', consent=True, counteroffer=True, privacy=True, conservation=True, restored_consent=True, mobile_overflow=False)
        except Exception as exc:
            report.update(status='failed', failure=str(exc))
            await host.screenshot(path=str(folder/'failure.png'), full_page=True)
            raise
        finally:
            (folder/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
            await browser.close()
    print(json.dumps({k:v for k,v in report.items() if k not in {'actions', 'dialogue'}}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
