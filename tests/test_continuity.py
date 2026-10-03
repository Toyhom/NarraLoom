from copy import deepcopy

import pytest

from roleplay_world.catalog import load_catalog
from roleplay_world.content import StoryBlueprint, WorldBlueprint, compile_story
from roleplay_world.continuity import carry_world
from roleplay_world.contracts import DomainError
from roleplay_world.journal import digest
from roleplay_world.memory import retrieve
from roleplay_world.store import Store
from roleplay_world.world import initial_state


def template():
    pack=load_catalog()['apartment-5c']
    result=compile_story(WorldBlueprint.model_validate(pack['world']),StoryBlueprint.model_validate(pack['story']),'chapter')
    result['world_ref']={'id':'world_5c','revision':1,'fingerprint':digest(pack['world'])}
    return result


def test_chapter_carries_resources_knowledge_and_world_not_old_quests(tmp_path):
    t=template();state=initial_state(t,'玩家');pc=state['player']
    state['version']=9;state['game_time_s']=500
    state['actor_states'][pc]['resources']['coins']=37
    state['quests']['quest_0']['status']='completed'
    state['knowledge'][pc].append('fact_clue_0')
    state['beliefs'][pc]['fact_clue_0']=deepcopy(state['facts']['fact_clue_0'])
    old_clue=state['facts']['fact_clue_0']['value']
    state['notes']={'n':{'id':'n','kind':'note','status':'open','actor_id':pc,'world_version':9,
                         'text':'记住旧线索','source_event_ids':['fact_clue_0']}}
    chapter=deepcopy(t);chapter['id']='chapter_two';chapter['title']='第二个故事'
    chapter['facts'][next(i for i,f in enumerate(chapter['facts']) if f['id']=='fact_clue_0')]['value']='新章线索与旧事不同'
    source={'id':'source_branch','state':state}
    campaign={'id':'previous_campaign','player_name':'玩家'}
    prepared=carry_world(chapter,source,campaign,9)
    resumed=initial_state(prepared,'玩家')
    assert resumed['version']==0 and resumed['game_time_s']==500
    assert resumed['actor_states'][pc]['resources']['coins']==37
    assert resumed['quests']['quest_0']['status']=='available'
    assert 'fact_clue_0' not in resumed['knowledge'][pc]
    assert resumed['facts']['fact_clue_0']['value']=='新章线索与旧事不同'
    assert any(old_clue in m['text'] for m in retrieve(resumed,pc,old_clue))
    assert resumed['notes']['n']['source_event_ids']==['carry_source_branch_fact_clue_0']
    assert prepared['continuity_origin']['state_hash']==digest(state)
    store=Store(tmp_path);created=store.create_campaign('owner',prepared,'玩家')
    expected=digest(store.branches[created['main_branch']]['state']);store.close();store=Store(tmp_path)
    assert digest(store.branches[created['main_branch']]['state'])==expected
    assert store.branches[created['main_branch']]['state']['actor_states'][pc]['resources']['coins']==37
    store.close()
    resumed['actor_states'][pc]['resources']['coins']=0
    assert state['actor_states'][pc]['resources']['coins']==37


def test_continuation_rejects_mismatched_world_or_stale_version():
    t=template();source={'id':'branch','state':initial_state(t,'玩家')};campaign={'id':'c','player_name':'玩家'}
    with pytest.raises(DomainError,match='刷新'):
        carry_world(t,source,campaign,1)
    changed=deepcopy(t);changed['world_ref']['revision']=2
    with pytest.raises(DomainError,match='世界修订'):
        carry_world(changed,source,campaign,0)


def test_continuation_opening_uses_actual_actor_positions():
    t=template();t['opening']='某位已经离开的角色向你问好。'
    state=initial_state(t,'玩家');pc=state['player']
    for actor in state['actors']:
        if actor!=pc:state['actor_states'][actor]['location_id']='loc_2'
    prepared=carry_world(t,{'id':'branch','state':state},{'id':'c','player_name':'玩家'},0)
    assert '某位已经离开的角色' not in prepared['opening']
    assert '暂时没有其他人' in prepared['opening']
