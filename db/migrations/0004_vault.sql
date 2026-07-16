-- 0004_vault.sql - Key Vault: agency API keys encrypted at rest.
--
-- Secrets are sealed with AES-256-GCM IN THE APPLICATION (app/services/vault.py)
-- using VAULT_MASTER_KEY, which is held ONLY in the process environment - NEVER in
-- Postgres. The DB stores nonce||ciphertext||tag (secret_sealed) + key_version +
-- masked metadata, so a database dump yields nothing usable and there is NO
-- decrypt path in SQL. Reveal is owner-only, enforced in the router + service
-- (the ciphertext never leaves the server and is never decrypted in SQL). This
-- replaces the former Supabase-Vault design (the `vault` schema wrappers + the
-- `secret_id` column are gone), so 0000->0012 apply on plain PostgreSQL.

create table public.vault_keys (
  id            uuid primary key default gen_random_uuid(),
  provider      text not null,
  label         text not null default '',
  masked        text not null default '',        -- e.g. "sk-...4cb6" for the list UI
  secret_sealed bytea not null,                   -- 12-byte nonce || ciphertext || 16-byte tag
  key_version   int  not null default 1,          -- for master-key rotation
  created_by    uuid references public.users (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create trigger vault_keys_set_updated_at
  before update on public.vault_keys
  for each row execute function public.set_updated_at();

alter table public.vault_keys enable row level security;
alter table public.vault_keys force row level security;

-- manage_vault holders (owner/admin) see the masked list + manage; the owner-only
-- REVEAL decrypts server-side in vault.py behind require_owner (the raw secret is
-- never exposed by RLS, never decrypted in SQL).
create policy vault_keys_select on public.vault_keys
  for select using (public.current_app_role() in ('owner', 'admin'));

create policy vault_keys_modify on public.vault_keys
  for all
  using (public.current_app_role() in ('owner', 'admin'))
  with check (public.current_app_role() in ('owner', 'admin'));
