-- 0040_client_onboarding.sql - Part 8 Phase 2F (Client Onboarding): the staff-only
-- new-client ACTIVATION checklist.
--
-- Winning the client is not delivering for them: an engagement only starts once the
-- access, the assets and the targets are actually in hand. This module turns that
-- into a tracked, auditable run instead of a Slack thread:
--
--   * onboarding_runs  - ONE activation per client engagement. Seeded from the
--     versioned 11-step local-SEO template in the module's constants.py (the
--     template lives in CODE, in git - there is deliberately no DB template
--     builder to drift from it). client_name is a display SNAPSHOT so client_id
--     never has to be surfaced; owner_name likewise snapshots the accountable
--     staffer. status drives the lifecycle (in_progress -> completed), and the
--     PARTIAL unique index below allows exactly one LIVE run per client while
--     leaving history (completed/archived runs) uncapped.
--   * onboarding_steps - the ordered checklist rows of a run. client_id is
--     denormalized (+ client_name snapshot) so the cross-client STEP BOARD reads
--     one table without a join. owner_* are display snapshots (mirrors
--     content_jobs / client_projects). sort_order is the template's fixed order.
--
-- TWO COLUMNS CARRY THE SECURITY WEIGHT OF THIS MODULE:
--
--   * vault_secret_id - a `collect_*` step's credential is sealed into the KEY
--     VAULT (AES-256-GCM under VAULT_MASTER_KEY, app-layer; see 0004_vault.sql +
--     app/services/vault.py) with kind='client_access' (0041_vault_kind.sql), and
--     ONLY the returned reference is stored here. The PLAINTEXT SECRET NEVER LANDS
--     IN THIS TABLE - there is no secret column, by construction. This column is
--     deliberately NOT a foreign key: the vault is a separate, owner/admin-only
--     security domain (vault_keys RLS excludes even a manager, who may well own an
--     onboarding step), so a step holds an OPAQUE reference into it and nothing more.
--     Reveal stays exactly where it was: owner-only, through the vault router.
--   * verified - the researched agency rule is "test every login". A COLLECTED
--     credential is NOT a VERIFIED one, so this flag NEVER flips automatically on
--     collection; it flips only on an explicit access-test confirmation. Defaulting
--     it false means the honest answer ("nobody has proven this login works") is the
--     one you get for free.
--
-- Shapes are SERVER-AUTHORITATIVE (no frontend/lib type mirrors this module); the
-- module's schemas.py owns the wire shape and its own shape/enum unit tests.
--
-- RLS mirrors 0035_keyword_research exactly: any STAFF may READ (is_staff()); only
-- LEADS (owner/admin/manager) may INSERT/UPDATE - which matches the app's
-- manage_clients gate. Clients get NO select policy at all, so onboarding is a
-- staff-only surface: a portal client can never read the checklist tracking its own
-- access collection (it names which credentials the agency holds). No delete policy
-- in v1 - a finished run is history (status='archived'), not a DELETE.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
-- NOTE (§3 enum fidelity): onboarding_step_status is SEPARATE from stage_status
-- (0021_milestones) and from onboarding_run_status - they share labels
-- ('completed', 'in_progress', 'blocked') but are DISTINCT types and must never be
-- merged. A step can be 'skipped' (not applicable to this client); a run cannot.
do $$ begin
  if not exists (select 1 from pg_type where typname = 'onboarding_run_status') then
    create type public.onboarding_run_status as enum
      ('in_progress', 'on_hold', 'completed', 'archived');
  end if;
  if not exists (select 1 from pg_type where typname = 'onboarding_step_status') then
    create type public.onboarding_step_status as enum
      ('pending', 'in_progress', 'blocked', 'completed', 'skipped');
  end if;
end $$;

