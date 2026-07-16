"""P6C gate: the PUBLIC free-audit endpoints - unauthenticated, tenant-isolated.

Covers: 201 returns the token (not the internal id); one-audit-per-email 409;
Free-tier-only rejection of paid types; SSRF rejection; the curated tokenized
report (no tenant data / internal id / email / error leaked); unknown token 404;
and that the routes carry NO auth dependency (a request with no Authorization
header succeeds)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.dependencies.utils import get_flat_dependant
from fastapi.routing import APIRoute

from app.core.auth import get_current_user
from app.core.deps import get_redis
from app.routers.public import (
    get_public_audit_enqueuer,
    get_public_cost_logger,
    get_public_gateway,
)
from app.routers.public import router as public_router

pytestmark = pytest.mark.unit

# A public IP literal: passes the SSRF guard with NO DNS lookup (offline-safe).
_PUBLIC_URL = "http://93.184.216.34"


class FakeGateway:
    def __init__(self) -> None:
        self.by_token: dict[str, dict[str, Any]] = {}
        self._by_email: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def seed(self, token: str, **over: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": "pa-seed", "email": "seed@example.com", "url": "https://seeded.example",
            "status": "done", "score": 77, "scores": {"overall": 77, "technical": 88},
            "run_uuid": "u-seed", "artifact_dir": "/art/u-seed",
            "pdf_path": "pa-seed/report.pdf", "json_path": "pa-seed/findings.json",
            "report_token": token, "source": "landing", "error": "some-internal-error",
            "created_at": datetime.now(UTC),
        }
        row.update(over)
        self.by_token[token] = row
        self._by_email[str(row["email"]).lower()] = {"id": row["id"]}
        return row

    def find_by_email(self, email: str) -> dict[str, Any] | None:
        return self._by_email.get(email.lower())

    def insert(self, email: str, url: str, source: str) -> dict[str, Any]:
        self._seq += 1
        rid, token = f"pa-{self._seq}", f"tok-{self._seq}"
        row = {
            "id": rid, "report_token": token, "status": "queued",
            "email": email, "url": url, "source": source, "score": None, "scores": {},
            "pdf_path": None, "json_path": None, "created_at": datetime.now(UTC),
        }
        self.by_token[token] = row
        self._by_email[email.lower()] = {"id": rid}
        return row

    def get_by_token(self, report_token: str) -> dict[str, Any] | None:
        return self.by_token.get(report_token)


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def enqueued() -> list[str]:
    return []


@pytest.fixture
def cost_logged() -> list[str]:
    return []


class _NoThrottleRedis:
    """A redis stand-in whose counter never exceeds 1, so the per-IP limiter is a
    no-op in these unit tests (the limiter itself is covered in test_ratelimit)."""

    async def incr(self, key: str) -> int:
        return 1

    async def expire(self, key: str, seconds: int) -> None:
        return None


@pytest.fixture(autouse=True)
def wire(
    app: FastAPI, gateway: FakeGateway, enqueued: list[str], cost_logged: list[str]
) -> None:
    app.dependency_overrides[get_public_gateway] = lambda: gateway
    app.dependency_overrides[get_public_audit_enqueuer] = lambda: enqueued.append
    app.dependency_overrides[get_public_cost_logger] = lambda: cost_logged.append
    # Pin the rate-limiter to a non-throttling redis so many POSTs in this module
    # (all from one test IP) stay deterministic regardless of a live local Redis.
    app.dependency_overrides[get_redis] = lambda: _NoThrottleRedis()


async def test_create_returns_token_not_internal_id(
    client: httpx.AsyncClient, gateway: FakeGateway, enqueued: list[str], cost_logged: list[str]
) -> None:
    resp = await client.post(
        "/api/v1/public/audits", json={"email": "Lead@Example.com", "url": _PUBLIC_URL}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"report_token", "status"}  # NEVER the internal id
    assert body["status"] == "queued"
    assert body["report_token"] in gateway.by_token
    # enqueued + $0 cost logged for the new row's internal id
    row = gateway.by_token[body["report_token"]]
    assert enqueued == [row["id"]]
    assert cost_logged == [row["id"]]


async def test_no_auth_header_still_succeeds(client: httpx.AsyncClient) -> None:
    # No Authorization header at all -> the route is unauthenticated (not 401/403).
    resp = await client.post(
        "/api/v1/public/audits", json={"email": "a@b.com", "url": _PUBLIC_URL}
    )
    assert resp.status_code == 201


async def test_one_audit_per_email_returns_409(
    client: httpx.AsyncClient, enqueued: list[str]
) -> None:
    first = await client.post(
        "/api/v1/public/audits", json={"email": "dup@example.com", "url": _PUBLIC_URL}
    )
    assert first.status_code == 201
    second = await client.post(
        "/api/v1/public/audits", json={"email": "DUP@example.com", "url": _PUBLIC_URL}
    )
    assert second.status_code == 409
    assert "already exists" in second.json()["error"]["message"]
    assert len(enqueued) == 1  # the duplicate never enqueued a second job


async def test_free_only_rejects_paid_types(
    client: httpx.AsyncClient, enqueued: list[str]
) -> None:
    resp = await client.post(
        "/api/v1/public/audits",
        json={"email": "paid@example.com", "url": _PUBLIC_URL, "types": ["technical", "local"]},
    )
    assert resp.status_code == 400
    assert "paid audit types" in resp.json()["error"]["message"]
    assert enqueued == []


async def test_ssrf_private_url_rejected(
    client: httpx.AsyncClient, enqueued: list[str]
) -> None:
    resp = await client.post(
        "/api/v1/public/audits", json={"email": "ssrf@example.com", "url": "http://127.0.0.1/admin"}
    )
    assert resp.status_code == 400
    assert "public address" in resp.json()["error"]["message"]
    assert enqueued == []


async def test_invalid_email_rejected(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/public/audits", json={"email": "not-an-email", "url": _PUBLIC_URL}
    )
    assert resp.status_code == 422  # EmailStr validation


async def test_report_by_token_is_curated(
    client: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    gateway.seed("secret-token")
    resp = await client.get("/api/v1/public/audits/secret-token")
    assert resp.status_code == 200
    body = resp.json()
    # Exactly the curated fields - no id, no email, no error, no artifact paths.
    assert set(body) == {
        "status", "score", "scores", "has_pdf", "has_report", "url", "when", "fiverr_url"
    }
    assert body["score"] == 77
    assert body["has_pdf"] is True and body["has_report"] is True
    assert body["fiverr_url"].startswith("https://www.fiverr.com/")
    # Assert no tenant / internal leakage in the serialized payload.
    raw = resp.text
    assert "pa-seed" not in raw  # internal id
    assert "seed@example.com" not in raw  # email
    assert "some-internal-error" not in raw  # stored error
    assert "artifact_dir" not in raw and "run_uuid" not in raw


async def test_unknown_token_404(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/public/audits/does-not-exist")
    assert resp.status_code == 404


def test_public_routes_have_no_auth_dependency() -> None:
    """Introspect every public route: get_current_user must not appear anywhere."""
    routes = [r for r in public_router.routes if isinstance(r, APIRoute)]
    assert routes, "expected the public router to declare routes"
    for route in routes:
        flat = get_flat_dependant(route.dependant)
        calls = {dep.call for dep in flat.dependencies}
        assert get_current_user not in calls, f"{route.path} must not require auth"
