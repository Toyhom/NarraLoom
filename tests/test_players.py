"""Independent PCs: authorization, observations, canonical mechanics and recovery."""
import asyncio
import json
import os
from copy import deepcopy

import pytest
import test_rulepacks
import test_state_rules

from roleplay_world.backups import export_campaign, restore_campaign
from roleplay_world.continuity import carry_world
from roleplay_world.contracts import ActionCommand, DomainError, TurnPlan
from roleplay_world.journal import digest
from roleplay_world.memory import retrieve
from roleplay_world.planning import choices, validate_plan
from roleplay_world.players import followers, human_players
from roleplay_world.rooms import RoomAction, RoomControl, RoomCreate, RoomJoin, Rooms
from roleplay_world.runtime import Runtime
from roleplay_world.store import Store
from roleplay_world.world import initial_state, present, project


@pytest.fixture
def game_template():
    return test_rulepacks.game_template.__wrapped__()


class Gateway:
    def __init__(self):
        self.calls = []

    async def generate(self, role, prompt, data, schema, *args, **kwargs):
        self.calls.append((role, deepcopy(data)))
        if role == 'game_master':
            speakers = [a['id'] for a in data['player_view']['present_actors'] if a['control'] == 'npc'
                        and (not data.get('private_recipient') or a['id'] == data['private_recipient'])][:1]
            return schema.model_validate({'intent': '交谈', 'time_cost_s': 30, 'speakers': speakers})
        if role == 'character_actor':
            return schema.model_validate({'text': '我愿意同行。', 'reaction': 'accept' if data.get('invitation') else 'none'})
        if role == 'narrator':
            return schema.model_validate({'text': '只属于行动者视角的叙事。', 'suggestions': ['行动者的私人建议']})
        raise AssertionError(role)


class Table:
    def __init__(self, root, template):
        self.store = Store(root)
        self.c = self.store.create_campaign('host', template, '房主角色')
        self.bid = self.c['main_branch']
        self.rooms = Rooms(self.store)
        self.rid = self.rooms.create('host', RoomCreate(campaign_id=self.c['id'], branch_id=self.bid,
            mode='independent_characters', name='房主'))['id']
        self.gateway = Gateway()

    @property
    def state(self):
        return self.store.branches[self.bid]['state']

    def view(self, owner='host'):
        return self.rooms.view(self.rid, owner)

    def join(self, owner='guest', create=True):
        return self.rooms.join(owner, RoomJoin(code=self.view()['invite_code'], name=owner+'角色',
                                              role='寻找旧友的旅人', create_character=create))

    def control(self, operation, member=None, actor=None, owner='host'):
        return self.rooms.control(self.rid, owner, RoomControl(expected_revision=self.view(owner)['revision'],
                                   operation=operation, member_id=member, actor_id=actor))

    def turn(self, owner):
        if self.view()['turn'] != self.view()['me']:
            self.control('reclaim')
        if owner != 'host':
            self.control('pass', self.view(owner)['me'])

    def act(self, owner='host', text='选择行动', **extra):
        self.turn(owner)
        command = ActionCommand(action_id='action_'+str(len(self.store.actions)), expected_world_version=self.state['version'],
                                text=text, **extra)
        payload = RoomAction(expected_revision=self.view(owner)['revision'], command=command)
        action, fresh = self.rooms.accept(self.rid, owner, payload)
        assert fresh
        asyncio.run(Runtime(self.store, self.gateway).run(action['id']))
        assert action['status'] == 'committed', action.get('error')
        return action, payload


def test_independent_join_is_atomic_bounded_and_never_clones_acquired_gear(tmp_path, game_template):
    table = Table(tmp_path, game_template)
    table.act(selected_operation={'kind': 'buy', 'target_id': 'shop', 'item_id': 'potion'})
    before = len(table.store.journal.records)
    guest = table.join(); pc = guest['state']['player_actor_id']; host = table.state['player']
    assert len(table.store.journal.records) == before+1
    assert table.store.journal.records[-1]['body']['kind'] == 'room.member_joined'
    assert table.state['version'] == 2 and len(human_players(table.state)) == 2
    assert table.state['actor_states'][pc]['resources']['coins'] == 20
    assert table.state['actor_states'][host]['resources']['coins'] == 17
    inventory = guest['state']['inventory']
    assert sum(i['quantity'] for i in inventory if i['name'] == '恢复药') == 2
    assert 'item_start' not in [i['id'] for i in inventory]
    assert all(i['id'].startswith('gear_'+pc) for i in inventory)
    snapshot = digest(table.state)
    assert table.join()['state']['player_actor_id'] == pc
    assert digest(table.state) == snapshot
    for i in range(4):
        table.join('guest'+str(i))
    with pytest.raises(DomainError, match='6位'):
        table.join('overflow')
    table.control('kick', table.view('guest')['me'])
    assert table.join()['state']['player_actor_id'] == pc
    assert len(human_players(table.state)) == 6
    table.store.close()


