-- 0033_support_tickets_portal.sql - Part 8 (Client Portal): client requests over
-- the existing support_tickets ledger.
--
-- The portal "Requests" surface (frontend ClientRequest in lib/client.ts) is a
-- client-raised support ticket with a request KIND (Report/Access/Support/Feature/
-- Billing), a free-text detail, and the latest admin reply. Rather than a parallel
-- table, these extend the 0024 support_tickets ledger with three nullable/defaulted
-- columns so a client request and a staff-logged ticket share one triage queue.
--
-- The staff TicketResponse (lib/data.ts Ticket) is a fixed 7-key shape and does
-- NOT read these columns, so it is unaffected. Clients are excluded by is_staff()
-- (0024) - no base-table select policy - and read their OWN requests ONLY through
-- the security-barrier portal_requests view, which maps the internal `pending`
-- status to the client-facing `in_review` and filters to rows that carry a `kind`
-- (a client request, not a purely staff-logged ticket). The insert path stays the
-- 0024 lead/service_role write (create_client_request pins client_id server-side).

-- --- Enum (idempotent guard) -------------------------------------------------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'request_kind') then
    create type public.request_kind as enum
      ('Report', 'Access', 'Support', 'Feature', 'Billing');
  end if;
end $$;

-- --- Columns (all additive + backwards compatible) ---------------------------
-- kind: NULL for a purely staff-logged ticket, set for a client request.
alter table public.support_tickets
  add column if not exists kind public.request_kind;
-- detail: the client's free-text body (defaulted so existing rows are valid).
alter table public.support_tickets
  add column if not exists detail text not null default '';
-- reply: the latest admin reply, NULL until a staffer responds.
alter table public.support_tickets
  add column if not exists reply text;

-- --- Client read surface = the security-barrier view -------------------------
-- The caller's own requests only (self-filtered + kind is not null), with the
-- internal `pending` lifecycle state mapped to the client-facing `in_review`
-- (matching RequestStatus in lib/client.ts). No client_id / created_by / internal
-- UUID id ever surfaces - `code` (T-####) is the public id.
create or replace view public.portal_requests
  with (security_barrier = true) as
  select
    code,
    kind,
    subject,
    detail,
    case status when 'pending' then 'in_review' else status::text end as status,
    reply,
    opened_at
  from public.support_tickets
  where client_id = public.current_client_id()
    and kind is not null;

comment on view public.portal_requests is
  'Client-safe view of the caller''s own support_tickets requests (kind set), '
  'self-filtered to current_client_id(); maps pending -> in_review.';

grant select on public.portal_requests to authenticated, anon;
