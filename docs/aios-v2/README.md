# AIOS v2 — Build Blueprint

**This folder is the complete context pack for rebuilding AIOS from zero.**
Hand it to an AI coding agent in an empty repository and it can build the system
without asking a single clarifying question.

**Status:** approved scope, 2026-09-16 · **Supersedes:** every document in the v1 repo.

---

## Read in this order

| # | File | What it settles |
|---|---|---|
| 0 | [`00-EXECUTIVE-SCOPE.md`](00-EXECUTIVE-SCOPE.md) | What we are building, for whom, the 12 modules, what is explicitly out, and the ten engineering principles that make it bulletproof |
| 1 | [`01-PRODUCT-REQUIREMENTS.md`](01-PRODUCT-REQUIREMENTS.md) | Personas, user journeys, the numbered requirement register (`REQ-*`) |
| 2 | [`02-SDLC.md`](02-SDLC.md) | How work moves: phases, gates, branch policy, definition of done, review, release |
| 3 | [`03-ARCHITECTURE.md`](03-ARCHITECTURE.md) | Target architecture, runtime topology, the job engine, module boundaries |
| 4 | [`04-DATA-MODEL.md`](04-DATA-MODEL.md) | Schema, tenancy and RLS, provenance, migration rules |
| 5 | [`05-API-CONTRACT.md`](05-API-CONTRACT.md) | REST surface, auth, errors, pagination, idempotency, versioning |
| 6 | [`06-AI-STACK.md`](06-AI-STACK.md) | LangGraph / LangChain / LangSmith, model routing, cost gates, evals |
| 7 | [`07-SECURITY.md`](07-SECURITY.md) | Vault, RBAC, RLS, extension permissions, SSRF, secrets, audit |
| 8 | [`08-TESTING-AND-QUALITY.md`](08-TESTING-AND-QUALITY.md) | Test pyramid, non-vacuity rule, the seven CI gates |
| 9 | [`09-INFRA-DEVOPS.md`](09-INFRA-DEVOPS.md) | Single-VPS topology, containers, deploy, backups, observability |
| 10 | [`10-BACKLOG-ROADMAP.md`](10-BACKLOG-ROADMAP.md) | Sequenced epics, the critical path, milestone exit criteria |
| 11 | [`11-ACCEPTANCE-CRITERIA.md`](11-ACCEPTANCE-CRITERIA.md) | Per-module done bars and the traceability matrix |
| 12 | [`12-DECISIONS-ADR.md`](12-DECISIONS-ADR.md) | Every architectural decision with its rationale and rejected alternatives |
| 13 | [`13-GLOSSARY.md`](13-GLOSSARY.md) | Domain vocabulary — read before writing any identifier |
| 14 | [`14-SALVAGE-MAP.md`](14-SALVAGE-MAP.md) | What to port from the v1 repo, what to rewrite, what to delete |
| 15 | [`15-REFERENCE-PRODUCTS.md`](15-REFERENCE-PRODUCTS.md) | SoMePoster and SEOSignalX — what was verified, what was not, and what we take from each |

**Module specifications** live in [`modules/`](modules/) — one file per module, each
with data model, flows, external dependencies, failure modes and acceptance tests.

**Drop into the new repo root:**
- [`CLAUDE.md`](CLAUDE.md) — the agent's standing instructions
- [`AGENTS.md`](AGENTS.md) — the working agreement (what it may and may not do)

**For humans / the client:** `AIOS-v2-Build-Blueprint.pdf` — the visual executive version.

---

## The one-paragraph brief

AIOS is a multi-tenant SEO operations platform for a single agency serving 50–100
client businesses. It runs twelve modules over one identity and one job engine: a
role-based **Portal**, an **Audit** engine (free lead-magnet and paid depth), a
**Content** system that learns a client's existing design system and writes and
publishes genuinely editable Elementor pages against an SEO keyword bank, a
**Citations** module driven by an operator-run browser extension with an AI agent that
creates accounts and fills directory forms, a **Web 2.0 / Social** publisher covering
32 platforms through official APIs, **Policy Radar**, **rank and geo-grid tracking**,
**keyword research**, **indexing**, **local/GBP**, **reporting** and **billing/tiers**.
Every paid call passes a cost gate, every tenant row is isolated by Postgres RLS, every
displayed number carries provenance, and no code path may ever invent data.

---

## How the agent should use this pack

1. Read `00`, `03`, `12` and `AGENTS.md` **before writing any code**.
2. Build in the order given by `10-BACKLOG-ROADMAP.md`. The order is load-bearing:
   platform core → job engine → one vertical slice → the rest.
3. Every task traces to a `REQ-*` id. If a task has no requirement, it is out of scope —
   raise it, do not build it.
4. When this pack and the v1 repo disagree, **this pack wins**. The v1 repo is evidence
   of what was tried, not a specification.
5. When this pack is silent, follow `12-DECISIONS-ADR.md` §Defaults, then ask.
