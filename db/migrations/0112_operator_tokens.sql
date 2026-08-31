-- 0112_operator_tokens.sql - a device credential for the citation browser extension.
--
-- WHY NOT THE ORDINARY ACCESS TOKEN. The dashboard's token is an EdDSA JWT carrying
-- `aud = "authenticated"`, which every one of the ~200 API routes accepts with the
-- holder's full role, and it lives for seven days. Copying one into a browser extension
-- would put an unrestricted seven-day credential on a machine that is, by design,
-- simultaneously signed into ~50 third-party directories and running next to whatever
-- JavaScript those sites serve. A scope claim would not help: no existing route reads
-- one, and teaching `get_current_user` to enforce scopes means editing the hottest
-- security path in the application for the benefit of one client.
--
-- WHY NOT `skill_tokens` (0030). Its `client_id` is `not null references clients`, so it
-- resolves to a TENANT with no user identity. The citation queue is staff surface, and
-- every completion has to be attributable to a NAMED operator for `record_activity` - a
-- skill token cannot express "Danyal, working across four clients tonight".
--
-- So: the same SHAPE as a skill token - sha256 of the full token, an indexed prefix to
-- locate the row, a mandatory expiry, a revoked flag, a jsonb scope set - keyed to a
-- USER instead of a client, and presented in its OWN header. A separate header and a
-- separate dependency mean this credential has zero blast radius on the existing 401
-- path: it is not a JWT, so `get_current_user` rejects it everywhere by construction.
--
-- THE SCOPE VOCABULARY IS CLOSED, and that is the real containment. `citation_queue` and
-- `citation_credential` are the only two values that can ever be stored, capped at mint
-- against a frozen set. It is therefore STRUCTURALLY impossible to mint an extension
-- token that reaches the vault, `/clients`, or the cost dials - not "no route grants it",
-- but "no such scope exists to grant".
--
-- TWELVE HOURS, not the skill token's thirty days. One shift. A skill token runs in a
-- developer's own terminal; this one sits in `chrome.storage.local`, which is plaintext
-- on disk and readable by anything with filesystem access to the browser profile. The
-- short TTL is the mitigation for a storage medium we do not control, and it is why the
-- extension's README says so out loud - so nobody later "improves" it to thirty days.
--
-- REVOCATION HAS THREE LAYERS, and two are reused rather than rebuilt: the `revoked`
-- flag, `expires_at`, and - the useful one - the EXISTING per-user epoch in
-- `token_denylist`. `revoke_all_for_user` already fires on a password change and on
-- suspension, so offboarding a staff member now also kills every extension token they
-- ever paired, with no new code on that path.

create table if not exists public.operator_tokens (
  id           uuid primary key default gen_random_uuid(),
  -- Keyed to a PERSON. Cascade: the tokens of a deleted user are meaningless.
  user_id      uuid not null references public.users (id) on delete cascade,
  -- O(1) row locator. Leaks nothing on its own - the secret half is never stored.
  token_prefix text not null unique,
  -- sha256 hex of the FULL raw token. A fast hash is correct: the token is high-entropy
  -- random with no brute-forceable structure, and argon2 would break the prefix lookup
  -- while defending against an attack this token shape does not have.
  token_hash   text not null,
  scopes       jsonb not null default '[]',
  label        text not null default '',
  -- "Danyal MacBook / Chrome 131" - so a person can revoke the right one without
  -- guessing. Free text, never parsed.
  device_label text not null default '',
  -- REQUIRED. A device credential with no expiry is a permanent one.
  expires_at   timestamptz not null,
  revoked      boolean not null default false,
  last_used_at timestamptz,
  created_by   uuid references public.users (id) on delete set null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists operator_tokens_user_idx on public.operator_tokens (user_id);
create index if not exists operator_tokens_live_idx
  on public.operator_tokens (expires_at) where not revoked;

alter table public.operator_tokens enable row level security;
alter table public.operator_tokens force row level security;

-- SELF-SERVICE, unlike 0030's owner/admin-only skill tokens, and the difference is
-- deliberate: a skill token is a tenant credential someone grants you, this one is a
-- personal device credential. An operator whose token expires mid-shift at 11pm must be
-- able to pair again without waiting for an owner. Owner/admin still see all of them,
-- which is what makes the board reviewable.
drop policy if exists operator_tokens_select on public.operator_tokens;
create policy operator_tokens_select on public.operator_tokens
  for select using (
    public.current_app_role() in ('owner', 'admin') or user_id = auth.uid()
  );
drop policy if exists operator_tokens_insert on public.operator_tokens;
create policy operator_tokens_insert on public.operator_tokens
  for insert with check (
    public.current_app_role() in ('owner', 'admin') or user_id = auth.uid()
  );
drop policy if exists operator_tokens_update on public.operator_tokens;
create policy operator_tokens_update on public.operator_tokens
  for update
  using (public.current_app_role() in ('owner', 'admin') or user_id = auth.uid())
  with check (public.current_app_role() in ('owner', 'admin') or user_id = auth.uid());

drop trigger if exists operator_tokens_set_updated_at on public.operator_tokens;
create trigger operator_tokens_set_updated_at
  before update on public.operator_tokens
  for each row execute function public.set_updated_at();

comment on table public.operator_tokens is
  'Short-lived, narrowly-scoped device credential for the citation browser extension. '
  'Presented as X-Operator-Token, never as a bearer JWT. The scope vocabulary is closed '
  'so it cannot reach the vault or any tenant-management route.';
