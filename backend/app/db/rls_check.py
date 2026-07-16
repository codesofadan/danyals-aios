"""RLS coverage gate.

Fails if any base table in the application schema (``public``) lacks BOTH
row-level security *enabled* and *forced*. ``FORCE`` is the load-bearing part:
without it the table owner - and Supabase's ``service_role``, which owns the
schema - silently bypasses every policy, so a bug in server code could read
across tenants even though "RLS is on".

``find_unprotected`` is a pure function (unit-tested). ``main`` connects to the
database named by ``DATABASE_URL`` and is exercised only in CI/integration
against an ephemeral Postgres that has the migrations applied.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable

# One row per base table: (table_name, rls_enabled, rls_forced).
TableRow = tuple[str, bool, bool]

# Base tables in the app schema with their RLS flags. Excludes views/sequences
# (relkind='r' only) and never touches the internal pg_* / auth schemas.
_CATALOG_SQL = """
select c.relname, c.relrowsecurity, c.relforcerowsecurity
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relkind = 'r'
order by c.relname
"""


def find_unprotected(
    rows: Iterable[TableRow], allowlist: frozenset[str] = frozenset()
) -> list[str]:
    """Return names of tables missing enabled+forced RLS (excluding ``allowlist``)."""
    return [
        name
        for (name, rls_enabled, rls_forced) in rows
        if name not in allowlist and not (rls_enabled and rls_forced)
    ]


def main() -> int:
    """Connect to ``DATABASE_URL`` and exit non-zero if any table is unprotected."""
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL not set; cannot run the RLS gate.", file=sys.stderr)
        return 2

    import psycopg  # lazy: only CI/integration installs and runs the driver

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(_CATALOG_SQL)
        rows: list[TableRow] = [(str(r[0]), bool(r[1]), bool(r[2])) for r in cur.fetchall()]

    offenders = find_unprotected(rows)
    if offenders:
        print("RLS gate FAILED - tables without FORCE row-level security:", file=sys.stderr)
        for name in offenders:
            print(f"  - public.{name}", file=sys.stderr)
        return 1
    print(f"RLS gate passed: {len(rows)} table(s) checked, all have FORCE RLS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
