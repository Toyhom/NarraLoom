"""Human consent, frozen terms and atomic item/currency settlement. No model calls."""
import hashlib
from copy import deepcopy

from .contracts import DomainError, TradeCommand
from .players import command_player, player_for

MAX_PENDING = 12


def fail(message):
    raise DomainError('invalid_trade', message, 422)


def together(state, sender, recipient):
    player_for(state, sender)
    player_for(state, recipient)
    if sender == recipient:
        fail('请选择另一位玩家')
    if state['actor_states'][sender]['location_id'] != state['actor_states'][recipient]['location_id']:
        fail('交易双方需要处于同一地点')


def bundle(state, actor, items, coins):
    if len({row['item_id'] for row in items}) != len(items):
        fail('同一物品请合并数量')
    result = {'items': [], 'coins': coins}
    for row in items:
        item = state['items'].get(row['item_id'])
        if not item or item['holder_id'] != actor or item['quantity'] < row['quantity']:
            fail('持有的物品数量不足，请刷新行囊后重新报价')
        result['items'].append({**row, 'name': item['name']})
    if coins > state['actor_states'][actor]['resources'].get('coins', 0):
        fail('金币不足，报价尚未成交')
    return result


def pending(state, offer_id):
    offer = state.get('trades', {}).get(offer_id)
    if not offer or offer['status'] != 'pending':
        fail('该报价不存在或已经结束')
    return offer


def proposal(state, cmd, actor, action_id):
    other = cmd.target_id
    receive = {'items': [], 'coins': cmd.request_coins}
    previous = None
    if cmd.kind == 'counter':
        previous = pending(state, cmd.offer_id)
        if previous['recipient'] != actor:
            fail('只有报价接收人可以还价')
        if cmd.target_id or cmd.request_coins:
            fail('还价索取原报价中的物资，请仅填写自己愿意交出的部分')
        other = previous['sender']
        receive = deepcopy(previous['give'])
    elif cmd.offer_id:
        fail('新报价不能指定旧报价编号')
    if not other:
        fail('请选择交易对象')
    together(state, actor, other)
    give = bundle(state, actor, [row.model_dump() for row in cmd.items], cmd.coins)
    if not give['items'] and not give['coins'] and not receive['items'] and not receive['coins']:
        fail('报价需要包含物品或金币')
    count = sum(o['status'] == 'pending' for o in state.get('trades', {}).values())
    if count - bool(previous) >= MAX_PENDING:
        fail('待回应报价已满，请先处理已有报价')
    return {'id': 'trade_'+hashlib.sha256(action_id.encode()).hexdigest()[:24], 'version': '1',
            'sender': actor, 'recipient': other, 'give': give, 'receive': receive,
            'status': 'pending', 'counter_of': cmd.offer_id, 'created_version': state['version']+1}


def settlement(state, offer, action_id):
    """Fully validate BOTH sides before emitting any recorded transfer outcomes."""
    sender, recipient = offer['sender'], offer['recipient']
    together(state, sender, recipient)
    sides = [(sender, recipient, offer['give']), (recipient, sender, offer['receive'])]
    for actor, _, terms in sides:
        actual = bundle(state, actor, [{k: row[k] for k in ('item_id', 'quantity')} for row in terms['items']], terms['coins'])
        if actual != terms:
            fail('报价物资已变化，请重新报价')
    events = []
    def emit(kind, payload):
        events.append({'event_id': f'{action_id}_transfer_{len(events)+1}', 'type': kind,
                       'visibility': {'kind': 'actors', 'actor_ids': [sender, recipient]}, 'payload': payload})
    for index, (actor, other, terms) in enumerate(sides):
        incoming = sides[1-index][2]['coins']
        own = state['actor_states'][actor]
        before = own['resources'].get('coins', 0)
        after = before-terms['coins']+incoming
        if after > own.get('resource_limits', {}).get('coins', 999999):
            fail('收款将超过金币上限，请调整报价')
        if after != before:
            emit('resource.changed', {'actor_id': actor, 'resource': 'coins', 'before': before, 'after': after})
        for row in terms['items']:
            item = state['items'][row['item_id']]
            if row['quantity'] == item['quantity']:
                emit('item.transferred', {'item_id': item['id'], 'from_holder': actor, 'to_holder': other})
            else:
                emit('item.quantity_changed', {'item_id': item['id'], 'before': item['quantity'], 'after': item['quantity']-row['quantity']})
                item_id = 'tradeitem_'+hashlib.sha256((action_id+':'+item['id']).encode()).hexdigest()[:24]
                emit('item.created', {'item': {**deepcopy(item), 'id': item_id, 'holder_id': other, 'quantity': row['quantity']}})
    return events


def bundle_text(terms):
    return '、'.join([f"{i['name']} ×{i['quantity']}" for i in terms['items']] + ([f"{terms['coins']}金币"] if terms['coins'] else [])) or '无'


def describe(state, offer, status):
    names = [state['actors'][offer[key]]['name'] for key in ('sender', 'recipient')]
    label = {'pending': '提出报价', 'accepted': '完成交易', 'declined': '拒绝报价', 'withdrawn': '撤回报价'}[status]
    return f"{names[0]}与{names[1]}：{label}；{names[0]}交出{bundle_text(offer['give'])}；{names[1]}交出{bundle_text(offer['receive'])}。"


