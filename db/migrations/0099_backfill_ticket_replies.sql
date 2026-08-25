-- 0099_backfill_ticket_replies.sql - carry the existing one-shot replies into threads.
--
-- Before 0098 a support ticket held its answer in a single `support_tickets.reply`
-- column: the agency could reply once, and the conversation had nowhere to go. Those
-- replies are real messages a client has already been sent and can currently read in
-- the portal, so they must survive the move to threads - otherwise shipping the new
-- surface would silently erase every answer the agency has given.
--
-- The `reply` column is deliberately LEFT IN PLACE and still populated by
-- `POST /tickets/{code}/reply`. Dropping it in the same migration that introduces its
-- replacement would mean a rollback of the application loses data. It is retired in a
-- later, separate change once the portal reads only threads.
--
-- IDEMPOTENT: re-running creates nothing new. The thread insert is guarded by the
-- (entity_type, entity_id) unique constraint, and the message insert skips any thread
-- that already carries a backfilled message.

-- One thread per ticket that has a reply worth carrying.
insert into public.threads (entity_type, entity_id, client_id)
select 'ticket', s.id, s.client_id
  from public.support_tickets s
 where s.reply is not null
   and length(btrim(s.reply)) > 0
on conflict (entity_type, entity_id) do nothing;

-- The reply itself, as the agency's first client-visible message.
--
-- `replied_at` is used when 0075 recorded one, falling back to the ticket's own
-- updated_at: a backfilled message must not claim to have been written now, or every
-- historical answer would appear in the portal as though it had just arrived.
insert into public.thread_messages
  (thread_id, author_id, author_name, author_kind, body, visibility, created_at)
select t.id,
       s.replied_by,
       coalesce(nullif(btrim(u.name), ''), 'Support'),
       'staff',
       btrim(s.reply),
       'client_visible',
       coalesce(s.replied_at, s.updated_at, now())
  from public.support_tickets s
  join public.threads t
    on t.entity_type = 'ticket' and t.entity_id = s.id
  left join public.users u on u.id = s.replied_by
 where s.reply is not null
   and length(btrim(s.reply)) > 0
   -- Skip a ticket whose reply is already in its thread (re-run safety).
   and not exists (
     select 1 from public.thread_messages m
      where m.thread_id = t.id and m.body = btrim(s.reply)
   );
