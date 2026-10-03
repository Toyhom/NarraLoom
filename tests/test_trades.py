"""Consent, conservation and recovery across the real command/journal path."""
import asyncio
import json
from copy import deepcopy

import pytest
import test_rulepacks
from pydantic import ValidationError
from test_players import Table

from roleplay_world.backups import export_campaign, restore_campaign
from roleplay_world.contracts import ActionCommand, DomainError
from roleplay_world.journal import digest
from roleplay_world.memory import retrieve
from roleplay_world.rooms import RoomAction, Rooms
from roleplay_world.runtime import Runtime
from roleplay_world.store import Store
from roleplay_world.trades import resolve_trade
from roleplay_world.world import apply_events, project


@pytest.fixture
def game_template():
    return test_rulepacks.game_template.__wrapped__()


def prepare(tmp_path, template):
    table = Table(tmp_path, template)
    guest = table.join()['state']['player_actor_id']
    return table, table.state['player'], guest


def offer(table, recipient, owner='host', **fields):
    action, payload = table.act(owner, trade={'kind': 'propose', 'target_id': recipient, **fields})
    return action['result']['events'][0]['payload']['offer']['id'], action, payload


def reject_action(table, owner='host', **fields):
    table.turn(owner)
    before = digest(table.state)
    command = ActionCommand(action_id='invalid_'+str(len(table.store.actions)), expected_world_version=table.state['version'], text='失败交易', **fields)
    action, _ = table.rooms.accept(table.rid, owner, RoomAction(expected_revision=table.view(owner)['revision'], command=command))
    asyncio.run(Runtime(table.store, table.gateway).run(action['id']))
    assert action['status'] == 'failed'
    assert digest(table.state) == before
    return action


def test_atomic_partial_item_sale_requires_explicit_consent_and_no_model(tmp_path, game_template):
    table, host, guest = prepare(tmp_path, game_template)
    table.join('third')
    before = deepcopy(table.state)
    oid, proposed, payload = offer(table, guest, items=[{'item_id': 'gear_0', 'quantity': 1}], request_coins=4)
    assert table.state['items'] == before['items'] and table.state['actor_states'] == before['actor_states']
    assert table.rooms.receipt(table.rid, 'third', proposed)['result'] is None
    assert project(table.state, table.view('third')['state']['player_actor_id'])['trades'] == []
    assert table.rooms.accept(table.rid, 'host', payload)[1] is False
    accepted, repeated = table.act('guest', trade={'kind': 'accept', 'offer_id': oid})
    assert table.state['actor_states'][host]['resources']['coins'] == 24
    assert table.state['actor_states'][guest]['resources']['coins'] == 16
    assert table.state['items']['gear_0']['quantity'] == 1
    assert sum(i['quantity'] for i in table.state['items'].values() if i.get('catalog_id') == 'potion') == 6
    assert any(i['holder_id'] == guest and i['id'].startswith('tradeitem_') for i in table.state['items'].values())
    assert table.state['game_time_s'] == before['game_time_s'] and not table.gateway.calls
    assert retrieve(table.state, guest, '完成交易')
    third_history = table.rooms.receipt(table.rid, 'third', accepted)['result']
    assert third_history['effects'] == ['房主角色与guest角色完成了一次交易。']
    assert not third_history['segments']
    witness = table.view('third')['state']['player_actor_id']
    memories = retrieve(table.state, witness, '完成了一次交易')
    assert memories and all('金币' not in m['text'] and '恢复药' not in m['text'] for m in memories)
    assert table.rooms.accept(table.rid, 'guest', repeated)[1] is False
    table.store.close()


def test_counteroffer_barter_freezes_original_give_and_requires_new_acceptance(tmp_path, game_template):
    table, host, guest = prepare(tmp_path, game_template)
    guest_sword = next(i['id'] for i in table.state['items'].values() if i['holder_id'] == guest and i.get('kind') == 'weapon')
    table.act('guest', selected_operation={'kind': 'equip', 'target_id': guest, 'item_id': guest_sword})
    oid, _, _ = offer(table, guest, items=[{'item_id': 'gear_0', 'quantity': 2}], request_coins=5)
    counter, _ = table.act('guest', trade={'kind': 'counter', 'offer_id': oid, 'items': [{'item_id': guest_sword}], 'coins': 2})
    new_id = counter['result']['events'][0]['payload']['offer']['id']
    assert table.state['trades'][oid]['status'] == 'countered'
    assert table.state['items']['gear_0']['holder_id'] == host
    assert table.state['trades'][new_id]['receive']['items'][0]['quantity'] == 2
    reject_action(table, 'guest', trade={'kind': 'accept', 'offer_id': new_id})
    table.act(trade={'kind': 'accept', 'offer_id': new_id})
    assert table.state['items']['gear_0']['holder_id'] == guest
    assert table.state['items'][guest_sword]['holder_id'] == host
    assert table.state['actor_states'][guest]['equipment']['weapon'] is None
    assert table.state['actor_states'][host]['resources']['coins'] == 22
    table.store.close()


