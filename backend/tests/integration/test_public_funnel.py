"""Integration: the PUBLIC free-audit funnel against local Postgres (P6C).

Proves the end-to-end lead path with NO mocks on the DB seam: POST creates a
public_audits lead row + an opaque report_token; a SECOND POST for the same email
is 409; GET {token} returns the curated report + the Fiverr upsell link; a random
token is 404. Also proves tenant isolation structurally: public_audits has NO
client_id column and no FK into any tenant table, and the curated report never
leaks the internal id / email / error / artifact paths - so the public routes
cannot reach clients / users / audits.

The enqueue + cost-log seams are overridden (no live Celery broker needed); the
DB gateway is the REAL privileged path. Auto-skips unless the local DB is
configured. The 3-portal login routing is proven separately in test_auth_login.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import get_settings
from app.db.database import privileged_connection

pytestmark = pytest.mark.integration

# Public IP literal: passes the SSRF guard with no DNS lookup (offline-safe).
_PUBLIC_URL = "http://93.184.216.34"


def _require_local_stack() -> Any:
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")
    return settings


def _delete_lead(email: str) -> None:
    with privileged_connection() as cur:
        cur.execute("delete from public.public_audits where lower(email) = lower(%s)", (email,))


def _row_by_email(email: str) -> dict[str, Any] | None:
    with privileged_connection() as cur:
        cur.execute(
            "select * from public.public_audits where lower(email) = lower(%s) limit 1", (email,)
        )
        return cur.fetchone()


# `test_public_funnel_end_to_end` was removed with the endpoint it drove
# (POST /public/audits, retired 2026-09-17): an operator now runs the audit from
# the dashboard and publishes it as a link, so there is no anonymous create path
# left to walk end to end. The equivalent coverage for the new flow is
# tests/integration/test_audit_public_pages.py.
#
# The structural check below STAYS and is not about the endpoint: `public_audits`
# must remain unable to reach any tenant row, which is what made an
# unauthenticated read of it safe in the first place - and the table, its rows and
# its read routes all still exist.

def test_public_audits_is_structurally_tenant_isolated() -> None:
    """public_audits has NO client_id column and no FK into any tenant table."""
    settings = _require_local_stack()
    import psycopg  # direct connect: this test runs without the app lifespan/pools

    with psycopg.connect(settings.database_admin_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            select column_name from information_schema.columns
            where table_schema = 'public' and table_name = 'public_audits'
            """
        )
        columns = {str(r[0]) for r in cur.fetchall()}
        # No tenant linkage of any kind.
        assert columns, "public_audits must exist"
        assert "client_id" not in columns
        assert "site_id" not in columns

        cur.execute(
            """
            select count(*) from information_schema.table_constraints
            where table_schema = 'public' and table_name = 'public_audits'
              and constraint_type = 'FOREIGN KEY'
            """
        )
        fk = cur.fetchone()
        assert fk is not None and fk[0] == 0  # zero FKs -> no path to a tenant row
