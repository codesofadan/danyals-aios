-- ============================================================================
-- AIOS - current schema snapshot (human-readable reference).
--
-- SOURCE OF TRUTH is db/migrations/*.sql (applied in order). This file is a
-- convenience snapshot kept in sync per chunk; regenerate against an applied
-- database with:  pg_dump --schema-only --schema=public "$DATABASE_URL"
--
-- Conventions (see 0001_conventions.sql): uuid PKs (gen_random_uuid),
-- created_at/updated_at timestamptz + set_updated_at() trigger, and every
-- table ENABLE + FORCE row level security with explicit policies.
-- ============================================================================

-- ---- 0000_local_platform -----------------------------------------------------
-- The self-hosted-Postgres SUBSTRATE (replaces the Supabase built-ins; sorts
-- FIRST). Roles anon (nologin) / authenticated (login, RLS binds) / service_role
-- (login, BYPASSRLS); schema auth + auth.users (id/email/password_hash, locked to
-- service_role); auth.uid()/role()/jwt() as GUC readers over app.user_id /
-- app.user_role / app.jwt_claims, STABLE with search_path pinned to pg_catalog.
-- MUST be applied by a BYPASSRLS superuser owner so the SECURITY DEFINER RLS
-- helpers do not recurse. See db/migrations/0000_local_platform.sql for the DDL.

-- ---- 0001_conventions --------------------------------------------------------
create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- ---- 0002_identity_rbac ------------------------------------------------------
-- Enums: app_role (owner/admin/manager/specialist/analyst/viewer), user_status.
-- Reference data (roles/permissions/features/templates) lives in code
-- (app/rbac/matrix.py), not tables.

create table public.users (
  id           uuid primary key references auth.users (id) on delete cascade,
  email        text not null unique,
  name         text not null,
  title        text not null default '',
  role         public.app_role not null default 'viewer',
  status       public.user_status not null default 'invited',
  avatar_color text not null default '#7B69EE',
  phone        text not null default '',
  two_fa       boolean not null default false,
  username     text,   -- (0016) local login key for the 3 portals; uuid stays the PK
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
-- + users_set_updated_at trigger; ENABLE + FORCE RLS; policies users_select
--   (self or staff), users_modify (owner/admin).
-- (0016) partial unique index users_username_key on (lower(username))
--   where username is not null - case-insensitive uniqueness; not an RLS boundary.

create table public.user_feature_grants (
  user_id     uuid not null references public.users (id) on delete cascade,
  feature_key text not null,
  level       text not null default 'full' check (level in ('full', 'view', 'off')),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (user_id, feature_key)
);
-- + trigger; ENABLE + FORCE RLS; policies select (self or staff), modify (owner/admin).

-- RLS helpers (SECURITY DEFINER, bypass RLS to avoid policy recursion):
--   public.current_app_role() -> app_role,  public.is_staff() -> boolean.

-- ---- 0003_clients_sites ------------------------------------------------------
-- Enums: sub_tier (Starter/Growth/Scale), sub_status (active/trial/past_due/paused).
-- No portal password column (client logins are Supabase Auth users).

create table public.clients (
  id                   uuid primary key default gen_random_uuid(),
  name                 text not null,
  industry             text not null default '',
  since_year           int,
  contact_name         text not null default '',
  contact_role         text not null default '',
  contact_email        text not null default '',
  contact_color        text not null default '#7B69EE',
  tier                 public.sub_tier not null default 'Starter',
  status               public.sub_status not null default 'trial',
  renews_at            date,
  mrr                  integer not null default 0,
  portal_admin         text not null default '',
  portal_seats         integer not null default 0,
  portal_two_fa        boolean not null default false,
  portal_last_login_at timestamptz,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create table public.sites (
  id         uuid primary key default gen_random_uuid(),
  client_id  uuid not null references public.clients (id) on delete cascade,
  domain     text not null,
  cms_type   text not null default 'wordpress',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
-- + triggers; ENABLE + FORCE RLS; select (is_staff), modify (owner/admin/manager).

-- ---- 0004_vault -------------------------------------------------------------
-- Agency API keys encrypted at rest with app-layer AES-256-GCM (VAULT_MASTER_KEY
-- in env, NEVER in Postgres). The DB stores nonce||ciphertext||tag + key_version +
-- masked metadata; there is NO SQL decrypt path (a dump yields nothing usable).
-- Reveal is owner-only, enforced in the router/service. Replaces the former
-- Supabase-Vault design (the vault schema wrappers + secret_id column are gone).

create table public.vault_keys (
  id            uuid primary key default gen_random_uuid(),
  provider      text not null,
  label         text not null default '',
  masked        text not null default '',
  secret_sealed bytea not null,               -- 12-byte nonce || ciphertext || 16-byte tag
  key_version   int  not null default 1,
  created_by    uuid references public.users (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
-- + trigger; ENABLE + FORCE RLS; select + modify restricted to owner/admin
--   (reveal further restricted to owner in app/services/vault.py, not SQL).

-- ---- 0005_activity_log ------------------------------------------------------
-- Append-only audit feed. Actor identity snapshotted. Staff read only; writes
-- happen solely via the service_role server client (no user can tamper).

create table public.activity_log (
  id          uuid primary key default gen_random_uuid(),
  actor_id    uuid references public.users (id) on delete set null,
  actor_name  text not null default '',
  actor_init  text not null default '',
  actor_color text not null default '#7B69EE',
  kind        text not null,
  action      text not null,
  target      text not null default '',
  meta        text,
  created_at  timestamptz not null default now()
);
-- + created_at index; ENABLE + FORCE RLS; select (is_staff) only, no write policy.
-- 0013 adds seq/entity_type/entity_id + the enqueue trigger (see that section).

-- ---- 0006_cost --------------------------------------------------------------
-- The cost-control subsystem. dial_mode enum (api/byhand/off).
--   client_budgets(client_id PK, cap, spent)      - staff read, manage_clients write
--   cost_dial(feature_key PK, mode)               - staff read, owner/admin write
--   cost_settings(singleton: daily_stop, halted)  - staff read, owner/admin write
--   cost_log(client, job, provider, cost, cached) - append-only, staff read
-- add_budget_spend(client, amount) RPC = atomic spent increment (service_role).
-- The gate (app/services/cost_gate.py) reads these before any paid call.

-- ---- 0007_delivery_tier -----------------------------------------------------
-- delivery_tier enum (free/semi/fully) + clients.delivery_tier column. SEPARATE
-- from the subscription tier (clients.tier = Starter/Growth/Scale). Delivery tier
-- is a preset over the cost dial; the two are never conflated.
alter table public.clients add column delivery_tier public.delivery_tier not null default 'free';

-- ---- 0008_audits ------------------------------------------------------------
-- Module 01 Audit job ledger. One row per run against the external audit engine
-- (invoked as a subprocess by a Celery worker). Enums: audit_tier (free/paid),
-- audit_status (queued/running/done/failed). Shapes mirror lib/audit.ts.
create table public.audits (
  id           uuid primary key default gen_random_uuid(),
  client_id    uuid references public.clients (id) on delete set null,
  site_id      uuid references public.sites (id) on delete set null,
  client_name  text not null default '',
  url          text not null,
  types        text[] not null default '{}',       -- technical|actionable|local|geo|backlink
  tier         public.audit_tier not null default 'free',
  status       public.audit_status not null default 'queued',
  run_uuid     text,                                 -- engine mints this; we parse + store it
  artifact_dir text,
  pdf_path     text,
  json_path    text,
  score        integer,                              -- 0-100 composite; null while pending
  scores       jsonb not null default '{}',          -- per-category detail from run.json
  cost         numeric(10, 2) not null default 0,
  error        text,
  runtime_seconds integer,
  started_at   timestamptz,
  finished_at  timestamptz,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
-- + client_id & created_at indexes; ENABLE + FORCE RLS. select (is_staff);
-- modify by run_audits holders (owner/admin/manager/specialist/analyst). The
-- worker updates rows via the service_role client (bypasses RLS by design).

-- ---- 0009_app_role_client ---------------------------------------------------
-- Add a 7th app_role label, 'client', in its OWN committed migration (Postgres
-- forbids using a new enum label in the txn that adds it - 55P04). 'client' is a
-- portal login OUTSIDE the 6-role governance matrix; is_staff() excludes it.
alter type public.app_role add value if not exists 'client';

-- ---- 0010_client_portal -----------------------------------------------------
-- The client trust boundary. users.client_id links a role='client' login to one
-- clients row (CHECK: client_id is set iff role='client'). is_staff() is
-- REDEFINED to exclude clients, so every staff-scoped base-table policy
-- default-denies a client. current_client_id() returns the caller's tenant id.
-- Clients read ONLY through three SECURITY-BARRIER views (no client select policy
-- on any base table), each exposing a safe column subset self-filtered by
-- current_client_id(); the views are owned by a BYPASSRLS role with
-- security_invoker left default (false), so the view filter is the boundary.
alter table public.users
  add column client_id uuid references public.clients (id) on delete cascade;   -- NULL for staff
-- + users_client_id_idx; CHECK users_client_id_role_chk ((role='client')=(client_id is not null)).

create or replace function public.is_staff() returns boolean
  language sql stable security definer set search_path = ''
  as $$ select exists (select 1 from public.users where id = auth.uid() and role <> 'client') $$;
create or replace function public.current_client_id() returns uuid
  language sql stable security definer set search_path = ''
  as $$ select client_id from public.users where id = auth.uid() and role = 'client' $$;

-- portal_audits (excl. cost/error/artifact_dir/run_uuid/pdf_path/json_path;
-- has_pdf/has_json booleans instead), portal_client (id/name/industry/
-- delivery_tier), portal_sites (id/domain). All WITH (security_barrier=true),
-- WHERE ... = current_client_id(); SELECT granted to authenticated, anon.
create or replace view public.portal_audits with (security_barrier = true) as
  select id, client_id, url, types, tier, status, score, scores, runtime_seconds,
         created_at, started_at, finished_at,
         (pdf_path is not null) as has_pdf, (json_path is not null) as has_json
  from public.audits where client_id = public.current_client_id();
create or replace view public.portal_client with (security_barrier = true) as
  select id, name, industry, delivery_tier
  from public.clients where id = public.current_client_id();
create or replace view public.portal_sites with (security_barrier = true) as
  select id, domain from public.sites where client_id = public.current_client_id();

-- ---- 0011_tasks -------------------------------------------------------------
-- Part 5 Team Flow: the task / workflow-board ledger. One row per team work
-- item. Enums: task_type (technical_audit/actionable_audit/content_sprint/
-- backlink_audit/local_seo/publishing), task_priority (urgent/high/med/low),
-- task_status (todo/in_progress/review/done). `code` is the PUBLIC J-#### id
-- rendered in the frontend badge (sequence tasks_code_seq start 2042); never a
-- UUID. Shapes mirror lib/data.ts (Task) + portal.ts (the lifecycle).
create sequence if not exists public.tasks_code_seq start 2042;

create table public.tasks (
  id           uuid primary key default gen_random_uuid(),
  code         text not null unique
                 default ('J-' || to_char(nextval('public.tasks_code_seq'), 'FM0000')),
  title        text not null,
  client_id    uuid references public.clients (id) on delete set null,
  client_name  text not null default '',
  type         public.task_type not null,
  assignee_id  uuid references public.users (id) on delete set null,
  priority     public.task_priority not null default 'med',
  status       public.task_status not null default 'todo',
  due_date     date,
  audit_id     uuid references public.audits (id) on delete set null,  -- forward-link, v1-unused
  created_by   uuid references public.users (id) on delete set null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
-- + assignee_id/status/created_at/client_id indexes; ENABLE + FORCE RLS.
-- Policies: select (is_staff); insert (owner/admin/manager = assign_tasks);
-- update (assignee_id = auth.uid() OR owner/admin/manager) - the actor guard.
-- No delete policy/endpoint in v1.
--
-- THE BOUNDARY: the lifecycle + review checkpoint are enforced at the DB, not
-- only in FastAPI (a specialist could PATCH PostgREST directly with their JWT).
-- tasks_guard_update() (BEFORE UPDATE, SECURITY DEFINER, empty search_path):
--   (1) a non-null assignee_id must be a staff user (role <> 'client'), else raise;
--   (2) a lead (owner/admin/manager) may make any legal edit -> return new;
--   (3) a non-lead may change ONLY status, and only along a legal transition
--       (todo->in_progress; in_progress->review iff type=content_sprint;
--        in_progress->done iff type<>content_sprint) - so entering/leaving
--       `review` and leaving `done` are lead-only. Any other change raises
--       (0012 added id + created_at to that lock - immutable for a non-lead).
-- tasks_guard_insert() (BEFORE INSERT) likewise rejects a client-role assignee.

-- ---- 0012_tasks_guard_hardening ---------------------------------------------
-- Redefines tasks_guard_update() to also lock `id` and `created_at` against a
-- non-lead edit (they were omitted from 0011's column-lock). create or replace,
-- idempotent. No schema shape change.

-- ---- 0013_context_events ----------------------------------------------------
-- Context / AI-memory EVENT BACKBONE (P6B-1). Additive on the append-only
-- activity_log (no new write policy): links every event to a typed entity and
-- gives it a monotonic total order; a trigger coalesces affected entities into a
-- debounced dirty-queue the compaction worker drains.
--   type context_entity as enum ('client','user','site')
--   activity_log += seq bigint (default nextval public.activity_seq, not null,
--     unique; backfilled in created_at,id order), entity_type context_entity,
--     entity_id uuid; partial index (entity_type, entity_id, seq) where linked.
--   context_dirty(entity_type, entity_id [PK], last_seq, event_count,
--     first_dirty_at, next_eligible_at, status check in ('pending','processing'))
--     - ENABLE+FORCE RLS; select is_staff() only; NO write policy.
--   activity_enqueue_context() AFTER INSERT on activity_log (SECURITY DEFINER,
--     empty search_path): NULL entity -> skip; else upsert ONE context_dirty row
--     per entity - debounce next_eligible_at = least(existing, now()+30s),
--     coalesce event_count, last_seq = greatest(...), re-arm processing->pending.

-- ---- 0014_entity_context ----------------------------------------------------
-- CANONICAL CONTEXT STORE + Pinecone ledger (P6B-2). Postgres = source of truth;
-- Pinecone = a derived index reconstructable from context_vectors.
--   type context_status as enum ('pending','summarized','degraded','error')
--   entity_context(id, entity_type context_entity, entity_id uuid, summary text,
--     facts jsonb '{}', token_budget int 1200, token_count int 0, version int 0,
--     event_watermark bigint 0, status context_status 'pending', model text,
--     checksum text, created_at, updated_at; unique (entity_type, entity_id))
--     + set_updated_at() trigger. The living-context row per entity; the worker
--     upserts on (entity_type, entity_id) and bumps version/watermark/status.
--   context_vectors(id, entity_type, entity_id, chunk_key text, pinecone_id text,
--     content_checksum text, version int, dim int, model text, embedded_at;
--     unique (entity_type, entity_id, chunk_key)) + index (entity_type, entity_id).
--     The Pinecone vector-sync LEDGER (dedupe/GC/consistency by checksum).
--   Both ENABLE + FORCE RLS; select is_staff() only; NO write policy (the
--     compaction worker writes via service_role).
--   view portal_context (security_barrier=true): a portal client reads ONLY its
--     own client-level summary/facts/updated_at, self-filtered by
--     current_client_id() (mirrors 0010 portal_*); granted to authenticated, anon.
--     No vectors, no watermark, no foreign tenant, no base-table access.

-- ---- 0015_public_audits -----------------------------------------------------
-- The PUBLIC no-login "Free Audit" funnel (P6C-1). ONE free audit per email
-- (lead capture); the report is fetched by an opaque token; a Fiverr upsell link
-- is shown on it. ISOLATED from ALL tenant data: written ONLY by the server
-- (service_role via the privileged path) - NO client_id, NO tenant read path.
--   public_audits(id, email text not null, url text not null, status audit_status
--     'queued', score int, scores jsonb '{}', run_uuid text, artifact_dir text,
--     pdf_path text, json_path text, report_token text not null unique default
--     encode(gen_random_bytes(24),'hex'), source text 'landing', error text,
--     created_at, updated_at) + set_updated_at() trigger. Reuses the audit_status
--     enum (0008); carries no cost/runtime/started_at/client columns.
--   unique index public_audits_email_key on lower(email) - the "one per email"
--     rule; index public_audits_created_at_idx on (created_at desc).
--   ENABLE + FORCE RLS; policy public_audits_select for select using is_staff()
--     ONLY - staff review the leads list; the anonymous tokenized read goes
--     through the privileged path filtered to one report_token, never via RLS.

-- ---- 0016_user_login --------------------------------------------------------
-- AUTH CUTOVER (P6A-7): adds public.users.username (nullable) + a partial unique
-- index users_username_key on lower(username) where username is not null. The
-- username is the human login key for all 3 portals; the uuid PK is unchanged and
-- stays the RLS/auth.uid() identity. Not a tenant boundary; RLS gate unaffected.

-- ---- 0017_content -----------------------------------------------------------
-- Part 7 Module 02 (Content): the content-job ledger (P7A-1). A content job = a
-- content type + topic pushed through an ~90% AUTOMATED pipeline (queued ->
-- drafting -> needs_review -> publishing -> done) with a HUMAN review gate off
-- needs_review (approve -> publishing, reject -> rejected, edit -> drafting).
-- Shapes mirror frontend/lib/content.ts (ContentJob).
--   enums content_page_type(service|blog|local), content_target(WordPress|
--     'PDF/Markdown'), content_framework(AIDA|PAS|BAB|FAB|'4 Ps'|PASTOR|'4 U''s'),
--     content_status(queued|drafting|needs_review|publishing|done|failed|rejected).
--   content_code_seq (start 4200) -> the public CJ-#### badge (never a UUID).
--   content_jobs(id uuid, code text unique CJ-####, client_id fk->clients set null,
--     client_name/color snapshots, page_type, topic, framework, auto bool, target,
--     status 'queued', cost numeric, words int, schema_type text (contract key
--     `schema`), images int, stage text; + server-only rich cols brief, source_pack/
--     keyword_map/outline/entity_coverage/qa_score/json_ld/internal_links jsonb,
--     draft_md, wp_post_id, artifact_dir/pdf_path/md_path, assignee_id fk->users,
--     created_by, context_watermark bigint; created_at/updated_at) + set_updated_at.
--   ENABLE + FORCE RLS: select is_staff(); insert owner/admin/manager; update
--     (assignee_id=auth.uid() OR lead).
--   THE LIFECYCLE GATE - content_jobs_guard_update() BEFORE UPDATE (SECURITY
--     DEFINER, empty search_path) binds ALL THREE actors (service_role bypasses
--     POLICIES but NOT TRIGGERS): (1) WORKER/system (auth.uid() IS NULL) may only
--     do queued->drafting, drafting->needs_review, publishing->done, any->failed,
--     and same-status streaming writes; (2) LEADS own the review decisions +
--     any legal edit; (3) a NON-LEAD assignee may NOT modify a job at all. Plus
--     content_jobs_guard_insert() rejects a client-role assignee. RLS gate: 17
--     tables, all FORCE.

-- ---- 0018_offpage -----------------------------------------------------------
-- Part 7 Module 03 (Off-page): backlink + citation MONITORING and the Web 2.0
-- property ledger. Three read-mostly, client-scoped ledgers; shapes mirror
-- frontend/lib/offpage.ts (Backlink/Citation/Web2Property). The internal client_id
-- never leaks (client_name is a display SNAPSHOT). §3 enum fidelity: web2_platform
-- MUST include 'Medium'. The Web 2.0 PUBLISH pipeline is a later chunk; only the
-- table + read endpoints exist now.
--   enums backlink_status(new|lost|toxic), nap_status(consistent|inconsistent|
--     missing), citation_action(Submit|Update), web2_platform(WordPress.com|Blogger|
--     Tumblr|Medium), web2_verified(verified|pending).
--   backlinks(id uuid, client_id fk->clients on delete cascade, client_name snapshot,
--     ref_domain, anchor, authority int 0-100, spam int 0-100, first_seen date,
--     status 'new'; created_at/updated_at) + set_updated_at; client_id & status idx.
--   citations(id uuid, client_id fk->clients cascade, client_name snapshot, directory,
--     nap_status 'missing', action citation_action 'Submit', note text; created_at/
--     updated_at) + set_updated_at; client_id & nap_status idx.
--   web2_properties(id uuid, client_id fk->clients cascade, client_name snapshot,
--     platform web2_platform, post_url, anchor, verified 'pending', published_at date;
--     created_at/updated_at) + set_updated_at; client_id & platform idx.
--   All three ENABLE + FORCE RLS: select is_staff(); insert/update leads (owner/admin/
--     manager). NO client select policy; NO delete policy. Paid-tier gate lives at the
--     service layer, not RLS; the monitoring ingest path runs on service_role
--     (BYPASSRLS). RLS gate: 20 tables, all FORCE.

-- ---- 0021_milestones --------------------------------------------------------
-- Part 7 Module (Milestones): the client-facing project timeline. Every project
-- moves through a FIXED 5-stage lifecycle, AUTO-ADVANCED from job/audit/publish/
-- payment events - never edited by a client. Shapes mirror frontend/lib/
-- milestones.ts (ClientProject + Stage + AutoAdvance). §3 enum fidelity:
-- project_health is SEPARATE from stage_status (share the label 'completed', are
-- DISTINCT types).
--   enums stage_key(onboarding|baseline|content|authority|reporting - lifecycle
--     ORDER = enum definition order), stage_status(completed|in_progress|upcoming|
--     blocked), project_health(on_track|at_risk|completed).
--   client_projects(id uuid, client_id fk->clients on delete cascade, client_name/
--     init/accent display SNAPSHOTS (accent = contract key `c`), site text,
--     health project_health 'on_track', created_at/updated_at) + set_updated_at;
--     client_id & created_at indexes.
--   project_stages(id uuid, project_id fk->client_projects on delete cascade,
--     stage_key, status stage_status 'upcoming', auto_source text, created_at/
--     updated_at, unique (project_id, stage_key)) + set_updated_at; project_id &
--     updated_at(desc) indexes. Exactly 5 stages per project; `order by stage_key`
--     yields the timeline order.
--   Both ENABLE + FORCE RLS: select is_staff(); insert/update leads (owner/admin/
--     manager). NO client select policy (clients can't read/edit stages); NO delete
--     policy. The auto-advance write path advances one stage row (service_role /
--     BYPASSRLS for the system/worker event path); the feed = recently-touched
--     stages (status <> 'upcoming') newest-first.

-- ---- 0022_upsells -----------------------------------------------------------
-- Part 7 Module (Upsells): the Fiverr upsell catalogue. Cards link OUT to the
-- agency's Fiverr gigs; admin curates them, the active ones render in the client
-- portal. Shapes mirror frontend/lib/upsells.ts (Upsell). AGENCY-GLOBAL (no
-- client_id - one shared catalogue).
--   upsells(id uuid, title text, description text, fiverr_url text '#' (contract
--     key `fiverrUrl`), active bool true, clicks30d int (portal-tracked), price
--     numeric, rating numeric, reviews int, icon text, color text, sort_order int,
--     created_at/updated_at) + set_updated_at; index (sort_order, created_at).
--   ENABLE + FORCE RLS: select is_staff() (any staff read/render); insert/update
--     owner/admin only (manage). Clients never touch the table (is_staff excludes
--     them, no client select policy); the portal renders active cards via the
--     server. No delete policy.

-- ---- 0019_policy ------------------------------------------------------------
-- Part 7 Module 05 (Policy Radar): the always-on SEO/algorithm intelligence brain
-- (Watch -> Detect -> Research -> Flag KB (3-axis) -> Recommend -> human-confirm ->
-- closed loop). Shapes mirror frontend/lib/policy.ts (Source + ChangeEvent + KBEntry
-- + Recommendation). Chunk 7C-1 = FOUNDATION: data + read/transition surface + a
-- BASELINE recommendation set (app/services/policy_baseline.py) so the Command
-- Center is populated PRE-LIVE. DEFERRED (tables shaped to receive them): the
-- change-detection WATCHER (service_role, fills last_hash + change_events + kb) and
-- the 'applied' CLOSED-LOOP overlay (a later chunk; Part-3 HARD RULE: the
-- danyals-audit-system engine is NEVER mutated - the overlay is separate).
--   enums policy_severity(critical|major|minor|info), policy_category(algorithm|
--     policy|technical|content|local|geo), policy_region(global|national),
--     policy_target_module(audit|content|portal), policy_scope(global|client|site),
--     rec_status(new|acknowledged|applied|dismissed), source_status(ok|change).
--   policy_sources(id uuid, name, kind text (contract `kind`), url, icon,
--     last_checked timestamptz (contract `lastChecked` relative; null pre-live),
--     last_hash text (contract `lastHash`, the diff anchor), status source_status
--     'ok', note, created_at/updated_at) + set_updated_at; status & created_at idx.
--   change_events(id uuid, source_id fk->policy_sources set null, source_name
--     snapshot (contract `sourceName`), summary, severity policy_severity 'info',
--     detected_at (contract `detected`), diff_ref text + triggered_job text (WATCHER
--     hooks, null now), created_at/updated_at) + set_updated_at; source_id &
--     detected_at(desc) idx.
--   kb_entries(id uuid, source_id fk->policy_sources set null, title, summary, the 3
--     AXES severity policy_severity/category policy_category/region policy_region +
--     region_flags text[] (specific national markets), region_label (contract
--     `regionLabel`), source_name/source_url citation snapshots, version text 'v1',
--     hash text (dedupe/version anchor), detected_at (contract `detected`),
--     created_at/updated_at) + set_updated_at; source_id/severity/category/
--     detected_at(desc) idx.
--   recommendations(id uuid, kb_entry_id fk->kb_entries set null (null for
--     baseline), kb_ref text (public kbId snapshot; synthetic kb-base-* for
--     baseline), title, why, action, scope policy_scope, target_module
--     policy_target_module (contract `target`), region policy_region, region_label
--     (contract `regionLabel`), status rec_status 'new', affected_clients text
--     (contract `clients`), created_at/updated_at) + set_updated_at; kb_entry_id/
--     status/created_at(desc) idx.
--   All four ENABLE + FORCE RLS: select is_staff(); insert/update owner/admin/
--     manager (the leads). NO client select policy; NO delete. The deferred WATCHER
--     writes on service_role (BYPASSRLS). Baseline recs are surfaced from a constant
--     set (list_recommendations dedups by kb_ref) and MATERIALIZED into the table on
--     a lead's first acknowledge/apply/dismiss. RLS gate: 21 tables, all FORCE.

-- ---- 0020_reports -----------------------------------------------------------
-- Part 7 Module 04 (Reports): the operational-store layer - per-client + master
-- Google Sheets workbooks, written through a quota-safe Redis write-buffer. The
-- audit/content/milestone modules push datasets here; the SheetStore
-- (app/services/sheetstore.py) buffers rows in Redis and, on flush, emits ONE batched
-- Sheets `batchUpdate` per workbook (integrations/sheets.py, KEY-GATED on
-- GOOGLE_SHEETS_SA_JSON, degrades to a fake/None with no key). Shapes mirror
-- frontend/lib/reports.ts (Workbook / SyncEvent / ReportType). The internal client_id
-- NEVER leaks (client_name is a snapshot).
--   enum sync_status(synced|syncing|error).
--   report_workbooks(id uuid, client_id fk->clients cascade (NULL for master),
--     client_name snapshot, sheet_id text (contract `sheet`), tabs jsonb (contract
--     `tabs`, a Dataset[] subset audit|content|milestones), status sync_status
--     'synced', rows_synced_today int (contract `rows`), last_sync timestamptz
--     (contract `lastSync`), is_master bool, created_at/updated_at) + set_updated_at;
--     client_id/last_sync idx + a PARTIAL UNIQUE index (is_master where is_master) so
--     exactly one master-rollup ref row exists. Seeds that master row (idempotent).
--   report_sync_events(id uuid, workbook_id fk->report_workbooks cascade, client_name
--     snapshot (contract `client`), dataset text check in(audit|content|milestones),
--     rows int, synced_at timestamptz (contract `ago`), created_at/updated_at) +
--     set_updated_at; workbook_id & synced_at(desc) idx.
--   Both ENABLE + FORCE RLS: select is_staff(); insert/update owner/admin/manager
--     (the leads; sync is lead-only). NO client select policy; NO delete. RLS gate:
--     23 tables, all FORCE.
