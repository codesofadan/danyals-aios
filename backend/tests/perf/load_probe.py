"""Reproducible perf probe for the RLS-backed read path.

Measures end-to-end p50/p99/throughput for a representative authenticated read
(``GET /api/v1/clients``) under concurrency, driving the REAL app in-process via
``httpx.ASGITransport`` with a REAL Supabase JWT - so the numbers include the app
logic + the Supabase round-trip (the dominant cost), minus only the local HTTP
socket. Run it before/after a query-layer change to see the effect.

Usage (Supabase env required; provisions + deletes one owner):
    ./.venv/Scripts/python -c "from dotenv import load_dotenv; load_dotenv('.env'); \
        import asyncio, tests.perf.load_probe as p; asyncio.run(p.main())"

Optional env: PROBE_CONCURRENCY (default 10), PROBE_REQUESTS (default 100),
PROBE_PATH (default /api/v1/clients).
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time
from uuid import uuid4

import httpx
from asgi_lifespan import LifespanManager
from supabase import create_client

from app.config import get_settings
from app.db.supabase import get_admin_client
from app.main import create_app
from app.services.provisioning import provision_user


def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(p / 100 * (len(xs) - 1)))]


async def main() -> None:
    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_service_role_key and settings.supabase_anon_key):
        print("SKIP: Supabase not configured")
        return
    concurrency = int(os.environ.get("PROBE_CONCURRENCY", "10"))
    total = int(os.environ.get("PROBE_REQUESTS", "100"))
    path = os.environ.get("PROBE_PATH", "/api/v1/clients")

    admin = get_admin_client()
    anon = create_client(settings.supabase_url, settings.supabase_anon_key.get_secret_value())
    email = f"perf-{uuid4().hex}@example.com"
    pw = "Passw0rd!perf-123"
    row = provision_user(admin, email=email, password=pw, name="Perf", role="owner", template_key="super")
    try:
        session = anon.auth.sign_in_with_password({"email": email, "password": pw})
        assert session.session is not None
        token = session.session.access_token
        headers = {"Authorization": f"Bearer {token}"}
        app = create_app()
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://probe", headers=headers) as ac:
                latencies: list[float] = []
                errors = 0
                sem = asyncio.Semaphore(concurrency)

                async def one() -> None:
                    nonlocal errors
                    async with sem:
                        t = time.perf_counter()
                        r = await ac.get(path)
                        latencies.append((time.perf_counter() - t) * 1000)
                        if r.status_code >= 400:
                            errors += 1

                # Warm the JWKS + first connection so the steady state is measured.
                await ac.get(path)
                wall = time.perf_counter()
                await asyncio.gather(*[one() for _ in range(total)])
                wall = time.perf_counter() - wall

        print(f"path={path} concurrency={concurrency} requests={total} errors={errors}")
        print(f"  p50={_pct(latencies, 50):.0f}ms  p95={_pct(latencies, 95):.0f}ms  "
              f"p99={_pct(latencies, 99):.0f}ms  mean={statistics.mean(latencies):.0f}ms")
        print(f"  throughput={total / wall:.1f} req/s over {wall:.1f}s wall")
    finally:
        admin.auth.admin.delete_user(row["id"])
