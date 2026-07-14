"""P2-4 gate: clients + sites CRUD - shapes, RBAC gating, portal-pass masking."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.clients_repo import get_clients_repo

pytestmark = pytest.mark.unit


class FakeRepo:
    def __init__(self) -> None:
        self.clients: dict[str, dict[str, Any]] = {}
        self.sites: dict[str, dict[str, Any]] = {}
        self._seq = 0
        self.last_page: tuple[int | None, int] | None = None

    def _id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq}"

    def seed_client(self, **over: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": over.get("id", self._id("cl")),
            "name": "NorthPeak Dental",
            "industry": "Healthcare",
            "since_year": 2023,
            "contact_name": "Sana Malik",
            "contact_role": "Owner",
            "contact_email": "sana@np.com",
            "contact_color": "#7B69EE",
            "tier": "Scale",
            "status": "active",
            "renews_at": "2026-08-14",
            "mrr": 1490,
            "portal_admin": "admin@np.com",
            "portal_seats": 6,
            "portal_two_fa": True,
            "portal_last_login_at": None,
        }
        row.update(over)
        self.clients[row["id"]] = row
        return row

    def list_clients(
        self, *, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        self.last_page = (limit, offset)
        return list(self.clients.values())

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        return self.clients.get(client_id)

    def insert_client(self, row: dict[str, Any]) -> dict[str, Any]:
        cid = self._id("cl")
        record = {"id": cid, **row}
        self.clients[cid] = record
        return record

    def update_client(self, client_id: str, row: dict[str, Any]) -> dict[str, Any] | None:
        if client_id not in self.clients:
            return None
        self.clients[client_id].update(row)
        return self.clients[client_id]

    def delete_client(self, client_id: str) -> bool:
        return self.clients.pop(client_id, None) is not None

    def site_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self.sites.values():
            counts[str(s["client_id"])] = counts.get(str(s["client_id"]), 0) + 1
        return counts

    def list_sites(
        self, client_id: str, *, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        self.last_page = (limit, offset)
        return [s for s in self.sites.values() if s["client_id"] == client_id]

    def insert_site(self, row: dict[str, Any]) -> dict[str, Any]:
        sid = self._id("site")
        record = {"id": sid, **row}
        self.sites[sid] = record
        return record

    def delete_site(self, site_id: str) -> bool:
        return self.sites.pop(site_id, None) is not None


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeRepo) -> Callable[[str], None]:
    app.dependency_overrides[get_clients_repo] = lambda: repo

    def _as(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


async def test_list_clients_shape_and_masking(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None]
) -> None:
    cl = repo.seed_client()
    repo.sites["site-1"] = {"id": "site-1", "client_id": cl["id"], "domain": "np.com", "cms_type": "wordpress"}
    wire("viewer")
    resp = await client.get("/api/v1/clients")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    row = body[0]
    assert row["cn"] == "NorthPeak Dental"
    assert row["sites"] == 1
    assert row["since"] == "2023"
    assert row["renews"] == "Aug 14, 2026"
    assert row["contact"]["init"] == "SM"
    # portal password is always masked, never the real value
    assert row["portal"]["pass"] == "••••••••"
    assert row["portal"]["twoFA"] is True


async def test_get_client_404(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/clients/nope")
    assert resp.status_code == 404


async def test_create_requires_manage_clients(
    client: httpx.AsyncClient, wire: Callable[[str], None]
) -> None:
    wire("viewer")  # no manage_clients
    resp = await client.post("/api/v1/clients", json={"cn": "New Co"})
    assert resp.status_code == 403


async def test_create_client_as_manager(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None]
) -> None:
    wire("manager")  # manager has manage_clients
    resp = await client.post(
        "/api/v1/clients",
        json={"cn": "Verde Cafe", "industry": "Hospitality", "tier": "Starter", "contact": {"name": "Nadia R"}},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["cn"] == "Verde Cafe"
    assert body["sites"] == 0
    assert body["contact"]["init"] == "NR"
    assert len(repo.clients) == 1


async def test_update_client(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None]
) -> None:
    cl = repo.seed_client()
    wire("admin")
    resp = await client.patch(f"/api/v1/clients/{cl['id']}", json={"status": "paused", "mrr": 0})
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"
    # empty patch is rejected
    resp2 = await client.patch(f"/api/v1/clients/{cl['id']}", json={})
    assert resp2.status_code == 400


async def test_delete_client(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None]
) -> None:
    cl = repo.seed_client()
    wire("owner")
    resp = await client.delete(f"/api/v1/clients/{cl['id']}")
    assert resp.status_code == 204
    assert not repo.clients
    # deleting again -> 404
    resp2 = await client.delete(f"/api/v1/clients/{cl['id']}")
    assert resp2.status_code == 404


async def test_sites_crud(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None]
) -> None:
    cl = repo.seed_client()
    wire("manager")
    created = await client.post(
        f"/api/v1/clients/{cl['id']}/sites", json={"domain": "np.com"}
    )
    assert created.status_code == 201
    site = created.json()
    assert site["domain"] == "np.com"
    assert site["clientId"] == cl["id"]

    listed = await client.get(f"/api/v1/clients/{cl['id']}/sites")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    deleted = await client.delete(f"/api/v1/sites/{site['id']}")
    assert deleted.status_code == 204


async def test_list_clients_default_pagination(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/clients")
    assert resp.status_code == 200
    assert repo.last_page == (50, 0)  # hard-cap defaults


async def test_list_clients_explicit_pagination(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/clients", params={"limit": 5, "offset": 10})
    assert resp.status_code == 200
    assert repo.last_page == (5, 10)


async def test_list_clients_cap_enforcement(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None]
) -> None:
    wire("viewer")
    assert (await client.get("/api/v1/clients", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/v1/clients", params={"limit": 201})).status_code == 422
