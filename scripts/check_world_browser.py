"""Live creator, notes, autonomous world, dynamic map and cross-story continuity acceptance."""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]


async def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',default='http://127.0.0.1:18091')
    p.add_argument('--output',default='outputs/validation/world-browser')
    args=p.parse_args();folder=(ROOT/args.output).resolve()
    if not folder.is_relative_to(ROOT/'outputs/validation'):
        raise ValueError('Output outside validation folder')
    folder.mkdir(parents=True,exist_ok=False)
    report={'status':'running','mode':'live_models','errors':[],'actions':[]}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,args=['--no-sandbox'])
        page=await browser.new_page(locale='zh-CN', viewport={'width':1440,'height':1080})
        page.on('pageerror',lambda e:report['errors'].append(str(e)))
        async def get(path):
            response=await page.request.get(args.url+path);assert response.ok,await response.text()
            return await response.json()
        async def post(path,data=None):
            response=await page.request.post(args.url+path,data=data,headers=headers)
            assert response.ok,await response.text()
            return await response.json()
        async def job_wait(job,label):
            last=None
            for _ in range(600):
                job=await get('/api/studio/jobs/'+job['id'])
                status=(job['status'],len(job['steps']))
                if status!=last:
                    print(label,*status,job.get('error') or '',flush=True);last=status
                (folder/(label+'.json')).write_text(json.dumps(job,ensure_ascii=False,indent=2))
                if job['status'] in {'ready','failed','interrupted','cancelled','recovery_required'}:
                    break
                await asyncio.sleep(2)
            assert job['status']=='ready',job
            return job
        async def wait_version(version):
            await page.locator(f'.turn[data-version="{version}"]').wait_for(timeout=185000)
        try:
            await page.goto(args.url)
            session=await (await page.request.post(args.url+'/api/session')).json()
            headers={'X-CSRF-Token':session['csrf_token']}
            await page.get_by_role('button',name='创建我的世界',exact=True).click()
            await page.get_by_label('世界构想',exact=True).fill('晨湾镇的开放沙盒。地点0码头，其他地点集市、旧灯塔、山坡。守灯人、商贩、园艺师各有目标。园艺公会经过两次十分钟准备公开屋顶花园，花园中会出现新的联络员小禾。至少两名NPC不在玩家起点。')
            await page.get_by_label('第一个故事（可选）').fill('从码头寻找被送错的邮袋，调查线索后完成交接，有可达的结局。')
            await page.get_by_label('自动设计主动世界').check()
            async with page.expect_response(lambda r:r.url.endswith('/api/studio/worlds') and r.request.method=='POST') as response:
                await page.get_by_role('button',name='生成世界与第一个故事',exact=True).click()
            job=await job_wait(await (await response.value).json(),'world')
            await page.context.storage_state(path=str(folder/'session.local.json'))
            exported=await get('/api/studio/stories/'+job['story_id']+'/export')
            (folder/'story.json').write_text(json.dumps(exported,ensure_ascii=False,indent=2))
            sim=exported['world']['simulation']
            assert sim and any(f.get('expansion') for f in sim['factions'])
            await page.reload()
            async with page.expect_response(lambda r:r.url.endswith('/api/campaigns') and r.request.method=='POST') as response:
                await page.locator('[data-story-id="'+job['story_id']+'"]').get_by_role('button',name='开始这个故事',exact=True).click()
            campaign=await (await response.value).json()
            base='/api/campaigns/'+campaign['id']+'/branches/'+campaign['branch_id']
            async def act(text,mode='wait'):
                view=await get(base+'/view')
                a=await post(base+'/actions',{'action_id':'worldqa_'+uuid.uuid4().hex[:18],
                           'expected_world_version':view['world_version'],'mode':mode,'text':text})
                for _ in range(360):
                    a=await get('/api/actions/'+a['id'])
                    if a['status'] in {'committed','failed','cancelled','interrupted'}:break
                    await asyncio.sleep(.5)
                assert a['status']=='committed',a
                report['actions'].append(a['result']);print('action',a['result']['version'],text,flush=True)
                return await get(base+'/view')
            await page.locator('.note-editor summary').click()
            await page.get_by_label('手记类型').select_option('commitment')
            await page.get_by_label('手记内容').fill('以后要去花园寻找青瓷风铃，先记录线索，不替居民承诺。')
            await page.get_by_role('button',name='保存手记',exact=True).click()
            await wait_version(1)
            view=await get(base+'/view');assert view['game_time_s']==0 and len(view['notes'])==1
            await page.get_by_role('button',name='标记完成',exact=False).click()
            await wait_version(2);view=await get(base+'/view');assert view['notes'][0]['status']=='done'
            await page.get_by_role('button',name='重新打开',exact=True).click();await wait_version(3)
            await page.locator('.memory-panel>details').first.locator('summary').first.click()
            await page.get_by_label('检索往事').fill('青瓷风铃')
            await page.get_by_role('button',name='搜索往事',exact=True).click()
            await page.locator('.memory-result').first.wait_for()
            assert '个人手记' in await page.locator('.memory-panel').inner_text() or '待办与约定' in await page.locator('.memory-panel').inner_text()
            await page.get_by_role('button',name='暂停世界主动运行',exact=True).click();await wait_version(4)
            view=await act('我在这里等待十分钟。')
            assert view['simulation']['paused'] and view['simulation']['elapsed_s']==0
            await page.reload();await page.get_by_role('button',name='恢复世界主动运行',exact=True).click();await wait_version(6)
            threshold=max(f['interval_s']*f['threshold'] for f in sim['factions'])
            for _ in range((threshold+1799)//1800):
                view=await act('我在这里等待三十分钟。')
            assert all(f['completed'] for f in view['simulation']['factions'])
            new_regions=[p for p in view['map'] if p['id'].startswith('region_')]
            assert new_regions and len(view['map'])>len(exported['world']['locations'])
            for f in sim['factions']:
                resident=(f.get('expansion') or {}).get('resident')
                if resident:
                    assert resident['secret'] not in json.dumps(view['known_facts'],ensure_ascii=False)
            await page.reload();await page.screenshot(path=str(folder/'world.png'))
            await page.set_viewport_size({'width':390,'height':844});assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path=str(folder/'mobile.png'));await page.set_viewport_size({'width':1440,'height':1080})
            before=view
            await page.get_by_role('button',name='返回世界库',exact=True).click()
            await page.get_by_role('button',name='新建故事',exact=True).click()
            await page.get_by_label('故事构想',exact=True).fill('同一世界的另一次故事，从码头调查一封迟到的邀请函。保留原有世界和人物，用新的线索与目标。')
            async with page.expect_response(lambda r:r.url.endswith('/stories') and r.request.method=='POST') as response:
                await page.get_by_role('button',name='生成新故事',exact=True).click()
            next_job=await job_wait(await (await response.value).json(),'next-story')
            await page.reload()
            card=page.locator('[data-story-id="'+next_job['story_id']+'"]')
            await card.get_by_role('combobox').select_option(campaign['id'])
            async with page.expect_response(lambda r:r.url.endswith('/api/campaigns') and r.request.method=='POST') as response:
                await card.get_by_role('button',name='开始这个故事',exact=True).click()
            created=await (await response.value).json();assert 'id' in created,created
            after=await get('/api/campaigns/'+created['id']+'/branches/'+created['branch_id']+'/view')
            assert after['world_version']==0 and after['game_time_s']==before['game_time_s']
            assert after['resources']==before['resources'] and after['notes']==before['notes']
            assert {p['id'] for p in after['map']}=={p['id'] for p in before['map']}
            assert after['continuity_origin']['campaign_id']==campaign['id']
            assert (await get(base+'/view'))['world_version']==before['world_version']
            assert not report['errors'],report['errors']
            await page.screenshot(path=str(folder/'continuation.png'))
            report.update(status='passed',campaign=campaign,next_campaign=created,notes=True,paused=True,
                          dynamic_regions=[p['name'] for p in new_regions],continuity=True,mobile_overflow=False)
        except Exception as exc:
            report.update(status='failed',error=str(exc)[:2000]);await page.screenshot(path=str(folder/'failure.png'),full_page=True)
            raise
        finally:
            (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');await browser.close()
    print('WORLD BROWSER PASSED',flush=True)


if __name__=='__main__':asyncio.run(main())
