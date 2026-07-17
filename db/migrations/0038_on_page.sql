-- 0038_on_page.sql - Part 8 Phase 2D (On-Page Optimizer): the per-page analysis
-- ledger + its actionable recommendation queue.
--
-- An on-page analysis = ONE page URL analysed against ONE target keyword. The
-- worker fetches the live page (SSRF-guarded, redirects disabled), parses its
-- title / meta / heading tree / links / image alts / canonical / JSON-LD / body
-- text - OR maps an existing 363-check audit run's findings when source_audit_id
-- is set - and emits one `page_recommendations` row per detected issue. A LEAD may
-- then APPLY a recommendation, which MUTATES THE CLIENT'S LIVE WORDPRESS SITE.
--
--   * onpage_analyses       - one row per analysed page. `code` is the PUBLIC OP-####
--     badge (never a UUID); client_name is a display SNAPSHOT so client_id never has
--     to be surfaced. `wp_post_id` is resolved ONCE at analysis time so every apply
--     is an UPDATE of that post and can never create a duplicate. `score` carries the
--     content-score breakdown (the content_qa rubric, reused - never reinvented).
--   * page_recommendations  - one row per detected issue. `fix_payload` is the
--     PROPOSED value; `current_value` is the SNAPSHOT of the live value taken at
--     analysis time, and it is load-bearing TWICE: it powers the DRIFT-GUARD (if the
--     live value no longer matches the snapshot, a human hand-edited the page after
--     we analysed it and an apply would CLOBBER them, so we refuse) and it is the
--     value a revert writes back. `priority_score` / `quick_win` rank Impact x Effort.
--
-- Shapes are SERVER-AUTHORITATIVE (no frontend/lib type mirrors this module); the
-- module's schemas.py owns the wire shape and its own shape/enum unit tests. The
-- capitalised onpage_impact labels ('High'/'Med'/'Low') ARE the display cell the
-- tool workspace renders verbatim (frontend/lib/tools.ts EXTRAS.on_page).
--
-- THREE ACTOR CLASSES touch these tables - and the state machine CANNOT live only in
-- FastAPI (mirrors 0011/0017's threat model: any authenticated principal could hit
-- the DB directly with a leaked credential):
--
--   * WORKER / SYSTEM (role service_role): the analysis pipeline. It runs on the
--     PRIVILEGED pool, which sets no app.user_id, so `auth.uid()` IS NULL. It drives
--     an analysis queued -> analyzing -> done|held|failed and INSERTS the
--     recommendations. It may NEVER drive a recommendation's lifecycle: applying a
--     fix mutates a live client site, so it must be attributable to a human lead.
--   * LEADS (owner/admin/manager): the humans who own the apply gate - open ->
--     applied | dismissed | held | reverted - plus any other legal edit.
--   * NON-LEAD STAFF (specialist/analyst/viewer): may NOT drive anything here.
--
-- THE LOAD-BEARING REASONING (invariant #3): service_role bypasses POLICIES but NOT
-- TRIGGERS. So the RLS policies below gate the HUMAN pools, while the
-- onpage_guard_update() BEFORE-UPDATE trigger (attached to BOTH tables) is the ONE
-- gate that binds ALL THREE actors - including the worker. That is precisely why
-- "the worker may never apply a fix to a live site" lives in the DATABASE and not
-- (only) in the Celery task.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'onpage_analysis_status') then
    create type public.onpage_analysis_status as enum
      ('queued', 'analyzing', 'done', 'failed', 'held');
  end if;
  if not exists (select 1 from pg_type where typname = 'onpage_rec_status') then
    -- `held` = we could not safely apply (no WP credential, or the SEO-plugin meta
    -- bridge silently dropped the write) - deliberately NOT `failed`: the
    -- recommendation is still valid, only the delivery path is missing.
    create type public.onpage_rec_status as enum
      ('open', 'applied', 'dismissed', 'held', 'reverted');
  end if;
  if not exists (select 1 from pg_type where typname = 'onpage_impact') then
    -- Capitalised = the EXACT display cell lib/tools.ts EXTRAS.on_page renders.
    create type public.onpage_impact as enum ('High', 'Med', 'Low');
  end if;
  if not exists (select 1 from pg_type where typname = 'onpage_fix_kind') then
    -- How a fix is delivered. title/meta/schema are low-effort + auto-applicable
    -- (the Quick Wins); heading/content are higher-effort; `manual` NEVER
    -- auto-applies (a human must do the work).
    create type public.onpage_fix_kind as enum
      ('title', 'meta', 'heading', 'schema', 'content', 'manual');
  end if;
  if not exists (select 1 from pg_type where typname = 'onpage_issue_code') then
    -- The stable issue taxonomy. Detectors emit these; the 363-check audit engine's
    -- on-page findings map ONTO these (rather than being re-detected) when an
    -- analysis carries a source_audit_id.
    create type public.onpage_issue_code as enum (
      'title_missing', 'title_short', 'title_long', 'title_keyword_missing',
      'title_no_brand',
      'meta_missing', 'meta_short', 'meta_long', 'meta_duplicate',
      'h1_missing', 'h1_multiple', 'h1_keyword_missing',
      'heading_hierarchy_skip',
      'thin_content',
      'duplicate_content',
      'schema_missing', 'schema_invalid',
      'internal_links_few', 'internal_link_orphan',
      'image_alt_missing',
      'canonical_missing', 'canonical_conflict',
      'readability_low',
      'keyword_density_low', 'keyword_density_high',
      'content_score_low'
    );
  end if;