def resolve_trade(state, command):
    from .world import present

    cmd = TradeCommand.model_validate(command['trade'])
    if command['mode'] != 'act' or any(command.get(key) for key in ('whisper_to', 'selected_operation', 'note_record', 'simulation_control')):
        fail('交易需单独提交，不能与说话、手记或其他操作混用')
    actor, aid = command_player(state, command), command['action_id']
    if cmd.kind in {'propose', 'counter'}:
        offer = proposal(state, cmd, actor, aid)
        kind, payload, status = 'trade.proposed', {'offer': offer, 'command': cmd.model_dump(), 'actor_id': actor, 'action_id': aid}, 'pending'
    else:
        if not cmd.offer_id or cmd.target_id or cmd.items or cmd.coins or cmd.request_coins:
            fail('回应只能引用原报价，修改条款请使用还价')
        offer = pending(state, cmd.offer_id)
        required = offer['sender'] if cmd.kind == 'withdraw' else offer['recipient']
        if actor != required:
            fail('只有报价本人可以回应或撤回')
        status = {'accept': 'accepted', 'decline': 'declined', 'withdraw': 'withdrawn'}[cmd.kind]
        payload = {'id': offer['id'], 'actor_id': actor, 'status': status, 'action_id': aid}
        if cmd.kind == 'accept':
            payload['settlement'] = settlement(state, offer, aid)
        kind = 'trade.closed'
    audience = [offer['sender'], offer['recipient']]
    text = describe(state, offer, status)
    event = {'event_id': aid+'_trade', 'type': kind, 'visibility': {'kind': 'actors', 'actor_ids': audience}, 'payload': payload}
    events = [event, {'event_id': aid+'_trade_memory', 'type': 'memory.recorded', 'visibility': event['visibility'],
                     'payload': {'audience': audience, 'category': 'outcome', 'text': text,
                                 'source_event_ids': [event['event_id']], 'world_version': state['version']+1}}]
    if status == 'accepted':
        witnesses = [who for who in present(state, actor) if who not in audience]
        if witnesses:
            observation = state['actors'][offer['sender']]['name']+'与'+state['actors'][offer['recipient']]['name']+'完成了一次交易。'
            events.append({'event_id': aid+'_trade_observed', 'type': 'action.observed',
                           'visibility': {'kind': 'actors', 'actor_ids': witnesses}, 'payload': {'actor_id': actor, 'text': observation}})
            events.append({'event_id': aid+'_trade_witness_memory', 'type': 'memory.recorded',
                           'visibility': {'kind': 'actors', 'actor_ids': witnesses},
                           'payload': {'audience': witnesses, 'category': 'outcome', 'text': observation,
                                       'source_event_ids': [aid+'_trade_observed'], 'world_version': state['version']+1}})
    return events, text


def reduce_trade(state, event):
    from .world import apply_events

    p = event['payload']
    if event['type'] == 'trade.proposed':
        cmd = TradeCommand.model_validate(p['command'])
        if cmd.kind not in {'propose', 'counter'}:
            fail('报价事件类型无效')
        expected = proposal(state, cmd, p['actor_id'], p['action_id'])
        if expected != p['offer'] or expected['id'] in state.get('trades', {}):
            fail('报价条款与记录不一致')
        offer = expected
    elif event['type'] == 'trade.closed':
        offer = pending(state, p['id'])
        who = offer['sender'] if p['status'] == 'withdrawn' else offer['recipient']
        if p['status'] not in {'accepted', 'declined', 'withdrawn'} or p['actor_id'] != who:
            fail('报价回应者或状态无效')
        if p['status'] == 'accepted':
            if p.get('settlement') != settlement(state, offer, p['action_id']):
                fail('结算与双方同意的报价不一致')
        elif p.get('settlement'):
            fail('未成交的报价不能转移物资')
    else:
        fail('未知交易事件')
    if event['visibility'] != {'kind': 'actors', 'actor_ids': [offer['sender'], offer['recipient']]}:
        fail('报价可见范围错误')
    if event['type'] == 'trade.proposed':
        state.setdefault('trades', {})[offer['id']] = deepcopy(offer)
        if offer['counter_of']:
            state['trades'][offer['counter_of']]['status'] = 'countered'
    else:
        if p['status'] == 'accepted':
            state.update(apply_events(state, p['settlement'], state['version']))
        state['trades'][offer['id']]['status'] = p['status']


def project_trades(state, actor):
    rows = [o for o in state.get('trades', {}).values() if actor in {o['sender'], o['recipient']}]
    rows.sort(key=lambda o: (o['created_version'], o['id']))
    recent = [o for o in rows if o['status'] != 'pending'][-20:]
    rows = [o for o in rows if o['status'] == 'pending'] + recent
    result = []
    for row in rows:
        reason = None
        if row['status'] == 'pending':
            try:
                settlement(state, row, 'preview')
            except DomainError as exc:
                reason = exc.message
        result.append({**deepcopy(row), 'sender_name': state['actors'][row['sender']]['name'],
                       'recipient_name': state['actors'][row['recipient']]['name'], 'unavailable': reason})
    return result
