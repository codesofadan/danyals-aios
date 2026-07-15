"""P4-5 gate: the /portal/* client surface + the staff /audits confinement (D10).

Repo, admin, enqueuer, artifact store + loader are faked (no Supabase, no
broker, no real files beyond a tmp fixture). Proves: the routes are client-only
(staff 403), reads are shaped safely (no cost/error/paths), unknown/foreign
audits 404, create pins the tenant, downloads verify ownership then serve, and a
client is 403'd out of the staff /audits namespace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.portal_repo import get_portal_repo
from app.routers.audits import get_artifact_store, get_audit_enqueuer
from app.routers.portal import get_portal_audit_inserter, get_portal_audit_loader

pytestmark = pytest.mark.unit

_PUBLIC_URL = "http://93.184.216.34"

_SAFE_AUDIT_KEYS = {"id", "url", "types", "tier", "status", "score", "scores", "runtime", "when", "pdf", "json"}


def _client_user(client_id: str | None = "cl-A") -> CurrentUser:
    return CurrentUser(
        id="u-1", email="p@acme.com", role="client", status="active",
        name="Acme Portal", title="", avatar_color="#000", phone="", two_fa=False,
        client_id=client_id,
    )


def _staff_user(role: str = "manager") -> CurrentUser:
    return CurrentUser(
        id="s-1", email="s@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Staff", title="", avatar_color="#000", phone="", two_fa=False,
    )


class FakePortalRepo:
    def __init__(self) -> None:
        self.client_row: dict[str, Any] | None = {
            "id": "cl-A", "name": "Acme", "industry": "Tech", "delivery_tier": "fully"
        }
        self.audits: list[dict[str, Any]] = []
        self.sites: list[dict[str, Any]] = []

    def seed_audit(self, **over: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": f"aud-{len(self.audits) + 1}", "url": "acme.com", "types": ["technical"],
            "tier": "free", "status": "done", "score": 82, "scores": {"technical": 82},
            "runtime_seconds": 240, "created_at": "2026-07-14T09:00:00Z",
            "has_pdf": True, "has_json": True,
        }
        row.update(over)
        self.audits.append(row)
        return row

    def get_client(self) -> dict[str, Any] | None:
        return self.client_row

    def list_audits(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return list(self.audits)

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        return next((a for a in self.audits if a["id"] == audit_id), None)

    def list_sites(self) -> list[dict[str, Any]]:
        return list(self.sites)


class FakeInserter:
    """Stand-in for the privileged ``insert_audit_row`` dependency: records the
    row and returns the persisted representation the DB would echo back."""

    def __init__(self) -> None:
        self.inserted: list[dict[str, Any]] = []

    def __call__(self, row: dict[str, Any]) -> dict[str, Any]:
        self.inserted.append(row)
        return {"id": "aud-new", "created_at": "2026-07-14T10:00:00Z", "scores": {}, **row}


@pytest.fixture
def repo() -> FakePortalRepo:
    return FakePortalRepo()


@pytest.fixture
def enqueued() -> list[str]:
    return []


@pytest.fixture
def wire(app: FastAPI, repo: FakePortalRepo, enqueued: list[str]) -> Any:
    app.dependency_overrides[get_portal_repo] = lambda: repo
    app.dependency_overrides[get_audit_enqueuer] = lambda: enqueued.append

    def _as(user: CurrentUser) -> None:
        app.dependency_overrides[get_current_user] = lambda: user

    return _as


# --- gate: client-only ---------------------------------------------------------


async def test_staff_forbidden_from_portal(client: httpx.AsyncClient, wire: Any) -> None:
    wire(_staff_user("owner"))  # even owner is not a client
    resp = await client.get("/api/v1/portal/audits")
    assert resp.status_code == 403


async def test_client_without_tenant_forbidden(client: httpx.AsyncClient, wire: Any) -> None:
    wire(_client_user(client_id=None))
    resp = await client.get("/api/v1/portal/dashboard")
    assert resp.status_code == 403


# --- reads ---------------------------------------------------------------------


async def test_list_audits_safe_shape(
    client: httpx.AsyncClient, repo: FakePortalRepo, wire: Any
) -> None:
    repo.seed_audit()
    wire(_client_user())
    resp = await client.get("/api/v1/portal/audits")
    assert resp.status_code == 200
    row = resp.json()[0]
    assert set(row) == _SAFE_AUDIT_KEYS
    # no sensitive fields ever surface
    assert not ({"cost", "error", "pdf_path", "json_path", "run_uuid", "artifact_dir"} & set(row))
    assert row["pdf"] is True and row["json"] is True


async def test_get_unknown_audit_404(client: httpx.AsyncClient, wire: Any) -> None:
    wire(_client_user())
    resp = await client.get("/api/v1/portal/audits/nope")
    assert resp.status_code == 404


async def test_dashboard_shape(
    client: httpx.AsyncClient, repo: FakePortalRepo, wire: Any
) -> None:
    repo.seed_audit(score=None, status="queued")  # newest, unscored
    repo.seed_audit(score=91, status="done")       # older, scored
    repo.sites = [{"id": "st-1", "domain": "acme.com"}]
    wire(_client_user())
    resp = await client.get("/api/v1/portal/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"client", "deliveryTier", "latestScore", "latestAuditWhen", "totalAudits", "sites"}
    assert body["client"] == "Acme"
    assert body["deliveryTier"] == "fully"
    assert body["totalAudits"] == 2
    assert body["latestScore"] == 91  # most recent SCORED run
    assert body["sites"] == [{"id": "st-1", "domain": "acme.com"}]


# --- create --------------------------------------------------------------------


async def test_create_pins_tenant(
    app: FastAPI, client: httpx.AsyncClient, enqueued: list[str], wire: Any
) -> None:
    inserter = FakeInserter()
    app.dependency_overrides[get_portal_audit_inserter] = lambda: inserter
    wire(_client_user("cl-A"))
    resp = await client.post(
        "/api/v1/portal/audits",
        json={"url": _PUBLIC_URL, "tier": "Free", "types": ["technical"], "client_id": "cl-EVIL"},
    )
    assert resp.status_code == 201, resp.text
    assert inserter.inserted[0]["client_id"] == "cl-A"  # body's cl-EVIL ignored
    assert set(resp.json()) == _SAFE_AUDIT_KEYS
    assert enqueued == ["aud-new"]


# --- downloads -----------------------------------------------------------------


async def test_download_pdf_verifies_ownership_then_serves(
    app: FastAPI, client: httpx.AsyncClient, repo: FakePortalRepo, wire: Any, tmp_path: Path
) -> None:
    owned = repo.seed_audit(id="aud-own")
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")

    class _Store:
        def resolve(self, key: str | None) -> Path | None:
            return pdf if key else None

    app.dependency_overrides[get_artifact_store] = lambda: _Store()
    app.dependency_overrides[get_portal_audit_loader] = lambda: (
        lambda _id: {"pdf_path": "stored/r.pdf", "json_path": None}
    )
    wire(_client_user())

    ok = await client.get(f"/api/v1/portal/audits/{owned['id']}/report.pdf")
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("application/pdf")
    # A foreign/unknown id the view does not return => 404, path never resolved.
    missing = await client.get("/api/v1/portal/audits/aud-foreign/report.pdf")
    assert missing.status_code == 404


# --- D10: staff namespace confinement -----------------------------------------


async def test_client_forbidden_from_staff_audits(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.dependency_overrides[get_current_user] = lambda: _client_user()
    for path in ("/api/v1/audits", "/api/v1/audits/stats", "/api/v1/audits/x"):
        resp = await client.get(path)
        assert resp.status_code == 403, path
