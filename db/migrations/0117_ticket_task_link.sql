-- 0117 · A converted request knows which task it became.
--
-- WHAT WAS MISSING. `convert-to-task` already existed and worked: it creates the task,
-- resolves the tenant from the ticket, and posts an internal note on the request's
-- thread saying "Converted to task J-1234". `assign_task` takes an `origin` argument
-- and uses it in the activity entry and the assignee's notification - and writes it
-- NOWHERE. There is no origin column on `tasks` and never was.
--
-- So the link existed only as prose inside a thread message. Nothing could answer
-- "which requests have been converted?" or "what is the status of the work behind this
-- request?" without a human reading messages, and nothing stopped the same request
-- being converted twice - the note is easy to miss, and the button stayed live.
--
-- WHY THE POINTER LIVES ON THE TICKET. `tasks` is guarded by `tasks_guard_update()`,
-- a trigger that restricts a non-lead to changing `status` alone along legal
-- transitions. Adding a column there means either widening that guard or accepting a
-- column no one can write. The ticket is the side that HAS the fact ("this request
-- became that task"), it is written by the same lead-only route that creates the link,
-- and one request produces one task - so a single pointer on `support_tickets`
-- expresses it exactly.
--
-- ON DELETE SET NULL: deleting a task unlinks the request rather than deleting it. The
-- request is the client's, and it outlives our bookkeeping.

alter table public.support_tickets
  add column if not exists task_id uuid references public.tasks (id) on delete set null;

comment on column public.support_tickets.task_id is
  'The task this request was converted into (0117). NULL means not converted - which is '
  'what the Convert control tests, so a request cannot be converted twice. Set only by '
  'POST /tickets/{code}/convert-to-task, which is lead-only.';

create index if not exists support_tickets_task_id_idx
  on public.support_tickets (task_id)
  where task_id is not null;

-- No policy change. `support_tickets` already carries its own RLS (0024/0033): staff
-- read and write, the client reads its own through the portal view. A new column
-- inherits that, and the portal ticket view selects an explicit column list which this
-- is deliberately not added to - a client has no use for an internal job id.
