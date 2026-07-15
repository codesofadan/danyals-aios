"""Integration: the full LOCAL auth stack, end to end (P6A-7 cutover).

Proves the entire local pipeline with NO Supabase and NO mocks: provision a user
into local Postgres (argon2id credential + identity row) -> POST /auth/login ->
our own EdDSA token -> that token loads the user via rls_connection -> the caller
reads local data. Also proves the trust boundary: a client-role login is routed
to the client portal and is 403'd out of a staff route.

Auto-skips unless the local DB DSNs are configured (DATABASE_URL +
DATABASE_ADMIN_URL) and the signing keypair is present.
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
from app.services.provisioning import provision_user

pytestmark = pytest.mark.integration


def _require_local_stack() -> Any:
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")
    if not (settings.jwt_private_key_pem and settings.jwt_public_key_pem):
        pytest.skip("signing keypair not configured (JWT_PRIVATE_KEY + JWT_PUBLIC_KEY)")
    return settings


def _insert_client(name: str) -> str:
    with privileged_connection() as cur:
        cur.execute("insert into public.clients (name) values (%s) returning id", (name,))
        row = cur.fetchone()
    assert row is not None
    return str(row["id"])


def _cleanup(*, auth_ids: list[str], client_ids: list[str]) -> None:
    with privileged_connection() as cur:
        for uid in auth_ids:
            # public.users FK -> auth.users ON DELETE CASCADE removes the identity too.
            cur.execute("delete from auth.users where id = %s", (uid,))
        for cid in client_ids:
            cur.execute("delete from public.clients where id = %s", (cid,))


async def test_local_login_end_to_end() -> None:
    _require_local_stack()
    suffix = uuid4().hex[:10]
    staff_user = f"staff_{suffix}"
    client_user = f"client_{suffix}"
    password = "Corr3ct-Passw0rd!"

    app = create_app()
    auth_ids: list[str] = []
    client_ids: list[str] = []
    async with LifespanManager(app):
        try:
            # --- provision a STAFF login + a CLIENT login (with a real tenant) ---
            staff_row = provision_user(
                email=f"{staff_user}@x.com", password=password, name="Staff Member",
                role="manager", username=staff_user, template_key="va",
            )
            auth_ids.append(str(staff_row["id"]))

            client_id = _insert_client(f"Tenant {suffix}")
            client_ids.append(client_id)
            client_row = provision_user(
                email=f"{client_user}@x.com", password=password, name="Portal User",
                role="client", username=client_user, client_id=client_id,
            )
            auth_ids.append(str(client_row["id"]))

            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as ac:
                # --- STAFF: login -> local EdDSA token -> local user load -> data ---
                resp = await ac.post(
                    "/api/v1/auth/login", json={"username": staff_user, "password": password}
                )
                assert resp.status_code == 200, resp.text
                body = resp.json()
                assert body["token_type"] == "bearer"
                assert body["role"] == "manager"
                assert body["portal"] == "team"
                staff_headers = {"Authorization": f"Bearer {body['access_token']}"}

                me = await ac.get("/api/v1/me", headers=staff_headers)
                assert me.status_code == 200, me.text
                assert me.json()["email"] == f"{staff_user}@x.com"

                clients = await ac.get("/api/v1/clients", headers=staff_headers)
                assert clients.status_code == 200, clients.text

                # A wrong password is a generic 401 (no enumeration).
                bad = await ac.post(
                    "/api/v1/auth/login", json={"username": staff_user, "password": "nope-nope-1"}
                )
                assert bad.status_code == 401

                # --- CLIENT: routed to the client portal, 403'd from a staff route ---
                c_resp = await ac.post(
                    "/api/v1/auth/login", json={"username": client_user, "password": password}
                )
                assert c_resp.status_code == 200, c_resp.text
                c_body = c_resp.json()
                assert c_body["role"] == "client"
                assert c_body["portal"] == "client"
                client_headers = {"Authorization": f"Bearer {c_body['access_token']}"}

                # /me requires view_reports, which a client does not hold -> 403.
                c_me = await ac.get("/api/v1/me", headers=client_headers)
                assert c_me.status_code == 403, c_me.text
        finally:
            _cleanup(auth_ids=auth_ids, client_ids=client_ids)
