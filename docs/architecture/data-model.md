# Data model

The source of truth is the ordered SQL in `db/migrations/` (`0000`–`0053`) with a snapshot
at `db/schema.sql`. This page indexes the tables by domain with their migration number.
Grounded in `backend/CLAUDE.md`, `ARCHITECTURE-AND-PLAN.md`, and the migration set.

## The two hard rules (never move)

1. **Migrations are ONE global ordered sequence** in `db/migrations/` — never per-module.
   The fresh-apply gate (`db/ci/verify_fresh_apply.py`) rebuilds a scratch DB and applies
   `0000…` in order to prove order-cleanliness.
2. **RLS is the tenant boundary.** Every base table is `ENABLE`+`FORCE ROW LEVEL
   SECURITY`; the CI gate `app/db/rls_check.py` fails on any unprotected `public` table.
   Staff read via `is_staff()`; a portal **client** reads ONLY through **security-barrier
   views** (`portal_audits`, `portal_client`, `portal_sites`, + later portal views)
   filtered by `current_client_id()` — there is **no client SELECT policy on any base
   table**. Writes that must bypass RLS go through `privileged_connection` (service_role),
   but DB **guard triggers** still bind them.

## Tables by domain (→ migration)

**Substrate / identity / access**
- `0000` local platform substrate · `0001` conventions · `0002` identity (`auth.users`,
  `public.users`, `user_feature_grants`) + RBAC · `0009` adds the `client` role ·
  `0010` client-portal views + `current_client_id()` · `0016` user-login.
- `0003` `clients`, `sites` · `0051` `client_business_profile` (NAP at creation).
- `0004` vault (`vault_secrets`) · `0041` adds `vault kind`.
- `0005` `activity_log` (append-only) · `0006` cost (`cost_dials`, `budgets`, `cost_log`)
  · `0044` numeric cost budget · `0007` delivery tier.

**Audit**
- `0008` `audits` · `0015` public/free audits · `0027` audit overlay (Policy Radar loop).

**Context / AI-memory**
- `0013` `context_dirty` (debounced outbox from the activity-log trigger) · `0014`
  `entity_context` + `context_vectors` (Postgres = source of truth; Pinecone = derived).

**Team / tasks**
- `0011` `tasks` (public `J-####` code) + RLS + `tasks_guard_update` trigger · `0012`
  guard hardening · `0029` member onboarding flags.

**Content**
- `0017` `content_jobs` + the 3-actor `content_jobs_guard_update` trigger · `0049` GBP-post
  extension.

**Off-page / citations / Web2**
- `0018` `backlinks` + `citations` · `0028` web2 publish · `0045` citation+web2
  automation · `0046` directories seed · `0048` directories strategy.

**Policy Radar**
- `0019` policy sources / kb entries / change events / recommendations · `0050` sources
  seed.

**Delivery + ops**
- `0020` reports + SheetStore · `0021` milestones · `0022` upsells · `0023` notifications
  · `0024` tickets · `0025` settings · `0026` backups.
- Client portal: `0031` `client_report_grants` · `0032` `client_deliverables` · `0033`
  support-tickets portal extension · `0034` portal milestone views.

**Tool modules (Part 8)**
- `0035` keyword_research · `0036` rank_tracker · `0037` competitor_intel (adds
  `competitor_id` to `backlinks` — every off-page query pins `competitor_id is null`) ·
  `0038` on_page · `0039` local_seo (exactly 3 tables) · `0040` client_onboarding +
  `0041` vault kind · `0042` data_import · `0043` billing · `0047` site_analytics ·
  `0053` gmb posts.

**Skills**
- `0030` `skill_tokens` (scoped per-client sha256 tokens for the skills gateway).

## What lives where (the data-plane decision)

- **PostgreSQL 16** holds identity, secrets (sealed), the knowledge base, and every module
  ledger — accessed only through the two seams with RLS as the tenant boundary.
- **Google Sheets** holds client-facing operational records (reporting layer).
- **Redis** is the job queue + cache + a Sheets write-buffer (separate DBs: cache=0,
  broker=1, result=2).

## Applying + verifying

```bash
# apply migrations (native install does this): psql over db/migrations/*.sql in order
# verify RLS coverage:
backend/.venv/Scripts/python -m app.db.rls_check          # needs DATABASE_URL
# prove the ordered set applies cleanly on a scratch DB:
backend/.venv/Scripts/python db/ci/verify_fresh_apply.py
```

Response shapes are **contract-locked** to `frontend/lib/*.ts`
(`backend/tests/test_contract_lock.py`) — build/adjust endpoints to match those types so
the dashboard works unchanged.
