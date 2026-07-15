"""Integration: RLS repo routes resolve auth first and return 2xx, not 500.

Regression for the empty-JWT bug: the repo factories read the caller's token
from ``request.state.access_token`` (set by ``get_current_user``). If a factory
did not depend on auth, FastAPI could resolve it before auth, so PostgREST saw
an empty JWT and the route 500'd. This drives the REAL app end-to-end - through
the actual route dependency graph - with a real Supabase JWT and asserts the
RLS-backed routes return 200.

Skips unless SUPABASE_URL + service_role + anon keys are set AND migrations have
been applied. Cleans up the provisioned owner in a ``finally``.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from asgi_lifespan import LifespanManager
from supabase import create_client

from app.config import get_settings
from app.db.supabase import get_admin_client
from app.main import create_app
from app.services.provisioning import provision_user

# Superseded by the P6A-7 local auth cutover; reworked in P6A-8. This whole-stack
# suite signs in via Supabase GoTrue and verifies against Supabase; after the
# cutover the API mints + verifies its OWN EdDSA tokens against LOCAL Postgres and
# provision_user writes locally (new signature), so a Supabase token no longer
# authenticates. The local-token rewrite of the elevated suites is P6A-8's job.
pytest.skip(
    "Superseded by P6A-7 local auth cutover; Supabase-token flow reworked in P6A-8.",
    allow_module_level=True,
)


def _require_supabase() -> Any:
    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_service_role_key and settings.supabase_anon_key):
        pytest.skip("Supabase not configured (SUPABASE_URL + keys)")
    return settings


@pytest.mark.integration
async def test_rls_routes_return_2xx_not_500() -> None:
    settings = _require_supabase()
    admin = get_admin_client()
    anon = create_client(settings.supabase_url, settings.supabase_anon_key.get_secret_value())

    email = f"routewire-{uuid4().hex}@example.com"
    password = "Passw0rd!route-123"
    user_row = provision_user(
        admin, email=email, password=password, name="Route Wire Owner", role="owner", template_key="super"
    )
    user_id = user_row["id"]
    try:
        session = anon.auth.sign_in_with_password({"email": email, "password": password})
        token = session.session.access_token
        headers = {"Authorization": f"Bearer {token}"}

        app = create_app()
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test", headers=headers
            ) as ac:
                for path in ("/api/v1/me", "/api/v1/clients", "/api/v1/tasks"):
                    resp = await ac.get(path)
                    assert resp.status_code == 200, (
                        f"{path} returned {resp.status_code} (expected 200); "
                        "repo factory likely resolved before auth (empty-JWT 500)"
                    )
    finally:
        admin.auth.admin.delete_user(user_id)
