import asyncio
from copy import deepcopy

import pytest

from roleplay_world.contracts import ActionCommand, DomainError
from roleplay_world.journal import digest
from roleplay_world.memory import context_memories, note_event, retrieve
from roleplay_world.runtime import Runtime
from roleplay_world.store import Store
from roleplay_world.world import apply_events, initial_state, model_view


def record(eid, audience, text, category='utterance'):
    return {'event_id':eid, 'type':'memory.recorded', 'payload':{
        'audience':audience,'text':text,'category':category,'source_event_ids':[eid+'_speech']}}


def test_retrieves_old_chinese_and_english_with_scoped_sources(template):
    state = initial_state(template, '访客')
    pc = state['player']
    npc = next(a for a in state['actors'] if a != pc)
    state = apply_events(state, [record('old_shared', [pc,npc], '约好下次去蓝铃塔归还陶笛。The bluebell promise.')], 1)
    state = apply_events(state, [record('secret_other', [npc], '只有船长知道密钥MOON-SECRET。')], 2)
    for i in range(120):
        state = apply_events(state, [record(f'filler_{i}', [pc,npc], f'今天聊起天气第{i}次。')], i+3)
    found = retrieve(state, pc, '蓝铃塔的陶笛约定')
    assert found[0]['source_id'] == 'old_shared'
    assert found[0]['source_event_ids'] == ['old_shared_speech']
    assert retrieve(state, pc, 'bluebell')[0]['source_id'] == 'old_shared'
    assert not retrieve(state, pc, 'MOON-SECRET')
    assert retrieve(state, npc, 'MOON-SECRET')[0]['source_id'] == 'secret_other'
    assert any(m['source_id'] == 'old_shared' for m in model_view(state, pc, '蓝铃塔')['memories'])
    assert sum(len(m['text']) for m in context_memories(state, pc, '陶笛')) <= 6800
    assert state['version'] == 122  # retrieval cannot mutate world


def test_retrieval_uses_belief_snapshot_not_gm_truth(template):
    state = initial_state(template, '访客')
    pc = state['player']
    fid = state['knowledge'][pc][0]
    before = deepcopy(state['beliefs'][pc][fid])
    state['facts'][fid]['value'] = 'SHOULD-NOT-LEAK'
    found = retrieve(state, pc)
    assert not any('SHOULD-NOT-LEAK' in row['text'] for row in found)
    assert state['beliefs'][pc][fid] == before


def test_notes_are_versioned_branch_private_and_do_not_write_facts(tmp_path, template):
    class NoModel:
        async def generate(self, *args, **kwargs):
            raise AssertionError('Notes must not call a model')
    store = Store(tmp_path)
    campaign = store.create_campaign('owner', template, '玩家')
    bid = campaign['main_branch']
    pc = store.branches[bid]['state']['player']
    original = digest(store.branches[bid]['state']['facts'])
    command = ActionCommand(action_id='note_action',expected_world_version=0,mode='ooc',text='记手记',
        note_record={'id':'promise','kind':'commitment','text':'准备把蓝铃陶笛交给船长。'})
    action, fresh = store.accept(campaign['id'],bid,'owner',command)
    assert fresh
    asyncio.run(Runtime(store,NoModel()).run(action['id']))
    assert store.actions[action['id']]['status'] == 'committed'
    state = store.branches[bid]['state']
    assert digest(state['facts']) == original and state['game_time_s'] == 0
    assert retrieve(state,pc,'蓝铃')[0]['certainty'] == 'player_note'
    same, fresh = store.accept(campaign['id'],bid,'owner',command)
    assert not fresh and same['status'] == 'committed'
    fork = store.fork(campaign['id'],bid,'owner',0,'之前')
    assert not retrieve(fork['state'],pc,'蓝铃')
    fork_later = store.fork(campaign['id'],bid,'owner',1,'之后')
    done = ActionCommand(action_id='done_action',expected_world_version=1,mode='ooc',text='完成手记',
        note_record={'id':'promise','kind':'commitment','status':'done','text':'准备把蓝铃陶笛交给船长。'})
    action, _ = store.accept(campaign['id'],bid,'owner',done)
    asyncio.run(Runtime(store,NoModel()).run(action['id']))
    assert store.branches[fork_later['id']]['state']['notes']['promise']['status'] == 'open'
    hash_before = digest(store.branches[bid]['state'])
    store.close()
    reopened = Store(tmp_path)
    assert digest(reopened.branches[bid]['state']) == hash_before
    reopened.close()


def test_note_references_cannot_invent_or_read_another_npc(template):
    state = initial_state(template,'玩家')
    state = apply_events(state,[record('private',['npc_captain'],'我知道一个秘密')],1)
    command = ActionCommand(action_id='note_test',expected_world_version=1,mode='ooc',text='记手记',
        note_record={'id':'n','text':'凭空引用','source_event_ids':['private_speech']}).model_dump(exclude_none=True)
    with pytest.raises(DomainError, match='本分支'):
        note_event(state,command)
    command['note_record']['source_event_ids'] = []
    event = note_event(state,command)
    after = apply_events(state,[event],2)
    assert after['notes']['n']['text'] == '凭空引用'
    assert not retrieve(after,'npc_captain','凭空引用')


def test_legacy_memory_event_keeps_exact_shape(template):
    state = initial_state(template, '玩家')
    event = {'event_id':'legacy','type':'memory.recorded','payload':{'audience':[state['player']],'text':'旧记录'}}
    after = apply_events(state,[event],1)
    assert after['memories'][state['player']] == [{'event_id':'legacy','text':'旧记录','game_time_s':0}]
    assert 'notes' not in after
