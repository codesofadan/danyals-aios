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
from uuid import uuid4

import httpx
import pytest
from asgi_lifespan import LifespanManager

from app.config import get_settings
from app.db.database import privileged_connection
from app.main import create_app
from app.routers.public import get_public_audit_enqueuer, get_public_cost_logger

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


async def test_public_funnel_end_to_end() -> None:
    _require_local_stack()
    email = f"lead_{uuid4().hex[:10]}@example.com"

    app = create_app()
    # No live broker / no cost side effects: the DB gateway stays REAL.
    enqueued: list[str] = []
    cost_logged: list[str] = []
    app.dependency_overrides[get_public_audit_enqueuer] = lambda: enqueued.append
    app.dependency_overrides[get_public_cost_logger] = lambda: cost_logged.append

    async with LifespanManager(app):
        try:
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
                # --- POST creates a lead row + token (NO auth header) ---
                first = await ac.post(
                    "/api/v1/public/audits", json={"email": email, "url": _PUBLIC_URL}
                )
                assert first.status_code == 201, first.text
                created = first.json()
                assert set(created) == {"report_token", "status"}  # never the internal id
                assert created["status"] == "queued"
                token = created["report_token"]
                assert len(token) >= 24  # opaque, unguessable capability

                # The lead landed in public_audits with our email + url.
                row = _row_by_email(email)
                assert row is not None
                assert row["url"] == _PUBLIC_URL
                assert row["report_token"] == token
                assert enqueued == [str(row["id"])]  # worker enqueued
                assert cost_logged == [str(row["id"])]  # $0 funnel cost logged

                # --- one-audit-per-email: a SECOND POST same email -> 409 ---
                dup = await ac.post(
                    "/api/v1/public/audits", json={"email": email.upper(), "url": _PUBLIC_URL}
                )
                assert dup.status_code == 409, dup.text
                assert "already exists" in dup.json()["error"]["message"]

                # --- GET {token} -> curated report + fiverr_url, no tenant/internal leak ---
                report = await ac.get(f"/api/v1/public/audits/{token}")
                assert report.status_code == 200, report.text
                body = report.json()
                assert set(body) == {
                    "status", "score", "scores", "has_pdf", "has_report",
                    "url", "when", "fiverr_url",
                }
                assert body["url"] == _PUBLIC_URL
                assert body["fiverr_url"] == get_settings().fiverr_upsell_url
                raw = report.text
                assert str(row["id"]) not in raw  # internal id never exposed
                assert email.lower() not in raw.lower()  # email never exposed

                # --- a random token -> 404 ---
                missing = await ac.get(f"/api/v1/public/audits/{uuid4().hex}")
                assert missing.status_code == 404
        finally:
            _delete_lead(email)


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
