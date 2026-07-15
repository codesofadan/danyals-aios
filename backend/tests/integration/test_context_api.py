"""Integration: the P6B-8 CONTEXT RETRIEVAL API + FRESHNESS GATE, end-to-end
against local Postgres and the REAL app (ASGITransport), with FAKE providers.

Proves the whole contract on real SQL + RLS:

    seed activity (service_role) -> the 0013 trigger enqueues a dirty row -> run
    the compaction core (fakes) -> staff GET /context/client/{id} returns the
    summarized context with lag 0, stale false. Then append a NEW activity ->
    /health shows lag>0 + stale true -> GET ?fresh=1 (fakes) recompacts -> lag 0.
    A portal CLIENT hitting /portal/context sees ONLY its own summary; a staff
    caller is 403'd from /portal/context and a client is 403'd from /context/*.

Auto-skips unless DATABASE_URL + DATABASE_ADMIN_URL and the signing keypair are
configured. Everything seeded is torn down in a finally.
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
from app.routers.context import get_context_provider_factory
from app.services.provisioning import provision_user
from integrations.context_providers import providers_for_tests
from workers.tasks.context import execute_compaction

pytestmark = pytest.mark.integration

_PASSWORD = "Passw0rd!ctx-api-123"


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
        "values ('Ctx API Bot', %(kind)s, %(action)s, %(target)s, %(meta)s, "
        "'client'::public.context_entity, %(entity_id)s) returning seq",
        {"kind": kind, "action": action, "target": target, "meta": meta, "entity_id": entity_id},
    )
    return int(cur.fetchone()["seq"])


async def _login(ac: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await ac.post("/api/v1/auth/login", json={"username": username, "password": _PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_context_api_freshness_and_isolation() -> None:
    settings = _require_local_stack()
    tag = uuid4().hex[:8]

    app = create_app()
    # Fresh path uses the deterministic fakes bundle (no external keys needed).
    app.dependency_overrides[get_context_provider_factory] = lambda: (
        lambda et, eid: providers_for_tests()
    )

    client_id: str | None = None
    uids: list[str] = []
    async with LifespanManager(app):
        try:
            with privileged_connection() as cur:
                cur.execute("insert into public.clients (name) values (%s) returning id", (f"Ctx API {tag}",))
                client_id = str(cur.fetchone()["id"])

            staff_name = f"ctx_api_staff_{tag}"
            client_name = f"ctx_api_client_{tag}"
            uid_staff = str(provision_user(
                email=f"{staff_name}@x.com", password=_PASSWORD, name="Ctx Staff",
                role="owner", username=staff_name, template_key="super",
            )["id"])
            uid_client = str(provision_user(
                email=f"{client_name}@x.com", password=_PASSWORD, name="Ctx Client",
                role="client", username=client_name, client_id=client_id,
            )["id"])
            uids += [uid_staff, uid_client]

            entity = ("client", client_id)

            # --- seed activity -> the trigger enqueues a dirty row ---
            with privileged_connection() as cur:
                _insert_event(cur, kind="audit", action=f"ran audit {tag}",
                              target="https://acme.test", meta="87", entity_id=client_id)
                seq2 = _insert_event(cur, kind="client", action=f"set tier {tag}",
                                     target="acme", meta="Growth", entity_id=client_id)

            # --- run the compaction core with FAKES (the "worker" step) ---
            out = execute_compaction(service_context_repo(), providers_for_tests(), *entity, settings=settings)
            assert out.state == "summarized" and out.watermark == seq2

            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                staff = await _login(ac, staff_name)
                client_h = await _login(ac, client_name)

                # (1) staff reads the summarized context: lag 0, stale false.
                got = await ac.get(f"/api/v1/context/client/{client_id}", headers=staff)
                assert got.status_code == 200, got.text
                body = got.json()
                assert body["status"] == "summarized"
                assert body["summary"]  # bounded prose folded by the FakeSummarizer
                assert body["facts"]["tier"] == "Growth"
                assert body["lag"] == 0 and body["stale"] is False

                # (2) a NEW activity => /health shows lag>0 + stale true.
                with privileged_connection() as cur:
                    seq3 = _insert_event(cur, kind="task", action=f"closed {tag}",
                                         target="onboarding", meta=None, entity_id=client_id)
                health = await ac.get(f"/api/v1/context/client/{client_id}/health", headers=staff)
                assert health.status_code == 200, health.text
                hbody = health.json()
                assert hbody["latest_seq"] == seq3
                assert hbody["lag"] > 0 and hbody["stale"] is True

                # (3) ?fresh=1 recompacts synchronously (fakes) => lag back to 0.
                fresh = await ac.get(f"/api/v1/context/client/{client_id}?fresh=1", headers=staff)
                assert fresh.status_code == 200, fresh.text
                fbody = fresh.json()
                assert fbody["event_watermark"] == seq3
                assert fbody["lag"] == 0 and fbody["stale"] is False
                assert "onboarding" in fbody["facts"]["last_task"]  # the new event folded in

                # (4) the portal CLIENT sees ONLY its own client-level summary+facts.
                portal = await ac.get("/api/v1/portal/context", headers=client_h)
                assert portal.status_code == 200, portal.text
                pbody = portal.json()
                assert pbody["facts"]["tier"] == "Growth"
                assert "event_watermark" not in pbody and "lag" not in pbody  # no internals

                # (5) RLS gating: staff 403 from the client-only portal; client 403 from staff /context.
                staff_portal = await ac.get("/api/v1/portal/context", headers=staff)
                assert staff_portal.status_code == 403
                client_ctx = await ac.get(f"/api/v1/context/client/{client_id}", headers=client_h)
                assert client_ctx.status_code == 403
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
