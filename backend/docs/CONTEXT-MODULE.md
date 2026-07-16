# Context / AI-memory module (Part 6B)

A per-entity **living context**: every client / site / user carries a bounded,
self-superseding summary + keyed facts + a vector index, kept fresh from the
activity log. It is the one door the AI layer (Content, audit narrative, assistant)
reads through to get an entity's CURRENT state without re-reading raw history.

**Governing principle: Postgres is the source of truth; Pinecone is a DERIVED
index.** The `context_vectors` ledger is the authority for what is embedded; the
vector store is fully reconstructable from it. A vector-store outage can never
corrupt the source of truth.

## The pipeline (event backbone → retrieval)

```
mutation → activity_log INSERT
   └─(0013 AFTER-INSERT trigger)→ public.context_dirty     (debounced enqueue, per entity)
        └─(Celery beat: dispatch_context)→ claim due rows FOR UPDATE SKIP LOCKED
             └─ compact_context.delay(entity)
                  └─ execute_compaction  (workers/tasks/context.py — the pure core)
                       ├─ compact()            fold events LWW-by-seq → summary + facts + chunks
                       ├─ sync_vectors()       embed ONLY changed chunks; GC superseded from BOTH stores
                       └─ upsert_context()     the SINGLE atomic write → entity_context (status='summarized')
```

Retrieval: `GET /api/v1/context/{type}/{id}[?query&fresh]` → `context_service.get_context`
returns `summary` + `facts` + top-k `chunks` (namespace-scoped to the entity) plus an
explicit freshness signal. `GET /api/v1/context/health` is the org rollup;
`GET /api/v1/portal/context` is a client's own summary+facts via the security-barrier view.

Reconcile: a slow beat (`reconcile_context_vectors`) walks every entity with vectors
and detects (optionally repairs) ledger-vs-store drift — the safety net for a lost
upsert / delete the write path missed.

## The freshness invariant

```
lag = max(latest_seq − event_watermark, 0)       # latest_seq = the entity's highest activity_log.seq
stale = lag > 0  OR  status ∉ {summarized}
fresh (caught up)  ⇔  event_watermark ≥ latest_seq
```

Check it at a glance:

```bash
# per entity
curl -H "Authorization: Bearer $TOKEN" .../api/v1/context/client/$ID/health
#   → { status, event_watermark, latest_seq, lag, stale, ... }
# org-wide rollup
curl -H "Authorization: Bearer $TOKEN" .../api/v1/context/health
#   → { total, stale, degraded, error, worst_lag }
```

`lag == 0 && stale == false` means the context is current. A degraded/stale entity
still serves (never blocks, never lies); `?fresh=true` runs a bounded, cost-gated
synchronous recompaction before serving.

## Provider keys (deferred — fakes until then)

The real providers are lazy-imported from the optional `[ai]` extra
(`pip install -e '.[ai]'`) and are key-gated: `context_providers_from_settings`
returns the REAL bundle only when ALL are set, else `None` (degraded — appends
events, marks `status='degraded'`, HOLDS the watermark so lag stays visible).

| Setting | Provider | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic Claude | the living-summary prose (Summarizer) |
| `EMBEDDINGS_API_KEY` | Voyage AI (`voyage-3`, dim 1024) | chunk embeddings (Anthropic has no embeddings API) |
| `PINECONE_API_KEY` + `PINECONE_INDEX` | Pinecone | the derived vector index (namespace = `entity_type:entity_id`) |

Until the keys land, the whole module runs on deterministic fakes
(`FakeSummarizer` / `FakeEmbedder` / `InMemoryVectorStore`) so the worker, retrieval,
and freshness suites run fully live with no external calls. The live end-to-end
proof (`tests/integration/test_context_live.py`) auto-SKIPS without keys and activates
the moment they are supplied.

## Cost dial (money-dial features)

Every context AI call flows through the Part-2 cost gate
(`dial → cache → client cap → daily spend-stop → call+log`) — no context spend can
bypass it. Two dial features:

* **`context`** — the summarize (LLM) spend (`context_summarize_cost_estimate`).
* **`context_embed`** — the embeddings spend (`context_embed_cost_estimate`); cached
  on the content checksum, so re-embedding UNCHANGED text is a `$0` gate hit.

Turning a feature `off` / `byhand`, or hitting a client cap / the daily spend-stop,
raises `ContextSpendBlocked`, which the worker DEGRADES on (holds the watermark) —
it never crashes and never blocks the originating mutation.
