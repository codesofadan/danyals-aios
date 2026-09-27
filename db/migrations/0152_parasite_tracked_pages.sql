-- 0152_parasite_tracked_pages.sql - make a Parasite Poster page TRACKABLE (M05 §6, A11).
--
-- A11: "A Parasite Poster page is published, tracked in M07, and its ranking appears in
-- the client report." The tracking half could not work, and the reason is a uniqueness
-- key rather than a missing feature:
--
--     tracked_keywords_client_id_normalized_keyword_engine_device_key
--       UNIQUE (client_id, normalized_keyword, engine, device, location, language)
--
-- `add_keywords` inserts `on conflict do nothing`. So subscribing a parasite page for
-- "cctv drain survey" when the client ALREADY tracks that term for their own site is
-- silently skipped - no row, no error, no ranking, and a deliverable that reports itself
-- as tracked while nothing measures it.
--
-- AND THE COLLISION IS THE NORMAL CASE, not an edge one. §6 says a parasite page exists
-- "for terms the client's own site cannot yet rank for" - which are exactly the terms an
-- SEO agency already has in the rank tracker. The feature collides with itself by design.
--
-- THE FIX IS A DISCRIMINATOR, NOT A WORKAROUND. The parasite page's ranking is a
-- genuinely DIFFERENT measurement from the client's own page ranking for the same term:
-- one asks "where does leedsdrainage.co.uk rank", the other "where does our page on
-- telegra.ph rank". Comparing the two is the entire point of the tactic, so both must be
-- trackable at once. `hosted_url` is that discriminator: empty for ordinary tracking (the
-- client's own site), set to the parasite page's URL for a hosted placement.
--
-- WHY NOT REUSE `target_url`. It is not in the uniqueness key and is freely editable, so
-- two rows differing only by target_url would still collide. Widening the key on
-- `hosted_url` keeps ordinary rows behaving EXACTLY as before ('' for all of them, so the
-- key is unchanged for every existing row) while making hosted pages independently
-- trackable.

begin;

alter table public.tracked_keywords
  add column if not exists hosted_url text not null default '';

-- Rebuild the uniqueness key with the discriminator. Ordinary rows all carry '' so their
-- key is byte-for-byte what it was, and no existing row can newly conflict.
--
-- It is a CONSTRAINT, not a bare index, so it is dropped as one - `drop index` on it
-- fails with "constraint ... requires it". Worth stating because the replacement is a
-- plain unique INDEX: `add_keywords` infers its ON CONFLICT target from the column list,
-- which an index satisfies, and an index is what the later `nulls not distinct` clause
-- needs to be expressible.
alter table public.tracked_keywords
  drop constraint if exists tracked_keywords_client_id_normalized_keyword_engine_device_key;

create unique index if not exists tracked_keywords_subscription_uq
  on public.tracked_keywords
     (client_id, normalized_keyword, engine, device, location, language, hosted_url)
  nulls not distinct;

create index if not exists tracked_keywords_hosted_idx
  on public.tracked_keywords (client_id) where hosted_url <> '';

comment on column public.tracked_keywords.hosted_url is
  'The PARASITE page this subscription measures (M05 §6 / A11), or '''' for ordinary '
  'tracking of the client''s own site. Part of the uniqueness key: a hosted page and the '
  'client''s own site can be tracked for the SAME term at once, which is the comparison '
  'the tactic exists to produce - without it the hosted page silently collided with the '
  'client''s existing subscription and was never measured.';

commit;
