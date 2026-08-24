-- 0085_content_keyword_plans.sql - real keyword demand, and a column that makes
-- fabrication impossible to hide.
--
-- THE DEFECT THIS EXISTS TO END. `integrations/content_research.py` derives keyword
-- "volume" and "difficulty" from the SERP's total-results count:
--
--     difficulty = min(100, log10(total_results) * 8)
--     volume     = min(500000, 10 ** (log10(total_results) / 2))
--
-- Those are invented numbers presented as metrics, and each one costs a paid Serper
-- credit to invent. They render in the UI identically to a real Google Ads figure,
-- so nothing downstream - not the operator, not the QA gate, not the client report -
-- can tell a measurement from a guess.
--
-- `estimated boolean` is the fix. Every row records whether its numbers came from a
-- provider or were derived, and `source` records which provider. A derived number is
-- still allowed (a keyword outside the plan still needs a rough sort order) but it can
-- never again masquerade as vendor data.
--
-- The plan is per ENGAGEMENT, not per page: ~10 DataForSEO calls amortise across
-- every page in the engagement ($0.198 total, ~$0.004/page across 50 pages), which is
-- cheaper per page than the fabricated numbers were.

do $$ begin
  if not exists (select 1 from pg_type where typname = 'keyword_metric_source') then
    -- `serp_derived` is the honest name for what the old code did silently. Keeping
    -- it as a first-class value means a degraded run is visible rather than absent.
    create type public.keyword_metric_source as enum
      ('dataforseo', 'serp_derived', 'operator', 'audit');
  end if;
  if not exists (select 1 from pg_type where typname = 'keyword_plan_status') then
    create type public.keyword_plan_status as enum
      ('pending', 'running', 'ready', 'degraded', 'failed');
  end if;
end $$;

create table if not exists public.keyword_plans (
  id             uuid primary key default gen_random_uuid(),
  engagement_id  uuid not null references public.content_engagements (id) on delete cascade,
  seed_terms     text[] not null default '{}',
  geo            text not null default '',
  provider       text not null default '',
  provider_run_at timestamptz,
  -- What the plan actually cost to build, in the same precision as the money ledger
  -- (0083). This is what the deliverable's "Method & Sources" tab reports.
  cost           numeric(12,4) not null default 0,
  status         public.keyword_plan_status not null default 'pending',
  notes          jsonb not null default '[]'::jsonb,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists keyword_plans_engagement_idx
  on public.keyword_plans (engagement_id, created_at desc);

create trigger keyword_plans_set_updated_at
  before update on public.keyword_plans
  for each row execute function public.set_updated_at();

create table if not exists public.keyword_plan_terms (
  id           uuid primary key default gen_random_uuid(),
  plan_id      uuid not null references public.keyword_plans (id) on delete cascade,
  keyword      text not null,
  volume       integer,
  difficulty   numeric(5,2),
  cpc          numeric(10,4),
  competition  numeric(5,4),
  intent       text not null default '',
  -- WHERE the numbers came from, and WHETHER they were measured.
  source       public.keyword_metric_source not null,
  estimated    boolean not null default false,
  -- Derived, not provider-supplied: how well the term fits this client, and the
  -- opportunity ranking. Deterministic and free (keyword_research/service.py), so
  -- they are always `estimated` in spirit - they are OURS, not a vendor's.
  relevance    numeric(5,4),
  opportunity  numeric(7,4),
  cluster_key  text not null default '',
  created_at   timestamptz not null default now()
);

-- One row per keyword per plan. Case-insensitive because "AC Repair" and "ac repair"
-- are the same demand, and counting them twice would inflate every cluster.
create unique index if not exists keyword_plan_terms_unique_idx
  on public.keyword_plan_terms (plan_id, lower(keyword));
create index if not exists keyword_plan_terms_cluster_idx
  on public.keyword_plan_terms (plan_id, cluster_key);
-- Partial index on the honest-metrics path: the workbook and the map both filter to
-- provider-measured terms when ranking, and estimated rows are the minority.
create index if not exists keyword_plan_terms_measured_idx
  on public.keyword_plan_terms (plan_id, volume desc)
  where estimated = false;

-- --- RLS ---------------------------------------------------------------------
alter table public.keyword_plans enable row level security;
alter table public.keyword_plans force row level security;
alter table public.keyword_plan_terms enable row level security;
alter table public.keyword_plan_terms force row level security;

create policy keyword_plans_select on public.keyword_plans
  for select using (public.is_staff());
create policy keyword_plans_write on public.keyword_plans
  for all
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy keyword_plan_terms_select on public.keyword_plan_terms
  for select using (public.is_staff());
create policy keyword_plan_terms_write on public.keyword_plan_terms
  for all
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
