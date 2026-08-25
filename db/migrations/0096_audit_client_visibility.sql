-- 0096_audit_client_visibility.sql - an audit reaches a client only when someone
-- decides it should.
--
-- WHAT WAS TRUE BEFORE THIS. `portal_audits` (0010) filtered on ONE condition:
--
--     where client_id = public.current_client_id()
--
-- So every audit linked to a client was ALREADY visible in that client's portal,
-- the moment it was created - including a queued run, a failed run, and an
-- exploratory run an operator fired to see what a prospect's site looked like.
-- There was no step at which anyone chose to show it. That is a disclosure
-- decision being made by a foreign key.
--
-- `visible_to_client` makes it a decision. Default FALSE: a new audit is internal
-- until someone says otherwise, which is the safe direction for a control whose
-- failure mode is "the client saw something we had not reviewed".
--
-- EXISTING ROWS ARE BACKFILLED TRUE, deliberately and in the opposite direction.
-- Those audits are visible in client portals right now. Defaulting them to false
-- would silently REMOVE reports clients can currently open - a regression they
-- would notice and we would not. The backfill preserves what is already true; the
-- default governs what happens next.

alter table public.audits
  add column if not exists visible_to_client boolean not null default false;

-- Preserve today's behaviour for everything that already exists. Runs once: the
-- column does not exist before this migration, so there is nothing to re-apply to.
do $$
begin
  if not exists (
    select 1 from pg_description d
    join pg_class c on c.oid = d.objoid
    where c.relname = 'audits' and d.description like 'audit-client-visibility-backfilled%'
  ) then
    update public.audits set visible_to_client = true where client_id is not null;
    comment on table public.audits is 'audit-client-visibility-backfilled 0096';
  end if;
end $$;

comment on column public.audits.visible_to_client is
  'Operator opt-in: does this audit appear in the client portal? Default false.';

-- The view gains the second condition. Tenancy is still the FIRST filter - this
-- narrows what a client sees, it never widens it.
create or replace view public.portal_audits
  with (security_barrier = true) as
  select
    id,
    client_id,
    url,
    types,
    tier,
    status,
    score,
    scores,
    runtime_seconds,
    created_at,
    started_at,
    finished_at,
    (pdf_path is not null)  as has_pdf,
    (json_path is not null) as has_json
  from public.audits
  where client_id = public.current_client_id()
    and visible_to_client;

comment on view public.portal_audits is
  'Client-safe view of public.audits: own tenant AND explicitly shared. No cost/error/paths.';
