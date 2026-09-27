-- 0154_brand_kit_page_type_blueprints.sql - a design system knows that a blog post is
-- not a homepage.
--
-- WHAT WAS WRONG, precisely. `brand_kits.blueprint` (0089) is ONE ordered list of
-- sections, and `page_blueprints.resolve_blueprint` returns it for EVERY page type at
-- tier 1. So a client whose captured page was their homepage got the homepage's section
-- sequence - hero, trust bar, services grid, stats, testimonials, CTA - used verbatim as
-- the structure of their blog articles and their location pages. Palette, typography and
-- components transferred correctly; the STRUCTURE did not, because a single blueprint
-- cannot express a per-page-type structure and nothing asked it to.
--
-- Worth being exact about why the single blueprint sat at tier 1 in the first place: it
-- was the right call for the problem it solved (2026-09-17). The content wizard sends a
-- template on every launch, so the "operator explicitly chose a template" tier matched
-- every single job and a client's measured design never once shaped a page. The fix was
-- to rank the measurement above the template. That remains correct. What was missing is
-- that a measurement of a HOMEPAGE is evidence about homepages.
--
-- THE SHAPE. `blueprints` is a MAP of page type -> ordered section list:
--
--     {"homepage": [{"kind": "hero", ...}, ...], "service": [...]}
--
-- and `source_page_type` records what kind of page THIS capture was of, so a reader can
-- always answer "which page did this sequence come from". `blueprint` (singular) is left
-- exactly as it is and still carries the captured page's own sections: every existing
-- row keeps working, the generation path falls back to it, and nothing has to be
-- backfilled for a client to keep publishing.
--
-- WHY A MAP RATHER THAN A page_type COLUMN + ONE ROW PER TYPE. A kit is a VERSIONED
-- WHOLE - "the client's design system as of March" - and the partial unique index
-- `brand_kits_active_per_client_idx` enforces exactly one active kit per client. Splitting
-- the blueprint across rows would either break that guarantee or require a second
-- versioning scheme for the rows inside a version. The map keeps one row = one design
-- system, which is what the rest of the module already assumes.
--
-- Additive and idempotent: two ADD COLUMN IF NOT EXISTS with defaults, no rewrite of any
-- existing value, no RLS change (brand_kits already ENABLE+FORCE from 0089).

alter table public.brand_kits
  add column if not exists blueprints jsonb not null default '{}'::jsonb;

alter table public.brand_kits
  add column if not exists source_page_type text not null default '';

comment on column public.brand_kits.blueprints is
  'Per-page-type section blueprints: {"<page_type>": [<SectionSpec>, ...]}. The '
  'generation path prefers the entry matching the page being built; with no entry it '
  'uses the audited template for that page type rather than another type''s measured '
  'sequence. Merged forward across versions, so capturing a homepage and later a '
  'service page leaves a kit that knows both.';

comment on column public.brand_kits.source_page_type is
  'What kind of page this capture measured (homepage / service / location / blog / ...), '
  'or '''' when the capture did not say. This is the key `blueprint` (singular) belongs '
  'under in `blueprints`, and the provenance for why a given sequence looks the way it '
  'does.';

-- A GIN index because the read is "does this kit hold a blueprint for page type X" -
-- a key-existence test on the map, which btree cannot serve.
create index if not exists brand_kits_blueprints_gin_idx
  on public.brand_kits using gin (blueprints);
