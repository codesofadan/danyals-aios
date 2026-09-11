-- 0131_extension_installs.sql - an INSTALLATION identity under the 12-hour token.
--
-- 0112 gave the citation extension a deliberately short-lived credential: twelve hours,
-- because `chrome.storage.local` is plaintext on disk. What it did not give the operator
-- is continuity - every shift starts with a copy-paste from the dashboard. The redesign
-- (plan §8, Area C) keeps the short token and adds the thing the token was too short to
-- be: a 30-day INSTALLATION identity that successive tokens chain under.
--
--   install  : active -> revoked | expired (pairing_expires_at, default +30d)
--   token    : live -> rotated -> (reuse of a rotated token => install-wide revocation)
--              | revoked | expired (12h)
--
-- ROTATION, NOT REFRESH TOKENS. There is no second credential class to steal: the access
-- token itself is exchanged for its successor (`rotated_to` / `rotated_at` record the
-- chain), and a presented token whose `rotated_at` is set is by definition either a
-- replay or a theft - the legitimate holder already holds the successor. The response is
-- to revoke EVERY token on that install and the install itself: blast radius is the
-- device, never the operator's dashboard session (the per-user Redis epoch is
-- deliberately NOT bumped on this path).
--
-- Idempotent throughout, per the house rule (if not exists / drop ... if exists).

begin;

create table if not exists public.extension_installs (
  id                 uuid primary key default gen_random_uuid(),
  -- Keyed to a PERSON, exactly like the tokens that chain under it. Cascade: the
  -- installs of a deleted user identify nothing.
  user_id            uuid not null references public.users (id) on delete cascade,
  -- "Danyal MacBook / Chrome 131" - free text, never parsed; copied onto each token.
  device_label       text not null default '',
  created_at         timestamptz not null default now(),
  -- Touched on every successful rotation, so the board can show a device is alive.
  last_seen_at       timestamptz,
  -- The OUTER bound. Rotation extends nothing past this: after 30 days the operator
  -- re-pairs by hand, which is the periodic human checkpoint the design wants.
  pairing_expires_at timestamptz not null default (now() + interval '30 days'),
  revoked            boolean not null default false
);

create index if not exists extension_installs_user_idx
  on public.extension_installs (user_id);

alter table public.extension_installs enable row level security;
alter table public.extension_installs force row level security;

-- The 0112 policy shape, deliberately: an install is a personal device identity, so
-- self-service like the tokens (an operator re-pairs at 11pm without waiting for an
-- owner), while owner/admin see and manage all of them. NO delete policy: a revoked
-- install is the audit record of a device that existed; under FORCE RLS a policy-less
-- DELETE matches zero rows.
drop policy if exists extension_installs_select on public.extension_installs;
create policy extension_installs_select on public.extension_installs
  for select using (
    public.current_app_role() in ('owner', 'admin') or user_id = auth.uid()
  );
drop policy if exists extension_installs_insert on public.extension_installs;
create policy extension_installs_insert on public.extension_installs
  for insert with check (
    public.current_app_role() in ('owner', 'admin') or user_id = auth.uid()
  );
drop policy if exists extension_installs_update on public.extension_installs;
create policy extension_installs_update on public.extension_installs
  for update
  using (public.current_app_role() in ('owner', 'admin') or user_id = auth.uid())
  with check (public.current_app_role() in ('owner', 'admin') or user_id = auth.uid());

comment on table public.extension_installs is
  'A 30-day installation identity for one browser extension install. Successive 12h '
  'operator_tokens chain under it via install_id/rotated_to; replaying a rotated token '
  'revokes the whole install. Re-pairing after pairing_expires_at is deliberate.';

-- --------------------------------------------------------------------------- --
-- The token side of the chain.
-- --------------------------------------------------------------------------- --
alter table public.operator_tokens
  add column if not exists install_id uuid references public.extension_installs (id) on delete cascade;
-- The successor, recorded on the OLD row at rotation time. `rotated_at is not null` is
-- the reuse tripwire; `rotated_to` is the forensic pointer. Plain NO ACTION reference:
-- the only delete path is the user cascade, which removes the whole chain in one
-- statement.
alter table public.operator_tokens
  add column if not exists rotated_to uuid references public.operator_tokens (id);
alter table public.operator_tokens
  add column if not exists rotated_at timestamptz;

-- Reuse detection revokes by install; make that one update indexed.
create index if not exists operator_tokens_install_idx
  on public.operator_tokens (install_id);

-- --------------------------------------------------------------------------- --
-- The closed vocabulary widens (0115 §3 dropped and re-added, same constraint name).
-- Legacy `citation_queue` stays legal so existing paired tokens keep working until
-- their natural 12h expiry; new mints get the granular values.
-- --------------------------------------------------------------------------- --
alter table public.operator_tokens
  drop constraint if exists operator_tokens_scopes_closed;
alter table public.operator_tokens
  add constraint operator_tokens_scopes_closed check (
    jsonb_typeof(scopes) = 'array'
    and scopes <@ '["citation_queue","citation_credential","citation_queue:read","citation_queue:write","client_profile:read","web2_queue:read","web2_queue:write"]'::jsonb
  );

commit;
