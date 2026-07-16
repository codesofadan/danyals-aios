"""Unit tests for the Upsells module: the response/request models (the exact 11
``Upsell`` keys + the ``fiverrUrl`` alias) and the /upsells endpoints with a faked
repo - list (staff), create/patch/toggle/reorder (owner/admin), and the RBAC/404
edges. No DB, no network.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.upsells_repo import get_upsells_repo
from app.schemas.upsells import UpsellCreate, UpsellResponse, to_response

pytestmark = pytest.mark.unit

_UPSELL_KEYS = {
    "id", "title", "description", "fiverrUrl", "active", "clicks30d",
    "price", "rating", "reviews", "icon", "color",
}


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-000000000001",
        "title": "Premium Backlink Package",
        "description": "20 high-authority editorial backlinks.",
        "fiverr_url": "https://www.fiverr.com/xegents/build-premium-backlinks",
        "active": True,
        "clicks30d": 412,
        "price": 149,
        "rating": 4.9,
        "reviews": 318,
        "icon": "link",
        "color": "#7B69EE",
        "sort_order": 0,
    }
    row.update(over)
    return row


# --- schema shape -------------------------------------------------------------

def test_response_emits_exactly_the_11_contract_keys() -> None:
    emitted = {
        f.serialization_alias or f.alias or name
        for name, f in UpsellResponse.model_fields.items()
    }
    assert emitted == _UPSELL_KEYS


def test_fiverr_url_is_emitted_as_wire_key_fiverr_url() -> None:
    dumped = to_response(_row()).model_dump(by_alias=True)
    assert set(dumped) == _UPSELL_KEYS
    assert "fiverrUrl" in dumped and "fiverr_url" not in dumped
    assert dumped["fiverrUrl"].startswith("https://www.fiverr.com/")
    assert dumped["clicks30d"] == 412


def test_no_internal_columns_leak() -> None:
    dumped = to_response(_row(sort_order=5, created_at="2026-07-16")).model_dump(by_alias=True)
    assert set(dumped) == _UPSELL_KEYS  # sort_order / timestamps never surface


def test_response_missing_values_fall_back_safely() -> None:
    resp = to_response({"id": 7})
    assert resp.id == "7"
    assert resp.title == ""
    assert resp.active is False
    assert resp.clicks30d == 0
    assert resp.price == 0.0


def test_create_model_has_no_clicks30d_field() -> None:
    # clicks30d is portal-tracked, never client-supplied at creation.
    assert "clicks30d" not in UpsellCreate.model_fields


def test_create_model_accepts_camelcase_fiverr_url() -> None:
    created = UpsellCreate.model_validate({"title": "X", "fiverrUrl": "https://f/x"})
    assert created.fiverr_url == "https://f/x"


# --- endpoints (faked repo) ---------------------------------------------------

class FakeUpsellsRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def seed(self, **over: Any) -> dict[str, Any]:
        self._seq += 1
        uid = over.get("id", f"up-{self._seq}")
        rec = _row(id=uid)
        rec["_i"] = self._seq
        rec.update(over)
        self.rows[uid] = rec
        return rec

    def list_upsells(
        self, *, active_only: bool = False, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        rows = list(self.rows.values())
        if active_only:
            rows = [r for r in rows if r.get("active")]
        return sorted(rows, key=lambda r: (r.get("sort_order", 0), r.get("_i", 0)))

    def get_upsell(self, upsell_id: str) -> dict[str, Any] | None:
        return self.rows.get(upsell_id)

    def insert_upsell(self, row: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        uid = f"up-{self._seq}"
        rec = {"id": uid, "clicks30d": 0, "_i": self._seq, **row}
        self.rows[uid] = rec
        return rec

    def update_upsell(self, upsell_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        row = self.rows.get(upsell_id)
        if row is None:
            return None
        row.update(changes)
        return row


def _user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeUpsellsRepo:
    return FakeUpsellsRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeUpsellsRepo) -> Callable[..., None]:
    app.dependency_overrides[get_upsells_repo] = lambda: repo

    def _as(role: str, uid: str = "u-1") -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)

    return _as


# reads

async def test_client_forbidden_from_reads(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")  # a portal client lacks view_reports
    assert (await client.get("/api/v1/upsells")).status_code == 403


async def test_list_shape_and_active_only_filter(
    client: httpx.AsyncClient, repo: FakeUpsellsRepo, wire: Callable[..., None]
) -> None:
    repo.seed(active=True)
    repo.seed(active=False)
    wire("viewer")
    body = (await client.get("/api/v1/upsells")).json()
    assert len(body) == 2
    assert set(body[0]) == _UPSELL_KEYS
    only_active = (await client.get("/api/v1/upsells", params={"active_only": "true"})).json()
    assert len(only_active) == 1
    assert only_active[0]["active"] is True


# create

async def test_create_requires_owner_or_admin(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager", "u-lead")  # a lead, but upsell management is owner/admin only
    resp = await client.post("/api/v1/upsells", json={"title": "X", "fiverrUrl": "https://f/x"})
    assert resp.status_code == 403


async def test_create_happy_path(
    client: httpx.AsyncClient, repo: FakeUpsellsRepo, wire: Callable[..., None]
) -> None:
    wire("admin", "u-admin")
    resp = await client.post(
        "/api/v1/upsells",
        json={"title": "Backlinks", "description": "d", "fiverrUrl": "https://f/x",
              "price": 149, "rating": 4.9, "reviews": 318, "icon": "link", "color": "#f00"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == _UPSELL_KEYS
    assert body["title"] == "Backlinks"
    assert body["fiverrUrl"] == "https://f/x"
    assert body["clicks30d"] == 0  # portal-tracked, starts at 0
    assert body["active"] is True


async def test_create_rejects_blank_title(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("owner", "u-owner")
    resp = await client.post("/api/v1/upsells", json={"title": ""})
    assert resp.status_code == 422


# patch

async def test_patch_updates_fields(
    client: httpx.AsyncClient, repo: FakeUpsellsRepo, wire: Callable[..., None]
) -> None:
    seeded = repo.seed()
    wire("owner", "u-owner")
    resp = await client.patch(
        f"/api/v1/upsells/{seeded['id']}", json={"price": 199, "active": False}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["price"] == 199
    assert body["active"] is False


async def test_patch_unknown_id_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("owner", "u-owner")
    resp = await client.patch("/api/v1/upsells/ghost", json={"price": 1})
    assert resp.status_code == 404


async def test_patch_forbidden_for_manager(
    client: httpx.AsyncClient, repo: FakeUpsellsRepo, wire: Callable[..., None]
) -> None:
    seeded = repo.seed()
    wire("manager", "u-lead")
    resp = await client.patch(f"/api/v1/upsells/{seeded['id']}", json={"price": 1})
    assert resp.status_code == 403


# toggle

async def test_toggle_flips_active(
    client: httpx.AsyncClient, repo: FakeUpsellsRepo, wire: Callable[..., None]
) -> None:
    seeded = repo.seed(active=True)
    wire("admin", "u-admin")
    resp = await client.post(f"/api/v1/upsells/{seeded['id']}/toggle")
    assert resp.status_code == 200
    assert resp.json()["active"] is False
    # flip back
    resp2 = await client.post(f"/api/v1/upsells/{seeded['id']}/toggle")
    assert resp2.json()["active"] is True


async def test_toggle_unknown_id_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("admin", "u-admin")
    assert (await client.post("/api/v1/upsells/ghost/toggle")).status_code == 404


# reorder

async def test_reorder_sets_sort_order_and_returns_full_list(
    client: httpx.AsyncClient, repo: FakeUpsellsRepo, wire: Callable[..., None]
) -> None:
    a = repo.seed(id="up-a", sort_order=9)
    b = repo.seed(id="up-b", sort_order=8)
    wire("owner", "u-owner")
    resp = await client.post("/api/v1/upsells/reorder", json={"ids": [b["id"], a["id"]]})
    assert resp.status_code == 200
    body = resp.json()
    # up-b now sort_order 0, up-a sort_order 1 -> b first
    assert [u["id"] for u in body] == ["up-b", "up-a"]
    assert repo.rows["up-b"]["sort_order"] == 0
    assert repo.rows["up-a"]["sort_order"] == 1


async def test_reorder_forbidden_for_specialist(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("specialist", "u-1")
    resp = await client.post("/api/v1/upsells/reorder", json={"ids": []})
    assert resp.status_code == 403
