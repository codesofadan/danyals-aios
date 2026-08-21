-- 0076_web2_platforms_batch5.sql - a FIFTH pass of real Web2Publisher adapters
-- (integrations/web2_publishers.py): 3 more platforms, growing WEB2_PLATFORMS from
-- 50 to 53. Same two-part shape as 0068/0070/0072 (enum growth is safe alongside the
-- catalog upsert in one file only because 0062's catalog `name` column is plain
-- text, decoupled from the public.web2_platform enum on purpose - see 0062's header).
--
--   Part A - grow the public.web2_platform PUBLISHING enum (0018/0045/0068/0070/0072)
--   with the 3 new platform labels. Standalone ALTER TYPE ... ADD VALUE statements,
--   same reason as always: Postgres forbids reading a freshly-added enum value back
--   in the SAME transaction that adds it, and nothing in Part B does.
--
--   Part B - insert the 3 new catalog rows (public.web2_platforms), with
--   publish_url_or_method/notes naming the real class each is served by.
--   `on conflict (name) do update`, same as prior passes.
--
-- WHAT WAS BUILT (3 real Web2Publisher clients - see web2_publishers.py):
--   Sanity, Storyblok, Hygraph - all three headless CMSs. Unlike every prior
--   platform, none of these three render a public page of their own: the client's
--   OWN frontend must query and render the content for it to become a live,
--   indexable placement. Every client here ALWAYS returns verified=False (the same
--   honesty NotionClient already established for the identical "page created, but
--   not provably public" case) - see each class's docstring in web2_publishers.py.

-- --- Part A: enum growth --------------------------------------------------------
alter type public.web2_platform add value if not exists 'Sanity';
alter type public.web2_platform add value if not exists 'Storyblok';
alter type public.web2_platform add value if not exists 'Hygraph';

-- --- Part B: catalog upsert ------------------------------------------------------
insert into public.web2_platforms
  (name, homepage_url, signup_url, publish_url_or_method, auth_type, authority_tier, market, automation_ready, notes)
values
  ('Sanity','https://www.sanity.io','https://www.sanity.io/get-started','api: SanityClient (integrations/web2_publishers.py) - POST https://{project_id}.api.sanity.io/v2024-01-01/data/mutate/{dataset}, Bearer API token, one `create`/`createOrReplace` mutation per publish','api','medium','global',true,'Real Web2Publisher live. Headless Content Lake only - no rendered public page of its own, so verified is always false; post_url is a best-effort Sanity Studio deep link. Document `_type` (doc_type, default "post") is project-schema-specific.'),
  ('Storyblok','https://www.storyblok.com','https://app.storyblok.com/#/signup','api: StoryblokClient (integrations/web2_publishers.py) - POST/PUT https://mapi.storyblok.com/v1/spaces/{space_id}/stories?publish=1, a raw (non-Bearer) Management API personal access token','api','medium','global',true,'Real Web2Publisher live. Headless CMS - the story auto-publishes into the space''s live content, but rendering it still needs the client''s own frontend, so verified stays false; post_url is a best-effort editor deep link. Story `component` (default "page") is space-schema-specific.'),
  ('Hygraph','https://hygraph.com','https://app.hygraph.com/signup','api: HygraphClient (integrations/web2_publishers.py) - GraphQL Content API, `create{Model}` then `publish{Model}(to: PUBLISHED)`, Bearer Permanent Auth Token','api','medium','global',true,'Real Web2Publisher live. Headless Content API only - no rendered public page of its own, so verified is always false; post_url points at the Content API endpoint, not a public page. GraphQL model name (model, default "post") and its title/slug/content fields are project-schema-specific.')
on conflict (name) do update set
  automation_ready = excluded.automation_ready,
  auth_type = excluded.auth_type,
  publish_url_or_method = excluded.publish_url_or_method,
  notes = excluded.notes;
