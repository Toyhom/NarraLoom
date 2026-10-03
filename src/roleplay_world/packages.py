"""Portable world/multi-story packages and explicit instance-local publication.

Only metadata is advertised. Installations copy immutable snapshots into a recipient's
library and always schedule that recipient's own tests. No source code is executed.
"""
import hashlib
import io
import json
import math
import os
import re
import time
import zipfile
import zlib
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, ValidationError, field_validator

from .content import StoryBlueprint, WorldBlueprint, validate_story
from .contracts import Contract, DomainError, Identifier
from .journal import canonical, digest

MAX_PACKAGE = 32 * 1024 * 1024
MAX_PAYLOAD = 2 * 1024 * 1024
RENDER_FILES = ('puppet/rig.json', 'puppet/portrait.png', 'puppet/mouth-atlas.png')
ACTIVE = {'queued', 'generating_world', 'generating_story', 'testing'}
CAPABILITIES = {'structured_generation', 'state_rules', 'rules', 'simulation', 'webgl_2d', 'check_engine', 'action_modules'}


class PackageMetadata(Contract):
    slug: Annotated[str, Field(pattern=r'^[a-z0-9][a-z0-9-]{0,59}$')]
    release: Annotated[str, Field(pattern=r'^\d{1,4}\.\d{1,4}\.\d{1,4}$')]
    title: Annotated[str, Field(min_length=1, max_length=100)]
    summary: Annotated[str, Field(min_length=1, max_length=800)]
    author: Annotated[str, Field(min_length=1, max_length=120)]
    license: Annotated[str, Field(min_length=1, max_length=80)]
    license_text: Annotated[str, Field(max_length=12000)] = ''
    tags: Annotated[list[Annotated[str, Field(min_length=1, max_length=32)]], Field(max_length=8)] = Field(default_factory=list)
    model_notes: Annotated[str, Field(max_length=1000)] = ''
    known_limits: Annotated[list[Annotated[str, Field(max_length=400)]], Field(max_length=20)] = Field(default_factory=list)

    @field_validator('title', 'summary', 'author', 'license')
    @classmethod
    def visible_text(cls, value):
        if not value.strip():
            raise ValueError('A visible value is required')
        return value.strip()


class PackageStoryRef(Contract):
    id: Identifier
    revision: Annotated[int, Field(strict=True, ge=1)]


class PackageBuild(Contract):
    metadata: PackageMetadata
    stories: Annotated[list[PackageStoryRef], Field(min_length=1, max_length=8)]
    include_avatars: bool = True


class PackageVisibility(Contract):
    expected_revision: Annotated[int, Field(strict=True, ge=1)]
    visibility: Literal['private', 'unlisted', 'listed', 'withdrawn']


class PackageInstall(Contract):
    story_keys: Annotated[list[Identifier], Field(max_length=8)] | None = None


class FileEntry(Contract):
    path: Annotated[str, Field(min_length=1, max_length=160)]
    sha256: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    bytes: Annotated[int, Field(strict=True, ge=1, le=MAX_PACKAGE)]


class AssetEntry(Contract):
    id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=120)]
    digest: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]


class PackageManifest(Contract):
    format: Literal['narraloom.content-package'] = 'narraloom.content-package'
    schema_version: Literal['1.0.0'] = '1.0.0'
    metadata: PackageMetadata
    engine_minimum: Literal['0.12.0', '0.16.0', '0.19.0'] = '0.12.0'
    files: Annotated[list[FileEntry], Field(min_length=1, max_length=13)]
    assets: Annotated[list[AssetEntry], Field(max_length=4)] = Field(default_factory=list)
    capabilities: Annotated[list[str], Field(min_length=1, max_length=7)]
    omissions: Annotated[list[str], Field(max_length=32)] = Field(default_factory=list)


def invalid(message):
    raise DomainError('invalid_package', message, 422)


