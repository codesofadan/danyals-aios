# 10 · Backlog and Roadmap

**Milestones close on exit criteria, not dates.** There is no imposed deadline; quality is
the binding constraint. The *order*, however, is load-bearing — each milestone exists
because the next one is unsafe or wasteful without it.

---

## The critical path, in one line

> Platform primitives → one vertical slice proven end to end → the two hardest modules
> (Content publishing, Citation account creation) → breadth → measurement → hand-over.

The two hardest things in this system are **emitting an editable Elementor block tree** and
**creating directory accounts at scale**. Both are attempted early — in M2 and M4 — because
if either is impossible, everything downstream changes and it is cheaper to learn that in
week four than in month four.

---

## M0 · Foundation

**Goal:** a repository that cannot be built carelessly.

- Repo skeleton, `docker compose` full stack, `Makefile` gates
- Postgres + Alembic + the RLS pattern and its adversarial gate
- Typed settings, structured logging, correlation ids, Sentry, OpenTelemetry
- The error taxonomy
- CI: all seven gates wired and failing loudly on a seeded violation
- `platform/providers` seam with the `ProviderResult` contract and the truth gate
- Auth: argon2id, sessions, refresh rotation, MFA, capability strings

**Exit criteria**
1. `docker compose up` from a clean clone yields a working, seeded system.
2. A deliberately introduced RLS violation, synthetic-data path, and type error each fail CI.
3. A user can log in, MFA is enforced for Owner, and every route enforces a capability.

---

## M1 · The job engine and the cost gate

**Goal:** the two primitives that make everything else safe. **Nothing else starts first.**

- Durable job engine: leases, heartbeats, idempotency keys, `side_effects` ledger, retry
  classes, dead letters, parent/child fan-out, per-client concurrency caps
- Transactional outbox and domain events
- Cost gate, dials, budgets, global halt, cost ledger with estimate/actual
- Vault: envelope encryption, per-client sealing, access log
- Provenance primitive and the `<Measured>` frontend component
- Chaos suite v1: kill a worker mid-job for three job kinds

**Exit criteria**
1. Running any job twice with the same idempotency key produces one effect and one charge.
2. Killing a worker mid-job resumes without repeating a confirmed side effect.
3. Setting a dial `off` provably prevents every paid call in that module.
4. A secret cannot be retrieved through any API response, log or Sentry event.

---

## M2 · Vertical slice — Content, one page, end to end

**Goal:** prove the hardest thing in the product on a single page before building breadth.

- Client record, profile, canonical NAP, WordPress connection + capability probe
- Design analysis: browser capture, computed styles, CSS Color 4 parsing, content-root
  detection, vision corroboration, DesignIR, provenance, approval UI
- Keyword bank minimal path (manual seed acceptable at this stage)
- Content graph: research → outline → draft → grounding → schema → title/meta → QA
- Composition plan → **Elementor emitter** → global kit sync → companion plugin → publish
- Review queue, draft-first publish, go-live, revert

**Exit criteria**
1. Design extraction of 10 real sites yields ≥9 grounded colour roles on ≥8 of them,
   including `oklch()`/`lab()` sites; header and footer captured.
2. **One page publishes to a real WordPress site and every heading, paragraph, image and
   button is individually editable in Elementor.**
3. Token conformance is 100% on that page.
4. A publish with no credentials ends `blocked`, never `done`.
5. A draft with an unsupported client claim is blocked.

> **This is the milestone that decides the product.** If the Elementor emitter cannot be
> made to work, stop and re-plan the publishing strategy before building anything else.

---

## M3 · Content at volume

- Keyword research proper: expansion, DataForSEO metrics, intent, clustering, entity sets
- Topical map → page-set proposal → human approval → 50-page fan-out
- Internal linking (new→new applied, new→existing proposed)
- Images, alt text, originality check
- QA calibration set: ≥30 human-graded drafts; scorecard correlation measured
- Gutenberg fallback emitter

**Exit criteria**
1. **50 pages generated, QA'd, reviewed and published with zero manual repair**, all passing
   token conformance and schema validation.
2. Killing the worker at page 31 resumes at page 31.
3. QA correlation against human grades ≥0.75; the gate cannot be switched to `hard` without
   the calibration set.

---

## M4 · Citations

- Directory registry seeded (≥160) with terms positions
- Extension: MV3 shell, scoped operator tokens, PII-free collector, session board
- Form intelligence: heuristic → model → structural-fingerprint cache
- Honeypot and trap detection
- **Account creation graph** with catch-all alias allocation and IMAP verification
- CAPTCHA integration, per-client profile/proxy isolation
- Human-submit flow, proof capture, liveness scheduling
- Marginal and loaded cost accounting per citation