def test_overlapping_quotes_spent_item_and_distance_cannot_partially_settle(tmp_path, game_template):
    table, host, guest = prepare(tmp_path, game_template)
    first, _, _ = offer(table, guest, items=[{'item_id': 'gear_0', 'quantity': 2}], request_coins=5)
    second, _, _ = offer(table, guest, items=[{'item_id': 'gear_0', 'quantity': 2}], request_coins=6)
    table.act('guest', trade={'kind': 'accept', 'offer_id': first})
    failed = reject_action(table, 'guest', trade={'kind': 'accept', 'offer_id': second})
    assert '数量不足' in failed['error']
    assert table.view('guest')['state']['trades'][0]['unavailable']
    table.act('guest', trade={'kind': 'decline', 'offer_id': second})
    gift, _, _ = offer(table, guest, coins=1)
    table.act('guest', selected_operation={'kind': 'move', 'target_id': 'loc_1'})
    assert '同一地点' in reject_action(table, 'guest', trade={'kind': 'accept', 'offer_id': gift})['error']
    table.act(trade={'kind': 'withdraw', 'offer_id': gift})
    assert table.state['actor_states'][host]['resources']['coins'] == 25
    table.store.close()


def test_invalid_authority_terms_mixed_commands_and_bounds(tmp_path, game_template):
    table, host, guest = prepare(tmp_path, game_template)
    third = table.join('third')['state']['player_actor_id']
    oid, _, _ = offer(table, guest, coins=2)
    attempts = [
        ('host', {'trade': {'kind': 'accept', 'offer_id': oid}}),
        ('guest', {'trade': {'kind': 'withdraw', 'offer_id': oid}}),
        ('third', {'trade': {'kind': 'counter', 'offer_id': oid, 'coins': 1}}),
        ('host', {'trade': {'kind': 'propose', 'target_id': host, 'coins': 1}}),
        ('host', {'trade': {'kind': 'propose', 'target_id': 'npc_2', 'coins': 1}}),
        ('host', {'trade': {'kind': 'propose', 'target_id': third, 'coins': 21}}),
        ('host', {'trade': {'kind': 'propose', 'target_id': guest, 'items': [{'item_id': 'gear_0'}, {'item_id': 'gear_0'}]}}),
        ('guest', {'trade': {'kind': 'accept', 'offer_id': oid, 'coins': 1}}),
        ('guest', {'trade': {'kind': 'accept', 'offer_id': oid}, 'mode': 'say'}),
        ('guest', {'trade': {'kind': 'accept', 'offer_id': oid}, 'note_record': {'id': 'mix', 'text': 'test'}}),
        ('guest', {'trade': {'kind': 'accept', 'offer_id': oid}, 'simulation_control': 'pause'}),
        ('guest', {'trade': {'kind': 'accept', 'offer_id': oid}, 'selected_operation': {'kind': 'move', 'target_id': 'loc_1'}}),
    ]
    for who, fields in attempts:
        reject_action(table, who, **fields)
    for value in (True, -1, 1.2, 1000000):
        with pytest.raises(ValidationError):
            ActionCommand(action_id='invalid', expected_world_version=1, text='交易', trade={'kind': 'propose', 'target_id': guest, 'coins': value})
    assert not table.gateway.calls
    table.store.close()


def test_pending_limit_replaces_one_on_counter_and_releases_on_close(tmp_path, game_template):
    table, _host, guest = prepare(tmp_path, game_template)
    ids = [offer(table, guest, coins=1)[0] for _ in range(12)]
    assert '已满' in reject_action(table, trade={'kind': 'propose', 'target_id': guest, 'coins': 1})['error']
    table.act('guest', trade={'kind': 'counter', 'offer_id': ids[0], 'coins': 2})
    assert sum(o['status'] == 'pending' for o in table.state['trades'].values()) == 12
    table.act(trade={'kind': 'withdraw', 'offer_id': ids[1]})
    offer(table, guest, coins=1)
    table.store.close()


def test_recorded_settlement_rejects_tampering_and_resource_overflow(tmp_path, game_template):
    table, host, guest = prepare(tmp_path, game_template)
    oid, _, _ = offer(table, guest, items=[{'item_id': 'gear_0'}], coins=2)
    command = {'action_id': 'closing', 'mode': 'act', 'actor_id': guest, 'trade': {'kind': 'accept', 'offer_id': oid}}
    events, _ = resolve_trade(table.state, command)
    for mutation in ('amount', 'audience', 'recipient'):
        altered = deepcopy(events)
        if mutation == 'amount':
            altered[0]['payload']['settlement'][0]['payload']['after'] += 1
        elif mutation == 'audience':
            altered[0]['visibility'] = {'kind': 'public'}
        else:
            altered[0]['payload']['actor_id'] = host
        with pytest.raises(DomainError):
            apply_events(table.state, altered, table.state['version']+1)
    limit_state = deepcopy(table.state)
    limit_state['actor_states'][guest]['resources']['coins'] = 999999
    with pytest.raises(DomainError, match='上限'):
        resolve_trade(limit_state, command)
    assert table.state['trades'][oid]['status'] == 'pending'
    table.store.close()


