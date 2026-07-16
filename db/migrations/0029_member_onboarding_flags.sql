-- 0029_member_onboarding_flags.sql - first-login onboarding flags for the
-- Add-Member credential-generation flow (Part 7 / 7F-4).
--
-- When a super-admin invites a team member the API generates a username + a
-- STRONG one-time password (shown to the admin exactly once, only the argon2id
-- hash is stored). Such an account must be forced to (a) reset that temporary
-- password and (b) enrol 2FA on first sign-in. Those two intentions are per-user
-- state, so they live here as boolean columns on public.users rather than in the
-- static RBAC reference data.
--
-- ``two_fa`` (0002) records whether 2FA is CURRENTLY enrolled; ``must_setup_2fa``
-- records that enrolment is REQUIRED at next login - the two are orthogonal (a
-- fresh invite has two_fa=false AND must_setup_2fa=true). Both default false so
-- existing rows and the ordinary explicit-password provisioning path are
-- unchanged. Neither column is a tenant boundary, so no RLS policy changes and
-- the RLS gate is unaffected. Idempotent (safe to re-run).

alter table public.users
  add column if not exists must_reset boolean not null default false;

alter table public.users
  add column if not exists must_setup_2fa boolean not null default false;

comment on column public.users.must_reset is
  'Force a password reset on next sign-in (set for generated one-time credentials).';
comment on column public.users.must_setup_2fa is
  'Require 2FA enrolment on next sign-in (set for generated one-time credentials).';
