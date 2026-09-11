-- 0133_backlink_evidence.sql - backlink VERIFICATION evidence (off-page redesign
-- Phase 5, plan §7).
--
-- WHAT WAS BROKEN. `public.backlinks` (0018) stored a referring DOMAIN and two scores
-- and nothing else: not the page the link lives on, not the URL it points at. So the
-- platform could never look for itself - "new" meant "DataForSEO said so once", and a
-- link that quietly vanished stayed on the client's board until the next paid pull
-- happened to notice. Verification needs the two URLs and a place to record what a
-- fetch actually found.
--
-- THE LIVENESS VOCABULARY (text + CHECK per the 0106 pattern - never a new Postgres
-- enum, 55P04). `liveness` is OUR OWN observation, orthogonal to the provider-derived
-- monitoring `status` (new|lost|toxic):
--
--   'unchecked'  never fetched by us (every pre-0133 row; the ingest default).
--   'live'       we fetched source_url and OUR link to target_url was on the page.
--   'missing'    we fetched the page and the link was NOT there - a real defect.
--   'unknown'    we could not look (network, 403, non-public host). NEVER shown as a
--                pass: "could not check" must stay distinguishable from "checked and
--                fine", or an outage silently turns into a green board.
--
-- `check_evidence` is the receipt: {http_status, detail, checked_at} - stamped
-- server-side by the verify worker, never provider-supplied. `next_check_at` drives
-- the sweep (live -> +30d; missing -> +7d, so a loss is CONFIRMED by a second look
-- before the row's monitoring status may flip to 'lost').
--
-- Additive + idempotent. `backlinks` already has ENABLE+FORCE RLS (0018); new columns
-- inherit the table's existing policies, so no policy work is needed here.

alter table public.backlinks
  add column if not exists source_url      text  not null default '',
  add column if not exists target_url      text  not null default '',
  add column if not exists link_rel        text  not null default '',
  add column if not exists liveness        text  not null default 'unchecked',
  add column if not exists last_checked_at timestamptz,
  add column if not exists next_check_at   timestamptz,
  add column if not exists check_evidence  jsonb not null default '{}';

do $$ begin
  if not exists (
    select 1 from pg_constraint where conname = 'backlinks_liveness_check'
  ) then
    alter table public.backlinks
      add constraint backlinks_liveness_check
      check (liveness in ('unchecked', 'live', 'missing', 'unknown'));
  end if;
end $$;

-- The verify sweep's due set: rows with a scheduled re-check. Partial, because the
-- overwhelming majority of rows at any moment are either unchecked (next_check_at is
-- null - found by the liveness predicate, not this index) or not yet due.
create index if not exists backlinks_due_check_idx
  on public.backlinks (next_check_at)
  where next_check_at is not null;
