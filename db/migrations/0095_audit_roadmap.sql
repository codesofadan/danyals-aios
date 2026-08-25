-- 0095_audit_roadmap.sql - turn a finding list into a sequenced plan of work.
--
-- WHAT WAS MISSING. An audit ended at "here are 461 problems". The question a
-- client actually asks next - "so what do we do first, and what does the next
-- six months look like?" - had no answer in the system. Spec 13.4 names this as
-- the defect: a long severity-sorted list transfers the prioritisation problem
-- back to the client, which is precisely the work an agency is paid to do.
--
-- THE ANTI-FABRICATION RULE, and it is the reason this table looks the way it does.
-- A roadmap is full of numbers a model would happily invent: dates, durations,
-- "you will see results in 90 days". None of those are derivable from anything
-- we measure. So:
--
--   * `phase` is a RELATIVE WINDOW (p0_30d / p1_90d / p2_180d / p3_365d), never a
--     date. Dates appear only if the operator sets `start_date`, and are then
--     computed in the UI from that input with the arithmetic shown.
--   * `capacity_points_per_month` is an OPERATOR INPUT with a default, not a
--     derivation. It is the single source of every timeline number in the plan.
--     Change it and the phases re-pack; nothing else moves.
--   * item ordering is `impact / effort`, both computed from measured finding
--     fields, and ties break on check_id so two runs never disagree.
--   * exactly ONE field in the whole structure is model-written: a short
--     per-phase summary. Everything else is arithmetic. If the model step is off
--     or fails, the roadmap is COMPLETE without it.
--
-- OVERFLOW IS EXPLICIT. Work that does not fit the horizon lands in `backlog`
-- rather than being dropped, so "we did not plan this" is visible instead of
-- looking like "there was nothing else to do".

do $$ begin
  if not exists (select 1 from pg_type where typname = 'audit_roadmap_phase') then
    create type public.audit_roadmap_phase as enum
      ('p0_30d', 'p1_90d', 'p2_180d', 'p3_365d', 'backlog');
  end if;
end $$;

do $$ begin
  if not exists (select 1 from pg_type where typname = 'audit_roadmap_status') then
    create type public.audit_roadmap_status as enum ('draft', 'active', 'superseded');
  end if;
end $$;

create table if not exists public.audit_roadmaps (
  id                        uuid primary key default gen_random_uuid(),
  audit_id                  uuid not null references public.audits (id) on delete cascade,
  client_id                 uuid references public.clients (id) on delete cascade,
  project_id                uuid references public.client_projects (id) on delete set null,
  status                    public.audit_roadmap_status not null default 'draft',
  superseded_by             uuid references public.audit_roadmaps (id) on delete set null,
  -- The ONLY input any timeline number comes from. Stored per roadmap so a plan
  -- built for a client with one developer is not silently re-read later against
  -- a different assumption.
  capacity_points_per_month integer not null default 40,
  -- Null means the plan is expressed in relative windows only, which is the
  -- default and the honest posture. Setting it is an operator act.
  start_date                date,
  -- Comparability guard, same rule as audit_rollups: a plan built from one
  -- measurement basis must not be compared against one built from another.
  basis_hash                text not null default '',
  scoring_model_version     text not null default '',
  -- The single model-written field: {"phases": {"p0_30d": "..."}}. Empty is a
  -- valid, complete roadmap.
  narrative                 jsonb not null default '{}'::jsonb,
  items_total               integer not null default 0,
  items_planned             integer not null default 0,
  items_backlog             integer not null default 0,
  generated_at              timestamptz not null default now(),
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),
  constraint audit_roadmaps_capacity_ck check (capacity_points_per_month > 0)
);

create index if not exists audit_roadmaps_audit_idx  on public.audit_roadmaps (audit_id);
create index if not exists audit_roadmaps_client_idx on public.audit_roadmaps (client_id, status);

create table if not exists public.audit_roadmap_items (
  id                  uuid primary key default gen_random_uuid(),
  roadmap_id          uuid not null references public.audit_roadmaps (id) on delete cascade,
  client_id           uuid references public.clients (id) on delete cascade,
  -- The problem this item fixes. Nullable so a hand-added item is possible, but
  -- every generated item carries it: that link is what makes the roadmap
  -- verifiable rather than aspirational.
  finding_id          uuid references public.audit_findings (id) on delete set null,
  phase               public.audit_roadmap_phase not null,
  sequence            integer not null,
  title               text not null,
  check_id            text not null default '',
  pillar              text not null default '',
  subcategory         text not null default '',
  dimension           text not null default '',
  owner_role          text not null default '',
  locus_kind          text not null default '',
  locus_value         text not null default '',
  instance_count      integer not null default 0,
  pages_affected      integer not null default 0,
  severity            text not null default '',
  impact_score        numeric,
  effort_points       numeric,
  priority            numeric,
  depends_on          uuid[] not null default '{}',
  -- What "done" means, in a form someone can check. Derived from the check's own
  -- pass condition, never written by a model.
  exit_criterion      text not null default '',
  -- The check to re-run to PROVE it. This is what makes "we fixed 14 issues"
  -- a claim with evidence behind it instead of an absence of evidence.
  verification_check  text not null default '',
  task_id             uuid references public.tasks (id) on delete set null,
  status              text not null default 'planned',
  created_at          timestamptz not null default now(),
  unique (roadmap_id, phase, sequence)
);

create index if not exists audit_roadmap_items_roadmap_idx on public.audit_roadmap_items (roadmap_id, phase, sequence);
create index if not exists audit_roadmap_items_client_idx  on public.audit_roadmap_items (client_id);
create index if not exists audit_roadmap_items_finding_idx on public.audit_roadmap_items (finding_id);

drop trigger if exists audit_roadmaps_set_updated_at on public.audit_roadmaps;
create trigger audit_roadmaps_set_updated_at
  before update on public.audit_roadmaps
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- Staff read, same as the altitude tables. Generation runs in the worker on the
-- service_role connection.
alter table public.audit_roadmaps      enable row level security;
alter table public.audit_roadmaps      force  row level security;
alter table public.audit_roadmap_items enable row level security;
alter table public.audit_roadmap_items force  row level security;

create policy audit_roadmaps_select      on public.audit_roadmaps      for select using (public.is_staff());
create policy audit_roadmap_items_select on public.audit_roadmap_items for select using (public.is_staff());
