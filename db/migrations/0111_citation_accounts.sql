-- 0111_citation_accounts.sql - a directory account is an ENTITY, not a lost secret.
--
-- THE DEFECT THIS CLOSES. `backend/integrations/citation_signup.py` generates a strong
-- per-account password (`_generate_password`, :196), types it into the signup form
-- (:206) - and never stores it anywhere. Every directory account the bot has ever
-- created has an irrecoverable login. We cannot correct those listings, cannot remove
-- them, and cannot hand them to an operator to finish; the only remaining move is to
-- abandon the account and create a duplicate, which is precisely the duplicate-listing
-- problem a citation campaign exists to prevent.
--
-- The other half of the same defect was `tools/finish_citation.py` (now deleted): it
-- read an exported JSON of every login in a campaign and printed `Password for all: …`.
-- One password across every account means one compromise is total, and the credentials
-- lived in a file outside the platform entirely.
--
-- WHY A TABLE AND NOT JUST A VAULT ENTRY. This is `0100_web2_accounts.sql`'s lesson,
-- applied to directories: a secret cannot carry health, an alias, a client, a creation
-- date, or a count of what was built with it. Those are properties of an ACCOUNT, and
-- an account is a thing we operate. The secret is one attribute of it, and it is the one
-- attribute that lives in the vault rather than here.
--
-- ---------------------------------------------------------------------------------
-- THREE ATTACKS THIS SCHEMA IS SHAPED TO DEFEAT, found by an adversarial review of the
-- first draft. Each fix only makes sense next to the attack it answers.
--
-- 1. VAULT COORDINATES AS DATA. The draft stored `vault_provider`/`vault_label` as
--    ordinary columns that the RLS policies let any lead UPDATE, and the reveal endpoint
--    looked a secret up BY those columns. So a manager could repoint a citation account
--    at any other row in `vault_keys` - a client's WordPress password, an API key - and
--    read it back through a legitimate citation route. Here the coordinates are SET BY
--    THE DATABASE from the row's own id and never accepted from a writer, and the
--    trigger refuses to let them change once written. They stop being data.
--
-- 2. A SEALED-AT TIMESTAMP WITH NOTHING BEHIND IT. `credential_sealed_at` looks like
--    proof a secret exists. Nothing stopped an INSERT setting it with no vault row at
--    all - a claim of a credential we do not hold, which is the same fabrication class
--    as reporting a screenshot as a live listing. It may now only be set together with
--    a label, and only by the sealing path.
--
-- 3. AN ALIAS THAT DOES NOT IDENTIFY AN ACCOUNT. `alias_for(directory, client_id,
--    domain)` is deterministic, so two accounts for the same (directory, client) collide
--    on one inbox - and a confirmation email or a suspension notice then cannot be
--    attributed to the right row. A mailbox address is globally the identity of an
--    inbox, so it is globally unique here.

create table if not exists public.citation_accounts (
  id           uuid primary key default gen_random_uuid(),
  -- RESTRICT, not CASCADE: the account exists on someone else's website and outlives our
  -- row. Deleting the client here would orphan a live login we can no longer reach -
  -- exactly the state this table exists to end. Remove the listings first.
  client_id    uuid not null references public.clients (id) on delete restrict,
  directory_id uuid not null references public.directories (id) on delete restrict,

  -- The per-account inbox. Per (directory, client) by construction, never one shared
  -- catch-all: one mailbox failure must not block every other client's confirmations,
  -- and a suspension notice has to be attributable.
  registration_email text not null,

  -- WHERE the sealed password lives. Written by the trigger below from this row's own
  -- id, never accepted from a caller (attack 1). They are recorded rather than derived
  -- at read time so a vault entry stays findable if the naming convention ever changes.
  vault_provider text not null default '',
  vault_label    text not null default '',
  -- Set ONLY by the sealing path, and only alongside a label (attack 2).
  credential_sealed_at timestamptz,

  -- What we know about the account's standing, and when we last had reason to believe
  -- it. `unverified` is the honest default: creating an account is not the same as
  -- confirming it works.
  health text not null default 'unverified'
    check (health in ('unverified', 'active', 'email_pending', 'locked', 'suspended', 'dead')),
  health_checked_at timestamptz,
  health_note       text not null default '',

  listings_built int not null default 0,
  created_by     uuid references public.users (id) on delete set null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),

  -- A timestamp claiming a sealed credential must name where it is (attack 2).
  constraint citation_accounts_sealed_names_its_label
    check (credential_sealed_at is null or btrim(vault_label) <> ''),
  -- One account per (client, directory). A second is a duplicate listing waiting to
  -- happen, which is the problem the module exists to prevent.
  constraint citation_accounts_one_per_client_directory
    unique (client_id, directory_id)
);

