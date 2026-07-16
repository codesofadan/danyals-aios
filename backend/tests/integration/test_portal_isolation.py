"""Integration: prove the client trust boundary against LOCAL Postgres.

Skips unless DATABASE_URL + DATABASE_ADMIN_URL are set (migrations 0009 + 0010
applied). Provisions two client tenants (A, B) + one staff user, seeds an audit
per tenant carrying sensitive columns, then asserts the tenant boundary the same
way the Supabase suite did - but against the LOCAL data plane.

The "direct-authenticated-role" probe replaces the old "PostgREST with the
client's JWT". A leaked portal credential would still connect only as the
``authenticated`` role with that user's identity bound; ``rls_connection(uid)``
reproduces exactly that (role ``authenticated`` + ``set_config('app.user_id',
uid, true)`` so ``auth.uid()`` returns it), so RLS - not FastAPI - is the boundary
under test. Every assertion from the Supabase version is preserved:

  (a) A's portal_audits view shows only A's audit (no sensitive columns);
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

from app.config import get_settings
from app.db.database import (
    build_admin_pool,
    build_rls_pool,
    clear_pools,
    privileged_connection,
    rls_connection,
    set_pools,
)
from app.db.portal_repo import PortalRepo
from app.routers.admin_users import _fetch_all_users
from app.schemas.audits import PortalAuditCreate
from app.services.client_audits import create_client_audit, insert_audit_row
from app.services.provisioning import provision_user

pytestmark = pytest.mark.integration

# A public IP literal: passes the SSRF guard with NO DNS lookup (offline-safe).
_PUBLIC_URL = "http://93.184.216.34"
_PASSWORD = "Passw0rd!portal-iso-123"

# Sensitive columns a client must NEVER be able to read.
_SENSITIVE = ("cost", "error", "pdf_path", "json_path", "run_uuid", "artifact_dir")


def _require_local_stack() -> Any:
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")
    return settings


async def test_client_isolation_end_to_end() -> None:
    _require_local_stack()
    settings = get_settings()

    rls_pool = build_rls_pool(settings.database_url)
    admin_pool = build_admin_pool(settings.database_admin_url)
    assert rls_pool is not None and admin_pool is not None
    rls_pool.open()
    admin_pool.open()
    set_pools(rls_pool, admin_pool)

    def _probe(uid: str, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """SELECT as role ``authenticated`` with ``uid`` bound as the RLS identity."""
        with rls_connection(uid, pool=rls_pool) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    audit_ids: list[str] = []
    client_a: str | None = None
    client_b: str | None = None
    uids: list[str] = []
    try:
        with privileged_connection(pool=admin_pool) as cur:
            # --- two tenants; A is delivery_tier 'free' (for the paid-block probe) ---
            cur.execute(
                "insert into public.clients (name, delivery_tier, mrr) "
                "values ('Iso A', 'free', 999) returning id"
            )
            client_a = str(cur.fetchone()["id"])
            cur.execute(
                "insert into public.clients (name, delivery_tier, mrr) "
                "values ('Iso B', 'fully', 777) returning id"
            )
            client_b = str(cur.fetchone()["id"])

            cur.execute("insert into public.sites (client_id, domain) values (%s, 'iso-a.com')", (client_a,))
            cur.execute("insert into public.sites (client_id, domain) values (%s, 'iso-b.com')", (client_b,))

            # seed one audit per tenant WITH sensitive columns populated
            def _seed(cur: Any, cid: str, name: str) -> str:
                cur.execute(
                    "insert into public.audits "
                    "(client_id, client_name, url, types, tier, status, score, cost, error, "
                    " pdf_path, json_path, run_uuid, artifact_dir) "
                    "values (%s, %s, %s, %s, 'free', 'done', 80, 12.5, 'internal detail', "
                    "%s, %s, %s, %s) returning id",
                    (cid, name, f"{name}.com", ["technical"],
                     f"/srv/{name}.pdf", f"/srv/{name}.json", f"uuid-{name}", f"/srv/{name}"),
                )
                aid = str(cur.fetchone()["id"])
                audit_ids.append(aid)
                return aid

            audit_a = _seed(cur, client_a, "isoa")
            audit_b = _seed(cur, client_b, "isob")

        # --- portal logins for A and B + a staff owner ---
        tag = uuid4().hex[:8]
        uid_a = str(provision_user(
            email=f"iso-a-{tag}@example.com", password=_PASSWORD, name="A Login",
            role="client", username=f"iso_a_{tag}", client_id=client_a,
        )["id"])
        uid_b = str(provision_user(
            email=f"iso-b-{tag}@example.com", password=_PASSWORD, name="B Login",
            role="client", username=f"iso_b_{tag}", client_id=client_b,
        )["id"])
        uid_staff = str(provision_user(
            email=f"iso-s-{tag}@example.com", password=_PASSWORD, name="Iso Staff",
            role="owner", username=f"iso_s_{tag}", template_key="super",
        )["id"])
        uids += [uid_a, uid_b, uid_staff]

        # (a) A's view shows only A's audit, and NONE of the sensitive columns.
        a_view = _probe(uid_a, "select * from public.portal_audits")
        assert [str(r["id"]) for r in a_view] == [audit_a]
        assert all(col not in a_view[0] for col in _SENSITIVE)
        assert a_view[0]["has_pdf"] is True  # presence surfaced as a boolean only

        # (b) A cannot see B's audit through the view.
        assert _probe(uid_a, "select * from public.portal_audits where id = %s", (audit_b,)) == []

        # (c) A gets ZERO rows from the BASE tables (RLS default-deny; no client
        #     select policy), and cannot read the sensitive columns either.
        assert _probe(uid_a, "select * from public.audits") == []
        assert _probe(uid_a, "select * from public.clients") == []
        assert _probe(uid_a, "select * from public.sites") == []
        assert _probe(uid_a, "select mrr from public.clients") == []
        assert _probe(uid_a, "select cost, error, pdf_path from public.audits") == []

        # (e) A is delivery_tier 'free' => a Paid audit is blocked (403), via the
        #     real portal_client view read inside the service.
        reader_a = PortalRepo(uid_a)
        scoped_a = _scoped(uid_a, client_a)
        with pytest.raises(HTTPException) as exc:
            await create_client_audit(
                insert_audit=insert_audit_row, reader=reader_a, scoped=scoped_a,
                body=PortalAuditCreate(url=_PUBLIC_URL, tier="Paid", types=["technical"]),
                enqueue=lambda _id: None,
            )
        assert exc.value.status_code == 403

        # (d) a Free audit is written with client_id pinned to A.
        created = await create_client_audit(
            insert_audit=insert_audit_row, reader=reader_a, scoped=scoped_a,
            body=PortalAuditCreate(url=_PUBLIC_URL, tier="Free", types=["technical"]),
            enqueue=lambda _id: None,
        )
        audit_ids.append(str(created["id"]))
        assert str(created["client_id"]) == client_a

        # (f) staff still read EVERY tenant's audits.
        staff_ids = {str(r["id"]) for r in _probe(uid_staff, "select id from public.audits")}
        assert audit_a in staff_ids and audit_b in staff_ids

        # (g) client rows never appear in the staff roster query.
        roster = _fetch_all_users(uid_staff)
        assert roster and all(r["role"] != "client" for r in roster)

        # (h) the RLS coverage gate is green (base tables all FORCE RLS).
        dsn = os.environ.get("DATABASE_URL")
        if dsn:
            import psycopg

            from app.db.rls_check import _CATALOG_SQL, TableRow, find_unprotected

            with psycopg.connect(dsn) as conn, conn.cursor() as pc:
                pc.execute(_CATALOG_SQL)
                rows: list[TableRow] = [(str(r[0]), bool(r[1]), bool(r[2])) for r in pc.fetchall()]
            assert find_unprotected(rows) == []
    finally:
        with contextlib.suppress(Exception), privileged_connection(pool=admin_pool) as cur:
            for aid in audit_ids:
                cur.execute("delete from public.audits where id = %s", (aid,))
            for uid in uids:
                cur.execute("delete from auth.users where id = %s", (uid,))
            for cid in (client_a, client_b):
                if cid:
                    cur.execute("delete from public.clients where id = %s", (cid,))
        clear_pools()
        rls_pool.close()
        admin_pool.close()


def _scoped(user_id: str, client_id: str) -> Any:
    from app.core.auth import CurrentClient, CurrentUser

    user = CurrentUser(
        id=user_id, email="portal@x.com", role="client", status="active",
        name="Portal", title="", avatar_color="#000", phone="", two_fa=False,
        client_id=client_id,
    )
    return CurrentClient(user=user, client_id=client_id)
