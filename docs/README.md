# Documentation

One tree, one rule of precedence — and as of **2026-09-17** it has two eras:

| # | Source | Why it ranks here |
|---|---|---|
| 1 | [`aios-v2/`](aios-v2/) | **The v2 build blueprint — the specification.** When any other document disagrees with it, the pack wins. Start at [`aios-v2/README.md`](aios-v2/README.md). |
| 2 | `architecture/` | How the **running v1** (app.qanry.com) is built. Operational reference for maintaining v1 — not the target design. |
| 3 | `operations/` | Deploy and runbooks for the running v1. |
| 4 | `implementation/` | v1 work log, test baseline, known limitations. Operational reference. |
| 5 | Code | On any question of what v1 *does*, code outranks every document above except the pack's statements about what v2 *will do*. |

**Code is not a spec, but it is the only evidence of behaviour.** A document describing
behaviour the code does not have is wrong, however confident its prose. A claim about
code cites a file and line and is re-derived before reuse. A claim about the database
schema is settled by a built database (`db/ci/verify_fresh_apply.py --keep`, then
`information_schema`), never by eyeballing migrations.

## Layout

| Directory | Contents | Status |
|---|---|---|
| [`aios-v2/`](aios-v2/) | the complete v2 rebuild blueprint: scope, requirements, SDLC, architecture, data model, API, AI stack, security, testing, infra, roadmap, ADRs, glossary, salvage map, module specs | **current — governs all new work** |
| `scope/` | the pre-scope discovery questionnaire that produced the pack | historical, 2026-09-16 |
| `architecture/` | how v1 is built; `reference/` holds the original PDFs | v1 operational reference |
| `operations/` | v1 deploy, runbooks | v1 operational reference |
| `implementation/` | v1 work log, test baseline, known limitations | v1 operational reference |
| `audit/fixtures/` | recorded real audit runs — **referenced by tests** (`test_audit_altitude.py`, `auditAltitude.test.ts`) | current, load-bearing |
| `deliverables/` | the client-facing PDF pack | current |

## Removed 2026-09-17 — where the rest went

The v1 planning and forensic prose (`recovery/`, `research/`, `audit/` minus
`fixtures/`, `meeting-notes/`, and the root-level `CI-RED-GATES.md`,
`DESIGN-REPLICATOR.md`, `QA-HANDOVER.md`, `PLATFORM-CREDENTIALS-CHECKLIST.md`,
`offpage-module-briefing-prompt.md`) was removed from `main` when the v2 pack landed:
superseded as specification, and a live hallucination risk next to the pack.

Nothing was destroyed. All of it — the entire v1 tree as it stood — is preserved at:

- branch **`v1-archive`** (pushed to origin) — tip also carries `docs/scope/`
- tag **`v1-final`** = commit `e3bb2c8`, the v1 state at cut-over

Retrieve any file with `git show v1-archive:docs/recovery/DECISIONS_LOG.md`, or check
the branch out. Historical records there are dated evidence: correct them with visible
errata on the archive branch if ever needed, never silently.

### On the two v1 architecture documents

`architecture/ARCHITECTURE-AND-PLAN.md` is the July **plan**;
`architecture/architecture-as-built.md` is **what exists**. They disagree in places.
`as-built` wins on questions of fact, the plan on questions of intent, code over both —
and the `aios-v2/` pack over all of it for anything being built from now on.
