-- 0104_web2_pacing.sql - publish pacing + the link-measurement columns (R2-13 / R2-16).
--
-- WHY PACING IS A SAFETY CONTROL, NOT A PREFERENCE. A Web 2.0 property is defensible
-- while it reads as a real, low-volume brand blog. Thirty articles appearing across a
-- client's properties in an afternoon does not, no matter how good each one is - the
-- pattern is the tell, independent of the prose, and no content-level check can see it.
-- These are the numbers that keep the shape plausible.
--
-- THEY ARE AGENCY POLICY, NOT VENDOR GUIDANCE. No platform publishes a "safe" cadence
-- and neither does Google. They are set deliberately conservative and are TUNABLE
-- without a deploy, because the honest posture is "safe by default, loosen knowingly"
-- rather than a number hard-coded somewhere an operator cannot see it.
--
-- ITS OWN TABLE, NOT `workspace_settings` (a departure from R2-13's text). That table is
-- a narrow, contract-locked singleton whose every column maps 1:1 to a field on the
-- agency settings screen (agency_name, support_email, timezone, ...) and is guarded by
-- `tests/test_contract_lock.py`. Ten publishing knobs do not belong in an agency-branding
-- record, and R2-13 explicitly permits a dedicated table. Same singleton shape, so a GET
-- is still one row.

create table if not exists public.web2_pacing_settings (
  id integer primary key default 1 check (id = 1),

  -- Spacing. A single property that posts weekly looks like a blog; one that posts
  -- three times a day looks like a feed someone is filling.
  min_interval_same_property_days      int not null default 7,
  min_interval_same_client_platform_h  int not null default 72,
  min_interval_same_client_h           int not null default 24,

  -- Volume ceilings. The per-client cap is what stretches a 30-article campaign across
  -- weeks; the operator sees the resulting completion date before they commit.
  max_publishes_per_client_per_day     int not null default 1,
  -- Keyed on the ACCOUNT, because a house account's blast radius is every client on it.
  max_publishes_per_house_account_day  int not null default 3,
  max_publishes_per_house_account_30d  int not null default 20,
  max_properties_per_house_account     int not null default 10,   -- closes WEB2-008

  -- Campaign shape.
  max_properties_per_client_campaign   int not null default 4,
  min_days_between_client_properties   int not null default 14,

  -- Timing jitter. Publishing every property at exactly the scheduled minute is itself
  -- a machine signature; the scheduler spreads each slot across this window.
  publish_jitter_max_hours             int not null default 36,

  updated_at timestamptz not null default now()
);

create trigger web2_pacing_settings_set_updated_at
  before update on public.web2_pacing_settings
  for each row execute function public.set_updated_at();

insert into public.web2_pacing_settings (id) values (1) on conflict (id) do nothing;

alter table public.web2_pacing_settings enable row level security;
alter table public.web2_pacing_settings force row level security;

create policy web2_pacing_settings_select on public.web2_pacing_settings
  for select using (public.is_staff());
create policy web2_pacing_settings_update on public.web2_pacing_settings
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

comment on table public.web2_pacing_settings is
  'Agency-global Web 2.0 publish pacing (singleton id=1). Agency policy, not vendor '
  'guidance: tunable without a deploy, conservative by default (R2-13).';

-- --- Scheduling + measured link facts on the property -----------------------------
-- `scheduled_for` mirrors `content_jobs.publish_at` (0072) deliberately: same pattern,
-- same sweep shape, so the drip scheduler is a known quantity rather than new machinery.
-- A row is `publishing` with a future `scheduled_for` = approved and waiting its slot.
alter table public.web2_properties
  add column if not exists scheduled_for timestamptz;

create index if not exists web2_properties_scheduled_for_idx
  on public.web2_properties (scheduled_for) where scheduled_for is not null;

-- R2-16: MEASURE the placed link, never assume it. Several surviving link surfaces are
-- nofollow by the catalogue's own notes, and a client must never be shown a nofollow
-- placement as a ranking link. `link_found = false` on a live URL is also the earliest
-- signal that a property was quietly moderated.
alter table public.web2_properties
  add column if not exists link_rel text not null default '';
alter table public.web2_properties
  add column if not exists link_found boolean;
alter table public.web2_properties
  add column if not exists link_checked_at timestamptz;

comment on column public.web2_properties.scheduled_for is
  'When an APPROVED property is due to publish. Future value => the approval skipped '
  'the immediate enqueue and the scheduler claims it when due (mirrors 0072).';

comment on column public.web2_properties.link_rel is
  'The rel attribute actually observed on the placed link (R2-16). Measured by fetching '
  'the published page - never inferred from the platform.';
