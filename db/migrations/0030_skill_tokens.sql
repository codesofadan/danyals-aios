-- 0030_skill_tokens.sql - Part 9 (Skills layer): the per-client SKILL TOKEN ledger.
--
-- A skill token is a SEPARATE, SCOPED credential a client uses to let LOCAL Claude
-- Code skills call this backend through the MCP gateway. It is NOT a user login and
-- NOT an EdDSA access token: it authenticates to `POST /skills/verify`, which
-- resolves it to a SCOPED PRINCIPAL = one client tenant + a capped RBAC/tier/budget
-- subset. The raw secret is shown to the minting owner/admin exactly ONCE and is
-- NEVER stored - only a hash of it lives here (like a GitHub PAT).
--
-- BLAST-RADIUS LIMIT (N7 threat model). A leaked skill token can reach ONLY:
--   * that ONE client's tenant (client_id is pinned here, never taken from a call),
--   * ONLY the perms/features in `scopes` (a subset, capped at mint),
--   * ONLY up to that client's budget + the org daily spend-stop (cost-gate still runs).
-- It can NEVER reach the vault, NEVER another tenant, NEVER an RLS bypass: verify
-- returns the scope, never the secret; dispatch pins client_id from the token, never
-- from the caller; and every paid call the token drives still passes the cost-gate.
--
-- WHO MANAGES TOKENS: owner/admin only (they hold access_control / manage_team).
-- Clients are already excluded by current_app_role() returning 'client' (never in
-- ('owner','admin')); no other staff role may read or manage a token. There is NO
-- client SELECT policy, so a portal client can never read ANY token row (its own or
-- another tenant's). Verify runs SERVER-SIDE on the privileged pool (the MCP gateway
-- presents only a token, no user identity), which is a trusted system op - like the
-- vault reveal - and returns a capped principal, never the hash and never the secret.

create table if not exists public.skill_tokens (
  id            uuid primary key default gen_random_uuid(),
  -- The tenant this token is scoped to. ON DELETE CASCADE: removing a client
  -- destroys its tokens (no orphaned credential can outlive its tenant).
  client_id     uuid not null references public.clients (id) on delete cascade,
  -- Short PUBLIC prefix (the leading segment of the raw token, e.g. "skt_ab12cd..").
  -- Indexed + unique so verify can O(1)-locate the row WITHOUT the secret, then
  -- constant-time-compare the full hash. It leaks nothing usable on its own.
  token_prefix  text not null unique,
  -- sha256 hex of the FULL raw token. The raw token is high-entropy (256-bit
  -- random), so a fast deterministic hash is the correct choice here (argon2's slow
  -- KDF defends LOW-entropy passwords; it is unnecessary - and would break the O(1)
  -- lookup - for a random token). The plaintext is NEVER stored.
  token_hash    text not null,
  -- The RBAC subset this token carries: {"perms": [...], "features": [...]}. A capped
  -- subset chosen at mint; the resolved principal holds EXACTLY this, never more.
  scopes        jsonb not null default '{}'::jsonb,
  -- Delivery-tier cap (free/semi/fully). A 'free' token can never drive a paid tier.
  tier          text not null default 'free',
  -- Expiry is REQUIRED (the service always sets it from the TTL) - a never-expiring
  -- token is a standing liability; a leaked one must age out.
  expires_at    timestamptz not null,
  revoked       boolean not null default false,
  created_by    uuid references public.users (id) on delete set null,
  last_used_at  timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists skill_tokens_client_id_idx  on public.skill_tokens (client_id);
create index if not exists skill_tokens_created_at_idx  on public.skill_tokens (created_at desc);

create trigger skill_tokens_set_updated_at
  before update on public.skill_tokens
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- FORCE so even the table owner is subject to policies. Owner/admin manage; no other
-- role (staff or client) may read or write. Clients return current_app_role()='client'
-- and are excluded, so a client can never SELECT another tenant's token (nor its own).
alter table public.skill_tokens enable row level security;
alter table public.skill_tokens force row level security;

create policy skill_tokens_select on public.skill_tokens
  for select using (public.current_app_role() in ('owner', 'admin'));

create policy skill_tokens_modify on public.skill_tokens
  for all
  using (public.current_app_role() in ('owner', 'admin'))
  with check (public.current_app_role() in ('owner', 'admin'));
