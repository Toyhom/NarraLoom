"""Real-model SDK acceptance for examples/check_engine.py and its pinned dice pool."""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from roleplay_world.checks import CheckBinding, CheckResult
from roleplay_world.client import NarraLoomClient, PreparedRequest, Session, save_private
from roleplay_world.content import CreateStory, CreateWorld
from roleplay_world.contracts import ActionCommand, ForkRequest, NewCampaign
from roleplay_world.journal import digest
from roleplay_world.packages import read_package
from roleplay_world.quality import route

BINDING = {'engine': 'example_pool', 'version': '1', 'options': {'count': 6, 'hit_at': 5}}


def check_roll(roll):
    CheckResult.model_validate({key: roll[key] for key in CheckResult.model_fields})
    assert roll['engine'] == {'id': 'example_pool', 'version': '1', 'options_sha256': digest(BINDING['options'])}
    assert len(roll['draws']) == 6 and all(1 <= face <= 6 for face in roll['draws'])
    assert roll['roll'] == sum(face >= 5 for face in roll['draws'])


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
                assert not any(engine['id'] == 'example_pool' for engine in await client.request('GET', '/api/check-engines'))
                usage = await client.request('GET', '/api/settings/usage')
                library = await client.library()
                for name, expected in report['receipts'].items():
                    receipt = await client.submit(PreparedRequest.load(folder / f'{name}.json'))
                    assert receipt['id'] == expected['id']
                current = await client.view(report['campaign']['id'], report['campaign']['branch_id'])
                assert current == json.loads((folder / 'view.json').read_text())
                assert await client.library() == library
                assert await client.request('GET', '/api/settings/usage') == usage
                report['checks'].append('restart_and_request_recovery_without_plugin_or_models')
            else:
                engines = await client.request('GET', '/api/check-engines')
                assert any(engine['id'] == 'example_pool' and engine['version'] == '1' for engine in engines)
                created = await submit('world', client.prepare_world(CreateWorld(
                    prompt='A small coastal workshop and safe training yard. Include two friendly inhabitants and '
                           'a harmless training dummy enemy with 100 HP and defense 5. All numerical checks use '
                           'six d6 dice counting faces of 5 or 6 as successes, plus skill modifiers. '
                           'Use craft challenge difficulty 3, attack bonus 2, defense 5 and damage 3. No deadline.',
                    story_prompt='Investigate the workshop, attempt a craft challenge with difficulty 3, then '
                                 'choose a nonrandom ending. The training dummy can be used for optional practice.',
                    rules_mode='d20', creation_preset='story', content_language='en',
                    check_engine=CheckBinding.model_validate(BINDING))))
                first = await client.wait_job(created['id'])
                second = await submit('story', client.prepare_story(first['world_id'], CreateStory(
                    prompt='A quiet visit to the same workshop to discuss the craftsperson’s favorite tools.',
                    creation_preset='scene', content_language='en')))
                second = await client.wait_job(second['id'])
                library = await client.library()
                stories = {story['id']: story for story in library['stories']}
                for sid in (first['story_id'], second['story_id']):
                    assert stories[sid]['world_content']['check_engine'] == BINDING
                    assert stories[sid]['test_report']['status'] == 'passed'
                save_private(folder / 'library.json', library)
                report['checks'].append('generated_world_two_stories_pinned_checks_and_automatic_playtests')

                campaign = await submit('campaign', client.prepare_campaign(NewCampaign(
                    story_id=first['story_id'], player_name='Check engine tester')))
                report['campaign'] = campaign
                template = (await client.backup(campaign['id']))['campaign']['template']
                assert template['mechanics']['checks'] == BINDING

                async def turn(text, operation=None):
                    view = await client.view(campaign['id'], campaign['branch_id'])
                    aid = 'checks_' + uuid.uuid4().hex
                    pending = client.prepare_action(campaign['id'], campaign['branch_id'], ActionCommand(
                        action_id=aid, expected_world_version=view['world_version'], text=text,
                        selected_operation=operation))
                    await submit(aid, pending)
                    result = await client.wait_action(aid)
                    assert (await client.submit(pending))['result'] == result['result']
                    return result['result']

                async def travel(target):
                    view = await client.view(campaign['id'], campaign['branch_id'])
                    for destination in route(template, view['location']['id'], target):
                        await turn('Walk to the next place.', {'kind': 'move', 'target_id': destination})

                enemy = template['mechanics']['rules']['enemies'][0]
                await travel(f'loc_{enemy["location"]}')
                attack = await turn('I practice against the training dummy.', {'kind': 'attack', 'target_id': 'enemy_' + enemy['id']})
                check_roll(attack['roll'])
                check_roll(attack['roll']['counterattack'])
                report['combat_roll'] = attack['roll']
                goal = next(goal for goal in template['mechanics']['challenges'] if goal['skill'] != 'none')
                facts = {fact['id']: fact for fact in template['facts']}
                for fid in goal['required_facts']:
                    await travel(facts[fid]['discoverable_at'][0])
                    await turn('Investigate the available clue.', {'kind': 'reveal', 'target_id': fid})
                await travel(goal['location_id'])
                ability = await turn('I attempt the task: ' + goal['name'] + '. ' + goal['description'])
                check_roll(ability['roll'])
                report['ability_roll'] = ability['roll']
                report['checks'].append('real_planner_narrator_skill_attack_and_counterattack')

                view = await client.view(campaign['id'], campaign['branch_id'])
                save_private(folder / 'view.json', view)
                branch = await client.fork(campaign['id'], ForkRequest(
                    source_branch_id=campaign['branch_id'], world_version=0, title='Before checks'))
                assert (await client.view(campaign['id'], branch['id']))['world_version'] == 0
                backup = await client.backup(campaign['id'])
                save_private(folder / 'backup.json', backup)
                restored = await client.restore(backup)
                restored_view = await client.view(restored['id'], restored['branch_id'])
                ignored = {'campaign_id', 'branch_id'}
                assert {k: v for k, v in view.items() if k not in ignored} == {
                    k: v for k, v in restored_view.items() if k not in ignored}
                report['checks'].append('idempotency_branches_backup_and_restore')

                package = await client.request('POST', '/api/studio/packages', json={
                    'metadata': {'slug': 'workshop-checks', 'release': '1.0.0', 'title': 'Workshop checks',
                                 'summary': 'A generated dice-pool workshop.', 'author': 'Local acceptance', 'license': 'CC0-1.0'},
                    'stories': [{'id': sid, 'revision': stories[sid]['revision']} for sid in (first['story_id'], second['story_id'])]})
                raw = await client.request('GET', f'/api/community/{package["id"]}/download', raw=True)
                (folder / 'world.narraloom.zip').write_bytes(raw)
                parsed = read_package(raw)
                assert parsed['payload']['world']['check_engine'] == BINDING
                async with NarraLoomClient(args.url) as recipient:
                    imported = await recipient.request('POST', '/api/studio/packages/import', content=raw,
                                                       params={'story_keys': parsed['payload']['stories'][0]['key']})
                    imported = await recipient.wait_job(imported['id'])
                    received = await recipient.export_story(imported['story_id'])
                    assert received['world']['check_engine'] == BINDING
                report['checks'].append('native_export_import_and_recipient_model_retest')
            report['status'] = 'passed'
    except BaseException as exc:
        report.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        save()
    print(json.dumps({'status': report['status'], 'checks': report['checks']}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    main()
