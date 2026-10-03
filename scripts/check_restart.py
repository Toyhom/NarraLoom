"""Restart only this project's managed web service; verify worlds, stories and saves."""

import argparse
import hashlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from snapshot_store import snapshot

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18090')
    parser.add_argument('--output', default='outputs/validation/restart-studio')
    parser.add_argument('--starter', help='Install this community pack instead of generating a world')
    parser.add_argument('--preset', choices=['scene','story','adventure'], help='Creation preset for the generated restart case')
    parser.add_argument('--language', help='Content language for the generated restart case')
    parser.add_argument('--state-scenario', action='store_true', help='Play its first declared state route before restarting')
    args = parser.parse_args()
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT / 'outputs/validation'):
        raise ValueError('Output must be inside outputs/validation')
    folder.mkdir(parents=True, exist_ok=True)
    record = json.loads((ROOT / 'outputs/services/web.json').read_text())
    if args.url.rstrip('/') != f"http://127.0.0.1:{record['port']}":
        raise ValueError('Restart checks require the managed localhost service URL')
    with httpx.Client(base_url=args.url, trust_env=False, timeout=15) as client:
        def call(path, payload=None, method='POST'):
            response = client.request(method, path, json=payload)
            response.raise_for_status()
            return response.json()

        client.headers['X-CSRF-Token'] = call('/api/session')['csrf_token']
        if args.starter:
            job = call('/api/studio/catalog/' + args.starter + '/install')
        else:
            job = call('/api/studio/worlds', {
                'prompt': '温暖的山间邮局世界，有邮差、修桥工和茶馆主人，居民通过信件互相帮助。',
                'story_prompt': '我扮演新来的邮差，与在场的人交谈。' if args.preset == 'scene' else '我扮演新来的邮差，调查一封迟到的信，找到收件人并送达好消息。',
                **({'creation_preset': args.preset} if args.preset else {}),
                **({'content_language': args.language} if args.language else {})})
        deadline = time.monotonic() + 1200
        previous = None
        while time.monotonic() < deadline:
            job = call('/api/studio/jobs/' + job['id'], method='GET')
            if job['status'] != previous:
                print('CREATION', job['status'], flush=True)
                previous = job['status']
            if job['status'] in {'ready', 'failed', 'interrupted', 'cancelled', 'recovery_required'}:
                break
            time.sleep(1)
        (folder / 'creation.json').write_text(json.dumps(job, ensure_ascii=False, indent=2))
        assert job['status'] == 'ready', job
        saved = []
        for story_id in [None, job['story_id']]:
            payload = {'player_name': '恢复验收旅人'}
            if story_id:
                payload['story_id'] = story_id
            campaign = call('/api/campaigns', payload)
            base = f"/api/campaigns/{campaign['id']}/branches/{campaign['branch_id']}"
            aid = 'restart_' + uuid.uuid4().hex[:24]
            command = {'action_id': aid, 'expected_world_version': 0, 'mode': 'say',
                       'text': '我向在场的人打招呼，问这里最近发生了什么。'}
            call(base + '/actions', command)
            deadline = time.monotonic() + 185
            while time.monotonic() < deadline:
                action = call('/api/actions/' + aid, method='GET')
                if action['status'] in {'committed', 'failed', 'interrupted', 'recovery_required'}:
                    break
                time.sleep(.5)
            assert action['status'] == 'committed', action
            if story_id and args.state_scenario:
                from roleplay_world.content import StoryBlueprint, WorldBlueprint, compile_story
                from roleplay_world.state_rules import test_command
                from roleplay_world.world import initial_state

                exported = call('/api/studio/stories/' + story_id + '/export', method='GET')
                template = compile_story(WorldBlueprint.model_validate(exported['world']),
                                         StoryBlueprint.model_validate(exported['story']), story_id)
                labels = initial_state(template, '恢复验收旅人')
                scenario = template['mechanics']['state_rules']['tests'][0]
                for step in scenario['steps']:
                    command = test_command(step, labels, 'restart_state_'+uuid.uuid4().hex[:20]).model_dump()
                    command['expected_world_version'] = call(base+'/view', method='GET')['world_version']
                    action = call(base+'/actions', command)
                    deadline = time.monotonic()+185
                    while time.monotonic() < deadline:
                        action = call('/api/actions/'+action['id'], method='GET')
                        if action['status'] in {'committed', 'failed', 'interrupted', 'recovery_required'}:
                            break
                        time.sleep(.5)
                    assert action['status'] == 'committed', action
                visible = call(base+'/view', method='GET')['custom_state']['variables']
                assert any(v['value'] != labels['state_rules']['values'][v['id']] for v in visible), 'Expected persisted noninitial state'
            saved.append((base, command, action, call(base + '/view', method='GET')))
        library = call('/api/studio', method='GET')
        # Inspect raw terminal statuses; normal Store construction marks active jobs
        # interrupted and therefore cannot establish that a live service is idle.
        before_store = snapshot(ROOT / 'data')
        # Preserve all prior journal bytes, including sessions outside this test.
        original_bytes = (ROOT / 'data/journal.jsonl').read_bytes()
        original_digest = hashlib.sha256(original_bytes).hexdigest()
        for verb in ['stop', 'start']:
            subprocess.run([sys.executable, 'scripts/manage.py', verb, '--port', str(record['port'])],
                           cwd=ROOT, check=True)
        assert snapshot(ROOT / 'data') == before_store
        assert call('/api/studio', method='GET') == library
        if args.starter:
            assert call('/api/studio/catalog/' + args.starter + '/install')['id'] == job['id']
            assert call('/api/studio', method='GET') == library
            exported = call('/api/studio/stories/' + job['story_id'] + '/export', method='GET')
            assert exported['origin']['id'] == args.starter
            assert 'Permission is hereby granted' in exported['origin']['source']['license_text']
        for base, command, action, before in saved:
            assert call(base + '/view', method='GET') == before
            assert call(base + '/actions', command)['result'] == action['result']
        with (ROOT / 'data/journal.jsonl').open('rb') as source:
            assert hashlib.sha256(source.read(len(original_bytes))).hexdigest() == original_digest
        report = {'status': 'passed', 'mode': 'live_models', 'same_browser_session': True,
                  'state_scenario_before_restart': args.state_scenario,
                  'world_story_and_test_report_identical': True,
                  'builtin_and_' + ('imported' if args.starter else 'generated') + '_saves_identical': True,
                  'duplicate_returns_original_commit': True, 'prior_journal_bytes_preserved': True,
                  'all_store_snapshots_identical': True,
                  'campaigns_preserved': len(before_store['campaigns']), 'branches_preserved': len(before_store['branches'])}
        if args.starter:
            report.update(starter=args.starter, source_retained=True, repeat_install='same_copy')
        (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
