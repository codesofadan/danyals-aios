# The AI stack — `app/platform/ai/`

The model router, the LangGraph runtime, LangSmith tracing and the prompt registry.
Specified by [`docs/aios-v2/06-AI-STACK.md`](../../docs/aios-v2/06-AI-STACK.md); decided by
ADR-022, ADR-023 and ADR-024.

```
job (durable, app/jobs/)                    owns lifecycle, idempotency, retries, dead letter
  └── graph (LangGraph, checkpointed)       owns reasoning state: which nodes ran, what they made
        └── node
              └── ModelRouter.complete()    tier → model → cost gate → backend → commit → trace
                    └── SummarizerBackend   over integrations/llm.py (official Anthropic SDK)
```

---

## 1. Turning it on

Everything here is **off by default** and degrades rather than fails. Four switches:

| Setting | Default | What it does |
|---|---|---|
| `AI_GRAPHS_ENABLED` | `false` | Routes Web 2.0 drafting through `campaign_content` instead of the linear pipeline |
| `LANGSMITH_ENDPOINT` | `""` (off) | A trace destination is **chosen**, never inherited from a package being installed |
| `LANGSMITH_REDACT_CONTENT` | `true` | Spans carry digests, not client content. See §4 |
| `AI_ROUTER_STRICT_TIERS` | `true` | `reasoning`/`judge` refuse a backend that cannot think. See §3 |

Install and migrate:

```bash
./.venv/Scripts/python -m pip install -e ".[graph]"
PGPASSWORD=... psql -U postgres -d aios -f ../db/migrations/0148_langgraph_checkpoints.sql
```

