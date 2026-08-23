"""P2-7 gate: cost-control endpoints (budgets, dial, log, spend-stop)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
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
        self.settings: dict[str, Any] = {"halted": False}
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
        # A newest-first synthetic log: J-0000 is newest, created_at descending. The
        # repo/endpoint slice it by offset/limit (the SQL does the same with
        # `order by created_at desc limit offset`), so we mirror that here.
        base = datetime.now(UTC)
        rows = [
            {
                "job_id": f"J-{i:04d}", "client_name": "NorthPeak Dental", "job_type": "audit",
                "provider": "DataForSEO", "cost": 0.75, "cached": False,
                "created_at": (base - timedelta(minutes=i)).isoformat(),
            }
            for i in range(10)
        ]
        end = None if limit is None else offset + limit
        return rows[offset:end]

    def today_spent(self) -> float:
        return 12.5

    def month_spent(self) -> float:
        return 187.25

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
    # +1 citations (7B-4), +1 site_analytics (7C), +1 policy watcher, +1 gmb,
    # +1 public_audit (P0-2: the free funnel gets its OWN dial so an operator can
    # switch the lead magnet off without disabling every client's paid audit).
    assert len(dial) == 18
    assert dial["public_audit"]["key"] == "public_audit"
    assert dial["public_audit"]["provider"] == "AuditEngine"
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
    assert e["id"] == "J-0000"
    assert e["provider"] == "DataForSEO"
    assert e["cost"] == 0.75


async def test_cost_log_paginates_newest_first(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    wire("viewer")
    # Page 1: two newest rows (J-0000, J-0001).
    p1 = await client.get("/api/v1/cost/log?limit=2&offset=0")
    assert p1.status_code == 200
    ids1 = [r["id"] for r in p1.json()]
    assert ids1 == ["J-0000", "J-0001"]  # respects limit + newest-first ordering
    # Page 2 (offset=2): the next window, non-overlapping.
    p2 = await client.get("/api/v1/cost/log?limit=2&offset=2")
    assert p2.status_code == 200
    ids2 = [r["id"] for r in p2.json()]
    assert ids2 == ["J-0002", "J-0003"]
    assert set(ids1).isdisjoint(ids2)
    # A short final page (< limit) is the has-more=false signal the frontend reads.
    last = await client.get("/api/v1/cost/log?limit=50&offset=8")
    assert len(last.json()) == 2  # only 2 rows remain of the 10


async def test_spend_halt_get_and_toggle(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    wire("viewer")
    got = await client.get("/api/v1/cost/spend-stop")
    assert got.status_code == 200
    body = got.json()
    assert body["halted"] is False
    assert body["todaySpent"] == 12.5
    assert body["monthSpent"] == 187.25  # REAL calendar-month figure, not the all-time budget counter
    assert "dailyStop" not in body  # the per-day threshold is gone
    # toggling the halt requires owner/admin
    denied = await client.put("/api/v1/cost/spend-stop", json={"halted": True})
    assert denied.status_code == 403
    # owner engages the halt
    wire("owner")
    on = await client.put("/api/v1/cost/spend-stop", json={"halted": True})
    assert on.status_code == 200
    assert on.json()["halted"] is True
    assert on.json()["monthSpent"] == 187.25
    assert "dailyStop" not in on.json()
    # ...and toggling it OFF restores the normal state
    off = await client.put("/api/v1/cost/spend-stop", json={"halted": False})
    assert off.status_code == 200
    assert off.json()["halted"] is False


# --------------------------------------------------------------------------- #
# WS-1 (Truth) · GET /cost/pricing — live unit prices, never hardcoded ones
# --------------------------------------------------------------------------- #
async def test_pricing_reports_the_settings_the_gate_actually_bills_at(
    client: httpx.AsyncClient, wire: Callable[[str], None]
) -> None:
    """Every figure served must equal the ``Settings`` value ``pricing.py`` computes from.

    This is the whole point of the endpoint: the UI previously shipped hardcoded
    strings ("$0.30 / search") that were ~300x the real Serper price and could not
    track an env change. Assert against ``Settings`` and ``pricing`` directly, so
    the test fails if the two ever diverge rather than pinning a literal here too.
    """
    from app.config import Settings
    from app.services import pricing

    wire("viewer")
    resp = await client.get("/api/v1/cost/pricing")
    assert resp.status_code == 200
    by_provider = {p["provider"]: p for p in resp.json()}

    s = Settings(_env_file=None, app_env="dev")

    serper = by_provider["Serper"]
    assert serper["paid"] is True
    assert serper["lines"][0]["amount"] == s.price_serper_per_query
    # The served number IS the number one real call commits.
    assert pricing.serper_cost(s, queries=1) == serper["lines"][0]["amount"]

    dfs = by_provider["DataForSEO"]
    assert dfs["lines"][0]["amount"] == pricing.dataforseo_cost(s, calls=1)

    places = by_provider["Places"]
    assert places["lines"][0]["amount"] == pricing.google_api_cost(s, calls=1)

    img = by_provider["ImageGen"]
    assert img["lines"][0]["amount"] == pricing.image_cost(s, images=1)

    anthropic = {line["label"]: line["amount"] for line in by_provider["Anthropic"]["lines"]}
    assert anthropic["Haiku input"] == s.price_anthropic_haiku_input_per_mtok
    assert anthropic["Opus output"] == s.price_anthropic_opus_output_per_mtok
    # A million haiku input tokens must cost exactly the quoted per-MTok price.
    assert pricing.anthropic_cost(
        s, model="claude-haiku-4-5", input_tokens=1_000_000, output_tokens=0
    ) == anthropic["Haiku input"]


async def test_pricing_marks_free_tier_providers_as_free_not_unpriced(
    client: httpx.AsyncClient, wire: Callable[[str], None]
) -> None:
    """A free-tier provider is stated as free — never left as an unpriced blank."""
    wire("viewer")
    rows = {p["provider"]: p for p in (await client.get("/api/v1/cost/pricing")).json()}
    for name in ("PageSpeed", "Google"):
        assert rows[name]["paid"] is False
        assert rows[name]["lines"] and rows[name]["lines"][0]["amount"] == 0.0


async def test_pricing_tracks_an_env_override(
    client: httpx.AsyncClient, wire: Callable[[str], None], app: FastAPI
) -> None:
    """Re-pricing a provider by env must move the number on screen, with no deploy."""
    from app.config import Settings, get_settings

    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, app_env="dev", price_serper_per_query=0.004
    )
    wire("viewer")
    rows = {p["provider"]: p for p in (await client.get("/api/v1/cost/pricing")).json()}
    assert rows["Serper"]["lines"][0]["amount"] == 0.004


async def test_pricing_requires_authentication(client: httpx.AsyncClient) -> None:
    """Unit prices are internal cost data: no anonymous read."""
    resp = await client.get("/api/v1/cost/pricing")
    assert resp.status_code in (401, 403)


async def test_no_dial_note_quotes_a_price(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    """Dial notes describe WHAT a feature spends on, never HOW MUCH.

    A price baked into a note string cannot track settings and goes stale silently
    (the content dial read "~$0.90/pg" against a token-billed provider).
    """
    import re

    wire("viewer")
    for d in (await client.get("/api/v1/cost/dial")).json():
        assert not re.search(r"\$\s*\d", d["note"]), f"dial {d['key']} note quotes a price: {d['note']}"
