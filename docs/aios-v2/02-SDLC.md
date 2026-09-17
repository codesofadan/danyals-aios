# 02 · SDLC — how work moves

The process is written for a team that is mostly an AI agent supervised by a human
owner. It optimises for one thing: **nothing lands that nobody can account for.**

---

## 1. Lifecycle model

**Iterative delivery against exit criteria, not dates.** There is no imposed deadline;
quality is the binding constraint. Work proceeds in milestones (`10-BACKLOG-ROADMAP.md`),
each of which is closed only when its exit criteria are demonstrated on real data.

```
  Requirement (REQ-*)
        │
        ▼
  Design note ──► Owner review ──► Implementation ──► Self-verify
        │                                                 │
        │                                                 ▼
        └────────────────── rejected ◄──── Code review ◄── CI gates
                                                          │
                                                          ▼
                                              Merge ──► Deploy ──► Verify in prod
                                                          │
                                                          ▼
                                                   Acceptance evidence
```

### Phase 0 · Understand
Read the requirement and every document it cites. Read the code that already touches the
area. **Do not start from the task description alone.** Produce a one-paragraph statement
of what the correct behaviour is, including the failure modes.

### Phase 1 · Design note (required above ~200 lines of change)
A short markdown note in `docs/design-notes/<REQ-ID>-<slug>.md` covering: the behaviour,
the data model delta, the API delta, the failure modes and their terminal states, the
cost implications, and what will be tested. **The owner approves the note before code is
written.** A note is 1–2 pages, not a specification.

### Phase 2 · Implement
Vertical slices: migration → repository → service → API → UI → tests, all in one branch.
Never a half-slice that leaves the system in a state nobody would ship.

### Phase 3 · Self-verify
Before asking for review, run every gate locally and fix what is red. Then do the
**adversarial pass on your own work**: for each test you wrote, re-inject the defect it
claims to catch and prove the test fails. Delete any test that still passes.

### Phase 4 · Review
Human review against the checklist in §6. The reviewer's job is to find the case the
implementer did not consider, not to check style — style is CI's job.

### Phase 5 · Release and verify
Deploy, then verify the behaviour in the running system, not in the test suite. Attach
the evidence (a screenshot, a record id, a log excerpt) to the requirement.

---

## 2. Environments

There is **one deployed environment**: `app.qanry.com`. This is a real constraint and the
process compensates for it:

| Environment | Where | Purpose |
|---|---|---|
| **Local** | Developer machine, full stack via `docker compose up` | All development. Must stand up from a clean clone with seeded data in one command |
| **Ephemeral CI** | GitHub Actions service containers | Every gate runs against a real Postgres and a real Redis, never mocks |
| **Production** | `app.qanry.com`, single VPS | The only deployment |

**Because there is no staging:**
- Every migration must be **forward-only and backward-compatible** with the previous
  application version (expand → migrate → contract, never a breaking rename in one step).
- Every deploy must be **revertible by redeploying the previous image tag**, with no
  database step required to roll back.
- Every new module ships behind a **feature flag**, off by default, enabled per client.
- A `--dry-run` mode is mandatory on any operation that spends money, publishes, or
  mutates a third-party system.

---

## 3. Branch, commit and PR policy

**Trunk-based.** `main` is always deployable.

| Rule | Detail |
|---|---|
| Branch name | `<type>/<REQ-ID>-<slug>` — e.g. `feat/REQ-CNT-022-elementor-block-tree` |
| Types | `feat` · `fix` · `refactor` · `perf` · `test` · `docs` · `chore` · `migration` |
| Direct commits to `main` | Not permitted, including for the agent |
| PR size | Prefer under 600 changed lines. Above 1,200 requires a stated reason in the PR body |
| PR body | Requirement id · what changed · why this design · what was considered and rejected · how it was verified · what it does **not** do |
| Merge | Squash. The squash message is the commit contract below |
| Stacking | Permitted; each PR in a stack must be independently green |

**Commit message contract:**

