-- 0149_web2_seo_fields.sql - the SEO + media fields a Web 2.0 placement carries
-- (M05 REQ-W2-007 / REQ-W2-008, off-page Phase 2).
--
-- WHAT WAS MISSING. `web2_properties` recorded WHERE a placement went and WHETHER its
-- link survived, but nothing about the page itself beyond the body. So the pipeline had
-- nowhere to put a meta description, a slug, a canonical URL, a lead image or its alt
-- text - which is why the publish path sent none of them even to platforms whose APIs
-- have the fields (Ghost's Admin API takes all five; dev.to's Articles API takes three).
-- The work was not skipped; there was no column to skip it from.
--
-- THE HONESTY RULE THESE COLUMNS ARE UNDER, and why they are all NULLABLE with no
-- default: NULL means "this platform has no such field", '' would mean "we produced an
-- empty one". Those are different facts and an operator reading a thin report needs to
-- tell them apart - a Bluesky placement with no meta description is CORRECT, a Ghost
-- placement with no meta description is a defect. `app.modules.web2.seo_fields` only
-- populates what the platform's measured spec says the adapter will actually transmit,
-- so a NULL here is a statement about the platform, not about our effort.
--
-- `image_alt` IS NOT INDEPENDENT of `image_url`. An image published on a client's behalf
-- with no alt text is an accessibility regression we authored, so the CHECK below makes
-- the pair travel together - the database refuses the combination rather than trusting
-- every future writer to remember. (alt WITHOUT a url is allowed and simply unused: a
-- leftover alt is inert, a missing one is not.)
--
-- `tags` is text[] rather than jsonb: it is a flat list of short strings, every consumer
-- wants it as a list, and jsonb would invite someone to put a structure in it later.

begin;

alter table public.web2_properties
  add column if not exists slug             text,
  add column if not exists meta_description text,
  add column if not exists canonical_url    text,
  add column if not exists image_url        text,
  add column if not exists image_alt        text,
  add column if not exists tags             text[];

-- An image must carry its alt text. See the header: this is a correctness rule about
-- what we publish under a client's brand, not a style preference, so it is a constraint
-- rather than a convention.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'web2_properties_image_alt_ck'
  ) then
    alter table public.web2_properties
      add constraint web2_properties_image_alt_ck
      check (image_url is null or image_url = '' or coalesce(image_alt, '') <> '');
  end if;
end $$;

-- Meta descriptions are rendered by search engines at roughly 155 characters and the
-- deriving code cuts at a word boundary before that. The bound here is deliberately
-- LOOSER (320) than the target: it is a sanity rail against a runaway model response
-- reaching the column, not a second opinion about SEO practice, and a constraint that
-- duplicated the target would reject a legitimate 160-character description.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'web2_properties_meta_len_ck'
  ) then
    alter table public.web2_properties
      add constraint web2_properties_meta_len_ck
      check (meta_description is null or char_length(meta_description) <= 320);
  end if;
end $$;

comment on column public.web2_properties.meta_description is
  'SEO description for platforms whose API transmits one (Ghost, dev.to, WP.com excerpt, '
  'and the static-Pages hosts whose <head> we render ourselves). NULL means the platform '
  'has no such field - NOT that it was skipped.';
comment on column public.web2_properties.canonical_url is
  'Canonical URL for this placement. NEVER the client''s target page: pointing a '
  'property''s canonical at the backlink destination declares the property a duplicate, '
  'Google consolidates it away, and the editorial link passes nothing.';
comment on column public.web2_properties.image_alt is
  'Alt text for image_url. Enforced non-empty whenever image_url is set '
  '(web2_properties_image_alt_ck): an image with no alt text is an accessibility '
  'regression published on the client''s behalf.';

commit;
