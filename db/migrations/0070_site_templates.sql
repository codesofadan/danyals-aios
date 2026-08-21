-- 0070_site_templates.sql - the reusable website/page TEMPLATE catalog (spec
-- sections 6-9, 34-36): industry x pageType x designStyle, never hardcoded into
-- the core engine (new categories/templates are new ROWS, not new Python).
--
-- WHY A SEPARATE TABLE FROM design_irs (0069), NOT A DUPLICATE BODY. A template's
-- actual STRUCTURE (sections/palette/typography/components) already has a home:
-- ``app.modules.site_builder.service.design_ir_from_template`` builds it on demand
-- from ``blueprint_key`` (today, one of the 7 ``page_blueprints`` templates) and a
-- job persists the RESULT as its own versioned ``design_irs`` row when it picks a
-- template. This table is the CATALOG entry only - the taxonomy (industry/pageType/
-- designStyle/category) + marketplace-shaped metadata (name/description/preview/
-- author/rating/version) a wizard recommends FROM - so a template's marketplace
-- metadata never pollutes every generated design row, and a template's structure is
-- never duplicated in two places. A future fully-custom template (not blueprint-
-- backed) attaches via ``design_ir_id`` instead of ``blueprint_key`` - exactly one of
-- the two is set, enforced by the check constraint below.
--
-- ``category`` is a plain TEXT, not an enum: the spec is explicit that "the template
-- system must support adding new categories dynamically" - a Postgres enum would
-- need a migration for every new category, defeating that requirement. The SAME
-- reasoning applies to ``industry``/``design_style``.
--
-- RLS mirrors 0035_keyword_research: any STAFF may READ (is_staff()) - the wizard's
-- template gallery is a staff-facing catalog; only LEADS (owner/admin/manager) may
-- add/edit catalog entries (curating the library is a deliberate content decision,
-- not a per-job action).

create table if not exists public.site_templates (
  id              uuid primary key default gen_random_uuid(),
  key             text not null unique,   -- stable slug the wizard/API references (never a UUID)
  name            text not null,
  category        text not null default '',   -- business/blog/real_estate/ecommerce/services/landing_page/...
  industry        text not null default '',   -- '' = generic/any industry
  page_type       text not null default '',   -- homepage/about/service/service-detail/blog/blog-post/...
  design_style    text not null default '',
  blueprint_key   text,                        -- one of app.services.page_blueprints.TEMPLATES, when blueprint-backed
  design_ir_id    uuid references public.design_irs (id) on delete set null,  -- when custom-body-backed instead
  supported_editors text[] not null default array['elementor', 'gutenberg', 'hybrid']::text[],
  preview_image_url text not null default '',
  description     text not null default '',
  author          text not null default 'AIOS',
  version         integer not null default 1,
  rating          numeric(2, 1),
  is_active       boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint site_templates_one_backing check (
    (blueprint_key is not null and design_ir_id is null)
    or (blueprint_key is null and design_ir_id is not null)
  )
);

create index if not exists site_templates_category_idx on public.site_templates (category);
create index if not exists site_templates_industry_idx on public.site_templates (industry);
create index if not exists site_templates_page_type_idx on public.site_templates (page_type);

create trigger site_templates_set_updated_at
  before update on public.site_templates
  for each row execute function public.set_updated_at();

alter table public.site_templates enable row level security;
alter table public.site_templates force row level security;

create policy site_templates_select on public.site_templates
  for select using (public.is_staff());

create policy site_templates_write on public.site_templates
  for all
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

comment on table public.site_templates is
  'The reusable website/page template catalog: industry x pageType x designStyle '
  'taxonomy + marketplace-shaped metadata, pointing at either a page_blueprints '
  'key or a custom design_irs row for its actual structure.';

-- --- Seed: the 7 existing page_blueprints, catalogued (idempotent) ------------
insert into public.site_templates
  (key, name, category, industry, page_type, design_style, blueprint_key, description)
values
  ('service-generic', 'Service page', 'services', '', 'service', 'modern',
   'service', 'A single-service page: split hero, trust bar, benefits/features grids, numbered process, proof + testimonials, pricing, FAQ, closing CTA.'),
  ('location-generic', 'Location page', 'services', '', 'service-detail', 'modern',
   'location', 'One physical location: NAP + hours high, local services, reviews, team, gallery, embedded map, sibling areas, FAQ.'),
  ('service-area-generic', 'Service-area page', 'services', '', 'service-detail', 'modern',
   'service_area', 'A service across an area with no fixed address there: local proof, covered-areas list, benefits, local reviews.'),
  ('blog-generic', 'Blog / article', 'blog', '', 'blog-post', 'editorial',
   'blog', 'The structural outlier: a repeatable body container absorbs the article body; sticky ToC, proof, FAQ, conclusion, CTA.'),
  ('faq-generic', 'FAQ page', 'blog', '', 'faq', 'minimal',
   'faq', 'A Q&A hub: search + category nav chrome, an accordion body, a contact fallback CTA.'),
  ('local-business-generic', 'Local business landing', 'services', 'local_service', 'homepage', 'modern',
   'local', 'A local business landing: tap-to-call hero, services, about, reviews, covered areas, map, one bottom CTA.'),
  ('homepage-generic', 'Homepage', 'business', '', 'homepage', 'modern',
   'homepage', 'A company homepage: hero + trust strip, benefits/features grids, proof + testimonials, about, stat tiles, repeated CTA.')
on conflict (key) do nothing;
