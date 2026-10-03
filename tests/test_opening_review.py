import asyncio
import json
import threading
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_content_preferences import SceneFixture, scene
from test_studio import session, wait_job

from roleplay_world.app import create_app
from roleplay_world.content_review import (
    ContentReview,
    ContentReviewFailure,
    SceneClaim,
    assess_content,
    opening_scene,
    review_fingerprint,
    review_schema,
    review_story,
    scene_conflict,
    validate_review,
)
from roleplay_world.contracts import DomainError


def finding(quote='The room is empty except for you.', **changes):
    return {"verdict": "fix", "kind": "scene_contradiction", "path": "/story/opening", "quote": quote,
            "explanation": "The engine places Robin in this room.", "scene_claim": {"kind": "no_other_people"}, **changes}


@pytest.mark.parametrize('kind,actor,location,conflicts', [
    ('no_other_people', None, None, True), ('actor_present', 'npc_0', None, False),
    ('actor_absent', 'npc_0', None, True), ('actor_location', 'npc_0', 'loc_0', False),
    ('actor_location', 'npc_0', 'loc_1', True), ('player_location', None, 'loc_0', False),
    ('player_location', None, 'loc_1', True),
])
def test_typed_opening_claims_use_compiled_positions(kind, actor, location, conflicts):
    world, story = scene()
    world.locations[0].connects_to = [1]
    world.locations.append(type(world.locations[0])(name='Garden', description='Outside', connects_to=[0]))
    truth = opening_scene(world, story)
    assert truth['characters'] == [{'id': 'npc_0', 'name': 'Robin', 'location_id': 'loc_0', 'present': True}]
    assert scene_conflict(truth, SceneClaim(kind=kind, actor_id=actor, location_id=location)) is conflicts
    story.start_location = 1
    alone = opening_scene(world, story)
    assert not alone['characters'][0]['present']
    assert not scene_conflict(alone, SceneClaim(kind='no_other_people'))
    assert truth['inventory'] == [] and truth['resources'] == {}


def test_scene_evidence_is_real_text_and_claims_are_bounded():
    world, story = scene()
    story.opening = 'The room is empty except for you.'
    data = {'world': world.model_dump(), 'story': story.model_dump(), 'initial_scene': opening_scene(world, story)}
    schema = review_schema(data)
    validate_review(schema(checks=[finding()]), data)
    for delta in ({'scene_claim': None}, {'path': '/initial_scene/characters/0/name', 'quote': 'Robin'},
                  {'scene_claim': {'kind': 'actor_location', 'actor_id': 'npc_0'}},
                  {'scene_claim': {'kind': 'no_other_people', 'location_id': 'loc_0'}},
                  {'kind': 'unsupported_item'}):
        with pytest.raises(DomainError):
            validate_review(ContentReview(checks=[finding(**delta)]), data)
    for key, value in [('actor_id', 'made_up_actor'), ('location_id', 'nonexistent')]:
        with pytest.raises(ValidationError):
            schema(checks=[finding(scene_claim={'kind': 'actor_location', key: value})])


@pytest.mark.parametrize('semantic_entailment', [True, False])
def test_scene_interpretation_is_independently_confirmed(semantic_entailment):
    world, story = scene()
    story.opening = 'The room is empty except for you.'
    calls = []

    async def generate(role, prompt, data, schema, jid, validator):
        calls.append(data)
        if schema.__name__ == 'DirectClaims':
            assert 'explanation' not in data['findings'][0]
            assert 'initial_scene' not in data and 'start_location' not in data['story']
            assert all('location' not in c for c in data['world']['characters'])
            assert data['entities']['characters'] == [{'id': 'npc_0', 'name': 'Robin'}]
            assert data['findings'][0]['scene_claim']['kind'] == 'no_other_people'
            result = schema(claims=[{'index': 0, 'explicit': semantic_entailment, 'reason': 'Independent fixture'}])
        else:
            result = schema(checks=[finding()])
        validator(result)
        return result

    review, rejected = asyncio.run(assess_content(world, story, generate, 'check'))
    assert len(calls) == 2 and bool(review.issues) is semantic_entailment
    assert bool(rejected) is not semantic_entailment


