-- 0004_vault.sql - Key Vault metadata + service_role-only Supabase Vault wrappers.
--
-- The raw secret NEVER lives in a public table: it is stored in Supabase Vault
-- (encrypted at rest). public.vault_keys holds only non-sensitive metadata plus
-- a masked preview and the vault secret_id. Reveal/store/rotate go through
-- SECURITY DEFINER wrappers whose EXECUTE is granted ONLY to service_role, so no
-- browser/anon/authenticated caller can reach the vault - only the server.

create table public.vault_keys (
  id         uuid primary key default gen_random_uuid(),
  provider   text not null,
  label      text not null,
  masked     text not null default '',
  scope      text not null default 'Agency-global',
  site       text,
  secret_id  uuid not null,   -- FK into vault.secrets (managed by Supabase Vault)
  rotated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger vault_keys_set_updated_at
  before update on public.vault_keys
  for each row execute function public.set_updated_at();

alter table public.vault_keys enable row level security;
alter table public.vault_keys force row level security;

-- Only manage_vault holders (owner/admin) can read the masked list; reveal of the
-- raw secret is further restricted to the super-admin in the application layer.
create policy vault_keys_select on public.vault_keys
  for select using (public.current_app_role() in ('owner', 'admin'));

create policy vault_keys_modify on public.vault_keys
  for all
  using (public.current_app_role() in ('owner', 'admin'))
  with check (public.current_app_role() in ('owner', 'admin'));

-- --- Vault wrappers (service_role only) --------------------------------------
create or replace function public.vault_create_secret(p_secret text, p_name text)
returns uuid language sql security definer set search_path = ''
as $$ select vault.create_secret(p_secret, p_name) $$;

create or replace function public.vault_update_secret(p_id uuid, p_secret text)
returns void language sql security definer set search_path = ''
as $$ select vault.update_secret(p_id, p_secret) $$;

create or replace function public.vault_reveal_secret(p_id uuid)
returns text language sql security definer set search_path = ''
as $$ select decrypted_secret from vault.decrypted_secrets where id = p_id $$;

revoke execute on function public.vault_create_secret(text, text) from public;
revoke execute on function public.vault_update_secret(uuid, text) from public;
revoke execute on function public.vault_reveal_secret(uuid) from public;
grant execute on function public.vault_create_secret(text, text) to service_role;
grant execute on function public.vault_update_secret(uuid, text) to service_role;
grant execute on function public.vault_reveal_secret(uuid) to service_role;
