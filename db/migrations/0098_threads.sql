-- 0098_threads.sql - the discussion primitive: threaded comments on work.
--
-- WHY THIS EXISTS. Across the ninety-seven migrations before this one there is no
-- comment, message, thread, note or conversation table anywhere. The product
-- coordinates an agency, its delivery team and its clients, and none of them could
-- talk to each other inside it:
--
--   * a TASK had no comment field. The assignee could advance its status or file a
--     deadline-change request, and had no way to ask a question about the work;
--   * a TICKET carried a single `reply` column - one reply, after which the
--     conversation had nowhere to go;
--   * TEAM <-> CLIENT was a complete void: the person doing the work could not see
--     the client request that caused it.
--
-- ONE primitive serves all of them, rather than a comment table per entity: the
-- thread is polymorphic over (entity_type, entity_id).
--
-- THE LOAD-BEARING COLUMN IS `visibility`. A thread on a client's request is read by
-- BOTH the agency and the client, so the team must be able to talk internally on the
-- same thread the client can see part of. Get this wrong and the feature is not
-- merely broken, it leaks the agency's internal discussion of a client TO that
-- client. Everything below is arranged around making that impossible.
--
-- THREAT MODEL (mirrors 0010/0011/0024): any authenticated principal may reach the
-- database directly with a leaked credential, so RLS is the boundary - not FastAPI.
-- Following 0010's doctrine exactly: clients hold NO select policy on either base
-- table. Their entire read surface is the two security-barrier views at the bottom,
-- which filter by current_client_id() AND visibility = 'client_visible' before any
-- user-supplied predicate can run.

-- --- Enums (idempotent; enums have no "create ... if not exists") -------------
do $$ begin
  -- The entities a thread can hang off. Deliberately a closed set: a new value is a
  -- deliberate migration, not something a caller can invent, because each value
  -- implies a tenancy rule the views below have to be taught.
  if not exists (select 1 from pg_type where typname = 'thread_entity') then
    create type public.thread_entity as enum ('task', 'ticket');
  end if;
  -- 'internal'       - agency-only. NEVER leaves the staff surface.
  -- 'client_visible' - part of the conversation with the client.
  if not exists (select 1 from pg_type where typname = 'message_visibility') then
    create type public.message_visibility as enum ('internal', 'client_visible');
  end if;
end $$;

