-- 0074_task_deadline_requests.sql - deadline-change-request workflow.
--
-- Business rule (app-enforced 12h window, see the router; the DB only enforces
-- WHO may write): a task's ASSIGNEE may ask for a new `due_date`; the due_date
-- itself never changes automatically - only a lead's approve/reject decision
-- ever touches it (via the ordinary `tasks` UPDATE path, lead-only per 0011).
-- This migration adds ONLY the request ledger; it does not touch `public.tasks`.
--
-- THE BOUNDARY (mirrors 0011's threat model): staff hold a DB credential + a
-- verified identity and could write PostgREST-style directly, so who may insert /
-- decide a request is enforced HERE via RLS, not just FastAPI. insert = the
-- REQUESTING ASSIGNEE only (must be requesting for their OWN task); update
-- (approve/reject) = lead roles only (owner/admin/manager, mirrors `assign_tasks`).
-- No delete - a request is either pending, approved or rejected, kept forever as
-- an audit trail.

create table if not exists public.task_deadline_requests (
  id                 uuid primary key default gen_random_uuid(),
  task_id            uuid not null references public.tasks (id) on delete cascade,
  -- Snapshot of the public J-#### code (matches the badge the frontend renders;
  -- survives even if the task row's own code were ever to change).
  task_code          text not null,
  requested_by       uuid not null references public.users (id),
  requested_due_date date not null,
  reason             text,
  status             text not null default 'pending'
                        check (status in ('pending', 'approved', 'rejected')),
  decided_by         uuid references public.users (id),
  decided_at         timestamptz,
  created_at         timestamptz not null default now()
);

create index if not exists task_deadline_requests_task_id_idx
  on public.task_deadline_requests (task_id);
create index if not exists task_deadline_requests_status_idx
  on public.task_deadline_requests (status);

-- --- RLS ---------------------------------------------------------------------
alter table public.task_deadline_requests enable row level security;
alter table public.task_deadline_requests force row level security;

create policy task_deadline_requests_select on public.task_deadline_requests
  for select using (public.is_staff());

-- Insert: only the task's OWN assignee, requesting as themselves. Both halves
-- matter - `requested_by = auth.uid()` stops one staff member filing a request
-- "as" another, and the tasks subquery stops anyone requesting on a task that
-- isn't theirs (a lead changes due_date directly via PATCH /tasks, not this table).
create policy task_deadline_requests_insert on public.task_deadline_requests
  for insert
  with check (
    requested_by = auth.uid()
    and exists (
      select 1 from public.tasks t
      where t.id = task_id and t.assignee_id = auth.uid()
    )
  );

-- Update (the approve/reject decision): lead roles only.
create policy task_deadline_requests_update on public.task_deadline_requests
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
