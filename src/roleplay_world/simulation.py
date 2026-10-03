"""Bounded world progression: game-time factions and one scoped NPC decision per tick."""

from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field, create_model

from .content_preferences import content_language, language_prompt
from .contracts import Contract, DomainError, Identifier

Text = Annotated[str, Field(min_length=1, max_length=600)]
Name = Annotated[str, Field(min_length=1, max_length=60)]


class Resident(Contract):
    name: Name
    role: Name
    personality: Text
    goal: Text
    boundary: Text
    secret: Text


class Expansion(Contract):
    name: Name
    description: Text
    connects_to: Annotated[int, Field(ge=0, le=23)]
    resident: Resident | None = None


class Faction(Contract):
    id: Identifier
    name: Name
    goal: Text
    interval_s: Annotated[int, Field(ge=300, le=7200)] = 900
    threshold: Annotated[int, Field(ge=2, le=24)] = 4
    outcome: Text
    expansion: Expansion | None = None


class SimulationConfig(Contract):
    interval_s: Annotated[int, Field(ge=300, le=3600)] = 600
    actor_indices: Annotated[list[int], Field(max_length=16)] = Field(default_factory=list)
    factions: Annotated[list[Faction], Field(max_length=8)] = Field(default_factory=list)


def validate_simulation(config, locations, actors):
    if not config:
        return
    if len(set(config.actor_indices)) != len(config.actor_indices) or any(i < 0 or i >= actors for i in config.actor_indices):
        raise DomainError('invalid_simulation', '主动NPC必须引用现有人物且不能重复', 422)
    if len({f.id for f in config.factions}) != len(config.factions):
        raise DomainError('invalid_simulation', '势力ID不能重复', 422)
    if any(f.expansion and f.expansion.connects_to >= locations for f in config.factions):
        raise DomainError('invalid_simulation', '新区域的通路连接不存在', 422)


def initial_simulation(config):
    return {'paused': False, 'elapsed_s': 0, 'next_tick_s': config['interval_s'], 'cursor': 0,
            'factions': {f['id']: {'value': 0, 'completed': False} for f in config['factions']}}


WORLD_ACTOR_PROMPT = """你是世界中一位有自己目标的角色。根据自己的view、个性、目标与已有记忆，选择下一步行动。
你不能控制玩家、其他人物或全知事实。allowed_locations包括原地与相邻地点；location_id只选其中之一。
选择原地表示继续当前活动；移动只能到相邻地点。reason简述自己的理由，不能声称已完成新交易、任务或发现。
当前玩家不在你的场景里，不可隔空听见玩家命令。你的输出仅是候选，引擎验证后才生效。
只输出JSON。"""