end $$;

-- Human-friendly stable code (OP-0001 ...), like the other module code sequences.
create sequence if not exists public.onpage_code_seq;

-- --- Analyses: one row per analysed page --------------------------------------
create table if not exists public.onpage_analyses (
  id              uuid primary key default gen_random_uuid(),
  -- The PUBLIC id rendered as a badge (OP-####); never a UUID.
  code            text not null unique
                  default ('OP-' || to_char(nextval('public.onpage_code_seq'), 'FM0000')),
  -- ON DELETE CASCADE: an analysis is meaningless without its client (unlike the
  -- audit ledger, this is working state, not a billing record).
  client_id       uuid not null references public.clients (id) on delete cascade,
  client_name     text not null default '',   -- display SNAPSHOT (client_id never leaks)
  site_id         uuid references public.sites (id) on delete set null,
  page_url        text not null,
  target_keyword  text not null default '',
  -- Resolved ONCE, at analysis time. Every apply is then an UPDATE of THIS post -
  -- a re-resolve per apply could drift onto a different post and duplicate content.
  wp_post_id      integer,
  status          public.onpage_analysis_status not null default 'queued',
  -- When set, the analysis MAPS this audit run's on-page findings instead of
  -- re-detecting them (the 363-check engine already did the work).
  source_audit_id uuid references public.audits (id) on delete set null,
  score           jsonb not null default '{}',  -- content-score breakdown (content_qa rubric)
  error           text,                          -- failure reason (server-side only)
  created_by      uuid references public.users (id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists onpage_analyses_client_id_idx  on public.onpage_analyses (client_id);
create index if not exists onpage_analyses_status_idx     on public.onpage_analyses (status);
create index if not exists onpage_analyses_created_at_idx on public.onpage_analyses (created_at desc);

create trigger onpage_analyses_set_updated_at
  before update on public.onpage_analyses
  for each row execute function public.set_updated_at();

-- --- Recommendations: one row per detected issue ------------------------------
create table if not exists public.page_recommendations (
  id             uuid primary key default gen_random_uuid(),
  analysis_id    uuid not null references public.onpage_analyses (id) on delete cascade,
  -- Denormalised from the analysis so the board can filter/scope without a join
  -- (and so a recommendation still knows its tenant in a cross-analysis query).
  client_id      uuid not null references public.clients (id) on delete cascade,
  site_id        uuid references public.sites (id) on delete set null,
  page_url       text not null,
  issue          text not null,                       -- the human sentence shown in the UI
  issue_code     public.onpage_issue_code not null,   -- the stable machine taxonomy
  impact         public.onpage_impact not null default 'Med',
  status         public.onpage_rec_status not null default 'open',
  fix_kind       public.onpage_fix_kind not null default 'manual',
  fix_payload    jsonb not null default '{}',         -- the PROPOSED value
  -- The live value SNAPSHOTTED at analysis time. Load-bearing twice: the drift-guard
  -- compares the live value against it before any write (a mismatch means a human
  -- hand-edited the page after we analysed it - applying would clobber them), and a
  -- revert writes it back. NULL = nothing was there to snapshot (e.g. a missing tag).
  current_value  text,
  priority_score numeric(6,2) not null default 0,     -- Impact x Effort ranking
  quick_win      boolean not null default false,      -- high impact + low effort + auto-applicable
  detail         jsonb not null default '{}',         -- evidence (thresholds, measured values)
  applied_at     timestamptz,
  applied_by     uuid references public.users (id) on delete set null,
  dismissed_at   timestamptz,
  dismissed_by   uuid references public.users (id) on delete set null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists page_recommendations_analysis_id_idx
  on public.page_recommendations (analysis_id);
create index if not exists page_recommendations_client_id_idx
  on public.page_recommendations (client_id);
create index if not exists page_recommendations_status_idx
  on public.page_recommendations (status);
-- The board's default ordering (best quick wins first).
create index if not exists page_recommendations_priority_idx
  on public.page_recommendations (priority_score desc);

create trigger page_recommendations_set_updated_at
  before update on public.page_recommendations
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- Clients are excluded by is_staff() (they get NO base-table select policy), so a
-- portal client can NOT read on-page analyses or recommendations. Any staff may
-- READ. The analysis worker runs on service_role (BYPASSRLS) and so is governed by
-- the TRIGGER below, not by these policies. No delete policy in v1.
alter table public.onpage_analyses enable row level security;
alter table public.onpage_analyses force row level security;
alter table public.page_recommendations enable row level security;
alter table public.page_recommendations force row level security;

create policy onpage_analyses_select on public.onpage_analyses
  for select using (public.is_staff());

-- INSERT mirrors the ROUTE's gate (`run_audits`) - i.e. the audits_modify holder set
-- in 0008 - NOT the lead set: `POST /on-page/analyze` is a run_audits action (running
-- an analysis is read-only against the live site; it changes nothing), and the app
-- gate and the database MUST agree or a specialist/analyst who passes the app gate
-- would be rejected by Postgres with an opaque RLS error instead of a clean 403.
create policy onpage_analyses_insert on public.onpage_analyses
  for insert
  with check (public.current_app_role() in ('owner', 'admin', 'manager', 'specialist', 'analyst'));

-- UPDATE is LEAD-only: the only human update on an analysis is the re-analyze
-- re-arm, and the guard's actor model gives no non-lead any legal transition.
create policy onpage_analyses_update on public.onpage_analyses
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy page_recommendations_select on public.page_recommendations
  for select using (public.is_staff());

-- Recommendations are the LIVE-SITE path: only leads may write them at all. (The
-- analysis worker inserts them on service_role, which bypasses this policy but is
-- still bound by the trigger.)
create policy page_recommendations_insert on public.page_recommendations
  for insert
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy page_recommendations_update on public.page_recommendations
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

-- --- DB-level lifecycle guard (the ONE gate binding all three actors) ---------
-- SECURITY DEFINER + empty search_path (schema-qualified everywhere) so it never
-- recurses and cannot be search_path-hijacked. Attached to BOTH tables; TG_TABLE_NAME
-- selects the state machine. Statuses are compared as ::text so ONE function can
-- serve two tables whose `status` columns are different enum types.
--
-- service_role bypasses POLICIES but NOT TRIGGERS (invariant #3) - which is exactly
-- why the "the worker may never apply a fix to a live site" rule lives HERE.
create or replace function public.onpage_guard_update()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  -- (1) WORKER / SYSTEM path (role service_role => auth.uid() IS NULL). The analysis
  -- pipeline runs on the privileged pool, which sets no app.user_id, so it is
  -- UNAMBIGUOUSLY this branch.
  if auth.uid() is null then
    if tg_table_name = 'onpage_analyses' then
      -- Allow ONLY the system transitions - plus same-status writes (the worker
      -- streams score/wp_post_id/error into an analysis WITHOUT a status change) and
      -- any status -> failed (a crash can fail an analysis from anywhere).
      if old.status::text = new.status::text
         or (old.status::text = 'queued'   and new.status::text = 'analyzing')
         or (old.status::text = 'analyzing' and new.status::text in ('done', 'held', 'failed'))
         or (new.status::text = 'failed')
      then
        return new;
      end if;
      raise exception 'illegal system on-page analysis transition % -> %',
        old.status, new.status;
    end if;

    -- page_recommendations: the worker may re-snapshot a recommendation during a
    -- re-analysis (a SAME-STATUS write), but may NEVER drive its lifecycle. Applying
    -- a fix MUTATES A LIVE CLIENT SITE, so it must be attributable to a human lead -
    -- an unattended worker (or a leaked service credential) must not be able to
    -- rewrite a client's titles. This is the whole reason this trigger exists.
    if old.status::text = new.status::text then
      return new;
    end if;
    raise exception
      'the on-page worker may not drive a recommendation lifecycle (% -> %); a live-site apply must be lead-attributed',
      old.status, new.status;
  end if;

  -- (2) LEADS (owner/admin/manager) own the apply gate: open -> applied | dismissed |
  -- held | reverted, plus any other legal edit (including the re-analyze re-arm).
  if public.current_app_role() in ('owner', 'admin', 'manager') then
    return new;
  end if;

  -- (3) NON-LEAD STAFF (specialist/analyst/viewer). The on-page lifecycle is owned
  -- ENTIRELY by the automated analyser (path 1) and the leads (path 2): the worker
  -- analyses, the leads apply/dismiss/revert. No legal non-lead transition remains,
  -- so we forbid ALL non-lead writes outright (mirrors the content_jobs guard).
  raise exception
    'a non-lead may not modify on-page analyses or recommendations (the analyser and leads own the lifecycle)';
end;
$$;

drop trigger if exists onpage_analyses_guard_update_trg on public.onpage_analyses;
create trigger onpage_analyses_guard_update_trg
  before update on public.onpage_analyses
  for each row execute function public.onpage_guard_update();

drop trigger if exists page_recommendations_guard_update_trg on public.page_recommendations;
create trigger page_recommendations_guard_update_trg
  before update on public.page_recommendations
  for each row execute function public.onpage_guard_update();
