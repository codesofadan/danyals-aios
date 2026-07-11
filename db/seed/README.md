# seed

Optional seed / fixture data, applied **after** the migrations.

There is intentionally little to seed: roles, permissions, features, role
templates, and the cost-dial/tier metadata are **static reference data in code**
(`backend/app/rbac/matrix.py`, `app/schemas/{cost,tiers}.py`), not tables. The
`cost_settings` singleton row is created by its migration.

The **first super-admin** is not seeded here (it needs a Supabase Auth user):
provision it once via the admin API / a one-off `provision_user(...)` call with
the service_role key. Thereafter every login is created through the app's
provisioning endpoint (no public signup).
