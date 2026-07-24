-- 0057_content_wp_url.sql - the WordPress push URLs captured at publish time.
--
-- When an APPROVED content job is pushed to a client's AIOS Publisher plugin (the
-- host-independent WordPress push), the plugin returns the created post's public
-- permalink and its wp-admin edit link. The existing `wp_post_id` records the id
-- (for reference / idempotent re-publish on the legacy REST path); these two columns
-- record the URLs so the dashboard can link the reviewer straight to the draft on
-- the WordPress site ("Pushed to WordPress (draft) - publish it on the site").
--
-- `wp_url`      = the post's public permalink (may be a preview/draft URL until live).
-- `wp_edit_url` = the wp-admin edit-post link (where the admin presses Publish).
--
-- Server-only, like the other rich pipeline columns (surfaced via the staff-only
-- rich-retrieval endpoint, never in the 15-key ContentJob contract), so no RLS
-- policy change and the RLS gate is unaffected. Nullable + default NULL keeps every
-- existing row + the non-WordPress / no-plugin-target publish path unchanged.
-- Idempotent (safe to re-run).

alter table public.content_jobs
  add column if not exists wp_url text;

alter table public.content_jobs
  add column if not exists wp_edit_url text;

comment on column public.content_jobs.wp_url is
  'The public permalink of the post pushed to the client''s AIOS Publisher plugin '
  '(WordPress); set on the approve->publish push, null until pushed.';
comment on column public.content_jobs.wp_edit_url is
  'The wp-admin edit-post link for the pushed WordPress draft (where the admin '
  'presses Publish); set on the approve->publish push, null until pushed.';