def json_value(raw, maximum=MAX_PAYLOAD):
    if len(raw) > maximum:
        invalid('内容包JSON超过大小限制')
    try:
        def reject(value):
            raise ValueError(value)
        value = json.loads(raw.decode('utf-8'), parse_constant=reject)
        if not isinstance(value, dict):
            invalid('内容包JSON必须是对象')
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DomainError('invalid_package', '内容包JSON无效', 422) from exc


def capabilities(world, stories, assets):
    result = ['structured_generation']
    for name in ('rules', 'state_rules', 'simulation'):
        if world.get(name) or any(s['content'].get(name) for s in stories):
            result.append(name)
    if assets:
        result.append('webgl_2d')
    if world.get('check_engine'):
        result.append('check_engine')
    if world.get('action_modules'):
        result.append('action_modules')
    return sorted(result)


def validate_render(files):
    """Bound only the three rendering files; source images, voices and prompts stay private."""
    rig = json_value(files['puppet/rig.json'], 96 * 1024)
    if rig.get('version') != 3 or rig.get('renderer') != 'deformable-portrait' or rig.get('image') != 'portrait.png':
        invalid('仅支持版本3的deformable-portrait渲染包')
    binding = rig.get('mouth_binding')
    if not isinstance(binding, dict) or binding.get('atlas') != 'mouth-atlas.png':
        invalid('口型图集必须引用包内mouth-atlas.png')
    if (binding.get('method') != 'source-lip-warp-v3' or type(rig.get('width')) is not int
            or type(rig.get('height')) is not int or type(rig.get('mouth_width_px')) not in {int, float}
            or not 0 < rig['mouth_width_px'] <= rig['width']):
        invalid('当前分享包仅支持有界的source-lip-warp-v3参数')
    def bounded(value, depth=0):
        if depth > 12:
            invalid('2D参数嵌套过深')
        if isinstance(value, (int, float)) and (not math.isfinite(value) or abs(value) > 1_000_000):
            invalid('2D参数数值超限')
        if isinstance(value, list):
            if len(value) > 4096:
                invalid('2D参数列表超限')
            for child in value:
                bounded(child, depth + 1)
        if isinstance(value, dict):
            for child in value.values():
                bounded(child, depth + 1)
    bounded(rig)
    landmarks = rig.get('landmarks', {})
    for key in ('mouth', 'left_eye', 'right_eye'):
        point = landmarks.get(key) if isinstance(landmarks, dict) else None
        if not isinstance(point, list) or len(point) != 2 or any(type(v) not in {int, float} or not 0 <= v <= 1 for v in point):
            invalid('2D面部坐标无效')
    if type(landmarks.get('face_width')) not in {int, float} or not 0 < landmarks['face_width'] <= 1:
        invalid('2D面部宽度无效')
    # Pillow remains optional for text-only/headless use.
    try:
        from PIL import Image
    except ImportError as exc:
        raise DomainError('avatar_dependency', '导入2D素材需要安装NarraLoom的avatar可选依赖', 422) from exc
    try:
        for filename in RENDER_FILES[1:]:
            with Image.open(io.BytesIO(files[filename])) as picture:
                if picture.format != 'PNG' or not 1 <= picture.width <= 4096 or not 1 <= picture.height <= 4096:
                    invalid('2D图片必须为4096像素以内的PNG')
                if filename.endswith('portrait.png') and (rig.get('width'), rig.get('height')) != picture.size:
                    invalid('2D图片尺寸与rig不符')
                picture.verify()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise DomainError('invalid_package', '2D图片校验失败', 422) from exc


