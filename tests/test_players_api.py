import hashlib
import time

from fastapi.testclient import TestClient
from test_players import Gateway

from roleplay_world.app import create_app


class FailOnce(Gateway):
    failed = False

    async def generate(self, *args, **kwargs):
        if not self.failed:
            self.failed = True
            raise RuntimeError('Injected model failure')
        return await super().generate(*args, **kwargs)


def test_room_http_authoritative_actor_private_exports_retry_and_scoped_avatar(tmp_path):
    from roleplay_world.config import AppConfig

    app = create_app(tmp_path/'api', FailOnce(), config=AppConfig(workspace_root=tmp_path))
    with TestClient(app) as client:
        sessions = {}
        def login(who):
            client.cookies.clear()
            if who in sessions:
                sid, csrf = sessions[who]
                client.cookies.set('rpw_session', sid)
            else:
                csrf = client.post('/api/session').json()['csrf_token']
                sessions[who] = (client.cookies.get('rpw_session'), csrf)
            client.headers['X-CSRF-Token'] = csrf

        def post(path, body=None, status=200):
            response = client.post(path, json=body) if body is not None else client.post(path)
            assert response.status_code == status, response.text
            return response.json()

        def poll(aid, expected):
            for _ in range(200):
                response = client.get(f'{base}/actions/{aid}').json()
                if response['status'] == expected:
                    return response
                time.sleep(.01)
            raise AssertionError(response)

        login('host')
        campaign = post('/api/campaigns', {'player_name': '主角'}, 201)
        room = post('/api/rooms', {'campaign_id': campaign['id'], 'branch_id': campaign['branch_id'], 'mode': 'independent_characters'})
        base = '/api/rooms/'+room['id']
        primary = room['state']['player_actor_id']
        host_owner = hashlib.sha256(sessions['host'][0].encode()).hexdigest()
        # A room's presentation route shares only renderable files, not the creator's profile or controls.
        avatar = {'id': 'avatar_test', 'owner': host_owner, 'state': 'ready', 'progress': 100,
                  'description': '只属于创作者的秘密形象提示', 'character_id': 'char_'+'a'*16}
        app.state.store.studio_save('avatars', avatar)
        app.state.store.branches[campaign['branch_id']]['state']['actors']['npc_captain']['avatar_id'] = avatar['id']
        folder = tmp_path/'characters'/avatar['character_id']; folder.mkdir(parents=True)
        (folder/'profile.json').write_text('{"private":"不应返回的原始设定"}')
        login('guest')
        guest = post('/api/rooms/join', {'code': room['invite_code'], 'name': '客人'})
        pc = guest['state']['player_actor_id']
        assert client.get('/api/avatars/avatar_test').status_code == 404
        assert client.get(base+'/avatars/avatar_test').json() == {'id': 'avatar_test', 'state': 'ready', 'progress': 100}
        assert client.get(base+'/avatars/avatar_test/files/profile.json').json() == {'character_id': avatar['character_id']}
        assert client.get(base+'/avatars/avatar_test/files/persona.json').status_code == 404
        assert client.get('/api/campaigns/'+campaign['id']+'/backup').status_code == 404
        assert client.get('/api/studio').json()['worlds'] == []
        assert client.get('/api/avatars').json() == []
        login('host')
        current = post(base+'/control', {'expected_revision': guest['revision'], 'operation': 'pass', 'member_id': guest['me']})
        login('guest')
        request = {'expected_revision': current['revision'], 'command': {'action_id': 'guest_failure', 'expected_world_version': 1, 'mode': 'say', 'text': '问候船长'}}
        post(base+'/actions', {**request, 'command': {**request['command'], 'actor_id': primary}}, 403)
        post(base+'/actions', request, 202)
        failed = poll('guest_failure', 'failed'); assert failed['can_retry']
        assert client.get(base).json()['recoverable'][0]['id'] == 'guest_failure'
        login('host')
        post('/api/actions/guest_failure/retry', status=403)
        current = post(base+'/control', {'expected_revision': current['revision'], 'operation': 'reclaim'})
        post(base+'/actions/guest_failure/retry', status=403)
        host_base = f"/api/campaigns/{campaign['id']}/branches/{campaign['branch_id']}/actions"
        post(host_base, {**request['command'], 'action_id': 'spoof', 'actor_id': pc}, 403)
        current = post(base+'/control', {'expected_revision': current['revision'], 'operation': 'pass', 'member_id': guest['me']})
        login('guest')
        post(base+'/actions/guest_failure/retry')
        assert poll('guest_failure', 'committed')['result']['actor_id'] == pc
        note = {'expected_revision': current['revision'], 'command': {'action_id': 'personal_note', 'expected_world_version': 2,
                'mode': 'ooc', 'text': '私人记录', 'note_record': {'id': 'private', 'text': '翠色杯子的约定'}}}
        post(base+'/actions', note, 202); poll('personal_note', 'committed')
        assert '翠色杯子' in client.get(base+'/export').text
        assert client.get(base+'/memories', params={'q': '翠色杯子'}).json()['records']
        assert post(base+'/actions', note, 202)['status'] == 'committed'
        login('host')
        assert client.get(base+'/actions/personal_note').json()['result'] is None
        assert '翠色杯子' not in client.get(base+'/export').text
        assert not client.get(base+'/memories', params={'q': '翠色杯子'}).json()['records']
        login('third')
        third = post('/api/rooms/join', {'code': room['invite_code'], 'name': '后来者'})
        assert client.get(base+'/actions/guest_failure').json()['result'] is None
        assert '问候船长' not in str(third['state']['history'])
        login('host')
        post(base+'/control', {'expected_revision': third['revision'], 'operation': 'kick', 'member_id': guest['me']})
        login('guest')
        assert client.get(base+'/avatars/avatar_test').status_code == 404
        assert client.get(base+'/export').status_code == 404


def test_invalid_private_targets_fail_before_model_or_world_change(tmp_path, template):
    import asyncio

    from test_players import Table

    from roleplay_world.contracts import ActionCommand
    from roleplay_world.rooms import RoomAction
    from roleplay_world.runtime import Runtime

    table = Table(tmp_path, template); pc = table.join()['state']['player_actor_id']
    table.turn('guest')
    for index, patch in enumerate([{'whisper_to': pc}, {'whisper_to': 'absent'}, {'whisper_to': table.state['player'], 'mode': 'act'}]):
        command = ActionCommand(action_id='bad_'+str(index), expected_world_version=1, text='非法私语', **{'mode': 'say', **patch})
        action, _ = table.rooms.accept(table.rid, 'guest', RoomAction(expected_revision=table.view('guest')['revision'], command=command))
        asyncio.run(Runtime(table.store, table.gateway).run(action['id']))
        assert action['status'] == 'failed'
        assert table.state['version'] == 1 and not table.gateway.calls
    table.store.close()
