"""P2-8 gate: delivery tiers (free/semi/fully) kept separate from subscription."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.tiers_repo import get_tiers_repo
from app.schemas.tiers import delivery_tier_modes

pytestmark = pytest.mark.unit


class FakeTiersRepo:
    def __init__(self) -> None:
        self.clients = {
            "cl-1": {"id": "cl-1", "name": "NorthPeak Dental", "industry": "Healthcare",
                     "contact_color": "#7B69EE", "delivery_tier": "fully"},
        }

    def list_tier_clients(
        self, *, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        return list(self.clients.values())

    def set_delivery_tier(self, client_id: str, tier: str) -> dict[str, Any] | None:
        if client_id not in self.clients:
            return None
        self.clients[client_id]["delivery_tier"] = tier
        return self.clients[client_id]


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeTiersRepo:
    return FakeTiersRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeTiersRepo) -> Callable[[str], None]:
    app.dependency_overrides[get_tiers_repo] = lambda: repo

    def _as(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


@pytest.mark.unit
def test_delivery_tier_modes_are_presets_over_the_dial() -> None:
    # free is the most restrictive, fully is all-API.
    free = delivery_tier_modes("free")
    fully = delivery_tier_modes("fully")
    assert free["C"] == "off" and free["A"] == "byhand"
    assert all(m == "api" for m in fully.values())


async def test_list_tiers(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/tiers")
    assert resp.status_code == 200
    tiers = {t["key"]: t for t in resp.json()}
    assert set(tiers) == {"free", "semi", "fully"}
    assert tiers["semi"]["popular"] is True
    assert tiers["fully"]["price"] == 54


async def test_feature_areas_matrix(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/tiers/feature-areas")
    assert resp.status_code == 200
    areas = resp.json()
    assert len(areas) == 7
    assert areas[0]["modes"]["fully"] == "api"


async def test_list_and_set_delivery_tier(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    wire("viewer")
    listed = await client.get("/api/v1/tiers/clients")
    assert listed.status_code == 200
    row = listed.json()[0]
    assert row["tier"] == "fully"
    assert row["init"] == "ND"

    # setting requires manage_clients
    denied = await client.put("/api/v1/tiers/clients/cl-1", json={"tier": "semi"})
    assert denied.status_code == 403
    wire("manager")
    ok = await client.put("/api/v1/tiers/clients/cl-1", json={"tier": "semi"})
    assert ok.status_code == 200
    assert ok.json()["tier"] == "semi"
    missing = await client.put("/api/v1/tiers/clients/nope", json={"tier": "free"})
    assert missing.status_code == 404
