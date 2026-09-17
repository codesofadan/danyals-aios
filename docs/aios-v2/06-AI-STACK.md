# 06 · AI Stack

**Decision:** LangGraph is the orchestration layer for multi-step AI work. The model call
itself goes through our own router, which wraps the **official Anthropic SDK**. LangChain
is used only where an adapter genuinely saves work. LangSmith traces everything. Sentry
catches what breaks.

---

## 1. Why this shape

LangGraph earns its place for one reason: **checkpointed, resumable graph state**. That is
the same property the durable job engine provides for jobs, and the two compose — a job
owns the lifecycle, the graph owns the reasoning state, both checkpoint to the same
Postgres. A content run that dies at page 31 of 50 resumes at page 31, mid-graph.

LangChain's chat-model abstraction is deliberately **not** in the hot path. It lags the
Anthropic API by weeks on exactly the features that matter here — adaptive thinking,
`output_config.effort`, prompt-cache breakpoint placement, strict tool schemas. A thin
router over the official SDK costs ~200 lines and removes that lag permanently.

```
  job (durable, Postgres)
    └── graph (LangGraph, checkpointed to Postgres)
          └── node
                └── ModelRouter.complete(...)   ← our code
                      ├── AnthropicBackend   (official SDK, default)
                      └── AgentRouterBackend (OpenAI-compatible proxy, fallback)
                            └── LangSmith trace + cost ledger commit
```

---

## 2. Where LangGraph is used

| Module | Graph | Why a graph rather than a function |
|---|---|---|
| **M03 Content** | `content_page` | 8+ stages with conditional loops (repair, regenerate), long runtime, and a real need to resume mid-page |
| **M03 Content** | `design_extraction` | Multi-source evidence (computed styles + vision) that must be reconciled with provenance |
| **M03 Content** | `page_set_proposal` | Iterative planning with a human-approval interrupt |
| **M04 Citations** | `form_fill` | Observe → heuristic → model → self-check → stage, with a cache short-circuit |
| **M04 Citations** | `account_creation` | Long-lived, waits on an external event (email verification), must survive a worker restart |
| **M05 Web 2.0** | `campaign_content` | Fan-out per platform with per-platform constraint solving |
| **M02 Audit** | `audit_narrative` | Multi-section synthesis over findings JSON |
| **M06 Policy Radar** | `policy_digest` | Source sweep → change detection → per-client exposure |

Everything else — a single classification, a title rewrite, an alt-text generation — is a
**direct router call**. Wrapping a one-shot call in a graph is overhead with no return.

### Graph conventions

- **State is a Pydantic model**, never a loose dict. It is the graph's contract.
- **Checkpointer:** `PostgresSaver` against the same database, in the same schema family
  as jobs. Checkpoints are garbage-collected with their job.
- **Every node is pure over its inputs** except designated IO nodes, which are the only
  place a provider is touched. This is what makes graphs unit-testable with fakes.
- **Human-in-the-loop uses `interrupt()`**, not polling. The graph parks; the review
  queue holds the item; resuming injects the decision.
- **Every node emits a LangSmith span** with `client_id`, `job_id`, `module` and cost.
- **No node retries internally.** Retry is the job engine's job — a node that swallows a
  failure hides it from the retry ledger.

---

## 3. The model router

One module, `platform/ai/router.py`. Every model call in the system goes through it.

```python
class ModelRouter:
    async def complete(
        self,
        *,
        task: TaskTier,             # what kind of work this is
        messages: list[MessageParam],
        system: str | list[TextBlockParam] | None = None,
        tools: list[ToolParam] | None = None,
        schema: type[BaseModel] | None = None,   # structured output
        client_id: UUID | None,
        job_id: UUID | None,
    ) -> ModelResult: ...
```

It is responsible for: choosing the model from the task tier, applying the cache
breakpoints, passing the cost gate, calling the backend, committing actual cost from real
token usage, emitting the trace, and translating provider errors into our taxonomy.

**Nothing else in the codebase imports `anthropic` directly.** A CI check enforces it.

### Task tiers → models

