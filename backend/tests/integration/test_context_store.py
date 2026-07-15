"""Integration: the P6B-2 CANONICAL CONTEXT STORE against local Postgres.

Proves the 0014 wiring end-to-end on real SQL (unit tests stop at the SQL shape):

  (a) service_role ``upsert_context`` seeds a client-level ``entity_context`` row
      and a re-upsert BUMPS ``version`` while advancing ``event_watermark`` via
      ``greatest`` (never regresses);
  (b) a staff ``rls_connection`` reads the row (get + list) and its vector ledger;
  (c) a portal CLIENT reads ONLY its OWN client-level summary+facts through the
      ``portal_context`` view - and gets ZERO rows from the ``entity_context`` /
      ``context_vectors`` BASE tables (mirrors test_portal_isolation);
  (d) the client cannot see a SECOND tenant's context through the view;
  (e) the vector ledger round-trips: ``record_vector`` upserts, ``delete_vector``
      returns the deleted row (so the caller GCs Pinecone too), list goes empty.

Skips unless DATABASE_URL + DATABASE_ADMIN_URL are set. Everything is cleaned up
in a finally block.
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import uuid4

import pytest

from app.config import get_settings
from app.db.context_repo import ContextRepo
from app.db.database import (
    build_admin_pool,
    build_rls_pool,
    clear_pools,
    privileged_connection,
    rls_connection,
    set_pools,
)
from app.services.provisioning import provision_user

pytestmark = pytest.mark.integration

_PASSWORD = "Passw0rd!ctx-store-123"


def _require_local_stack() -> Any:
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")
    return settings


async def test_context_store_end_to_end() -> None:
    settings = _require_local_stack()

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

    client_a: str | None = None
    client_b: str | None = None
    uids: list[str] = []
    # A free-standing entity (a plain uuid; entity_id has no FK) for the ledger round-trip.
    free_entity = str(uuid4())
    try:
        with privileged_connection(pool=admin_pool) as cur:
            cur.execute("insert into public.clients (name) values ('Ctx A') returning id")
            client_a = str(cur.fetchone()["id"])
            cur.execute("insert into public.clients (name) values ('Ctx B') returning id")
            client_b = str(cur.fetchone()["id"])

        tag = uuid4().hex[:8]
        uid_client = str(provision_user(
            email=f"ctx-a-{tag}@example.com", password=_PASSWORD, name="Ctx Client",
            role="client", username=f"ctx_a_{tag}", client_id=client_a,
        )["id"])
        uid_staff = str(provision_user(
            email=f"ctx-s-{tag}@example.com", password=_PASSWORD, name="Ctx Staff",
            role="owner", username=f"ctx_s_{tag}", template_key="super",
        )["id"])
        uids += [uid_client, uid_staff]

        staff_repo = ContextRepo(uid_staff)
        client_repo = ContextRepo(uid_client)

        # (a) service_role seeds A's client-level context; watermark advances via greatest.
        first = staff_repo.upsert_context(
            "client", client_a, summary="A summary v1", facts={"tier": "free"},
            event_watermark=5, status="summarized", model="haiku", checksum="cs1",
        )
        assert first["version"] == 0 and int(first["event_watermark"]) == 5

        # A stale watermark must NOT regress (greatest); version still bumps.
        second = staff_repo.upsert_context(
            "client", client_a, summary="A summary v2", facts={"tier": "fully"},
            event_watermark=3, status="summarized", model="haiku", checksum="cs2",
        )
        assert second["version"] == 1 and int(second["event_watermark"]) == 5

        third = staff_repo.upsert_context(
            "client", client_a, summary="A summary v3", facts={"tier": "fully"},
            event_watermark=12, status="summarized", model="haiku", checksum="cs3",
        )
        assert third["version"] == 2 and int(third["event_watermark"]) == 12

        # Seed B's context so the cross-tenant view test has something to (not) see.
        staff_repo.upsert_context(
            "client", client_b, summary="B PRIVATE summary", facts={"secret": "B"},
            event_watermark=1, status="summarized",
        )

        # (b) staff read the row + the ledger via RLS.
        got = staff_repo.get_entity_context("client", client_a)
        assert got is not None and got["summary"] == "A summary v3"
        listed = staff_repo.list_contexts("client")
        assert {str(r["entity_id"]) for r in listed} >= {client_a, client_b}

        # Seed a vector ledger row for A (service_role).
        staff_repo.record_vector(
            "client", client_a, chunk_key="summary", pinecone_id=f"client:{client_a}#summary",
            content_checksum="v-cs1", version=2, dim=1024, model="voyage-3",
        )
        assert len(staff_repo.list_vectors("client", client_a)) == 1

        # (c) the portal CLIENT reads ONLY its own client-level summary+facts.
        portal = client_repo.read_portal_context()
        assert portal is not None
        assert portal["summary"] == "A summary v3"
        assert portal["facts"] == {"tier": "fully"}
        assert "event_watermark" not in portal and "version" not in portal  # view omits internals

        # ...and gets ZERO rows from the BASE tables (no client select policy).
        assert _probe(uid_client, "select * from public.entity_context") == []
        assert _probe(uid_client, "select * from public.context_vectors") == []

        # (d) the client cannot reach B's context through the view (self-filtered to A).
        assert "B PRIVATE" not in (portal["summary"] or "")
        # The base-table probe already returns 0 rows, so B is doubly unreachable.

        # (e) vector ledger round-trip on a free-standing entity.
        staff_repo.record_vector(
            "client", free_entity, chunk_key="facts:seo", pinecone_id="client:free#facts",
            content_checksum="f-cs1", version=1, dim=1024, model="voyage-3",
        )
        deleted = staff_repo.delete_vector("client", free_entity, "facts:seo")
        assert deleted is not None and deleted["pinecone_id"] == "client:free#facts"
        assert staff_repo.list_vectors("client", free_entity) == []
    finally:
        with contextlib.suppress(Exception), privileged_connection(pool=admin_pool) as cur:
            cur.execute(
                "delete from public.context_vectors where entity_id = any(%s::uuid[])",
                ([x for x in (client_a, client_b, free_entity) if x],),
            )
            cur.execute(
                "delete from public.entity_context where entity_id = any(%s::uuid[])",
                ([x for x in (client_a, client_b, free_entity) if x],),
            )
            for uid in uids:
                cur.execute("delete from auth.users where id = %s", (uid,))
            for cid in (client_a, client_b):
                if cid:
                    cur.execute("delete from public.clients where id = %s", (cid,))
        clear_pools()
        rls_pool.close()
        admin_pool.close()
