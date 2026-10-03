"""Create an RPG in the browser, then exercise its authored rules against live models."""

import argparse
import asyncio
import json
import uuid
from collections import deque
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18091')
    parser.add_argument('--system', choices=['d20', 'd100'], default='d20')
    parser.add_argument('--output', default='outputs/validation/rules-browser')
    args = parser.parse_args()
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT / 'outputs/validation'):
        raise ValueError('Output outside validation folder')
    folder.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'mode': 'live_models', 'errors': [], 'actions': []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page(locale='zh-CN', viewport={'width': 1440, 'height': 1080})
        page.on('pageerror', lambda e: report['errors'].append(str(e)))
        try:
            await page.goto(args.url)
            await page.get_by_role('button', name='创建我的世界', exact=True).click()
            await page.get_by_label('世界构想', exact=True).fill(
                '温暖奇幻风格的苔灯镇，旅人可以邀请守灯人同行、从杂货店购买补给，探索旧矿洞并击败弱小的训练傀儡。'
                '地点0是安全的镇口，有商店和愿意接受旅行邀请的守灯人。装备是灯杖和披风，初始有灯杖与恢复药。')
            await page.get_by_label('第一个故事（可选）').fill('从地点0的镇口开始。寻找熄灭路灯的原因，调查三处线索后修复灯芯。')
            await page.get_by_label('冒险规则', exact=True).select_option(args.system)
            await page.screenshot(path=str(folder / 'create.png'))
            async with page.expect_response(lambda r: r.url.endswith('/api/studio/worlds') and r.request.method == 'POST') as response:
                await page.get_by_role('button', name='生成世界与第一个故事', exact=True).click()
            response = await response.value
            assert response.status == 202, await response.text()
            job = await response.json()
            await page.context.storage_state(path=str(folder / 'browser-session.local.json'))
            previous = None
            for _ in range(600):
                job = await (await page.request.get(args.url + '/api/studio/jobs/' + job['id'])).json()
                status = (job['status'], len(job['steps']))
                if status != previous:
                    print('creation', *status, job.get('error') or '', flush=True)
                    previous = status
                (folder / 'job.json').write_text(json.dumps(job, ensure_ascii=False, indent=2))
                if job['status'] in {'ready','failed','interrupted','cancelled','recovery_required'}:
                    break
                await asyncio.sleep(2)
            assert job['status'] == 'ready', job.get('error')
            assert any(c['name'] == '冒险规则与确定性回放' for c in job['checks'])
            exported = await (await page.request.get(args.url + '/api/studio/stories/' + job['story_id'] + '/export')).json()
            (folder / 'story.json').write_text(json.dumps(exported, ensure_ascii=False, indent=2))
            rules = exported['world']['rules']
            assert rules['system'] == args.system and rules['shops'] and rules['enemies']
            await page.reload()
            await page.get_by_role('button', name='编辑世界', exact=True).click()
            await page.locator('.rules-editor').wait_for()
            await page.locator('.rules-editor').screenshot(path=str(folder / 'rules-editor.png'))
            await page.get_by_role('button', name='退出编辑', exact=True).click()
            story = page.locator('[data-story-id="'+job['story_id']+'"]')
            async with page.expect_response(lambda r: r.url.endswith('/api/campaigns') and r.request.method == 'POST') as response:
                await story.get_by_role('button', name='开始这个故事', exact=True).click()
            campaign = await (await response.value).json()
            root = args.url + '/api/campaigns/' + campaign['id'] + '/branches/' + campaign['branch_id']
            session = await (await page.request.post(args.url + '/api/session')).json()
            headers = {'X-CSRF-Token': session['csrf_token']}
            await page.context.storage_state(path=str(folder / 'browser-session.local.json'))

            async def view():
                return await (await page.request.get(root + '/view')).json()

            async def wait_action(action):
                for _ in range(360):
                    action = await (await page.request.get(args.url + '/api/actions/' + action['id'])).json()
                    if action['status'] in {'committed','failed','cancelled','interrupted','recovery_required'}:
                        break
                    await asyncio.sleep(.5)
                assert action['status'] == 'committed', action
                v = await view()
                report['actions'].append({'version':v['world_version'],'input':action['result']['player_text'],
                                          'effects':action['result']['effects'],'roll':action['result'].get('roll')})
                print('action', v['world_version'], action['result']['player_text'], flush=True)
                return v

            async def act(op, text=None):
                v = await view()
                command = {'action_id':'qa_'+uuid.uuid4().hex[:20], 'expected_world_version':v['world_version'],
                           'mode':'act','text':text or '执行选定操作：'+op['kind'],'selected_operation':op}
                response = await page.request.post(root + '/actions', data=command, headers=headers)
                assert response.status == 202, await response.text()
                action = await response.json()
                v = await wait_action(action)
                duplicate = await (await page.request.post(root + '/actions', data=command, headers=headers)).json()
                assert duplicate['status'] == 'committed' and duplicate['id'] == action['id']
                assert (await view())['world_version'] == v['world_version']
                return v

            async def travel(target):
                v = await view()
                start = int(v['location']['id'].split('_')[1])
                queue = deque([(start, [])]); seen = {start}
                places = exported['world']['locations']
                while queue:
                    i, path = queue.popleft()
                    if i == target:
                        for j in path:
                            await act({'kind':'move','target_id':f'loc_{j}'}, '我前往'+places[j]['name']+'。')
                        return
                    adjacent = set(places[i]['connects_to']) | {j for j,p in enumerate(places) if i in p['connects_to']}
                    for j in adjacent - seen:
                        seen.add(j); queue.append((j, path+[j]))
                raise AssertionError('Unreachable target')

            v = await view()
            equips = [a for a in v['rule_actions'] if a['kind'] == 'equip']
            if equips:
                await page.get_by_role('button', name='装备 ', exact=False).first.click()
                await page.locator('.turn[data-version="1"]').wait_for(timeout=185000)
                v = await view()
                assert any(v['equipment'].values())
                report['browser_equipment'] = True
            await travel(rules['shops'][0]['location'])
            v = await view()
            buys = [a for a in v['rule_actions'] if a['kind'] == 'buy']
            assert buys, 'Generated starting economy must allow a purchase'
            buy = buys[0]
            price = next(i['price'] for i in rules['items'] if i['id'] == buy['item_id'])
            before = v['resources']['coins']
            v = await act(buy)
            assert v['resources']['coins'] == before-price
            gear = next(i for i in v['inventory'] if i['id'].startswith('loot_'))
            v = await act({'kind':'sell','target_id':buy['target_id'],'item_id':gear['id']})
            assert v['resources']['coins'] == before-price+max(1,price//2)
            if rules['recruitable']:
                index = rules['recruitable'][0]
                await travel(exported['world']['characters'][index]['location'])
                v = await act({'kind':'recruit','target_id':f'npc_{index}'}, '我邀请你结伴调查路灯，我们相互照应，尊重你的安排。')
                report['recruited'] = any(a['id'] == f'npc_{index}' for a in v['party'])
            enemy = rules['enemies'][0]
            await travel(enemy['location'])
            for _ in range(24):
                v = await view()
                target = next(e for e in v['enemies'] if e['id'] == 'enemy_'+enemy['id'])
                if target['hp'] == 0:
                    break
                assert v['resources']['hp'] > 0, 'Generated encounter defeated acceptance player'
                v = await act({'kind':'attack','target_id':target['id']}, '我用手中的装备攻击'+target['name']+'。')
                uses = [a for a in v['rule_actions'] if a['kind'] == 'use']
                if uses and v['resources']['hp'] < v['resource_limits']['hp']:
                    await act(uses[0])
            assert target['hp'] == 0, 'Generated foe not defeated within bounded combat'
            xp = v['resources']['xp']
            assert xp >= enemy['reward_xp']
            assert not any(a['kind'] == 'attack' and a['target_id'] == target['id'] for a in v['rule_actions'])
            if not any(a['kind']=='rest' for a in v['rule_actions']):
                safe = next(i for i in range(len(exported['world']['locations'])) if all(e['location'] != i for e in rules['enemies']))
                await travel(safe)
            await act({'kind':'rest','target_id':v['player_actor_id']})
            v = await view()
            assert v['resources']['hp'] == v['resource_limits']['hp']
            response = await page.request.post(root.rsplit('/',1)[0], headers=headers,
                data={'source_branch_id':campaign['branch_id'],'world_version':0,'title':'规则初始分支'})
            assert response.status == 201, await response.text()
            fork = await response.json()
            base = await (await page.request.get(root.rsplit('/',1)[0]+'/'+fork['id']+'/view')).json()
            assert base['resources']['coins'] == rules['coins'] and base['resources']['xp'] == 0
            await page.reload()
            await page.locator('.game-panel').wait_for()
            await page.screenshot(path=str(folder / 'adventure.png'))
            await page.set_viewport_size({'width':390,'height':844})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path=str(folder / 'mobile.png'))
            assert not report['errors'], report['errors']
            report.update(status='passed',system=args.system,campaign=campaign,creation_steps=len(job['steps']),
                          transactions=True,defeated=True,branch_isolated=True,mobile_overflow=False)
        except Exception as exc:
            report.update(status='failed',error=str(exc)[:1500])
            await page.screenshot(path=str(folder / 'failure.png'),full_page=True)
            raise
        finally:
            (folder / 'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            await browser.close()
    print('RULES BROWSER PASSED',flush=True)


if __name__ == '__main__':
    asyncio.run(main())
