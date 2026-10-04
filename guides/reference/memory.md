# Source-preserving memory retrieval

NarraLoom retrieves a character's known facts, observed events and personal notes from the current branch snapshot. Each result retains its source ID, source event IDs and certainty. A remembered statement stays a statement; recall changes the model's context while canonical facts remain governed by events.

Keyword retrieval works without a model service. Optional hybrid retrieval reserves candidates from keyword and embedding rankings, then orders the combined shortlist using reciprocal rank fusion. It can recover older records when a player paraphrases a subject or asks in another language. Choose an embedding model that supports the languages of your content.

## Configure an embedding module

Add a named provider and explicit `memory_embedding` binding to your deployment configuration:

```json
{
  "providers": {
    "memory": {
      "backend": "openai_embedding",
      "url": "http://127.0.0.1:18112/v1",
      "api_key_env": "NARRALOOM_EMBEDDING_API_KEY",
      "context_chars": 120000,
      "timeout_s": 30,
      "query_prefix": "",
      "document_prefix": ""
    }
  },
  "bindings": {
    "memory_embedding": {
      "provider": "memory",
      "model": "BAAI/bge-m3",
      "revision": "your-deployed-checkpoint-revision"
    }
  },
  "memory_policy": {
    "mode": "hybrid",
    "failure": "lexical",
    "max_calls": 12,
    "max_chunks": 1024,
    "min_similarity": 0.2
  }
}
```

Merge these entries with the generation-model configuration. In the reference frontend, open **Models & usage**, add an **OpenAI-compatible embeddings** provider, bind **Memory embeddings**, select hybrid retrieval and save. The module connection check verifies vector shape and finite values. It uses the embedding provider's own credential.

`query_prefix` and `document_prefix` follow the selected model's instructions. For example, multilingual E5 uses `query: ` and `passage: `; BGE-M3 uses plain text. Prefixes affect both transport inputs and the cache identity. An ordinary chat endpoint needs a separate embedding service to supply vectors.

## Use local models or Python adapters

The optional example loads a local Transformers model and serves a loopback embedding API:

```bash
python -m pip install '.[embedding]'
python examples/transformer_embedding.py \
  --model-path /path/to/bge-m3 --model-id BAAI/bge-m3 \
  --device cpu --pooling cls --port 18112
```

Download the chosen model into your configured model directory first. On shared GPU hosts, submit a CUDA invocation through the host's scheduler. The example retains its assigned device visibility, batches inference and stops after `--max-runtime-s` (default 3600 seconds). It rejects inputs exceeding `--max-tokens` instead of silently truncating them. Select `cls` or `mean` pooling according to the model card.

For native embedding, register an `Engine` with capability `embed`. Its async `invoke(config, payload, auth_headers)` receives `model`, `input` (a list of texts) and `encoding_format: float`. Return `{model, vectors, usage?}` in input order. Vectors must be finite, nonzero and have a consistent dimension from 1 to 8192. The gateway normalizes them before cosine comparison. `TransformerEmbedding.engine()` in the example supplies a ready native adapter; register it and bind backend `transformer_embedding` to the configured model ID.

## Runtime, API and SDK

Hybrid recall supplies the planner's player view, each speaking NPC's own view and autonomous NPC decisions. Recent observations remain in context alongside retrieved records. Narration follows the normal committed-view pipeline.

```python
result = await client.recall(campaign_id, branch_id,
                             "Where did we agree to return the borrowed instrument?", limit=8)
for record in result["records"]:
    print(record["text"], record["source_event_ids"])
```

`POST /api/campaigns/{cid}/branches/{bid}/recall` accepts `{query, limit}` and returns `{world_version, records, diagnostics}`. It uses an immutable snapshot for that request and may make embedding calls. `POST /api/rooms/{rid}/recall` uses the member's controlled character and the host's configured service. Both require the normal session and CSRF token. Existing `GET .../memories` endpoints retain keyword-only, model-free behavior.

## Budgets, caching and recovery

Records are split into overlapping 800-character chunks with a 600-character stride. Requests contain up to 64 unique texts and fit the provider's configured character budget. `max_chunks` bounds the complete candidate corpus; `max_calls` bounds auxiliary embedding calls across a whole action, including all participating characters. Generation retains its own call budget. Initial recall builds a cold index; subsequent turns usually embed new records and the query.

The shortlist reserves half the requested count for each ranking (rounded down, with at least one semantic candidate), then fills remaining slots by fused rank. This keeps repeated common-word matches from crowding out a strong semantic result. A one-result query prioritizes its best semantic candidate; exact keyword lookup remains available through the model-free endpoint.

The cache stores normalized vectors keyed by owner, actor, branch, provider configuration, credential identity and text digest. It holds up to 2048 entries and 2,097,152 float32 values. Source records and permissions are reselected from the current actor/branch on every request. Changed text, endpoint, prefixes or configured revision get new cache identities. A changed returned model ID or dimension invalidates the affected cache and reports `embedding_revision_changed`. Direct Python callers can supply `scope=branch_id`; an omitted scope uses the visible corpus digest for isolation.

With `failure: lexical`, service errors or exhausted limits return keyword results and record the reason. With `failure: error`, these conditions fail the request for strict evaluation. Diagnostics distinguish successful hybrid recall, fallback and cancellation. Public diagnostics expose counts and model metadata; raw server traces contain the submitted texts and belong in the host's private workspace.

Vectors are disposable process-local data. Restarting rebuilds them on demand. Saved events, committed receipts, backups and branches replay without embeddings. Cancellation during retrieval leaves canonical world state unchanged. Pin model revisions when reproducible rankings matter.

## Verify recall quality

`tests/test_semantic_memory.py` covers transport validation, source/actor/branch isolation, cache invalidation, limits, cancellation, API ownership and runtime integration. A real-service check is available:

```bash
python scripts/check_semantic_memory.py \
  --models-config configs/models.local.json --secrets-root secrets \
  --embedding-url http://127.0.0.1:18112/v1 --embedding-model BAAI/bge-m3 \
  --output outputs/validation/memory-live
```

It seeds a fixed history, compares keyword and hybrid recall on multilingual paraphrases, checks source isolation, then runs an actual planner/character exchange and restart recovery. The seeded history measures retrieval over older records; longer model-generated campaigns and independent playtests assess story continuity and dialogue quality. Cosine scores and retrieval rank are relevance signals, separate from the certainty of a source record.
