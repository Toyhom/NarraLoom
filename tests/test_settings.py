import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from roleplay_world.app import create_app
from roleplay_world.gateway import ModelGateway
from roleplay_world.settings import MODEL_OWNER, ProviderSettings, Settings


def payload(**kw):
    return ProviderSettings(url='https://example.com/v1',model='flash',api_key='test-private-key',**kw)


def test_provider_credentials_do_not_cross_owners_or_endpoints(tmp_path):
    settings=Settings(tmp_path,{'default':{'url':'https://deployment.example/v1','model':'base','api_key_file':'secrets/private.key'}})
    assert settings.public('a')['using_default']
    settings.save('a',payload(roles={'game_master':'reasoner'}))
    public=settings.public('a');assert 'test-private-key' not in str(public)
    gateway=ModelGateway(settings.default,tmp_path/'traces',settings)
    token=MODEL_OWNER.set('a')
    assert gateway.role_config('game_master')['model']=='reasoner'
    assert gateway.auth_headers(gateway.role_config('character_actor'))['Authorization']=='Bearer test-private-key'
    MODEL_OWNER.reset(token)
    token=MODEL_OWNER.set('b');assert gateway.role_config('game_master')['model']=='base';MODEL_OWNER.reset(token)
    same=payload();same.api_key='';settings.save('a',same);assert settings.effective('a')['default']['api_key']=='test-private-key'
    same.url='https://different.example/v1';settings.save('a',same)
    assert settings.effective('a')['default']['api_key']==''
    assert 'api_key_file' not in settings.effective('a')['default']
    reopened=Settings(tmp_path,settings.default);assert reopened.public('a')['url']==same.url
    assert reopened.reset('a')['using_default']


def test_model_context_is_inherited_by_background_job_without_cross_talk():
    async def check():
        gate=asyncio.Event()
        async def worker():await gate.wait();return MODEL_OWNER.get()
        token=MODEL_OWNER.set('owner-a');a=asyncio.create_task(worker());MODEL_OWNER.reset(token)
        token=MODEL_OWNER.set('owner-b');b=asyncio.create_task(worker());MODEL_OWNER.reset(token)
        gate.set();assert await a=='owner-a';assert await b=='owner-b';assert MODEL_OWNER.get() is None
    asyncio.run(check())


def test_usage_is_prompt_free_and_reports_missing_usage(tmp_path):
    settings=Settings(tmp_path,{})
    trace={'role':'character_actor','model':'flash','usage':{'prompt_tokens':10,'completion_tokens':7},'duration_s':2,'context':'PRIVATE-STORY','output':'PRIVATE-RESPONSE'}
    settings.record_usage('a',trace);settings.record_usage('a',{**trace,'usage':None});settings.record_usage('b',trace)
    report=settings.report('a');assert report['calls']==2 and report['models'][0]['prompt_tokens']==10
    assert report['models'][0]['unreported_calls']==1
    assert 'PRIVATE' not in (tmp_path/'usage.jsonl').read_text()
    assert Settings(tmp_path,{}).report('b')['calls']==1


def test_http_provider_is_session_owned_and_masks_keys(tmp_path):
    with TestClient(create_app(tmp_path/'api')) as client:
        client.headers['X-CSRF-Token']=client.post('/api/session').json()['csrf_token']
        r=client.put('/api/settings/provider',json=payload().model_dump());assert r.status_code==200
        assert 'test-private-key' not in r.text and r.json()['has_key']
        assert client.get('/api/settings/provider').json()['model']=='flash'
        invalid=payload().model_dump();invalid['url']='file:///invalid/private'
        bad=client.put('/api/settings/provider',json=invalid)
        assert bad.status_code==422 and 'test-private-key' not in bad.text
        client.cookies.clear();client.headers['X-CSRF-Token']=client.post('/api/session').json()['csrf_token']
        assert client.get('/api/settings/provider').json()['using_default']
        assert client.get('/api/settings/usage').json()['calls']==0


def test_provider_validates_urls_roles():
    for url in ('file:///etc/passwd','https://key@example.com/v1','https://host/v1?key=x'):
        with pytest.raises(ValidationError):ProviderSettings(url=url,model='foo')
    with pytest.raises(ValidationError):payload(roles={'untrusted':'bad'})
