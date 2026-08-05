-- 0060_business_profile_fields.sql - richer canonical business identity for citation
-- submissions: expand business_profiles beyond bare NAP.
--
-- 0045 gave business_profiles the fields a listing form's NAP block needs
-- (name/address/phone/hours/categories). Real directory forms ask for MORE than NAP:
-- a short description/tagline, a contact email, a logo, the primary social profiles,
-- the year founded, accepted payment types, and a service area. Carrying those on the
-- canonical profile means the submission engines (integrations/citation_bot's FormSpec
-- fields + the direct-API submitters) can fill a richer form from one source of truth
-- instead of leaving those fields blank.
--
-- All additive + nullable + idempotent (`add column if not exists`). Adding columns
-- does NOT touch RLS: business_profiles already ENABLE+FORCE RLS with its select/
-- insert/update policies (0045) and those apply unchanged to the wider row, so the
-- FORCE-RLS gate is unaffected. Existing rows default to NULL (text/int) or an empty
-- array (payment_types) and keep submitting exactly as before.

alter table public.business_profiles
  add column if not exists description   text,
  add column if not exists email         text,
  add column if not exists logo_url      text,
  add column if not exists facebook_url  text,
  add column if not exists instagram_url text,
  add column if not exists linkedin_url  text,
  add column if not exists year_founded  int,
  add column if not exists payment_types text[],
  add column if not exists tagline       text,
  add column if not exists service_area  text;

comment on column public.business_profiles.description is
  'A short business description a directory listing form can fill (nullable).';
comment on column public.business_profiles.payment_types is
  'Accepted payment types (e.g. {cash,visa,amex}); many local directories ask for these.';
comment on column public.business_profiles.service_area is
  'The geographic area served, for service-area businesses that list no storefront.';
