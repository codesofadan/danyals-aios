-- 0068_web2_platforms_new_adapters.sql - four new REAL Web2Publisher adapters:
-- Webflow, HubSpot CMS, Drupal, Joomla (integrations/web2_publishers.py). Same
-- shape as 0045's enum growth + 0066's catalog-insert idiom, so this is one file
-- doing two additive, independently-safe things:
--
--   Part A - grow the public.web2_platform PUBLISHING enum (0018/0045) with the 4
--   new platform labels. Standalone ALTER TYPE ... ADD VALUE statements, exactly
--   like 0045: Postgres forbids using a freshly-added enum value in the SAME
--   transaction that adds it, but nothing in this file's Part B reads the enum
--   back (the catalog's `name` column is plain text, decoupled from the enum on
--   purpose - see 0062's header) so both parts are safe together in one file.
--
--   Part B - flip the EXISTING Webflow row in public.web2_platforms (inserted by
--   0066 with automation_ready=false, back when there was no Webflow client yet)
--   to automation_ready=true, and insert 3 new catalog rows for HubSpot CMS,
--   Drupal, and Joomla, all automation_ready=true / auth_type='api' - the pipeline
--   can publish to all 4 today. Uses `on conflict (name) do update` (not `do
--   nothing`) specifically so re-applying this migration correctly upgrades the
--   pre-existing Webflow row instead of leaving it stuck at automation_ready=false.

-- --- Part A: enum growth --------------------------------------------------------
alter type public.web2_platform add value if not exists 'Webflow';
alter type public.web2_platform add value if not exists 'HubSpot CMS';
alter type public.web2_platform add value if not exists 'Drupal';
alter type public.web2_platform add value if not exists 'Joomla';

-- --- Part B: catalog upsert ------------------------------------------------------
insert into public.web2_platforms
  (name, homepage_url, signup_url, publish_url_or_method, auth_type, authority_tier, market, automation_ready, notes)
values
  ('Webflow','https://webflow.com','https://webflow.com/signup','api: WebflowClient (integrations/web2_publishers.py) - Data API v2, Bearer site token; PATCH/POST the CMS item then POST .../publish so the collection item goes live at once (two-step, mirrors GitHubPagesClient''s commit-then-enable-Pages honesty)','api','medium','global',true,'Real Web2Publisher live. Free Starter site gives a *.webflow.io staging subdomain (Webflow branding, no custom domain, capped pages/CMS items on the free tier). Token self-serve in site settings.'),
  ('HubSpot CMS','https://www.hubspot.com/products/cms','https://app.hubspot.com/signup/cms','api: HubSpotClient (integrations/web2_publishers.py) - CMS Blog Post API v3, private-app Bearer token; POST/PATCH /cms/v3/blogs/posts against an existing content_group_id (blog)','api','high','global',true,'Real Web2Publisher live. Needs an existing HubSpot blog (content_group_id) to post into - no default blog. Private-app token is self-serve from Settings > Integrations > Private Apps. High-DA, marketing-grade CMS.'),
  ('Drupal','https://www.drupal.org','https://www.drupal.org/register','api: DrupalClient (integrations/web2_publishers.py) - core JSON:API (ships in core >= 8.7, no contrib module), HTTP Basic with an API-only Drupal user; POST/PATCH /jsonapi/node/<content_type>','api','medium','global',true,'Real Web2Publisher live. Auth is HTTP Basic against a client-provisioned Drupal user - Basic-auth requests are exempt from Drupal''s cookie-session CSRF check, so no separate token handshake is needed. Self-hosted, so authority varies by the specific site.'),
  ('Joomla','https://www.joomla.org','https://www.joomla.org/register.html','api: JoomlaClient (integrations/web2_publishers.py) - core Web Services API (com_content), per-user "API Token" (Joomla 4.3+, User > Edit > API Token); POST/PATCH /api/index.php/v1/content/articles','api','low','global',true,'Real Web2Publisher live. Response carries no absolute public URL (SEF routing is site-configured), so the client builds the always-resolvable non-SEF permalink (index.php?option=com_content&view=article&id=<id>) rather than guessing a pretty slug. Self-hosted, wide quality variance -> authority_tier=low.')
on conflict (name) do update set
  automation_ready = excluded.automation_ready,
  auth_type = excluded.auth_type,
  publish_url_or_method = excluded.publish_url_or_method,
  notes = excluded.notes;
