"""Two real browser sessions share a DeepSeek-backed cooperative table."""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
async def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='http://127.0.0.1:18092');p.add_argument('--output',default='outputs/validation/rooms-browser');args=p.parse_args()
    folder=(ROOT/args.output).resolve()
    if not folder.is_relative_to(ROOT/'outputs/validation'):raise ValueError('Invalid output')
    folder.mkdir(parents=True,exist_ok=False);report={'status':'running','mode':'live_deepseek','errors':[]}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,args=['--no-sandbox']);host=await browser.new_page(locale='zh-CN', viewport={'width':1440,'height':1000});guest=await browser.new_page(locale='zh-CN', viewport={'width':1440,'height':1000})
        for page in (host,guest):page.on('pageerror',lambda e:report['errors'].append(str(e)))
        try:
            await host.goto(args.url);await host.get_by_role('button',name='体验内置雾港故事',exact=False).click();await host.locator('.story-toolbar').wait_for()
            await host.get_by_role('button',name='协作冒险',exact=True).click();await host.get_by_label('席位名称',exact=True).fill('小舟')
            async with host.expect_response(lambda r:r.url.endswith('/api/rooms') and r.request.method=='POST') as response:
                await host.get_by_role('button',name='为当前冒险创建房间',exact=True).click()
            room=await (await response.value).json();rid=room['id'];report['room_id']=rid
            await host.get_by_label('房间邀请口令',exact=True).wait_for();code=await host.get_by_label('房间邀请口令',exact=True).input_value()
            await guest.goto(args.url);await guest.get_by_role('button',name='协作冒险',exact=True).click();await guest.get_by_label('席位名称',exact=True).fill('小灯');await guest.get_by_label('邀请口令',exact=True).fill(code);await guest.get_by_role('button',name='加入协作房间',exact=True).click()
            await guest.locator('.room-shell').wait_for();assert await guest.get_by_label('房间行动',exact=True).is_disabled()
            await host.get_by_role('button',name='交给小灯',exact=True).click();await guest.get_by_label('房间行动',exact=True).wait_for();await guest.wait_for_function("!document.querySelector('[aria-label=房间行动]').disabled")
            assert await host.get_by_label('房间行动',exact=True).is_disabled()
            await guest.get_by_label('房间行动',exact=True).fill('我向船长打招呼，请她说说修船最需要什么。');await guest.get_by_role('button',name='提交共同冒险行动',exact=True).click()
            await guest.locator('.turn[data-version="1"]').wait_for(timeout=180000);await host.locator('.turn[data-version="1"]').wait_for(timeout=15000)
            assert await guest.locator('.turn[data-version="1"]').inner_text()==await host.locator('.turn[data-version="1"]').inner_text()
            await guest.get_by_role('button',name='交给小舟',exact=True).click();await host.wait_for_function("!document.querySelector('[aria-label=房间行动]').disabled")
            await guest.reload();await guest.locator('.turn[data-version="1"]').wait_for()
            await host.screenshot(path=str(folder/'host-desktop.png'),full_page=True)
            await guest.set_viewport_size({'width':390,'height':844});await guest.screenshot(path=str(folder/'guest-mobile.png'),full_page=True)
            assert await guest.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            assert (await (await guest.request.get(args.url+'/api/settings/usage')).json())['calls']==0
            report['host_usage']=await (await host.request.get(args.url+'/api/settings/usage')).json();assert report['host_usage']['calls']>0
            await host.get_by_role('button',name='移除小灯',exact=True).click();await guest.get_by_role('alert').filter(has_text='未加入').wait_for(timeout=15000)
            await host.get_by_role('button',name='关闭房间',exact=True).click();await host.locator('.room-shell').filter(has_text='房间已关闭').wait_for()
            assert not report['errors'];report['status']='passed'
        except Exception as exc:
            report.update(status='failed',failure=str(exc));await host.screenshot(path=str(folder/'failure.png'),full_page=True);raise
        finally:
            (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));await browser.close()
if __name__=='__main__':asyncio.run(main())
