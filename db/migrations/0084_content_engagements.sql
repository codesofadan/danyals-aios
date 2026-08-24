-- 0084_content_engagements.sql - the planning layer above content_jobs.
--
-- WHY THIS TABLE EXISTS. `content_jobs` is a ledger of PAGES. Everything an operator
-- actually decides happens one level up and currently has nowhere to live: which
-- client, what shape of work, how many pages, what budget, and - the one that blocks
-- drafting - whether the client's first-party facts have been collected yet.
--
-- Without it, "build me the whole site" and "write me one page" are the same request
-- repeated N times, each re-deciding scope from scratch. Every downstream table in
-- 0085-0092 hangs off an engagement, because the keyword plan, the topical map and
-- the SME dossier are all properties of an ENGAGEMENT, not of a page: pulling
-- keywords once and reusing them across 50 pages is the whole cost model
-- (~10 DataForSEO calls per engagement rather than per page).
--
-- ADDITIVE ONLY. Nothing here alters or drops an existing object. `content_jobs`
-- gains its nullable link in 0090, so every existing row and every existing code path
-- keeps working with no engagement at all.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'engagement_shape') then
    -- The five shapes an operator can actually be asked for. `continue_existing` is
    -- the audit-first path (a client already three months into SEO elsewhere);
    -- `retainer` is recurring work, driven by an operator action rather than cron,
    -- because beat is parked platform-wide.
    create type public.engagement_shape as enum
      ('single_page', 'page_set', 'full_site', 'continue_existing', 'retainer');
  end if;
  if not exists (select 1 from pg_type where typname = 'engagement_status') then
    -- `awaiting_sme` is load-bearing, not decorative: it is where an engagement sits
    -- when the client's first-party facts have not been collected. The owner's
    -- standing decision is a HARD HALT, so this status is what stops drafting rather
    -- than a convention someone has to remember.
    create type public.engagement_status as enum
      ('draft', 'planning', 'awaiting_sme', 'ready', 'producing', 'paused',
       'completed', 'cancelled');
  end if;
end $$;

create table if not exists public.content_engagements (
  id            uuid primary key default gen_random_uuid(),
  -- Same tenant-linkage convention as content_jobs: ON DELETE SET NULL keeps the
  -- planning record intact if a client is removed, and client_name is snapshotted so
  -- client_id never has to reach the API.
  client_id     uuid references public.clients (id) on delete set null,
  client_name   text not null default '',
  shape         public.engagement_shape not null,
  name          text not null default '',
  status        public.engagement_status not null default 'draft',
  -- Free-form scope the shape cannot express: named services, target cities, the
  -- URL list for a continue_existing audit. jsonb rather than columns because the
  -- shape of this genuinely differs per engagement type.
  scope         jsonb not null default '{}'::jsonb,
  -- Ceiling for the WHOLE engagement, checked before each page is enqueued. The
  -- per-job ceiling is a different guard; this one stops a 50-page run rather than
  -- one runaway page. numeric(12,4) not (10,2): 0083 widened the money ledger
  -- because sub-cent provider charges were rounding to zero on the way in, and a
  -- budget that cannot represent what the ledger records is the same defect again.
  budget_cap    numeric(12,4),
  page_target   integer not null default 0,
  -- The audit an engagement continues FROM. Nullable and set null on delete: the
  -- audit is an input, and losing it must not orphan months of planning.
  source_audit_id uuid references public.audits (id) on delete set null,
  owner_id      uuid references public.users (id) on delete set null,
  created_by    uuid references public.users (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists content_engagements_client_idx
  on public.content_engagements (client_id, created_at desc);
create index if not exists content_engagements_status_idx
  on public.content_engagements (status)
  where status in ('planning', 'awaiting_sme', 'ready', 'producing');

create trigger content_engagements_set_updated_at
  before update on public.content_engagements
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- Mirrors content_jobs: clients are excluded by is_staff(); any staff may READ;
-- only leads may create or change an engagement, because shape and budget are
-- commercial decisions rather than production ones.
--
-- service_role (the worker pool) bypasses POLICIES but not TRIGGERS. There is no
-- lifecycle guard trigger here BY DESIGN: unlike content_jobs, no worker advances an
-- engagement through a state machine - the operator drives it - so there is no
-- machine actor whose writes need constraining, and a trigger that guards nothing
-- would be a false assurance.
alter table public.content_engagements enable row level security;
alter table public.content_engagements force row level security;

create policy content_engagements_select on public.content_engagements
  for select using (public.is_staff());

create policy content_engagements_insert on public.content_engagements
  for insert
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy content_engagements_update on public.content_engagements
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy content_engagements_delete on public.content_engagements
  for delete using (public.current_app_role() in ('owner', 'admin'));
