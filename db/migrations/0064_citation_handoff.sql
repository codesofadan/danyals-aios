-- 0064_citation_handoff.sql
-- Citation HANDOFF queue: the citation bot creates a directory account + fills the
-- listing automatically, but some directories can't be auto-published (a captcha the
-- last step re-checks, a JS category widget, a paid-claim). Those land as
-- `ready_for_human`: the account exists + the form is prepared, and an operator
-- finishes with one click in the browser at `handoff_url`.
--
-- Additive + idempotent. The enum value is only ADDED here (never USED in this same
-- migration/transaction) so PG's "new enum value not usable in the adding txn" rule
-- (55P04) is not tripped — runtime writes/seeds use it after this commits.

alter type public.citation_submit_status add value if not exists 'ready_for_human';

-- Where a human finishes the listing (the directory's add/edit page for the account
-- we already created). Empty for every non-handoff row.
alter table public.citations
  add column if not exists handoff_url text not null default '';
