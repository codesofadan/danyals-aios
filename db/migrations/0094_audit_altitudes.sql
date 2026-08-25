-- 0094_audit_altitudes.sql - store an audit's findings as ROWS, at three
-- altitudes, instead of as a JSON blob on disk.
--
-- WHAT WAS MISSING, measured on a real 197-page run (run_uuid 837b75d6, see
-- docs/audit/fixtures/README.md):
--
--   * `findings.json` was an opaque 9.3 MB file. Nothing indexed it, queried it,
--     diffed it or trended it. Every question the product needs to answer -
--     "which pages", "is this fixed", "what changed this month" - was unanswerable.
--   * That run emitted 15,617 findings, of which 8,077 were fail/warn. Those
--     8,077 rows contain only **81 distinct causes**. The client was being handed
--     8,077 things to read when there were 81 things to fix. Grouping by cause is
--     a 99.0% reduction in what a human must read.
--   * A finding carried `page_id` - a per-run autoincrement - and NO URL. The URL
--     lived only in the engine's own SQLite, which was never emitted, so the
--     per-page grain could not be recovered from the artifacts at all.
--
-- THE THREE ALTITUDES, and why each is a separate table rather than a view:
--
--   NANO   audit_finding_instances   one occurrence, one locus
--                                    "/services/x  <img src=hero.jpg>  alt missing"
--   MICRO  audit_findings            one CAUSE, N instances
--                                    "the service template omits H1 - 42 pages"
--   MACRO  audit_rollups             pillar / subpoint verdict + COVERAGE
--                                    "technical: 25 of 100 checks ran"
--
-- audit_pages is the fourth table and the page-side pivot: without it "every
-- page was checked" is not a claim we can substantiate, and a page-denominated
-- health number cannot be computed.
--
-- WHY MACRO IS MATERIALISED AND NOT A VIEW. `audit_findings` is CURRENT STATE -
-- a re-run upserts it. A view over current state cannot reconstruct what run N's
-- basis was once run N+1 has landed, and coverage ("off-page: 0 of 71 checks
-- ran") is a property of the RUN, not of the findings that survived it. Five
-- consumers - report.html, the PDF, the workbook, the staff dashboard and the
-- client portal - must show one number; computing it five times is five chances
-- to disagree.
--
-- TENANCY. Every table carries `client_id` directly so RLS never needs a join,
-- matching every other tenant table in this schema. The worker writes through
-- the service_role connection, which bypasses RLS by design.

-- --- pages -------------------------------------------------------------------
create table if not exists public.audit_pages (
  id                uuid primary key default gen_random_uuid(),
  audit_id          uuid not null references public.audits (id) on delete cascade,
  client_id         uuid references public.clients (id) on delete cascade,
  run_uuid          text not null default '',
  -- The engine's per-run autoincrement. Kept ONLY as the join key for this run's
  -- findings; it is meaningless across runs and must never be used as identity.
  engine_page_id    integer,
  url               text not null,
  url_hash          text not null,
  canonical_url     text,
  page_type         text,
  template_id       text not null default '',
  http_status       integer,
  response_ms       integer,
  title             text,
  meta_description  text,
  h1                text,
  word_count        integer,
  indexable         boolean,
  crawl_depth       integer,
  is_orphan         boolean not null default false,
  -- Per-page issue rollup, written by the ingest so the page pivot needs no join.
  issues_total      integer not null default 0,
  issues_critical   integer not null default 0,
  issues_major      integer not null default 0,
  issues_minor      integer not null default 0,
  issues_info       integer not null default 0,
  -- A page is "healthy" when nothing critical or major was observed on it. This
  -- is the numerator of url_health_pct, the one score whose denominator is pages
  -- rather than checks and which is therefore comparable across tiers and months.
  health_pass       boolean not null default true,
  created_at        timestamptz not null default now(),
  unique (audit_id, url_hash)
);

create index if not exists audit_pages_audit_idx  on public.audit_pages (audit_id);
create index if not exists audit_pages_client_idx on public.audit_pages (client_id);
create index if not exists audit_pages_engine_idx on public.audit_pages (audit_id, engine_page_id);

-- --- findings (MICRO: one cause) ---------------------------------------------
create table if not exists public.audit_findings (
  id                    uuid primary key default gen_random_uuid(),
  client_id             uuid references public.clients (id) on delete cascade,
  -- The audit that most recently OBSERVED this finding. The row itself outlives
  -- any single audit: that is what makes first_seen/last_seen and delta possible.
  audit_id              uuid references public.audits (id) on delete set null,
  scope_type            text not null default 'site',
  -- The registrable site this finding belongs to. A client may hold several
  -- domains, and a finding on one is not a finding on another.
  scope_key             text not null,
  check_id              text not null,
  check_name            text not null default '',
  -- Cause-shaped identity. NEVER contains a URL, an evidence value, a page id, a
  -- run id or a count: a fingerprint that moves when the site's content moves
  -- cannot support "is this the same problem as last month".
  fingerprint           text not null,
  fingerprint_version   integer not null default 1,
  locus_kind            text not null default 'site',   -- site | template | url | entity
  locus_value           text not null default '',
  discriminator         text not null default '',
  -- Taxonomy, joined from the canonical checklist registry at ingest. Before the
  -- registry existed these were 38% populated and sometimes out of vocabulary.
  pillar                text not null default '',       -- on-page|technical|off-page|local-seo
  subcategory           text not null default '',       -- the SUBPOINT
  dimension             text not null default '',       -- onpage|technical|offpage|local|geo|strategy
  owner_agent           text not null default '',
  automation            text not null default '',       -- full | ai-assisted
  severity              text not null default 'info',
  status                text not null default 'open',   -- open|closed_verified|closed_unverified|regressed|unknown_not_checked
  confidence            numeric,
  confidence_label      text not null default '',       -- measured | inferred | sampled
  impact_score          numeric,
  effort_points         numeric,
  priority              numeric,
  scoring_model_version text not null default '',
  -- instance_count is what we OBSERVED; instances_stored is what we KEPT. They
  -- are separate columns so a cap can never masquerade as a smaller problem.
  instance_count        integer not null default 0,
  instances_stored      integer not null default 0,
  pages_affected        integer not null default 0,
  evidence              jsonb not null default '{}'::jsonb,
  remediation           text not null default '',
  references_json       jsonb not null default '[]'::jsonb,
  first_seen_audit      uuid,
  first_seen_at         timestamptz not null default now(),
  last_seen_audit       uuid,
  last_seen_at          timestamptz not null default now(),
  closed_audit          uuid,
  closed_at             timestamptz,
  closure_reason        text not null default '',
  closure_evidence      jsonb,
  regressed_at          timestamptz,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  -- The identity constraint. A re-run UPDATES last_seen_at rather than inserting
  -- a duplicate; without this every month's audit would re-report every finding
  -- as new and every delta would be a lie.
  unique (scope_type, scope_key, check_id, fingerprint)
);

create index if not exists audit_findings_client_idx   on public.audit_findings (client_id, status, priority desc nulls last);
create index if not exists audit_findings_audit_idx    on public.audit_findings (audit_id);
create index if not exists audit_findings_scope_idx    on public.audit_findings (scope_key, last_seen_at desc);
create index if not exists audit_findings_dim_idx      on public.audit_findings (audit_id, dimension, subcategory);

-- --- instances (NANO: one occurrence) ----------------------------------------
create table if not exists public.audit_finding_instances (
  id                uuid primary key default gen_random_uuid(),
  finding_id        uuid not null references public.audit_findings (id) on delete cascade,
  client_id         uuid references public.clients (id) on delete cascade,
  audit_id          uuid references public.audits (id) on delete set null,
  -- The identity of this occurrence WITHIN its finding. Not `url`, because an
  -- entity instance (a directory listing, a GBP field) has no URL and every one
  -- of them would collide on the empty string.
  instance_key      text not null,
  instance_kind     text not null default 'url',        -- url | entity | resource
  url               text not null default '',
  page_id           uuid references public.audit_pages (id) on delete set null,
  template_id       text not null default '',
  -- WHERE on the page: {selector, nth, attr, line}. This is what turns "197 pages
  -- have an alt-text problem" into "this img on this page".
  locator           jsonb not null default '{}'::jsonb,
  observed          text not null default '',
  expected          text not null default '',
  detail            text not null default '',
  evidence          jsonb not null default '{}'::jsonb,
  severity_override text not null default '',
  status            text not null default 'open',
  first_seen_at     timestamptz not null default now(),
  last_seen_at      timestamptz not null default now(),
  closed_at         timestamptz,
  unique (finding_id, instance_key)
);

create index if not exists audit_fi_finding_idx on public.audit_finding_instances (finding_id);
create index if not exists audit_fi_client_idx  on public.audit_finding_instances (client_id);
create index if not exists audit_fi_audit_idx   on public.audit_finding_instances (audit_id);
create index if not exists audit_fi_url_idx     on public.audit_finding_instances (audit_id, url);

-- --- rollups (MACRO: the verdict, with its basis) ----------------------------
create table if not exists public.audit_rollups (
  id                    uuid primary key default gen_random_uuid(),
  audit_id              uuid not null references public.audits (id) on delete cascade,
  client_id             uuid references public.clients (id) on delete cascade,
  run_uuid              text not null default '',
  level                 text not null,                  -- site | pillar | subpoint | dimension
  key                   text not null default '',       -- '' | 'technical' | 'technical/crawlability'
  label                 text not null default '',
  -- COVERAGE. These four columns are the reason this table exists. A real run
  -- scored technical 97.2 having run 25 of 100 technical checks; without a
  -- denominator on the row, "97.2" reads as a clean bill of health.
  checks_applicable     integer not null default 0,
  checks_planned        integer not null default 0,
  checks_ran            integer not null default 0,
  checks_skipped        integer not null default 0,
  skip_reasons          jsonb not null default '{}'::jsonb,
  findings_open         integer not null default 0,
  instances_open        integer not null default 0,
  pages_affected        integer not null default 0,
  pages_crawled         integer not null default 0,
  severity_counts       jsonb not null default '{}'::jsonb,
  status_counts         jsonb not null default '{}'::jsonb,
  -- NULL means NOT MEASURED. Never 0, never omitted: a zero score and an
  -- unmeasured dimension are opposite statements and must not share a value.
  score                 numeric,
  -- Denominator is PAGES, not checks, so this one IS comparable across tiers and
  -- across months even when the check set changes.
  url_health_pct        numeric,
  -- Two scores may only be compared when this matches. Enforced in code.
  basis_hash            text not null default '',
  scoring_model_version text not null default '',
  generated_at          timestamptz not null default now(),
  unique (audit_id, level, key)
);

create index if not exists audit_rollups_audit_idx  on public.audit_rollups (audit_id, level);
create index if not exists audit_rollups_client_idx on public.audit_rollups (client_id);

-- --- updated_at trigger on findings ------------------------------------------
drop trigger if exists audit_findings_set_updated_at on public.audit_findings;
create trigger audit_findings_set_updated_at
  before update on public.audit_findings
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- Staff read; nobody writes through a user JWT. The ingest runs in the worker on
-- the service_role connection, which bypasses RLS - the same seam `audits` uses.
-- There is deliberately NO client-facing policy here: the portal reads audits
-- through the `portal_audits` view, and an equivalent view for findings is a
-- separate decision about what a client may see.
alter table public.audit_pages             enable row level security;
alter table public.audit_pages             force  row level security;
alter table public.audit_findings          enable row level security;
alter table public.audit_findings          force  row level security;
alter table public.audit_finding_instances enable row level security;
alter table public.audit_finding_instances force  row level security;
alter table public.audit_rollups           enable row level security;
alter table public.audit_rollups           force  row level security;

create policy audit_pages_select     on public.audit_pages             for select using (public.is_staff());
create policy audit_findings_select  on public.audit_findings          for select using (public.is_staff());
create policy audit_fi_select        on public.audit_finding_instances for select using (public.is_staff());
create policy audit_rollups_select   on public.audit_rollups           for select using (public.is_staff());
