import io
import json
import zipfile
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from test_content_preferences import SceneFixture, scene
from test_studio import session, wait_job

from roleplay_world.app import create_app
from roleplay_world.avatars import AvatarService
from roleplay_world.contracts import DomainError
from roleplay_world.packages import (
    PackageBuild,
    PackageInstall,
    build_package,
    install_package,
    package_path,
    read_package,
)
from roleplay_world.store import Store
from roleplay_world.studio import Studio


def metadata(**changes):
    return {'slug': 'rain-room', 'release': '1.0.0', 'title': 'Rain Room Collection', 'summary': 'Two quiet visits.',
            'author': 'Creator', 'license': 'CC-BY-4.0', 'tags': ['everyday'], **changes}


def seed(store, owner='creator', count=2):
    world, story = scene()
    store.studio_save('worlds', {'id': 'world_source', 'owner': owner, 'revision': 1, 'content': world.model_dump(),
                               'origin': {'source': {'license': 'CC-BY-4.0', 'author': 'World Author'}}})
    result = []
    for i in range(count):
        value = {'id': f'story_source_{i}', 'owner': owner, 'world_id': 'world_source', 'world_revision': 1, 'revision': 1,
                 'world_content': world.model_dump(), 'content': story.model_dump(), 'created_at': 1,
                 'origin': {'source': {'license': 'MIT', 'license_text': 'Attribution must be retained.'}},
                 'test_report': {'status': 'passed', 'revision': 1, 'mode': 'test_fixture', 'steps': []}}
        value['content']['title'] += f' {i+1}'
        store.studio_save('stories', value)
        result.append({'id': value['id'], 'revision': 1})
    return result


def make(store, **changes):
    studio = Studio(store, SceneFixture(), store.journal.root / 'tests')
    refs = seed(store, count=changes.pop('count', 2))
    request = PackageBuild(metadata=metadata(), stories=refs, **changes)
    record = build_package(studio, AvatarService(store, {}), 'creator', request)
    return studio, request, record, package_path(store, record['sha256']).read_bytes()


def repack(raw, mutate):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = {n: archive.read(n) for n in archive.namelist()}
    mutate(files)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue()


def test_snapshot_deterministic_private_and_multiple_stories(tmp_path):
    with_store = Store(tmp_path)
    try:
        studio, request, record, raw = make(with_store)
        assert record['visibility'] == 'private' and len(record['stories']) == 2
        assert build_package(studio, AvatarService(with_store, {}), 'creator', request)['id'] == record['id']
        parsed = read_package(raw)
        assert parsed['payload']['world'] == with_store.stories['story_source_0']['world_content']
        assert parsed['payload']['world_origin'] == with_store.worlds['world_source']['origin']
        assert parsed['payload']['stories'][0]['origin']['source']['license'] == 'MIT'
        assert parsed['payload']['stories'][0]['test_summary']['advisory_only']
        source = deepcopy(with_store.stories['story_source_0']); source['content']['opening'] = 'Changed later'
        with_store.studio_save('stories', source)
        assert package_path(with_store, record['sha256']).read_bytes() == raw
        with pytest.raises(DomainError, match='版本'):
            build_package(studio, AvatarService(with_store, {}), 'creator', request)
    finally:
        with_store.close()


@pytest.mark.parametrize('kind', ['stale', 'untested', 'world_revision', 'owner', 'duplicate'])
def test_invalid_selection_never_publishes_or_calls_models(tmp_path, kind):
    store = Store(tmp_path)
    try:
        refs = seed(store);studio = Studio(store, SceneFixture(), tmp_path / 'tests')
        if kind == 'duplicate':
            refs[1] = refs[0]
        else:
            row = store.stories[refs[0]['id']]
            if kind == 'stale': row['revision'] = 2
            if kind == 'untested': row['test_report']['status'] = 'pending'
            if kind == 'world_revision': row['world_revision'] = 2
            if kind == 'owner': row['owner'] = 'other'
        before = store.journal.path.read_bytes()
        with pytest.raises(DomainError):
            build_package(studio, AvatarService(store, {}), 'creator', PackageBuild(metadata=metadata(), stories=refs))
        assert not store.publications and store.journal.path.read_bytes() == before
    finally:
        store.close()


@pytest.mark.parametrize('change', ['extra', 'traversal', 'hash', 'new_schema', 'external_asset', 'unknown_capability'])
def test_archive_rejects_tampering_and_unsupported_dependencies(tmp_path, change):
    store = Store(tmp_path)
    try:
        _, _, _, raw = make(store)
        def mutate(files):
            if change in {'extra', 'traversal', 'external_asset'}:
                files[{'extra': 'script.js', 'traversal': '../world.json', 'external_asset': 'https://invalid/portrait.png'}[change]] = b'{}'
            elif change == 'hash':
                files['content.json'] += b' '
            else:
                m = json.loads(files['manifest.json'])
                if change == 'new_schema': m['schema_version'] = '9.0.0'
                if change == 'unknown_capability': m['capabilities'].append('execute_scripts')
                files['manifest.json'] = json.dumps(m).encode()
        with pytest.raises(DomainError):
            read_package(repack(raw, mutate))
    finally:
        store.close()


