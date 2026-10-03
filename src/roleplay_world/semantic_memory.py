"""Optional hybrid recall over one actor's source records in one branch snapshot."""

import asyncio
import hashlib
import json
import time
from array import array
from collections import OrderedDict
from copy import deepcopy
from typing import Annotated

from pydantic import Field

from .contracts import Contract, DomainError
from .journal import digest
from .memory import context_memories, records, retrieve
from .settings import MODEL_OWNER, MemoryPolicy


class RecallRequest(Contract):
    query: Annotated[str, Field(min_length=1, max_length=4000)]
    limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 8


class SemanticMemory:
    """Vectors are a bounded disposable cache; canonical records stay in the journal."""

    def __init__(self, gateway):
        self.gateway = gateway
        self.cache = OrderedDict()
        self.signatures = OrderedDict()
        self.floats = 0
        self.lock = asyncio.Lock()

    def discard(self, namespace):
        for key in [key for key in self.cache if key[0] == namespace]:
            self.floats -= len(self.cache.pop(key))
        self.signatures.pop(namespace, None)

    def put(self, key, vector):
        previous = self.cache.pop(key, ())
        value = array('f', vector)
        self.cache[key] = value
        self.floats += len(value) - len(previous)
        while len(self.cache) > 2048 or self.floats > 2097152:
            self.floats -= len(self.cache.popitem(last=False)[1])
        return value

    async def vectors(self, texts, action_id, budget, stats, config, perspective):
        # Credential changes, model revisions and transport options invalidate cached vectors.
        identity = json.dumps({'owner': MODEL_OWNER.get(), 'perspective': perspective, 'config': config,
                               'auth': self.gateway.auth_headers(config)}, sort_keys=True, ensure_ascii=False)
        namespace = hashlib.sha256(identity.encode()).hexdigest()
        keys = [(namespace, hashlib.sha256(text.encode()).hexdigest()) for text in texts]
        async with self.lock:
            found = {key: self.cache[key] for key in set(keys) if key in self.cache}
            for key in found:
                self.cache.move_to_end(key)
            stats['cache_hits'] = len(found)
            missing = list(dict.fromkeys(key for key in keys if key not in found))
            inputs = dict(zip(keys, texts, strict=True))
            batches, batch = [], []
            for key in missing:
                def size(candidate):
                    return len(json.dumps({'model': config.get('model', ''), 'input': [inputs[k] for k in candidate],
                                           'encoding_format': 'float'}, ensure_ascii=False))
                if size([key]) > config.get('context_chars', 120000):
                    raise DomainError('context_limit', 'A memory chunk exceeds the embedding context budget', 422)
                if batch and (len(batch) == 64 or size([*batch, key]) > config.get('context_chars', 120000)):
                    batches.append(batch)
                    batch = []
                batch.append(key)
            if batch:
                batches.append(batch)
            # Preflight the whole cold corpus; a partial index never substitutes for full recall.
            if len(batches) > budget['max_calls'] - budget['calls']:
                raise DomainError('embedding_budget', 'Cold memory index exceeds the remaining call budget', 422)
            for batch in batches:
                result = await self.gateway.embed('memory_embedding', [inputs[key] for key in batch], action_id, budget,
                                                  configuration=config)
                signature = (result['model'], len(result['vectors'][0]))
                if namespace in self.signatures and self.signatures[namespace] != signature:
                    self.discard(namespace)
                    raise DomainError('embedding_revision_changed', 'Embedding model or dimension changed; retry with a pinned revision', 502)
                self.signatures[namespace] = signature
                self.signatures.move_to_end(namespace)
                while len(self.signatures) > 128:
                    self.discard(next(iter(self.signatures)))
                for key, vector in zip(batch, result['vectors'], strict=True):
                    found[key] = self.put(key, vector)
            return [found[key] for key in keys]

    async def recall(self, state, actor, query, action_id, budget, *, limit=8, char_budget=4800, scope=None):
        policy = MemoryPolicy.model_validate(self.gateway.effective_config().get('memory_policy', {}))
        baseline = retrieve(state, actor, query, limit, char_budget)
        if policy.mode == 'lexical' or not query.strip():
            return baseline
        started = time.monotonic()
        stats = {'mode': 'hybrid', 'records': 0, 'chunks': 0, 'cache_hits': 0}
        trace = {'role': 'memory_retrieval', 'status': 'ok', 'retrieval': stats}
        try:
            corpus = records(state, actor)
            stats['records'] = len(corpus)
            if not corpus:
                return []
            chunks = []
            for index, row in enumerate(corpus):
                text = row['text']
                for start in range(0, len(text), 600):
                    chunks.append((index, text[start:start + 800]))
                    if len(chunks) > policy.max_chunks:
                        raise DomainError('memory_corpus_limit', 'Memory corpus exceeds the configured chunk limit', 422)
                    if start + 800 >= len(text):
                        break
            stats['chunks'] = len(chunks)
            if not chunks:
                return []
            config = self.gateway.role_config('memory_embedding')
            auxiliary = budget.setdefault('_memory_budget', {
                'calls': 0, 'max_calls': policy.max_calls, 'traces': budget['traces']})
            texts = [config.get('query_prefix', '') + query]
            texts.extend(config.get('document_prefix', '') + text for _, text in chunks)
            perspective = {'actor': actor, 'branch': scope or digest(corpus)}
            vectors = await self.vectors(texts, action_id, auxiliary, stats, deepcopy(config), perspective)
            query_vector, documents = vectors[0], vectors[1:]
            best = {}
            for (index, text), vector in zip(chunks, documents, strict=True):
                if len(vector) != len(query_vector):
                    raise DomainError('invalid_embedding_output', 'Cached embedding dimensions differ', 502)
                similarity = sum(a * b for a, b in zip(query_vector, vector, strict=True))
                if index not in best or similarity > best[index][0]:
                    best[index] = (similarity, text)
            semantic = sorted((index for index in best if best[index][0] >= policy.min_similarity),
                              key=lambda index: (best[index][0], index), reverse=True)
            lexical = retrieve(state, actor, query, len(corpus), sum(len(row['text']) + 2 for row in corpus))
            lexical_ranks = {row['source_id']: rank for rank, row in enumerate(lexical, 1)}
            semantic_ranks = {index: rank for rank, index in enumerate(semantic, 1)}
            scores = {}
            for index, row in enumerate(corpus):
                score = 0
                if row['source_id'] in lexical_ranks:
                    score += 1 / (20 + lexical_ranks[row['source_id']])
                if index in semantic_ranks:
                    score += 1 / (20 + semantic_ranks[index])
                if score:
                    scores[index] = score
            fused = sorted(scores, key=lambda index: (scores[index], index), reverse=True)
            # Reserve candidates from both signals. Repeated common-word matches
            # cannot crowd an old paraphrased source out of the semantic shortlist.
            by_id = {row['source_id']: index for index, row in enumerate(corpus)}
            quota = max(1, limit // 2)
            selected = list(dict.fromkeys([
                *semantic[:quota], *[by_id[row['source_id']] for row in lexical[:quota]], *fused]))[:limit]
            selected.sort(key=lambda index: (scores[index], index), reverse=True)
            answer, used = [], 0
            for index in selected:
                snippet = best.get(index, (0, corpus[index]['text']))[1][:min(900, char_budget - used)]
                if not snippet:
                    break
                answer.append({**deepcopy(corpus[index]), 'text': snippet, 'score': round(scores[index], 6),
                               'similarity': round(best[index][0], 6) if index in best else None})
                used += len(snippet)
                if used >= char_budget:
                    break
            stats['returned'] = len(answer)
            return answer
        except asyncio.CancelledError:
            trace['status'] = 'cancelled'
            raise
        except (DomainError, ValueError, TypeError, OSError) as exc:
            trace.update(status='fallback' if policy.failure == 'lexical' else 'failed',
                         error=exc.code if isinstance(exc, DomainError) else 'memory_retrieval_failed')
            if policy.failure == 'error':
                raise
            return baseline
        finally:
            trace['duration_s'] = round(time.monotonic() - started, 4)
            budget['traces'].append(trace)


async def recalled_context(gateway, state, actor, query, action_id, budget, *, scope=None):
    service = getattr(gateway, 'memory', None)
    if service is None or gateway.effective_config().get('memory_policy', {}).get('mode', 'lexical') == 'lexical':
        return context_memories(state, actor, query)
    recalled = await service.recall(state, actor, query, action_id, budget, scope=scope)
    seen = {row['source_id'] for row in recalled}
    recent = [{'source_id': row['event_id'], 'kind': row.get('category', 'historical_record'),
               'text': row['text'][:500], 'source_event_ids': row.get('source_event_ids', [row['event_id']]),
               'game_time_s': row['game_time_s']} for row in state['memories'][actor][-4:]
              if row['event_id'] not in seen]
    return recalled + recent
