"""Phase 3.2 · the audit DEPTH axis - breadth, the pre-flight estimate, and the
confirmation a deep run needs before it spends.

The plan (§3.2) specifies four audit tiers; the platform served two, because
``tier`` (free|paid) is a SPEND authorisation that was also being read as a depth
choice it cannot express. These tests pin the third axis and the two things that
make it safe: an estimate derived from the SAME arithmetic as the bill, and a
confirmation bound to a specific figure rather than to a yes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from itertools import combinations
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.core.auth import CurrentUser, get_current_user
from app.core.security import PrivateAddressError
from app.db.audits_repo import get_audits_repo
from app.db.clients_repo import get_clients_repo
from app.routers.audits import get_audit_enqueuer, get_paid_audit_gate, get_site_size_probe
from app.schemas.audits import AuditCreate, default_depth_for_tier
from app.services.audit_depth import (
    CONFIRM_REQUIRED_DEPTHS,
    agent_fanout_enabled,
    estimate_audit_cost,
    planned_pages,
)
from app.services.cost_gate import GateDecision
from app.services.site_size import UNKNOWN, SiteSize
from integrations.audit_engine import build_argv

pytestmark = pytest.mark.unit

_PUBLIC_URL = "http://93.184.216.34"
_TYPES = ("onpage", "offpage", "technical", "local", "geo", "strategy")


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, **over)


# --------------------------------------------------------------------------- #
# The breadth ladder
# --------------------------------------------------------------------------- #
def test_each_depth_has_its_own_breadth_and_they_increase() -> None:
    s = _settings()
    free, standard, deep = (planned_pages(s, d) for d in ("free", "standard", "deep"))
    assert free < standard < deep
    # The plan's figures: free ~10-15, standard ~15-20, deep 200-300+.
    assert free == s.audit_free_max_pages == 15
    assert standard == s.audit_standard_max_pages == 20
    assert deep == s.audit_deep_max_pages == 300


def test_breadth_knobs_are_independent() -> None:
    """Widening one depth must never widen another.

    The free budget is the UNAUTHENTICATED funnel's exposure, so it has to be
    impossible to raise it by tuning the paid product - the same separation the
    free funnel already had from `audit_max_pages`, extended to the new depths.
    """
    s = _settings(audit_deep_max_pages=999)
    assert planned_pages(s, "deep") == 999
    assert planned_pages(s, "free") == 15
    assert planned_pages(s, "standard") == 20


def test_free_tier_defaults_to_free_depth_and_paid_to_standard() -> None:
    assert default_depth_for_tier("Free") == "free"
    assert default_depth_for_tier("Paid") == "standard"


def test_a_request_without_a_depth_keeps_its_pre_existing_behaviour() -> None:
    """An older caller that never heard of depth must not change what it runs."""
    assert AuditCreate(client_id="c", url=_PUBLIC_URL, tier="Free").resolved_depth() == "free"
    assert AuditCreate(client_id="c", url=_PUBLIC_URL, tier="Paid").resolved_depth() == "standard"


# --------------------------------------------------------------------------- #
# The estimate
# --------------------------------------------------------------------------- #
def test_a_free_run_is_estimated_at_zero() -> None:
    """Not a policy choice - `--mode free` clears every paid provider at the engine,
    so there is nothing to spend and the estimate says so."""
    s = _settings()
    assert estimate_audit_cost(s, mode="free", depth="free") == 0.0


def test_the_estimate_moves_with_depth_which_the_flat_constant_could_not() -> None:
    """The defect the derived estimate replaces.

    `settings.audit_paid_cost_estimate` is ONE number. It was the pre-flight
    figure for a 20-page single-dimension run and for a 300-page full consulting
    run alike, so the cost dial and the client budget cap could not tell a cheap
    request from one an order of magnitude larger.
    """
    s = _settings()
    standard = estimate_audit_cost(s, mode="paid", depth="standard", types=["onpage"])
    deep = estimate_audit_cost(s, mode="paid", depth="deep", types=["onpage"])
    assert deep > standard * 10
    # Both were previously quoted at the same flat figure.
    assert s.audit_paid_cost_estimate not in (standard, deep)


def test_the_estimate_drops_the_agent_fan_out_when_no_agent_type_is_selected() -> None:
    s = _settings()
    with_agents = estimate_audit_cost(s, mode="paid", depth="standard", types=["strategy"])
    without = estimate_audit_cost(s, mode="paid", depth="standard", types=["onpage"])
    assert with_agents > without
    # The fan-out is the dominant term, which is why pricing it wrong made the
    # flat estimate useless in both directions rather than merely imprecise.
    assert with_agents > without * 4


def test_an_empty_selection_is_priced_as_the_full_run() -> None:
    """Empty types is the comprehensive audit, not the cheapest one."""
    s = _settings()
    assert estimate_audit_cost(s, mode="paid", depth="deep", types=[]) == estimate_audit_cost(
        s, mode="paid", depth="deep", types=["strategy"]
    )


@pytest.mark.parametrize(
    "types",
    [list(c) for n in range(len(_TYPES) + 1) for c in combinations(_TYPES, n)],
)
def test_agent_fanout_mirrors_build_argv(types: list[str]) -> None:
    """The estimate is only honest if it prices the run that will ACTUALLY launch.

    `agent_fanout_enabled` duplicates a rule that lives in `build_argv`, and a
    duplicated rule drifts. This walks all 64 type selections and asserts the two
    agree on every one, so a change to the engine's flag gating fails here rather
    than quietly mispricing every deep audit.
    """
    argv = build_argv(
        domain="example.com", mode="paid", max_pages=100,
        profile="general", comprehensive=True, types=types,
    )
    argv_says_on = "--agents" in argv and argv[argv.index("--agents") + 1] == "on"
    assert agent_fanout_enabled(types) is argv_says_on


# --------------------------------------------------------------------------- #
# The endpoint: quote, confirm, run
# --------------------------------------------------------------------------- #
class FakeAuditsRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def insert_audit(self, row: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        aid = f"aud-{self._seq}"
        rec = {"id": aid, "created_at": datetime.now(UTC).isoformat(), "score": None,
               "runtime_seconds": None, "pdf_path": None, "json_path": None, **row}
        self.rows[aid] = rec
        return rec

    def list_audits(self, **_: Any) -> list[dict[str, Any]]:
        return list(self.rows.values())

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        return self.rows.get(audit_id)


class FakeClientsRepo:
    def get_client(self, client_id: str) -> dict[str, Any]:
        return {"id": client_id, "name": "Verde Cafe"}


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
def gated() -> list[float]:
    """Every cost the pre-flight gate was asked to evaluate."""
    return []


@pytest.fixture
def probed() -> list[str]:
    """Every URL the size probe was asked to measure."""
    return []


@pytest.fixture
def wire(
    app: FastAPI, repo: FakeAuditsRepo, enqueued: list[str], gated: list[float],
    probed: list[str],
) -> Callable[..., None]:
    app.dependency_overrides[get_audits_repo] = lambda: repo
    app.dependency_overrides[get_audit_enqueuer] = lambda: enqueued.append
    app.dependency_overrides[get_clients_repo] = lambda: FakeClientsRepo()

    def _gate(client_id: str, client_name: str, cost: float) -> GateDecision:
        gated.append(cost)
        return GateDecision("call", cost=cost)

    app.dependency_overrides[get_paid_audit_gate] = lambda: _gate

    def _measure(url: str) -> SiteSize:
        probed.append(url)
        return _measure.result  # type: ignore[attr-defined]

    _measure.result = UNKNOWN  # type: ignore[attr-defined]
    app.dependency_overrides[get_site_size_probe] = lambda: _measure

    def _as(role: str, *, size: SiteSize = UNKNOWN) -> None:
        _measure.result = size  # type: ignore[attr-defined]
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


async def _quote(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    resp = await client.post("/api/v1/audits/estimate", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_estimate_returns_the_figure_and_its_derivation(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    q = await _quote(client, tier="Paid", depth="deep", types=["strategy"])
    assert q["depth"] == "deep"
    assert q["pages"] == 300
    assert q["agents"] is True
    assert q["estimatedCost"] > 0
    assert q["confirmationRequired"] is True


async def test_estimate_needs_run_audits_not_merely_a_login(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    """It serves the platform's own provider unit costs out of in-process settings.

    WU-13/WU-14 found the same shape twice - a handler serving constants is never
    RLS-bounded, whatever table sits beside it - so this one is guarded at the app
    layer, by name, and a viewer is refused.
    """
    wire("viewer")
    resp = await client.post("/api/v1/audits/estimate", json={"tier": "Paid"})
    assert resp.status_code == 403


async def test_estimate_spends_nothing_and_creates_nothing(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, enqueued: list[str],
    gated: list[float], wire: Callable[..., None],
) -> None:
    wire("manager")
    await _quote(client, tier="Paid", depth="deep")
    assert repo.rows == {} and enqueued == [] and gated == []


async def test_a_deep_run_is_refused_without_a_confirmed_estimate(
    client: httpx.AsyncClient, enqueued: list[str], wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Paid", "depth": "deep"},
    )
    assert resp.status_code == 400
    assert "confirmed" in resp.json()["error"]["message"]
    assert enqueued == []


async def test_a_stale_confirmation_is_refused_rather_than_charged(
    client: httpx.AsyncClient, enqueued: list[str], wire: Callable[..., None]
) -> None:
    """A confirmation is a decision about a NUMBER, so it cannot outlive it.

    The operator echoes the figure back rather than a boolean; if unit prices or
    the depth's page budget moved between quote and submit, the run is refused and
    re-quoted instead of being charged against a figure nobody saw.
    """
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={
            "client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Paid", "depth": "deep",
            "confirmed_estimate": 0.01,  # a figure the server will not recognise
        },
    )
    assert resp.status_code == 409
    assert "estimate changed" in resp.json()["error"]["message"].lower()
    assert enqueued == []


async def test_a_confirmed_deep_run_persists_its_breadth_and_its_quote(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, enqueued: list[str],
    wire: Callable[..., None],
) -> None:
    wire("manager")
    q = await _quote(client, tier="Paid", depth="deep", types=["strategy"])
    resp = await client.post(
        "/api/v1/audits",
        json={
            "client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Paid", "depth": "deep",
            "types": ["strategy"], "confirmed_estimate": q["estimatedCost"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["depth"] == "deep"
    assert body["maxPages"] == 300
    assert body["estimatedCost"] == pytest.approx(q["estimatedCost"])
    row = repo.rows[body["id"]]
    # The durable evidence that a human was shown a number and accepted it.
    assert row["estimate_confirmed_at"] is not None
    assert enqueued == [body["id"]]


async def test_standard_runs_without_interrupting_the_operator(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    """Only the depths in CONFIRM_REQUIRED_DEPTHS stop to ask."""
    assert "standard" not in CONFIRM_REQUIRED_DEPTHS
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Paid",
              "depth": "standard", "types": ["technical"]},
    )
    assert resp.status_code == 201
    row = repo.rows[resp.json()["id"]]
    assert row["max_pages"] == 20 and row["estimate_confirmed_at"] is None


async def test_the_gate_now_sees_the_run_it_is_gating(
    client: httpx.AsyncClient, gated: list[float], wire: Callable[..., None]
) -> None:
    """The load-bearing consequence of a derived estimate.

    A budget cap that evaluates a flat $1.50 for every paid audit either blocks a
    trivial run or waves through one twenty times its size - the number it was
    given had nothing to do with the request. These two runs now reach the gate as
    the different things they are.
    """
    wire("manager")
    await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Paid",
              "depth": "standard", "types": ["technical"]},
    )
    q = await _quote(client, tier="Paid", depth="deep", types=["strategy"])
    await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Paid", "depth": "deep",
              "types": ["strategy"], "confirmed_estimate": q["estimatedCost"]},
    )
    assert len(gated) == 2
    small, large = gated
    assert large > small * 10


async def test_a_free_run_may_not_buy_extra_breadth(
    client: httpx.AsyncClient, enqueued: list[str], wire: Callable[..., None]
) -> None:
    """`--mode free` clears every paid provider, so a wider free crawl returns more
    pages of the same two deterministic dimensions while multiplying the load on an
    UNMETERED path. Refused, not silently downgraded: a caller told nothing would
    report a 300-page audit it never got."""
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Free",
              "depth": "deep", "types": ["technical"]},
    )
    assert resp.status_code == 400
    assert "Paid tier" in resp.json()["error"]["message"]
    assert enqueued == []


# --------------------------------------------------------------------------- #
# Scaling a deep run to the site's actual size (plan §3.2)
# --------------------------------------------------------------------------- #
async def test_a_deep_quote_scales_down_to_the_measured_site(
    client: httpx.AsyncClient, probed: list[str], wire: Callable[..., None]
) -> None:
    """The gap this closes.

    The engine always stopped at whatever the site had, so the BILL was honest.
    The QUOTE was not: it named the 300-page ceiling for a 40-page site, and the
    pre-flight gate reserved budget against that figure.
    """
    wire("manager", size=SiteSize(pages=40, source="sitemap"))
    q = await _quote(client, tier="Paid", depth="deep", url=_PUBLIC_URL, types=["onpage"])
    assert q["pages"] == 40
    assert q["measuredPages"] == 40
    assert q["sizeSource"] == "sitemap"
    assert probed == [_PUBLIC_URL]

    ceiling_quote = await _quote(client, tier="Paid", depth="deep", types=["onpage"])
    assert ceiling_quote["pages"] == 300
    assert q["estimatedCost"] < ceiling_quote["estimatedCost"]


async def test_a_site_larger_than_the_ceiling_is_still_capped(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    """A measurement may only ever NARROW the run. The sitemap is an input we do
    not control, so it must not be able to raise a spend ceiling."""
    wire("manager", size=SiteSize(pages=9000, source="sitemap_index"))
    q = await _quote(client, tier="Paid", depth="deep", url=_PUBLIC_URL)
    assert q["pages"] == 300


async def test_a_one_page_sitemap_does_not_collapse_a_deep_audit(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    """Stale, partial and landing-page-only sitemaps are common. Without the floor
    an operator would pay a deep price to confirm a one-page crawl."""
    wire("manager", size=SiteSize(pages=1, source="sitemap"))
    q = await _quote(client, tier="Paid", depth="deep", url=_PUBLIC_URL)
    assert q["pages"] == 20  # the standard budget, not 1


async def test_an_unmeasurable_site_falls_back_to_the_ceiling_and_says_so(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    """Erring HIGH is the safe direction, and `measuredPages: null` is what lets an
    operator see that is what happened rather than wonder why the number is round."""
    wire("manager", size=UNKNOWN)
    q = await _quote(client, tier="Paid", depth="deep", url=_PUBLIC_URL)
    assert q["pages"] == 300
    assert q["measuredPages"] is None
    assert q["sizeSource"] == "unknown"


async def test_only_deep_spends_a_request_measuring_the_site(
    client: httpx.AsyncClient, probed: list[str], wire: Callable[..., None]
) -> None:
    """Free and standard are small fixed reads; probing them would spend an
    outbound request on a number nothing consumes."""
    wire("manager", size=SiteSize(pages=40, source="sitemap"))
    await _quote(client, tier="Paid", depth="standard", url=_PUBLIC_URL)
    await _quote(client, tier="Free", depth="free", url=_PUBLIC_URL)
    assert probed == []


async def test_the_quoted_budget_is_echoed_back_and_reproduces_the_figure(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    """How a deep run is created at the price it was quoted WITHOUT re-probing.

    Re-probing on submit would bind the confirmation to a value that can move
    between quote and submit, producing 409s that mean nothing. Echoing the budget
    back makes the arithmetic reproducible; the ceiling check below is what keeps
    the echo from being a way to ask for more.
    """
    wire("manager", size=SiteSize(pages=40, source="sitemap"))
    q = await _quote(client, tier="Paid", depth="deep", url=_PUBLIC_URL, types=["onpage"])
    resp = await client.post(
        "/api/v1/audits",
        json={
            "client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Paid", "depth": "deep",
            "types": ["onpage"], "max_pages": q["pages"],
            "confirmed_estimate": q["estimatedCost"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["maxPages"] == 40
    assert body["estimatedCost"] == pytest.approx(q["estimatedCost"])
    assert repo.rows[body["id"]]["max_pages"] == 40


async def test_an_echoed_budget_may_not_exceed_the_depth_ceiling(
    client: httpx.AsyncClient, enqueued: list[str], wire: Callable[..., None]
) -> None:
    """The echo can only ever narrow a run. A caller that inflates it is refused;
    one that shrinks it merely gets a smaller audit than it was entitled to, which
    is not worth a round trip to prevent."""
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={
            "client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Paid", "depth": "deep",
            "max_pages": 5000, "confirmed_estimate": 1.0,
        },
    )
    assert resp.status_code == 400
    assert "ceiling" in resp.json()["error"]["message"]
    assert enqueued == []


async def test_a_blocked_host_is_refused_rather_than_quoted_as_unknown(
    client: httpx.AsyncClient, app: FastAPI, wire: Callable[..., None]
) -> None:
    """An SSRF hit must not degrade to "could not measure". Quoting a run against a
    host the guard refused would price work that can never legitimately run, and
    the operator would see an ordinary-looking estimate for it."""
    wire("manager")

    def _blocked(url: str) -> SiteSize:
        raise PrivateAddressError("private/local address not allowed")

    app.dependency_overrides[get_site_size_probe] = lambda: _blocked
    resp = await client.post(
        "/api/v1/audits/estimate",
        json={"tier": "Paid", "depth": "deep", "url": "http://127.0.0.1/admin"},
    )
    assert resp.status_code == 400
    assert "public address" in resp.json()["error"]["message"]


# --------------------------------------------------------------------------- #
# Estimate vs actual, at the place audits are reviewed
# --------------------------------------------------------------------------- #
def test_a_queued_run_reports_no_cost_rather_than_zero() -> None:
    """`audits.cost` is `not null default 0`, so a queued row reads $0.00 - true and
    misleading: nothing has been spent YET, and a reviewer scanning the table would
    read it as "this audit was free". It is surfaced only once the engine actually
    started, which is precisely the condition the worker commits a cost under."""
    from app.schemas.audits import AuditResponse

    queued = AuditResponse.from_row(
        {"id": "a1", "url": "x.test", "tier": "paid", "status": "queued", "cost": 0}
    )
    assert queued.cost is None

    ran = AuditResponse.from_row(
        {"id": "a2", "url": "x.test", "tier": "paid", "status": "done",
         "run_uuid": "u-1", "cost": 1.09}
    )
    assert ran.cost == pytest.approx(1.09)


def test_the_estimate_and_the_bill_are_carried_on_the_same_row() -> None:
    """The comparison the platform could not make.

    The pre-flight figure was a flat constant that left no trace, so nothing
    recorded what a run had been QUOTED next to what it SPENT. Both now sit on the
    row and on the wire, which is what makes "is our cost model any good" an
    answerable question rather than a rhetorical one.
    """
    from app.schemas.audits import AuditResponse

    body = AuditResponse.from_row(
        {"id": "a3", "url": "x.test", "tier": "paid", "status": "done",
         "run_uuid": "u-1", "estimated_cost": 1.152, "cost": 1.09}
    ).model_dump(by_alias=True)
    assert body["estimatedCost"] == pytest.approx(1.152)
    assert body["cost"] == pytest.approx(1.09)


async def test_the_portal_still_never_sees_a_cost(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    """Staff gained the figure; the client-facing model must not have.

    `PortalAuditResponse` deliberately omits cost/error/run_uuid/artifact_dir/paths.
    Widening the staff row is not a reason to widen that one, and this pins the two
    apart so a future edit to the shared module cannot quietly join them.
    """
    from app.schemas.audits import PortalAuditResponse

    assert "cost" not in PortalAuditResponse.model_fields
    assert "estimated_cost" not in PortalAuditResponse.model_fields
