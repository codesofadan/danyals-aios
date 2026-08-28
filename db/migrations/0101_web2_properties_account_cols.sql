-- 0101_web2_properties_account_cols.sql - attribute every Web 2.0 placement to the
-- ACCOUNT that published it (R2-02 of docs/research/R2-web2-safety.md).
--
-- Purely ADDITIVE: two nullable/defaulted columns on public.web2_properties. No
-- change to the web2_status enum, no change to any policy, so the RLS gate and the
-- job-contract status mapping (app/jobs/status.py) are untouched.
--
-- WHY. Two later controls key off "which account did this go out on", and neither is
-- implementable without it:
--   * R2-10 scope S2 - the CROSS-CLIENT similarity scope. The whole reason a shared
--     house account is dangerous is that many clients' articles land on ONE account;
--     detecting templating across them requires grouping by account_id, which does
--     not exist as a fact anywhere today.
--   * R2-13's per-house-account publish caps (per day, per 30 days, max properties).
--
-- account_id is deliberately left NULLABLE here. Existing rows predate accounts and
-- cannot be attributed until the one-shot reconciliation (app/cli/web2_migrate_house.py,
-- R2-07) groups the current vault rows by secret hash and decides which are shared. A
-- later migration tightens this to NOT NULL once no nulls remain - tightening before
-- the backfill would simply fail to apply on any real database.
--
-- shared_origin records the OUTCOME of that reconciliation: true means "this was
-- published through a credential we now know was shared across clients". It is the
-- flag the freeze rule reads - a shared-origin property on a platform since tiered
-- per_client stops receiving new publishes, because continuing to post to it keeps
-- extending a correlation we can no longer defend. The already-published article is
-- left in place on purpose: deleting a live article is a bigger, stranger signal than
-- letting it sit (R2-07, and risk #4 in that record).

alter table public.web2_properties
  add column if not exists account_id uuid references public.web2_accounts (id);

alter table public.web2_properties
  add column if not exists shared_origin boolean not null default false;

create index if not exists web2_properties_account_id_idx
  on public.web2_properties (account_id);

-- Partial: the freeze/reporting paths only ever ask for the shared ones, and they are
-- expected to be a small minority once per-client accounts are the norm.
create index if not exists web2_properties_shared_origin_idx
  on public.web2_properties (shared_origin) where shared_origin;

comment on column public.web2_properties.account_id is
  'The web2_accounts row this placement was published through. Nullable only until the '
  'R2-07 reconciliation backfills historic rows; required for the cross-client '
  'similarity scope (R2-10 S2) and the per-house-account publish caps (R2-13).';

comment on column public.web2_properties.shared_origin is
  'True when this placement went out on a credential later found to be shared across '
  'clients. Such a property is FROZEN (no further publishing) on any platform now '
  'tiered per_client; the existing article is deliberately left live (R2-07).';