def test_guest_rules_location_equipment_spending_and_followers_are_independent(tmp_path, game_template):
    table = Table(tmp_path, game_template); pc = table.join()['state']['player_actor_id']; host = table.state['player']
    host_before = deepcopy(table.state['actor_states'][host])
    sword = next(i['id'] for i in table.state['items'].values() if i['holder_id'] == pc and i.get('kind') == 'weapon')
    table.act('guest', selected_operation={'kind': 'equip', 'target_id': pc, 'item_id': sword})
    table.act('guest', selected_operation={'kind': 'buy', 'target_id': 'shop', 'item_id': 'potion', 'quantity': 2})
    table.act('guest', selected_operation={'kind': 'recruit', 'target_id': 'npc_2'})
    assert followers(table.state, pc) == ['npc_2'] and followers(table.state, host) == []
    table.act('guest', selected_operation={'kind': 'move', 'target_id': 'loc_1'})
    assert table.state['actor_states'][pc]['location_id'] == table.state['actor_states']['npc_2']['location_id'] == 'loc_1'
    assert table.state['actor_states'][pc]['resources']['coins'] == 14
    assert table.state['actor_states'][pc]['equipment']['weapon'] == sword
    assert table.state['actor_states'][host] == host_before
    assert any('购买恢复药' in t for c in table.view()['state']['history'] for t in c['effects'])
    assert retrieve(table.state, host, '购买恢复药')
    assert not any(op['kind'] == 'dismiss' for op in choices(table.state, 'act', host)[0])
    with pytest.raises(DomainError):
        validate_plan(table.state, {'mode': 'act', 'actor_id': host}, TurnPlan(intent='越权', operations=[{'kind': 'equip', 'target_id': pc, 'item_id': sword}]))
    assert '只属于行动者' not in json.dumps(table.view()['state']['history'], ensure_ascii=False)
    assert any('前往' in t for c in table.view()['state']['history'] for t in c['effects'])
    table.store.close()


def test_private_notes_whisper_histories_receipts_and_late_arrival(tmp_path, template):
    table = Table(tmp_path, template)
    old, old_payload = table.act(mode='ooc', text='加入前的私有记录', note_record={'id': 'early', 'text': '紫色茶杯暗号'})
    guest = table.join(); pc = guest['state']['player_actor_id']; host = table.state['player']
    assert all(c['action_id'] != old['id'] for c in guest['state']['history'])
    assert table.rooms.receipt(table.rid, 'guest', old)['result'] is None
    assert table.rooms.accept(table.rid, 'host', old_payload)[1] is False
    note, _ = table.act('guest', mode='ooc', text='密记', note_record={'id': 'private', 'text': '蓝色雪人标记'})
    assert table.rooms.receipt(table.rid, 'host', note)['result'] is None
    assert '蓝色雪人' not in json.dumps(table.view()['state'], ensure_ascii=False)
    with pytest.raises(DomainError, match='不能修改'):
        from roleplay_world.memory import note_event
        note_event(table.state, {'action_id': 'overwrite', 'mode': 'ooc', 'note_record': note['command']['note_record']})
    third = table.join('third'); other = third['state']['player_actor_id']
    table.gateway.calls.clear()
    whisper, _ = table.act('guest', mode='say', text='白色羽毛私人约定', whisper_to=host)
    assert table.gateway.calls == []  # No model may supply a human's reply.
    assert '白色羽毛' in json.dumps(table.view()['state']['history'], ensure_ascii=False)
    assert '白色羽毛' not in json.dumps(table.view('third')['state'], ensure_ascii=False)
    assert table.rooms.receipt(table.rid, 'third', whisper)['result'] is None
    assert retrieve(table.state, host, '白色羽毛')
    for actor in table.state['actors']:
        if actor not in {host, pc}:
            assert not retrieve(table.state, actor, '白色羽毛')
    assert other not in whisper['result']['perspectives']
    table.store.close()