**Both are required for durable graphs.** Without the extra, `campaign_content` raises
`GraphUnavailable` and the worker runs the linear path. Without the migration,
`PostgresSaver` cannot create its tables (neither runtime role may `CREATE` in `public` —
that is migrations' job) and the runtime falls back to an **in-memory** checkpointer with a
warning. Everything keeps working; nothing resumes. Check which you have:

```python
from app.config import get_settings
from app.platform.ai import graph
print(graph.runtime_state(get_settings()).describe)
# graphs on -> postgres checkpointer, durable
```

---

## 2. The router is the only door

`ModelRouter.complete(ModelRequest(...))` does six things that were previously done
differently at each of ~15 call sites:

1. picks the model from the **task tier**, never from a string a caller typed;
2. applies cache breakpoints (stable prefix first) when the backend can honour them;
3. passes the **cost gate before** the provider is contacted;
4. commits the **actual** cost, with cache reads at 0.1× and writes at 1.25× the input rate
   (`pricing.anthropic_cost_cached`);
5. emits the trace span with `client_id`, `job_id`, `module`, `task_tier`, `cost_cents`,
   `cache_hit` and the **prompt hash**;
6. translates provider errors into our taxonomy.

### Tiers (`tiers.py`)

| Tier | Model | Effort | For |
|---|---|---|---|
| `reasoning` | `claude-opus-5` | high + adaptive thinking | reconciliation, planning, narrative |
| `drafting` | `claude-opus-5` | medium | page drafting, Web 2.0 bodies |
| `structured` | `claude-sonnet-5` | medium | extraction, classification, platform shaping |
| `bulk` | `claude-haiku-4-5` | — | alt text, meta variants |
| `judge` | `claude-opus-5` | high + adaptive thinking | QA, grounding, eval graders |

An unknown tier raises `KeyError`. It never defaults: a cheap default silently downgrades
work that asked for reasoning, an expensive one silently multiplies a bulk job's bill.

### Estimating, and the trap in it

`max_tokens` is a **runaway ceiling, not a purchase**. Sizing the pre-call estimate from it
priced a 900-word article at ~$0.20 instead of ~$0.03 — and the estimate is what the cost
gate decides on, so a client on a $5 daily budget would have been refused after 25 articles
it could easily afford. Pass `expected_output_tokens`; the default is
`DEFAULT_EXPECTED_OUTPUT_TOKENS` (1500). A variance past ±25% logs `model_cost_variance`,
which is the signal that an estimator is wrong.

### Migrating an existing caller

`RouterSummarizer` is a `SystemSummarizer` that routes. Hand it to any existing caller and
every call it makes becomes tier-routed, gated, priced and traced **with no change to the
caller**:

```python
writer = RouterSummarizer(router, task=TaskTier.DRAFTING, module="web2", feature_key="content")
article = write(plan, writer=writer)     # content_generator, 1,000 lines, untouched
```

This retires the duplicated `_Web2GatedWriter` / `_ContentGatedWriter` wrappers — the same
class written twice, each re-deriving cost from `input_tokens` alone and therefore pricing
every cached call wrong.

---

## 3. Backends and the capability rule

One backend class covers both real cases, because the difference is configuration:

| `anthropic_base_url` | Backend name | Prompt cache |
|---|---|---|
| unset | `anthropic` | advertised |
| set (the proxy this deployment uses) | `agentrouter` | **not** advertised — a proxy cannot guarantee it, and claiming a cache hit we cannot substantiate corrupts the one number §4 says to verify rather than assume |

Neither can do `effort` or adaptive thinking through this seam. So (ADR-024):

- **`reasoning` / `judge` raise `CapabilityMissingError`.** A judge that does not think is a
  different grader, not a cheaper one.
- **`drafting` / `structured` / `bulk` proceed and record** the degradation on
  `ModelResult.degraded`, in the log, and in the span.

`AI_ROUTER_STRICT_TIERS=false` moves that line deliberately.

---

## 4. Tracing, and what never leaves the process

Traces contain client page content, NAP data and business descriptions. So:

- `LANGSMITH_ENDPOINT` blank ⇒ no tracing at all.
- `LANGSMITH_REDACT_CONTENT` (default **on**) replaces content-bearing fields with a stable
  16-char digest plus a length. A span still answers *"did these two properties get the same
  prompt?"* — the Web 2.0 failure mode the similarity gate exists for — without carrying a
  syllable of the client's business.
- Redaction keys off field **name**, never by sniffing values: a value-based rule cannot tell
  a business description from a model id and would eventually let one through.
- Pointing at `api.smith.langchain.com` logs a warning naming ADR-019's requirements
  (signed-off ADR, PII redaction, DPA note).
- **Nothing in `tracing.py` raises into the caller.** A trace store that is down must not
  take a client's campaign down with it.

`tracing.configure(settings)` is called from `app/main.py` and `workers/celery_app.py`. It
arms a process-global SDK through environment variables; `tracing.reset()` disarms it (the
unit suite depends on this — an armed SDK keeps a background thread POSTing).

---

## 5. Prompts are code

`app/platform/ai/prompts/**/*.md`, each with frontmatter (`id`, `version`, `task_tier`,
`inputs`, `outputs`, `changelog`) and a hash **over the text only** — so a changelog fix does
not break the link between an article and the bytes that wrote it, while an instruction
change does. The hash rides in every span, so any output traces back to the exact prompt.

A malformed file fails the **load**, not the call: a registry that quietly drops the one file
that failed to parse hands a `PromptNotFoundError` to a worker at 3am for a file sitting in
git. A missing placeholder raises naming the prompt, rather than shipping a literal
`{topic}` into a client's article.

---

## 6. Graphs

`graph.py` is the runtime: `checkpointer()`, `run()`, `parked()`, `interrupt_payload()`,
`thread_id_for()`.

- **The thread id equals the job's idempotency identity**, so a redelivered job attaches to
  its own run instead of forking a second one beside it.
- **No node retries internally.** Retry belongs to the job engine — a node that swallows a
  failure hides it from the retry ledger.
- **Resuming a thread that does not exist raises `GraphThreadMissing`.** LangGraph would
  otherwise treat a missing checkpoint as a *fresh run*, which for an approval endpoint means
  re-drafting and re-billing the article instead of applying the decision.
- Checkpoints live in the same Postgres as jobs, `ENABLE`+`FORCE` RLS with **no policy** —
  default-deny for `authenticated`, written only by `service_role` (BYPASSRLS).

### `campaign_content` (Module 05)

```
load → shape → draft → gate → persist_draft → ⏸ await_approval → queue_publish
                                                              ↘ rejected
```

`load`, `draft`, `gate`, `persist_draft`, `queue_publish` and `rejected` are IO nodes; the
rest are pure. `shape` is the one genuinely new stage — it turns the platform's measured
capability row (migration 0135) into the constraint note the writer drafts against, because
v1 posted the same 900-word blog article to a developer community, a microblog and a paste
site. Individually fine; collectively a clearer footprint than any content-level check sees.

Everything else **calls** v1's measured logic rather than rewriting it: the similarity gate,
the anchor rules, the `[NEEDS:]` grounding discipline and the contextual link placement are
unchanged.

**Parking is success.** The graph stopping at `await_approval` means the article exists, the
row is at `needs_review`, and a lead owes a decision. `POST /offpage/web2/{id}/approve`
delivers it back — best-effort and non-authoritative: the endpoint still owns RBAC, the live
similarity re-check, lane routing and the row transitions. A `GraphThreadMissing` there is
the **ordinary** case on a deployment that drafts linearly.

---

## 7. Keeping it honest

| Guard | Where | Catches |
|---|---|---|
| `test_langgraph_checkpoint_schema.py` | unit | a LangGraph upgrade adding DDL our migration does not seed — which would silently drop production onto a non-durable checkpointer |
| `test_ai_router.py` | unit | tier→model routing, gate-before-provider, cache-aware actual cost, the estimate trap, capability blocking |
| `test_ai_tracing.py` | unit | that no content value survives scrubbing, in any form |
| `test_web2_campaign_graph.py` | unit | that a resume replays **no model call** — if this regresses, the checkpoint is decorative |
| `test_offpage_worker.py` | unit | the flag is off by default; the fallback still drafts; a graph fault never re-raises |
