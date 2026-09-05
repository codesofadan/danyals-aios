-- 0127 - TEAM REQUESTS: a staff member asking the agency's leads for something.
--
-- The client portal has had a request channel since 0024; the TEAM portal has had
-- none. A member who needed an access grant, a tool, a deadline moved or a decision
-- had no route inside the product and fell back to chat - so the ask left no record,
-- no owner and no status, and "did anyone action that?" had no answer.
--
-- REUSES `support_tickets` rather than adding a second requests table. The two are the
-- same object with a different origin: a subject, a body, a status, a reply and a
-- conversation. A parallel table would need its own status vocabulary, its own reply
-- path and its own thread, and the admin surfaces would then have to merge two ledgers
-- that can disagree about what happened to a request.
--
-- THE DISCRIMINATOR IS `client_id IS NULL`, not a new channel value.
--
-- A new `ticket_channel` value was the first instinct and is the wrong trade here. It
-- needs ownership of the type to ALTER, and Postgres forbids USING a value in the
-- transaction that adds it (0045's header records the same rule) - so the view below
-- could not reference it in this file, and a migration runner that wraps a file in one
-- transaction would fail outright. Against that: a client request ALWAYS pins
-- `client_id` from the authenticated client (services/client_requests.py, "pinned
-- server-side; never from the body"), so a NULL client is already an exact,
-- structural statement that no client raised this. Measured before relying on it:
-- 0 of the existing rows have a NULL client_id.
--
-- `created_by` alone would NOT do: a client portal user and a staff user are both rows
-- in `users`, so telling them apart would mean joining to a role on every read, and a
-- person's role changing would silently reclassify their old requests.

-- The member's own requests, for the team portal to read under RLS.
--
-- Scoped to `created_by = auth.uid()` AND to client-less rows, so this view can never
-- return another member's request and never leaks a CLIENT's request into the team
-- portal. Both halves are enforced here, at the view - not in whatever query happens
-- to be written above it.
create or replace view public.team_requests
with (security_invoker = true) as
  select id, code, subject, detail, kind, status, priority,
         opened_at, created_at, updated_at, reply, replied_at
    from public.support_tickets
   where client_id is null
     and created_by = auth.uid();

comment on view public.team_requests is
  'A staff member''s OWN team-origin requests: support_tickets with no client_id.
   security_invoker so the caller''s RLS applies; filtered to auth.uid() so one member
   can never read another''s, and to client_id is null so a client request never
   appears in the team portal.';

grant select on public.team_requests to authenticated;
