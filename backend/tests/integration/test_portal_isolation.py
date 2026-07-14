"""Integration: prove the client trust boundary against a real Supabase project.

Skips unless SUPABASE_URL + service_role + anon keys are set AND migrations 0009+
0010 are applied. Provisions two client tenants (A, B) + one staff user, seeds an
audit per tenant carrying sensitive columns, then asserts - via a client's OWN
JWT hitting PostgREST directly (RLS is the boundary, not FastAPI):

  (a) A's portal_audits view shows only A's audit;
  (b) A cannot see B's audit through the view (0 rows for a foreign id);
  (c) A gets ZERO rows from the audits/clients/sites BASE tables and cannot read
      mrr/cost/error/*_path (the views omit them entirely);
  (d) a portal-run Free audit is written with client_id = A (never body-driven);
  (e) A's delivery_tier='free' blocks a Paid audit (403);
  (f) staff still read every tenant's audits;
  (g) client rows never appear in the staff roster query;
  (h) the RLS coverage gate is green.

Everything created is cleaned up in a finally block.
"""

from __future__ import annotations

import contextlib
import os
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from supabase import create_client

from app.config import get_settings
from app.core.auth import CurrentClient, CurrentUser
from app.db.portal_repo import PortalRepo
from app.db.supabase import client_for_user, get_admin_client
from app.routers.admin_users import _fetch_all_users
from app.schemas.audits import PortalAuditCreate
from app.services.client_audits import create_client_audit
from app.services.provisioning import provision_user

# A public IP literal: passes the SSRF guard with NO DNS lookup (offline-safe).
_PUBLIC_URL = "http://93.184.216.34"
_PASSWORD = "Passw0rd!portal-iso-123"

# Sensitive columns a client must NEVER be able to read.
_SENSITIVE = ("cost", "error", "pdf_path", "json_path", "run_uuid", "artifact_dir")


def _require_supabase() -> Any:
    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_service_role_key and settings.supabase_anon_key):
        pytest.skip("Supabase not configured (SUPABASE_URL + keys)")
    return settings


def _scoped(user_id: str, client_id: str) -> CurrentClient:
    user = CurrentUser(
        id=user_id, email="portal@x.com", role="client", status="active",
        name="Portal", title="", avatar_color="#000", phone="", two_fa=False,
        client_id=client_id,
    )
    return CurrentClient(user=user, client_id=client_id)


