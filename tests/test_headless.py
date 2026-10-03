"""Exercise the standalone client against an HTTP fixture, including process-like restarts."""
import hashlib
import json
import runpy
import sys
from pathlib import Path

import httpx


def test_headless_resumes_pending_creation_and_keeps_cookie_scope(tmp_path, monkeypatch, capsys):
    session_file = tmp_path/'session.local.json'
    cookie = 'a'*64
    csrf = hashlib.sha256(('csrf:'+cookie).encode()).hexdigest()
    session_file.write_text(json.dumps({'url':'http://127.0.0.1:18091','cookie':cookie,'job_id':'pending'}))
    seen = []; version = 0; last_action = None
    def handle(request):
        nonlocal version, last_action
        path = request.url.path; seen.append((request.method,path))
        assert request.headers.get('Cookie') == 'rpw_session='+cookie
        if path == '/api/session':
            return httpx.Response(200,json={'csrf_token':csrf},headers={'set-cookie':'rpw_session='+cookie+'; Path=/; HttpOnly'})
        if request.method == 'POST':
            assert request.headers['X-CSRF-Token'] == csrf
        if path == '/api/studio/jobs/pending':
            return httpx.Response(200,json={'id':'pending','status':'ready','story_id':'generated'})
        if path == '/api/campaigns':
            body = json.loads(request.content)
            assert body['story_id'] == 'generated'
            assert body['request_id'] == json.loads(session_file.read_text())['flow']['request']['body']['request_id']
            return httpx.Response(201,json={'id':'campaign','branch_id':'branch'})
        if path.endswith('/view'):
            return httpx.Response(200,json={'world_version':version})
        if path.endswith('/actions'):
            command = json.loads(request.content)
            assert command['action_id'] == json.loads(session_file.read_text())['flow']['request']['body']['action_id']
            assert command['expected_world_version'] == version
            last_action = command['action_id']; version += 1
            return httpx.Response(202,json={'id':last_action})
        if path == '/api/actions/'+last_action:
            return httpx.Response(200,json={'id':last_action,'status':'committed','result':{'segments':[{'text':'A new scene.'}]}})
        raise AssertionError(path)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(**{**kw,'transport':httpx.MockTransport(handle)}))
    script = Path(__file__).resolve().parents[1]/'examples/headless.py'
    for _ in range(2):
        monkeypatch.setattr(sys,'argv',[str(script),'--session-file',str(session_file),'--url','http://127.0.0.1:18091'])
        runpy.run_path(str(script),run_name='__main__')
    monkeypatch.setattr(sys,'argv',[str(script),'--session-file',str(session_file),'--url','http://127.0.0.1:18091','--resume'])
    runpy.run_path(str(script),run_name='__main__')
    assert version == 2 and seen.count(('POST','/api/campaigns')) == 1
    assert seen.count(('GET','/api/studio/jobs/pending')) == 1
    assert 'job_id' not in json.loads(session_file.read_text())
    assert cookie not in capsys.readouterr().out