def test_same_scene_speech_and_npc_private_context_without_remote_history(tmp_path, template):
    table = Table(tmp_path, template); pc = table.join()['state']['player_actor_id']; table.join('third')
    host = table.state['player']; npc = next(a for a in present(table.state, pc) if table.state['actors'][a]['control'] == 'npc')
    table.act('guest', mode='say', text='向同桌朋友分享一则传闻')
    assert any(s.get('speaker_id') == pc for c in table.view()['state']['history'] for s in c['segments'])
    table.gateway.calls.clear()
    secret, _ = table.act('guest', mode='say', text='橙色灯塔私下询问', whisper_to=npc)
    calls = [c for role,c in table.gateway.calls if role == 'character_actor']
    assert len(calls) == 1 and calls[0]['character']['id'] == npc
    assert calls[0]['player_name'] == 'guest角色'
    assert table.rooms.receipt(table.rid, 'host', secret)['result'] is None
    assert not retrieve(table.state, host, '橙色灯塔')
    destination = project(table.state, pc)['exits'][0]['id']
    table.act('guest', selected_operation={'kind': 'move', 'target_id': destination})
    remote, _ = table.act(mode='say', text='客人离开后才说的翠玉暗语')
    assert table.rooms.receipt(table.rid, 'guest', remote)['result'] is None
    assert not retrieve(table.state, pc, '翠玉暗语')
    table.act('guest', selected_operation={'kind': 'move', 'target_id': table.state['actor_states'][host]['location_id']})
    assert '翠玉暗语' not in json.dumps(table.view('guest')['state'], ensure_ascii=False)
    table.store.close()


def test_investigation_is_personal_and_no_human_speaker_can_be_planned(tmp_path, game_template):
    table = Table(tmp_path, game_template); pc = table.join()['state']['player_actor_id']; host = table.state['player']
    clue = next(f for f in table.state['facts'].values() if f.get('discoverable_at'))
    table.act('guest', selected_operation={'kind': 'move', 'target_id': clue['discoverable_at'][0]})
    op = next(o for o in choices(table.state, 'act', pc)[0] if o['kind'] == 'reveal')
    table.act('guest', selected_operation=op)
    assert op['target_id'] in table.state['knowledge'][pc] and op['target_id'] not in table.state['knowledge'][host]
    assert pc not in choices(table.state, 'say', host)[1]
    with pytest.raises(DomainError, match='NPC'):
        validate_plan(table.state, {'mode': 'say'}, TurnPlan(intent='越权', speakers=[pc]))
    table.store.close()


def test_reassignment_revokes_all_old_binding_snapshots_and_reopen_cannot_replenish(tmp_path, template):
    table = Table(tmp_path, template); guest = table.join(); pc = guest['state']['player_actor_id']
    table.control('kick', guest['me'])
    new = table.join('new', create=False)
    assert new['state'] is None
    table.control('assign', new['me'], pc)
    assert table.view('new')['state']['player_actor_id'] == pc
    old = table.join()
    assert old['state'] is None and len(human_players(table.state)) == 2
    with pytest.raises(DomainError, match='分配'):
        table.control('pass', old['me'])
    table.control('close')
    table.rid = table.rooms.create('host', RoomCreate(campaign_id=table.c['id'], branch_id=table.bid,
                               mode='independent_characters'))['id']
    assert table.join()['state'] is None
    assert table.join('new')['state']['player_actor_id'] == pc
    assert len(human_players(table.state)) == 2
    table.store.close()


def test_fork_before_join_creates_new_branch_role_without_reusing_future_binding(tmp_path, template):
    table = Table(tmp_path, template); guest = table.join(); original = guest['state']['player_actor_id']
    fork = table.store.fork(table.c['id'], table.bid, 'host', 0, '加入之前')
    room = table.rooms.create('host', RoomCreate(campaign_id=table.c['id'], branch_id=fork['id'], mode='independent_characters'))
    again = table.rooms.join('guest', RoomJoin(code=room['invite_code'], name='另一个旅人'))
    assert again['state']['player_actor_id'] != original
    assert len(human_players(fork['state'])) == len(human_players(table.state)) == 2
    assert original not in fork['state']['actors']
    table.store.close()


