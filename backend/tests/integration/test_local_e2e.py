"""Integration: the full shared-base flow against the LOCAL Postgres data plane.

The whole stack with NO Supabase and NO mocks: provision an owner into local
Postgres -> POST /auth/login -> our own EdDSA token -> drive the REAL app to read
back the caller's row and CREATE a client through the RLS path -> run the cost
gate against a seeded over-cap budget (blocked) -> append an activity row and read
it back through the staff feed.

Auto-skips unless DATABASE_URL + DATABASE_ADMIN_URL and the signing keypair are
configured. Everything created is cleaned up in a ``finally``.
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
from app.services.activity import log_activity
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import SupabaseCostStore
from app.services.provisioning import provision_user

pytestmark = pytest.mark.integration


class _NoCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _require_local_stack() -> Any:
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")
    if not (settings.jwt_private_key_pem and settings.jwt_public_key_pem):
        pytest.skip("signing keypair not configured (JWT_PRIVATE_KEY + JWT_PUBLIC_KEY)")
    return settings


async def test_shared_base_end_to_end() -> None:
    _require_local_stack()
    suffix = uuid4().hex[:10]
    username = f"e2e_{suffix}"
    password = "Passw0rd!e2e-123"
    dial_key = f"e2e_feat_{suffix}"

    app = create_app()
    user_id: str | None = None
    client_id: str | None = None
    async with LifespanManager(app):
        try:
            row = provision_user(
                email=f"{username}@x.com", password=password, name="E2E Admin",
                role="owner", username=username, template_key="super",
            )
            user_id = str(row["id"])

            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                # login -> our own EdDSA token
                login = await ac.post(
                    "/api/v1/auth/login", json={"username": username, "password": password}
                )
                assert login.status_code == 200, login.text
                token = login.json()["access_token"]
                headers = {"Authorization": f"Bearer {token}"}

                # the provisioned owner reads their own row (RLS self-read)
                me = await ac.get("/api/v1/me", headers=headers)
                assert me.status_code == 200, me.text
                assert me.json()["email"] == f"{username}@x.com"

                # owner creates a client (manage_clients) through the RLS repo
                created = await ac.post(
                    "/api/v1/clients", headers=headers, json={"cn": "E2E Client", "tier": "Starter"}
                )
                assert created.status_code == 201, created.text
                client_id = created.json()["id"]

            # budget cap 10 with 9 already spent + dial 'api' -> a $5 call is over-cap
            with privileged_connection() as cur:
                cur.execute(
                    "insert into public.client_budgets (client_id, cap, spent) values (%s, 10, 9) "
                    "on conflict (client_id) do update set cap = 10, spent = 9",
                    (client_id,),
                )
                cur.execute(
                    "insert into public.cost_dial (feature_key, mode) values (%s, 'api')",
                    (dial_key,),
                )

            gate = CostGate(SupabaseCostStore(), _NoCache())
            decision = gate.evaluate(
                GateContext(
                    feature_key=dial_key, client_id=client_id, provider="DataForSEO",
                    estimated_cost=5.0,
                )
            )
            assert decision.outcome == "blocked_cap"

            # activity is written server-side (append-only) and visible to staff
            log_activity(
                actor_id=user_id, actor_name="E2E Admin", actor_color="#000",
                kind="client", action="created client", target="E2E Client",
            )
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                feed = await ac.get("/api/v1/activity", headers=headers)
                assert feed.status_code == 200, feed.text
                assert any(a["action"] == "created client" for a in feed.json())
        finally:
            with privileged_connection() as cur:
                if user_id:
                    cur.execute("delete from public.activity_log where actor_id = %s", (user_id,))
                if client_id:
                    cur.execute("delete from public.clients where id = %s", (client_id,))
                cur.execute("delete from public.cost_dial where feature_key = %s", (dial_key,))
                if user_id:
                    cur.execute("delete from auth.users where id = %s", (user_id,))
