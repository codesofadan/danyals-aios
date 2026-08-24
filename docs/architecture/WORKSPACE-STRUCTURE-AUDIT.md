# Workspace Structure — Audit and Target

**Date:** 2026-08-23 · **Scope:** the whole `danyals-aios` working tree
**Status:** audit complete; migration sequenced against the recovery plan's phases, not yet executed

---

## How this was produced

Every number below was measured, not estimated: `du`/`find`/`git ls-files` for the
inventory, AST counts for code, `grep` for reference-counting, and import-graph reads to
establish what each portal actually uses. Where a claim is about the *database schema* it
was taken from a database built from zero, never from reading a migration — that
distinction is itself one of this repository's recent lessons
(`db/migrations/README.md`, "the CREATE TABLE is not the schema").

Nothing here is a matter of taste. Each finding names the concrete cost it imposes:
work that goes to the wrong place, a reader who reaches a wrong conclusion, or bytes
shipped to a client.

---

## 1. The finding that matters most

**The repository's structure does not express the product.**

The product is five modules delivered through three portals. Neither axis is visible in
the tree. Instead the layout preserves the *order the code was written in* — a first
generation organised by technical layer, a second organised by feature, and neither
finished. A new capability has no obvious home, so it lands wherever the last one did,
and the split widens.

That is the root cause of most of what follows. The rest is litter, which is easy.

### 1.1 The backend is mid-migration between two architectures, and stopped

| Generation | Location | Files | Lines | Organised by |
|---|---|---|---|---|
| First | `app/routers/` + `app/schemas/` + `app/services/` + `app/db/` | 147 | ~36,300 | technical layer |
| Second | `app/modules/<feature>/` | 87 | ~25,100 | feature |

A second-generation package is a complete vertical slice —
`router.py · schemas.py · service.py · repo.py · tasks.py`. That is the better pattern
and it is already proven in 15 packages.

**The five v1 modules are split across both generations:**

| v1 module | Lives in | Generation |
|---|---|---|
| Portal (admin/team/client) | `routers/{clients,admin_users,portal,team,tasks,...}.py` | first |
| Audit | `routers/audits.py` | first |
| Content | `routers/content.py` | first |
| **Citations** | `modules/citations/` | **second** |
| Web 2.0 | `routers/offpage.py` | first |

The sharpest example: **citations and Web 2.0 are the same product surface** — the
off-page module — and they live in different architectural generations. A change to
"off-page" is two changes in two shapes.

Cost: every off-page task requires deciding which pattern to follow, and the answer has
been "whichever the file you opened uses" for six weeks.

### 1.2 The three portals are the product's primary axis and are invisible

Measured from the actual import graph:

```
/admin  (15 pages) -> audit auth charts clients content cost leads offpage
                      overview policy reports settings tasks team vault wordpress
/team   ( 5 pages) -> auth portal
/client ( 5 pages) -> auth client
```

So the separation *exists* but is named by accident:

- `components/portal/` is the **team** portal. Nothing in the name says so.
- `components/client/` is the **client** portal — and sits beside `components/clients/`,
  which is the **admin's client-management** screens. Ten characters apart, opposite
  audiences, adjacent in every file listing.
- `components/report/` (a shared viewer) sits beside `components/reports/` (the admin
  workspace). Same trap.
- The admin portal has no grouping at all; it is 16 sibling directories.

Cost: this is a real defect generator. The client portal is the one surface where showing
the wrong data is a **client-visible data breach** — other clients' existence, internal
cost and MRR, credentials, team performance. A layout where `client/` and `clients/` are
adjacent invites exactly the wrong import, and the compiler cannot catch it.

### 1.3 `integrations/` is 41 flat files where domains already exist

`citation*` ×7 · `web2*` ×4 · `wordpress*` ×2 · `content*` ×2 · `audit*` ×1, plus ~25
single-provider clients. The groupings are already in the filenames; only the directories
are missing.

---

## 2. Litter, and things in the wrong place

Cheap to fix, and several are client-visible.

### 2.1 Build artefacts committed as source

> **⚠️ CORRECTED 2026-08-23, before execution.** The first version of this section listed
> all three zips as litter and put `SEO-CONTENT-OS.zip` first on a delete list. **That was
> wrong and would have destroyed the canonical content doctrine.** The error came from a
> reference check that filtered by file extension and so missed a `.ps1`; re-running it
> with no filter changed the disposition of three of the six items below. The corrected
> findings stand; the original conclusions did not survive contact with evidence, and the
> record of that is left visible deliberately.

