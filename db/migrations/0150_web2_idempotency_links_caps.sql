-- 0150_web2_idempotency_links_caps.sql - three M05 acceptance criteria that had no
-- mechanism behind them at all (A3, A6, A8).
--
-- ============================================================================
-- A3. `web2_properties.idempotency_key` UNIQUE
-- ============================================================================
-- "Re-running a publish job produces exactly one post on the platform." Today the only
-- thing standing between a redelivered Celery message and a duplicate post is
-- `run_publish`'s status check - a read followed by a write, with no lock between them.
-- Two workers that both read `publishing` both publish, and `M05` §3 says why that is
-- not a cosmetic bug: on a social platform a double post is a SPAM SIGNAL.
--
-- The key is derived, not random: same property + same target = same key, so a retry
-- collides with itself by construction rather than by remembering to pass something.
-- NULL is allowed and excluded from the index, because every pre-existing row has no key
-- and back-filling one would invent history.
--
-- ============================================================================
-- A6. `property_count` becomes REAL
-- ============================================================================
-- Migration 0100 declared `property_count` and `max_properties`; the repo reads them and
-- the account board renders them. `property_count` is incremented NOWHERE in the
-- codebase - verified by grep across app/, workers/ and every migration - so every
-- account reads 0/10 forever and the cap can never trip. A6 ("a house account cannot be
-- used for a client once its property cap is reached") was not merely unenforced, it was
-- unenforceable.
--
-- The count is maintained by a TRIGGER rather than by application code, for the reason
-- invariant #10 gives about the activity log: the worker runs as service_role, which is
-- BYPASSRLS, so a policy cannot bind it - but a trigger fires for BYPASSRLS roles too.
-- It also means the count cannot drift when a future writer forgets, which is precisely
-- how it came to be zero everywhere.
--
-- Counted on the transition INTO `published` and out of it, not on every update: a
-- property is "on" an account once it is live, and re-saving a published row must not
-- inflate the count.
--
-- ============================================================================
-- A8. `placed_links` - link liveness as a state machine, not three columns
-- ============================================================================
-- 0028 added `link_found` / `link_rel` / `link_checked_at` to `web2_properties`. That
-- records the LATEST look and nothing else, so "the link was live in March and is gone
-- now" is unanswerable - the row simply changes and the previous fact is overwritten.
-- `M05` §3 specifies `placed_links.state ∈ live | removed | nofollowed | unknown`, each
-- "set from a fetch, never assumed", and A8 asks the system to DETECT a removal - which
-- requires knowing what it was before.
--
-- One row per (property, target), holding the current state plus when it was first seen
-- live and when it was last confirmed. The history that matters for a client report is
-- "live since X, lost at Y", which this can answer and three mutable columns cannot.

begin;

-- --- A3 ---------------------------------------------------------------------
alter table public.web2_properties
  add column if not exists idempotency_key text;

create unique index if not exists web2_properties_idempotency_key_uq
  on public.web2_properties (idempotency_key)
  where idempotency_key is not null;

comment on column public.web2_properties.idempotency_key is
  'Derived publish key (client|platform|target|topic). UNIQUE where set: a redelivered '
  'job collides with itself instead of double-posting, which on a social platform is a '
  'spam signal rather than a cosmetic duplicate (M05 A3).';

-- --- A6 ---------------------------------------------------------------------
create or replace function public.web2_sync_account_property_count()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  became_published boolean;
  left_published   boolean;
begin
  -- Counted on the TRANSITION, so re-saving a published row cannot inflate the count and
  -- a property that is withdrawn gives its slot back.
  --
  -- The INSERT branch is separate deliberately. `OLD` is UNASSIGNED on an insert - not
  -- null, unassigned - so merely referencing `old.status` raises, and `coalesce(old.status,
  -- '')` fails a second way besides: `status` is the `web2_status` ENUM and '' is not one
  -- of its values, so the cast errors even on an update. Both were live in the first draft
  -- of this function and both fired on the very first insert.
  if tg_op = 'INSERT' then
    became_published := (new.status = 'published');
    left_published   := false;
  else
    became_published := (new.status = 'published')
                        and (old.status is distinct from 'published');
    left_published   := (old.status = 'published')
                        and (new.status is distinct from 'published');
  end if;

  if became_published and new.account_id is not null then
    update public.web2_accounts
       set property_count = property_count + 1
     where id = new.account_id;
  elsif left_published and old.account_id is not null then
    update public.web2_accounts
       set property_count = greatest(property_count - 1, 0)
     where id = old.account_id;
  end if;
  return new;
end;
$$;

drop trigger if exists web2_properties_sync_account_count on public.web2_properties;
create trigger web2_properties_sync_account_count
  after insert or update of status on public.web2_properties
  for each row execute function public.web2_sync_account_property_count();

-- Re-derive the counts ONCE from what is actually published, so the column starts
-- truthful rather than at the zero it has always held.
update public.web2_accounts a
   set property_count = coalesce(counted.n, 0)
  from (
    select account_id, count(*) as n
      from public.web2_properties
     where status = 'published' and account_id is not null
     group by account_id
  ) as counted
 where counted.account_id = a.id;

update public.web2_accounts a
   set property_count = 0
 where not exists (
   select 1 from public.web2_properties p
    where p.account_id = a.id and p.status = 'published'
 );

-- --- A8 ---------------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_type where typname = 'web2_link_state') then
    create type public.web2_link_state as enum ('live', 'removed', 'nofollowed', 'unknown');
  end if;
end $$;

create table if not exists public.placed_links (
  id             uuid primary key default gen_random_uuid(),
  web2_id        uuid not null references public.web2_properties (id) on delete cascade,
  client_id      uuid references public.clients (id) on delete cascade,
  page_url       text not null,
  target_url     text not null,
  anchor         text not null default '',
  -- Every value here is SET FROM A FETCH. `unknown` is the honest default and means
  -- "nobody has looked", which must stay distinguishable from `removed` ("we looked and
  -- it was gone") - the distinction the three columns on web2_properties could not hold.
  state          public.web2_link_state not null default 'unknown',
  rel            text not null default '',
  first_seen_at  timestamptz,
  last_checked_at timestamptz,
  lost_at        timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint placed_links_property_target_uq unique (web2_id, target_url)
);

create index if not exists placed_links_client_idx on public.placed_links (client_id);
create index if not exists placed_links_state_idx  on public.placed_links (state);
create index if not exists placed_links_recheck_idx
  on public.placed_links (last_checked_at nulls first) where state <> 'removed';

drop trigger if exists placed_links_set_updated_at on public.placed_links;
create trigger placed_links_set_updated_at
  before update on public.placed_links
  for each row execute function public.set_updated_at();

-- RLS: same posture as the off-page ledgers 0018 established - staff read, leads write,
-- portal clients excluded entirely by is_staff(). The monitoring sweep runs on
-- service_role (BYPASSRLS) and is unaffected.
alter table public.placed_links enable row level security;
alter table public.placed_links force row level security;

drop policy if exists placed_links_select on public.placed_links;
create policy placed_links_select on public.placed_links
  for select using (public.is_staff());
drop policy if exists placed_links_insert on public.placed_links;
create policy placed_links_insert on public.placed_links
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
drop policy if exists placed_links_update on public.placed_links;
create policy placed_links_update on public.placed_links
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

comment on table public.placed_links is
  'Every outbound link a Web 2.0 property placed, with its measured state over time '
  '(M05 A8). Distinct from web2_properties.link_found, which records only the latest '
  'look: answering "live since March, lost in June" needs the previous fact kept.';

commit;
