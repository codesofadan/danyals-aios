"""P6B-9 integration: the freshness suite's PG-backed proofs (the unit half lives
in ``tests/test_context_freshness.py``). Runs against local Postgres with the
deterministic fakes; auto-skips when the DB DSNs are unset.

Two "how you check freshness" stories on real SQL + RLS + the real app:

* **``GET /context/health`` reflects staleness.** Seed activity -> the 0013 trigger
  enqueues a dirty row -> fold (fakes) -> the entity is summarized, lag 0. Append a
  NEW activity -> the per-entity ``.../health`` shows lag>0 + stale, and the ORG
  rollup ``/context/health`` reports ``worst_lag >= that lag``. Run the worker fold
  again -> the per-entity lag is back to 0 (the invariant restored).
* **The reconcile sweep runs against the real ledger.** A folded entity's ledger +
  the InMemory store agree (``reconcile`` healthy); an injected orphan/missing is
  flagged; ``distinct_vector_entities`` includes the entity so the scheduled sweep
  would walk it.
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import uuid4

import httpx
import pytest
from asgi_lifespan import LifespanManager

from app.config import get_settings
from app.db.context_repo import service_context_repo
from app.db.database import privileged_connection
from app.main import create_app
from app.services.context_vectorsync import namespace_for, pinecone_id_for, reconcile
from app.services.provisioning import provision_user
from integrations.context_providers import providers_for_tests
from integrations.vectorstore import VectorItem
from workers.tasks.context import execute_compaction

pytestmark = pytest.mark.integration

_PASSWORD = "Passw0rd!ctx-fresh-123"


def _require_local_stack() -> Any:
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")
    if not (settings.jwt_private_key_pem and settings.jwt_public_key_pem):
        pytest.skip("signing keypair not configured (JWT_PRIVATE_KEY + JWT_PUBLIC_KEY)")
    return settings


def _insert_event(cur: Any, *, kind: str, action: str, target: str, meta: str | None, entity_id: str) -> int:
    cur.execute(
        "insert into public.activity_log (actor_name, kind, action, target, meta, entity_type, entity_id) "
        "values ('Ctx Fresh Bot', %(kind)s, %(action)s, %(target)s, %(meta)s, "
        "'client'::public.context_entity, %(entity_id)s) returning seq",
        {"kind": kind, "action": action, "target": target, "meta": meta, "entity_id": entity_id},
    )
    return int(cur.fetchone()["seq"])


async def _login(ac: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await ac.post("/api/v1/auth/login", json={"username": username, "password": _PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_context_health_reflects_staleness_and_lag_returns_to_zero() -> None:
    settings = _require_local_stack()
    tag = uuid4().hex[:8]
    app = create_app()

    client_id: str | None = None
    uids: list[str] = []
    async with LifespanManager(app):
        try:
            with privileged_connection() as cur:
                cur.execute("insert into public.clients (name) values (%s) returning id", (f"Ctx Fresh {tag}",))
                client_id = str(cur.fetchone()["id"])

            staff_name = f"ctx_fresh_staff_{tag}"
            uid_staff = str(provision_user(
                email=f"{staff_name}@x.com", password=_PASSWORD, name="Fresh Staff",
                role="owner", username=staff_name, template_key="super",
            )["id"])
            uids.append(uid_staff)
            entity = ("client", client_id)

            # Seed activity -> the trigger enqueues -> fold (fakes) -> summarized, lag 0.
            with privileged_connection() as cur:
                seq1 = _insert_event(cur, kind="client", action=f"set tier {tag}",
                                     target="acme", meta="Growth", entity_id=client_id)
            out = execute_compaction(service_context_repo(), providers_for_tests(), *entity, settings=settings)
            assert out.state == "summarized" and out.watermark == seq1

            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                staff = await _login(ac, staff_name)

                # Caught up: per-entity health is fresh (the invariant holds).
                h0 = (await ac.get(f"/api/v1/context/client/{client_id}/health", headers=staff)).json()
                assert h0["lag"] == 0 and h0["stale"] is False and h0["status"] == "summarized"

                # A NEW activity makes it stale; per-entity health reports lag>0.
                with privileged_connection() as cur:
                    seq2 = _insert_event(cur, kind="task", action=f"closed {tag}",
                                         target="onboarding", meta=None, entity_id=client_id)
                h1 = (await ac.get(f"/api/v1/context/client/{client_id}/health", headers=staff)).json()
                assert h1["latest_seq"] == seq2
                entity_lag = h1["lag"]
                assert entity_lag > 0 and h1["stale"] is True

                # The ORG rollup /context/health EXPOSES the freshness surface and its
                # worst_lag is at least this entity's lag (the "how you check" glance).
                org = (await ac.get("/api/v1/context/health", headers=staff)).json()
                assert set(org) >= {"total", "stale", "degraded", "error", "worst_lag"}
                assert org["total"] >= 1 and org["stale"] >= 1
                assert org["worst_lag"] >= entity_lag

                # Run the worker fold again -> lag returns to 0 (invariant restored).
                out2 = execute_compaction(service_context_repo(), providers_for_tests(), *entity, settings=settings)
                assert out2.state == "summarized" and out2.watermark == seq2
                h2 = (await ac.get(f"/api/v1/context/client/{client_id}/health", headers=staff)).json()
                assert h2["event_watermark"] == seq2 and h2["latest_seq"] == seq2
                assert h2["lag"] == 0 and h2["stale"] is False
        finally:
            with contextlib.suppress(Exception), privileged_connection() as cur:
                if client_id:
                    cur.execute("delete from public.context_vectors where entity_id = %s", (client_id,))
                    cur.execute("delete from public.entity_context where entity_id = %s", (client_id,))
                    cur.execute("delete from public.context_dirty where entity_id = %s", (client_id,))
                cur.execute("delete from public.activity_log where action like %s", (f"%{tag}%",))
                for uid in uids:
                    cur.execute("delete from auth.users where id = %s", (uid,))
                if client_id:
                    cur.execute("delete from public.clients where id = %s", (client_id,))


async def test_reconcile_against_real_ledger_detects_and_lists_entity() -> None:
    settings = _require_local_stack()
    tag = uuid4().hex[:8]
    app = create_app()

    client_id: str | None = None
    async with LifespanManager(app):
        try:
            with privileged_connection() as cur:
                cur.execute("insert into public.clients (name) values (%s) returning id", (f"Ctx Recon {tag}",))
                client_id = str(cur.fetchone()["id"])
            entity = ("client", client_id)

            with privileged_connection() as cur:
                _insert_event(cur, kind="client", action=f"set tier {tag}", target="acme",
                              meta="Growth", entity_id=client_id)
                _insert_event(cur, kind="audit", action=f"ran audit {tag}", target="https://x.test",
                              meta="80", entity_id=client_id)

            providers = providers_for_tests()
            repo = service_context_repo()
            execute_compaction(repo, providers, *entity, settings=settings)
            vstore = providers.vector_store
            namespace = namespace_for(*entity)

            # The scheduled sweep would walk this entity (it now has ledger rows).
            assert entity in repo.distinct_vector_entities()

            # Healthy: the real ledger and the store agree.
            assert reconcile(*entity, store=vstore, ledger=repo).healthy

            # Inject an orphan + a missing -> reconcile flags each against real PG.
            vstore.upsert(namespace, [VectorItem(
                id=f"client:{client_id}#ghost", vector=providers.embedder.embed(["x"])[0],
                metadata={"chunk_key": "ghost"})])
            vstore.delete(namespace, [pinecone_id_for(*entity, "facts:audit")])
            drift = reconcile(*entity, store=vstore, ledger=repo)
            assert not drift.healthy
            assert [d.chunk_key for d in drift.orphans] == ["ghost"]
            assert [d.chunk_key for d in drift.missing] == ["facts:audit"]
        finally:
            with contextlib.suppress(Exception), privileged_connection() as cur:
                if client_id:
                    cur.execute("delete from public.context_vectors where entity_id = %s", (client_id,))
                    cur.execute("delete from public.entity_context where entity_id = %s", (client_id,))
                    cur.execute("delete from public.context_dirty where entity_id = %s", (client_id,))
                cur.execute("delete from public.activity_log where action like %s", (f"%{tag}%",))
                if client_id:
                    cur.execute("delete from public.clients where id = %s", (client_id,))
