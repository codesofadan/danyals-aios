"""P3-4 gate: /audits endpoints - shapes, RBAC, SSRF guard, Free-tier gating,
enqueue, list/get/stats. Repo + enqueuer are faked (no Supabase, no broker)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.audits_repo import get_audits_repo
from app.db.clients_repo import get_clients_repo
from app.routers.audits import get_audit_enqueuer

pytestmark = pytest.mark.unit

# A public IP literal: passes the SSRF guard with NO DNS lookup (offline-safe).
_PUBLIC_URL = "http://93.184.216.34"


class FakeAuditsRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self._seq = 0
        self.last_page: tuple[int | None, int] | None = None

    def seed(self, **over: Any) -> dict[str, Any]:
        self._seq += 1
        aid = over.get("id", f"aud-{self._seq}")
        row: dict[str, Any] = {
            "id": aid,
            "client_name": "Verde Cafe",
            "url": "verdecafe.co",
            "types": ["technical"],
            "tier": "free",
            "status": "done",
            "score": 74,
            "runtime_seconds": 288,
            "pdf_path": "x.pdf",
            "json_path": "x.json",
            "created_at": datetime.now(UTC).isoformat(),
        }
        row.update(over)
        self.rows[aid] = row
        return row

    def list_audits(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        self.last_page = (limit, offset)
        return list(self.rows.values())

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        return self.rows.get(audit_id)

    def insert_audit(self, row: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        aid = f"aud-{self._seq}"
        rec = {"id": aid, "created_at": datetime.now(UTC).isoformat(), "score": None,
               "runtime_seconds": None, "pdf_path": None, "json_path": None, **row}
        self.rows[aid] = rec
        return rec


class FakeClientsRepo:
    def __init__(self, exists: bool = True) -> None:
        self.exists = exists

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        return {"id": client_id, "name": "Verde Cafe"} if self.exists else None


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeAuditsRepo:
    return FakeAuditsRepo()


@pytest.fixture
def enqueued() -> list[str]:
    return []


@pytest.fixture
def wire(
    app: FastAPI, repo: FakeAuditsRepo, enqueued: list[str]
) -> Callable[..., None]:
    app.dependency_overrides[get_audits_repo] = lambda: repo
    app.dependency_overrides[get_audit_enqueuer] = lambda: enqueued.append

    def _as(role: str, *, client_exists: bool = True) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        app.dependency_overrides[get_clients_repo] = lambda: FakeClientsRepo(client_exists)

    return _as


async def test_create_enqueues_queued_row(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, enqueued: list[str], wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Free", "types": ["technical", "actionable"]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"id", "client", "url", "types", "tier", "status", "score", "runtime", "when", "pdf", "json"}
    assert body["status"] == "queued"
    assert body["tier"] == "Free"
    assert body["client"] == "Verde Cafe"
    assert body["score"] is None
    assert body["runtime"] == "—"
    assert body["pdf"] is False and body["json"] is False
    # exactly one job enqueued, for the new row id
    assert enqueued == [body["id"]]


async def test_create_requires_run_audits(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")  # viewer lacks run_audits
    resp = await client.post("/api/v1/audits", json={"client_id": "cl-1", "url": _PUBLIC_URL})
    assert resp.status_code == 403


async def test_create_rejects_private_url(
    client: httpx.AsyncClient, enqueued: list[str], wire: Callable[..., None]
) -> None:
    wire("analyst")
    resp = await client.post(
        "/api/v1/audits", json={"client_id": "cl-1", "url": "http://127.0.0.1/admin"}
    )
    assert resp.status_code == 400
    assert "public address" in resp.json()["error"]["message"]
    assert enqueued == []  # never enqueued


async def test_free_tier_rejects_paid_types(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Free", "types": ["technical", "local"]},
    )
    assert resp.status_code == 400
    assert "Paid tier" in resp.json()["error"]["message"]


async def test_paid_tier_allows_paid_types(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Paid", "types": ["technical", "local", "geo"]},
    )
    assert resp.status_code == 201
    assert resp.json()["tier"] == "Paid"


async def test_create_unknown_client_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager", client_exists=False)
    resp = await client.post("/api/v1/audits", json={"client_id": "nope", "url": _PUBLIC_URL})
    assert resp.status_code == 404


async def test_list_and_get_shape(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    row = repo.seed(tier="paid", status="done", score=91)
    wire("viewer")
    listed = await client.get("/api/v1/audits")
    assert listed.status_code == 200
    assert listed.json()[0]["tier"] == "Paid"
    got = await client.get(f"/api/v1/audits/{row['id']}")
    assert got.status_code == 200
    assert got.json()["score"] == 91
    missing = await client.get("/api/v1/audits/nope")
    assert missing.status_code == 404


async def test_stats_shape(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    repo.seed(status="done", score=80, runtime_seconds=360)
    repo.seed(status="done", score=90, runtime_seconds=600)
    repo.seed(status="running", score=None, runtime_seconds=None)
    # an old run (previous month) must not count toward thisMonth
    old = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    repo.seed(status="done", score=50, runtime_seconds=120, created_at=old)
    wire("viewer")
    resp = await client.get("/api/v1/audits/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"thisMonth", "avgScore", "runningNow", "turnaroundMin"}
    assert body["runningNow"] == 1
    assert body["thisMonth"] == 3  # the 60-day-old run excluded


async def test_list_audits_default_pagination(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/audits")
    assert resp.status_code == 200
    assert repo.last_page == (50, 0)  # hard-cap defaults


async def test_list_audits_explicit_pagination(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/audits", params={"limit": 5, "offset": 10})
    assert resp.status_code == 200
    assert repo.last_page == (5, 10)


async def test_list_audits_cap_enforcement(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")
    assert (await client.get("/api/v1/audits", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/v1/audits", params={"limit": 201})).status_code == 422