def test_consistent_scene_claim_cannot_block_or_trigger_paid_repair():
    world, story = scene()
    calls = []

    async def generate(role, prompt, data, schema, jid, validator):
        calls.append(role)
        result = schema(checks=[finding(quote=story.opening, scene_claim={'kind': 'actor_present', 'actor_id': 'npc_0'})])
        validator(result)
        return result

    changed, report = asyncio.run(review_story(world, story, generate, 'check', repair=True))
    assert changed == story and report['status'] == 'passed'
    assert report['rejected_findings'][0]['verifier'] == 'engine'
    assert calls == ['content_reviewer']


@pytest.mark.parametrize('repair', [True, False])
def test_plain_scene_review_repairs_only_text_and_preserves_failure_diagnostics(repair):
    world, story = scene()
    story.opening = 'The room is empty except for you.'
    original = deepcopy(story)
    before_truth = opening_scene(world, story)

    async def generate(role, prompt, data, schema, jid, validator):
        if schema.__name__ == 'DirectClaims':
            result = schema(claims=[{'index': 0, 'explicit': True, 'reason': 'Explicit sole occupant'}])
        elif role == 'state_builder':
            assert data['initial_scene'] == before_truth
            result = schema(patches=[{'path': '/story/opening', 'text': 'Robin waves from the window.'}])
        else:
            result = schema(checks=[finding()] if data['story']['opening'] == original.opening else [])
        validator(result)
        return result

    if repair:
        changed, report = asyncio.run(review_story(world, story, generate, 'check', repair=True))
        assert changed.opening == 'Robin waves from the window.'
        assert opening_scene(world, changed) == before_truth
        assert report['changes_applied'] and report['changes'] == [
            {'round': 1, 'path': '/story/opening', 'before': original.opening, 'after': changed.opening}]
    else:
        with pytest.raises(ContentReviewFailure) as raised:
            asyncio.run(review_story(world, story, generate, 'check'))
        assert raised.value.report['issues'][0]['scene_claim']['kind'] == 'no_other_people'
    assert story == original
    changed_world = world.model_copy(deep=True)
    changed_world.characters[0].name = 'Someone else'
    assert review_fingerprint(world, story) != review_fingerprint(changed_world, story)


class SceneReviewerFixture(SceneFixture):
    def __init__(self):
        super().__init__()
        self.review_count = 0
        self.reject = False
        self.bad_opening = False

    async def generate(self, role, system, data, schema, aid, budget, validate=None):
        if schema.__name__ == 'DirectClaims':
            result = schema(claims=[{'index': 0, 'explicit': True, 'reason': 'Fixture evidence'}])
        elif role == 'content_reviewer':
            self.review_count += 1
            result = schema(checks=[finding()] if self.reject and data['story']['opening'] == finding()['quote'] else [])
        elif role == 'state_builder':
            result = schema(patches=[{'path': '/story/opening', 'text': 'Robin waves from the window.'}])
        else:
            result = await super().generate(role, system, data, schema, aid, budget, validate)
            if role == 'story_builder' and self.bad_opening:
                result.opening = finding()['quote']
        if validate:
            validate(result)
        return result


def test_explicit_retest_rechecks_plain_scene_and_revokes_old_certificate(tmp_path):
    gateway = SceneReviewerFixture()
    gateway.bad_opening = True  # A first-pass semantic miss is caught on explicit retest.
    with TestClient(create_app(tmp_path / 'scene', gateway)) as client:
        session(client)
        job = client.post('/api/studio/worlds', json={'prompt': 'A quiet room', 'creation_preset': 'scene', 'content_language': 'en'}).json()
        ready = wait_job(client, job['id'])
        assert ready['status'] == 'ready' and gateway.review_count == 1
        sid = ready['story_id']
        existing = client.post('/api/campaigns', json={'story_id': sid, 'player_name': 'Visitor'}).json()
        path = f"/api/campaigns/{existing['id']}/branches/{existing['branch_id']}/view"
        before = client.get(path).json()
        gateway.reject = True
        test = client.post(f'/api/studio/stories/{sid}/test').json()
        assert wait_job(client, test['id'])['status'] == 'failed'
        assert gateway.review_count == 2
        assert client.post('/api/campaigns', json={'story_id': sid, 'player_name': 'Visitor'}).status_code == 409
        record = client.get('/api/studio').json()['stories'][0]
        assert record['test_report']['semantic_review']['issues'][0]['kind'] == 'scene_contradiction'
        assert client.get(path).json() == before
        gateway.reject = False
        assert client.post('/api/studio/jobs/' + test['id'] + '/retry').status_code == 200
        assert wait_job(client, test['id'])['status'] == 'ready' and gateway.review_count == 3


