import asyncio

import pytest

from roleplay_world.contracts import ActionCommand, DomainError
from roleplay_world.rooms import RoomAction, RoomControl, RoomCreate, RoomJoin, Rooms
from roleplay_world.runtime import Runtime
from roleplay_world.store import Store


class NoModel:
    async def generate(self,*args,**kwargs):raise AssertionError('No model for notes')

def test_invite_turn_race_idempotency_revocation_and_restart(tmp_path,template):
    store=Store(tmp_path);campaign=store.create_campaign('host',template,'共同旅人');rooms=Rooms(store)
    room=rooms.create('host',RoomCreate(campaign_id=campaign['id'],branch_id=campaign['main_branch'],name='主持'))
    rid=room['id'];invite=room['invite_code'];host=room['me']
    guest=rooms.join('guest',RoomJoin(code=invite,name='朋友'));gid=guest['me']
    assert guest['invite_code'] is None and 'owner' not in str(guest['members'])
    assert not any(f.get('audience')=='gm' for f in guest['state']['known_facts'])
    with pytest.raises(DomainError):rooms.get(rid,'stranger')
    command=RoomAction(expected_revision=guest['revision'],command=ActionCommand(action_id='shared_1',expected_world_version=0,
        mode='ooc',text='共同记事',note_record={'id':'shared_note','text':'一起去码头'}))
    with pytest.raises(DomainError,match='尚未轮到'):rooms.accept(rid,'guest',command)
    with pytest.raises(DomainError,match='已有变化'):rooms.control(rid,'host',RoomControl(expected_revision=0,operation='pass',member_id=gid))
    current=rooms.control(rid,'host',RoomControl(expected_revision=guest['revision'],operation='pass',member_id=gid))
    command.expected_revision=current['revision'];action,fresh=rooms.accept(rid,'guest',command);assert fresh
    assert action['owner']=='host' and action['submitter']=='guest'
    with pytest.raises(DomainError,match='本轮结束'):rooms.control(rid,'guest',RoomControl(expected_revision=current['revision'],operation='pass',member_id=host))
    asyncio.run(Runtime(store,NoModel()).run(action['id']))
    assert action['status']=='committed' and rooms.view(rid,'host')['state']['world_version']==1
    current=rooms.control(rid,'guest',RoomControl(expected_revision=current['revision'],operation='pass',member_id=host))
    assert rooms.accept(rid,'guest',command)[1] is False
    rotated=rooms.control(rid,'host',RoomControl(expected_revision=current['revision'],operation='rotate'))
    with pytest.raises(DomainError):rooms.join('third',RoomJoin(code=invite,name='过期邀请'))
    rooms.control(rid,'host',RoomControl(expected_revision=rotated['revision'],operation='kick',member_id=gid))
    with pytest.raises(DomainError):rooms.get(rid,'guest')
    store.close();store=Store(tmp_path);rooms=Rooms(store)
    assert rooms.view(rid,'host')['state']['world_version']==1
    assert len(store.rooms[rid]['members'])==1
    store.close()


def test_host_api_cannot_bypass_turn_but_old_receipt_survives_handoff_and_close(tmp_path):
    import time

    from fastapi.testclient import TestClient

    from roleplay_world.app import create_app
    with TestClient(create_app(tmp_path/'api',NoModel())) as host:
        host.headers['X-CSRF-Token']=host.post('/api/session').json()['csrf_token']
        c=host.post('/api/campaigns',json={'player_name':'共同玩家'}).json()
        room=host.post('/api/rooms',json={'campaign_id':c['id'],'branch_id':c['branch_id']}).json()
        base=f"/api/campaigns/{c['id']}/branches/{c['branch_id']}/actions"
        command={'action_id':'host_note','expected_world_version':0,'mode':'ooc','text':'共同约定',
                 'note_record':{'id':'n','text':'记得归还工具'}}
        response=host.post(base,json=command);assert response.status_code==202
        for _ in range(100):
            if host.get('/api/actions/host_note').json()['status']=='committed':break
            time.sleep(.01)
        sid=host.cookies.get('rpw_session');headers=dict(host.headers)
        host.cookies.clear();host.headers['X-CSRF-Token']=host.post('/api/session').json()['csrf_token']
        guest=host.post('/api/rooms/join',json={'code':room['invite_code'],'name':'朋友'}).json()
        assert host.get(f"/api/campaigns/{c['id']}/backup").status_code==404
        host.cookies.clear();host.cookies.set('rpw_session',sid);host.headers.update(headers)
        handed=host.post('/api/rooms/'+room['id']+'/control',json={'expected_revision':guest['revision'],'operation':'pass','member_id':guest['me']}).json()
        assert host.post(base,json={**command,'action_id':'bypass','expected_world_version':1}).status_code==403
        assert host.post(base,json=command).json()['status']=='committed'
        closed=host.post('/api/rooms/'+room['id']+'/control',json={'expected_revision':handed['revision'],'operation':'close'})
        assert closed.status_code==200
        assert host.post(base,json=command).json()['status']=='committed'
