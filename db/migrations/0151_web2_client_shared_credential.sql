-- 0151_web2_client_shared_credential.sql - ONE username/password per client, reused
-- across every platform that can accept it.
--
-- THE OPERATOR'S REQUIREMENT, stated plainly: the agency enters a client's username and
-- password ONCE, and every platform that client publishes to uses that same login. No
-- per-platform credential entry, no thirty forms.
--
-- WHY THIS IS THE RIGHT SHAPE AND NOT THE PATTERN ADR-014 RETIRED. The retired
-- `seed_web2_vault` copied ONE AGENCY credential into every CLIENT's vault - a shared
-- failure domain ACROSS CLIENTS, where a single suspension took every client down and the
-- shared login made them mutually identifiable. This is the opposite: one credential per
-- CLIENT, reused across that client's OWN platforms. The blast radius of a ban stays one
-- client, which is exactly what M05 §4's per-client identity tier asks for.
--
-- WHAT A USERNAME AND PASSWORD CAN AND CANNOT DO, measured against the adapters
-- (`PLATFORM_CREDENTIAL_FIELDS`), because this is where the requirement meets the APIs:
--
--     8 platforms publish with username+password directly   (LiveJournal, Dreamwidth,
--       Drupal, FC2, Seesaa, Lemmy, and Disqus/Gravatar partially)
--     2 take an APP PASSWORD generated inside the account   (Bluesky, WhiteWind)
--    43 require a token or an OAuth grant                   (WordPress.com, Blogger,
--       dev.to, Hashnode, Mastodon, GitHub, and every mainstream social network)
--
-- So the shared credential is the client's IDENTITY everywhere, and the publishing
-- credential on 43 of 53 platforms is still a token that identity has to go and fetch.
-- Pretending otherwise would produce a system that reports "connected" and cannot post.
-- `app.modules.web2.client_credentials` turns that into an operator-facing plan: which
-- platforms are publishable now, and which need exactly one signup or OAuth click.
--
-- THE PASSWORD IS NEVER A COLUMN. It is sealed in the vault exactly like every other
-- credential (invariant #10, and the same discipline 0122 applied to the IMAP password);
-- this row carries only the vault coordinates. A password in a column is readable by
-- anything holding a service_role connection, and this one unlocks every platform the
-- client is on.

begin;

alter table public.clients
  -- The single login the client uses across platforms. Operator-entered, brand-derived,
  -- and deliberately SEPARATE from `web2_handle_base`: a handle is the public name on a
  -- property ("leedsdrainageco"), a username is what logs in. They are usually the same
  -- string and are not the same fact - a platform that renames handles must not silently
  -- change what we try to authenticate with.
  add column if not exists web2_username text not null default '',
  -- Vault coordinates of the sealed shared password. NEVER the password itself.
  add column if not exists web2_password_vault_provider text not null default '',
  add column if not exists web2_password_vault_label text not null default '';

comment on column public.clients.web2_username is
  'The ONE username this client uses across every Web 2.0 and social platform. Distinct '
  'from web2_handle_base (the public handle on a property): this is what authenticates.';
comment on column public.clients.web2_password_vault_label is
  'Vault label of the sealed shared password. The password is NEVER a column: it unlocks '
  'every platform this client is on, and a column is readable by anything holding a '
  'service_role connection.';

commit;
