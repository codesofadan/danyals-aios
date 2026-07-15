-- 0027_audit_overlay.sql - Part 7 Module 05 (Policy Radar), chunk 7C-3: the
-- CLOSED-LOOP overlay a human-CONFIRMED recommendation writes into.
--
-- THE HARD RULE (Part 3): the danyals-audit-system ENGINE is NEVER mutated. When a
-- lead APPLIES a Policy-Radar recommendation, the concrete change is NOT written
-- back into the engine's check set or the content generator - it is recorded HERE,
-- in a SEPARATE overlay table, and laid ON TOP of the untouched engine output by
-- the PRESENTATION layer (the audit/report renderer + the content-guidance
-- surface). The engine dir stays byte-for-byte identical; deleting every overlay
-- row (or flipping active=false) returns the platform to pure-engine behaviour.
--
-- ONE table serves both overlay kinds, discriminated by target_module (the 0019
-- enum, reused - no new enum):
--   * 'audit'   -> an extra CHECK / weight / advisory layered onto an audit of a
--     given type + region (the audit renderer reads active rows and appends them).
--   * 'content' -> a content-guidance advisory layered onto the brief/draft surface.
--   * 'portal'  -> a standing client advisory.
-- payload jsonb carries any structured extra (extra checks / weight deltas) beyond
-- the flat title/guidance/weight columns, so the overlay shape can grow WITHOUT a
-- migration (the "reuse a jsonb col" option in the chunk brief).
--
-- Traceability: source_kb_ref (the recommendation's public kbId snapshot) and
-- source_rec_id (the MATERIALIZED recommendation's id) tie an overlay back to the
-- KB finding that justified it. They are SNAPSHOTS (text), NOT FKs - matching the
-- module's snapshot convention (kb_ref / source_name in 0019) so a later KB/rec
-- cleanup never cascades away the applied overlay. action is the applied action
-- text; version + active let a later apply SUPERSEDE an earlier overlay without a
-- delete (active=false retires it).
--
-- RLS: any staff may READ (view_reports surface - the renderer/presentation layer
-- reads active rows); only owner/admin/manager MANAGE (insert/update) - the SAME
-- lead set the router's require_role enforces on 'apply', so the app-layer 403 and
-- the DB boundary agree. Clients are excluded by is_staff() (redefined in 0010);
-- there is no client select policy and no delete policy in v1.

-- --- Table -------------------------------------------------------------------
create table if not exists public.audit_overlay (
  id             uuid primary key default gen_random_uuid(),
  target_module  public.policy_target_module not null default 'audit',   -- audit|content|portal (reused 0019 enum)
  audit_type     text not null default '',            -- keyed axis: technical/actionable/local/geo/backlink, '' = all types
  region         public.policy_region not null default 'global',          -- keyed axis (global|national); reused 0019 enum
  title          text not null,                        -- the extra check / advisory title
  guidance       text not null default '',             -- what the check/advisory instructs the renderer to apply
  weight         numeric not null default 0,           -- weight/severity delta for an extra audit check (0 for an advisory)
  payload        jsonb not null default '{}'::jsonb,   -- structured extra (checks/weights); grows WITHOUT a migration
  source_kb_ref  text not null default '',             -- the recommendation's public kbId snapshot (traceability)
  source_rec_id  text not null default '',             -- the materialized recommendation id (snapshot, NOT an FK)
  action         text not null default '',             -- the applied action text (snapshot of the rec's action)
  version        integer not null default 1,           -- bump when a later apply supersedes this overlay
  active         boolean not null default true,        -- applied on top of the engine while true; false = retired
  created_by     uuid references public.users (id) on delete set null,    -- the lead who confirmed the apply
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists audit_overlay_target_idx      on public.audit_overlay (target_module);
create index if not exists audit_overlay_active_idx       on public.audit_overlay (active);
create index if not exists audit_overlay_created_at_idx    on public.audit_overlay (created_at desc);

create trigger audit_overlay_set_updated_at
  before update on public.audit_overlay
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- Any staff may READ (the presentation layer reads active rows to lay them on top
-- of the engine output); only owner/admin/manager MANAGE - the same lead set the
-- router's require_role enforces on 'apply'. No client select policy; no delete.
alter table public.audit_overlay enable row level security;
alter table public.audit_overlay force row level security;

create policy audit_overlay_select on public.audit_overlay
  for select using (public.is_staff());

create policy audit_overlay_insert on public.audit_overlay
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy audit_overlay_update on public.audit_overlay
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
