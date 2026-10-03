import asyncio
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from roleplay_world.app import create_app
from roleplay_world.backups import export_campaign, preview_backup, restore_campaign
from roleplay_world.contracts import ActionCommand, DomainError
from roleplay_world.journal import digest
from roleplay_world.runtime import Runtime
from roleplay_world.store import Store


class NoModel:
    async def generate(self, *args, **kwargs):
        raise AssertionError('No model call for notes')

def note(store, cid, bid, aid, text):
    state = store.branches[bid]['state']
    a, _ = store.accept(cid, bid, store.campaigns[cid]['owner'], ActionCommand(
        action_id=aid, expected_world_version=state['version'], mode='ooc', text=text,
        note_record={'id':aid, 'kind':'commitment', 'text':text}))
    asyncio.run(Runtime(store, NoModel()).run(a['id']))
    assert a['status']=='committed'

def test_complete_branch_backup_replay_restore_reopen_continue(tmp_path,template):
    source=Store(tmp_path/'source');c=source.create_campaign('old',template,'旅行者');bid=c['main_branch']
    note(source,c['id'],bid,'first','记得把风铃送还船长')
    fork=source.fork(c['id'],bid,'old',1,'另一条路')
    note(source,c['id'],fork['id'],'second','先调查灯塔')
    note(source,c['id'],bid,'third','在码头等待')
    backup=export_campaign(source,c['id'],'old');raw=json.dumps(backup)
    target=Store(tmp_path/'target');preview=preview_backup(target,'new',raw)
    assert len(preview['branches'])==2
    restored=restore_campaign(target,'new',raw);assert not restored['existing']
    assert restore_campaign(target,'new',raw)['existing']
    assert len(target.campaigns)==1 and len(target.journal.records)==1
    before={b['title']:digest(b['state']) for b in source.branches.values()}
    assert {b['title']:digest(b['state']) for b in target.branches.values()}==before
    with pytest.raises(DomainError):target.campaign(restored['id'],'old')
    source.close();target.close();target=Store(tmp_path/'target')
    note(target,restored['id'],restored['branch_id'],'after_restore','继续旧冒险')
    assert target.branches[restored['branch_id']]['state']['version']==3
    assert len(target.branches)==2
    target.close()

@pytest.mark.parametrize('corruption',['checksum','hash','parent','inherited','sequence'])
def test_corrupt_backup_has_no_partial_publication(tmp_path,template,corruption):
    store=Store(tmp_path);c=store.create_campaign('owner',template,'玩家');bid=c['main_branch']
    note(store,c['id'],bid,'n1','前往港口');store.fork(c['id'],bid,'owner',1,'分支')
    value=deepcopy(export_campaign(store,c['id'],'owner'))
    if corruption=='checksum':value['campaign']['player_name']='篡改'
    elif corruption=='hash':value['branches'][0]['commits'][0]['state_hash']='bad'
    elif corruption=='parent':value['branches'][1]['parent_id']='absent'
    elif corruption=='inherited':value['branches'][1]['commits']=[]
    elif corruption=='sequence':value['branches'][0]['commits'][0]['version']=5
    if corruption!='checksum':value.pop('sha256');value['sha256']=digest(value)
    count=len(store.journal.records)
    with pytest.raises(DomainError):restore_campaign(store,'new',json.dumps(value))
    assert len(store.journal.records)==count and len(store.campaigns)==1
    store.close()

def test_http_backup_owner_cap_and_preview(tmp_path):
    with TestClient(create_app(tmp_path/'api')) as client:
        client.headers['X-CSRF-Token']=client.post('/api/session').json()['csrf_token']
        c=client.post('/api/campaigns',json={'template_id':client.get('/api/worlds').json()[0]['id'],'player_name':'旅人'}).json()
        response=client.get('/api/campaigns/'+c['id']+'/backup');assert response.status_code==200
        raw=response.content
        client.cookies.clear();client.headers['X-CSRF-Token']=client.post('/api/session').json()['csrf_token']
        assert client.get('/api/campaigns/'+c['id']+'/backup').status_code==404
        assert client.post('/api/backups/preview',content=raw).status_code==200
        assert client.post('/api/backups/restore',content=raw).status_code==200
        assert client.post('/api/backups/restore',content=raw).json()['existing']
        assert client.post('/api/backups/restore',content=b'{}',headers={'Content-Length':'6000001'}).status_code==413
