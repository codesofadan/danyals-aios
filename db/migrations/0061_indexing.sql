-- 0061_indexing.sql - Indexing module: the durable ledger of every URL-submission the
-- platform makes to a search engine (IndexNow / Google Indexing API / sitemap ping).
--
-- WHEN a content page is published (or an operator submits on demand), the indexing
-- service fans the URL out to the enabled engines and appends ONE row per (url, engine)
-- attempt here, recording how it went (status + a short detail line). This is a pure
-- append-only audit trail: "did we tell Google/IndexNow about this page, and what did
-- they say?".
--
-- WRITTEN ONLY BY THE SERVER: the publish worker + the on-demand endpoint both append
-- rows on the service_role (BYPASSRLS) connection - exactly like scheduled_job_runs /
-- public_audits / the audit worker's status writes - so there is NO authenticated
-- INSERT/UPDATE policy. Any provisioned staff may READ (mirrors 0055_scheduled_job_runs);
-- a portal client is excluded by is_staff() (no select policy for them), so the
-- operator's indexing view never leaks to a client. No delete in v1.

do $$ begin
  if not exists (select 1 from pg_type where typname = 'index_submission_status') then
    create type public.index_submission_status as enum (
      'ok', 'error', 'skipped'
    );
  end if;
end $$;

create table if not exists public.index_submissions (
  id          uuid primary key default gen_random_uuid(),
  -- Nullable: an on-demand ad-hoc submission may not be tied to a client, and a
  -- content publish snapshots the client at publish time. SET NULL on delete keeps the
  -- audit trail even after a client is removed.
  client_id   uuid references public.clients (id) on delete set null,
  -- The exact URL submitted to the engine.
  url         text not null,
  -- Which mechanism the row records: 'indexnow' | 'google' | 'sitemap'.
  engine      text not null default '',
  status      public.index_submission_status not null default 'ok',
  -- A short human line ("202 Accepted", "not configured", "sitemap 404").
  detail      text not null default '',
  created_at  timestamptz not null default now()
);

-- Newest-first history for the admin indexing view + a per-client filter.
create index if not exists index_submissions_created_idx
  on public.index_submissions (created_at desc);
create index if not exists index_submissions_client_idx
  on public.index_submissions (client_id, created_at desc);

-- --- RLS ----------------------------------------------------------------------
-- Written ONLY by the server (service_role, BYPASSRLS) - so no authenticated
-- INSERT/UPDATE policy (mirrors scheduled_job_runs / public_audits). Any staff may
-- READ; clients are excluded by is_staff() (no select policy for them).
alter table public.index_submissions enable row level security;
alter table public.index_submissions force row level security;

create policy index_submissions_select on public.index_submissions
  for select using (public.is_staff());