def read_package(raw):
    if not raw or len(raw) > MAX_PACKAGE:
        invalid('内容包必须小于32 MiB')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 14 or sum(f.file_size for f in entries) > MAX_PACKAGE:
                invalid('内容包文件数或解压总量超限')
            names = set()
            for f in entries:
                path = PurePosixPath(f.filename)
                if (f.filename in names or path.is_absolute() or '..' in path.parts or '\\' in f.filename or ':' in f.filename
                        or str(path) != f.filename or f.is_dir() or (f.external_attr >> 16) & 0o170000 == 0o120000
                        or f.flag_bits & 1 or f.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
                    invalid('内容包路径、链接、加密或压缩方式无效')
                names.add(f.filename)
            if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size > 64 * 1024:
                invalid('内容包缺少有界的manifest.json')
            manifest = PackageManifest.model_validate(json_value(archive.read('manifest.json'), 64 * 1024)).model_dump()
            listed = {entry['path'] for entry in manifest['files']}
            if len(listed) != len(manifest['files']) or names != listed | {'manifest.json'}:
                invalid('文件清单必须逐项精确覆盖内容包')
            asset_ids = [a['id'] for a in manifest['assets']]
            if len(set(asset_ids)) != len(asset_ids):
                invalid('2D资源ID重复')
            expected = {'content.json'} | {f'assets/{aid}/{name}' for aid in asset_ids for name in RENDER_FILES}
            if listed != expected:
                invalid('包只允许content.json和已声明的2D渲染文件')
            files = {}
            for entry in manifest['files']:
                info = archive.getinfo(entry['path'])
                if info.file_size != entry['bytes']:
                    invalid('文件大小不符')
                value = archive.read(entry['path'])
                if hashlib.sha256(value).hexdigest() != entry['sha256']:
                    invalid('文件摘要不符')
                files[entry['path']] = value
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, RuntimeError, ValueError, KeyError, ValidationError, RecursionError) as exc:
        raise DomainError('invalid_package', '无法验证内容包格式/文件清单', 422) from exc
    payload = json_value(files['content.json'])
    if set(payload) != {'world', 'world_origin', 'stories'} or not isinstance(payload['stories'], list) or not 1 <= len(payload['stories']) <= 8:
        invalid('内容包须包含一个世界和1至8篇故事')
    try:
        world = WorldBlueprint.model_validate(payload['world'])
        keys = set()
        for story in payload['stories']:
            if set(story) != {'key', 'content', 'origin', 'source_revision', 'test_summary'}:
                invalid('故事快照字段无效')
            if not isinstance(story['key'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', story['key']) or story['key'] in keys:
                invalid('故事key无效或重复')
            keys.add(story['key'])
            if type(story['source_revision']) is not int or story['source_revision'] < 1:
                invalid('故事来源修订无效')
            validate_story(world, StoryBlueprint.model_validate(story['content']))
    except (ValidationError, KeyError, TypeError, ValueError) as exc:
        raise DomainError('invalid_package', '世界或故事快照不符合契约', 422) from exc
    refs = {c.avatar_id for c in world.characters if c.avatar_id}
    if refs != set(asset_ids):
        invalid('世界的形象引用必须精确对应包内资源')
    for asset in manifest['assets']:
        group = {name: files[f"assets/{asset['id']}/{name}"] for name in RENDER_FILES}
        validate_render(group)
        if digest({name: hashlib.sha256(value).hexdigest() for name, value in group.items()}) != asset['digest']:
            invalid('2D资源组摘要不符')
    if set(manifest['capabilities']) != set(capabilities(payload['world'], payload['stories'], asset_ids)):
        invalid('依赖能力与实际内容不符或未支持')
    if 'action_modules' in payload['world'] and manifest['engine_minimum'] != '0.19.0':
        invalid('Action module fields require NarraLoom 0.19.0 or newer')
    if 'check_engine' in payload['world'] and manifest['engine_minimum'] not in {'0.16.0', '0.19.0'}:
        invalid('检定引擎字段需要 NarraLoom 0.16.0 或更新版本')
    return {'manifest': manifest, 'payload': payload, 'files': files, 'sha256': hashlib.sha256(raw).hexdigest()}


def write_file(path, raw):
    """Publish immutable files before a journal reference; a failed journal leaves only an orphan."""
    missing = []
    folder = path.parent
    while not folder.exists():
        missing.append(folder)
        folder = folder.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise DomainError('package_corrupt', '已保存的内容包摘要路径冲突', 503)
        return
    temp = path.with_name(path.name + '.pending-' + str(time.time_ns()))
    with temp.open('xb') as target:
        target.write(raw); target.flush(); os.fsync(target.fileno())
    os.replace(temp, path)
    for directory in dict.fromkeys([path.parent, *(p.parent for p in missing)]):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def package_path(store, sha):
    if not re.fullmatch(r'[a-f0-9]{64}', sha):
        invalid('内容包摘要无效')
    return store.journal.root / 'packages' / (sha + '.zip')


def public_package(record):
    return {k: deepcopy(record[k]) for k in ('id', 'revision', 'visibility', 'sha256', 'created_at', 'metadata',
        'stories', 'languages', 'genre', 'locations', 'characters', 'assets', 'capabilities', 'omissions')}


def preview_package(parsed):
    manifest, payload = parsed['manifest'], parsed['payload']
    world = payload['world']
    return {'sha256': parsed['sha256'], 'metadata': manifest['metadata'], 'assets': manifest['assets'],
            'capabilities': manifest['capabilities'], 'omissions': manifest['omissions'],
            'engine_minimum': manifest['engine_minimum'],
            'check_engine': ({key: world['check_engine'][key] for key in ('engine', 'version')}
                             if world.get('check_engine') else None),
            'action_modules': [{key: binding[key] for key in ('id', 'engine', 'version')}
                               for binding in world.get('action_modules', [])],
            'genre': world['genre'], 'locations': len(world['locations']), 'characters': len(world['characters']),
            'stories': [{'key': s['key'], 'title': s['content']['title'],
                         'language': s['content'].get('content_language') or world.get('content_language', 'zh-CN'),
                         'preset': s['content'].get('creation_preset') or world.get('creation_preset', 'adventure')}
                        for s in payload['stories']]}


def build_package(studio, avatars, owner, request):
    studio.store.require_writable()
    if len({ref.id for ref in request.stories}) != len(request.stories):
        invalid('不能重复选择同一故事')
    rows = [studio.store.studio_get('stories', ref.id, owner) for ref in request.stories]
    first = rows[0]
    for row, ref in zip(rows, request.stories):
        if row['revision'] != ref.revision:
            raise DomainError('stale_revision', '故事已更新，请刷新分享选择', 409)
        if (row['world_id'], row['world_revision'], row['world_content']) != (first['world_id'], first['world_revision'], first['world_content']):
            invalid('同一内容包的故事必须固定同一世界修订')
        if row.get('test_report', {}).get('status') != 'passed' or row['test_report'].get('revision') != row['revision']:
            raise DomainError('story_not_tested', '分享前请先通过当前故事修订的测试', 409)
        if any(j.get('story_id') == row['id'] and j['status'] in ACTIVE for j in studio.store.jobs.values()):
            raise DomainError('story_busy', '故事仍在测试，暂时不能制作快照', 409)
    world = deepcopy(first['world_content'])
    files, assets, mapping, omissions = {}, [], {}, []
    for character in world['characters']:
        aid = character.get('avatar_id')
        if not aid:
            continue
        if not request.include_avatars:
            character['avatar_id'] = None
            omissions.append('2D presentation omitted: ' + character['name'])
            continue
        if aid not in mapping:
            if len(assets) >= 4:
                invalid('一个内容包最多包含4份2D资源；可分包或取消打包形象')
            group = {name: avatars.asset(aid, owner, name).read_bytes() for name in RENDER_FILES}
            validate_render(group)
            sha = digest({name: hashlib.sha256(value).hexdigest() for name, value in group.items()})
            key = 'asset_' + sha[:24]
            mapping[aid] = key
            if not any(a['id'] == key for a in assets):
                assets.append({'id': key, 'name': character['name'], 'digest': sha})
                files.update({f'assets/{key}/{name}': value for name, value in group.items()})
        character['avatar_id'] = mapping[aid]
    stories = [{'key': f'story_{i+1}', 'content': deepcopy(row['content']), 'origin': deepcopy(row.get('origin')),
                'source_revision': row['revision'], 'test_summary': {'status': 'passed', 'mode': row['test_report'].get('mode', 'unknown'),
                    'steps': len(row['test_report'].get('steps', [])), 'advisory_only': True}} for i, row in enumerate(rows)]
    source_world = studio.store.studio_get('worlds', first['world_id'], owner)
    payload = {'world': world, 'world_origin': deepcopy(source_world.get('origin')), 'stories': stories}
    files['content.json'] = canonical(payload)
    manifest = PackageManifest(metadata=request.metadata,
        engine_minimum='0.19.0' if 'action_modules' in world else '0.16.0' if 'check_engine' in world else '0.12.0',
        files=[FileEntry(path=name, sha256=hashlib.sha256(value).hexdigest(), bytes=len(value)) for name, value in sorted(files.items())],
        assets=assets, capabilities=capabilities(world, stories, assets), omissions=omissions).model_dump()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in sorted({**files, 'manifest.json': canonical(manifest)}.items()):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0));entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, value)
    raw = output.getvalue()
    parsed = read_package(raw)
    sha = parsed['sha256'];pid = 'package_' + digest({'owner': owner, 'sha': sha})[:24]
    if pid in studio.store.publications:
        return studio.store.studio_get('publications', pid, owner)
    if any(p['owner'] == owner and p['metadata']['slug'] == request.metadata.slug and p['metadata']['release'] == request.metadata.release
           for p in studio.store.publications.values()):
        raise DomainError('release_exists', '这个作品版本已经制作过；修改内容请使用新的版本号', 409)
    record = {'id': pid, 'owner': owner, 'revision': 1, 'visibility': 'private', 'sha256': sha, 'created_at': time.time(),
              'metadata': manifest['metadata'], 'capabilities': manifest['capabilities'], 'assets': assets, 'omissions': omissions,
              'stories': [{'key': s['key'], 'title': s['content']['title'], 'language': s['content'].get('content_language') or world.get('content_language', 'zh-CN'),
                           'preset': s['content'].get('creation_preset') or world.get('creation_preset', 'adventure')} for s in stories],
              'action_modules': [{key: binding[key] for key in ('id', 'engine', 'version')}
                               for binding in world.get('action_modules', [])],
            'genre': world['genre'], 'locations': len(world['locations']), 'characters': len(world['characters']),
              'languages': sorted({s['content'].get('content_language') or world.get('content_language', 'zh-CN') for s in stories})}
    write_file(package_path(studio.store, sha), raw)
    return studio.store.studio_save('publications', record)


