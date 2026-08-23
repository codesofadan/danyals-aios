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

| Path | Size | Problem |
|---|---|---|
| `SEO-CONTENT-OS.zip` | 1.1 MB | **A zip with no source folder in this repo.** Opaque blob; nothing can review, diff or test it. |
| `aios-publisher.zip` | 24 KB | Duplicates `wordpress-plugin/aios-publisher/`. Two copies, one reviewable. |
| `spotino-theme.zip` | 16 KB | Duplicates `spotino-theme/`. Same. |

A zip in version control is a diff nobody can read. Where a distributable is genuinely
needed, it should be produced by a build step, not committed — and `.gitignore` already
carries `wordpress-plugin/aios-publisher.zip`, so the intent existed and the file at the
root simply escaped it.

### 2.2 Files at the root that belong to nothing

| Path | Size | Referenced by |
|---|---|---|
| `best-ai-agents-featured.png` | 428 KB | 1 file |
| `best-ai-agents-for-seo-agencies-2026.html` | 16 KB | **0 files** |
| `scratchpad-hero/hero.html` | — | scratchpad, by its own name |
| `push-to-wordpress.ps1` | 8 KB | 2 files |
| `Start-Backend.bat`, `Start-Dashboard.bat`, `Finish-Citations.bat` | — | operator launchers, undifferentiated from source |

These are a marketing artefact, a one-off scratch file, and platform-specific operator
scripts, all sitting at the same level as `backend/` and `frontend/`. The root of a
repository is the first thing a new engineer — or a client's future developer — reads.
Ours currently says "assorted".

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

`components/{backups,gmb,milestones,tiers,upsells}/` — 19 files, **zero importers**.
Their pages were deleted; the components were not. Part of ~5,900 orphaned lines
(~20% of the frontend), alongside 81 dead CSS classes and 26 exported-but-unused hooks.

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

1. Delete `SEO-CONTENT-OS.zip`, `aios-publisher.zip`, `spotino-theme.zip`,
   `best-ai-agents-*.{png,html}`, `scratchpad-hero/`.
2. Move the three `.bat` files and `push-to-wordpress.ps1` into `scripts/`.
3. Delete the 19 orphaned frontend components, 81 dead CSS classes, and the 6 dead
   `EXTRAS` entries — **after** deciding the 26 dead hooks (§2.5): each is either wired
   to a UI or deleted with its endpoint, and that is a product call, not a cleanup call.
4. Decide `dashboard/`: `tools/` with a README, or delete.
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
