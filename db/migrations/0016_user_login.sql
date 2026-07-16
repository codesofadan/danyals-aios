-- 0016_user_login.sql - local username login key for the 3 portals (P6A-7).
--
-- The AUTH CUTOVER (P6A-7) replaces Supabase GoTrue with local username/password
-- login. Every login - admin, team, and client portal - resolves a user by
-- USERNAME (case-insensitively), then verifies the argon2 hash held in
-- auth.users. The uuid PK is UNCHANGED and stays the identity RLS/auth.uid()
-- compare against; username is only the human-facing login key.
--
-- Nullable + a PARTIAL unique index (WHERE username is not null): existing rows
-- may pre-date a username, but any two present usernames must be unique
-- case-insensitively (lower(username)), so "Owner" and "owner" cannot collide.
-- This column is NOT a tenant boundary and does not change any RLS policy, so the
-- 12-table RLS gate is unaffected. Idempotent (safe to re-run).

alter table public.users add column if not exists username text;

create unique index if not exists users_username_key
  on public.users (lower(username))
  where username is not null;