def test_pending_join_spoofed_actor_stale_actions_and_receipt_dedup(tmp_path, template):
    table = Table(tmp_path, template); guest = table.join(); pc = guest['state']['player_actor_id']
    with pytest.raises(DomainError, match='其他参与者'):
        table.store.accept(table.c['id'], table.bid, 'host', ActionCommand(action_id='spoof', expected_world_version=1, actor_id=pc, text='越权'))
    table.turn('guest')
    command = ActionCommand(action_id='pending', expected_world_version=1, mode='ooc', text='记事', note_record={'id': 'n', 'text': '将要记录'})
    payload = RoomAction(expected_revision=table.view('guest')['revision'], command=command)
    action, _ = table.rooms.accept(table.rid, 'guest', payload)
    with pytest.raises(DomainError, match='当前行动'):
        table.join('third')
    with pytest.raises(DomainError, match='等待或取消'):
        table.control('kick', guest['me'])
    Runtime(table.store, table.gateway).cancel(action['id'], 'host')
    assert table.state['version'] == 1 and 'n' not in table.state.get('notes', {})
    assert table.rooms.accept(table.rid, 'guest', payload)[1] is False
    table.act('guest', mode='ooc', note_record={'id': 'n', 'text': '记录成功'})
    with pytest.raises(DomainError, match='世界已有变化'):
        table.rooms.accept(table.rid, 'guest', RoomAction(expected_revision=table.view('guest')['revision'],
                           command=command.model_copy(update={'action_id': 'stale'})))
    table.store.close()


def test_atomic_join_fsync_uncertainty_restart_fork_backup_and_explicit_rebind(tmp_path, template, monkeypatch):
    table = Table(tmp_path/'source', template); original = os.fsync
    def fail(fd):
        if fd == table.store.journal.fd:
            raise OSError('injected join write uncertainty')
        return original(fd)
    monkeypatch.setattr(os, 'fsync', fail)
    with pytest.raises(DomainError, match='待确认'):
        table.join()
    assert len(human_players(table.state)) == 1 and len(table.store.rooms[table.rid]['members']) == 1
    table.store.close(); monkeypatch.setattr(os, 'fsync', original)
    table.store = Store(tmp_path/'source'); table.rooms = Rooms(table.store)
    assert len(human_players(table.state)) == 2 and len(table.store.rooms[table.rid]['members']) == 2
    pc = table.join()['state']['player_actor_id']
    table.act('guest', mode='ooc', note_record={'id': 'secret', 'text': '重启和备份保留的私人约定'})
    table.store.fork(table.c['id'], table.bid, 'host', table.state['version'], '另一条路')
    raw = json.dumps(export_campaign(table.store, table.c['id'], 'host'))
    target = Store(tmp_path/'target'); restored = restore_campaign(target, 'new_host', raw)
    assert {b['title']: digest(b['state']) for b in target.branches.values()} == {b['title']: digest(b['state']) for b in table.store.branches.values()}
    rooms = Rooms(target)
    r = rooms.create('new_host', RoomCreate(campaign_id=restored['id'], branch_id=restored['branch_id'], mode='independent_characters'))
    seat = rooms.join('new_guest', RoomJoin(code=r['invite_code'], name='新浏览器', create_character=False))
    assert seat['state'] is None
    rooms.control(r['id'], 'new_host', RoomControl(expected_revision=seat['revision'], operation='assign', member_id=seat['me'], actor_id=pc))
    assert rooms.view(r['id'], 'new_guest')['state']['notes'][0]['text'] == '重启和备份保留的私人约定'
    target.close(); table.store.close()


@pytest.mark.parametrize('corrupt', ['missing', 'leak', 'wrong_actor'])
def test_backup_rejects_invalid_or_rewritten_perspectives(tmp_path, template, corrupt):
    table = Table(tmp_path, template); pc = table.join()['state']['player_actor_id']
    body = export_campaign(table.store, table.c['id'], 'host'); body.pop('sha256')
    commit = body['branches'][0]['commits'][0]
    if corrupt == 'missing':
        commit.pop('perspectives')
    elif corrupt == 'leak':
        commit['perspectives'][pc]['player_text'] = '伪造其他玩家的私密行动'
    else:
        commit['actor_id'] = 'absent'
    body['sha256'] = digest(body)
    count = len(table.store.journal.records)
    with pytest.raises(DomainError):
        restore_campaign(table.store, 'new', json.dumps(body))
    assert len(table.store.journal.records) == count
    table.store.close()


