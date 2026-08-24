-- 0087_content_briefs.sql - the brief, and the Experience store the hard halt runs on.
--
-- TWO THINGS, in one migration because one is meaningless without the other.
--
-- 1. `content_briefs` gives a page a durable brief. Today the research output lives in
--    `content_jobs.source_pack` jsonb and is overwritten on every redraft, so there is
--    no record of what the page was ASKED to do versus what it did. `doctrine_refs`
--    records which doctrine chunks governed it, which is what makes the method trail
--    real rather than asserted.
--
-- 2. `sme_dossiers` / `sme_slots` are THE EXPERIENCE STORE, and this is the load-
--    bearing half.
--
-- WHY IT NEEDS A TABLE AT ALL. Experience is the one E-E-A-T signal no competitor and
-- no model can scrape, because it exists only in the operator's head and invoice
-- history. A model asked for it will produce fluent, plausible, invented Experience -
-- "our team has seen", "over 1,200 jobs" - and that is indistinguishable from the real
-- thing at the level of prose. The only defence is provenance: every Experience claim
-- must trace to a row here, with a SOURCE saying who supplied it and how directly.
--
-- The owner's standing decision is a HARD HALT: no page drafts until the dossier is
-- complete. That is enforceable only if "complete" is a fact about rows rather than a
-- judgement, which is what `status` and the per-slot `answer`/`artifact_url` provide.
--
-- INVARIANT, stated here because it is the point of the table: NOTHING in the system
-- may write an Experience claim that does not trace to a slot in this table.

do $$ begin
  if not exists (select 1 from pg_type where typname = 'sme_dossier_status') then
    create type public.sme_dossier_status as enum ('empty', 'partial', 'complete');
  end if;
  if not exists (select 1 from pg_type where typname = 'sme_slot_source') then
    -- Ordered by DIRECTNESS, and the order matters: `client` is the operator's own
    -- word; `client_site` is second-hand (harvested from their existing pages) and
    -- carries lower confidence precisely so it is never mistaken for a fresh answer.
    create type public.sme_slot_source as enum
      ('client', 'operator', 'transcript', 'client_site');
  end if;
end $$;

create table if not exists public.content_briefs (
  id              uuid primary key default gen_random_uuid(),
  engagement_id   uuid references public.content_engagements (id) on delete cascade,
  node_id         uuid references public.topical_map_nodes (id) on delete set null,
  page_type       text not null default 'service',
  primary_keyword text not null,
  -- The SERP as it looked when the brief was built. Kept because a brief judged
  -- against today's SERP tells you nothing about a page written six months ago.
  serp_snapshot   jsonb not null default '{}'::jsonb,
  competitor_teardown jsonb not null default '[]'::jsonb,
  entities        jsonb not null default '[]'::jsonb,
  -- The mandatory information-gain angle, and whether it is GROUNDED. An ungrounded
  -- angle is the failure `content_qa`'s hard gate exists to catch.
  differentiation_angle text not null default '',
  angle_grounded  boolean not null default false,
  outline         jsonb not null default '{}'::jsonb,
  -- Which doctrine chunks governed this brief (ids from `doctrine_chunks`, 0091).
  doctrine_refs   text[] not null default '{}',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists content_briefs_engagement_idx
  on public.content_briefs (engagement_id, created_at desc);
create index if not exists content_briefs_node_idx
  on public.content_briefs (node_id) where node_id is not null;

create trigger content_briefs_set_updated_at
  before update on public.content_briefs
  for each row execute function public.set_updated_at();

create table if not exists public.sme_dossiers (
  id            uuid primary key default gen_random_uuid(),
  engagement_id uuid not null references public.content_engagements (id) on delete cascade,
  -- Dossiers are per CLUSTER, not per page: the questions that unlock "emergency AC
  -- repair" unlock every page in that cluster, so asking once is the difference
  -- between three questions and thirty.
  cluster_key   text not null default '',
  status        public.sme_dossier_status not null default 'empty',
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create unique index if not exists sme_dossiers_engagement_cluster_idx
  on public.sme_dossiers (engagement_id, cluster_key);

create trigger sme_dossiers_set_updated_at
  before update on public.sme_dossiers
  for each row execute function public.set_updated_at();

create table if not exists public.sme_slots (
  id            uuid primary key default gen_random_uuid(),
  dossier_id    uuid not null references public.sme_dossiers (id) on delete cascade,
  -- The proof category this slot supplies, matching what `content_lint.experience`
  -- reports as missing (founding_date, license_permit, review_source, count_source,
  -- credential_source, photo, named_team). That correspondence is what lets the
  -- questionnaire ask for exactly the artifact a claim lacks.
  slot_key      text not null,
  question      text not null default '',
  answer        text not null default '',
  -- The DATED artifact. An Experience claim backed by an undated assertion is still
  -- an assertion; the doctrine requires the artifact and its date.
  artifact_url  text not null default '',
  artifact_date date,
  source        public.sme_slot_source not null default 'operator',
  confidence    numeric(4,3) not null default 1.0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create unique index if not exists sme_slots_dossier_key_idx
  on public.sme_slots (dossier_id, slot_key);
-- The hard halt's query: which slots in this dossier are still unanswered.
create index if not exists sme_slots_unanswered_idx
  on public.sme_slots (dossier_id)
  where answer = '' and artifact_url = '';

create trigger sme_slots_set_updated_at
  before update on public.sme_slots
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- Briefs and dossiers are ordinary production work, so any staff may read and write.
-- The commercial layer (the engagement itself) stays lead-only in 0084.
alter table public.content_briefs enable row level security;
alter table public.content_briefs force row level security;
alter table public.sme_dossiers enable row level security;
alter table public.sme_dossiers force row level security;
alter table public.sme_slots enable row level security;
alter table public.sme_slots force row level security;

create policy content_briefs_select on public.content_briefs
  for select using (public.is_staff());
create policy content_briefs_write on public.content_briefs
  for all using (public.is_staff()) with check (public.is_staff());

create policy sme_dossiers_select on public.sme_dossiers
  for select using (public.is_staff());
create policy sme_dossiers_write on public.sme_dossiers
  for all using (public.is_staff()) with check (public.is_staff());

create policy sme_slots_select on public.sme_slots
  for select using (public.is_staff());
create policy sme_slots_write on public.sme_slots
  for all using (public.is_staff()) with check (public.is_staff());