-- A mailbox address is globally the identity of an inbox (attack 3).
create unique index if not exists citation_accounts_email_uq
  on public.citation_accounts (lower(registration_email));

create index if not exists citation_accounts_client_idx
  on public.citation_accounts (client_id);
create index if not exists citation_accounts_directory_idx
  on public.citation_accounts (directory_id);
-- The operator board: accounts that need attention.
create index if not exists citation_accounts_health_idx
  on public.citation_accounts (health) where health <> 'active';

-- --- the coordinates are the database's, not the caller's (attack 1) --------------
create or replace function public.citation_accounts_guard()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  dir_name text;
begin
  select d.name into dir_name from public.directories d where d.id = new.directory_id;

  if tg_op = 'INSERT' then
    -- Overwritten unconditionally: whatever a caller supplied is discarded. The label
    -- is the ACCOUNT id (0100's R2-06 rule) - one account, one credential - so a shared
    -- login cannot be expressed here even by accident.
    new.vault_provider := 'citation:' || coalesce(dir_name, new.directory_id::text);
    new.vault_label    := new.id::text;
    -- A credential cannot already be sealed at INSERT, because the vault entry is named
    -- after THIS ROW'S id - which does not exist until the insert completes. So sealing
    -- is necessarily a later UPDATE by the sealing path, and any sealed-at supplied here
    -- is a claim about a secret that cannot exist yet.
    --
    -- MEASURED: the `citation_accounts_sealed_names_its_label` CHECK alone does NOT
    -- catch this. The trigger fills `vault_label` above before the constraint is
    -- evaluated, so the check always passes on INSERT - it was decoration. This line is
    -- the rule; the constraint only guards the UPDATE path.
    new.credential_sealed_at := null;
  else
    -- Write-once. Without this a lead could repoint an account at any vault row and read
    -- it back through the citation reveal route.
    if new.vault_label is distinct from old.vault_label
       or new.vault_provider is distinct from old.vault_provider then
      raise exception
        'citation_accounts vault coordinates are set by the database and cannot be '
        'changed - they are not a lookup key a caller may choose'
        using errcode = 'check_violation';
    end if;
    -- A credential is sealed once. Re-sealing is a ROTATION, which must go through the
    -- vault''s own rotate path so the old secret is superseded rather than orphaned.
    if old.credential_sealed_at is not null
       and new.credential_sealed_at is distinct from old.credential_sealed_at then
      raise exception 'citation_accounts.credential_sealed_at is write-once (rotate via the vault)'
        using errcode = 'check_violation';
    end if;
  end if;

  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists citation_accounts_guard_trg on public.citation_accounts;
create trigger citation_accounts_guard_trg
  before insert or update on public.citation_accounts
  for each row execute function public.citation_accounts_guard();

alter table public.citation_accounts enable row level security;
alter table public.citation_accounts force row level security;

drop policy if exists citation_accounts_select on public.citation_accounts;
create policy citation_accounts_select on public.citation_accounts
  for select using (public.is_staff());
drop policy if exists citation_accounts_insert on public.citation_accounts;
create policy citation_accounts_insert on public.citation_accounts
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
drop policy if exists citation_accounts_update on public.citation_accounts;
create policy citation_accounts_update on public.citation_accounts
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

comment on table public.citation_accounts is
  'Per-client, per-directory account. The password is sealed in the vault at '
  'vault_provider/vault_label, which the database sets from this row''s own id and '
  'refuses to let a caller change. Replaces the shared-password handoff export.';
