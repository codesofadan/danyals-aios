-- 0073_ticket_reply_metadata.sql - admin free-text ticket reply metadata.
--
-- 0033 added support_tickets.reply (the latest admin reply text) but no endpoint
-- ever wrote it - it was a dead column. This adds the two audit columns needed
-- alongside it (who replied, when) so POST /tickets/{code}/reply can record a
-- real, attributable reply. Additive + backwards compatible; existing rows get
-- NULL (no reply yet).

alter table public.support_tickets
  add column if not exists replied_at timestamptz;

alter table public.support_tickets
  add column if not exists replied_by uuid references public.users(id);

comment on column public.support_tickets.reply is
  'The latest admin free-text reply to this ticket/request, written by POST /tickets/{code}/reply.';
comment on column public.support_tickets.replied_at is
  'When the latest reply was sent.';
comment on column public.support_tickets.replied_by is
  'Which staff user sent the latest reply.';
