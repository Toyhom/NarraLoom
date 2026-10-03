"""Create, search, archive and restore a world without changing its pinned story."""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
async def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='http://127.0.0.1:18092');p.add_argument('--output',default='outputs/validation/library-browser');args=p.parse_args()
    folder=(ROOT/args.output).resolve()
    if not folder.is_relative_to(ROOT/'outputs/validation'):raise ValueError('Invalid output')
    folder.mkdir(parents=True,exist_ok=False);report={'status':'running','mode':'live_models','errors':[]}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,args=['--no-sandbox']);page=await browser.new_page(locale='zh-CN', viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:report['errors'].append(str(e)))
        try:
            await page.goto(args.url);await page.get_by_role('button',name='创建我的世界',exact=True).click()
            await page.get_by_label('世界构想',exact=True).fill('风铃渡口的小城，居民共同修理一座钟楼。温暖的日常调查故事。')
            async with page.expect_response(lambda r:r.url.endswith('/api/studio/worlds') and r.request.method=='POST') as response:
                await page.get_by_role('button',name='生成世界与第一个故事',exact=True).click()
            job=await (await response.value).json()
            for _ in range(300):
                job=await (await page.request.get(args.url+'/api/studio/jobs/'+job['id'])).json()
                if job['status'] in {'ready','failed','cancelled','interrupted'}:break
                await asyncio.sleep(2)
            assert job['status']=='ready',job;report['job_id']=job['id']
            path='/api/studio/stories/'+job['story_id']+'/export';original=await (await page.request.get(args.url+path)).json()
            await page.reload();await page.get_by_role('button',name='归档世界',exact=True).click()
            await page.wait_for_function("document.querySelectorAll('.studio-world-card').length===0")
            await page.get_by_label('查看归档世界',exact=True).check();await page.get_by_role('button',name='恢复到世界库',exact=True).wait_for()
            await page.get_by_label('搜索世界',exact=True).fill('不存在的随机世界匹配词');assert await page.locator('.studio-world-card').count()==0
            await page.get_by_label('搜索世界',exact=True).fill(original['world']['title']);await page.get_by_role('button',name='恢复到世界库',exact=True).click()
            await page.get_by_label('查看归档世界',exact=True).uncheck();await page.locator('.studio-world-card').wait_for()
            assert await (await page.request.get(args.url+path)).json()==original
            await page.screenshot(path=str(folder/'library.png'),full_page=True)
            await page.set_viewport_size({'width':390,'height':844});assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            await page.screenshot(path=str(folder/'library-mobile.png'),full_page=True)
            assert not report['errors'];report['status']='passed'
        except Exception as exc:
            report.update(status='failed',failure=str(exc));await page.screenshot(path=str(folder/'failure.png'),full_page=True);raise
        finally:
            (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));await browser.close()
if __name__=='__main__':asyncio.run(main())