def test_partial_install_one_world_atomic_jobs_retest_and_no_overwrite(tmp_path, monkeypatch):
    store = Store(tmp_path)
    try:
        studio, _, _, raw = make(store, count=3)
        started = [];monkeypatch.setattr(studio, 'start', started.append)
        first = install_package(studio, 'reader', raw, PackageInstall(story_keys=['story_1']))
        before = store.journal.path.read_bytes()
        assert install_package(studio, 'reader', raw, PackageInstall(story_keys=['story_1']))['id'] == first['id']
        assert store.journal.path.read_bytes() == before
        imported = store.stories[first['story_id']]
        assert imported['test_report']['status'] == 'pending'
        imported['content']['title'] = 'Reader edit'
        store.worlds[first['world_id']]['revision'] = 2
        store.worlds[first['world_id']]['content']['title'] = 'Newer reader world'
        install_package(studio, 'reader', raw, PackageInstall())
        assert len(started) == 3
        records = [s for s in store.stories.values() if s['owner'] == 'reader']
        assert len({s['world_id'] for s in records}) == 1
        assert imported['content']['title'] == 'Reader edit'
        assert all(s['world_revision'] == 1 and s['world_content']['title'] == 'The Rain Room' for s in records)
        assert store.worlds[first['world_id']]['revision'] == 2
        studio.require_capacity('reader')  # Three tests belong to one bounded import.
        last = json.loads(store.journal.path.read_text().splitlines()[-1])['body']
        assert last['kind'] == 'studio.batch_saved' and len(last['items']) == 4
        assert all(j['status'] == 'queued' for j in store.jobs.values())
    finally:
        store.close()


def test_publication_permissions_visibility_download_install_restart(tmp_path):
    app = create_app(tmp_path, SceneFixture())
    with TestClient(app) as client:
        session(client)
        import hashlib
        creator = hashlib.sha256(client.cookies['rpw_session'].encode()).hexdigest()
        refs = seed(app.state.store, creator)
        created = client.post('/api/studio/packages', json={'metadata': metadata(), 'stories': refs})
        assert created.status_code == 201, created.text
        record = created.json();pid = record['id']
        raw = client.get(f'/api/community/{pid}/download').content
        assert client.get('/api/community').json()['total'] == 0
        assert 'secret-marker' not in json.dumps(record)
        creator_cookies = dict(client.cookies)
        client.cookies.clear();session(client)
        assert client.get(f'/api/community/{pid}').status_code == 404
        assert client.get(f'/api/community/{pid}/download').status_code == 404
        assert client.put(f'/api/studio/packages/{pid}/visibility', json={'expected_revision': 1, 'visibility': 'listed'}).status_code == 404
        reader_cookies = dict(client.cookies)
        client.cookies.clear();client.cookies.update(creator_cookies);session(client)
        published = client.put(f'/api/studio/packages/{pid}/visibility', json={'expected_revision': 1, 'visibility': 'unlisted'}).json()
        assert published['revision'] == 2
        client.cookies.clear();client.cookies.update(reader_cookies);session(client)
        assert client.get(f'/api/community/{pid}').status_code == 200
        assert client.get('/api/community').json()['total'] == 0
        preview = client.post('/api/studio/packages/preview', content=raw).json()
        assert len(preview['stories']) == 2 and 'secret-marker' not in json.dumps(preview)
        job = client.post(f'/api/community/{pid}/install', json={}).json()
        library = client.get('/api/studio').json()
        for row in library['jobs']:
            assert wait_job(client, row['id'])['status'] == 'ready'
        assert len(library['worlds']) == 1 and len(library['stories']) == 2
        assert client.post('/api/studio/packages/import', content=raw).json()['id'] == job['id']
        client.cookies.clear();client.cookies.update(creator_cookies);session(client)
        assert client.put(f'/api/studio/packages/{pid}/visibility', json={'expected_revision': 1, 'visibility': 'listed'}).status_code == 409
        assert client.put(f'/api/studio/packages/{pid}/visibility', json={'expected_revision': 2, 'visibility': 'listed'}).status_code == 200
        assert client.get('/api/community?q=quiet&tag=everyday&language=en').json()['total'] == 1
        assert client.get('/api/community?language=ja').json()['total'] == 0
        assert client.put(f'/api/studio/packages/{pid}/visibility', json={'expected_revision': 3, 'visibility': 'withdrawn'}).status_code == 200
    with TestClient(create_app(tmp_path, SceneFixture())) as client:
        client.cookies.update(reader_cookies);session(client)
        assert client.get(f'/api/community/{pid}/download').status_code == 404
        assert len(client.get('/api/studio').json()['stories']) == 2
        assert client.post('/api/campaigns', json={'story_id': job['story_id']}).status_code == 201


