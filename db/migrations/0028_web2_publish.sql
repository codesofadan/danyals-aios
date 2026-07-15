-- 0026_web2_publish.sql - Part 7 Module 03 (Off-page) / 7B-3: the Web 2.0 PUBLISH
-- pipeline's persistence. 0018 shipped web2_properties as a READ-ONLY ledger (the
-- publish pipeline was "a later chunk"); this migration ADDITIVELY extends that same
-- table with the columns the plan -> write -> human-review-gate -> publish -> verify
-- -> track state machine needs. No new table, no new RLS policy: the existing
-- web2_properties policies (0018) already gate it - any staff READ; only leads
-- (owner/admin/manager) INSERT/UPDATE; clients excluded by is_staff(); the worker's
-- publish/track path runs on service_role (BYPASSRLS).
--
-- The frontend contract (frontend/lib/offpage.ts Web2Property) is UNCHANGED - these
-- are internal pipeline columns that never leak into Web2PropertyResponse (its 7 keys
-- are pinned by the contract-lock test). A row is surfaced to the UI exactly as before
-- (platform / post_url / anchor / verified / published), regardless of its status.
--
-- State machine (status):
--   draft        - just planned; the write worker will draft the article.
--   needs_review - a drafted article is HELD for a human lead to approve (the quality
--                  gate; the article is NEVER auto-published). A degraded/keyless draft
--                  also parks here so the gap is visible, never silently published.
--   publishing   - a lead approved; the publish worker is (or will be) pushing it live.
--   published    - live on the Web 2.0 property (post_url + published_at set; verified
--                  reflects the live/indexable check - 'verified' or still 'pending').
--   failed       - the publish attempt errored (error holds the reason); never stuck.
--   rejected     - a lead rejected the draft at the review gate.

-- --- Enum (idempotent guard; enums have no "create ... if not exists") ---------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'web2_status') then
    create type public.web2_status as enum
      ('draft', 'needs_review', 'publishing', 'published', 'failed', 'rejected');
  end if;
end $$;

-- --- Additive pipeline columns on the existing ledger -------------------------
alter table public.web2_properties
  -- The review/publish state machine (see header). Existing rows default to
  -- 'published' so a pre-pipeline placement (post_url already set) is not mistaken
  -- for an un-drafted plan; new plan rows are inserted explicitly as 'draft'.
  add column if not exists status       public.web2_status not null default 'published',
  -- What the branded article is about + how it is built (mirrors content_jobs).
  add column if not exists topic        text not null default '',
  add column if not exists page_type    text not null default 'blog',
  add column if not exists framework    text not null default 'Auto',
  -- The client page this property links BACK to (the anchor points here). This is
  -- the whole point of a Web 2.0 property: an on-topic branded post carrying one
  -- editorial backlink to target_url.
  add column if not exists target_url   text not null default '',
  -- The drafted article, persisted between the write stage and the (post-approval)
  -- publish stage so the publish worker republishes the SAME approved copy.
  add column if not exists body_md      text not null default '',
  -- The provider-side post id (WordPress.com / Blogger / Tumblr), recorded once so a
  -- retried publish UPDATES in place instead of spawning a duplicate (idempotency).
  add column if not exists external_id  text,
  -- Last publish error (server-side only; capped by the worker).
  add column if not exists error        text not null default '';

-- The write/publish workers claim rows by status; index it (partial-free: the set
-- is small and status is low-cardinality, a plain btree is enough).
create index if not exists web2_properties_status_idx on public.web2_properties (status);
