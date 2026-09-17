# 14 · Salvage Map — what to take from v1

v1 is **evidence of what was tried**, not a specification. It is ~82k lines of backend
Python, ~30k of TypeScript, 147 migrations and a separate 20k-line audit engine, running at
`app.qanry.com`. A great deal of that is hard-won domain knowledge that would be expensive to
rediscover. A great deal of the rest is the architecture this rebuild exists to replace.

**Rule: port knowledge, not structure.** Every item marked PORT is read, understood and
rewritten against the v2 contracts — never copied wholesale.

---

## Port — high value, rewrite against v2 contracts

| v1 location | What is worth having | Port into |
|---|---|---|
| `danyals-audit-system/checklists/`, `knowledge/` | The audit checklists, scoring rubrics and GEO/AI-search checks. This is years of SEO domain knowledge encoded as rules | M02 |
| `backend/app/services/design_system.py` | Computed-style recovery with the declared-beats-derived rule, validated against a real page where derived extraction recovered six author-declared tokens exactly | M03 design analysis |
| `backend/app/services/color_spaces.py` | CSS Color 4 transforms (`oklch()`, `lab()`, `lch()`). Verified without trusting any colour table — `lab()` and `oklch()` as independent paths converging on the same byte | M03 (`platform/` utility) |
| `backend/app/services/site_design.py` | The vision-corroboration approach and the reasoning behind it (a plain GET returns an empty JS shell) | M03 design analysis |
| `backend/app/services/form_intelligence.py` + `extension/src/content/collector.ts` | The PII-free digest shape and the heuristic-then-model ordering. Live-verified across four form shapes | M04 |
| `db/migrations/0140_form_field_maps.sql` | The structural-fingerprint keying decision and its rationale | M04 |
| `app/modules/grid_tracker/` | Ring geometry, summary maths, and the three-state point model with its CHECK constraints | M07 |
| `backend/integrations/*` | **Provider behaviour notes** — how each API really behaves versus its documentation. Rate limits, error shapes, undocumented constraints | `docs/provider-notes/` |
| `backend/app/services/content_pipeline/` | The stage decomposition (research → outline → draft → grounding → links → schema → title/meta → QA) and the grounding/claims concept | M03 content graph |
| `backend/app/modules/citations/verticals.py`, `directory_names.py` | The directory list and vertical mapping, as **seed data** | M04 seed |
| `wordpress-plugin/aios-publisher/` | What was learned about writing Elementor meta: slashing, `_elementor_edit_mode`, CSS cache regeneration | M03 companion plugin |
| `docs/recovery/DECISIONS_LOG.md` | The owner's recorded decisions — scope baseline, ownership tiering, cost lines, approval doctrine | Already folded into this pack |
| `docs/audit/*` | The forensic audit and salvageability analysis — the honest account of what was broken and why | Context, not spec |

---

## Reference only — read, do not port

| v1 area | Why |
|---|---|
| `backend/app/services/` (≈100 modules) | The service layer's shape is the problem this rebuild addresses: cross-module table access, scattered model calls, no consistent provider contract |
| `backend/app/routers/` + `app/modules/*/router.py` | Two competing routing conventions. v2 has one |
| Celery configuration and `_BEAT_SCHEDULE_DISABLED` | The schedule was disabled because the job contract was unsafe. v2 fixes the contract; the schedule config carries no information |
| `frontend/` | Useful for understanding the surfaces operators expect. The component architecture predates the generated API client and the provenance component |
| `backend/tests/` (339 files, ~4,900 tests) | **Do not port.** Many are vacuous by the criteria in `08-TESTING-AND-QUALITY.md` §1. Read them for the *cases* they cover, then write new tests that fail on re-injection |

---

## Delete — do not carry forward

| v1 artefact | Why |
|---|---|
| Any `Fake*` provider outside tests | The class of defect the truth gate exists to prevent |
| The Sheets-as-store layer and its Redis write-buffer | ADR-018: Sheets is a format, not a store |
| `seed_web2_vault` CLI | It copies one house credential set into every client's vault — the shared-footprint pattern ADR-014 retires |
| Aggregator submission paths (Yext / Data Axle / Apify) | ADR-012: out, and not as a stub |
| `danyals-audit-system/.../geo_grid.py` | Orphaned **and wrong** — sent `location="lat,lng"` into a parameter expecting a place name, returning an unlocalised SERP for every point: a perfectly smooth, entirely fictional heat map |
| The subprocess audit-engine seam | ADR-020 |
| Hand-maintained per-directory DOM specs | ADR-011 |
| Any code path that records `status="done"` for unperformed work | The defect this pack is built around |
| Vendored `test-venv/`, `test-venv2/`, `logs.zip`, `0_build.txt` | Build detritus |

---

## Data migration

**Decision: no automated data migration from v1.** Start clean, re-onboard clients.

Why: v1 holds data produced under the defects this rebuild eliminates — measurements that may
be synthesised, grid points whose states were blurred, publishes recorded as `done` that
published nothing, and rank series that mix sources. Importing it would carry that
uncertainty into a system whose entire premise is that its numbers are trustworthy.

**Exceptions, imported by hand with verification:**

| Import | Verification |
|---|---|
| Client records, profiles, canonical NAP | Re-verified against GBP or the client's own site before use |
| Directory registry and platform registry | As seed data; terms positions re-checked and dated |
| Live citation listings | Only those that pass a fresh liveness fetch and NAP match. A v1 row claiming `live` is a candidate, not a fact |
| Web 2.0 properties and accounts | Only accounts that authenticate successfully now; properties only where the URL resolves |
| Published content URLs | Recorded as existing pages for internal-linking purposes; not re-imported as content records |
| Provider credentials | **Rotated, not imported** — every credential exposed during v1 development is replaced |

Everything else — rank history, grid history, audit findings, job history, cost ledger —
starts empty. A short history that is true beats a long history that is not, and the client
is better served by "measurement begins now, and here is why" than by a chart nobody can
stand behind.

---

## The three lessons worth stating plainly

1. **A test that cannot fail is worse than no test.** v1 had ~4,900 tests and shipped a form
   filler that reported success while filling a honeypot, because the test environment made
   the failing branch unreachable.
2. **Silent degradation is the expensive failure mode.** Every v1 defect that reached a client
   — fictional heat maps, phantom publishes, hash-derived metrics — was a system continuing
   confidently with data it did not have.
3. **The job contract is the foundation, not a detail.** Almost every v1 reliability problem
   traces to work that could run twice, could not resume, and could not honestly say what it
   had done.
