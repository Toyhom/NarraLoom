"""Fork a new story from a committed world snapshot, preserving provenance and knowledge scopes."""

from copy import deepcopy

from .contracts import DomainError
from .journal import digest


def carry_world(template, source, source_campaign, expected_version):
    from .players import followers
    from .world import initial_state, visible

    old = source['state']
    if expected_version != old['version']:
        raise DomainError('stale_continuity','来源存档已变化，请刷新后重新选择',409)
    if not template.get('world_ref') or template['world_ref'] != old['template'].get('world_ref'):
        raise DomainError('incompatible_world','只可继承同一世界修订的存档；请使用匹配的世界版本',422)
    target = deepcopy(template)
    # A continuation starts at this story's opening location, carrying the established party and resources.
    fresh = initial_state(target,source_campaign['player_name'])
    pc = fresh['player']; start = fresh['actor_states'][pc]['location_id']
    fresh['locations'] = deepcopy(old['locations'])
    fresh['actors'] = deepcopy(old['actors'])
    fresh['actor_states'] = deepcopy(old['actor_states'])
    fresh['actor_states'][pc]['location_id'] = start
    fresh['items'] = deepcopy(old['items'])
    new_item = next((i for i in target['items'] if i['id']=='item_start'),None)
    if new_item and old['items'].get('item_start',{}).get('name') != new_item['name']:
        item = deepcopy(new_item);item['id']='chapter_'+digest({'id':target['id'],'version':target['version']})[:20]
        fresh['items'].setdefault(item['id'],item)
    fresh['relations'] = deepcopy(old['relations'])
    fresh['game_time_s'] = old['game_time_s']
    for key in ('party','companion_leaders','shops','simulation','notes'):
        if key in old:
            fresh[key] = deepcopy(old[key])
    if 'state_rules' in fresh and 'state_rules' in old:
        cfg = target['mechanics']['state_rules']
        for group, declarations in (('values', 'variables'), ('actions', 'actions'), ('triggers', 'triggers')):
            for row in cfg[declarations]:
                if row['scope'] == 'world' and row['id'] in old['state_rules'][group]:
                    fresh['state_rules'][group][row['id']] = deepcopy(old['state_rules'][group][row['id']])
    for follower in followers(fresh, pc):
        fresh['actor_states'][follower]['location_id'] = start
    # Story clues/pressure are chapter-local. World secrets and public world announcements persist.
    persistent = {fid:deepcopy(f) for fid,f in old['facts'].items()
                  if fid.startswith(('fact_secret_','secret_resident_','faction_fact_'))}
    fresh['facts'].update(persistent)
    fresh['knowledge'] = {actor:[] for actor in fresh['actors']}
    fresh['beliefs'] = {actor:{} for actor in fresh['actors']}
    fresh['memories'] = deepcopy(old['memories'])
    for actor in fresh['actors']:
        for row in fresh['memories'][actor]:
            row.setdefault('origin_story',old['template']['title'])
        original = next((a for a in target['actors'] if a['id']==actor),None)
        initial_knowledge = (original['initial_knowledge'] if original else
                             [fid for fid, fact in fresh['facts'].items() if visible(fact.get('visibility', {}), actor)])
        for fid in initial_knowledge:
            fresh['knowledge'][actor].append(fid)
            fresh['beliefs'][actor][fid] = deepcopy(fresh['facts'][fid])
        for fid in old['knowledge'][actor]:
            snapshot = deepcopy(old['beliefs'][actor][fid])
            if fid in persistent:
                if fid not in fresh['knowledge'][actor]:
                    fresh['knowledge'][actor].append(fid)
                fresh['beliefs'][actor][fid] = snapshot
            else:
                text = snapshot.get('value_labels',{}).get(str(snapshot['value']),str(snapshot['value']))
                fresh['memories'][actor].append({'event_id':'carry_'+source['id']+'_'+fid,
                    'text':'上一故事的已知记录：'+text,'game_time_s':old['game_time_s'],
                    'category':'historical_record','origin_story':old['template']['title'],
                    'source_event_ids':['carry_'+source['id']+'_'+fid]})
    target['continuity_origin'] = {'campaign_id':source_campaign['id'],'branch_id':source['id'],
                                   'world_version':old['version'],'state_hash':digest(old),
                                   'story_title':old['template']['title']}
    for note in fresh.get('notes', {}).values():
        note['source_event_ids'] = ['carry_'+source['id']+'_'+fid if fid in old['facts'] and fid not in persistent else fid
                                    for fid in note['source_event_ids']]
    target['continuity_state'] = {k:deepcopy(v) for k,v in fresh.items() if k not in {'template','version','player'}}
    nearby = [fresh['actors'][a]['name'] for a, value in fresh['actor_states'].items()
              if a != pc and value['location_id'] == start and not fresh['actors'][a].get('combatant')]
    target['opening'] = ('你带着上一段经历来到'+fresh['locations'][start]['name']+'。\n\n'
                         + fresh['locations'][start]['description']+'\n\n'
                         + ('此刻在场：'+'、'.join(nearby)+'。' if nearby else '此刻，这里暂时没有其他人。')
                         + '\n\n新故事的方向：'+target['premise'])
    return target
