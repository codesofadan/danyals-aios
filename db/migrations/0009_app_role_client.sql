-- 0009_app_role_client.sql - add the 'client' label to the app_role enum.
--
-- This migration exists ON ITS OWN, and MUST be applied + COMMITTED before 0010,
-- because PostgreSQL forbids using a freshly-added enum label in the SAME
-- transaction that adds it (error 55P04 "unsafe use of new value ... of enum
-- type"). Splitting the ADD VALUE into its own committed migration lets 0010
-- reference 'client' safely.
--
-- 'client' is a SEVENTH role that sits OUTSIDE the 6-role governance matrix
-- (owner/admin/manager/specialist/analyst/viewer). It is a portal login scoped
-- to a single clients row; it holds NONE of the staff permissions and is guarded
-- out of every staff surface in code (app/rbac/matrix.py) and in the DB
-- (public.is_staff() excludes it - see 0010). The governance matrix in
-- app/rbac/matrix.py (AppRole) deliberately stays the 6 staff roles.

alter type public.app_role add value if not exists 'client';
