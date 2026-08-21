-- 0069_site_builder.sql - Part "Website Reconstruction" Phase 1+2: the persisted,
-- versioned DesignIR + the single end-to-end site-generation job ledger.
--
-- WHY THIS EXISTS. Today a "design profile" (app/services/site_design.py) is
-- computed at request time and stored inline as jsonb inside content_jobs.
-- source_pack - it is never its own entity, never versioned, and cannot be reused
-- across multiple generated pages or diffed against a later re-analysis. DesignIR
-- promotes that into a first-class, platform-independent record: one row per
-- extracted/authored design, versioned, reusable by many generation jobs.
--
--   * design_irs          - the platform-independent design: palette / typography /
--     layout / components / responsive rules / assets / an ordered section tree,
--     PLUS which page-builder(s) it can render into. `source_type` records where it
--     came from (an analyzed existing site, a reference-design site whose LAYOUT is
--     borrowed but content is NOT, a template, or a hand-authored manual profile).
--     Versioned (`version`) so a re-analysis or a template edit creates a new row
--     rather than silently overwriting one a job already published from.
--   * site_generation_jobs - ONE job spans the WHOLE pipeline (analyze -> generate ->
--     upload assets -> render -> validate -> correct -> publish), matching the
--     browser's own status copy ("Analyzing... Generating... Publishing..."). A
--     single unified state machine (not a bespoke enum per phase like content_jobs/
--     web2_properties) because, unlike Content vs. Off-page (separate FEATURES), a
--     website build is genuinely one user-facing job end-to-end; fragmenting it into
--     per-phase tables would fragment the one progress bar the wizard shows.
--
-- RLS mirrors 0035_keyword_research / 0018_offpage: any STAFF may READ (is_staff());
-- the create/advance path is gated FINER at the app layer (require_perm) exactly
-- like on_page's queueing action, because triggering a real external Playwright
-- browse (cost + SSRF surface) is closer to "run_audits" than to a lead-only
-- internal-data mutation - so RLS itself stays broad (is_staff()) and the specific
-- perm lives in app/modules/site_builder/router.py, matching 0038's documented
-- split between the DB boundary and the app-layer permission. The WORKER (the
-- analyze/generate/render/publish tasks) writes via privileged_connection
-- (service_role bypasses RLS) - identical to every other module's worker path.

-- --- Enum (idempotent guard; enums have no "create ... if not exists") --------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'site_job_status') then
    create type public.site_job_status as enum (
      'queued', 'analyzing', 'generating', 'uploading_assets', 'rendering',
      'validating', 'correcting', 'publishing', 'completed', 'failed'
    );
  end if;
end $$;

-- Human-friendly stable code (SB-0001 ...), like the other module code sequences.
create sequence if not exists public.site_builder_code_seq;

-- --- design_irs: the platform-independent, versioned design -------------------
create table if not exists public.design_irs (
  id                uuid primary key default gen_random_uuid(),
  -- NULLABLE: an org-level template or a not-yet-assigned analysis has no client.
  client_id         uuid references public.clients (id) on delete set null,
  client_name       text not null default '',   -- display SNAPSHOT (client_id never leaks)
  source_type       text not null default 'manual'
                      check (source_type in ('existing_site', 'reference_site', 'template', 'manual')),
  source_url        text not null default '',
  industry          text not null default '',
  page_type         text not null default '',
  design_style      text not null default '',
  version           integer not null default 1,
  -- The IR body. Kept as separate jsonb columns (not one blob) so a single facet
  -- (e.g. just the palette) can be read/diffed without deserialising the whole IR -
  -- mirrors site_design.SiteDesignProfile's field shape so that extractor's output
  -- slots in directly (see app/modules/site_builder/service.py).
  palette           jsonb not null default '{}',
  typography        jsonb not null default '{}',
  layout            jsonb not null default '{}',
  components        jsonb not null default '{}',
  responsive        jsonb not null default '{}',   -- per-breakpoint overrides (desktop/tablet/mobile)
  assets            jsonb not null default '[]',   -- extracted images/logos/icons [{url, kind, alt, width, height}]
  sections          jsonb not null default '[]',   -- the ordered component tree (content-slot-bearing)
  supported_editors text[] not null default array['elementor']::text[],
  notes             text not null default '',
  wireframe_html    text not null default '',
  created_by        uuid references public.users (id) on delete set null,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists design_irs_client_id_idx on public.design_irs (client_id);

create trigger design_irs_set_updated_at
  before update on public.design_irs
  for each row execute function public.set_updated_at();

alter table public.design_irs enable row level security;
alter table public.design_irs force row level security;

create policy design_irs_select on public.design_irs
  for select using (public.is_staff());

create policy design_irs_write on public.design_irs
  for all
  using (public.is_staff())
  with check (public.is_staff());

comment on table public.design_irs is
  'Platform-independent, versioned page/site design (palette/typography/layout/'
  'components/responsive/assets/sections) - the intermediate representation between '
  'an analyzed or referenced site (or a template) and a WordPress renderer.';

-- --- site_generation_jobs: the one end-to-end pipeline job --------------------
create table if not exists public.site_generation_jobs (
  id             uuid primary key default gen_random_uuid(),
  code           text not null unique
                   default ('SB-' || to_char(nextval('public.site_builder_code_seq'), 'FM0000')),
  client_id      uuid references public.clients (id) on delete set null,
  client_name    text not null default '',
  status         public.site_job_status not null default 'queued',
  source_type    text not null default 'template'
                   check (source_type in ('existing_site', 'reference_site', 'template', 'manual')),
  source_url     text not null default '',
  page_type      text not null default '',
  industry       text not null default '',
  editor_mode    text not null default 'auto'
                   check (editor_mode in ('auto', 'gutenberg', 'elementor', 'hybrid')),
  fidelity_mode  text not null default 'balanced'
                   check (fidelity_mode in ('max_editability', 'max_fidelity', 'balanced')),
  -- Set once the analyze/generate phase resolves or authors the design; NULL while
  -- queued/analyzing. ON DELETE SET NULL: a design row can be pruned without
  -- corrupting the job's own history.
  design_ir_id   uuid references public.design_irs (id) on delete set null,
  -- The human-readable progress line the wizard polls + renders verbatim
  -- ("Analyzing website...", "Uploading assets...") - never fabricated client-side.
  stage_detail   text not null default '',
  error          text,
  created_by     uuid references public.users (id) on delete set null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists site_generation_jobs_client_id_idx on public.site_generation_jobs (client_id);
create index if not exists site_generation_jobs_status_idx on public.site_generation_jobs (status);

create trigger site_generation_jobs_set_updated_at
  before update on public.site_generation_jobs
  for each row execute function public.set_updated_at();

alter table public.site_generation_jobs enable row level security;
alter table public.site_generation_jobs force row level security;

create policy site_generation_jobs_select on public.site_generation_jobs
  for select using (public.is_staff());

create policy site_generation_jobs_write on public.site_generation_jobs
  for all
  using (public.is_staff())
  with check (public.is_staff());

comment on table public.site_generation_jobs is
  'ONE job per end-to-end website/page build (analyze -> generate -> upload assets -> '
  'render -> validate -> correct -> publish); status drives the browser progress copy.';
