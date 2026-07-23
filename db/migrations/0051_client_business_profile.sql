-- 0051_client_business_profile.sql - Wave 4: the client's OWN business identity /
-- NAP, captured at CLIENT CREATION.
--
-- 0045 gave the citation-builder a `business_profiles` table: a MULTI-LOCATION
-- canonical NAP a citation SUBMISSION fills a directory form with (label, is_primary,
-- nap_locked, one row per branch). That is the submission-engine's view of a client.
-- What was missing is the client's OWN identity captured up front, the moment the
-- account is created, so that the very first citation campaign has a real name /
-- address / phone to submit and the operator is not met with "No business profile yet
-- for this client".
--
-- This migration adds exactly one such record PER CLIENT (`unique (client_id)`): the
-- source-of-truth NAP the Add-Client wizard collects and the citation-builder DERIVES
-- its first `business_profiles` row from. It is additive and idempotent - it mirrors
-- 0040_client_onboarding.sql's structure (FORCE RLS, staff-read / lead-write, a
-- snapshot client_name, the shared set_updated_at trigger) and it REUSES the
-- `business_market` enum created in 0045 so the market maps 1:1 into a derived
-- `business_profiles` row with no translation.
--
-- RLS mirrors 0040/0045 exactly: any STAFF may READ (is_staff()); only LEADS
-- (owner/admin/manager) may INSERT/UPDATE - the app's manage_clients gate. A portal
-- client gets NO select policy: this is staff-facing operational data (it enumerates
-- the exact NAP the agency will publish on the client's behalf), so it stays inside
-- the staff namespace, exactly like the onboarding checklist and the submission NAP.

create table if not exists public.client_business_profiles (
  id             uuid primary key default gen_random_uuid(),
  -- One profile per client engagement. ON DELETE CASCADE retires the NAP with its
  -- client; client_name is a display SNAPSHOT so client_id never has to be surfaced.
  client_id      uuid not null references public.clients (id) on delete cascade,
  client_name    text not null default '',
  business_name  text not null default '',
  address_line1  text not null default '',
  address_line2  text not null default '',
  city           text not null default '',
  region         text not null default '',              -- state / province / county
  postal_code    text not null default '',
  -- Reuse the enum 0045 created so a derived citation `business_profiles` row takes
  -- this value verbatim (no US/UK/... translation layer to drift).
  market         public.business_market not null default 'US',
  phone          text not null default '',
  website_url    text not null default '',
  -- The GBP-style PRIMARY category plus any additional categories. Kept split (not a
  -- single array) because the primary category is load-bearing for a listing while the
  -- extras are optional - a derived submission profile folds them into one ordered list.
  primary_category text not null default '',
  extra_categories text[] not null default '{}',
  hours          jsonb not null default '{}'::jsonb,     -- {"mon": "9:00-17:00", ...}
  description    text not null default '',               -- the business blurb / bio
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  -- Exactly one identity per client: the Add-Client wizard writes it once and the
  -- Edit modal UPSERTs it, so a re-save can never duplicate the record.
  unique (client_id)
);

create index if not exists client_business_profiles_client_id_idx
  on public.client_business_profiles (client_id);

create trigger client_business_profiles_set_updated_at
  before update on public.client_business_profiles
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
alter table public.client_business_profiles enable row level security;
alter table public.client_business_profiles force row level security;

create policy client_business_profiles_select on public.client_business_profiles
  for select using (public.is_staff());
create policy client_business_profiles_insert on public.client_business_profiles
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy client_business_profiles_update on public.client_business_profiles
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
