-- 0123 — the Web 2.0 account provisioning queue.
--
-- THE GAP THIS CLOSES, and why it is structural rather than missing glue.
-- `web2_accounts` rows exist only AFTER an account exists, and its health enum
-- (unverified/active/degraded/suspended/deleted) has no room for a pre-creation state.
-- So the system could record an account it HAD, and could not record an account it
-- INTENDED - which meant provisioning N platforms for a client was N separate manual
-- POSTs with no shared state, no progress, no resumption and nothing to show an
-- operator halfway through. At one client that is an annoyance; at twenty it is why
-- the module sat idle with four platforms connected.
--
-- WHAT ONE ROW IS. One (client, platform) account we intend to bring to life, carrying
-- the identity it will be created under, where its verification mail landed, and what
-- is blocking it. The queue is the unit of work; `web2_accounts` remains the registry
-- of accounts that actually exist, and a row here points at one once it is created.
--
-- THE LANES ARE A PROPERTY OF THE PLATFORM, NOT A PREFERENCE.
--   auto   - the platform has an API signup we can drive end to end (Telegra.ph).
--   guided - a human creates the account (every OAuth platform, and every platform
--            whose terms forbid programmatic registration). The machine still does the
--            tedious half: it issues the identity, holds the guide, watches the client's
--            mailbox for the verification link, seals the token and verifies it.
-- There is deliberately no third lane that drives a browser through a defended signup:
-- Tumblr's own guidelines forbid registering accounts "automatically, systematically,
-- or programmatically", and an account created that way is a client asset built on a
-- terms breach (R2 §3.2, R2c).

do $$
begin
  if not exists (select 1 from pg_type where typname = 'web2_provision_status') then
    create type public.web2_provision_status as enum (
      'queued',                 -- intended; nothing done yet
      'identity_ready',         -- handle + registration email decided
      'awaiting_account',       -- someone (or the auto lane) is creating it now
      'awaiting_verification',  -- created; waiting on the platform's confirmation mail
      'awaiting_credential',    -- verified; needs the API token / OAuth token
      'live',                   -- credential sealed, web2_accounts row exists
      'blocked',                -- needs a decision; `note` says which
      'cancelled'
    );
  end if;
  if not exists (select 1 from pg_type where typname = 'web2_provision_lane') then
    create type public.web2_provision_lane as enum ('auto', 'guided');
  end if;
end $$;

create table if not exists public.web2_provision_items (
  id                 uuid primary key default gen_random_uuid(),
  client_id          uuid not null references public.clients (id) on delete cascade,
  platform           public.web2_platform not null,
  status             public.web2_provision_status not null default 'queued',
  lane               public.web2_provision_lane not null default 'guided',
  -- The identity this account is created under, SNAPSHOT at queue time from the
  -- client's standing identity (0122). Snapshotted on purpose: editing a client's
  -- handle base later must not silently rewrite what an in-flight signup already used
  -- on the platform.
  handle             text not null default '',
  registration_email text not null default '',
  signup_url         text not null default '',
  -- What the mailbox watcher found, so an operator can click it without hunting.
  verify_link        text not null default '',
  verify_found_at    timestamptz,
  -- Set once the account exists; the queue row then just narrates how it got there.
  account_id         uuid references public.web2_accounts (id) on delete set null,
  -- Why it is blocked, or what last failed. Never a secret.
  note               text not null default '',
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint web2_provision_blocked_has_note
    check (status <> 'blocked' or length(btrim(note)) > 0)
);

-- At most ONE live attempt per (client, platform). Partial so a cancelled attempt does
-- not block a retry, and so history is keepable rather than deleted.
create unique index if not exists web2_provision_client_platform_uq
  on public.web2_provision_items (client_id, platform)
  where status <> 'cancelled';
create index if not exists web2_provision_client_idx on public.web2_provision_items (client_id);
create index if not exists web2_provision_status_idx on public.web2_provision_items (status);

create trigger web2_provision_items_set_updated_at
  before update on public.web2_provision_items
  for each row execute function public.set_updated_at();

alter table public.web2_provision_items enable row level security;
alter table public.web2_provision_items force row level security;

create policy web2_provision_items_select on public.web2_provision_items
  for select using (public.is_staff());
create policy web2_provision_items_insert on public.web2_provision_items
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy web2_provision_items_update on public.web2_provision_items
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

comment on table public.web2_provision_items is
  'The account provisioning queue: one row per (client, platform) account we intend to '
  'create, with the identity it is created under and where its verification mail landed. '
  'web2_accounts records accounts that EXIST; this records accounts we are bringing to '
  'life, which had no representation at all before 0123.';
comment on column public.web2_provision_items.lane is
  'auto = a drivable API signup; guided = a human creates the account (every OAuth '
  'platform, and every platform whose terms forbid programmatic registration). No lane '
  'drives a browser through a defended signup - that is a terms breach, not a feature.';
comment on column public.web2_provision_items.handle is
  'Snapshot of the handle at queue time, so editing the client identity later cannot '
  'rewrite what an in-flight signup already used on the platform.';
