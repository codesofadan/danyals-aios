-- 0100_web2_accounts.sql - Web 2.0 ACCOUNTS as first-class entities (closes DATA-016,
-- implements R2-01 of docs/research/R2-web2-safety.md).
--
-- WHY THIS TABLE EXISTS. Until now a Web 2.0 account was a SECRET, not an entity: the
-- only trace of "we have a WordPress.com login for this client" was a vault row
-- (provider='web2:<Platform>', label=<client_id>). A secret cannot carry health, a
-- property count, a cap, or an ownership tier - so four things were unimplementable:
--   * the house-account property cap (WEB2-008) had nowhere to live;
--   * account health (suspended / degraded) could not be recorded or acted on;
--   * the cross-client similarity scope ("every client sharing THIS house account",
--     R2-10 scope S2) had no key to group by;
--   * and, most importantly, nothing distinguished a per-client account the CLIENT
--     owns from a shared house login used for everybody.
--
-- THE FAILURE MODE THIS PREVENTS. The retired pattern (app/cli/seed_web2_vault.py)
-- copied ONE house credential into every client's vault row. That is one shared
-- failure domain: a suspension on a shared WordPress.com login removes EVERY client's
-- property at once, and it links our clients to each other in a way no content-level
-- check can see or fix. Tiering ownership is what bounds that blast radius to one
-- client - which is the whole point of `ownership`.
--
-- NOT tenant-scoped-by-client for reads: a house account belongs to no client, so the
-- read policy is the module's normal staff read (is_staff()), matching web2_properties
-- (0018) and web2_platforms (0062). Writes are LEAD-only, same shape. Workers write on
-- service_role (BYPASSRLS), so these policies gate the HTTP surface; they are not the
-- worker's boundary (see 0018's header for the same reasoning).

-- --- Enums ---------------------------------------------------------------------
-- Guarded so a re-apply is a no-op, mirroring 0062's web2_auth_type guard. Creating a
-- type and using it in the same file is allowed; only ALTER TYPE ... ADD VALUE then
-- using that NEW value in the same txn is forbidden (see 0045's header).
do $$ begin
  if not exists (select 1 from pg_type where typname = 'web2_ownership') then
    -- WHO owns the account, which decides the blast radius of a suspension:
    --   per_client - the CLIENT owns this property (client-branded handle, client
    --                domain email). A ban costs that one client an asset.
    --   house      - the agency publishes through it for many clients. A ban costs
    --                EVERY client on it at once, so it is capped (max_properties)
    --                and only allowed where publishing implies no durable identity.
    create type public.web2_ownership as enum ('per_client', 'house');
  end if;
end $$;

do $$ begin
  if not exists (select 1 from pg_type where typname = 'web2_account_health') then
    --   unverified - recorded but not yet proven to publish (the honest default).
    --   active     - last publish/verify succeeded.
    --   degraded   - reachable but wrong: a placed link went missing or turned
    --                nofollow (R2-16), or a publish failed in a recoverable way.
    --   suspended  - the platform has actioned the account; publishing must stop.
    --   deleted    - gone at the platform; retained for the audit trail.
    create type public.web2_account_health as enum
      ('active', 'degraded', 'suspended', 'deleted', 'unverified');
  end if;
end $$;

-- --- web2_accounts ---------------------------------------------------------------
create table if not exists public.web2_accounts (
  id                  uuid primary key default gen_random_uuid(),
  -- The publishing enum (NOT web2_platforms.name, which is free text) - an account
  -- only exists for a platform the pipeline can actually drive. See 0062's header.
  platform            public.web2_platform not null,
  ownership           public.web2_ownership not null,
  -- ON DELETE RESTRICT (not CASCADE): a live third-party account outlives our row.
  -- Deleting the client must NOT silently orphan a real login that is still posting
  -- under their brand - the operator has to retire the account deliberately first.
  client_id           uuid references public.clients (id) on delete restrict,
  -- The real account/blog name on the platform. For per_client accounts this is
  -- operator-entered and derived from the CLIENT'S BRAND (R2-08) - never generated
  -- from a client-id hash, which is the enumerable footprint being retired.
  handle              text not null,
  property_url        text not null default '',
  -- What the account was registered WITH. Recorded so a report can flag the tell:
  -- more than a few per-client accounts sharing one registration domain is exactly
  -- the pattern a platform trust-and-safety team enumerates by (R2-08.3).
  registration_email  text not null default '',
  registration_domain text not null default '',
  -- Where this account's sealed credential lives. vault_label is the ACCOUNT id, not
  -- the client id (R2-06): one account = one credential, so a shared house login is
  -- stored ONCE instead of copied per client.
  vault_provider      text not null,
  vault_label         text not null,
  health              public.web2_account_health not null default 'unverified',
  health_checked_at   timestamptz,
  property_count      int not null default 0,
  -- The cap the publish scheduler refuses to exceed (WEB2-008). A per-client account
  -- is a real brand blog and stays at 1 property; a house account is capped low.
  max_properties      int not null default 1,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  -- The two halves of the ownership contract, enforced by the DB rather than trusted
  -- to the app: a per_client account MUST name its client, a house account MUST NOT.
  constraint web2_accounts_per_client_has_client
    check (ownership <> 'per_client' or client_id is not null),
  constraint web2_accounts_house_has_no_client
    check (ownership <> 'house' or client_id is null)
);

-- One real account per (platform, handle): the same login cannot be recorded twice.
create unique index if not exists web2_accounts_platform_handle_uq
  on public.web2_accounts (platform, handle);
-- At most ONE per-client account per platform per client. Partial, so house accounts
-- (client_id is null) are unconstrained by it.
create unique index if not exists web2_accounts_per_client_uq
  on public.web2_accounts (platform, client_id) where ownership = 'per_client';
create index if not exists web2_accounts_client_id_idx on public.web2_accounts (client_id);
create index if not exists web2_accounts_health_idx    on public.web2_accounts (health);

create trigger web2_accounts_set_updated_at
  before update on public.web2_accounts
  for each row execute function public.set_updated_at();

alter table public.web2_accounts enable row level security;
alter table public.web2_accounts force row level security;

create policy web2_accounts_select on public.web2_accounts
  for select using (public.is_staff());
create policy web2_accounts_insert on public.web2_accounts
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy web2_accounts_update on public.web2_accounts
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

comment on table public.web2_accounts is
  'Web 2.0 publishing accounts as first-class entities: ownership tier (per-client vs '
  'shared house), health, property count and cap, and the vault coordinates of the '
  'sealed credential. Replaces the per-client house-credential fan-out (R2-01/R2-06).';
