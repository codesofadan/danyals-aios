# 12 · Architecture Decision Records

Each record states the decision, why, and **what was rejected**. A decision with no rejected
alternative was not a decision.

**Status key:** ✅ accepted · 🟡 pending owner approval · ⛔ superseded

---

## ADR-001 ✅ Rebuild rather than refactor

**Decision:** build v2 greenfield; port domain knowledge, not architecture.
**Why:** v1's defects were structural — synthesised data reachable in production, jobs with
no idempotency contract, dishonest terminal states, design capture that could not produce an
editable page. Each fix touches the same foundations.
**Rejected:** incremental refactor of the 82k-line v1 backend. Every structural fix would
have to coexist with the structure it replaces, on a single production environment, with no
staging.
**Cost accepted:** rebuilding ~18 months of accumulated domain detail. Mitigated by
[`14-SALVAGE-MAP.md`](14-SALVAGE-MAP.md).

## ADR-002 ✅ Modular monolith, not microservices

**Decision:** one API process, one worker type, one browser-worker type; modules are enforced
package boundaries with public `api.py` interfaces.
**Why:** 50–100 clients on one VPS. v1's failures were correctness failures, not scaling
failures. Distributed tracing and service discovery would cost more than they return.
**Rejected:** microservices (operational cost, distributed transactions); a plain monolith
(v1 was one, and its modules reached into each other's tables).
**Enforcement:** an import-linter gate, not good intentions.

## ADR-003 ✅ Postgres-backed durable job engine

**Decision:** implement the job queue in Postgres using `FOR UPDATE SKIP LOCKED`, with
leases, idempotency keys and a `side_effects` ledger. Redis is cache, locks and rate limits
only — **nothing durable**.
**Why:** a job's state and its side-effect rows must commit in one transaction. That is the
single property v1 lacked and the root of its double-spend and phantom-success defects.
**Rejected:** Celery + Redis (no idempotency contract; Redis flush loses jobs — v1's exact
shape); Temporal (right at 10× this scale, wrong operationally on one VPS); a hosted queue
(another failure domain and another bill).

## ADR-004 ✅ RLS as the primary tenant boundary

**Decision:** `FORCE ROW LEVEL SECURITY` on every table with `client_id`; tenant context set
once in the session factory; an adversarial CI gate over every table.
**Why:** application-level filtering fails the first time someone writes a query in a hurry.
The database does not get in a hurry.
**Rejected:** database-per-tenant (100 databases, 100 migration runs, no cross-client
reporting); application-only scoping (one missed `WHERE` is a breach).

## ADR-005 ✅ LangGraph for orchestration, official Anthropic SDK for the call

**Decision:** LangGraph owns multi-step AI state (checkpointed to Postgres). Every model call
goes through our own `ModelRouter` wrapping the official SDK. LangChain is used only as an
adapter where it genuinely saves work. Nothing else imports `anthropic` directly.
**Why:** LangGraph's checkpointing composes exactly with durable jobs. LangChain's chat-model
abstraction lags the Anthropic API on precisely the features that matter here — adaptive
thinking, `output_config.effort`, cache breakpoint placement, strict tool schemas.
**Rejected:** LangChain end-to-end (feature lag, opaque cost accounting); a bespoke
orchestrator (we would rebuild checkpointing badly); LangGraph.js inside the extension (the
extension must stay a thin actuator — see ADR-010).

## ADR-006 ✅ Direct Anthropic key preferred; agentrouter as a configured fallback

**Decision:** `AnthropicBackend` is the default. `AgentRouterBackend` exists, is chosen by
configuration, and is **feature-degraded by definition** — a call requiring adaptive
thinking, effort control or cache guarantees raises `CapabilityMissingError` rather than
silently producing worse output.
**Why:** v1 routed through agentrouter.org with an exhausted premium tier, leaving only
budget models with quota — which silently degraded output quality with no signal. A
backend change must never change quality silently.
**Rejected:** agentrouter as the default (no feature parity); hard-coding a single backend
(no fallback when a key lapses).

## ADR-007 ✅ Task tiers, not one model everywhere

**Decision:** `reasoning` and `judge` → `claude-opus-5`; `drafting` → `claude-opus-5` at
medium effort; `structured` → `claude-sonnet-5`; `bulk` → `claude-haiku-4-5`. The judge tier
is never the generator's configuration.
**Why:** cost and quality both. Alt text does not need Opus; a QA judge does.
**Rejected:** one model for everything (either too expensive or too weak); routing by prompt
length (a proxy for nothing).

## ADR-008 ✅ Design fidelity is token conformance, not pixel replication

**Decision:** generated pages must use only values present in the approved DesignIR. Checked
programmatically. No pixel diff.
**Why:** the client wants new pages in their design language, not clones of an old page. A
pixel target is unachievable for new compositions and would fail on content the source never
had.
**Rejected:** pixel-diff replication (wrong goal, brittle); "looks about right" review (not
enforceable, not testable).

## ADR-009 ✅ Elementor block tree is a hard requirement, HTML-in-a-widget is a failure

**Decision:** publish emits a real Elementor element tree with global-kit token references,
written through a companion plugin that also regenerates Elementor's CSS cache.
**Why:** the client must be able to edit their own pages. A single HTML widget is a page the
client cannot touch, which converts the deliverable into a dependency on us.
**Rejected:** styled HTML in one widget (v1's outcome — editable only as source); a page
builder of our own (we would be maintaining a builder, not an SEO platform).
**Risk accepted:** Elementor's data model changed at 3.16 (`container` vs `section`/`column`).
Capability discovery branches on the site's real version; both emitters are maintained.

## ADR-010 ✅ The extension is a thin actuator with no submit capability

**Decision:** all intelligence runs backend-side. The extension observes, applies a fill plan,
and shows the operator what will be sent. It holds no credentials and **contains no code path
that submits a form.**
**Why:** the owner's decision is that a human always presses submit. Making that a *capability
the system lacks* rather than a *policy it follows* means it cannot regress.
**Rejected:** full auto-submit (directory terms, client risk, and the owner's decision);
intelligence in the extension (credential exposure, no shared cache, no server-side audit).

## ADR-011 ✅ Citation mappings cached on a structural fingerprint

**Decision:** cache field mappings against a fingerprint of form structure — field order,
types, label shapes — never the URL and never CSS selectors.
**Why:** directories rotate class names per page load and reuse one form across many URLs. A
selector-keyed or URL-keyed cache is wrong in both directions.
**Rejected:** hand-maintained per-directory DOM specs (v1's approach — unmaintainable at 160
directories); URL-keyed caching (misses and false hits).

## ADR-012 ✅ Aggregators out; the extension is the only submission route

**Decision:** no Yext / Data Axle / Apify submission path. No stub either.
**Why:** owner decision. Aggregator economics and control did not fit, and a stub invites a
future contributor to wire it up.
**Rejected:** aggregator-primary with extension fallback; hybrid routing by directory tier.

## ADR-013 ✅ Official APIs only for Web 2.0; no browser automation of platforms

**Decision:** a platform with no usable API is `unsupported`. Medium is the worked example.
**Why:** browser-automating a platform that forbids it risks the *client's* properties and
the agency's reputation, to save one integration.
**Rejected:** headless automation for API-less platforms; third-party unofficial APIs.

## ADR-014 ✅ Tiered Web 2.0 account ownership

**Decision:** per-client identity on every platform where a ban costs something; house
accounts only on anonymous/throwaway tiers, with a hard property cap per house account,
enforced at the database level.
**Why:** shared accounts are a shared failure domain. A platform that can link 40 unrelated
local businesses to one account has been handed the pattern it polices. It was also promised
to the client in writing.
**Rejected:** house accounts everywhere (v1's `seed_web2_vault` behaviour); per-client
everywhere (unjustifiable onboarding cost on throwaway platforms).

## ADR-015 ✅ SoMePoster is the reference surface for M05

**Decision:** adopt its information architecture — connection grid, compose-once editor,
video composer, AI studio, Parasite Poster, automations, calendar, posts ledger, analytics —
and rebuild it multi-tenant with the link-building spine it lacks.
**Why:** a validated, shipped surface for exactly this job. Redesigning the navigation from
first principles would spend design effort on a solved problem.
**Rejected:** designing the surface fresh; licensing or reselling SoMePoster (no
multi-tenancy, no SEO spine, no control).

## ADR-016 ✅ QA gate ships advisory, switchable, and cannot go hard uncalibrated

**Decision:** advisory with mandatory acknowledgement; the `hard` switch is blocked in code
until a calibration set of ≥30 human-graded drafts exists.
**Why:** an uncalibrated hard gate either blocks good work or passes bad work, and nobody
knows which. v1 asserted a hard gate with a threshold marked PROVISIONAL.
**Rejected:** hard from day one (unknown threshold); advisory forever (no quality floor).

## ADR-017 ✅ Three-state measurement, enforced by CHECK constraints

**Decision:** `ranked` / `absent` / `error` as distinct states; ratios divide by measured
points only; the constraint makes blurring impossible.
**Why:** collapsing `absent` and `error` renders a rate-limited afternoon as a client's
service area collapsing, permanently, in an append-only table.
**Rejected:** nullable position with a separate error flag (allows incoherent rows); handling
it in application code (one missed branch and the data is wrong forever).

## ADR-018 ✅ Sheets is a format, never a store

**Decision:** Google Sheets and CSV are export targets. Nothing in the platform reads its own
data back from a spreadsheet.
**Why:** v1 carried a Sheets-as-store layer alongside Postgres, so "where is the truth" had
two answers and a write-buffer to reconcile them.
**Rejected:** Sheets as a client-facing store (quota limits, no integrity, no RLS).

## ADR-019 ✅ LangSmith self-hosted by default

**Decision:** self-host. Hosted SaaS requires an explicit owner ADR, input redaction, and a
note in the client DPA.
**Why:** traces contain client page content, NAP data and business descriptions — the client's
commercial information, for 50–100 businesses.
**Rejected:** hosted by default (data egress the client has not agreed to); no tracing (the
AI paths become unobservable, which is how v1's quality regressions went unnoticed).

## ADR-020 ✅ Audit engine is a module, not a subprocess

**Decision:** `modules/audit/` is an ordinary module on the shared job engine, cost gate and
provider seam. v1's checklists, scoring and GEO domain knowledge are ported.
**Why:** v1's engine minted its own run id, never timed itself out, and did not catch its own
top-level exceptions, so the caller owned failure handling for a process it could not see
into. That seam produced a disproportionate share of v1's reliability problems.
**Rejected:** keeping the subprocess with a hardened contract (still two job systems, two
cost models, two failure taxonomies).

## ADR-021 🟡 Add a Google Search Console connector

**Decision (pending owner approval):** add GSC to M07 as `REQ-RNK-008`, P1.
**Why:** it is the only **first-party** measurement in the platform, free, and uses an OAuth
scope the client already grants for GBP. It turns "we published 50 pages" into "these 43 are
receiving impressions for these queries" — the only honest proof the content module works.
**Constraint:** GSC reports an **average position**, not a rank. It is stored with
`source='gsc'`, labelled as an average, and never enters a rank series (`REQ-RNK-001`).
**Origin:** surfaced while reviewing seosignalx.com, which exposes a GSC area. See
[`15-REFERENCE-PRODUCTS.md`](15-REFERENCE-PRODUCTS.md) §B.
**Rejected:** GSC as the rankings source (it is an average, which is exactly why v1's
documents flagged the two as different).

## ADR-022 ✅ The AI stack lands in the v1 tree first, starting with Web 2.0

**Decision:** build `platform/ai` (model router, LangGraph runtime, LangSmith tracing,
prompt registry) **inside the running v1 backend** as `app/platform/ai/`, and convert one
module to it — Web 2.0's `campaign_content` — before any other.
**Why:** ADR-001 rebuilds greenfield, but the AI stack is the one layer whose value does not
depend on the rebuild landing. It is additive (nothing in `app/services` changes because it
exists), it pays for itself immediately (v1 drafts a 30-property campaign with no checkpoint,
no trace and no tier routing), and converting one module proves the contracts against real
work rather than against a document. Web 2.0 is the right first module because its drafting
stage fans out a dozen model calls per property and persists nothing until the end — the
exact shape checkpointing exists for.
**Rejected:** waiting for the v2 skeleton (the stack would be designed against no caller, and
v1 keeps double-billing interrupted campaigns in the meantime); a shim that only wraps the
existing writer (no checkpoint, no resumption — the reason for adopting LangGraph at all).
**Constraint:** `platform/` may never import a module (`03-ARCHITECTURE.md` §5 rule 4), which
holds here, so the package ports to v2 unchanged.

## ADR-023 ✅ LangGraph for orchestration, our own router for the model call

**Decision:** LangGraph owns multi-step graph state; every model call goes through
`ModelRouter` over the **official Anthropic SDK**. `langchain` itself is not a dependency.
**Why:** LangGraph is adopted for one property — checkpointed, resumable state — which
composes with the job engine (the job owns the lifecycle, the graph owns the reasoning
state). LangChain's chat-model abstraction lags the Anthropic API on exactly the features
that matter here: adaptive thinking, `output_config.effort`, cache-breakpoint placement,
strict tool schemas.
**Rejected:** LangChain's chat models in the hot path (the lag becomes ours permanently);
hand-rolled checkpointing (re-implementing resumable state is the one thing LangGraph is
worth taking a dependency for).
**Enforcement:** both packages are an optional `[graph]` extra, lazy-imported, and a
deployment without them degrades to the linear path rather than failing — the base image
stays light, which is a live constraint (heavy AI trees have broken this build's dependency
resolution before).

## ADR-024 ✅ A missing backend capability blocks the judge, and is recorded everywhere else

**Decision:** when the configured backend cannot honour a tier's declared configuration, the
`reasoning` and `judge` tiers **raise** `CapabilityMissingError`; `drafting`, `structured`
and `bulk` proceed and record the degradation on the result, the log line and the trace.
**Why:** `06-AI-STACK.md` §3 forbids a backend change altering output quality *silently* —
silence is the thing being ruled out, not degradation. A judge that cannot think is a
different grader, so an eval calibrated against one says nothing about the other; a drafting
call that cannot set `effort` is the same article written slightly differently.
**Rejected:** blocking every tier (this deployment's live backend is an OpenAI-compatible
proxy, so all work would stop to enforce a preference); recording every tier (an
uninterpretable grade is worse than a refusal, and evals built on one would be meaningless).
**Escape hatch:** `ai_router_strict_tiers=false` moves the line, deliberately and visibly.

---

## Defaults for decisions this pack does not cover

When the pack is silent, apply these in order, then ask:

1. **Honesty over completeness.** Degrade visibly rather than fill a gap.
2. **Database-enforced over code-enforced.** If a constraint can be a constraint, it is one.
3. **Boring over clever.** The team maintaining this is one person and an agent.
4. **Reversible over fast.** Prefer the choice that can be undone by redeploying.
5. **Explicit over implicit.** No magic, no reflection-based wiring, no convention that is
   not checked.
6. **One way to do a thing.** A second way is a future inconsistency.
7. **Cost visible at the point of spend.** Never hide a price behind a button.

## Document precedence

`DECISIONS-ADR.md` → this scope pack → the code → older v1 documents.
The v1 repository is **evidence of what was tried**, not a specification.