-- --- threads -----------------------------------------------------------------
create table if not exists public.threads (
  id           uuid primary key default gen_random_uuid(),
  entity_type  public.thread_entity not null,
  -- Polymorphic, so no FK. The owning row's existence is enforced by the service
  -- that creates the thread (it has already read the entity to authorize the call);
  -- a dangling thread is inert - nothing renders a thread whose entity is gone.
  entity_id    uuid not null,
  -- DENORMALIZED tenant. The client-facing views must answer "is this thread yours"
  -- without reading `tasks` or `support_tickets`, which a client cannot select from
  -- at all. Copying the tenant here keeps the filter a single indexed equality
  -- instead of a cross-table subquery into a table the principal cannot see.
  -- NULL means an internal thread with no client (a task on no client's behalf).
  client_id    uuid references public.clients (id) on delete set null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  -- One thread per entity: "the discussion on task J-1042" is a single place.
  constraint threads_entity_uniq unique (entity_type, entity_id)
);

create index if not exists threads_client_id_idx on public.threads (client_id);
create index if not exists threads_entity_idx    on public.threads (entity_type, entity_id);

create trigger threads_set_updated_at
  before update on public.threads
  for each row execute function public.set_updated_at();

-- --- thread_messages ---------------------------------------------------------
create table if not exists public.thread_messages (
  id           uuid primary key default gen_random_uuid(),
  thread_id    uuid not null references public.threads (id) on delete cascade,
  author_id    uuid references public.users (id) on delete set null,
  -- Display SNAPSHOT, exactly as support_tickets.client_name is: the message must
  -- still read correctly after the author is offboarded, and resolving a name means
  -- reading public.users, which a client cannot do.
  author_name  text not null default '',
  -- Whether the author was writing as the agency or as the client. Needed because
  -- author_id is NULL-able and a client is not in the staff roster.
  author_kind  text not null default 'staff'
                 constraint thread_messages_author_kind_ck
                 check (author_kind in ('staff', 'client')),
  body         text not null constraint thread_messages_body_ck check (length(btrim(body)) > 0),
  visibility   public.message_visibility not null default 'internal',
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  -- A client cannot author an internal note. Enforced as a CHECK rather than left to
  -- the service layer: bypassing Python must not buy you a message that is filed as
  -- agency-internal but written by someone outside the agency.
  constraint thread_messages_client_is_visible_ck
    check (author_kind <> 'client' or visibility = 'client_visible')
);

create index if not exists thread_messages_thread_idx
  on public.thread_messages (thread_id, created_at);
-- The client read path filters on visibility inside a thread, so index the pair.
create index if not exists thread_messages_visible_idx
  on public.thread_messages (thread_id, visibility, created_at);

create trigger thread_messages_set_updated_at
  before update on public.thread_messages
  for each row execute function public.set_updated_at();

-- --- Append-only, enforced for EVERY principal --------------------------------
-- A conversation between an agency and its client is a record. Silently rewriting or
-- deleting a message is worse than living with a typo, so neither is permitted.
--
-- This is a TRIGGER, not merely an absent policy, and the distinction is the lesson
-- `activity_log` taught: "no update policy" constrains everyone EXCEPT the principal
-- that actually writes the table, because service_role is BYPASSRLS and policies are
-- never consulted for it. A trigger fires for BYPASSRLS roles too - so this binds the
-- server, not just the browser. (Same pattern as WU-16 used for `evidence`.)
create or replace function public.thread_messages_guard_write()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'thread_messages is append-only: a message cannot be deleted'
      using errcode = 'check_violation';
  end if;
  -- updated_at is maintained by its own BEFORE trigger; everything an author could
  -- meaningfully change is frozen.
  if new.body is distinct from old.body
     or new.visibility is distinct from old.visibility
     or new.author_id is distinct from old.author_id
     or new.author_kind is distinct from old.author_kind
     or new.thread_id is distinct from old.thread_id then
    raise exception 'thread_messages is append-only: % cannot be edited after posting',
      case
        when new.visibility is distinct from old.visibility then 'visibility'
        else 'a message'
      end
      using errcode = 'check_violation';
  end if;
  return new;
end $$;

create trigger thread_messages_guard_update
  before update on public.thread_messages
  for each row execute function public.thread_messages_guard_write();

create trigger thread_messages_guard_delete
  before delete on public.thread_messages
  for each row execute function public.thread_messages_guard_write();

-- --- RLS ---------------------------------------------------------------------
-- No client policy on either base table, by design (0010's doctrine). is_staff() was
-- redefined in 0010 to EXCLUDE clients, so these policies default-deny a portal
-- client outright; the views below are their entire read surface.
alter table public.threads enable row level security;
alter table public.threads force row level security;

create policy threads_select on public.threads
  for select using (public.is_staff());

create policy threads_insert on public.threads
  for insert with check (public.is_staff());

-- No update/delete policy: a thread's identity (which entity, which tenant) is fixed
-- at creation. `updated_at` moves via the server, which is BYPASSRLS.

alter table public.thread_messages enable row level security;
alter table public.thread_messages force row level security;

-- Any staff member may read the whole conversation, internal notes included.
create policy thread_messages_select on public.thread_messages
  for select using (public.is_staff());

-- Any staff member may post. Contributing to a discussion is not a privileged act -
-- it is the point of the feature - and restricting it to leads would reproduce the
-- gap this table exists to close.
create policy thread_messages_insert on public.thread_messages
  for insert with check (public.is_staff());

-- --- The client read surface: security-barrier views only ---------------------
-- security_barrier = true guarantees the tenant + visibility filters run BEFORE any
-- user-supplied predicate, so a crafted WHERE cannot be used to probe rows the filter
-- would have excluded.

create or replace view public.portal_threads
  with (security_barrier = true) as
  select
    t.id,
    t.entity_type,
    t.entity_id,
    t.created_at,
    t.updated_at
  from public.threads t
  where t.client_id = public.current_client_id()
    -- A client converses on their own REQUESTS. A task thread is agency-internal
    -- work-tracking even when the task is about their account, and is not theirs to
    -- read; restricting the entity type here means a task thread cannot become
    -- client-readable by mistakenly carrying a client_id.
    and t.entity_type = 'ticket';

comment on view public.portal_threads is
  'Client-safe view of the caller''s own request threads. Filtered by current_client_id() and entity_type=''ticket''.';

create or replace view public.portal_thread_messages
  with (security_barrier = true) as
  select
    m.id,
    m.thread_id,
    m.author_name,
    m.author_kind,
    m.body,
    m.created_at
  from public.thread_messages m
  join public.threads t on t.id = m.thread_id
  where t.client_id = public.current_client_id()
    and t.entity_type = 'ticket'
    -- THE line this whole migration is arranged around. An internal note is never
    -- selected, so it cannot be returned by any query a client can write.
    and m.visibility = 'client_visible';

comment on view public.portal_thread_messages is
  'Client-safe view of the caller''s own request messages. NEVER exposes visibility=''internal'', and omits author_id.';
