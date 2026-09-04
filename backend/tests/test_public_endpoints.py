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
    get_public_audit_enqueuer,
    get_public_funnel_gate,
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
    app.dependency_overrides[get_public_audit_enqueuer] = lambda: enqueued.append
    app.dependency_overrides[get_public_funnel_gate] = lambda: (lambda: funnel_open[0])
    # Pin the rate-limiter to a non-throttling redis so many POSTs in this module
    # (all from one test IP) stay deterministic regardless of a live local Redis.
    app.dependency_overrides[get_redis] = lambda: _NoThrottleRedis()


async def test_create_returns_token_not_internal_id(
    client: httpx.AsyncClient, gateway: FakeGateway, enqueued: list[str]
) -> None:
    resp = await client.post(
        "/api/v1/public/audits", json={"email": "Lead@Example.com", "url": _PUBLIC_URL}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"report_token", "status"}  # NEVER the internal id
    assert body["status"] == "queued"
    assert body["report_token"] in gateway.by_token
    # Enqueued for the new row's internal id. NO cost row is written here: the
    # worker commits exactly one ledger entry, priced from what the run did.
    row = gateway.by_token[body["report_token"]]
    assert enqueued == [row["id"]]


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


async def test_paid_types_now_accepted_comprehensive_audit(
    client: httpx.AsyncClient, enqueued: list[str]
) -> None:
    # The free funnel is now comprehensive: paid audit types are NO LONGER
    # rejected. A request naming paid dimensions is accepted and enqueued.
    resp = await client.post(
        "/api/v1/public/audits",
        json={"email": "paid@example.com", "url": _PUBLIC_URL, "types": ["technical", "local"]},
    )
    assert resp.status_code == 201
    assert len(enqueued) == 1  # the job was enqueued despite the paid type


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


async def test_a_closed_dial_refuses_the_funnel_without_creating_a_row(
    client: httpx.AsyncClient, gateway: FakeGateway, enqueued: list[str], funnel_open: list[bool]
) -> None:
    """An operator turning the funnel off must stop it BEFORE any work is booked."""
    funnel_open[0] = False
    resp = await client.post(
        "/api/v1/public/audits", json={"email": "closed@example.com", "url": _PUBLIC_URL}
    )
    assert resp.status_code == 503
    assert resp.headers.get("Retry-After")
    # Nothing was created and nothing was queued — not merely "not run".
    assert gateway.by_token == {}
    assert enqueued == []
    # The refusal never names which control closed the funnel.
    message = resp.json()["error"]["message"]
    assert "dial" not in message.lower() and "cap" not in message.lower()


async def test_a_gate_failure_closes_the_funnel_rather_than_opening_it(
    client: httpx.AsyncClient, app: FastAPI, gateway: FakeGateway
) -> None:
    """Unable to establish that spending is permitted must mean: do not spend."""

    def _boom() -> bool:
        raise RuntimeError("cost store unavailable")

    app.dependency_overrides[get_public_funnel_gate] = lambda: _boom
    resp = await client.post(
        "/api/v1/public/audits", json={"email": "boom@example.com", "url": _PUBLIC_URL}
    )
    assert resp.status_code == 503
    assert gateway.by_token == {}


async def test_the_daily_cap_is_enforced_agency_wide(
    client: httpx.AsyncClient, app: FastAPI, gateway: FakeGateway
) -> None:
    """Per-IP limiting bounds one abuser; this bounds a distributed one.

    Every request here uses a DIFFERENT email, so the one-per-email rule is not
    what stops it — the agency-wide ceiling is.
    """
    from app.config import Settings, get_settings

    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, app_env="dev", public_audit_daily_cap=2
    )
    for i in range(2):
        ok = await client.post(
            "/api/v1/public/audits", json={"email": f"lead{i}@example.com", "url": _PUBLIC_URL}
        )
        assert ok.status_code == 201, ok.text

    over = await client.post(
        "/api/v1/public/audits", json={"email": "lead2@example.com", "url": _PUBLIC_URL}
    )
    assert over.status_code == 503
    assert len(gateway.by_token) == 2  # the third was never created


async def test_an_uncountable_daily_cap_closes_the_funnel(
    client: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    """An unenforceable ceiling is treated as reached, not as absent."""
    gateway.count_today_raises = True
    resp = await client.post(
        "/api/v1/public/audits", json={"email": "nocount@example.com", "url": _PUBLIC_URL}
    )
    assert resp.status_code == 503
    assert gateway.by_token == {}


async def test_a_zero_daily_cap_disables_the_ceiling_not_the_funnel(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    """`0` means "no daily ceiling configured" — it must not read as "cap of zero"."""
    from app.config import Settings, get_settings

    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, app_env="dev", public_audit_daily_cap=0
    )
    resp = await client.post(
        "/api/v1/public/audits", json={"email": "uncapped@example.com", "url": _PUBLIC_URL}
    )
    assert resp.status_code == 201


async def test_the_per_ip_limiter_fails_closed_on_this_route(
    client: httpx.AsyncClient, app: FastAPI, gateway: FakeGateway
) -> None:
    """A Redis outage must not silently remove the only control on an anon caller.

    Contrast `test_ratelimit`'s fail-OPEN cases: those guard authenticated callers
    who are already bounded by permissions and budget caps.
    """

    class _DeadRedis:
        async def incr(self, key: str) -> int:
            raise ConnectionError("redis down")

        async def expire(self, key: str, seconds: int) -> None:
            raise ConnectionError("redis down")

    app.dependency_overrides[get_redis] = lambda: _DeadRedis()
    resp = await client.post(
        "/api/v1/public/audits", json={"email": "noredis@example.com", "url": _PUBLIC_URL}
    )
    assert resp.status_code == 503
    assert gateway.by_token == {}


async def test_the_funnel_meters_under_its_own_dial_not_the_paid_audits(
    client: httpx.AsyncClient,
) -> None:
    """Switching the lead magnet off must not disable the paid product.

    They shared the `tech_audit` dial, so the only way to stop the free funnel was
    to stop every client's technical audit too.
    """
    from app.routers.public import _COST_FEATURE
    from app.schemas.cost import DIAL_KEYS

    assert _COST_FEATURE == "public_audit"
    assert _COST_FEATURE != "tech_audit"
    # An UNREGISTERED dial key resolves to "off" and is rejected by PATCH
    # /cost/dials — i.e. unswitchable-on. Registration is what makes it a control.
    assert _COST_FEATURE in DIAL_KEYS
