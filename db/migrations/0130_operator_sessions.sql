-- 0130_operator_sessions.sql - session-based citation building (off-page redesign
-- Phase 4, plan §3/§7).
--
-- THE UNIT OF WORK CHANGES. The 0110 queue hands an operator ONE item at a time; a
-- session hands them a BATCH (default 10, capped 25) so the extension can open every
-- tab, autofill each form where a spec is earned, and the person walks the row of tabs
-- submitting. Two tables:
--
--   operator_sessions       one operator working one client's citations (or, later,
--                           web2 placements - `kind` is generalized on day one so 0136
--                           needs no schema change). State machine (plan §3):
--                           active <-> paused, active -> completed (all batches
--                           terminal), active -> abandoned (explicit close or
--                           lease-reaped). ONE active session per operator - enforced
--                           by a partial unique index, which is also what the ad-hoc
--                           claim endpoint queries to refuse 409.
--
--   operator_session_tasks  one citation (or web2 property) inside a session, with a
--                           batch number and a UI-TELEMETRY state. `ui_state` carries
--                           ZERO authority: the forward, non-terminal half
--                           (pending -> released -> opened -> form_detected -> filled
--                           -> awaiting_submit) is extension-reported; the terminal
--                           values {submitted, skipped, deferred, blocked} are written
--                           ONLY server-side by the probe-verified complete / blocked /
--                           skip / defer handlers. Evidence stays on the CITATION row
--                           (live_url / verification_*); a session task never asserts
--                           liveness.
--
-- KIND <-> FK INTEGRITY, the simplest honest mechanism: the task row carries a
-- DENORMALIZED `kind` column, a CHECK ties that kind to exactly one of
-- citation_id/web2_id, and a BEFORE INSERT trigger copies the kind from the parent
-- session so the denormalization cannot lie (an inserted task always matches its
-- session's kind, whatever the caller sent). A pure two-table CHECK cannot see the
-- parent row; a trigger that only COPIES one column is smaller than one that
-- re-validates everything.
--
-- Text + CHECK closed vocabularies throughout (0106 pattern - never a new Postgres
-- enum). Additive + idempotent. New tables get ENABLE+FORCE RLS with the standard
-- staff-read / lead-write shape.

begin;

-- --------------------------------------------------------------------------- --
-- The session.
-- --------------------------------------------------------------------------- --
create table if not exists public.operator_sessions (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid not null references public.clients (id) on delete cascade,
  -- Snapshotted display name, same rule as citations.client_name: responses carry
  -- the name, never the internal id.
  client_name   text not null default '',
  operator_id   uuid not null references public.users (id) on delete cascade,
  status        text not null default 'active'
                  check (status in ('active', 'paused', 'completed', 'abandoned')),
  kind          text not null default 'citation'
                  check (kind in ('citation', 'web2_placement')),
  batch_size    int  not null default 10 check (batch_size between 1 and 25),
  current_batch int  not null default 1,
  -- What the operator asked for ({fromGaps: {tiers, limit}} or {citationIds}) - the
  -- reproducibility record, never a source of truth for any task row.
  params        jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now(),
  -- Bumped by every heartbeat; a session whose updated_at goes stale past the lease
  -- window is lease-reaped to 'abandoned' (lazily, on the next read/create - no cron).
  updated_at    timestamptz not null default now(),
  closed_at     timestamptz
);

-- ONE ACTIVE SESSION PER OPERATOR. The partial unique index is the enforcement AND
-- the query the ad-hoc claim refusal reads: while a caller holds an active session,
-- POST /queue/claim answers 409 (work through the session instead).
create unique index if not exists operator_sessions_one_active_per_operator
  on public.operator_sessions (operator_id)
  where status = 'active';

create index if not exists operator_sessions_client_idx
  on public.operator_sessions (client_id, created_at desc);

alter table public.operator_sessions enable row level security;
alter table public.operator_sessions force row level security;

drop policy if exists operator_sessions_select on public.operator_sessions;
create policy operator_sessions_select on public.operator_sessions
  for select using (public.is_staff());
drop policy if exists operator_sessions_insert on public.operator_sessions;
create policy operator_sessions_insert on public.operator_sessions
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
drop policy if exists operator_sessions_update on public.operator_sessions;
create policy operator_sessions_update on public.operator_sessions
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
-- No delete policy: a closed session is the audit record of a shift that happened;
-- under FORCE RLS a policy-less DELETE matches zero rows.

comment on table public.operator_sessions is
  'One operator working one client''s citations (or web2 placements) in batches '
  'through the extension (0130). One ACTIVE session per operator (partial unique '
  'index). Claims ride the existing citations.claimed_by lease columns; evidence '
  'stays on the citation row - a session is orchestration, never proof.';

-- --------------------------------------------------------------------------- --
-- The tasks.
-- --------------------------------------------------------------------------- --
create table if not exists public.operator_session_tasks (
  id          uuid primary key default gen_random_uuid(),
  session_id  uuid not null references public.operator_sessions (id) on delete cascade,
  -- DENORMALIZED from the session (trigger below); the CHECK ties it to exactly one FK.
  kind        text not null default 'citation'
                check (kind in ('citation', 'web2_placement')),
  citation_id uuid references public.citations (id) on delete cascade,
  web2_id     uuid references public.web2_properties (id) on delete cascade,
  batch_no    int  not null default 1 check (batch_no >= 1),
  position    int  not null default 0,
  -- UI telemetry, zero authority. Forward non-terminal half is extension-reported;
  -- terminal values are server-written only.
  ui_state    text not null default 'pending'
                check (ui_state in (
                  'pending', 'released', 'opened', 'form_detected', 'filled',
                  'awaiting_submit', 'submitted', 'skipped', 'deferred', 'blocked')),
  ui_state_at timestamptz,
  telemetry   jsonb not null default '{}'::jsonb,
  -- Exactly one target, matching the kind. With the trigger keeping `kind` equal to
  -- the session's, this is the whole cross-table rule expressed as one local CHECK.
  constraint operator_session_tasks_one_target check (
    (kind = 'citation'       and citation_id is not null and web2_id is null) or
    (kind = 'web2_placement' and web2_id is not null and citation_id is null)
  )
);

-- A citation (or property) appears at most once per session.
create unique index if not exists operator_session_tasks_citation_uidx
  on public.operator_session_tasks (session_id, citation_id)
  where citation_id is not null;
create unique index if not exists operator_session_tasks_web2_uidx
  on public.operator_session_tasks (session_id, web2_id)
  where web2_id is not null;

create index if not exists operator_session_tasks_session_batch_idx
  on public.operator_session_tasks (session_id, batch_no, position);

-- The kind is COPIED from the parent session on insert, so a task can never claim a
-- kind its session does not have - the CHECK above then guarantees the right FK is
-- set. Insert-only: session kind is immutable in practice (no update path exists),
-- and tasks never migrate between sessions (session_id has no update either).
create or replace function public.operator_session_tasks_stamp_kind()
returns trigger
language plpgsql
as $$
begin
  select s.kind into new.kind
  from public.operator_sessions s
  where s.id = new.session_id;
  if new.kind is null then
    raise exception 'operator_session_tasks: unknown session %', new.session_id;
  end if;
  return new;
end;
$$;

drop trigger if exists operator_session_tasks_kind_trg on public.operator_session_tasks;
create trigger operator_session_tasks_kind_trg
  before insert on public.operator_session_tasks
  for each row execute function public.operator_session_tasks_stamp_kind();

alter table public.operator_session_tasks enable row level security;
alter table public.operator_session_tasks force row level security;

drop policy if exists operator_session_tasks_select on public.operator_session_tasks;
create policy operator_session_tasks_select on public.operator_session_tasks
  for select using (public.is_staff());
drop policy if exists operator_session_tasks_insert on public.operator_session_tasks;
create policy operator_session_tasks_insert on public.operator_session_tasks
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
drop policy if exists operator_session_tasks_update on public.operator_session_tasks;
create policy operator_session_tasks_update on public.operator_session_tasks
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

comment on table public.operator_session_tasks is
  'One citation (or web2 property) inside an operator session (0130), with a batch '
  'number and a zero-authority ui_state: the forward non-terminal half is extension '
  'telemetry; terminal values are written only by the server''s complete/blocked/'
  'skip/defer handlers. kind is trigger-copied from the session; the CHECK ties it '
  'to exactly one of citation_id/web2_id.';

commit;
