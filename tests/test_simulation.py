import asyncio
from copy import deepcopy

import pytest

from roleplay_world.catalog import load_catalog
from roleplay_world.content import StoryBlueprint, WorldBlueprint, compile_story
from roleplay_world.contracts import ActionCommand, DomainError
from roleplay_world.journal import digest
from roleplay_world.runtime import Runtime
from roleplay_world.simulation import SimulationConfig, advance_world, control_event, validate_simulation
from roleplay_world.store import Store
from roleplay_world.world import apply_events, initial_state, project


@pytest.fixture
def living():
    pack = load_catalog()['apartment-5c']
    world = WorldBlueprint.model_validate(pack['world'])
    world.simulation = SimulationConfig.model_validate({'interval_s':300,'actor_indices':[1],
        'factions':[{'id':'gardeners','name':'屋顶园艺社','goal':'开放屋顶花园','interval_s':300,'threshold':2,
            'outcome':'园艺社宣布屋顶花园正式开放。',
            'expansion':{'name':'屋顶花园','description':'公开的新花园','connects_to':0,
                'resident':{'name':'青禾','role':'园艺社联络人','personality':'开朗','goal':'照料花圃',
                            'boundary':'不践踏植物','secret':'她独自保管一枚星辉种子。'}}}]})
    return compile_story(world,StoryBlueprint.model_validate(pack['story']),'living')


class ActorGateway:
    def __init__(self):
        self.calls = []

    async def generate(self,role,system,data,schema,aid,budget,validate=None):
        self.calls.append((role,data))
        assert role == 'world_actor'
        return schema(location_id=data['allowed_locations'][-1]['id'], reason='我去照料另一处的花草。')


def tick(state, delta=300, gateway=None, cached=None, save=None):
    gateway = gateway or ActorGateway()
    before = deepcopy(state)
    state = apply_events(state,[{'type':'time.advanced','payload':{'before_s':state['game_time_s'],
                             'after_s':state['game_time_s']+delta}}],state['version']+1)
    command = {'action_id':f'tick_{state["version"]}','mode':'wait','text':'我等待'}
    events,effects = asyncio.run(advance_world(before,state,command,[],gateway,{},cached,save))
    after = apply_events(state,events,state['version'])
    assert digest(after) == digest(apply_events(state,events,state['version']))
    return after,events,effects,gateway


def test_faction_expansion_resident_secret_and_one_time_threshold(living):
    state = initial_state(living,'玩家')
    state,events,_,_ = tick(state,600)
    assert state['simulation']['factions']['gardeners']['completed']
    assert 'region_gardeners' in state['locations']
    assert any(e['to']=='region_gardeners' for e in state['locations']['loc_0']['exits'])
    assert 'resident_gardeners' in state['actors']
    secret = 'secret_resident_gardeners'
    assert secret not in state['knowledge'][state['player']]
    assert secret in state['knowledge']['resident_gardeners']
    assert not any(f['id']==secret for f in project(state)['known_facts'])
    assert sum(e['type']=='announcement.recorded' for e in events)==1
    state,events,_,_ = tick(state,600)
    assert not any(e['type'] in {'location.created','actor.created','announcement.recorded'} for e in events)


def test_scoped_npc_context_bound_and_cached_proposal(living):
    state = initial_state(living,'玩家')
    state['actor_states']['npc_1']['location_id'] = 'loc_2'
    cached = []
    after,events,_,gateway = tick(state,300,save=cached.append)
    assert len(gateway.calls)==1 and len(cached)==1
    assert gateway.calls[0][1]['view']['quests']==[]
    assert 'player_input' not in gateway.calls[0][1]
    secret_text = state['facts']['fact_secret_0']['value']
    assert secret_text not in str(gateway.calls[0][1])
    class NoCalls:
        async def generate(self,*args,**kwargs):
            raise AssertionError('Retry must reuse recorded autonomous choice')
    again,_,_,_ = tick(state,300,gateway=NoCalls(),cached=cached[0])
    assert digest(again)==digest(after)
    moves = [e for e in events if e['type']=='actor.moved']
    assert all(e['payload']['actor_id']!=state['player'] for e in moves)


def test_pause_has_no_catchup_and_control_is_versioned(living,tmp_path):
    state = initial_state(living,'玩家')
    command = {'action_id':'pause','mode':'ooc','simulation_control':'pause'}
    state = apply_events(state,[control_event(state,command)],1)
    after,events,_,gateway = tick(state,1800)
    assert not events and not gateway.calls and after['simulation']['elapsed_s']==0
    state = apply_events(after,[control_event(after,{**command,'simulation_control':'resume'})],3)
    state,_,_,_ = tick(state,60)
    assert state['simulation']['elapsed_s']==60
    assert not state['simulation']['factions']['gardeners']['completed']
    store = Store(tmp_path)
    c = store.create_campaign('owner',living,'玩家')
    cmd = ActionCommand(action_id='pause_run',expected_world_version=0,mode='ooc',text='暂停世界',simulation_control='pause')
    a,_ = store.accept(c['id'],c['main_branch'],'owner',cmd)
    asyncio.run(Runtime(store,ActorGateway()).run(a['id']))
    assert store.actions[a['id']]['status']=='committed'
    assert store.branches[c['main_branch']]['state']['simulation']['paused']
    fork = store.fork(c['id'],c['main_branch'],'owner',0,'暂停之前')
    assert not fork['state']['simulation']['paused']
    expected = digest(store.branches[c['main_branch']]['state'])
    store.close();store=Store(tmp_path)
    assert digest(store.branches[c['main_branch']]['state'])==expected
    store.close()


def test_simulation_rejects_invalid_refs_and_forged_move(living):
    with pytest.raises(DomainError):
        validate_simulation(SimulationConfig(actor_indices=[99]),3,3)
    state=initial_state(living,'玩家')
    with pytest.raises(DomainError):
        apply_events(state,[{'type':'location.created','payload':{'location':{'id':'bad','exits':[]},'connect_from':'loc_0'}}],1)