| Path | Size | Verified disposition |
|---|---|---|
| `SEO-CONTENT-OS.zip` | 1.1 MB | **DO NOT DELETE. Extract, do not remove.** |
| `aios-publisher.zip` | 24 KB | **Delete — it is stale, and it is actively harmful.** |
| `spotino-theme.zip` | 16 KB | **Delete — byte-identical to `spotino-theme/`.** |

**`SEO-CONTENT-OS.zip` is the single most important file in this section and nearly the
worst possible thing to delete.** It contains 87 `knowledge/` files plus scripts and
research, and it is the **only copy** of the material that `backend/docs/CONTENT-DOCTRINE.md`
declares *"the single canonical spine for what a ranking-grade page is"*.
`content_qa.py:70` and `content_generator.py:55,59` both cite
`backend/seo-content-os/knowledge/` as the justification for their numeric constants — and
**that directory has never existed**: `git log --all -- backend/seo-content-os` returns
zero commits. The zip is what the code's constants are justified by, and the planned seed
for the SEO intelligence substrate (R6-1, which explicitly claims ownership).

The original critique — *opaque, ungreppable, unreviewable, unversioned at file level* — is
correct and is exactly why it must be **extracted into the tree**, not removed. Deleting it
resolves the opacity by destroying the content. R6-1 owns that extraction and targets
`knowledge-base/seo-content-os/`; this audit touches it only to say **hands off**. Note the
open licence question (research O-18) blocks seeding, not extraction.

**`aios-publisher.zip` is not a duplicate — it is a stale build with client impact.**
Verified by comparison: the zip is plugin **v1.4.0** and contains 4 files; the source
folder is **v1.7.0** and contains 8, including the entire `includes/` directory —
`core-connector.php`, `auto-publisher.php`, `design-reconstruction.php`,
`theme-adapter.php`, ~1,475 lines, i.e. most of the plugin.

And `push-to-wordpress.ps1` instructs the operator: *"Install + activate the AIOS
Publisher plugin (`aios-publisher.zip`)"*. **So the documented install procedure ships a
three-versions-stale plugin, missing most of its code, to a client's WordPress site.**
That is a live defect surfaced by a folder audit, not a tidiness item. Deleting the zip
and correcting the instruction to build from source fixes it.

`spotino-theme.zip` is genuinely redundant — `diff -rq` against `spotino-theme/` reports
no differences.

Where a distributable is genuinely needed it should be produced by a build step, not
committed; `.gitignore` already carries `wordpress-plugin/aios-publisher.zip`, so the
intent existed and the root copy simply escaped it.

### 2.2 Files at the root that belong to nothing

> **⚠️ ALSO CORRECTED.** The "0 files" against the HTML below was an artefact of the same
> filtered grep. `push-to-wordpress.ps1:23` reads it: `$ContentFile = Join-Path
> $PSScriptRoot "best-ai-agents-for-seo-agencies-2026.html"`.

| Path | Size | Verified disposition |
|---|---|---|
| `push-to-wordpress.ps1` + `best-ai-agents-*.html` + `best-ai-agents-*.png` | ~452 KB | **Move together — a coherent tool, not three orphans.** |
| `scratchpad-hero/hero.html` | 4 KB | **Delete** — zero references anywhere, scratchpad by its own name. |
| `Start-Backend.bat`, `Start-Dashboard.bat`, `Finish-Citations.bat` | — | **Leave at root.** |

The first three are **one artefact**: a one-shot demo publisher, the article it publishes,
and that article's featured image. Separating them would break the script; deleting the
HTML — as the first draft of this audit proposed — would break it silently, since the
failure would only appear when an operator next ran it. They move together to
`tools/wordpress-demo/`, with the `$PSScriptRoot` reference still resolving because the
script and its content stay side by side.

