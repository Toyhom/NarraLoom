"""Source-preserving lexical retrieval. Visibility and branch ancestry precede ranking."""

import math
import re
from collections import Counter
from copy import deepcopy

from .contracts import DomainError


def tokens(text):
    text = text.casefold()
    result = re.findall(r'[a-z0-9_]+', text)
    for block in re.findall(r'[\u3400-\u9fff]+', text):
        result.extend(block[i:i+2] for i in range(len(block)-1))
        if len(block) == 1:
            result.append(block)
    return result


def records(state, actor_id):
    """Receive only this branch's reconstructed state, never a global corpus."""
    if actor_id not in state['actors']:
        raise DomainError('actor_missing', '角色不存在', 404)
    values = []
    for key in state['knowledge'][actor_id]:
        fact = state['beliefs'][actor_id][key]
        text = fact.get('value_labels', {}).get(str(fact['value']), str(fact['value']))
        values.append({'source_id': key, 'kind': 'known_fact', 'text': text,
                       'source_event_ids': [key], 'certainty': 'known_snapshot'})
    for memory in state['memories'][actor_id]:
        values.append({'source_id': memory['event_id'], 'kind': memory.get('category', 'historical_record'),
                       'text': memory['text'], 'source_event_ids': memory.get('source_event_ids', [memory['event_id']]),
                       'game_time_s': memory['game_time_s'], 'world_version': memory.get('world_version'),
                       'origin_story': memory.get('origin_story'),
                       'certainty': 'recorded_outcome' if memory.get('category') == 'outcome' else 'said_or_observed'})
    for note in state.get('notes', {}).values():
        if note['actor_id'] != actor_id:
            continue
        values.append({'source_id': note['id'], 'kind': note['kind'], 'text': note['text'],
                       'source_event_ids': note['source_event_ids'], 'status': note['status'],
                       'world_version': note['world_version'], 'certainty': 'player_note'})
    return values


def excerpt(text, query, limit):
    if len(text) <= limit:
        return text
    needles = tokens(query)
    positions = [text.casefold().find(t) for t in needles if t in text.casefold()]
    start = max(0, min(positions, default=0)-limit//4)
    return ('…' if start else '') + text[start:start+limit] + ('…' if start+limit < len(text) else '')


def retrieve(state, actor_id, query='', limit=12, char_budget=6000):
    corpus = records(state, actor_id)
    if not corpus:
        return []
    terms = set(tokens(query))
    counts = [Counter(tokens(row['text'])) for row in corpus]
    df = Counter(term for count in counts for term in terms if term in count)
    avg = sum(sum(c.values()) for c in counts)/len(counts) or 1
    ranked = []
    for i, (row, count) in enumerate(zip(corpus, counts, strict=True)):
        score = 0.0
        for term in terms & count.keys():
            tf = count[term]
            idf = math.log(1 + (len(corpus)-df[term]+.5)/(df[term]+.5))
            score += idf*tf*2.2/(tf+1.2*(.25+.75*sum(count.values())/avg))
        if terms and score == 0:
            continue
        # Stable tie-breaking prefers recent evidence; lexical evidence dominates.
        ranked.append((score, i, row))
    ranked.sort(key=lambda value: (value[0], value[1]), reverse=True)
    answer, used = [], 0
    for score, _, row in ranked[:limit]:
        text = excerpt(row['text'], query, min(900, max(0, char_budget-used)))
        if not text or used+len(text) > char_budget:
            break
        answer.append({**deepcopy(row), 'text': text, 'score': round(score, 4)})
        used += len(text)
        if used >= char_budget:
            break
    return answer


def context_memories(state, actor_id, query):
    recalled = retrieve(state, actor_id, query, limit=8, char_budget=4800)
    seen = {m['source_id'] for m in recalled}
    recent = [{'source_id': m['event_id'], 'kind': m.get('category', 'historical_record'),
               'text': m['text'][:500], 'source_event_ids': m.get('source_event_ids', [m['event_id']]),
               'game_time_s': m['game_time_s']} for m in state['memories'][actor_id][-4:]
              if m['event_id'] not in seen]
    return recalled + recent


def note_event(state, command):
    note = command['note_record']
    if command['mode'] != 'ooc' or command.get('selected_operation'):
        raise DomainError('invalid_note', '手记只能作为独立的游戏外操作', 422)
    from .players import command_player

    actor = command_player(state, command)
    sources = {s for row in records(state, actor) for s in [row['source_id'], *row['source_event_ids']]}
    if any(source not in sources for source in note['source_event_ids']):
        raise DomainError('unknown_source', '手记只能引用本分支角色已经获知的记录', 422)
    prior = state.get('notes', {}).get(note['id'])
    if prior and prior['actor_id'] != actor:
        raise DomainError('invalid_note', '不能修改其他角色的手记', 403)
    if not prior and len(state.get('notes', {})) >= 200:
        raise DomainError('notes_limit', '当前分支的手记已达200条，请更新已有条目', 422)
    return {'event_id': command['action_id']+'_note', 'type': 'note.updated',
            'visibility': {'kind': 'actors', 'actor_ids': [actor]},
            'payload': {**deepcopy(note), 'actor_id': actor, 'world_version': state['version']+1}}