async def advance_world(before, candidate, command, speakers, gateway, budget, cached=None, save=None):
    from .world import apply_events, model_view, present

    cfg = candidate['template']['mechanics'].get('simulation')
    if not cfg or candidate['simulation']['paused'] or command['mode'] == 'ooc':
        return [], []
    delta = candidate['game_time_s']-before['game_time_s']
    if delta <= 0:
        return [], []
    state = deepcopy(candidate)
    previous = deepcopy(state['simulation']); progress = deepcopy(previous)
    progress['elapsed_s'] += delta
    events, effects = [], []
    from .players import command_player, human_players

    pc = command_player(state, command)

    def emit(kind, payload, audience=None, text=None):
        nonlocal state
        event = {'event_id':command['action_id']+'_world_'+str(len(events)+1), 'type':kind,
                 'visibility':{'kind':'actors','actor_ids':audience or [pc]},'payload':payload}
        events.append(event)
        state = apply_events(state,[event],state['version'])
        if text:
            effects.append(text)
        return event

    for faction in cfg['factions']:
        status = progress['factions'][faction['id']]
        status['value'] = min(faction['threshold'],progress['elapsed_s']//faction['interval_s'])
        if status['value'] < faction['threshold'] or status['completed']:
            continue
        status['completed'] = True
        fid = 'faction_fact_'+faction['id']
        fact = {'id':fid,'name':faction['name'],'value':faction['outcome'],'visibility':{'kind':'public'}}
        emit('announcement.recorded',{'fact':fact})
        effects.append(faction['outcome'])
        expansion = faction.get('expansion')
        if expansion:
            lid = 'region_'+faction['id']; anchor = f"loc_{expansion['connects_to']}"
            location = {'id':lid,'name':expansion['name'],'description':expansion['description'],
                        'exits':[{'to':anchor,'travel_time_s':120}]}
            emit('location.created',{'location':location,'connect_from':anchor},
                 text=state['locations'][anchor]['name']+'出现了通往'+expansion['name']+'的新通路')
            resident = expansion.get('resident')
            if resident:
                nid = 'resident_'+faction['id']; secret_id = 'secret_'+nid
                secret = {'id':secret_id,'value':resident['secret'],'visibility':{'kind':'actors','actor_ids':[nid]}}
                emit('fact.created',{'fact':secret},[nid])
                actor = {'id':nid,'name':resident['name'],'control':'npc','public_description':resident['role'],
                         'persona':{'personality':resident['personality']},'goals':[resident['goal']],
                         'boundaries':[resident['boundary']],'initial_knowledge':[secret_id,fid],
                         'initial_state':{'location_id':lid,'resources':{'vitality':10,'coins':0}}}
                emit('actor.created',{'actor':actor},[nid])
    if progress['elapsed_s'] >= progress['next_tick_s']:
        progress['next_tick_s'] = progress['elapsed_s']+cfg['interval_s']
        possible = [f'npc_{i}' for i in cfg['actor_indices']]
        possible += [a for a in state['actors'] if a.startswith('resident_')]
        observed = {a for human in human_players(state) for a in present(state, human)}
        possible = [a for a in possible if a not in observed and a not in state.get('party',[]) and a not in speakers]
        if possible:
            actor = possible[progress['cursor'] % len(possible)]
            progress['cursor'] += 1
            loc = state['actor_states'][actor]['location_id']
            locations = [loc,*[e['to'] for e in state['locations'][loc]['exits']]]
            schema = create_model('WorldActorStep',__base__=Contract,
                                  location_id=(Literal[tuple(locations)],...),
                                  reason=(Annotated[str,Field(min_length=1,max_length=240)],...))
            if cached:
                if cached['actor_id'] != actor:
                    raise DomainError('simulation_conflict','世界推进缓存不匹配',409)
                proposal = schema.model_validate(cached['proposal'])
            else:
                npc = state['actors'][actor]
                data = {'character':{k:npc[k] for k in ('name','persona','goals','boundaries')},
                        'view':model_view(state,actor,' '.join(npc['goals'])),
                        'allowed_locations':[{'id':lid,'name':state['locations'][lid]['name']} for lid in locations]}
                proposal = await gateway.generate('world_actor',WORLD_ACTOR_PROMPT + language_prompt(content_language(state)),data,schema,command['action_id'],budget)
                if save:
                    save({'actor_id':actor,'proposal':proposal.model_dump()})
            if proposal.location_id != loc:
                audience = sorted({actor,*present(state,actor),
                                   *[a for a,s in state['actor_states'].items() if s['location_id']==proposal.location_id]})
                text = state['actors'][actor]['name']+'前往'+state['locations'][proposal.location_id]['name']
                event = emit('actor.moved',{'actor_id':actor,'from_location':loc,'to_location':proposal.location_id},
                             audience,text if pc in audience else None)
                emit('memory.recorded',{'audience':audience,'text':text,'category':'outcome',
                                       'source_event_ids':[event['event_id']],'world_version':state['version']},audience)
            emit('memory.recorded',{'audience':[actor],'text':'我的下一步考虑：'+proposal.reason,
                                   'category':'intention','world_version':state['version']},[actor])
    emit('simulation.advanced',{'before':previous,'after':progress})
    if len(events) > 400:
        raise DomainError('simulation_limit','本次世界推进变化过多',422)
    return events, effects


def control_event(state, command):
    from .players import command_player

    if command['mode'] != 'ooc' or command.get('selected_operation') or command.get('note_record'):
        raise DomainError('invalid_simulation','世界运行开关必须独立提交',422)
    if 'simulation' not in state:
        raise DomainError('invalid_simulation','此世界未启用主动运行',422)
    return {'event_id':command['action_id']+'_control','type':'simulation.paused',
            'visibility':{'kind':'actors','actor_ids':[command_player(state, command)]},
            'payload':{'before':state['simulation']['paused'],'after':command['simulation_control']=='pause'}}
