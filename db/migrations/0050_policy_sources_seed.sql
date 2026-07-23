-- 0050_policy_sources_seed.sql - seeds public.policy_sources (0019) with the real
-- curated Google policy/algorithm watch list the LIVE change-detection WATCHER polls
-- (workers/tasks/policy.py). Idempotent (mirror 0046_directories_seed.sql style).
--
-- policy_sources has NO natural unique constraint, so we FIRST add a unique index on
-- url (the natural key - one row per monitored URL) and then insert ON CONFLICT (url)
-- DO NOTHING, so re-running this file after an edit never duplicates a source.
-- Editing a source's name/kind/icon going forward is a NEW migration that UPDATEs by
-- url, not a hand-edit of this seed.
--
-- last_hash is left at its '' default: the watcher captures each source's baseline
-- content hash on its FIRST poll (status stays 'ok', no change_event); only a LATER
-- diff flips status to 'change' and appends a change_event. last_checked stays NULL
-- until that first poll. icon is a material-symbols name (contract `icon`).

create unique index if not exists policy_sources_url_key on public.policy_sources (url);

insert into public.policy_sources (name, kind, url, icon)
values
  ('Google Search Central Blog', 'blog',
   'https://developers.google.com/search/blog/rss', 'rss_feed'),
  ('Search Status Dashboard', 'status',
   'https://status.search.google.com/incidents.json', 'monitor_heart'),
  ('Search Essentials (Webmaster Guidelines)', 'docs',
   'https://developers.google.com/search/docs/essentials', 'menu_book'),
  ('Spam Policies', 'policy',
   'https://developers.google.com/search/docs/essentials/spam-policies', 'gavel'),
  ('Ranking Systems Guide (core updates)', 'docs',
   'https://developers.google.com/search/docs/appearance/ranking-systems-guide', 'trending_up'),
  ('Helpful Content Guidance', 'docs',
   'https://developers.google.com/search/docs/fundamentals/creating-helpful-content', 'verified'),
  ('Structured Data Policies', 'technical',
   'https://developers.google.com/search/docs/appearance/structured-data/sd-policies', 'data_object'),
  ('Search Central Updates', 'updates',
   'https://developers.google.com/search/updates', 'update')
on conflict (url) do nothing;
