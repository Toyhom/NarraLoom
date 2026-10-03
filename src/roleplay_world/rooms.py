"""Invite-only shared or independent characters, with explicit turn ownership."""
import secrets
import time
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field

from .contracts import ActionCommand, Contract, DomainError, Identifier
from .players import human_players
from .store import public_action, public_history, uid
from .world import project

ACTIVE = {'accepted','planning','characters','narrating'}

class RoomCreate(Contract):
    campaign_id: Identifier
    branch_id: Identifier
    name: Annotated[str,Field(min_length=1,max_length=32)] = '房主'
    mode: Literal['shared_character', 'independent_characters'] = 'shared_character'

class RoomJoin(Contract):
    code: Annotated[str,Field(min_length=20,max_length=160)]
    name: Annotated[str,Field(min_length=1,max_length=32)]
    role: Annotated[str,Field(min_length=1,max_length=80)] = '同行旅人'
    create_character: bool = True

class RoomControl(Contract):
    expected_revision: Annotated[int,Field(ge=0)]
    operation: str
    member_id: Identifier | None = None
    actor_id: Identifier | None = None

class RoomAction(Contract):
    expected_revision: Annotated[int,Field(ge=0)]
    command: ActionCommand

class Rooms:
    def __init__(self,store):self.store=store

    def active_for(self,bid):
        return next((r for r in self.store.rooms.values() if r['branch_id']==bid and not r['closed']),None)

    def member(self,room,owner):
        return next((m for m in room['members'] if m['owner']==owner),None)

    def get(self,rid,owner):
        r=self.store.rooms.get(rid)
        if not r or not self.member(r,owner) or (r['closed'] and owner!=r['owner']):
            raise DomainError('room_missing','未加入这个房间，或邀请已失效',404)
        return r

    def save(self,room):
        self.store.studio_save('rooms',room)
        return self.store.rooms[room['id']]

    def create(self,owner,payload):
        branch = self.store.branch(payload.campaign_id,payload.branch_id,owner)
        old=self.active_for(payload.branch_id)
        if old:return self.view(old['id'],owner)
        mid=uid('member')
        r={'id':uid('room'),'owner':owner,'campaign_id':payload.campaign_id,'branch_id':payload.branch_id,
           'members':[{'id':mid,'owner':owner,'name':payload.name}],'turn':mid,'revision':0,'closed':False,
           'invite':secrets.token_hex(24),'created_at':time.time()}
        if payload.mode == 'independent_characters':
            # Carry only the latest binding snapshot, including revocations. Looking
            # through older rosters at join time could restore a reassigned identity.
            prior = self.latest_roster(branch)
            r.update(mode=payload.mode, roster={**prior, owner: branch['state']['player']})
            r['members'][0]['actor_id'] = branch['state']['player']
        self.save(r);return self.view(r['id'],owner)

    def latest_roster(self, branch):
        candidates = [r for r in self.store.rooms.values()
                      if r['branch_id'] == branch['id'] and r.get('mode') == 'independent_characters']
        if candidates:
            return deepcopy(max(candidates, key=lambda r: r['created_at']).get('roster', {}))
        if branch.get('parent_id'):
            roster = self.latest_roster(self.store.branches[branch['parent_id']])
            return {owner: actor for owner, actor in roster.items() if actor is None or actor in human_players(branch['state'])}
        return {}

    def join(self,owner,payload):
        rid,_,invite=payload.code.strip().partition(':');r=self.store.rooms.get(rid)
        if not r or r['closed'] or not secrets.compare_digest(r['invite'],invite):
            raise DomainError('room_invite','邀请无效或已关闭',404)
        if not self.member(r,owner):
            if len(r['members'])>=6:raise DomainError('room_full','房间已有6位参与者',409)
            if self.pending(r):raise DomainError('room_busy','请等待当前行动结束后加入',409)
            r=deepcopy(r);member={'id':uid('member'),'owner':owner,'name':payload.name}
            event = None
            if r.get('mode') == 'independent_characters':
                state = self.store.branches[r['branch_id']]['state']
                actor = r.get('roster', {}).get(owner)
                if actor and any(m.get('actor_id') == actor for m in r['members']):
                    actor = None
                if owner not in r.get('roster', {}) and payload.create_character and len(human_players(state)) < 6:
                    actor = uid('pc')
                    event = {'event_id': uid('joined'), 'type': 'player.joined', 'visibility': {'kind': 'public'},
                             'payload': {'id': actor, 'name': payload.name, 'role': payload.role, 'initialization_version': '1'}}
                member['actor_id'] = actor
                if actor:
                    r.setdefault('roster', {})[owner] = actor
            r['members'].append(member);r['revision']+=1
            if event:
                self.store.join_room_player(r, event)
            else:
                self.save(r)
        return self.view(rid,owner)

    def character(self, room, owner, required=True):
        member = self.member(room, owner)
        actor = (member.get('actor_id') if member else None) if room.get('mode') == 'independent_characters' else self.store.branches[room['branch_id']]['state']['player']
        if required and not actor:
            raise DomainError('room_character','请先由房主分配一个角色',409)
        return actor

    def pending(self,room):
        return [a for a in self.store.actions.values() if a['branch_id']==room['branch_id'] and a['status'] in ACTIVE]

    def view(self,rid,owner):
        r=self.get(rid,owner);b=self.store.branches[r['branch_id']];member=self.member(r,owner)
        actor = self.character(r, owner, required=False)
        state=project(b['state'], actor) if actor else None
        if state is not None:
            opening = (b['state']['template']['opening'] if actor == b['state']['player']
                       else '你以'+state['player_role']+'的身份来到'+state['location']['name']+'，开始自己的冒险。')
            state.update(opening=opening,history=public_history(b['commits'], actor, b['state']['player']))
        return {'id':rid,'revision':r['revision'],'closed':r['closed'],'turn':r['turn'],'me':member['id'],
                'host':owner==r['owner'],'members':[{k:m[k] for k in ('id','name','actor_id') if k in m} for m in r['members']],
                'invite_code':rid+':'+r['invite'] if owner==r['owner'] and not r['closed'] else None,
                'title': b['state']['template']['title'], 'world_version': b['state']['version'],
                'state':state,'pending':[self.receipt(rid, owner, a) for a in self.pending(r)] if actor else [],
                'recoverable': [self.receipt(rid, owner, a) for a in reversed(list(self.store.actions.values()))
                    if actor and a['branch_id'] == r['branch_id'] and a.get('submitter') == owner
                    and a['command'].get('actor_id', b['state']['player']) == actor
                    and a['status'] in {'failed', 'interrupted'}][:3],
                'characters': [{'id': aid, 'name': b['state']['actors'][aid]['name']} for aid in human_players(b['state'])],
                'mode':r.get('mode','shared_character'),'billing':'房主的模型配置与额度'}

    def control(self,rid,owner,payload):
        r=self.get(rid,owner);member=self.member(r,owner)
        if r['closed']:raise DomainError('room_closed','房间已关闭',409)
        if payload.expected_revision!=r['revision']:raise DomainError('room_stale','房间已有变化，请刷新',409)
        r=deepcopy(r)
        if payload.operation=='pass':
            if member['id']!=r['turn']:raise DomainError('room_turn','只有当前行动者可以交接',403)
            if self.pending(r):raise DomainError('room_busy','本轮结束后再交接',409)
            if not any(m['id']==payload.member_id for m in r['members']):raise DomainError('room_member','参与者不存在',422)
            target = next(m for m in r['members'] if m['id'] == payload.member_id)
            if r.get('mode') == 'independent_characters' and not target.get('actor_id'):
                raise DomainError('room_character','请先为该席位分配角色',409)
            r['turn']=payload.member_id
        elif payload.operation in {'close','rotate','kick','reclaim','assign'}:
            if owner!=r['owner']:raise DomainError('room_host','只有房主可以执行',403)
            if payload.operation in {'close','kick','reclaim','assign'} and self.pending(r):raise DomainError('room_busy','请先等待或取消本轮行动',409)
            if payload.operation=='close':r['closed']=True;r['invite']=secrets.token_hex(24)
            elif payload.operation=='rotate':r['invite']=secrets.token_hex(24)
            elif payload.operation=='reclaim':r['turn']=member['id']
            elif payload.operation=='assign':
                state = self.store.branches[r['branch_id']]['state']
                target = next((m for m in r['members'] if m['id'] == payload.member_id), None)
                if (r.get('mode') != 'independent_characters' or not target or target['owner'] == r['owner']
                        or payload.actor_id not in human_players(state) or payload.actor_id == state['player']):
                    raise DomainError('room_character','请选择其他席位与已有的独立玩家角色',422)
                if any(m['id'] != target['id'] and m.get('actor_id') == payload.actor_id for m in r['members']):
                    raise DomainError('room_character','这个角色已由另一位参与者操控',409)
                r['roster'] = {o:None if a == payload.actor_id else a for o,a in r.get('roster',{}).items()}
                target['actor_id'] = payload.actor_id
                r['roster'][target['owner']] = payload.actor_id
            else:
                if payload.member_id==member['id']:raise DomainError('room_host','房主请使用关闭房间',422)
                r['members']=[m for m in r['members'] if m['id']!=payload.member_id]
                if r['turn']==payload.member_id:r['turn']=member['id']
        else:raise DomainError('room_operation','不支持的房间操作',422)
        r['revision']+=1;self.save(r);return self.view(rid,owner)

    def require_turn(self,room,owner):
        member=self.member(room,owner)
        if room['closed'] or not member or member['id']!=room['turn']:
            raise DomainError('room_turn','尚未轮到你行动，请等待交接',403)
        self.character(room, owner)

    def accept(self,rid,owner,payload):
        room=self.get(rid,owner)
        actor = self.character(room, owner) if room.get('mode') == 'independent_characters' else None
        old=self.store.actions.get(payload.command.action_id)
        if old and old.get('room_id')==rid and old.get('submitter')==owner:
            return self.store.accept(room['campaign_id'],room['branch_id'],room['owner'],payload.command,owner,rid,actor)
        self.require_turn(room,owner)
        if payload.expected_revision!=room['revision']:raise DomainError('room_stale','房间已有变化，请刷新',409)
        return self.store.accept(room['campaign_id'],room['branch_id'],room['owner'],payload.command,owner,rid,actor)

    def receipt(self, rid, owner, action):
        room = self.get(rid, owner)
        actor = self.character(room, owner)
        state = self.store.branches[room['branch_id']]['state']
        value = public_action(action, actor, state['player'])
        controls = owner in {room['owner'], action.get('submitter')}
        same_actor = action['command'].get('actor_id', state['player']) == actor
        value.update(can_cancel=controls and action['status'] in ACTIVE,
                     can_retry=controls and same_actor and not room['closed'] and room['turn'] == self.member(room, owner)['id']
                     and action['status'] in {'failed', 'interrupted'}
                     and action['command']['expected_world_version'] == state['version'] and not self.pending(room))
        return value

    def visible_avatar(self, rid, owner, aid):
        from .world import present

        room = self.get(rid, owner)
        actor = self.character(room, owner)
        state = self.store.branches[room['branch_id']]['state']
        if not any(state['actors'][a].get('avatar_id') == aid for a in present(state, actor)):
            raise DomainError('avatar_missing', '这个形象不在你的当前场景中', 404)
        return room['owner']

    def action(self,rid,owner,aid,control=False):
        room=self.get(rid,owner);action=self.store.actions.get(aid)
        if not action or action['branch_id']!=room['branch_id']:raise DomainError('not_found','没有此房间行动',404)
        if (control and owner != room['owner'] and room.get('mode') == 'independent_characters'
                and action['command'].get('actor_id', self.store.branches[room['branch_id']]['state']['player']) != self.character(room, owner)):
            # A host may cancel a stalled guest turn but cannot retry/act as them;
            # retry has an additional explicit actor check in the API.
            raise DomainError('room_action','不能恢复其他角色的行动',403)
        if control and owner not in {room['owner'],action.get('submitter')}:
            raise DomainError('room_action','只能取消或重试自己提交的行动',403)
        return room,action
