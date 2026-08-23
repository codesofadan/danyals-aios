-- 0079_user_suspension.sql - the audit trail for an offboarding.
--
-- Additive and nullable only: no existing row changes, no default is written,
-- and nothing here can fail on a populated table. Requires 0078 (the 'suspended'
-- enum label) to be applied and committed first.
--
-- WHY THESE COLUMNS
-- -----------------
-- `users.status = 'suspended'` alone answers "can this person log in". It does
-- not answer the questions actually asked after an offboarding: WHEN did their
-- access end, WHO ended it, and WHY. Those matter for a dispute, for an incident
-- timeline, and for the "a person is provisioned, works, and is offboarded"
-- acceptance bar in the master plan's Definition of Done.
--
-- They are NOT a substitute for the activity log - the suspend/reactivate
-- endpoints write there too. They are the denormalised current state, so the
-- roster can show "suspended 3 days ago by X" without scanning an append-only
-- feed.

alter table public.users
  add column if not exists suspended_at     timestamptz,
  add column if not exists suspended_by     uuid references public.users (id) on delete set null,
  add column if not exists suspended_reason text not null default '';

comment on column public.users.suspended_at is
  'When access was last revoked. NULL for a user who has never been suspended. '
  'Cleared on reactivation.';
comment on column public.users.suspended_by is
  'The user who performed the suspension. ON DELETE SET NULL so removing an '
  'administrator later never erases the fact that a suspension happened.';
comment on column public.users.suspended_reason is
  'Free text captured at suspend time. Empty string when never suspended.';

-- Find the suspended roster without scanning every user. Partial: the index only
-- holds the rows that are actually suspended, which is the small set.
create index if not exists users_suspended_idx
  on public.users (suspended_at desc)
  where status = 'suspended';
