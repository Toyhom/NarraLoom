"""Live optional Avatar creation and committed-dialogue browser acceptance (GPUQ required)."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]

async def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='http://127.0.0.1:18091');p.add_argument('--reference',type=Path,required=True);p.add_argument('--resume',type=Path);p.add_argument('--output',default='outputs/validation/avatar-browser');args=p.parse_args()
    folder=(ROOT/args.output).resolve()
    if not folder.is_relative_to(ROOT/'outputs/validation'):raise ValueError('Invalid evidence path')
    folder.mkdir(parents=True,exist_ok=False)
    reference=folder/'reference.png';reference.write_bytes(args.reference.read_bytes())
    report={'status':'running','mode':'real_gpuq_and_deepseek','reference_source':str(args.reference),'reference_sha256':hashlib.sha256(reference.read_bytes()).hexdigest(),'errors':[]}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,args=['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        page=await browser.new_page(locale='zh-CN', viewport={'width':1440,'height':1080},storage_state=str(args.resume/'session.local.json') if args.resume else None);page.on('pageerror',lambda e:report['errors'].append(str(e)))
        async def get(path):
            r=await page.request.get(args.url+path);assert r.ok,await r.text();return await r.json()
        try:
            if args.resume:
                previous_report=json.loads((args.resume/'report.json').read_text());job={'id':previous_report['job_id']}
                await page.goto(args.url)
            else:
                await page.goto(args.url);await page.get_by_role('button',name='创建我的世界',exact=True).click()
                await page.get_by_label('世界构想',exact=True).fill('晨雾海港的开放式调查世界。第一位角色为女性精灵守灯人林笺，绿衣棕发，温和坚定，在地点0码头迎接旅人。另有集市、灯塔和邮局，居民各有目标。')
                await page.get_by_label('第一个故事（可选）').fill('玩家在码头遇到林笺，协助寻找一封寄错的信，调查三个线索后送还信件。')
                await page.locator('.initial-avatar-form summary').click()
                await page.get_by_label('初始NPC参考图',exact=True).set_input_files(reference)
                await page.get_by_label('重要NPC描述（可选）',exact=True).fill('林笺，成年女性精灵守灯人。绿衣棕发，温和坚定，善于倾听和讲述海港故事。保留参考图的风格和五官。')
                async with page.expect_response(lambda r:r.url.endswith('/api/studio/worlds') and r.request.method=='POST',timeout=120000) as response:
                    await page.get_by_role('button',name='生成世界与第一个故事',exact=True).click()
                job=await (await response.value).json();assert job.get('id'),job
            await page.context.storage_state(path=str(folder/'session.local.json'))
            previous=None
            for _ in range(900):
                job=await get('/api/studio/jobs/'+job['id']);avatars=await get('/api/avatars');avatar=avatars[-1]
                current=(job['status'],avatar['state'],avatar['stage'])
                if current!=previous:print('progress',*current,flush=True);previous=current
                report.update(job_id=job['id'],avatar_id=avatar['id'],job_status=job['status'],avatar_status=avatar)
                (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
                assert job['status'] not in {'failed','cancelled','interrupted'},job
                assert avatar['state'] not in {'failed','cancelled','submission_error'},avatar
                if job['status']=='ready' and avatar['state']=='ready':break
                await asyncio.sleep(3)
            assert job['status']=='ready' and avatar['state']=='ready',report
            exported=await get('/api/studio/stories/'+job['story_id']+'/export');assert exported['world']['characters'][0]['avatar_id']==avatar['id']
            report['story_id']=job['story_id'];await page.reload()
            async with page.expect_response(lambda r:r.url.endswith('/api/campaigns') and r.request.method=='POST') as response:
                await page.locator('[data-story-id="'+job['story_id']+'"]').get_by_role('button',name='开始这个故事',exact=True).click()
            campaign=await (await response.value).json();report['campaign']=campaign
            await page.locator('canvas[data-ready="true"]').wait_for(timeout=120000)
            textarea=page.get_by_label('你的行动',exact=True);await textarea.fill('林笺，你好！请你轻轻点头，告诉我你最喜欢海港的什么？')
            await page.get_by_role('button',name='继续故事',exact=True).click()
            await page.locator('.turn[data-version="1"]').wait_for(timeout=180000)
            await page.wait_for_function("Number(document.querySelector('.npc-theater canvas')?.dataset.frames)>10 && Number(document.querySelector('.npc-theater canvas')?.dataset.mouth)>.1",timeout=30000)
            await page.wait_for_timeout(1000)
            report['motion']=await page.locator('.npc-theater canvas').evaluate('(c)=>({...c.dataset})')
            report['committed_view']=await get(f"/api/campaigns/{campaign['id']}/branches/{campaign['branch_id']}/view")
            assert await page.locator('.world-map h3>svg').evaluate('(e)=>e.getBoundingClientRect().width')<=20
            await page.screenshot(path=str(folder/'desktop.png'),full_page=True)
            await page.get_by_role('button',name='收起2D人物',exact=True).click();assert await page.locator('.npc-theater canvas').count()==0
            await page.get_by_role('button',name='展开2D人物',exact=True).click();await page.locator('canvas[data-ready="true"]').wait_for(timeout=30000)
            await page.set_viewport_size({'width':390,'height':844});await page.screenshot(path=str(folder/'mobile.png'),full_page=True)
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            await page.route('**/api/avatars/*/files/puppet/rig.json',lambda route:route.abort())
            await page.get_by_role('button',name='收起2D人物',exact=True).click()
            await page.get_by_role('button',name='展开2D人物',exact=True).click()
            await page.locator('.npc-stage-caption').filter(has_text='形象暂时不可用').wait_for()
            await page.get_by_label('你的行动',exact=True).fill('我点头表示理解，问问眼下可以帮上什么忙。')
            await page.get_by_role('button',name='继续故事',exact=True).click()
            await page.locator('.turn[data-version="2"]').wait_for(timeout=180000)
            report['presentation_failure_keeps_story_working']=True
            other=await browser.new_page(locale='zh-CN');await other.goto(args.url)
            denied=await other.request.get(args.url+f"/api/avatars/{avatar['id']}/files/profile.json")
            assert denied.status in {401,404};report['asset_ownership_checked']=True
            assert not report['errors'],report['errors'];report['status']='passed'
        except Exception as exc:
            report.update(status='failed',failure=str(exc));await page.screenshot(path=str(folder/'failure.png'),full_page=True);raise
        finally:
            (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));await browser.close()
if __name__=='__main__':asyncio.run(main())
