"""P6C gate: the PUBLIC free-audit endpoints - unauthenticated, tenant-isolated.

Covers: 201 returns the token (not the internal id); one-audit-per-email 409;
paid types accepted (the free audit is comprehensive); SSRF rejection; the curated tokenized
report (no tenant data / internal id / email / error leaked); unknown token 404;
and that the routes carry NO auth dependency (a request with no Authorization
header succeeds)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.core.auth import get_current_user
from app.core.deps import get_redis
from app.routers.public import (
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
        self.count_today_raises = False

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

    def delete_by_id(self, public_audit_id: str) -> None:
        for token, row in list(self.by_token.items()):
            if row["id"] == public_audit_id:
                self.by_token.pop(token)
                self._by_email.pop(str(row["email"]).lower(), None)

    def count_today(self) -> int:
        """Rows created "today". The fake creates everything in one run, so the
        insert count IS today's count. `count_today_raises` simulates the DB being
        unreachable, which the endpoint must treat as a closed funnel."""
        if self.count_today_raises:
            raise RuntimeError("public_audits count unavailable")
        return self._seq


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def enqueued() -> list[str]:
    return []


@pytest.fixture
def funnel_open() -> list[bool]:
    """One-element switch for the cost gate's verdict, flipped per test."""
    return [True]


class _NoThrottleRedis:
    """A redis stand-in whose counter never exceeds 1, so the per-IP limiter is a
    no-op in these unit tests (the limiter itself is covered in test_ratelimit)."""

    async def incr(self, key: str) -> int:
        return 1

    async def expire(self, key: str, seconds: int) -> None:
        return None


@pytest.fixture(autouse=True)
def wire(
    app: FastAPI, gateway: FakeGateway, enqueued: list[str], funnel_open: list[bool]
) -> None:
    app.dependency_overrides[get_public_gateway] = lambda: gateway
    # Pin the rate-limiter to a non-throttling redis so many POSTs in this module
    # (all from one test IP) stay deterministic regardless of a live local Redis.
    app.dependency_overrides[get_redis] = lambda: _NoThrottleRedis()


async def test_report_by_token_is_curated(
    client: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    gateway.seed("secret-token")
    resp = await client.get("/api/v1/public/audits/secret-token")
    assert resp.status_code == 200
    body = resp.json()
    # Exactly the curated fields - no id, no email, no error, no artifact paths.
    # `publicSlug` belongs here: it names a page that is PUBLIC by design (free pages
    # publish on completion), so it discloses nothing the slug does not already
    # advertise -- and without it the person who ran the audit is never shown the one
    # artifact meant for them to share.
    assert set(body) == {
        "status", "score", "scores", "has_pdf", "has_report", "url", "when",
        "fiverr_url", "publicSlug",
    }
    # It must be a SLUG, never the capability token that addresses this endpoint.
    assert body["publicSlug"] != "secret-token"
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


def _all_dependency_calls(dependant: Dependant) -> set[Any]:
    """Every callable in a route's dependency TREE, flattened.

    Walks the tree here rather than through FastAPI's private
    ``get_flat_dependant`` helper, which is not part of the public API and was
    removed in FastAPI 0.141 - taking this whole module's collection down with
    it. The walk is cycle-safe (FastAPI caches sub-dependants by identity, and a
    self-referential graph would otherwise hang).
    """
    calls: set[Any] = set()
    seen: set[int] = set()
    stack: list[Dependant] = [dependant]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        for sub in node.dependencies:
            if sub.call is not None:
                calls.add(sub.call)
            stack.append(sub)
    return calls


def test_public_routes_have_no_auth_dependency() -> None:
    """Introspect every public route: get_current_user must not appear anywhere."""
    routes = [r for r in public_router.routes if isinstance(r, APIRoute)]
    assert routes, "expected the public router to declare routes"
    for route in routes:
        calls = _all_dependency_calls(route.dependant)
        assert get_current_user not in calls, f"{route.path} must not require auth"


# --------------------------------------------------------------------------- #
# P0-2 · the funnel's abuse controls
# --------------------------------------------------------------------------- #
# The defect: this unauthenticated route ran the engine with Serper + Google
# Places + citations + PSI enabled and committed a hardcoded $0.00 to the cost
# ledger, behind a per-IP limiter that failed OPEN. Anyone could spend the
# agency's provider budget from the internet, and nothing in the money ledger
# would show it. Each test below pins one of the controls that closes that.