def visible_package(store, pid, viewer=None):
    record = store.publications.get(pid)
    if not record or (record['owner'] != viewer and record['visibility'] not in {'listed', 'unlisted'}):
        raise DomainError('not_found', '没有找到可用的分享包', 404)
    return record


def set_visibility(store, owner, pid, request):
    record = store.studio_get('publications', pid, owner)
    if record['revision'] != request.expected_revision:
        raise DomainError('stale_revision', '分享状态已更新，请刷新后再试', 409)
    value = {**deepcopy(record), 'visibility': request.visibility, 'revision': record['revision'] + 1}
    return store.studio_save('publications', value)


def install_package(studio, owner, raw, request, *, source_id=None):
    parsed = read_package(raw);sha = parsed['sha256'];payload = parsed['payload'];manifest = parsed['manifest']
    keys = [s['key'] for s in payload['stories']] if request.story_keys is None else request.story_keys
    if not keys or len(keys) != len(set(keys)) or set(keys) - {s['key'] for s in payload['stories']}:
        invalid('请至少选择一篇包内故事，不能重复或使用未知key')
    rows = [s for s in payload['stories'] if s['key'] in keys]
    batch = 'package_install_' + digest({'owner': owner, 'sha': sha})[:24]
    wid = 'world_' + batch[16:]
    ids = {s['key']: 'story_' + digest({'batch': batch, 'key': s['key']})[:24] for s in rows}
    jids = {key: 'packtest_' + sid[6:] for key, sid in ids.items()}
    new = [s for s in rows if jids[s['key']] not in studio.store.jobs]
    if not new:
        return studio.store.studio_get('jobs', jids[rows[0]['key']], owner)
    studio.require_capacity(owner, batch)
    # Extending a partial installation must not attach new stories to an edited
    # world under its old revision number. The original pinned snapshot stays v1.
    created = time.time();items = [];world = deepcopy(payload['world'])
    for asset in manifest['assets']:
        aid = 'avatar_' + digest({'owner': owner, 'asset': asset['digest']})[:24]
        for character in world['characters']:
            if character.get('avatar_id') == asset['id']:
                character['avatar_id'] = aid
        if aid not in studio.store.avatars:
            items.append(('avatars', {'id': aid, 'owner': owner, 'state': 'ready', 'stage': 'ready', 'progress': 100,
                'created_at': created, 'name': asset['name'], 'description': asset['name'], 'asset_digest': asset['digest'],
                'character_id': 'char_' + asset['digest'][:16]}))
    pack_origin = {'metadata': deepcopy(manifest['metadata']), 'sha256': sha, 'omissions': manifest['omissions'],
                   'capabilities': manifest['capabilities'], 'source_id': source_id}
    if wid not in studio.store.worlds:
        items.append(('worlds', {'id': wid, 'owner': owner, 'revision': 1, 'content': world,
            'created_at': created, 'brief': manifest['metadata']['summary'], 'origin': {'package': pack_origin, 'upstream': payload['world_origin']}}))
    for row in new:
        sid, jid = ids[row['key']], jids[row['key']]
        origin = deepcopy(row['origin'])
        origin = origin if isinstance(origin, dict) else {'upstream': origin}
        origin = {**origin, 'package': {**pack_origin, 'story_key': row['key'], 'source_revision': row['source_revision']}}
        story = {'id': sid, 'owner': owner, 'revision': 1, 'world_id': wid, 'world_revision': 1, 'world_content': deepcopy(world),
            'content': deepcopy(row['content']), 'created_at': created, 'origin': origin,
            'brief': manifest['metadata']['summary'], 'test_report': {'status': 'pending'}}
        job = {'id': jid, 'owner': owner, 'kind': 'package', 'batch_id': batch, 'package_digest': sha,
            'world_id': wid, 'story_id': sid, 'story_revision': 1, 'world_snapshot': None, 'prompt': '', 'story_prompt': '',
            'status': 'queued', 'created_at': created, 'checks': [], 'steps': [], 'error': None}
        items += [('stories', story), ('jobs', job)]
    # Leave margin beneath the journal's 8 MiB frame cap before any publication.
    if len(canonical(items)) > 7 * 1024 * 1024:
        invalid('安装快照超过日志批次限制，请选择较少故事')
    write_file(package_path(studio.store, sha), raw)
    for asset in manifest['assets']:
        folder = studio.store.journal.root / 'package-assets' / asset['digest']
        for name in RENDER_FILES:
            write_file(folder / name, parsed['files'][f"assets/{asset['id']}/{name}"])
        write_file(folder / 'profile.json', canonical({'character_id': 'char_' + asset['digest'][:16]}))
    studio.store.studio_save_batch(items)
    for row in new:
        studio.start(jids[row['key']])
    return studio.store.studio_get('jobs', jids[rows[0]['key']], owner)
