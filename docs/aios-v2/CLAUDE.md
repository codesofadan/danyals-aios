# CLAUDE.md — AIOS v2

> Drop this file at the root of the new repository. It is loaded into every session.

You are building **AIOS v2**, a multi-tenant SEO operations platform for a single agency
serving 50–100 client businesses. This is a **greenfield rebuild**. The previous version
exists and works in places; its architecture is not the target.

**Read before writing any code:** `docs/00-EXECUTIVE-SCOPE.md`, `docs/03-ARCHITECTURE.md`,
`docs/12-DECISIONS-ADR.md`, and `AGENTS.md`.

---

## The ten principles

Every one of these is a defect class the previous version shipped. A change that violates one
is rejected in review regardless of whether tests pass.

1. **Never invent data.** A provider that is not configured returns a **degraded result**,
   never a plausible number. No hash-derived, sampled or estimated value is ever presented as
   measured.
2. **Three states, never two.** `measured` · `absent` (looked, not there) · `unmeasured`
   (never looked). Every ratio divides by measured only. Enforced by CHECK constraints.
3. **Degrade, never crash.** Every external seam returns `status: ok | degraded` with a
   machine-branchable `reason` **enum**. Never parse a message string to branch.
4. **Terminal states are honest.** A publish with no credentials is `blocked`, not `done`.
   `succeeded` requires the effect to be **confirmed**, not attempted.
5. **Money is gated before it is spent.** The estimate gates; the actual is committed after.
   A blocked call never reaches the provider.
6. **The database enforces tenancy.** `FORCE ROW LEVEL SECURITY` on every table with
   `client_id`. Application filtering is the second line, never the first.
7. **Every job is idempotent, durable and resumable.** Idempotency key, persisted state,
   lease, bounded retry, dead letter. Re-running must never double-spend or double-publish.
8. **Provenance on every value.** `measured` · `derived` · `declared` · `inferred` ·
   `defaulted`, with source and timestamp. A value without provenance cannot be displayed.
9. **Secrets are sealed, per-client, audited.** Never in a log, an API response, a job
   payload, a trace, or a Sentry event.
10. **Tests prove behaviour, not coverage.** Every test must **fail when its defect is
    re-injected**. A test that passes against a broken implementation is deleted.

---

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2.0 async · Alembic · PostgreSQL 16 (+pgvector) ·
Redis (cache/locks/rate-limits **only** — nothing durable) · LangGraph + the official
Anthropic SDK behind our own `ModelRouter` · Playwright · Next.js 15 / React 19 / TypeScript
strict · Chrome MV3 extension · Docker Compose on one VPS.

**Model defaults:** `claude-opus-5` for reasoning and judging, `claude-sonnet-5` for
structured extraction, `claude-haiku-4-5` for bulk. Use `thinking={"type": "adaptive"}` and
`output_config={"effort": ...}` — **never `budget_tokens`** (400 on current models). No
assistant prefill. Stream large outputs.

---

## Non-negotiable structural rules

- **SQL lives only in `repo.py`.** Services take and return domain objects.
- **A module imports another module only through its `api.py`.** Never its models, repo or
  tables. Enforced by an import-linter gate.
- **Nothing imports `anthropic` except `platform/ai/router.py`.**
- **Nothing calls `set_config` for the tenant context except the session factory.**
- **Routers contain no logic** — parse, authorise, delegate, serialise.
- **Authorisation is by capability string**, never `if user.role == ...`.
- **The frontend API client is generated** from OpenAPI. Hand-written `fetch` is rejected.
- **Any operation that can exceed 25 seconds is a job**, not a long HTTP request.
- **Every list endpoint is server-paginated.** There is no unbounded list in the API.
- **Migrations are forward-only and backward-compatible** (expand → migrate → contract).
  There is no staging environment; rollback is redeploying the previous image tag.

---

## The three hardest things — get these right

1. **Elementor block tree** (`REQ-CNT-022`). A published page must open in Elementor with
   every heading, paragraph, image and button individually editable. A single HTML widget is
   an **explicit failure**, not a fallback. Widgets reference Elementor **global** tokens so
   a client restyle propagates. Publishing goes through our companion plugin, which handles
   meta slashing and **CSS cache regeneration** — a raw REST meta write renders unstyled.
2. **Citation account creation** (`REQ-CIT-007`). The extension has no submit capability —
   that is a code-level absence, not a policy. Credentials are generated and vaulted
   server-side; the extension never sees them. Honeypot fields are **never** filled: touching
   one is a hard failure, and the eval bar is **zero**, not "low".
3. **Design token conformance** (`REQ-CNT-008`). Every colour, face, size, weight, radius,
   shadow and spacing value on a generated page must exist in the approved DesignIR. Checked
   programmatically before publish. Parse CSS Color 4 (`oklch()`, `lab()`) — most sites built
   since 2024 emit it, and failing to parse it collapses every brand colour to white.

---

## Working agreement

- **Every task cites a `REQ-*` id.** A change with no requirement is out of scope — raise it,
  do not build it.
- **Design note before code** above ~200 lines of change, approved by the owner.
- **Run every gate locally before review**, then do the adversarial pass on your own tests.
- **Ask when a decision is the owner's** — scope, a principle, a fixed constraint, spending
  real money, touching production. Do not decide these.
- **Never** deploy, run a migration against production, spend on a live provider, or publish
  to a real client site without an explicit go-ahead **for that action**.
- **Report honestly.** If tests fail, say so with the output. If a step was skipped, say so.
  If something is partially done, say which part.

---

## Commands

```
make dev        # full stack, migrated and seeded, from a clean clone
make gates      # everything CI runs
make test       # unit + integration
make eval       # AI eval suites against fixtures
make chaos      # kill-the-worker resumability suite
make openapi    # regenerate the schema and the typed clients
```

The seven CI gates: lint/format · types (`mypy --strict`, `tsc`) · unit+integration ·
migration fresh-apply · RLS adversarial · truth (no synthetic data reachable) ·
contract+eval. **No gate may be skipped or weakened to turn a build green.**

---

## When in doubt

Honesty over completeness · database-enforced over code-enforced · boring over clever ·
reversible over fast · explicit over implicit · one way to do a thing · cost visible at the
point of spend.

Then ask.