**The `.bat` launchers stay at root, reversing this audit's first recommendation.** They
are double-click entry points for a non-technical operator, and each resolves its paths
from `%~dp0` — its own directory — assuming that directory is the repo root
(`cd /d "%~dp0backend"`, `backend\.venv\Scripts\python.exe tools\finish_citation.py`).
Moving them requires rewriting those paths, and **a Windows batch file cannot be executed
or tested from this environment.** Moving an operator's untestable entry point to buy
tidiness is a bad trade: the downside is a client-facing workflow that silently stops
working, and the upside is three fewer lines in a directory listing. A launcher at the
repository root is as legitimate as a `Makefile`; it is not clutter merely because it is
platform-specific.

### 2.3 A second, undocumented frontend

`dashboard/` (52 KB: `index.html`, `bridge.py`, `worker.py`) is a separate operator UI
that no deployment references — `docker-compose.yml`, the Dockerfiles and even
`Start-Dashboard.bat` all point at `frontend/`. Its practical effect has been *design
contamination*: the maroon/blush palette that leaked into five Next.js screens as
undefined-variable fallbacks originates here.

It is either a real tool that belongs in `tools/` with a README, or it is dead. It cannot
stay a third thing.

### 2.4 Documentation in three places with overlapping remits

| Location | Files | Size | Contains |
|---|---|---|---|
| `context/` | 6 | 2.8 MB | architecture + plan, workflow/data-flow/API-research PDFs |
| `knowledge-base/` | 7 | 56 KB | architecture, modules, data-model, cost, deploy, APIs |
| `docs/` | 54 | 14 MB | recovery, audit, research, implementation, deliverables, meeting-notes |

`context/ARCHITECTURE-AND-PLAN.md` and `knowledge-base/architecture.md` describe the same
system to different depths. When they disagree, nothing says which wins.

This is not hypothetical. This repository has already been damaged twice by exactly this:
a false invariant in `backend/CLAUDE.md` propagated into the recovery specification as
`[CONFIRMED]` evidence for a headline defect, and a forensic audit's RED verdict rested
on a figure off by 17×. **Ambiguous documentation locations produce confidently wrong
documents**, and here they went on to scope engineering work.

### 2.5 Dead frontend code with no owner

`components/{backups,gmb,milestones,tiers,upsells}/` — 19 files, **zero importers**
(verified twice). Their admin pages were deleted in `158c204`; the components were not.
Part of ~5,900 orphaned lines (~20% of the frontend), alongside 81 dead CSS classes and 26
exported-but-unused hooks.

> **⚠️ These are NOT a cleanup item, and this audit does not delete them.** Checked against
> `DECISIONS_LOG.md`: **milestones are explicitly inside the v1 Portal module**
> (*"task queue, review checkpoint, milestones, notifications…"*) and **upsells are v1 too**
> (D-7: *"keep in portal + free audit; remove only the Reports-tab instance"*). So two of
> the five directories are dead **because their page was removed, not because the feature
> was** — and v1 has to rebuild that UI. Deleting it would destroy work the plan requires,
> which is the opposite of cleanup.
>
> The correct disposition is per-directory and it is a **product decision**: for each, is
> the feature v1, v1.1, or gone? Only "gone" justifies deletion. `gmb` maps to GBP posts
> (deferred to v1.1), `backups` is ops tooling, `tiers` is unresolved. Left in place with
> this note rather than guessed at.

The hooks are the interesting ones: they front **working backend endpoints with no UI** —
report-grant management, password change, Sheets sync, GSC/GA4 sync, key rotation. That
is paid-for capability with no front door, and the folder structure is why nobody noticed.

### 2.6 Migration numbering has already collided

`0070` and `0072` each appear twice; `0052` is missing. They apply in filename order so
it currently works, but the ledger keys on filename and applied files must not be renamed
— so this is permanent, and the only fix available is preventing the next one.

---

## 3. The target

Two rules generate the whole thing:

> **R1 — The structure names the product, not its build order.** Five modules, three
> portals. A stranger should locate "the citation submitter" or "what the client sees"
> without grep.
>
> **R2 — One home per concept.** Every file has exactly one defensible location, and a
> second copy is a defect, not a convenience.

### 3.1 Root

```
danyals-aios/
├── backend/          FastAPI + workers
├── frontend/         Next.js
├── audit-engine/     (renamed from danyals-audit-system/ — it is a product, not a person)
├── db/               migrations + schema
├── infra/            deploy, systemd, Caddy, CI
├── wordpress-plugin/ the AIOS Publisher plugin (source only; zip is built)
├── docs/             ALL documentation (see 3.4)
├── scripts/          operator + dev scripts, incl. the .bat launchers
├── tools/            standalone operator tools (incl. dashboard/, or it is deleted)
└── README.md · docker-compose.yml · dotfiles
```

