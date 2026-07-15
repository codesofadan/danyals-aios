"""Integration: RLS repo routes resolve auth first and return 2xx, not 500.

Regression for the empty-identity bug: the RLS repos open ``rls_connection`` off
the VERIFIED ``sub`` that ``get_current_user`` resolves. If a repo factory were
wired to resolve before auth, it would open a connection with no identity and the
route would fail. This drives the REAL app end-to-end - through the actual route
dependency graph - with a locally-minted EdDSA token and asserts the RLS-backed
routes return 200.

Since the P6A cutover the token is our OWN EdDSA access token (minted by
``issue_access_token``) and the caller is provisioned into LOCAL Postgres; no
Supabase. Skips unless DATABASE_URL + DATABASE_ADMIN_URL and the signing keypair
are configured. Cleans up the provisioned owner in a ``finally``.
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
from app.services.tokens import issue_access_token

pytestmark = pytest.mark.integration


def _require_local_stack() -> Any:
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")
    if not (settings.jwt_private_key_pem and settings.jwt_public_key_pem):
        pytest.skip("signing keypair not configured (JWT_PRIVATE_KEY + JWT_PUBLIC_KEY)")
    return settings


async def test_rls_routes_return_2xx_not_500() -> None:
    settings = _require_local_stack()
    suffix = uuid4().hex[:10]
    username = f"routewire_{suffix}"

    app = create_app()
    user_id: str | None = None
    async with LifespanManager(app):
        try:
            # provision (inside the lifespan so the module pools are registered) an
            # owner, then mint our own EdDSA token for it.
            row = provision_user(
                email=f"{username}@x.com", password="Passw0rd!route-123", name="Route Wire Owner",
                role="owner", username=username, template_key="super",
            )
            user_id = str(row["id"])
            token = issue_access_token(user_id, "owner", settings=settings)
            headers = {"Authorization": f"Bearer {token}"}

            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test", headers=headers
            ) as ac:
                for path in ("/api/v1/me", "/api/v1/clients", "/api/v1/tasks"):
                    resp = await ac.get(path)
                    assert resp.status_code == 200, (
                        f"{path} returned {resp.status_code} (expected 200); "
                        "repo factory likely resolved before auth (empty-identity)"
                    )
        finally:
            if user_id:
                with privileged_connection() as cur:
                    cur.execute("delete from auth.users where id = %s", (user_id,))
