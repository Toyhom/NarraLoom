"""Real browser + generation + System One checks for independent module providers."""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

from roleplay_world.gateway import ModelGateway

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18091')
    parser.add_argument('--decision-url', required=True)
    parser.add_argument('--decision-model', default='jev-style-0.8b-decision-v3')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    folder = (ROOT/args.output).resolve()
    if not folder.is_relative_to(ROOT/'outputs/validation'):
        raise ValueError('Reports must stay in project validation outputs')
    folder.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'errors': [], 'mode': 'real_generation_and_decision'}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page(locale='zh-CN', viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda e: report['errors'].append(str(e)))
        try:
            await page.goto(args.url)
            await page.get_by_role('button', name='模型与用量', exact=True).click()
            gw = ModelGateway(json.loads((ROOT/'configs/models.local.json').read_text()), folder/'traces')
            cfg = gw.role_config('game_master')
            key = gw.auth_headers(cfg).get('Authorization', '').removeprefix('Bearer ')
            await page.get_by_label('模型服务地址').fill(cfg['url'])
            await page.get_by_label('默认模型', exact=True).fill(cfg['model'])
            await page.get_by_label('API密钥', exact=True).fill(key)
            await page.locator('.engine-bindings > summary').click()
            await page.get_by_role('dialog').get_by_label('界面语言 / Interface language').select_option('en')
            await page.get_by_role('button', name='Add provider', exact=True).click()
            await page.get_by_label('provider_1 URL').fill(cfg['url'])
            await page.get_by_label('provider_1 API key').fill(key)
            await page.get_by_label('narrator provider').select_option('provider_1')
            await page.get_by_label('narrator model', exact=True).fill(cfg['model'])
            await page.get_by_role('button', name='Add provider', exact=True).click()
            await page.get_by_label('provider_2 backend').select_option('systemone')
            await page.get_by_label('provider_2 URL').fill(args.decision_url)
            await page.get_by_label('action_router provider').select_option('provider_2')
            await page.get_by_label('action_router model', exact=True).fill(args.decision_model)
            await page.get_by_label('Decision routing mode').select_option('shadow')
            await page.get_by_role('button', name='Save model settings', exact=True).click()
            await page.get_by_role('status').filter(has_text='Saved').wait_for()
            assert await page.get_by_label('provider_1 API key').input_value() == ''
            config = await (await page.request.get(args.url+'/api/settings/provider')).json()
            assert key not in json.dumps(config) and config['providers']['provider_1']['has_key']
            assert not config['providers']['provider_2']['has_key']
            for role in ('narrator', 'action_router'):
                section = page.locator('fieldset').filter(has=page.get_by_label(role+' model', exact=True))
                async with page.expect_response(lambda r, module=role: r.url.endswith('/api/engines/'+module+'/check'), timeout=120000) as response:
                    await section.get_by_role('button', name='Test saved module', exact=True).click()
                result = await (await response.value).json()
                assert result.get('protocol_passed'), result
                report[role+'_diagnostic'] = result
            await page.screenshot(path=str(folder/'providers-desktop.png'), full_page=True)
            await page.set_viewport_size({'width': 390, 'height': 844})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            await page.screenshot(path=str(folder/'providers-mobile.png'), full_page=True)
            await page.set_viewport_size({'width': 1440, 'height': 1000})
            await page.get_by_role('button', name='Close model settings', exact=True).click()
            async with page.expect_response(lambda r: r.url.endswith('/api/campaigns') and r.request.method == 'POST') as response:
                await page.get_by_role('button', name='Try the built-in', exact=False).click()
            campaign = await (await response.value).json(); report['campaign'] = campaign
            base = f"/api/campaigns/{campaign['id']}/branches/{campaign['branch_id']}"
            view = await (await page.request.get(args.url+base+'/view')).json()
            await page.locator('.composer textarea').fill('我前往'+view['exits'][0]['name']+'。')
            async with page.expect_response(lambda r: r.url.endswith(base+'/actions') and r.request.method == 'POST') as response:
                await page.get_by_role('button', name='Continue story', exact=True).click()
            action = await (await response.value).json()
            await page.locator('.turn[data-version="1"]').wait_for(timeout=180000)
            diagnostic = await (await page.request.get(args.url+'/api/actions/'+action['id']+'/diagnostics')).json()
            assert diagnostic['status'] == 'committed', diagnostic
            assert any(t['role'] == 'action_router' and t.get('routing', {}).get('mode') == 'shadow' for t in diagnostic['traces'])
            assert any(t['role'] == 'game_master' for t in diagnostic['traces'])
            assert any(t['role'] == 'narrator' and t['provider'] == 'provider_1' for t in diagnostic['traces'])
            report['shadow_action'] = diagnostic
            # Deliberately unavailable decision service: the same user can continue with the main planner.
            csrf = (await (await page.request.post(args.url+'/api/session')).json())['csrf_token']
            payload = {k:v for k,v in config.items() if k not in {'has_key','using_default'}}
            payload['providers'] = {name: {k:v for k,v in p.items() if k != 'has_key'} for name,p in payload['providers'].items()}
            payload['providers']['provider_2'].update(url='http://127.0.0.1:9/v1', timeout_s=1)
            payload['decision_policy']['mode'] = 'auto'
            result = await page.request.put(args.url+'/api/settings/provider', data=payload, headers={'X-CSRF-Token': csrf})
            assert result.status == 200
            view = await (await page.request.get(args.url+base+'/view')).json()
            await page.locator('.composer textarea').fill('我前往'+view['exits'][0]['name']+'。')
            async with page.expect_response(lambda r: r.url.endswith(base+'/actions') and r.request.method == 'POST') as response:
                await page.get_by_role('button', name='Continue story', exact=True).click()
            action = await (await response.value).json()
            await page.locator('.turn[data-version="2"]').wait_for(timeout=180000)
            diagnostic = await (await page.request.get(args.url+'/api/actions/'+action['id']+'/diagnostics')).json()
            assert any(t.get('routing', {}).get('reason') == 'decision_unavailable' for t in diagnostic['traces'])
            assert any(t['role'] == 'game_master' for t in diagnostic['traces'])
            report['fallback_action'] = diagnostic
            other = await browser.new_page(locale='zh-CN'); await other.goto(args.url)
            assert (await other.request.get(args.url+'/api/actions/'+action['id']+'/diagnostics')).status == 404
            other_config = await (await other.request.get(args.url+'/api/settings/provider')).json()
            assert other_config['using_default']
            await page.reload(); await page.locator('.turn[data-version="2"]').wait_for()
            await page.get_by_role('button', name='Models and usage', exact=True).click()
            await page.locator('.engine-bindings > summary').click()
            assert await page.get_by_role('dialog').get_by_label('界面语言 / Interface language').input_value() == 'en'
            assert await page.get_by_label('provider_1 API key').input_value() == ''
            assert await page.get_by_label('provider_2 URL').input_value() == 'http://127.0.0.1:9/v1'
            report['usage'] = await (await page.request.get(args.url+'/api/settings/usage')).json()
            assert not report['errors']; report['status'] = 'passed'
        except Exception as exc:
            report.update(status='failed', failure=str(exc)); await page.screenshot(path=str(folder/'failure.png'), full_page=True)
            raise
        finally:
            (folder/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)); await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
