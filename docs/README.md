# Documentation

One tree. Every document has exactly one home, and when two documents disagree the
order below decides which wins.

## Precedence — highest first

| # | Source | Why it ranks here |
|---|---|---|
| 1 | `recovery/DECISIONS_LOG.md` | Decisions the owner actually made, in their own words. Nothing outranks a decision. |
| 2 | `decisions/` (ADRs) | Deliberate architectural choices, dated, with the alternatives recorded. |
| 3 | `architecture/` | How the system is built. |
| 4 | `research/` | Phase 1 evidence records — sourced and dated, but they inform decisions rather than make them. |
| 5 | `recovery/`, `audit/`, `implementation/` | The historical record. **Accurate as of its date, not necessarily now.** |

**Code is not on this list, because code outranks all of it.** A document describing
behaviour the code does not have is wrong, however senior its author or confident its
prose. That is not a hypothetical:

> `backend/CLAUDE.md` invariant #12 stated that content publishing was protected by a
> hard QA gate raising `PublishBlocked`. **`PublishBlocked` is raised nowhere.** The claim
> appeared in four places, and the recovery specification then cited
> *`[CONFIRMED — [CODE] backend/CLAUDE.md item 12]`* as evidence for one of its six
> headline defects. The audit cited documentation as code evidence, and the documentation
> was false.

Separately, a forensic audit's single RED verdict rested on a count of **3** where the
real figure is **50** — established four times over, including from the audited commit
itself.

**Both failures share one cause: a confident document that nobody re-derived from
source.** Hence the rules below.

## Rules

1. **Every document carries a date and a status** (`current` · `historical` · `superseded`).
2. **Historical records are corrected, never silently edited.** The recovery and audit
   trees are dated evidence. When one is wrong, add the correction visibly — an erratum,
   or a struck line with the reason. Quietly rewriting a premise destroys the thing that
   made the record citable.
3. **A claim about code cites a file and line, and is re-derived before reuse.** Citing a
   document that cites a document is how the failure above happened.
4. **A claim about the database schema is settled by a built database, never by reading a
   migration.** A column's type is its creating migration plus every later `ALTER`; across
   85 ordered migrations that is not something to eyeball. `db/ci/verify_fresh_apply.py
   --keep`, then query `information_schema`. Two sessions got the same column wrong on the
   same day by reading `0006` and missing `0044`. See `db/migrations/README.md`.

## Layout

| Directory | Contents | Status |
|---|---|---|
| `architecture/` | how the system is built; `reference/` holds the original PDFs | current |
| `operations/` | deploy, runbooks, credentials | current |
| `research/` | the seven Phase 1 decision records + cross-track index | current, dated |
| `recovery/` | specification, requirements traceability, decisions, open questions | mixed — read `DECISIONS_LOG.md` first |
| `audit/` | the forensic audit set and salvageability matrix | historical, 2026-08-23 |
| `implementation/` | the work log, test baseline, known limitations | current |
| `deliverables/` | the client-facing PDF pack | current |
| `meeting-notes/` | call records | historical |

### On the two architecture documents

`ARCHITECTURE-AND-PLAN.md` is the **plan** (the v1 locked architecture, July).
`architecture-as-built.md` is **what exists**. They overlap and in places disagree —
because the second describes a system the first predicted.

**They are deliberately not merged here.** Reconciling them means deciding, case by case,
whether the plan or the build is right, and each of those is an architectural decision
that belongs in `decisions/` with its reasoning visible. Merging them silently would
destroy exactly the evidence needed to make those calls. Until then, `as-built` wins on
questions of fact and the plan wins on questions of intent — and the code wins over both.

## Where things moved (2026-08-23)

`context/` and `knowledge-base/` were separate top-level trees describing the same system
to different depths, with nothing stating which governed. Both are now here. The old
paths appear in older documents and commit messages; they resolve as:

| Was | Now |
|---|---|
| `context/ARCHITECTURE-AND-PLAN.md` | `docs/architecture/ARCHITECTURE-AND-PLAN.md` |
| `context/PRODUCT-OVERHAUL-BACKLOG.md` | `docs/architecture/PRODUCT-OVERHAUL-BACKLOG.md` |
| `context/*.pdf` | `docs/architecture/reference/` |
| `knowledge-base/architecture.md` | `docs/architecture/architecture-as-built.md` |
| `knowledge-base/{modules,data-model,apis-and-keys,cost-and-dials}.md` | `docs/architecture/` |
| `knowledge-base/deploy.md` | `docs/operations/deploy.md` |

Note "knowledge base" also names a **Policy Radar domain concept** (`kb_entries`,
`KBEntry`) which has nothing to do with the old directory. Occurrences in
`backend/app/schemas/policy.py` and `services/policy_watch.py` are that concept, not a
path, and were correctly left alone.
