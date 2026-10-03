import asyncio
import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from roleplay_world.app import create_app
from roleplay_world.avatars import AvatarCreate, AvatarService, vendor_module
from roleplay_world.contracts import DomainError
from roleplay_world.store import Store


def request(**changes):
    out=io.BytesIO();Image.new('RGB',(128,128),'green').save(out,format='PNG')
    return AvatarCreate(request_id='request_test',description='原创测试角色',
                        image_base64=base64.b64encode(out.getvalue()).decode(),**changes)


class Executor:
    def __init__(self,ambiguous=False):self.values={};self.calls=0;self.ambiguous=ambiguous
    def create(self,request,job_id):
        self.calls+=1;self.values[job_id]={'state':'queued','stage':'queued','progress':0}
        if self.ambiguous:raise RuntimeError('Receipt lost')
    def get(self,job_id):return self.values[job_id]
    def cancel(self,job_id):self.values[job_id].update(state='cancelled')
    def retry(self,job_id):self.calls+=1;self.values[job_id].update(state='queued')


def test_avatar_ambiguous_submit_idempotency_owner_and_recovery(tmp_path):
    store=Store(tmp_path);executor=Executor(ambiguous=True)
    service=AvatarService(store,{'enabled':True},executor)
    value=asyncio.run(service.create('owner',request()))
    assert value['state']=='submission_error' and executor.calls==1
    value=asyncio.run(service.create('owner',request()))
    assert value['state']=='queued' and executor.calls==1
    different=request();different.description='不同角色'
    with pytest.raises(DomainError,match='不同图片'):
        asyncio.run(service.create('owner',different))
    with pytest.raises(DomainError):asyncio.run(service.status(value['id'],'other'))
    assert asyncio.run(service.control(value['id'],'owner','cancel'))['state']=='cancelled'
    assert asyncio.run(service.control(value['id'],'owner','retry'))['state']=='queued'
    assert executor.calls==2
    store.close();store=Store(tmp_path)
    assert store.avatars[value['id']]['owner']=='owner'
    store.close()


def test_invalid_avatar_image_cannot_create_or_charge_job(tmp_path):
    store=Store(tmp_path);executor=Executor();service=AvatarService(store,{'enabled':True},executor)
    payload=request();payload.image_base64='not base64'*10
    with pytest.raises(DomainError,match='PNG'):
        asyncio.run(service.create('owner',payload))
    assert not store.avatars and executor.calls==0
    store.close()


def test_avatar_http_ownership_cap_and_path_boundaries(tmp_path):
    app=create_app(tmp_path/'api')
    with TestClient(app) as client:
        executor=Executor();app.state.avatars=AvatarService(app.state.store,{'enabled':True},executor)
        client.headers['X-CSRF-Token']=client.post('/api/session').json()['csrf_token']
        response=client.post('/api/avatars',json=request().model_dump());assert response.status_code==202
        aid=response.json()['id']
        assert client.post('/api/avatars',json=request().model_dump()).json()['id']==aid
        assert executor.calls==1
        assert client.get('/api/avatars/'+aid+'/files/profile.json').status_code==404
        assert client.post('/api/avatars',content=b'{}',headers={'Content-Length':'15000000'}).status_code==413
        assert client.post('/api/avatars',content=b'garbage').status_code==422
        client.cookies.clear();client.headers['X-CSRF-Token']=client.post('/api/session').json()['csrf_token']
        assert client.get('/api/avatars/'+aid).status_code==404
        assert client.post('/api/avatars/'+aid+'/cancel').status_code==404


def test_pinned_worker_deduplicates_stable_creation_id(tmp_path):
    module=vendor_module('creation');store=module.CreationStore(tmp_path,runner='gpuq');calls=[]
    store.submit=lambda folder:calls.append(folder)
    payload=module.CreationRequest(description='测试形象',image_base64=request().image_base64)
    first=store.create(payload,'f'*32);second=store.create(payload,'f'*32)
    assert first['id']==second['id'] and len(calls)==1
    with pytest.raises(ValueError):store.create(payload,'../bad')


def test_lost_receipt_cannot_be_cancelled_then_blindly_resubmitted(tmp_path,monkeypatch):
    module=vendor_module('creation');store=module.CreationStore(tmp_path,runner='gpuq')
    store.submit=lambda folder:None
    payload=module.CreationRequest(description='角色参考',image_base64=request().image_base64)
    store.create(payload,'a'*32)
    monkeypatch.setattr(store,'recover_receipt',lambda folder:False)
    with pytest.raises(ValueError,match='not confirmed'):store.cancel('a'*32)
    state=module.read_json(store.folder('a'*32)/'status.json')
    assert state['state']=='queued'
    assert (store.folder('a'*32)/'cancel').exists()
    with pytest.raises(ValueError):store.retry('a'*32)


def test_lost_gpuq_receipt_reconciles_same_exact_job(tmp_path,monkeypatch):
    import json
    import subprocess
    module=vendor_module('creation');store=module.CreationStore(tmp_path,runner='gpuq')
    store.submit=lambda folder:None
    payload=module.CreationRequest(description='角色参考',image_base64=request().image_base64)
    store.create(payload,'b'*32);folder=store.folder('b'*32)
    state=module.read_json(folder/'status.json');state['state']='submission_error';module.write_json(folder/'status.json',state)
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**k:subprocess.CompletedProcess(a,0,json.dumps({'jobs':[
        {'id':'system-1:aaaaaaaaaaaa','command':['bash','worker',str(folder)]},
        {'id':'system-2:bbbbbbbbbbbb','command':['bash','worker',str(folder)+'-other']}]})))
    assert store.recover_receipt(folder)
    assert module.read_json(folder/'runner.json')['ref']=='system-1:aaaaaaaaaaaa'
    assert module.read_json(folder/'status.json')['state']=='queued'
