-- 0092_content_deliverables.sql - the artifacts handed to the client, tracked.
--
-- WHY A LEDGER RATHER THAN JUST FILES. The deliverables are the keyword workbook (one
-- tab per planned page), the content PDF, the method report and the brand-kit report.
-- Today the only record a file exists is a path column on a job, which cannot answer
-- "what was delivered for this engagement", cannot distinguish a stale artifact from
-- a current one, and has no integrity check.
--
-- `sha256` matters more than it looks: a deliverable is what an operator sends a
-- client, so "is the file I am about to send the one we generated?" needs an answer.
-- `bytes` is stored because a zero-byte or implausibly small artifact is the exact
-- shape of the title-only-PDF defect, and a size check catches it before a client
-- downloads it.

do $$ begin
  if not exists (select 1 from pg_type where typname = 'content_deliverable_kind') then
    create type public.content_deliverable_kind as enum
      ('keyword_workbook', 'content_pdf', 'method_report', 'brand_kit_report',
       'keyword_csv_bundle');
  end if;
end $$;

create table if not exists public.content_deliverables (
  id            uuid primary key default gen_random_uuid(),
  -- Engagement-level (a workbook) or job-level (a page PDF). Exactly one is set in
  -- practice; both are nullable because the two kinds genuinely differ in scope.
  engagement_id uuid references public.content_engagements (id) on delete cascade,
  job_id        uuid references public.content_jobs (id) on delete cascade,
  kind          public.content_deliverable_kind not null,
  artifact_key  text not null,
  sha256        text not null default '',
  bytes         integer not null default 0,
  generated_at  timestamptz not null default now(),
  generated_by  uuid references public.users (id) on delete set null,
  -- Anything a reader needs that is not the bytes: tab count for a workbook, page
  -- count for a PDF, the provider calls a method report covers.
  meta          jsonb not null default '{}'::jsonb
);

create index if not exists content_deliverables_engagement_idx
  on public.content_deliverables (engagement_id, kind, generated_at desc)
  where engagement_id is not null;
create index if not exists content_deliverables_job_idx
  on public.content_deliverables (job_id, kind, generated_at desc)
  where job_id is not null;

-- A deliverable must belong to SOMETHING. Without this a row can be orphaned from
-- both parents and become unreachable while still occupying storage.
alter table public.content_deliverables
  drop constraint if exists content_deliverables_has_parent;
alter table public.content_deliverables
  add constraint content_deliverables_has_parent
  check (engagement_id is not null or job_id is not null);

-- --- RLS ---------------------------------------------------------------------
alter table public.content_deliverables enable row level security;
alter table public.content_deliverables force row level security;

create policy content_deliverables_select on public.content_deliverables
  for select using (public.is_staff());
create policy content_deliverables_write on public.content_deliverables
  for all using (public.is_staff()) with check (public.is_staff());
