"""Live provider configuration, diagnostics and independent-browser campaign recovery."""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
async def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='http://127.0.0.1:18092');p.add_argument('--output',default='outputs/validation/portability-browser');args=p.parse_args()
    folder=(ROOT/args.output).resolve()
    if not folder.is_relative_to(ROOT/'outputs/validation'):raise ValueError('Invalid output')
    folder.mkdir(parents=True,exist_ok=False);report={'status':'running','mode':'live_configured_provider','errors':[]}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,args=['--no-sandbox']);page=await browser.new_page(locale='zh-CN', viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:report['errors'].append(str(e)))
        try:
            await page.goto(args.url);await page.get_by_role('button',name='模型与用量',exact=True).click()
            from roleplay_world.gateway import ModelGateway
            config=json.loads((ROOT/'configs/models.local.json').read_text())
            gateway=ModelGateway(config,folder/'diagnostic-traces');default=gateway.role_config('game_master')
            await page.get_by_label('模型服务地址').fill(default['url']);await page.get_by_label('默认模型',exact=True).fill(default['model'])
            await page.get_by_label('API密钥',exact=True).fill(gateway.auth_headers(default).get('Authorization','').removeprefix('Bearer '))
            await page.get_by_role('button',name='保存模型设置',exact=True).click();await page.get_by_role('status').filter(has_text='已保存').wait_for()
            assert await page.get_by_label('API密钥',exact=True).input_value()==''
            async with page.expect_response(lambda r:r.url.endswith('/api/settings/provider/check'),timeout=120000) as response:
                await page.get_by_role('button',name='测试已保存连接',exact=True).click()
            diagnostic=await (await response.value).json();assert diagnostic['generation_passed'];report['diagnostic']=diagnostic
            await page.locator('summary',has_text='调用用量与费用估算').click();await page.screenshot(path=str(folder/'provider-desktop.png'),full_page=True)
            await page.get_by_role('button',name='关闭模型设置').click()
            async with page.expect_response(lambda r:r.url.endswith('/api/campaigns') and r.request.method=='POST') as response:
                await page.get_by_role('button',name='体验内置雾港故事',exact=False).click()
            campaign=await (await response.value).json();report['original']=campaign
            await page.locator('.note-editor summary').click();await page.get_by_label('手记内容').fill('备份之后仍记得：青瓷风铃留在码头。');await page.get_by_role('button',name='保存手记',exact=True).click()
            await page.locator('.turn[data-version="1"]').wait_for(timeout=30000)
            async with page.expect_download() as download:
                await page.get_by_role('link',name='完整备份',exact=True).click()
            path=folder/'campaign.rpw.json';await (await download.value).save_as(path)
            backup=json.loads(path.read_text());assert backup['branches'][0]['commits'][0]['version']==1
            other=await browser.new_page(locale='zh-CN', viewport={'width':1440,'height':1000});other.on('pageerror',lambda e:report['errors'].append(str(e)));await other.goto(args.url)
            await other.locator('summary',has_text='恢复冒险备份').click();await other.get_by_label('选择冒险备份',exact=True).set_input_files(path)
            await other.get_by_role('button',name='恢复为独立冒险',exact=True).wait_for()
            assert '第1幕' in await other.locator('.backup-preview').inner_text()
            async with other.expect_response(lambda r:r.url.endswith('/api/backups/restore')) as response:
                await other.get_by_role('button',name='恢复为独立冒险',exact=True).click()
            restored=await (await response.value).json();report['restored']=restored;assert restored['id']!=campaign['id']
            await other.locator('.turn[data-version="1"]').wait_for(timeout=30000)
            assert '青瓷风铃' in await other.locator('body').inner_text()
            await other.locator('.composer textarea').fill('船长你好，今天海港的天气怎么样？');await other.get_by_role('button',name='继续故事',exact=True).click()
            await other.locator('.turn[data-version="2"]').wait_for(timeout=180000)
            await other.reload();await other.locator('.turn[data-version="2"]').wait_for()
            await other.screenshot(path=str(folder/'restored-desktop.png'),full_page=True)
            await other.set_viewport_size({'width':390,'height':844});await other.screenshot(path=str(folder/'restored-mobile.png'),full_page=True)
            assert await other.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            original=await (await page.request.get(args.url+f"/api/campaigns/{campaign['id']}/branches/{campaign['branch_id']}/view")).json();assert original['world_version']==1
            report['usage']=await (await other.request.get(args.url+'/api/settings/usage')).json();assert report['usage']['calls']>0
            assert (await (await other.request.get(args.url+'/api/settings/provider')).json())['using_default']
            assert not report['errors'];report['status']='passed'
        except Exception as exc:
            report.update(status='failed',failure=str(exc));await page.screenshot(path=str(folder/'failure.png'),full_page=True);raise
        finally:
            (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));await browser.close()
if __name__=='__main__':asyncio.run(main())
