# Documentation

As of **2026-09-17** this tree is the v2 blueprint plus the minimum v1 carries forward.

| Directory | Contents | Status |
|---|---|---|
| [`aios-v2/`](aios-v2/) | the complete v2 rebuild blueprint: scope, requirements, SDLC, architecture, data model, API, AI stack, security, testing, infra, roadmap, ADRs, glossary, salvage map, module specs, agent instructions | **current — governs all work** |
| `scope/` | the pre-scope discovery questionnaire that produced the pack | historical, 2026-09-16 |
| `audit/fixtures/` | recorded real audit runs — **load-bearing for tests** (`backend/tests/test_audit_altitude.py`, `frontend/lib/auditAltitude.test.ts` pin against run 837b75d6) | current, do not delete |

Start at [`aios-v2/README.md`](aios-v2/README.md). When any other document — or code
comment, or memory — disagrees with the pack, the pack wins.

## Where everything else went

Every v1 document (architecture as-built, implementation logs, operations/deploy
runbooks, forensic audits, research records, recovery plans, meeting notes, the client
deliverables PDF pack) was removed from `main` on 2026-09-17 and is preserved verbatim at:

- branch **`v1-archive`** (on origin) — also carries `docs/scope/`
- tag **`v1-final`** = commit `e3bb2c8`, the complete pre-cut-over tree

Retrieve any file with `git show v1-archive:docs/operations/deploy.md` (etc.), or check
the branch out. For deploy specifics that are still live, `infra/deploy/README-deploy.md`
remains in the tree.