@pytest.mark.integration
async def test_client_isolation_end_to_end() -> None:
    settings = _require_supabase()
    admin = get_admin_client()
    anon = create_client(settings.supabase_url, settings.supabase_anon_key.get_secret_value())

    audit_ids: list[str] = []
    client_a: str | None = None
    client_b: str | None = None
    uid_a: str | None = None
    uid_b: str | None = None
    uid_staff: str | None = None
    try:
        # --- two tenants; A is delivery_tier 'free' (for the paid-block probe) ---
        client_a = admin.table("clients").insert(
            {"name": "Iso A", "delivery_tier": "free", "mrr": 999}
        ).execute().data[0]["id"]
        client_b = admin.table("clients").insert(
            {"name": "Iso B", "delivery_tier": "fully", "mrr": 777}
        ).execute().data[0]["id"]

        admin.table("sites").insert({"client_id": client_a, "domain": "iso-a.com"}).execute()
        admin.table("sites").insert({"client_id": client_b, "domain": "iso-b.com"}).execute()

        # seed one audit per tenant WITH sensitive columns populated
        def _seed(cid: str, name: str) -> str:
            row = admin.table("audits").insert(
                {
                    "client_id": cid, "client_name": name, "url": f"{name}.com",
                    "types": ["technical"], "tier": "free", "status": "done", "score": 80,
                    "cost": 12.5, "error": "internal detail", "pdf_path": f"/srv/{name}.pdf",
                    "json_path": f"/srv/{name}.json", "run_uuid": f"uuid-{name}",
                    "artifact_dir": f"/srv/{name}",
                }
            ).execute().data[0]
            audit_ids.append(row["id"])
            return str(row["id"])

        audit_a = _seed(client_a, "isoa")
        audit_b = _seed(client_b, "isob")

        # --- portal logins for A and B + a staff owner ---
        email_a = f"iso-a-{uuid4().hex}@example.com"
        email_b = f"iso-b-{uuid4().hex}@example.com"
        email_s = f"iso-s-{uuid4().hex}@example.com"
        uid_a = provision_user(
            admin, email=email_a, password=_PASSWORD, name="A Login", role="client", client_id=client_a
        )["id"]
        uid_b = provision_user(
            admin, email=email_b, password=_PASSWORD, name="B Login", role="client", client_id=client_b
        )["id"]
        uid_staff = provision_user(
            admin, email=email_s, password=_PASSWORD, name="Iso Staff", role="owner"
        )["id"]

        a_token = anon.auth.sign_in_with_password({"email": email_a, "password": _PASSWORD}).session.access_token
        s_token = anon.auth.sign_in_with_password({"email": email_s, "password": _PASSWORD}).session.access_token
        a = client_for_user(a_token)

        # (a) A's view shows only A's audit, and NONE of the sensitive columns.
        a_view = a.table("portal_audits").select("*").execute().data
        assert [r["id"] for r in a_view] == [audit_a]
        assert all(col not in a_view[0] for col in _SENSITIVE)
        assert a_view[0]["has_pdf"] is True  # presence surfaced as a boolean only

        # (b) A cannot see B's audit through the view.
        assert a.table("portal_audits").select("*").eq("id", audit_b).execute().data == []

        # (c) A gets ZERO rows from the BASE tables (RLS default-deny; no client
        #     select policy), and cannot read the sensitive columns either.
        assert a.table("audits").select("*").execute().data == []
        assert a.table("clients").select("*").execute().data == []
        assert a.table("sites").select("*").execute().data == []
        assert a.table("clients").select("mrr").execute().data == []
        assert a.table("audits").select("cost, error, pdf_path").execute().data == []

        # (e) A is delivery_tier 'free' => a Paid audit is blocked (403), via the
        #     real portal_client view read inside the service.
        reader_a = PortalRepo(a_token)
        scoped_a = _scoped(str(uid_a), client_a)
        with pytest.raises(HTTPException) as exc:
            await create_client_audit(
                admin=admin, reader=reader_a, scoped=scoped_a,
                body=PortalAuditCreate(url=_PUBLIC_URL, tier="Paid", types=["technical"]),
                enqueue=lambda _id: None,
            )
        assert exc.value.status_code == 403

        # (d) a Free audit is written with client_id pinned to A.
        created = await create_client_audit(
            admin=admin, reader=reader_a, scoped=scoped_a,
            body=PortalAuditCreate(url=_PUBLIC_URL, tier="Free", types=["technical"]),
            enqueue=lambda _id: None,
        )
        audit_ids.append(str(created["id"]))
        assert created["client_id"] == client_a

        # (f) staff still read EVERY tenant's audits.
        s = client_for_user(s_token)
        staff_ids = {r["id"] for r in s.table("audits").select("id").execute().data}
        assert audit_a in staff_ids and audit_b in staff_ids

        # (g) client rows never appear in the staff roster query.
        roster = _fetch_all_users(s_token)
        assert roster and all(r["role"] != "client" for r in roster)

        # (h) the RLS coverage gate is green (base tables all FORCE RLS).
        dsn = os.environ.get("DATABASE_URL")
        if dsn:
            import psycopg

            from app.db.rls_check import _CATALOG_SQL, TableRow, find_unprotected

            with psycopg.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(_CATALOG_SQL)
                rows: list[TableRow] = [(str(r[0]), bool(r[1]), bool(r[2])) for r in cur.fetchall()]
            assert find_unprotected(rows) == []
    finally:
        for aid in audit_ids:
            admin.table("audits").delete().eq("id", aid).execute()
        for cid in (client_a, client_b):
            if cid:
                admin.table("clients").delete().eq("id", cid).execute()
        for uid in (uid_a, uid_b, uid_staff):
            if uid:
                with contextlib.suppress(Exception):  # best-effort cleanup
                    admin.auth.admin.delete_user(uid)
