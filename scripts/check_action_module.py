"""Real-provider SDK acceptance for the external exploration action module."""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from roleplay_world.client import NarraLoomClient, PreparedRequest, Session, save_private
from roleplay_world.content import CreateStory, CreateWorld
from roleplay_world.contracts import ActionCommand, ForkRequest, NewCampaign
from roleplay_world.packages import preview_package, read_package

SELECTION = {'id': 'exploration', 'engine': 'example_exploration', 'version': '1', 'options': {}}


async def run(args):
    folder = args.output.resolve()
    if args.resume:
        report = json.loads((folder / 'report.json').read_text())
        assert report['status'] == 'passed'
        session = Session.load(folder / 'session.local.json')
    else:
        folder.mkdir(parents=True, exist_ok=False)
        report = {'status': 'running', 'mode': 'live_models', 'checks': [], 'receipts': {}}
        session = None

    def save():
        save_private(folder / 'report.json', report)

    try:
        async with NarraLoomClient(args.url, session=session) as client:
            client.session.save(folder / 'session.local.json')

            async def submit(label, pending):
                pending.save(folder / f'{label}.json')
                result = await client.submit(pending)
                report['receipts'][label] = {'id': result['id']}
                save()
                return result

            if args.resume:
                assert await client.request('GET', '/api/action-modules') == []
                usage = await client.request('GET', '/api/settings/usage')
                library = await client.library()
                for name, expected in report['receipts'].items():
                    receipt = await client.submit(PreparedRequest.load(folder / f'{name}.json'))
                    assert receipt['id'] == expected['id']
                view = await client.view(report['campaign']['id'], report['campaign']['branch_id'])
                assert view == json.loads((folder / 'view.json').read_text())
                assert await client.library() == library
                assert await client.request('GET', '/api/settings/usage') == usage
                report['checks'].append('restart_and_receipt_recovery_without_plugin_or_models')
            else:
                assert any(row['engine'] == 'example_exploration'
                           for row in await client.request('GET', '/api/action-modules'))
                created = await submit('world', client.prepare_world(CreateWorld(
                    prompt='A small field station with one friendly resident who studies the nearby forest. '
                           'A quiet open-ended conversation in one room, with optional exploration surveys.',
                    story_prompt='A visitor meets the resident and can make terrain or weather surveys and rest.',
                    creation_preset='scene', content_language='en', action_modules=[SELECTION])))
                first = await client.wait_job(created['id'])
                second = await submit('story', client.prepare_story(first['world_id'], CreateStory(
                    prompt='A later quiet visit to the same field station, discussing observations of the weather.',
                    creation_preset='scene', content_language='en')))
                second = await client.wait_job(second['id'])
                library = await client.library()
                stories = {story['id']: story for story in library['stories']}
                for sid in (first['story_id'], second['story_id']):
                    assert stories[sid]['world_content']['action_modules'][0]['engine'] == SELECTION['engine']
                    assert any(c['name'].startswith('Action module model route:') and c['status'] == 'passed'
                               for c in stories[sid]['test_report']['checks'])
                save_private(folder / 'library.json', library)
                report['checks'].append('generated_world_two_stories_and_automatic_module_routes')
                campaign = await submit('campaign', client.prepare_campaign(NewCampaign(
                    story_id=first['story_id'], player_name='Explorer')))
                report['campaign'] = campaign

                for text, surveys, focus in [
                    ('I survey the terrain using the exploration survey action.', 1, 2),
                    ('探索モジュールの休息を使い、集中力を回復します。', 1, 3),
                    ('我使用探索模块的调查行动，记录天气。', 2, 2),
                ]:
                    view = await client.view(campaign['id'], campaign['branch_id'])
                    aid = 'explore_' + uuid.uuid4().hex
                    pending = client.prepare_action(campaign['id'], campaign['branch_id'], ActionCommand(
                        action_id=aid, expected_world_version=view['world_version'], text=text))
                    await submit(aid, pending)
                    result = await client.wait_action(aid)
                    assert (await client.submit(pending))['result'] == result['result']
                    view = await client.view(campaign['id'], campaign['branch_id'])
                    module = view['action_modules'][0]
                    assert module['public']['surveys'] == surveys and module['personal']['focus'] == focus
                    assert 'private' not in module and 'draws' not in json.dumps(module)
                report['checks'].append('english_japanese_chinese_natural_language_module_actions')
                save_private(folder / 'view.json', view)

                fork = await client.fork(campaign['id'], ForkRequest(
                    source_branch_id=campaign['branch_id'], world_version=1, title='After the first survey'))
                fork_view = await client.view(campaign['id'], fork['id'])
                assert fork_view['action_modules'][0]['public']['surveys'] == 1
                backup = await client.backup(campaign['id'])
                save_private(folder / 'backup.json', backup)
                module_events = [e for branch in backup['branches'] if branch['id'] == campaign['branch_id'] for c in branch['commits']
                                 for e in c['events'] if e['type'] == 'module.resolved']
                assert len(module_events) == 3
                restored = await client.restore(backup)
                restored_view = await client.view(restored['id'], restored['branch_id'])
                assert restored_view['action_modules'] == view['action_modules']
                continued = await client.submit(client.prepare_campaign(NewCampaign(
                    story_id=second['story_id'], player_name='Explorer', source_campaign_id=campaign['id'],
                    source_branch_id=campaign['branch_id'], source_world_version=view['world_version'])))
                continued_view = await client.view(continued['id'], continued['branch_id'])
                assert continued_view['action_modules'] == view['action_modules']
                report['checks'].append('idempotency_historical_fork_backup_restore_and_story_continuation')

                package = await client.request('POST', '/api/studio/packages', json={
                    'metadata': {'slug': 'exploration-station', 'release': '1.0.0', 'title': 'Field station',
                                 'summary': 'A small exploration setting.', 'author': 'Local acceptance', 'license': 'CC0-1.0'},
                    'stories': [{'id': sid, 'revision': stories[sid]['revision']}
                                for sid in (first['story_id'], second['story_id'])]})
                raw = await client.request('GET', f'/api/community/{package["id"]}/download', raw=True)
                (folder / 'world.narraloom.zip').write_bytes(raw)
                parsed = read_package(raw)
                assert preview_package(parsed)['action_modules'] == [{k: SELECTION[k] for k in ('id', 'engine', 'version')}]
                async with NarraLoomClient(args.url) as recipient:
                    imported = await recipient.request('POST', '/api/studio/packages/import', content=raw,
                                                       params={'story_keys': parsed['payload']['stories'][0]['key']})
                    imported = await recipient.wait_job(imported['id'])
                    received = await recipient.export_story(imported['story_id'])
                    assert received['world']['action_modules'] == parsed['payload']['world']['action_modules']
                report['checks'].append('native_package_dependency_and_recipient_model_retest')
            report['status'] = 'passed'
    except BaseException as exc:
        report.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        save()
    print(json.dumps({'status': report['status'], 'checks': report['checks']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    asyncio.run(run(parser.parse_args()))