| Tier | Model | Effort | Used for |
|---|---|---|---|
| `reasoning` | `claude-opus-5` | `high` | Design extraction reconciliation, page-set planning, audit narrative, policy exposure analysis, citation field mapping on a cache miss |
| `drafting` | `claude-opus-5` | `medium` | Page drafting, Web 2.0 post bodies, GBP posts |
| `structured` | `claude-sonnet-5` | `medium` | Extraction to a fixed schema, classification, intent labelling, clustering labels |
| `bulk` | `claude-haiku-4-5` | — | Alt text, title/meta variants, description variants, tag suggestions — high volume, low stakes |
| `judge` | `claude-opus-5` | `high` | QA scorecard, grounding checks, eval graders. **Never the same tier as the generator** |

Model IDs are exactly as written — no date suffixes. Current pricing (input / output per
1M tokens): Opus 5 **$5 / $25** · Sonnet 5 **$2 / $10** · Haiku 4.5 **$1 / $5**. These
feed the cost estimator directly; the table lives in one config object, not scattered.

### Call defaults

- `thinking={"type": "adaptive"}` on every `reasoning` and `judge` call. Do **not** pass
  `budget_tokens` — it is rejected with a 400 on Opus 5 and Sonnet 5.
- Depth is controlled with `output_config={"effort": ...}`, not by thinking budgets.
- **Stream** any call with a large `max_tokens`; use the SDK's `get_final_message()`.
  Non-streaming defaults to `max_tokens≈16000`; streaming to `≈64000`.
- **No assistant prefill** — it returns 400 on Opus 5 / Sonnet 5. Shape output with
  structured outputs or system instructions.
- Structured output via `output_config={"format": ...}` and `client.messages.parse()`,
  never by asking for JSON in a prompt and regexing the reply.
- Tool schemas use `strict: true` with `additionalProperties: false`, so tool inputs
  validate exactly. Always `json.loads()` a tool input; never string-match it.
- Errors are caught most-specific-first (`NotFoundError` → `RateLimitError` →
  `APIStatusError` → `APIConnectionError`) and mapped to our taxonomy.

### Backends

| Backend | When | Notes |
|---|---|---|
| **`AnthropicBackend`** (default) | A direct Anthropic API key is configured | The only backend with full feature support — adaptive thinking, effort, cache diagnostics, batches |
| **`AgentRouterBackend`** | Configured explicitly as a fallback | An OpenAI-compatible proxy. **Feature-degraded by definition**: no adaptive thinking, no effort control, no cache guarantees. The router must not silently fall back to it — a call requiring a feature the backend lacks raises `CapabilityMissingError` and the job blocks |

**Rule:** the backend is chosen by configuration, never by code branching on a model name.
A change of backend must never change output quality silently; if it would, it blocks.

---

## 4. Prompt caching

At this volume, caching is the difference between a viable cost model and an unviable one.
A 50-page content run reuses the same client context 50 times.

**Rules:**
- Render order is `tools` → `system` → `messages`. **Stable content first.** A single byte
  changed in the prefix invalidates everything after it.
- Cache the client context block (profile, NAP, DesignIR tokens, keyword bank slice) as a
  system block with `cache_control: {"type": "ephemeral"}`.
- Volatile content — the specific page brief, timestamps, per-request ids — goes **after**
  the last breakpoint. Never interpolate a timestamp into a cached prefix.
- Maximum 4 breakpoints per request; minimum cacheable prefix ≈1024 tokens.
- **Verify, don't assume:** `usage.cache_read_input_tokens` is logged on every call and
  charted per module. A module whose cache-hit rate drops below its baseline raises an
  alert — that is how a silent invalidator gets caught.
- Any JSON serialised into a cached prefix is serialised with sorted keys.

**Batch API** for anything not latency-sensitive (bulk alt text, description variants,
re-scoring a calibration set) — 50% cost, results keyed by `custom_id`, never by position.

---

## 5. Cost control

Every router call:

1. Estimates tokens with `messages.count_tokens` (never `tiktoken`, never a character
   heuristic) and prices the estimate from the model table.
2. Calls `CostGate.check(module, client, estimate)`. A block raises `CostBlockedError`
   **before** the provider is contacted.
3. On return, commits the **actual** cost from `usage`, including cache reads and writes
   at their own rates.
4. Records the variance. A module whose actual consistently exceeds estimate by >25% has a
   broken estimator and raises a task.

Per-module budgets are money dials (`off` / `by_hand` / `on`). `by_hand` means the call is
queued for human approval rather than refused — the operator sees what it would cost and
approves or declines.

