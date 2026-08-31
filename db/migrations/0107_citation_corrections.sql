-- 0107_citation_corrections.sql - what happens to a live listing when the truth changes.
--
-- TWO GAPS, ONE THEME: a citation is not finished when it goes live. It is a claim we
-- have made about a client on someone else's website, and claims go stale.
--
-- GAP 1 - THE CLIENT MOVES AND NOBODY TELLS THE LISTINGS. `business_profiles` is the
-- canonical NAP every submission is built from. Editing it silently re-points the
-- canonical record while every listing already built still carries the OLD address, and
-- nothing anywhere notices. The listings do not become wrong slowly - they become wrong
-- the moment the edit is saved - and an inconsistent citation is worse than no citation,
-- because it splits the local signal instead of reinforcing it. So an edit now writes a
-- `client_change_events` row and flips every affected LIVE listing to `drifted`, which
-- is precisely what it now is: it exists, and it no longer matches us.
--
-- WHY `drifted` AND NOT A NEW `correction_required` STATUS. The observable fact is
-- identical - listing does not match canonical, go fix it - and the operator does the
-- same thing either way. A fourth near-synonym would have to be added to the Postgres
-- enum, the Pydantic Literal and the frontend union, and would then need explaining
-- forever. The CAUSE is what differs, so the cause is recorded in
-- `verification_evidence` (`{"reason": "canonical_nap_changed", "change_event": <id>}`)
-- rather than in a status. A status should say what IS, not how it got there.
--
-- GAP 2 - WE COULD NOT SAY WHAT WE HAD REMOVED. There was no record of asking a
-- directory to take a listing down: not the request, not the method, not whether it ever
-- completed. That matters because removability is a property of the ROUTE, not a
-- universal capability - an API listing has a delete call, an account-held listing can be
-- edited, and a listing on a directory with neither is permanent unless a human argues
-- with support. A client is entitled to know which of those they are getting BEFORE we
-- build it, and afterwards to be told the truth about what we cannot undo.
--
-- Both tables are ENABLE + FORCE RLS with the house policies: staff read, leads write.
-- Neither carries a delete policy - the same discipline as `citations` (0018), so a
-- delete has to be a deliberate service_role action rather than an ordinary mistake.

-- --- 1. the change ledger -------------------------------------------------------
create table if not exists public.client_change_events (
  id                  uuid primary key default gen_random_uuid(),
  client_id           uuid not null references public.clients (id) on delete cascade,
  business_profile_id uuid references public.business_profiles (id) on delete set null,
  -- Which canonical field moved, and to what. Stored as text on purpose: this is an
  -- audit record of a value AT A MOMENT, not a foreign key into a live row that will
  -- itself keep changing. A year from now "what did we submit back then?" must still
  -- have an answer even if the profile has moved on twice more.
  field               text not null,
  old_value           text not null default '',
  new_value           text not null default '',
  occurred_at         timestamptz not null default now(),
  -- What the fan-out did: {"citations_flagged": 12, "at": "..."} - so a partial or
  -- failed propagation is visible rather than assumed. An empty object means the
  -- fan-out has not run yet, which is a DIFFERENT state from "it ran and found none".
  fanout_state        jsonb not null default '{}',
  created_at          timestamptz not null default now()
);

create index if not exists client_change_events_client_idx
  on public.client_change_events (client_id, occurred_at desc);
create index if not exists client_change_events_profile_idx
  on public.client_change_events (business_profile_id);

alter table public.client_change_events enable row level security;
alter table public.client_change_events force row level security;

create policy client_change_events_select on public.client_change_events
  for select using (public.is_staff());
create policy client_change_events_insert on public.client_change_events
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy client_change_events_update on public.client_change_events
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

-- --- 2. the removal ledger ------------------------------------------------------
create table if not exists public.citation_removals (
  id            uuid primary key default gen_random_uuid(),
  citation_id   uuid not null references public.citations (id) on delete cascade,
  requested_by  uuid references public.users (id) on delete set null,
  requested_at  timestamptz not null default now(),
  reason        text not null default '',
  -- HOW removal is even possible here, which is a property of the route:
  --   api_delete     - route A: a documented delete call (Data Axle 'D', Apple, GBP)
  --   account_edit   - we hold the account and can remove the listing ourselves
  --   support_ticket - neither: a human has to ask, and may be refused
  method        text not null
    check (method in ('api_delete', 'account_edit', 'support_ticket')),
  ticket_ref    text not null default '',
  resolved_at   timestamptz,
  -- Proof it actually came down: {"http_status": 200, "checked_at": "...", "final_url": ...}
  -- A removal is subject to the same discipline as a submission - "we asked" is not
  -- "it is gone", and only a re-check that fails to find the listing closes this out.
  evidence      jsonb not null default '{}',
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists citation_removals_citation_idx
  on public.citation_removals (citation_id);
create index if not exists citation_removals_open_idx
  on public.citation_removals (requested_at) where resolved_at is null;

create trigger citation_removals_set_updated_at
  before update on public.citation_removals
  for each row execute function public.set_updated_at();

alter table public.citation_removals enable row level security;
alter table public.citation_removals force row level security;

create policy citation_removals_select on public.citation_removals
  for select using (public.is_staff());
create policy citation_removals_insert on public.citation_removals
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy citation_removals_update on public.citation_removals
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