Everything in §2.1 and §2.2 is deleted or moved. `spotino-theme/` — a sample WordPress
theme used as a publish target — moves to `tools/fixtures/` or leaves the repo entirely;
it is test data, not product.

### 3.2 Backend — finish the migration that was started

```
backend/app/
├── core/            auth, RLS seams, errors, middleware, cost gate, jobs contract
├── modules/         ONE package per capability — the only place features live
│   ├── portal/      admin · team · client
│   ├── audit/
│   ├── content/     incl. the WordPress publishing subsystem
│   ├── offpage/
│   │   ├── citations/
│   │   └── web2/
│   ├── policy_radar/
│   └── ... (the 15 existing packages, unchanged in shape)
├── integrations/    grouped by provider domain, not flat
│   ├── citations/ · web2/ · wordpress/ · serp/ · google/ · llm/
└── workers/         thin Celery entry points only; logic lives in modules
```

`routers/`, `schemas/`, `services/`, `db/` stop being top-level homes for feature code and
retain only genuinely cross-cutting pieces. **The pattern is not new** — it is the one
already working in 15 packages. This is finishing a migration, not starting one.

### 3.3 Frontend — make the three portals structural

```
frontend/
├── app/
│   ├── (admin)/ · (team)/ · (client)/ · (public)/
└── components/
    ├── admin/     the 16 currently-loose admin dirs, grouped
    ├── team/      ← components/portal/
    ├── client/    ← components/client/ (and `clients/` becomes admin/clients/)
    ├── shared/    charts, report viewer, layout chrome
    └── ui/        primitives — Button, Modal, Table, Field, StatusPill
```

`ui/` currently holds **2 primitives for 136 components**, which is why there are 450
inline `style={{}}` blocks and `useCountUp` is defined **11 separate times**. The absence
of a primitives layer is a structural cause, not a styling preference.

This also removes the `client`/`clients` and `report`/`reports` collisions by construction.

### 3.4 Documentation — one tree, with precedence

```
docs/
├── architecture/   how the system is built (absorbs context/ + knowledge-base/)
├── modules/        one document per v1 module
├── operations/     deploy, runbooks, credentials
├── decisions/      ADRs — the tie-breaker when documents disagree
├── research/       Phase 1 evidence records (dated, sourced)
├── recovery/       the recovery record (historical; corrected, never silently edited)
└── client/         deliverables handed to Daniel
```

`context/` and `knowledge-base/` are merged into `architecture/` and deleted. **Precedence
is stated at the top of `docs/README.md`**: ADRs > architecture > module docs > research
notes. Every document carries a date and a status.

---

## 4. Roadmap — sequenced against the recovery plan

Structure work is disruptive: it moves files other work is editing, and it makes `git
blame` and in-flight diffs harder. So it is sequenced by *risk*, and the large moves are
deliberately placed where they cannot collide with module work.

### Stage A — litter (safe now, ~1 hour, zero behaviour change)

Deletions and moves only; nothing imports any of it.

1. Delete `spotino-theme.zip` (byte-identical duplicate), `aios-publisher.zip` (stale
   v1.4.0 missing `includes/`; correct the install instruction that points at it), and
   `scratchpad-hero/`. **`SEO-CONTENT-OS.zip` is NOT deleted** — see §2.1.
2. Move `push-to-wordpress.ps1` + its HTML + its PNG together into
   `tools/wordpress-demo/`. **The `.bat` launchers stay at root** — see §2.2.
3. **Deferred, not done:** the 19 orphaned components, 81 dead CSS classes, 6 dead
   `EXTRAS` entries and 26 dead hooks. Every one is a **product** call (§2.5) — two of the
   five component directories belong to v1-scoped features whose pages were removed, and
   the hooks front working endpoints. Cleanup does not get to decide what ships.
4. **Deferred:** `dashboard/` — `tools/` with a README, or delete. Also a product call.
5. Add the CI guards in §5 — **first**, so nothing regresses while the rest proceeds.

**Gate:** full suite unchanged; `tsc` clean; no import resolves to a deleted path.

### Stage B — documentation consolidation (safe now, ~half a day)

