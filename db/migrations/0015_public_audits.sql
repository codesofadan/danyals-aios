-- 0015_public_audits.sql - the PUBLIC, no-login "Free Audit" funnel (P6C-1).
--
-- ONE free audit per email (lead capture); the report is fetched by an opaque
-- token; a Fiverr upsell link is shown on it. This table is ISOLATED from ALL
-- tenant data - it is written ONLY by the server (service_role via the
-- privileged path): there is NO client_id and NO tenant read path. The single
-- RLS policy lets STAFF review the leads list; the anonymous visitor NEVER reads
-- through RLS - GET /public/audits/{token} fetches through the privileged path
-- filtered to that one report_token and returns only its curated result.
--
-- Reuses the audit_status enum (0008). This is NOT the tenant `audits` table:
-- it carries no client linkage, no cost/runtime/started_at columns - only the
-- lead's email, the target url, the job state, the results, artifact refs, and
-- the capability token. Idempotent (create table/index if not exists).

create table if not exists public.public_audits (
  id           uuid primary key default gen_random_uuid(),
  email        text not null,
  url          text not null,
  status       public.audit_status not null default 'queued',
  score        integer,
  scores       jsonb not null default '{}'::jsonb,
  run_uuid     text,
  artifact_dir text,
  pdf_path     text,
  json_path    text,
  report_token text not null unique default encode(gen_random_bytes(24), 'hex'),  -- pgcrypto
  source       text not null default 'landing',
  error        text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
-- The "allow only one audit" rule: one free audit per email (case-insensitive).
create unique index if not exists public_audits_email_key on public.public_audits (lower(email));
create index if not exists public_audits_created_at_idx on public.public_audits (created_at desc);

-- Idempotent trigger (Postgres has no CREATE TRIGGER IF NOT EXISTS pre-14 style
-- guard we rely on elsewhere; drop-then-create keeps re-runs clean).
drop trigger if exists public_audits_set_updated_at on public.public_audits;
create trigger public_audits_set_updated_at
  before update on public.public_audits
  for each row execute function public.set_updated_at();

-- --- RLS ----------------------------------------------------------------------
-- Staff may review leads; writes only via the server (service_role, BYPASSRLS).
-- The anonymous visitor NEVER reads via RLS - the tokenized read goes through the
-- privileged path filtered to a single report_token. No client_id, no tenant path.
alter table public.public_audits enable row level security;
alter table public.public_audits force row level security;

create policy public_audits_select on public.public_audits
  for select using (public.is_staff());
