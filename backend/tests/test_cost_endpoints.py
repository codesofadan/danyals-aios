"""P2-7 gate: cost-control endpoints (budgets, dial, log, spend-stop)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.cost_repo import get_cost_repo

pytestmark = pytest.mark.unit


class FakeCostRepo:
    def __init__(self) -> None:
        self.dial: dict[str, str] = {}
        self.settings: dict[str, Any] = {"daily_stop": 75, "halted": False}
        self._clients = {"cl-1": {"name": "NorthPeak Dental", "tier": "Scale", "contact_color": "#7B69EE"}}
        self._budgets: dict[str, int] = {"cl-1": 500}

    def list_budgets(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        out = []
        for cid, cap in self._budgets.items():
            c = self._clients[cid]
            out.append({"id": cid, "cn": c["name"], "tier": c["tier"], "cap": cap, "spent": 312, "c": c["contact_color"]})
        return out

    def upsert_budget(self, client_id: str, cap: int) -> dict[str, Any] | None:
        if client_id not in self._clients:
            return None
        self._budgets[client_id] = cap
        c = self._clients[client_id]
        return {"id": client_id, "cn": c["name"], "tier": c["tier"], "cap": cap, "spent": 0, "c": c["contact_color"]}

    def dial_modes(self) -> dict[str, str]:
        return dict(self.dial)

    def set_dial(self, feature_key: str, mode: str) -> None:
        self.dial[feature_key] = mode

    def list_cost_log(self, limit: int | None = 50, offset: int = 0) -> list[dict[str, Any]]:
        rows = [
            {
                "job_id": "J-2041", "client_name": "NorthPeak Dental", "job_type": "audit",
                "provider": "DataForSEO", "cost": 0.75, "cached": False,
                "created_at": datetime.now(UTC).isoformat(),
            }
        ]
        end = None if limit is None else offset + limit
        return rows[offset:end]

    def today_spent(self) -> float:
        return 12.5

    def get_settings(self) -> dict[str, Any]:
        return self.settings

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        self.settings.update(changes)
        return self.settings


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeCostRepo:
    return FakeCostRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeCostRepo) -> Callable[[str], None]:
    app.dependency_overrides[get_cost_repo] = lambda: repo

    def _as(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


async def test_list_budgets_shape(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/cost/budgets")
    assert resp.status_code == 200
    b = resp.json()[0]
    assert set(b) == {"id", "cn", "tier", "cap", "spent", "c"}
    assert b["cap"] == 500


async def test_set_budget_requires_manage_clients(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    wire("viewer")
    resp = await client.put("/api/v1/cost/budgets/cl-1", json={"cap": 300})
    assert resp.status_code == 403


async def test_set_budget_ok_and_404(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    wire("manager")
    ok = await client.put("/api/v1/cost/budgets/cl-1", json={"cap": 300})
    assert ok.status_code == 200
    assert ok.json()["cap"] == 300
    missing = await client.put("/api/v1/cost/budgets/nope", json={"cap": 300})
    assert missing.status_code == 404


async def test_dial_merges_defaults(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/cost/dial")
    assert resp.status_code == 200
    dial = {d["key"]: d for d in resp.json()}
    assert len(dial) == 16  # +1 citations (7B-4), +1 site_analytics (7C), +1 policy (Module 05 watcher)
    assert dial["keywords"]["mode"] == "off"  # default
    assert dial["tech_audit"]["mode"] == "api"
    # Part 8: the tool modules' spends are dial-controllable. rank_tracker is the
    # first STANDING per-client cost, so it defaults off - ops must opt in.
    assert dial["rank_tracker"]["mode"] == "off"
    assert dial["on_page"]["mode"] == "off"
    assert dial["competitor_intel"]["mode"] == "off"
    # P6B-4: the context module's two AI spends are dial-controllable.
    assert dial["context"]["provider"] == "Anthropic"
    assert dial["context_embed"]["provider"] == "Voyage"
    assert dial["context"]["mode"] == "api"  # default
    # P7A-3: the content RESEARCH spend is dial-controllable (Serper).
    assert dial["content_research"]["provider"] == "Serper"
    assert dial["content_research"]["mode"] == "api"  # default
    # P9-5: the web in-product AI-assist spend is dial-controllable (Anthropic).
    assert dial["ai_assist"]["provider"] == "Anthropic"
    assert dial["ai_assist"]["mode"] == "api"  # default


async def test_set_dial_owner_admin_only(client: httpx.AsyncClient, repo: FakeCostRepo, wire: Callable[[str], None]) -> None:
    wire("manager")  # manager is not owner/admin
    denied = await client.put("/api/v1/cost/dial/keywords", json={"mode": "api"})
    assert denied.status_code == 403
    wire("admin")
    ok = await client.put("/api/v1/cost/dial/keywords", json={"mode": "api"})
    assert ok.status_code == 200
    assert ok.json()["mode"] == "api"
    unknown = await client.put("/api/v1/cost/dial/nope", json={"mode": "api"})
    assert unknown.status_code == 404


async def test_cost_log_shape(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/cost/log")
    assert resp.status_code == 200
    e = resp.json()[0]
    assert e["id"] == "J-2041"
    assert e["provider"] == "DataForSEO"
    assert e["cost"] == 0.75


async def test_spend_stop_get_and_set(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    wire("viewer")
    got = await client.get("/api/v1/cost/spend-stop")
    assert got.status_code == 200
    assert got.json()["dailyStop"] == 75
    assert got.json()["todaySpent"] == 12.5
    # setting requires owner/admin
    denied = await client.put("/api/v1/cost/spend-stop", json={"halted": True})
    assert denied.status_code == 403
    wire("owner")
    ok = await client.put("/api/v1/cost/spend-stop", json={"halted": True, "daily_stop": 120})
    assert ok.status_code == 200
    assert ok.json()["halted"] is True
    assert ok.json()["dailyStop"] == 120
