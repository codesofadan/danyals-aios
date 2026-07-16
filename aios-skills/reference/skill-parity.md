# Skill ↔ Dashboard Parity — one backend, two front doors

The aios-seo skills and the web Dashboard/Portal are **not two implementations**. They
are two front doors onto the **same** AIOS FastAPI backend, behind the **same** guards.
A skill run and a dashboard click land on the identical `/api/v1/...` engines, RLS
boundary, RBAC permissions, and cost-gate — so they cannot diverge in what they produce
or what they are allowed to do.

## The two front doors

| | Local skills (this plugin) | Web in-product AI (`POST /api/v1/ai/assist`) |
|---|---|---|
| Who calls the backend | `scripts/aios_client.py` (bearer = skill token) | the dashboard/portal → our backend |
| Who holds the model key | **nobody local** — the backend calls Claude | **nobody client-side** — the backend calls Claude |
| Auth | skill-token gateway (P9-1) → a real user role | the logged-in staff session (`view_reports`) |
| RLS | enforced on every query (token's verified id) | enforced on every query (session's verified id) |
| Cost | metered by the money-dial cost-gate | metered by the money-dial cost-gate (`ai_assist` dial) |
| Heavy generation | the module engine (content pipeline, audit, …) | the **same** module engine — `/ai/assist` only routes + summarizes |

Neither door bypasses the other's protections. `/ai/assist` never generates a
deliverable itself: it interprets the plain-language request and points at the module
endpoint that owns the real workflow — exactly the endpoint a skill would call.

## What the harness proves

`backend/tests/test_skills_plugin.py` (a `unit` test) locks this parity in at build time:

- **every** `/api/v1` path a `SKILL.md` body references is a **real route** on
  `app.main:app` (modulo `{param}`). A documented skill call therefore always maps to
  an actual backend call — the same call the dashboard makes.
- every skill's frontmatter is well-formed (name = folder, third-person description
  < 1024 chars, least-privilege `allowed-tools` with no bare `Bash(*)`, body < 500 lines).
- every skill that **writes / publishes / spends** sets `disable-model-invocation: true`
  (a human runs it — the money-dial + review gates are not enough on their own).
- `plugin.json` is valid and all 22 skills are present.

## Keeping it green

If a backend route is renamed or removed, the parity test fails until the SKILL.md that
cites it is updated — the same contract-lock discipline `reference/output-formats.md`
applies to response fields. Add a new writer/spender skill → give it
`disable-model-invocation: true`. Add a new skill → add it to `EXPECTED_SKILLS` in the
harness. The dashboard's `/ai/assist` surface and the skills stay in lockstep because
they share one engine, not because anyone keeps two copies in sync by hand.
