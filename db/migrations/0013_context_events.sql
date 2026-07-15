-- 0013_context_events.sql - the Client-Context / AI-Memory EVENT BACKBONE (P6B-1).
--
-- Three additive changes that turn the append-only activity_log into the event
-- source the context-compaction layer drains:
--   (A) link every activity to a TYPED entity (client|user|site) at write-time;
--   (B) give every event a MONOTONIC total order (seq) - the freshness watermark;
--   (C) coalesce affected entities into a DEBOUNCED dirty-queue (context_dirty)
--       via an AFTER INSERT trigger; the compaction worker (P6B-7) drains it.
--
-- Append-only is PRESERVED: only additive columns on activity_log, and NO new
-- write policy - the trigger runs SECURITY DEFINER and the worker uses
-- service_role, so a user-JWT client can neither write activity_log nor
-- context_dirty. Idempotent; safe to re-run (mirrors 0011's guard patterns).

-- --- (A) Typed-entity enum (idempotent; enums have no "create ... if not exists") ---
do $$ begin
  if not exists (select 1 from pg_type where typname = 'context_entity') then
    create type public.context_entity as enum ('client', 'user', 'site');
  end if;
end $$;

-- --- (A)+(B) Additive columns on the append-only activity_log ------------------
alter table public.activity_log
  add column if not exists seq         bigint,
  add column if not exists entity_type public.context_entity,
  add column if not exists entity_id   uuid;

-- The total-order source. Backfill existing rows in (created_at, id) order so the
-- watermark is well-defined for history, THEN attach the default + not-null.
create sequence if not exists public.activity_seq;
do $$ declare r record; begin
  if exists (select 1 from public.activity_log where seq is null) then
    for r in select id from public.activity_log where seq is null order by created_at, id loop
      update public.activity_log set seq = nextval('public.activity_seq') where id = r.id;
    end loop;
  end if;
end $$;
alter table public.activity_log
  alter column seq set default nextval('public.activity_seq'),
  alter column seq set not null;

create unique index if not exists activity_log_seq_key on public.activity_log(seq);
-- Drives "events for this entity after watermark W, in order" (the worker's read).
create index if not exists activity_log_entity_seq_idx
  on public.activity_log(entity_type, entity_id, seq) where entity_type is not null;

-- --- (C) The coalescing dirty-queue (outbox) ----------------------------------
-- ONE row per affected entity, upserted by the trigger. next_eligible_at is the
-- debounce gate the Celery beat dispatcher (P6B-7) claims past with FOR UPDATE
-- SKIP LOCKED. event_count/last_seq coalesce a burst; status re-arms if a new
-- event lands while a worker is mid-compaction.
create table if not exists public.context_dirty (
  entity_type      public.context_entity not null,
  entity_id        uuid not null,
  last_seq         bigint not null,
  event_count      int  not null default 0,
  first_dirty_at   timestamptz not null default now(),
  next_eligible_at timestamptz not null default now(),   -- debounce; beat claims when passed
  status           text not null default 'pending' check (status in ('pending','processing')),
  primary key (entity_type, entity_id)
);
alter table public.context_dirty enable row level security;
alter table public.context_dirty force row level security;
create policy context_dirty_select on public.context_dirty
  for select using (public.is_staff());               -- writes: trigger (definer) + worker only

-- AFTER INSERT: coalesce each event into ONE dirty row per entity. SECURITY
-- DEFINER + empty search_path (schema-qualified everywhere) so it upserts
-- regardless of RLS/current role and never recurses. Unlinked events (no
-- entity) don't drive context.
create or replace function public.activity_enqueue_context()
returns trigger language plpgsql security definer set search_path = '' as
$$
declare v_debounce constant interval := interval '30 seconds';
begin
  if new.entity_type is null or new.entity_id is null then
    return new;                                       -- unlinked events don't drive context
  end if;
  insert into public.context_dirty as d
    (entity_type, entity_id, last_seq, event_count, first_dirty_at, next_eligible_at, status)
  values (new.entity_type, new.entity_id, new.seq, 1, now(), now() + v_debounce, 'pending')
  on conflict (entity_type, entity_id) do update
    set last_seq         = greatest(d.last_seq, excluded.last_seq),
        event_count      = d.event_count + 1,
        next_eligible_at = least(d.next_eligible_at, now() + v_debounce),
        status           = case when d.status = 'processing' then 'pending' else d.status end;
  return new;
end $$;

drop trigger if exists activity_enqueue_context_trg on public.activity_log;
create trigger activity_enqueue_context_trg
  after insert on public.activity_log
  for each row execute function public.activity_enqueue_context();
