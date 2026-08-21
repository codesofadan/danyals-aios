-- 0071_visual_validations.sql - the visual-QA verdict ledger (spec section 26/27):
-- ONE row per QA pass over a rendered build, carrying STRUCTURED diagnostics (never
-- just a similarity percentage) produced by ``app.services.visual_diff``.
--
-- A job's `generating` design is compared against a fresh capture of the actually
-- RENDERED page (the publish phase's own output) - see
-- ``app.modules.site_builder.tasks.run_visual_qa``. Multiple rows per job are
-- expected: a build that fails QA gets corrected and re-validated (spec's own
-- Render -> Visual QA -> Correct -> Render-again loop), so this is an append-only
-- history, not a single mutable verdict column on the job.
--
-- RLS mirrors 0069/0070: any STAFF may READ (is_staff()); the WORKER writes via
-- privileged_connection (service_role bypasses RLS), identical to every other
-- module's worker path - there is no human-authored write to this table.

do $$ begin
  if not exists (select 1 from pg_type where typname = 'visual_qa_status') then
    create type public.visual_qa_status as enum ('pass', 'warn', 'fail');
  end if;
end $$;

create table if not exists public.visual_validations (
  id            uuid primary key default gen_random_uuid(),
  job_id        uuid not null references public.site_generation_jobs (id) on delete cascade,
  rendered_url  text not null default '',
  status        public.visual_qa_status not null default 'warn',
  -- [{"kind","section","detail","magnitude"}, ...] - app.services.visual_diff.Diagnostic
  diagnostics   jsonb not null default '[]',
  created_at    timestamptz not null default now()
);

create index if not exists visual_validations_job_id_idx on public.visual_validations (job_id);

alter table public.visual_validations enable row level security;
alter table public.visual_validations force row level security;

create policy visual_validations_select on public.visual_validations
  for select using (public.is_staff());

create policy visual_validations_write on public.visual_validations
  for all
  using (public.is_staff())
  with check (public.is_staff());

comment on table public.visual_validations is
  'Append-only visual-QA history per site_generation_jobs row: a structured, '
  'multi-dimension diagnostic verdict (typography/layout/spacing/color/size/image/'
  'responsive), never a single similarity percentage.';
