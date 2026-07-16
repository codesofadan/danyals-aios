"""Unit: EVERY protected API route rejects an unauthenticated request with 401.

Auto-discovering companion to the hand-curated E2E contract suite
(``tests/integration/test_route_contracts.py``). That suite pins ~51 Part-2
endpoints with real tokens + seed rows and needs a live DB, so it only grows by
manual registration and does not yet enumerate the Part-7 modules. THIS test
walks the app's OpenAPI surface at runtime and asserts the single most important
contract - no route is reachable without a verified identity - for EVERY
endpoint, so it automatically covers every Part-7 module (content / off-page /
web2 / policy / reports / milestones / upsells / tickets / settings /
notifications / alerts / backups / command-center) and any route a future
migration adds.

It needs no database: ``get_current_user`` raises 401 on a missing token before
any repo factory or pool is touched, so this runs on every commit in the unit
gate and fails the moment a new route ships without its ``CurrentUserDep`` guard
(the empty-identity / unguarded-route regression class).

The only unauthenticated surface BY DESIGN is the public free-audit funnel
(``/api/v1/public/*``) and the sign-in endpoints (``/api/v1/auth/*``), plus the
ops endpoints (health / metrics / docs); those are allow-listed below.
"""

from __future__ import annotations

import httpx
import pytest
from asgi_lifespan import LifespanManager

from app.main import create_app

pytestmark = pytest.mark.unit

# The ONLY unauthenticated route prefixes. Per app/routers/__init__.py the public
# free-audit funnel is the sole unauthenticated business router; ``auth`` is
# sign-in; the rest is ops surface (liveness / metrics / docs).
_PUBLIC_PREFIXES = (
    "/api/v1/public/",
    "/api/v1/auth/",
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
)
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _is_public(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


async def test_every_protected_route_requires_auth() -> None:
    """Sweep the whole OpenAPI surface: each non-public op must 401 unauthenticated."""
    app = create_app()
    spec = app.openapi()
    protected: list[tuple[str, str]] = [
        (method.upper(), path)
        for path, ops in spec["paths"].items()
        for method in ops
        if method.upper() in _METHODS and not _is_public(path)
    ]
    # Guard against the sweep silently going empty (e.g. an OpenAPI shape change).
    assert len(protected) > 50, f"suspiciously few protected routes discovered: {len(protected)}"

    failures: list[str] = []
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            for method, path in protected:
                # Path params are sent as their literal ``{name}`` template: the route
                # still matches (the segment binds the literal) and the auth dependency
                # runs FIRST, so a guarded route 401s before the handler/DB is reached.
                resp = await ac.request(method, path)
                if resp.status_code != 401:
                    failures.append(
                        f"{method} {path}: got {resp.status_code}, expected 401 (unauthenticated)"
                    )
    assert not failures, (
        "UNGUARDED ROUTES - reachable without a verified identity:\n" + "\n".join(failures)
    )
