"""Portable, replay-verified campaign backups. Restore is a single journal transaction."""
import json
import re
import time
from copy import deepcopy

from .contracts import DomainError
from .journal import canonical, digest
from .players import commit_perspectives, human_players, player_for
from .world import apply_events, initial_state, project

MAX_BACKUP = 6_000_000
VERSION = 'rpw-campaign-1'


def export_campaign(store, cid, owner):
    campaign = store.campaign(cid, owner)
    body = {'format': VERSION, 'campaign': {k: deepcopy(campaign[k]) for k in ('id', 'template', 'player_name', 'main_branch', 'created_at')},
            'branches': [{k: deepcopy(b[k]) for k in ('id', 'title', 'parent_id', 'fork_version', 'commits')}
                         for b in store.branches.values() if b['campaign_id'] == cid]}
    body['sha256'] = digest(body)
    if len(canonical(body)) > MAX_BACKUP:
        raise DomainError('backup_limit', '这份冒险超过浏览器备份上限，请使用部署目录备份', 422)
    return body


def validate_backup(raw):
    try:
        if len(raw) > MAX_BACKUP:
            raise ValueError('Backup too large')
        value = json.loads(raw)
        if set(value) != {'format', 'campaign', 'branches', 'sha256'} or value['format'] != VERSION:
            raise ValueError('Unsupported backup')
        checksum = value.pop('sha256')
        if digest(value) != checksum:
            raise ValueError('Checksum mismatch')
        c = value['campaign']; rows = value['branches']
        if not isinstance(c['player_name'], str) or not 1 <= len(c['player_name']) <= 32:
            raise ValueError('Invalid player')
        if not 1 <= len(rows) <= 32:
            raise ValueError('Branch limit')
        if any(not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', r['id']) for r in rows):
            raise ValueError('Invalid branch identifier')
        if len({r['id'] for r in rows}) != len(rows):
            raise ValueError('Duplicate branches')
        root = initial_state(c['template'], c['player_name'])
        project(root)
        built = {}; pending = deepcopy(rows); count = 0
        while pending:
            progress = False
            for row in list(pending):
                parent = row['parent_id']; fork = row['fork_version']
                if parent is not None and parent not in built:
                    continue
                if not isinstance(row['title'], str) or not 1 <= len(row['title']) <= 100:
                    raise ValueError('Invalid title')
                if parent is None:
                    if row['id'] != c['main_branch'] or fork != 0:
                        raise ValueError('Invalid root branch')
                    base = deepcopy(root)
                else:
                    p = built[parent]
                    if not isinstance(fork, int) or not p['fork_version'] <= fork <= p['state']['version']:
                        raise ValueError('Invalid fork version')
                    inherited = [x for x in p['commits'] if x['version'] <= fork]
                    if row['commits'][:len(inherited)] != inherited:
                        raise ValueError('Fork history differs from parent')
                    base = deepcopy(p['base_state'])
                    for commit in inherited:
                        if commit['version'] > p['fork_version']:
                            base = apply_events(base, commit['events'], commit['version'])
                state = deepcopy(base); previous = 0
                for commit in row['commits']:
                    count += 1
                    if count > 3000 or commit['version'] != previous + 1 or len(commit['events']) > 200:
                        raise ValueError('Invalid commit sequence or limit')
                    previous = commit['version']
                    # Require all player history fields before publishing a restored save.
                    for key in ('id', 'action_id', 'segments', 'effects', 'suggestions', 'roll', 'player_text', 'mode', 'game_time_s'):
                        if key not in commit:
                            raise ValueError('Incomplete history')
                    if any(not isinstance(s.get('text'), str) for s in commit['segments']):
                        raise ValueError('Invalid narrative')
                    if (not isinstance(commit['player_text'], str) or commit['mode'] not in {'act', 'say', 'wait', 'ooc'}
                            or any(not isinstance(commit[k], list) or any(not isinstance(t, str) for t in commit[k])
                                   for k in ('effects', 'suggestions'))):
                        raise ValueError('Invalid history')
                    if commit['version'] > fork:
                        before = state
                        state = apply_events(state, commit['events'], commit['version'])
                        if digest(state) != commit['state_hash']:
                            raise ValueError('Replay hash mismatch')
                        if len(human_players(state)) > 1:
                            actor = player_for(before, commit['actor_id'])
                            expected = commit_perspectives(before, state, {'actor_id': actor}, commit)
                            if commit['primary_actor_id'] != state['player'] or commit['perspectives'] != expected:
                                raise ValueError('Invalid character perspectives')
                        elif any(k in commit for k in ('perspectives', 'primary_actor_id', 'actor_id')):
                            raise ValueError('Unexpected character perspectives')
                for actor in human_players(state):
                    project(state, actor)
                built[row['id']] = {**row, 'base_state': base, 'state': state}
                pending.remove(row); progress = True
            if not progress:
                raise ValueError('Missing parent or cycle')
        if c['main_branch'] not in built:
            raise ValueError('Missing main branch')
        return value, checksum, built
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, RuntimeError, RecursionError, DomainError) as exc:
        raise DomainError('invalid_backup', '备份格式、校验和或事件回放不一致，原有存档未改变', 422) from exc


def preview_backup(store, owner, raw):
    value, checksum, branches = validate_backup(raw)
    avatar_ids = {a.get('avatar_id') for b in branches.values() for a in b['state']['actors'].values() if a.get('avatar_id')}
    missing = [aid for aid in avatar_ids if aid not in store.avatars or store.avatars[aid]['owner'] != owner]
    return {'title': value['campaign']['template']['title'], 'player_name': value['campaign']['player_name'],
            'branches': [{'title': b['title'], 'version': b['state']['version']} for b in branches.values()],
            'sha256': checksum, 'missing_avatars': sorted(missing),
            'includes': '全部故事分支、规则状态、物品、人物知识、手记、世界变化与已提交对白'}


def restore_campaign(store, owner, raw):
    value, checksum, branches = validate_backup(raw)
    key = digest([owner, checksum])[:24]
    cid = 'campaign_' + key
    if cid in store.campaigns:
        campaign = store.campaign(cid, owner)
        return {'id': cid, 'branch_id': campaign['main_branch'], 'existing': True}
    mapping = {bid: 'branch_' + digest([key, bid])[:24] for bid in branches}
    original = value['campaign']
    campaign = {**original, 'id': cid, 'owner': owner, 'main_branch': mapping[original['main_branch']],
                'created_at': time.time(), 'restored_from': checksum}
    records = [{**b, 'id': mapping[b['id']], 'campaign_id': cid,
                'parent_id': mapping.get(b['parent_id'])} for b in branches.values()]
    frame = {'kind': 'campaign.restored', 'campaign': campaign, 'branches': records}
    if len(canonical(frame)) > 7_500_000:
        raise DomainError('backup_limit', '还原后的存档超过单次写入上限', 422)
    store.record(frame)
    return {'id': cid, 'branch_id': campaign['main_branch'], 'existing': False}
