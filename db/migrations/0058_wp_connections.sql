-- 0058_wp_connections.sql - the MULTI-CLIENT WordPress Connections registry.
--
-- One row per client records HOW to publish generated content to THAT client's own
-- WordPress site: the site URL, the auth method, and the sealed credential. So the
-- admin (Danyal) connects EVERY client's site once and the content publish path
-- resolves the RIGHT client's connection at push time (workers/tasks/content.py).
--
-- THREE auth methods (the `auth_method` check), matching the publish adapters:
--   * 'plugin'       - the companion AIOS Publisher plugin's own endpoint + a shared
--                      api_key (the host-independent primary; secret = the api_key).
--   * 'xmlrpc'       - POST /xmlrpc.php wp.newPost with username+password in the body
--                      (the path that works on hostile managed hosts; secret = the
--                      password, `username` is the plaintext login).
--   * 'app_password' - the WP REST v2 API over HTTP Basic (an Application Password;
--                      secret = the app password, `username` is the login).
--
-- SECRET AT REST: `secret_sealed` holds the plugin api_key OR the password, sealed
-- IN THE APPLICATION with AES-256-GCM under VAULT_MASTER_KEY (app/services/vault.py's
-- seal_value / open_sealed) - exactly like the Key Vault (0004). The DB stores only
-- nonce||ciphertext||tag; there is NO decrypt path in SQL, a dump yields nothing
-- usable, and the sealed bytea is NEVER returned to a client (the API returns only
-- masked metadata + a `configured` flag). Nullable so a connection can be saved with
-- a site_url before a credential lands, or a re-save can leave the secret unchanged.
--
-- RLS: staff-managed, mirrors client_budgets (0006) / clients (0003). Every staff
-- member reads (is_staff()); only manage_clients holders (owner/admin/manager) write.
-- ENABLE + FORCE RLS so even the table owner is subject to the policies (the RLS gate
-- requires FORCE on every public table). Idempotent-friendly ordering (create type
-- guard not needed - auth_method is a plain text CHECK, not an enum).

create table public.wp_connections (
  id             uuid primary key default gen_random_uuid(),
  -- one connection per client (UNIQUE); cascades away with the client.
  client_id      uuid not null unique references public.clients (id) on delete cascade,
  site_url       text not null default '',
  auth_method    text not null default 'plugin'
                   check (auth_method in ('plugin', 'xmlrpc', 'app_password')),
  -- nonce||ciphertext||tag (AES-256-GCM); the plugin api_key OR the password. Never
  -- returned to a client, never decrypted in SQL. Nullable: a row may exist before a
  -- credential is set, and a metadata-only re-save keeps the prior secret.
  secret_sealed  bytea,
  -- plaintext login for xmlrpc / app_password (NOT a secret); '' for the plugin method.
  username       text not null default '',
  -- last connectivity-test verdict: 'unknown' (never tested) | 'connected' | 'failed'.
  status         text not null default 'unknown',
  last_tested_at timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create trigger wp_connections_set_updated_at
  before update on public.wp_connections
  for each row execute function public.set_updated_at();

-- --- RLS: wp_connections ------------------------------------------------------
alter table public.wp_connections enable row level security;
alter table public.wp_connections force row level security;

-- Every provisioned staff member sees the connection metadata + status (the manager
-- screen lists all clients with their connection); a portal client has no policy and
-- so default-denies.
create policy wp_connections_select on public.wp_connections
  for select using (public.is_staff());

-- manage_clients holders (owner/admin/manager) may create/edit/remove a connection -
-- the same write set that manages the client account itself (clients_modify, 0003).
create policy wp_connections_modify on public.wp_connections
  for all
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

comment on table public.wp_connections is
  'Per-client WordPress publish connections (site_url + auth_method + sealed '
  'credential). Secret sealed app-layer like the vault; never returned to a client.';
comment on column public.wp_connections.secret_sealed is
  'AES-256-GCM nonce||ciphertext||tag of the plugin api_key OR the password; sealed '
  'by app/services/vault.seal_value, opened only server-side. Never leaves the server.';