def test_fork_backup_replay_restart_preserve_pending_and_settled_quotes(tmp_path, game_template):
    table, _host, guest = prepare(tmp_path/'source', game_template)
    oid, _, _ = offer(table, guest, items=[{'item_id': 'gear_0'}], request_coins=3)
    pending_version = table.state['version']
    fork = table.store.fork(table.c['id'], table.bid, 'host', pending_version, '保留报价')
    _accepted, payload = table.act('guest', trade={'kind': 'accept', 'offer_id': oid})
    assert fork['state']['trades'][oid]['status'] == 'pending'
    before = {who: table.view(who) for who in ('host', 'guest')}
    snapshot = digest(table.state)
    backup = export_campaign(table.store, table.c['id'], 'host')
    restored = restore_campaign(table.store, 'new-owner', json.dumps(backup))
    restored_state = table.store.branches[restored['branch_id']]['state']
    assert digest(restored_state) == snapshot
    table.store.close()
    table.store = Store(tmp_path/'source'); table.rooms = Rooms(table.store)
    assert digest(table.state) == snapshot
    assert before == {who: table.view(who) for who in ('host', 'guest')}
    assert table.rooms.accept(table.rid, 'guest', payload)[1] is False
    table.store.close()


def test_cancelled_trade_never_moves_items_and_fsync_uncertainty_recovers(tmp_path, game_template, monkeypatch):
    import os

    table, host, guest = prepare(tmp_path, game_template)
    oid, _, _ = offer(table, guest, coins=2)
    table.turn('guest')
    def accept(aid):
        return table.rooms.accept(table.rid, 'guest', RoomAction(expected_revision=table.view('guest')['revision'],
            command=ActionCommand(action_id=aid, expected_world_version=table.state['version'], text='接受', trade={'kind': 'accept', 'offer_id': oid})))[0]
    cancelled = accept('cancelled_trade')
    runtime = Runtime(table.store, table.gateway)
    runtime.cancel(cancelled['id'], 'host')
    asyncio.run(runtime.run(cancelled['id']))
    assert table.state['trades'][oid]['status'] == 'pending'
    action = accept('uncertain_trade')
    events, text = resolve_trade(table.state, action['command'])
    real = os.fsync
    def uncertain(fd):
        real(fd)
        raise OSError('uncertain durability')
    monkeypatch.setattr(os, 'fsync', uncertain)
    with pytest.raises(DomainError, match="写入状态待确认"):
        table.store.commit(action['id'], events, [{'kind': 'note', 'text': text}], [], [], None)
    monkeypatch.setattr(os, 'fsync', real)
    table.store.close()
    table.store = Store(tmp_path); table.rooms = Rooms(table.store)
    assert table.state['trades'][oid]['status'] == 'accepted'
    assert table.state['actor_states'][host]['resources']['coins'] == 18
    assert table.state['actor_states'][guest]['resources']['coins'] == 22
    assert table.store.actions['uncertain_trade']['status'] == 'committed'
    table.store.close()


def test_legacy_world_coins_trade_without_migrating_initial_state(tmp_path, template):
    table, host, guest = prepare(tmp_path, template)
    assert 'resource_limits' not in table.state['actor_states'][host]
    oid, _, _ = offer(table, guest, coins=2)
    table.act('guest', trade={'kind': 'accept', 'offer_id': oid})
    assert table.state['actor_states'][host]['resources']['coins'] == 6
    assert table.state['actor_states'][guest]['resources']['coins'] == 10
    assert 'resource_limits' not in table.state['actor_states'][host]
    before = digest(table.state)
    table.store.close(); table.store = Store(tmp_path)
    assert digest(table.state) == before
    table.store.close()


def test_continuation_carries_transferred_goods_and_not_old_pending_quotes(tmp_path, game_template):
    from roleplay_world.continuity import carry_world
    from roleplay_world.world import initial_state

    game_template['world_ref'] = {'id': 'same_world', 'revision': 1}
    table, host, guest = prepare(tmp_path, game_template)
    oid, _, _ = offer(table, guest, items=[{'item_id': 'gear_0'}], request_coins=2)
    table.act('guest', trade={'kind': 'accept', 'offer_id': oid})
    offer(table, guest, coins=1)
    before = digest(table.state)
    next_chapter = carry_world(game_template, table.store.branches[table.bid], table.c, table.state['version'])
    carried = initial_state(next_chapter, table.c['player_name'])
    assert carried['items'] == table.state['items']
    assert carried['actor_states'][host]['resources']['coins'] == 22
    assert not carried.get('trades')
    assert retrieve(carried, guest, '完成交易')
    assert digest(table.state) == before
    table.store.close()



def test_captain_receives_public_repair_procedure_without_player_inventory(tmp_path, template):
    from roleplay_world.world import npc_context

    table, host, _guest = prepare(tmp_path, template)
    context = npc_context(table.state, 'npc_captain', '工具仍在我手里，下一步？', [], host)
    assert '先将修理工具交给你' in context['known_procedures'][0]
    assert 'item_tools' not in {i['id'] for i in context['view']['inventory']}
    assert 'known_procedures' not in npc_context(table.state, 'npc_keeper', '你好', [], host)
    table.store.close()