def test_native_import_with_omitted_defaults_is_not_normalized_or_repaired(tmp_path):
    world, story = scene()
    source = {'world': world.model_dump(exclude_defaults=True), 'story': story.model_dump(exclude_defaults=True)}
    assert 'starting_item' not in source['story']
    with TestClient(create_app(tmp_path / 'native', SceneReviewerFixture())) as client:
        session(client)
        upload = client.post('/api/studio/imports?filename=native.json', content=json.dumps(source).encode(),
                             headers={'Content-Type': 'application/octet-stream'}).json()
        job = client.post('/api/studio/imports/' + upload['id'] + '/convert', json={}).json()
        ready = wait_job(client, job['id'])
        assert ready['status'] == 'ready', ready
        exported = client.get('/api/studio/stories/' + ready['story_id'] + '/export').json()
        assert exported['story'] == source['story'] and exported['world'] == source['world']
        assert not ready['generated_conversion']


def import_scene(client, *, conflict=True, origin=None):
    world, story = scene()
    if conflict:
        story.opening = finding()['quote']
    source = {'world': world.model_dump(), 'story': story.model_dump()}
    if origin is not None:
        source['origin'] = origin
    raw = json.dumps(source).encode()
    upload = client.post('/api/studio/imports?filename=native.json', content=raw,
                         headers={'Content-Type': 'application/octet-stream'}).json()
    job = client.post('/api/studio/imports/' + upload['id'] + '/convert', json={}).json()
    ready = wait_job(client, job['id'])
    return source, raw, upload['id'], ready


@pytest.mark.parametrize('origin', [None, {'text_revisions': 'unknown legacy metadata'}])
def test_explicit_repair_versions_text_preserves_original_and_exports_audit(tmp_path, origin):
    gateway = SceneReviewerFixture()
    gateway.reject = True
    with TestClient(create_app(tmp_path, gateway)) as client:
        session(client)
        source, raw, iid, failed = import_scene(client, origin=origin)
        sid = failed['story_id']
        assert failed['status'] == 'failed'
        original = client.get(f'/api/studio/stories/{sid}/export').json()
        assert original['story'] == source['story']
        request = client.post(f'/api/studio/stories/{sid}/repair', json={'expected_revision': 1})
        assert request.status_code == 202
        repaired = wait_job(client, request.json()['id'])
        assert repaired['status'] == 'ready', repaired
        assert repaired['story_revision'] == 2
        exported = client.get(f'/api/studio/stories/{sid}/export').json()
        assert exported['world'] == source['world']
        assert exported['story'] == {**source['story'], 'opening': 'Robin waves from the window.'}
        assert exported['origin']['text_revisions'][-1]['changes'][0]['before'] == source['story']['opening']
        if origin:
            assert exported['origin']['text_revisions'][0]['preserved_source_value'] == origin['text_revisions']
        assert client.get(f'/api/studio/imports/{iid}/original').content == raw
        assert client.post(f'/api/studio/stories/{sid}/repair', json={'expected_revision': 1}).status_code == 409
        for value in [0, True, '2']:
            assert client.post(f'/api/studio/stories/{sid}/repair', json={'expected_revision': value}).status_code == 422
        old_cookies, old_csrf = client.cookies, client.headers['X-CSRF-Token']
        client.cookies.clear()
        session(client)
        assert client.post(f'/api/studio/stories/{sid}/repair', json={'expected_revision': 2}).status_code == 404
        client.cookies = old_cookies
        client.headers['X-CSRF-Token'] = old_csrf