**Exit criteria**
1. **100 live, NAP-verified citations** for one client with proof artefacts.
2. Account creation succeeds end to end on ≥25 directories including email verification.
3. **Zero honeypot touches** across the fixture corpus; mapping accuracy ≥95%.
4. No submit capability exists in the extension — asserted against the built bundle.
5. Loaded cost per citation reported and inside the agreed ceiling.

---

## M5 · Web 2.0 and social

- Platform registry (32) with auth, content model, media rules, link policy, terms position
- OAuth connection flows; per-client vs house ownership enforced at the database level
- Connection grid, composer with per-platform preview, calendar, posts ledger
- Campaign entity, approval gate, anchor bank with distribution caps
- Pacing engine, publish adapters, idempotent publishing
- Link liveness, account health, eligibility gating
- **Parasite Poster**: host selection, publish, and tracking of the hosted URL
- AI Studio surface over the M03 pipeline

**Exit criteria**
1. One campaign publishes across **≥15 platforms** with per-client identities, images, SEO
   fields and internal links — official APIs only, no ban.
2. Re-running a publish job produces exactly one post.
3. Anchor distribution caps hold across a full campaign; no two properties share body text.
4. A Parasite Poster page is published, tracked in M07, and appears in the client report.

---

## M6 · Measurement

- Rank tracking (DataForSEO), append-only observations, SERP features
- Geo-grid: coordinate-based queries, three-state points, CHECK constraints, heat map
- GSC connector (pending ADR-021)
- Indexing: submission with quota queueing, verification, event-driven registration
- Local/GBP: connection, posts, NAP consistency score

**Exit criteria**
1. A rate-limited grid run produces `error` points and every ratio divides by measured only.
2. Sources are never mixed in one series, in the API or the UI.
3. A submission exceeding quota is queued, not lost.
4. NAP consistency itemises every mismatch with both values and their sources.

---

## M7 · Audit

- Port the v1 domain knowledge: checklists, scoring, GEO checks
- Six paid types + the free condensed audit
- `findings.json` contract, per-section degradation, coverage reporting
- Narrative graph constrained to findings values
- Free-audit abuse controls and lead capture
- Findings → tasks; audit diff

**Exit criteria**
1. Each of the six types completes with zero degraded sections on a fully-keyed environment.
2. Removing a key degrades exactly its sections and renders explicit "not measured" blocks.
3. Free audit completes in under 3 minutes with abuse controls proven under a scripted attempt.
4. The narrative contains no number absent from `findings.json`.

---

## M8 · Portal completion, reporting, tiers

- Task queue, milestones, notifications with digest batching, activity log
- Command Center, capability truth table from live probes
- Client portal
- Bulk client import with dry-run and rollback
- Policy Radar
- Document model, HTML + PDF renderers, monthly report, scheduled delivery
- Tiers, entitlements enforced at the API, cost reporting

**Exit criteria**
1. The capability truth table reflects reality within one probe cycle of a key change.
2. A 50-child fan-out produces one digest notification.
3. HTML and PDF render from one document model; a fact change appears in both.
4. Over-entitlement requests are refused at the API.

---

## M9 · Hardening and hand-over

- Chaos suite across all eight long-running job kinds
- Load scenario at 100 clients' data volume
- Full eval suite at production tiers with stored baselines
- Schedules enabled one module at a time, each after its chaos pass
- Backup restore drill into a clean host
- Security checklist (`07-SECURITY.md` §11) completed
- Runbooks written and walked through by someone who did not write them
- Provider disclosure page; known-limitations register current

**Exit criteria — the v2.0 success criteria in `00-EXECUTIVE-SCOPE.md` §6, all eight, on
production data.**

---

## Standing rules for sequencing

1. **No module ships before the job engine can carry it.** A module that spends money or
   publishes without durable jobs will be rebuilt.
2. **No schedule is enabled before its job kind passes chaos.** This is the deliberate
   inverse of v1, where the scheduler was disabled because the jobs were unsafe and nobody
   could tell which.
3. **Every milestone ends with evidence on real data**, not a green test suite.
4. **Feature flags per module, off by default, enabled per client** — the only safe way to
   ship into a single production environment.
5. **If a milestone's exit criteria cannot be met, stop and re-plan.** Do not proceed with a
   known-broken foundation and a note to fix it later; that is precisely how v1 arrived
   where it did.