```
<type>(<scope>): <imperative summary under 72 chars>

<why this change exists — the problem, not the solution>

<what is deliberately not done, and any follow-up id>

Refs: REQ-XXX-000
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

---

## 4. The seven CI gates

Every PR. All must be green. **No gate may be skipped, and no test may be weakened to
turn one green** — if a gate is wrong, fix the gate in its own PR with its own reasoning.

| # | Gate | Command | Fails on |
|---|---|---|---|
| 1 | **Lint & format** | `ruff check . && ruff format --check .` · `biome ci .` | Any violation |
| 2 | **Types** | `mypy --strict app workers integrations` · `tsc --noEmit` | Any error. `Any` requires an inline justification comment |
| 3 | **Unit & integration** | `pytest -q` · `vitest run` | Any failure. Flaky tests are quarantined within 24h or deleted |
| 4 | **Migration fresh-apply** | `scripts/verify_fresh_apply.py` | Migrations do not apply from zero, or the resulting schema differs from the models |
| 5 | **RLS gate** | `scripts/verify_rls.py` | Any table with `client_id` lacking `FORCE ROW LEVEL SECURITY` and a policy; any cross-tenant read succeeding |
| 6 | **Truth gate** | `pytest -m truth` | Any writing path reachable with an unconfigured provider that produces a value instead of a degraded result |
| 7 | **Contract & eval** | `schemathesis run` against the OpenAPI spec · `pytest -m eval` | API response diverging from the published contract; AI eval scores below the fixture baseline |

Advisory (reported, not blocking): coverage delta, bundle size, p95 latency on the
benchmark suite, dependency audit.

---

## 5. Definition of Done

A requirement is done when **all** of these hold. Partial is not done.

- [ ] Behaviour matches the requirement, including its failure modes
- [ ] Every failure mode has an explicit, honest terminal state
- [ ] Data model changes have a forward-only migration that applies from zero
- [ ] Every new tenant table has FORCE RLS and a policy
- [ ] Every paid call passes the cost gate; estimate before, actual after
- [ ] Every stored value carries provenance where the schema requires it
- [ ] Tests exist at the right level and each one **fails when its defect is re-injected**
- [ ] `mypy --strict` and `ruff` clean; no new `Any` without justification
- [ ] OpenAPI spec regenerated; the typed client regenerated
- [ ] Observability: the operation emits a trace, a structured log line and, if it can
      fail silently, a metric
- [ ] Docs updated: the module spec, the ADR if a decision was made, the capability
      truth table if a capability changed
- [ ] Verified in the running system with evidence attached

---

## 6. Code review checklist

The reviewer asks these, in this order:

1. **Is this the right problem?** Does the change serve the cited requirement, and
   nothing beyond it?
2. **What happens when the provider is down, slow, or returns garbage?** Find the path.
3. **What happens if this job runs twice?** Find the idempotency key. If there is none,
   reject.
4. **Can this show a user a number that was never measured?** Trace the value to its
   source.
5. **Whose data can this read?** Find the tenant boundary. Application-level filtering
   without RLS is a reject.
6. **What does this cost, and who stops it?** Find the gate.
7. **Would this test fail if the code were wrong?** Pick one test and check.
8. **Is the terminal state honest?** Look for `done` on a path that did nothing.
9. **What did the author choose not to do, and did they say so?**

---

## 7. Documentation duties

Documentation is part of the change, not a follow-up.

| When | Update |
|---|---|
| A decision was made between real alternatives | `12-DECISIONS-ADR.md` — a new ADR with the rejected options |
| Module behaviour changed | `modules/M??-*.md` |
| A capability became operational, degraded or removed | The capability truth table |
| A limitation was discovered and not fixed | `docs/KNOWN-LIMITATIONS.md` — with its requirement id |
| An external contract was learned (an API's real behaviour vs its docs) | `docs/provider-notes/<provider>.md` |

**Rule:** if a future engineer would be surprised, write it down. If you were surprised,
you are that engineer.

---

## 8. Risk and change management

| Risk class | Control |
|---|---|
| **Spend runaway** | Money dials default `off`; per-client cap; global halt; every job estimates before it spends; `--dry-run` on every spending command |
| **Client-visible error** | Human approval before any publish, submission or live-site mutation; feature flags per client; revertible publishes |
| **Platform ban** | Official APIs only; pacing engine; per-client identity; account-health gate that stops using a degrading account |
| **Data loss** | Nightly encrypted backups; append-only ledgers for measurements; restore drill before hand-over |
| **Cross-tenant leak** | RLS as the primary boundary; adversarial CI gate; no raw SQL outside the repository layer |
| **Silent degradation** | Truth gate in CI; capability truth table derived from live probes; degraded states surfaced in the UI, not swallowed |
| **Scope drift** | Every task cites a `REQ-*`; an unreferenced change is rejected in review |

**Change control:** a change to scope, a principle, or a fixed constraint requires a new
ADR and the owner's explicit approval recorded in it. The agent may not decide these.

---

## 9. Cadence and reporting

| Artefact | When | Contents |
|---|---|---|
| **Work log** | Every session | What was attempted, what landed, what is blocked, what surprised you |
| **Milestone report** | Milestone close | Exit criteria with evidence, what slipped and why, revised risk list |
| **Capability truth table** | Continuously, automated | Live per-capability state: operational / degraded / unconfigured |
| **Spend report** | Weekly | Actual vs estimated by module and client; variance explained |

**Escalate immediately, do not batch:** a security exposure, a cross-tenant leak, a
provider contract change that breaks a module, any evidence the system showed a client a
number that was not measured.
