-- 0041_vault_kind.sql - Part 8 Phase 2F: give the Key Vault a `kind` DIMENSION.
--
-- WHY THIS EXISTS
-- The vault was built (0004_vault.sql) for the AGENCY's own API keys: its
-- application-level ProviderId enum is provider-oriented (serper / dataforseo /
-- google / anthropic / imagegen / gsheets / wordpress). Client onboarding
-- (0040_client_onboarding.sql) collects a different species of secret entirely -
-- CLIENT ACCESS credentials: a GBP manager login, a CMS admin, an analytics
-- account. Those are not providers and never will be.
--
-- The tempting shortcut is to overload `provider` with pseudo-providers ('gbp',
-- 'cms', ...). That silently corrupts the vault's own vocabulary: `provider` would
-- no longer answer "which integration is this key for?", every provider lookup
-- would have to learn which values are lies, and the two populations would be
-- indistinguishable to any future policy (rotation cadence, expiry, egress rules)
-- that legitimately wants to treat an agency API key differently from a client's
-- password. So this migration adds an ORTHOGONAL dimension instead: `kind` says
-- WHAT SPECIES of secret this is; `provider` keeps meaning what it always meant.
--
-- WHAT THIS MIGRATION DELIBERATELY DOES NOT DO (the review contract)
-- This touches credential storage, so the change is strictly ADDITIVE:
--
--   * The column is NOT NULL DEFAULT 'api_key', so EVERY existing row stays valid
--     and keeps its exact current meaning. There is no backfill, no rewrite, and
--     no re-seal: the sealed bytes are not read or touched by this migration.
--   * NO existing RLS policy is altered, dropped, or weakened. vault_keys_select /
--     vault_keys_modify stay exactly as 0004 wrote them (owner/admin only), and
--     they cover the new rows automatically - a client_access secret is therefore
--     no more visible than an API key ever was.
--   * NO new read path to secret_sealed is created. There is still exactly ONE
--     decrypt path in the entire system: app/services/vault.py's owner-only
--     reveal_secret(), behind require_owner in the vault router. `kind` is
--     metadata; it grants nothing. In particular an onboarding step (0040) stores
--     only an opaque vault_secret_id and has NO way to open the blob.
--   * The masked-list behaviour is UNCHANGED: `select *` already returns whatever
--     columns exist, and VaultKeyResponse is contract-locked to the frontend
--     `VaultKey` type - so `kind` is exposed on the SERVICE's masked metadata, not
--     added to the wire response, and the vault list/rotate/reveal endpoints all
--     keep their byte-for-byte current shape.
--   * key_version (master-key rotation) is untouched and stays orthogonal: a
--     client_access secret is sealed with the same master key, the same AES-256-GCM
--     construction, and rotates by exactly the same mechanism as any other key.
--
-- Net effect: a strictly wider vocabulary, an unchanged security posture.

-- --- Enum (idempotent guard; enums have no "create ... if not exists") --------
-- 'api_key'       - an AGENCY integration credential (the 0004 population; the
--                   value every pre-existing row carries by default).
-- 'client_access' - a CLIENT's own access credential, collected during onboarding.
do $$ begin
  if not exists (select 1 from pg_type where typname = 'vault_kind') then
    create type public.vault_kind as enum ('api_key', 'client_access');
  end if;
end $$;

-- --- The additive column ------------------------------------------------------
-- `if not exists` + a defaulted NOT NULL: re-runnable, and every row that already
-- exists is correctly classified as what it actually is (an agency API key) with
-- no data migration. PG11+ adds a defaulted NOT NULL column without a table
-- rewrite, so this is also a metadata-only operation on the sealed data.
alter table public.vault_keys
  add column if not exists kind public.vault_kind not null default 'api_key';

-- The population split is the only new query pattern (e.g. "list the agency's API
-- keys" vs "the credentials collected for a client"), so index it.
create index if not exists vault_keys_kind_idx on public.vault_keys (kind);

comment on column public.vault_keys.kind is
  'What SPECIES of secret this is: api_key = an agency integration credential '
  '(the 0004 default); client_access = a client access credential collected by '
  'the client_onboarding module. Orthogonal to `provider` - it classifies the '
  'secret, it does NOT grant access. The sealed bytes remain readable only via '
  'the owner-only reveal path in app/services/vault.py.';

-- NOTE: RLS is intentionally NOT re-declared here. public.vault_keys already has
-- ENABLE + FORCE row level security and its two 0004 policies; re-issuing them
-- would risk weakening what is already correct. The FORCE-RLS coverage gate
-- (app/db/rls_check.py) keeps passing for this table on exactly the 0004 grounds.