def test_render_assets_are_portable_owned_and_do_not_include_creation_inputs(tmp_path, monkeypatch):
    import hashlib

    from PIL import Image

    from roleplay_world.journal import canonical, digest
    from roleplay_world.packages import RENDER_FILES, validate_render, write_file
    store = Store(tmp_path)
    try:
        refs = seed(store)
        rig = {'version': 3, 'renderer': 'deformable-portrait', 'image': 'portrait.png', 'width': 32, 'height': 32,
               'mouth_width_px': 6, 'landmarks': {'mouth': [.5, .6], 'left_eye': [.4, .4], 'right_eye': [.6, .4], 'face_width': .4},
               'mouth_binding': {'atlas': 'mouth-atlas.png', 'method': 'source-lip-warp-v3'}}
        png = io.BytesIO();Image.new('RGB', (32, 32), 'green').save(png, format='PNG')
        files = {'puppet/rig.json': canonical(rig), 'puppet/portrait.png': png.getvalue(), 'puppet/mouth-atlas.png': png.getvalue()}
        asset_hash = digest({name: hashlib.sha256(value).hexdigest() for name, value in files.items()})
        for name, raw in files.items():
            write_file(tmp_path / 'package-assets' / asset_hash / name, raw)
        store.studio_save('avatars', {'id': 'avatar_source', 'owner': 'creator', 'state': 'ready', 'asset_digest': asset_hash,
                                      'character_id': 'char_' + asset_hash[:16]})
        for story in store.stories.values():
            story['world_content']['characters'][0]['avatar_id'] = 'avatar_source'
        studio = Studio(store, SceneFixture(), tmp_path / 'tests');monkeypatch.setattr(studio, 'start', lambda _: None)
        service = AvatarService(store, {})
        request = PackageBuild(metadata=metadata(), stories=refs)
        package = build_package(studio, service, 'creator', request)
        raw = package_path(store, package['sha256']).read_bytes()
        parsed = read_package(raw)
        assert set(parsed['files']) == {'content.json', *[f"assets/{parsed['manifest']['assets'][0]['id']}/{name}" for name in RENDER_FILES]}
        job = install_package(studio, 'reader', raw, PackageInstall())
        aid = store.stories[job['story_id']]['world_content']['characters'][0]['avatar_id']
        assert aid != 'avatar_source'
        assert all(service.asset(aid, 'reader', name).read_bytes() == value for name, value in files.items())
        assert json.loads(service.asset(aid, 'reader', 'profile.json').read_text()) == {'character_id': 'char_' + asset_hash[:16]}
        for wrong_owner in ['creator', 'outsider']:
            with pytest.raises(DomainError):
                service.asset(aid, wrong_owner, 'puppet/portrait.png')
        for name in ['input.png', '../profile.json', 'voice/ref.wav']:
            with pytest.raises(DomainError):
                service.asset(aid, 'reader', name)
        broken = {**files, 'puppet/rig.json': canonical({**rig, 'image': 'https://invalid/p.png'})}
        with pytest.raises(DomainError):
            validate_render(broken)
        request.include_avatars = False;request.metadata.release = '1.0.1'
        without = build_package(studio, service, 'creator', request)
        assert without['omissions'] and not without['assets']
        assert read_package(package_path(store, without['sha256']).read_bytes())['payload']['world']['characters'][0]['avatar_id'] is None
    finally:
        store.close()


def test_batch_capacity_and_poisoned_write_never_certify_partial_install(tmp_path, monkeypatch):
    store = Store(tmp_path)
    try:
        studio, _, _, raw = make(store)
        monkeypatch.setattr(studio, 'start', lambda _: None)
        for i in range(2):
            store.studio_save('jobs', {'id': f'busy_{i}', 'owner': 'reader', 'status': 'queued'})
        before = store.journal.path.read_bytes()
        with pytest.raises(DomainError, match='已有创作'):
            install_package(studio, 'reader', raw, PackageInstall())
        assert store.journal.path.read_bytes() == before
        for j in store.jobs.values():
            j['status'] = 'ready'
        def fail(items):
            raise OSError('simulated write failure before journal commit')
        monkeypatch.setattr(store, 'studio_save_batch', fail)
        with pytest.raises(OSError):
            install_package(studio, 'reader', raw, PackageInstall())
        assert not any(s['owner'] == 'reader' for s in store.stories.values())
        assert not any(w['owner'] == 'reader' for w in store.worlds.values())
    finally:
        store.close()