def test_restored_room_projection_order_survives_actual_journal_reopen(tmp_path, game_template):
    table = Table(tmp_path/'source', game_template); pc = table.join()['state']['player_actor_id']; table.join('third')
    table.act('guest', selected_operation={'kind': 'buy', 'target_id': 'shop', 'item_id': 'potion'})
    raw = json.dumps(export_campaign(table.store, table.c['id'], 'host'))
    target = Store(tmp_path/'restored'); restored = restore_campaign(target, 'restored_host', raw); rooms = Rooms(target)
    room = rooms.create('restored_host', RoomCreate(campaign_id=restored['id'], branch_id=restored['branch_id'], mode='independent_characters'))
    guest = rooms.join('restored_guest', RoomJoin(code=room['invite_code'], name='恢复席位', create_character=False))
    rooms.control(room['id'], 'restored_host', RoomControl(expected_revision=guest['revision'], operation='assign', member_id=guest['me'], actor_id=pc))
    before = [rooms.view(room['id'], owner) for owner in ('restored_host', 'restored_guest')]
    target.close(); target = Store(tmp_path/'restored'); rooms = Rooms(target)
    for index, owner in enumerate(('restored_host', 'restored_guest')):
        after = rooms.view(room['id'], owner)
        differences = [key for key in after if key != 'state' and after[key] != before[index][key]]
        differences += ['state.'+key for key in after['state'] if after['state'][key] != before[index]['state'][key]]
        assert not differences, differences
    target.close(); table.store.close()


def test_new_character_after_restoring_snapshot_has_stable_knowledge_hash(tmp_path, game_template):
    game_template['facts'].extend([{'id': fid, 'value': fid, 'visibility': {'kind': 'public'}}
                                   for fid in ('public_zeta', 'public_alpha')])
    table = Table(tmp_path/'source', game_template); table.join()
    raw = json.dumps(export_campaign(table.store, table.c['id'], 'host'))
    target = Store(tmp_path/'restored'); restored = restore_campaign(target, 'restored_host', raw); rooms = Rooms(target)
    room = rooms.create('restored_host', RoomCreate(campaign_id=restored['id'], branch_id=restored['branch_id'], mode='independent_characters'))
    guest = rooms.join('new_person', RoomJoin(code=room['invite_code'], name='新加入'))
    pc = guest['state']['player_actor_id']; state = target.branches[restored['branch_id']]['state']
    expected = digest(state)
    assert state['knowledge'][pc] == sorted(state['knowledge'][pc])
    target.close(); target = Store(tmp_path/'restored')
    assert digest(target.branches[restored['branch_id']]['state']) == expected
    assert Rooms(target).view(room['id'], 'new_person') == guest
    target.close(); table.store.close()


def test_new_chapter_keeps_guest_location_followers_and_private_memory(tmp_path, game_template):
    game_template['world_ref'] = {'id': 'w', 'revision': 1}
    table = Table(tmp_path, game_template); pc = table.join()['state']['player_actor_id']
    table.act('guest', selected_operation={'kind': 'recruit', 'target_id': 'npc_2'})
    table.act('guest', selected_operation={'kind': 'move', 'target_id': 'loc_1'})
    table.act('guest', mode='ooc', note_record={'id': 'n', 'text': '只属于我的章节记录'})
    continued = carry_world(game_template, table.store.branches[table.bid], table.c, table.state['version'])
    fresh = initial_state(continued, '下一章房主')
    assert fresh['player'] == table.state['player']
    assert followers(fresh, pc) == ['npc_2']
    assert fresh['actor_states'][pc]['location_id'] == fresh['actor_states']['npc_2']['location_id'] == 'loc_1'
    assert project(fresh, pc)['notes'][0]['text'] == '只属于我的章节记录'
    assert not project(fresh)['notes']
    table.store.close()


def test_guest_state_action_keeps_literal_author_targets_and_private_effects(tmp_path):
    template = test_state_rules.compile_authored(test_state_rules.authored.__wrapped__())
    table = Table(tmp_path, template); pc = table.join()['state']['player_actor_id']; host = table.state['player']
    table.act('guest', selected_operation={'kind': 'state_action', 'target_id': 'study'})
    table.act('guest', selected_operation={'kind': 'state_action', 'target_id': 'study'})
    guest = table.view('guest')['state']; primary = table.view()['state']
    assert 'unlocked' not in [v['id'] for v in guest['custom_state']['variables']]
    assert 'hidden' not in [v['id'] for v in guest['custom_state']['variables']]
    assert next(v for v in primary['custom_state']['variables'] if v['id'] == 'unlocked')['value'] is True
    before = table.state['actor_states'][pc]['resources']['coins']
    host_before = table.state['actor_states'][host]['resources']['coins']
    table.act('guest', selected_operation={'kind': 'state_action', 'target_id': 'claim'})
    assert table.state['actor_states'][pc]['resources']['coins'] == before
    assert table.state['actor_states'][host]['resources']['coins'] == host_before + 3
    assert '幕后路线' not in json.dumps(guest, ensure_ascii=False)
    assert '星环密码' not in json.dumps(guest, ensure_ascii=False)
    assert '星环密码' in json.dumps(primary, ensure_ascii=False)
    table.store.close()