---

## 6. Tracing and observability

| Tool | Scope | Notes |
|---|---|---|
| **LangSmith** | Every model call and every graph run | Project per environment. Metadata: `client_id`, `job_id`, `module`, `task_tier`, `cost_cents`, `cache_hit` |
| **Sentry** | Backend, frontend, extension | Errors and performance. Release-tagged, correlation id attached |
| **OpenTelemetry** | HTTP → job → provider spans | One correlation id end to end |
| **Structured logs** | Everything | JSON, correlation id, never a secret, never raw client content |

**LangSmith hosting decision:** self-hosted is preferred because traces contain client page
content, NAP data and business descriptions. If hosted SaaS is used instead, it requires
an explicit owner decision recorded as an ADR, PII redaction on inputs, and a note in the
client DPA. **Default: self-hosted; hosted only with a signed-off ADR.**

**Sentry hosting:** SaaS is acceptable with `send_default_pii=False`, a `before_send`
scrubber that strips credentials, NAP, emails and page bodies, and the extension
configured never to attach page content to an event.

---

## 7. Prompt management

Prompts are **code**, versioned in the repository, not rows in a database and not strings
inline in a service.

```
platform/ai/prompts/
  content/draft.v3.md        outline.v2.md     qa_judge.v4.md
  citations/field_map.v2.md  account_create.v1.md
  design/reconcile.v2.md
  ...
```

- Each file has YAML frontmatter: `id`, `version`, `task_tier`, `inputs`, `outputs`,
  `changelog`.
- Prompts are loaded once at startup and hashed; the hash goes into every trace, so any
  output can be traced back to the exact prompt that produced it.
- A prompt change is a version bump and a PR, and it **must** re-run the eval suite for
  its module. A prompt change that lowers an eval score is rejected like any regression.

---

## 8. Evals

`REQ-X-009`. Without these, prompt changes are guesswork.

| Suite | Fixtures | Metric | Gate |
|---|---|---|---|
| **Content quality** | 30 human-graded drafts across page types (the QA calibration set) | Correlation between machine QA score and human grade; per-dimension error | Correlation ≥ 0.75, no dimension worse than baseline |
| **Grounding** | Drafts with injected unsupported claims | Detection rate of unsupported claims | ≥ 95% caught, ≤ 5% false positives |
| **Design conformance** | 10 captured sites with known token sets | Every token used by a generated page exists in the approved DesignIR | 100% — this is a hard invariant, not a score |
| **Form fill** | 25 saved directory form fixtures, including 5 with honeypots | Correct field mapping rate; honeypot touch rate | ≥ 95% mapping, **0% honeypot touches** |
| **Intent classification** | 200 labelled keywords | Accuracy vs labels | ≥ 90% |
| **Audit findings** | 5 sites with known defects | Recall of known defects; false-positive rate | Recall ≥ 90%, FP ≤ 10% |

Evals run in CI against fixed fixtures using the **cheapest tier that is representative**,
with a nightly full run at production tiers. Results are stored, so drift is visible as a
time series rather than discovered in a client complaint.

**Judge independence:** the eval grader never uses the same prompt, and never the same
tier configuration, as the generator it grades.

---

## 9. Safety rails on AI output

| Risk | Rail |
|---|---|
| Hallucinated client facts | Grounding node: every factual claim about the client must resolve to the client profile or a cited source. Unresolved claims **block** the draft (`REQ-CNT-018`) |
| Hallucinated statistics in audits | Audit narrative may only reference values present in `findings.json`. A narrative citing a number not in the findings fails a post-check |
| Banned terms | Enforced at draft time from the client's banned list, and re-checked at publish |
| Prompt injection from scraped pages | Scraped content is wrapped in a delimited, clearly-labelled untrusted block, and the system prompt states that content inside it is data. Tool use is disabled on nodes that read scraped content |
| Injection via directory form text | The citation graph treats page text as data; the fill plan is validated against an allow-list of the client's own field values before it is offered to the operator |
| Model choosing to submit | The citation graph **has no submit tool**. It cannot transmit a form; only the human can |
| Runaway cost | Task budgets on agentic loops, the cost gate before every call, and a per-job spend ceiling that hard-stops the graph |
