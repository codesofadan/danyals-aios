-- 0122 — Web 2.0 per-client publishing identity.
--
-- WHY THIS TABLE EXISTS. Creating accounts for 20-50 clients is not 20-50 repetitions
-- of a one-off form; it is a standing fact per client that every signup then reuses:
-- WHO the account is (a brand-derived handle base), WHERE its verification mail lands
-- (the client's own mailbox), and HOW the machine reads that mailbox (IMAP, optional).
--
-- WHY THE CLIENT'S OWN MAILBOX AND NOT AN AGENCY ALIAS. R2-08, measured: an alias
-- minted per (platform, client) on one agency catch-all shares a platform prefix, a
-- client-id hash and a registrant domain, so a trust-and-safety team that suspends ONE
-- account can enumerate every other client by prefix, by suffix and by domain. The
-- content-similarity gate cannot see that footprint and cannot fix it. Per-client
-- accounts therefore register on the CLIENT's domain, which is also why
-- `validate_registration_email` refuses a shared catch-all for ownership='per_client'.
-- The agency catch-all remains correct for anonymous HOUSE accounts, which carry no
-- durable identity to correlate.
--
-- WHAT IS AND IS NOT STORED HERE. The mailbox PASSWORD is never a column: it is sealed
-- in the vault exactly like a publishing credential, and this row carries only its
-- coordinates (provider + label). A row with no IMAP config is completely legitimate —
-- verification then falls to the operator reading the client's inbox by hand, which is
-- the honest degrade, not a failure.

alter table public.clients
  -- The brand-derived stem an account handle is built from ("leedsdrainageco"), so the
  -- handle is a real brand asset rather than a generated string that reads as machinery.
  add column if not exists web2_handle_base text not null default '',
  -- The client's own address that receives platform verification mail.
  add column if not exists web2_contact_email text not null default '',
  -- Where the machine reads that mailbox. Optional: without it, verification is manual.
  add column if not exists web2_imap_host text not null default '',
  add column if not exists web2_imap_port int not null default 993,
  add column if not exists web2_imap_user text not null default '',
  -- Vault coordinates of the sealed IMAP password (never the password itself).
  add column if not exists web2_imap_vault_provider text not null default '',
  add column if not exists web2_imap_vault_label text not null default '';

comment on column public.clients.web2_handle_base is
  'Brand stem for Web 2.0 account handles (R2-08): operator-entered, never generated, '
  'so handles carry no platform prefix or client-id hash to correlate across clients.';
comment on column public.clients.web2_contact_email is
  'The CLIENT-domain address platform verification mail is sent to. Per-client accounts '
  'must not register on the agency catch-all - that shared domain is the footprint that '
  'lets one suspension enumerate every client (R2-08).';
comment on column public.clients.web2_imap_host is
  'IMAP host for the client mailbox, so the account builder can read a verification '
  'link automatically. Empty is legitimate: verification degrades to manual.';
comment on column public.clients.web2_imap_vault_label is
  'Vault label of the sealed IMAP password. The password is NEVER a column here.';
