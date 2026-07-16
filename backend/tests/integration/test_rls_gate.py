"""Integration: assert the applied schema has FORCE RLS on every app table.

Runs against the database named by DATABASE_URL (with the migrations applied);
skips otherwise. This is the pytest twin of the CI ``db-rls`` job.
"""

from __future__ import annotations

import os

import pytest

from app.db.rls_check import _CATALOG_SQL, TableRow, find_unprotected


@pytest.mark.integration
def test_every_app_table_has_forced_rls() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        pytest.skip("DATABASE_URL not set")

    import psycopg

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(_CATALOG_SQL)
        rows: list[TableRow] = [(str(r[0]), bool(r[1]), bool(r[2])) for r in cur.fetchall()]

    assert rows, "no public tables found - are the migrations applied?"
    unprotected = find_unprotected(rows)
    assert unprotected == [], f"tables missing FORCE RLS: {unprotected}"