def test_repair_enqueue_is_atomic_and_capacity_does_not_change_revision(tmp_path, monkeypatch):
    app = create_app(tmp_path, SceneReviewerFixture())
    with TestClient(app) as client:
        session(client)
        _, _, _, ready = import_scene(client, conflict=False)
        sid = ready['story_id']
        before = deepcopy(app.state.store.stories[sid])
        monkeypatch.setattr(app.state.studio, 'start', lambda _: None)
        job = client.post(f'/api/studio/stories/{sid}/repair', json={'expected_revision': 1}).json()
        assert app.state.store.stories[sid]['revision'] == 2
        assert app.state.store.stories[sid]['test_report']['status'] == 'pending'
        assert job['story_revision'] == 2 and job['repair_from_revision'] == 1
        frames = (tmp_path / 'journal.jsonl').read_text().splitlines()
        body = json.loads(frames[-1])['body']
        assert 'studio.batch_saved' in json.dumps(body)
        assert sid in json.dumps(body) and job['id'] in json.dumps(body)
        assert client.post(f'/api/studio/stories/{sid}/test').status_code == 409
        assert client.post(f'/api/studio/stories/{sid}/repair', json={'expected_revision': 2}).status_code == 409
        assert client.post('/api/studio/worlds', json={'prompt': 'Another room'}).status_code == 202
        snap = deepcopy(app.state.store.stories[sid])
        assert client.post(f'/api/studio/stories/{sid}/repair', json={'expected_revision': 2}).status_code == 409
        assert app.state.store.stories[sid] == snap
        assert snap['content'] == before['content']


def test_failed_repair_candidates_are_not_saved_and_retry_uses_same_revision(tmp_path):
    gateway = SceneReviewerFixture()
    gateway.reject = True
    original_generate = gateway.generate
    stuck = True

    async def generate(role, system, data, schema, aid, budget, validate=None):
        if role == 'state_builder' and stuck:
            result = schema(patches=[{'path': '/story/synopsis', 'text': 'A candidate that does not fix the opening.'}])
            if validate:
                validate(result)
            return result
        return await original_generate(role, system, data, schema, aid, budget, validate)

    gateway.generate = generate
    with TestClient(create_app(tmp_path, gateway)) as client:
        session(client)
        source, _, _, failed = import_scene(client)
        sid = failed['story_id']
        job = client.post(f'/api/studio/stories/{sid}/repair', json={'expected_revision': 1}).json()
        assert wait_job(client, job['id'])['status'] == 'failed'
        record = client.get('/api/studio').json()['stories'][0]
        review = record['test_report']['semantic_review']
        assert record['revision'] == 2 and record['content'] == source['story']
        assert review['changes'] and review['changes_applied'] is False and review['repair_rounds'] == 2
        stuck = False
        assert client.post('/api/studio/jobs/' + job['id'] + '/retry').status_code == 200
        assert wait_job(client, job['id'])['status'] == 'ready'
        assert client.get('/api/studio').json()['stories'][0]['revision'] == 2


@pytest.mark.parametrize('cancel', [False, True])
def test_late_or_cancelled_repair_cannot_overwrite_newer_content(tmp_path, cancel):
    gateway = SceneReviewerFixture()
    gateway.reject = True
    entered, release = threading.Event(), threading.Event()
    original_generate = gateway.generate

    async def generate(role, system, data, schema, aid, budget, validate=None):
        if role == 'state_builder':
            entered.set()
            while not release.is_set():
                await asyncio.sleep(.01)
        return await original_generate(role, system, data, schema, aid, budget, validate)

    gateway.generate = generate
    with TestClient(create_app(tmp_path, gateway)) as client:
        session(client)
        source, _, _, failed = import_scene(client)
        sid = failed['story_id']
        job = client.post(f'/api/studio/stories/{sid}/repair', json={'expected_revision': 1}).json()
        assert entered.wait(5)
        try:
            if cancel:
                assert client.post('/api/studio/jobs/' + job['id'] + '/cancel').status_code == 200
            edited = {**source['story'], 'opening': 'Rain taps the window; Robin waves.'}
            newer = client.put(f'/api/studio/stories/{sid}', json={'expected_revision': 2, 'content': edited}).json()
        finally:
            release.set()
        assert wait_job(client, job['id'])['status'] == ('cancelled' if cancel else 'failed')
        assert wait_job(client, newer['id'])['status'] == 'ready'
        record = client.get('/api/studio').json()['stories'][0]
        assert record['revision'] == 3 and record['content'] == edited
        assert client.post('/api/studio/jobs/' + job['id'] + '/retry').status_code == 409