Merge `context/` + `knowledge-base/` into `docs/architecture/`, establish precedence in
`docs/README.md`, date and status every document. Reconcile the two architecture
documents into one and record the differences as ADRs rather than deleting either
silently.

**Do this early.** Documentation ambiguity is not cosmetic here — it has already produced
two confidently wrong documents that went on to scope engineering work.

### Stage C — backend module consolidation (after P0-5, per module)

**Not one migration.** One module at a time, each its own commit, each with its full
suite green before the next begins:

1. **Off-page first** — it is the worst split (citations in `modules/`, Web 2.0 in
   `routers/`) and it is the module whose rebuild is already planned, so the move and the
   rework land together instead of twice.
2. Content + WordPress · 3. Audit · 4. Portal · 5. `integrations/` grouping.

**Blocked until the beat-schedule work settles.** `celery_app.py` pins task names and
`include=[...]` paths; moving a task module while the scheduler is being repaired risks
silently unregistering it. Every Celery task is already `name=`-pinned, so routing
survives a move — but the `include` list and a task-registration smoke test must land in
the same commit.

### Stage D — frontend portal restructure (with the Portal slice, Phase 3.1)

Do it *with* the portal work, not before. It touches nearly every import path; doing it
separately means paying the review cost twice. Extract the `ui/` primitives first — that
is what removes the 450 inline styles and the 11 `useCountUp` copies.

---

## 5. Guardrails — so it cannot rot back

Structure decays silently unless something refuses the decay. These are cheap and
mechanical, and this repository already uses the pattern (`test_dial_registration.py`,
`test_backlinks_own_profile.py`, `test_no_synthetic_providers_in_production.py`).

### First, the order of remedies — a guard is the weakest of the three

> **Eliminate the duplicate · then generate it · then guard it.**

Added 2026-08-24, from the RBAC single-source work, and it is a correction to how the
rest of this section was originally framed. Faced with the backend RBAC matrix and its
hand-mirrored copy in `frontend/lib/data.ts`, the obvious fix is codegen — emit the
TypeScript from the Python so the two cannot drift. That was **rejected in favour of
something better**: have the dashboard read `GET /rbac/*` and delete its copies outright.

The reasoning generalises, so it belongs here rather than in that module's notes:

| Remedy | What is left on disk | What keeps it true |
|---|---|---|
| **Eliminate** | one copy | nothing needs to — there is nothing to diverge |
| **Generate** | two copies | a build step, plus a guard that it was re-run |
| **Guard** | two copies | a test, and whoever reads its failure |

A guard is a **detector**, not a cure: it announces drift that has already happened, and
it only works while someone believes its output. That is not hypothetical here — the
species of defect catalogued in §2.4 is precisely a guard (`test_rbac_matrix.py`) whose
name claimed a comparison its body never performed, sitting green for months.

So every guard below should be read as *"the best available remedy given that the
duplicate is staying"*. Where the duplicate can be **removed instead**, remove it, and
the guard becomes unnecessary rather than merely satisfied.

| Guard | Refuses |
|---|---|
| **Migration ordinal uniqueness** | a third `0070`. Applied files are never renamed, so prevention is the only fix available. |
| **No binary artefacts in source** | a committed `.zip`/`.png` outside an assets allow-list. |
| **Feature code lives in `modules/`** | a new file in `app/routers/` or `app/services/` that is not on the cross-cutting allow-list. Fails with the reason. |
| **Portal import isolation** | a `/client` page importing an admin component. This one is a **security** guard, not a tidiness guard: the client portal is where a wrong import is a data breach. |
| **No orphaned components** | a `components/**` file with zero importers. |
| **Docs precedence** | a document with no date or status header. |

The portal-isolation guard is the highest-value item in this table and should ship with
Stage A rather than waiting for Stage D.

---

## 6. What this is not

Not a rewrite. Every proposal is a **move, a delete, or a guard** — no behaviour changes,
no logic rewritten, no architecture invented. The backend target is the pattern already
working in 15 packages; the frontend target is the separation the import graph already
has and merely fails to name.

Nor is it urgent in the way the truth defects were. A publish that lied to a client cost
trust immediately; a confusing folder costs a little every day and compounds. It is
sequenced accordingly — the cheap safe wins now, the invasive moves alongside the module
work that was going to touch those files anyway.