-- --- Parent: one activation run per client engagement -------------------------
create table if not exists public.onboarding_runs (
  id             uuid primary key default gen_random_uuid(),
  -- Tenant linkage. ON DELETE CASCADE retires the activation with its client;
  -- client_name is a display SNAPSHOT so client_id never has to be surfaced.
  client_id      uuid not null references public.clients (id) on delete cascade,
  client_name    text not null default '',
  -- Which versioned code template seeded this run (see constants.py). Stored so a
  -- run stays readable after the template evolves in a later release.
  template_key   text not null default 'local_seo_default',
  status         public.onboarding_run_status not null default 'in_progress',
  -- The accountable staffer. ON DELETE SET NULL keeps the run (and its snapshot)
  -- when the owner leaves the agency - the work does not vanish with the person.
  owner_user_id  uuid references public.users (id) on delete set null,
  owner_name     text not null default '',          -- display snapshot
  target_date    date,
  completed_at   timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists onboarding_runs_client_id_idx on public.onboarding_runs (client_id);
create index if not exists onboarding_runs_status_idx    on public.onboarding_runs (status);

-- ONE ACTIVE RUN PER CLIENT. A PARTIAL unique index (not a plain unique) is the
-- point: 'in_progress'/'on_hold' are the LIVE states and may exist at most once per
-- client, while completed/archived runs accumulate freely as history. A plain
-- unique(client_id) would make re-onboarding a client (a re-engagement) impossible;
-- no constraint at all would let the auto-seed hook on client-create silently mint a
-- second live checklist next to the real one.
create unique index if not exists onboarding_runs_one_active
  on public.onboarding_runs (client_id)
  where status in ('in_progress', 'on_hold');

create trigger onboarding_runs_set_updated_at
  before update on public.onboarding_runs
  for each row execute function public.set_updated_at();

-- --- Child: the ordered checklist steps of a run ------------------------------
create table if not exists public.onboarding_steps (
  id             uuid primary key default gen_random_uuid(),
  run_id         uuid not null references public.onboarding_runs (id) on delete cascade,
  -- DENORMALIZED tenant linkage (+ snapshot): the cross-client step BOARD reads
  -- this table alone, with no join back to the run. Cascades with the client for
  -- the same reason the run does.
  client_id      uuid not null references public.clients (id) on delete cascade,
  client_name    text not null default '',
  step_key       text not null,                     -- the template's stable key
  label          text not null default '',          -- the display label (snapshot)
  status         public.onboarding_step_status not null default 'pending',
  owner_user_id  uuid references public.users (id) on delete set null,
  owner_name     text not null default '',          -- display snapshots (mirror
  owner_init     text not null default '',          -- content_jobs / client_projects)
  owner_color    text not null default '',
  due_date       date,
  notes          text not null default '',
  -- The access-test flag. NEVER set automatically on collection - see the header.
  verified       boolean not null default false,
  -- An OPAQUE reference to the sealed credential in public.vault_keys. Never a FK
  -- (the vault is an owner/admin-only domain); NEVER the secret itself.
  vault_secret_id uuid,
  sort_order     integer not null default 0,
  completed_at   timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  -- One row per step_key per run: the seed is idempotent by construction, so a
  -- double-seed (a retried client-create hook) can never duplicate the checklist.
  unique (run_id, step_key)
);

create index if not exists onboarding_steps_run_id_idx    on public.onboarding_steps (run_id);
create index if not exists onboarding_steps_client_id_idx on public.onboarding_steps (client_id);
create index if not exists onboarding_steps_status_idx    on public.onboarding_steps (status);

create trigger onboarding_steps_set_updated_at
  before update on public.onboarding_steps
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- Clients are excluded by is_staff() (they get NO base-table select policy), so a
-- portal client can NOT read its own onboarding checklist - it enumerates which of
-- the client's credentials the agency holds, which is staff-only intelligence. Any
-- staff may READ; only leads (owner/admin/manager) may INSERT/UPDATE, mirroring the
-- app's manage_clients gate exactly (the app gate and the database must agree, or a
-- caller who passes the app gate is rejected by Postgres with an opaque RLS error
-- instead of a clean 403). No delete policy in v1.
alter table public.onboarding_runs enable row level security;
alter table public.onboarding_runs force row level security;
alter table public.onboarding_steps enable row level security;
alter table public.onboarding_steps force row level security;

create policy onboarding_runs_select on public.onboarding_runs
  for select using (public.is_staff());
create policy onboarding_runs_insert on public.onboarding_runs
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy onboarding_runs_update on public.onboarding_runs
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy onboarding_steps_select on public.onboarding_steps
  for select using (public.is_staff());
create policy onboarding_steps_insert on public.onboarding_steps
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy onboarding_steps_update on public.onboarding_steps
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
