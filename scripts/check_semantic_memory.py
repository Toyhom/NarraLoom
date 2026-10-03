"""Real embedding recall and model dialogue over a frozen, explicitly seeded history.

The history is a retrieval fixture, not a claim of 100 model-generated turns.
Expected source IDs stay in this checker and are never sent as model instructions.
"""

import argparse
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from roleplay_world.app import create_app
from roleplay_world.config import AppConfig
from roleplay_world.contracts import ActionCommand
from roleplay_world.journal import digest

MEMORIES = [
    ('instrument', '我把那件吹奏的小乐器放进蓝铃塔二层的胡桃木柜，答应节庆后取回。'),
    ('compass', 'Mira promised to deliver the brass compass to the old observatory before sunrise.'),
    ('medicine', '薬師のアキは、熱を下げる薬草を北の温室で育てていると言った。'),
    ('crossing', 'The ferryman refuses silver coins and takes dried apples as payment for crossing the river.'),
]
CASES = [
    ('Where was the wind instrument stored for safekeeping?', 'instrument'),
    ('吹いて演奏する道具はどこに保管されましたか？', 'instrument'),
    ('米拉要在天亮以前把导航用的东西送去哪里？', 'compass'),
    ('夜明け前にミラが届ける方位を示す道具の行き先は？', 'compass'),
    ('Where does the healer grow plants for reducing a fever?', 'medicine'),
    ('退烧用的植物在什么地方种植？', 'medicine'),
    ('摆渡过河时，船夫要收什么食物当船费？', 'crossing'),
    ('渡し船の料金として受け取る食べ物は？', 'crossing'),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models-config', type=Path, required=True)
    parser.add_argument('--secrets-root', type=Path, required=True)
    parser.add_argument('--embedding-url', required=True)
    parser.add_argument('--embedding-model', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    config = json.loads(args.models_config.read_text())
    config.setdefault('providers', {})['acceptance_embedding'] = {
        'backend': 'openai_embedding', 'url': args.embedding_url, 'timeout_s': 60,
        'api_key_env': 'NARRALOOM_EMBEDDING_API_KEY', 'context_chars': 120000}
    config.setdefault('bindings', {})['memory_embedding'] = {
        'provider': 'acceptance_embedding', 'model': args.embedding_model, 'revision': 'acceptance'}
    config['memory_policy'] = {'mode': 'hybrid', 'failure': 'error', 'max_calls': 16, 'max_chunks': 2048}
    workspace = AppConfig(workspace_root=folder / 'host', secrets_root=args.secrets_root.resolve())
    report = {'status': 'running', 'history': 'frozen retrieval fixture', 'cases': [], 'checks': []}

    def save():
        (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    try:
        with TestClient(create_app(config=workspace, model_config=config)) as client:
            client.headers['X-CSRF-Token'] = client.post('/api/session').json()['csrf_token']
            campaign = client.post('/api/campaigns', json={'player_name': 'Memory tester'}).json()
            cid, bid = campaign['id'], campaign['branch_id']
            path = f'/api/campaigns/{cid}/branches/{bid}'
            store = client.app.state.store
            owner = store.campaigns[cid]['owner']
            state = store.branches[bid]['state']
            pc = state['player']

            def record(eid, text, audience):
                return {'event_id': eid, 'type': 'memory.recorded', 'visibility': {'kind': 'actors', 'actor_ids': audience}, 'payload': {
                    'audience': audience, 'text': text, 'category': 'utterance', 'source_event_ids': [eid + '_speech']}}

            # Seed canonical event history through the normal commit/replay path.
            for index in range(101):
                action, _ = store.accept(cid, bid, owner, ActionCommand(
                    action_id=f'history_{index}', expected_world_version=index, text='Frozen retrieval history'))
                events = ([record(key, text, [pc, 'npc_captain']) for key, text in MEMORIES]
                          + [record('private_code', 'SECRET-ORCHID is the hidden password.', ['npc_keeper'])]
                          if index == 0 else [record(f'weather_{index}', f'The dock bell rang {index} times during a weather discussion.', [pc, 'npc_captain'])])
                store.commit(action['id'], events, [], [], [], None)
            baseline = digest(store.branches[bid]['state'])
            journal = (workspace.data_root / 'journal.jsonl').read_bytes()
            report['history_versions'] = 101
            for query, expected in CASES:
                lexical = client.get(path + '/memories', params={'q': query, 'limit': 5}).json()['records']
                response = client.post(path + '/recall', json={'query': query, 'limit': 5})
                response.raise_for_status()
                result = response.json()
                found = [row['source_id'] for row in result['records']]
                assert 'private_code' not in found
                assert all(row['source_event_ids'] for row in result['records'])
                assert all(trace['status'] == 'ok' for trace in result['diagnostics'])
                report['cases'].append({'query': query, 'expected': expected, 'retrieved': found,
                                        'lexical_hit_at_5': expected in {row['source_id'] for row in lexical},
                                        'hybrid_hit_at_5': expected in found, 'diagnostics': result['diagnostics']})
                save()
            assert digest(store.branches[bid]['state']) == baseline
            assert (workspace.data_root / 'journal.jsonl').read_bytes() == journal
            report['checks'].append('source_preserving_read_only_multilingual_recall')
            fork = client.post(f'/api/campaigns/{cid}/branches', json={
                'source_branch_id': bid, 'world_version': 0, 'title': 'Before the agreements'}).json()
            earlier = client.post(f'/api/campaigns/{cid}/branches/{fork["id"]}/recall',
                                  json={'query': CASES[0][0], 'limit': 5}).json()
            assert not {key for key, _ in MEMORIES} & {row['source_id'] for row in earlier['records']}
            report['checks'].append('warm_cache_cannot_leak_later_branch_or_other_actor_sources')

            command = {'action_id': 'recall_dialogue', 'expected_world_version': 101, 'mode': 'say',
                       'text': '船长，咱们以前说过那件吹奏用的小物件，我忘了收在什么地方，能提醒我吗？'}
            response = client.post(path + '/actions', json=command)
            response.raise_for_status()
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                result = client.get('/api/actions/recall_dialogue').json()
                if result['status'] in {'committed', 'failed', 'cancelled'}:
                    break
                time.sleep(.1)
            report['dialogue'] = result
            assert result['status'] == 'committed', result.get('error')
            traces = [json.loads(p.read_text()) for p in workspace.output_root.joinpath('model-traces').glob('recall_dialogue-*.json')]
            actor_traces = [trace for trace in traces if trace['role'] == 'character_actor']
            assert actor_traces and any('instrument' in {row['source_id'] for row in trace['context']['view']['memories']}
                                        for trace in actor_traces)
            assert all('SECRET-ORCHID' not in json.dumps(trace['context'], ensure_ascii=False) for trace in actor_traces)
            report['dialogue_mentions_storage'] = '蓝铃塔' in json.dumps(result, ensure_ascii=False)
            report['checks'].append('real_planner_and_character_receive_retrieved_old_sources')
            final = client.get(path + '/view').json()
            cookie = dict(client.cookies)
            usage = client.get('/api/settings/usage').json()
            save()
        with TestClient(create_app(config=workspace, model_config={})) as client:
            client.cookies.update(cookie)
            client.headers['X-CSRF-Token'] = client.post('/api/session').json()['csrf_token']
            assert client.get(path + '/view').json() == final
            assert client.post(path + '/actions', json=command).json()['result'] == result['result']
            assert client.get('/api/settings/usage').json() == usage
            report['checks'].append('restart_and_committed_request_recovery_without_models_or_vectors')
        report['lexical_hit_at_5'] = sum(row['lexical_hit_at_5'] for row in report['cases'])
        report['hybrid_hit_at_5'] = sum(row['hybrid_hit_at_5'] for row in report['cases'])
        assert report['hybrid_hit_at_5'] == len(CASES), 'Inspect failed retrieval cases in report.json'
        assert report['dialogue_mentions_storage'], 'Inspect the actual dialogue in report.json'
        report['status'] = 'passed'
    except BaseException as exc:
        report.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        save()
    print(json.dumps({key: value for key, value in report.items() if key not in {'cases', 'dialogue'}}, indent=2))


if __name__ == '__main__':
    main()
