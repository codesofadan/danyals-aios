"""P9-5 unit gate: the web ``POST /ai/assist`` in-product AI surface.

Proves the four properties the plan requires, with the summarizer + cost gate
faked (no Anthropic key, no Postgres, no broker):

* surface routing - each surface reaches the right engine + endpoint, and the
  operator's prompt is FRAMED for that surface before the summarizer sees it;
* the cost gate is ENFORCED - a dial-off / by-hand / spend-stop block DEGRADES
  (200) and NO provider call happens (the gate is never bypassed);
* keyless DEGRADE - no summarizer => a degraded stub, gate never consulted;
* RBAC - a portal client is 403'd off the whole surface.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.routers.ai_assist import get_assist_gate, get_assist_summarizer
from app.services.ai_assist import SURFACES
from app.services.cost_gate import CostGate, DialMode, GateContext
from integrations.llm import LLMResult

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class SpySummarizer:
    """A ``Summarizer`` that records every call and echoes the framed prompt back,
    so a test can assert BOTH that a provider call happened and how it was framed."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
        self.calls.append((prompt, model, max_tokens))
        return LLMResult(text=f"[reply] {prompt}", input_tokens=1, output_tokens=1)


class FakeStore:
    """A minimal ``CostStore``: one dial mode + optional cap/halt, capturing writes."""

    def __init__(
        self,
        *,
        mode: DialMode = "api",
        budget: tuple[float, float] | None = None,
        daily_spent: float = 0.0,
        daily_stop: float = 75.0,
        halted: bool = False,
    ) -> None:
        self._mode = mode
        self._budget = budget
        self._daily_spent = daily_spent
        self._daily_stop = daily_stop
        self._halted = halted
        self.recorded: list[tuple[GateContext, float, bool]] = []

    def dial_mode(self, feature_key: str) -> DialMode:
        return self._mode

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return self._budget

    def daily_spent(self) -> float:
        return self._daily_spent

    def daily_stop(self) -> float:
        return self._daily_stop

    def is_halted(self) -> bool:
        return self._halted

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.recorded.append((ctx, cost, cached))


class FakeCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def summarizer() -> SpySummarizer:
    return SpySummarizer()


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def wire(app: FastAPI, summarizer: SpySummarizer, store: FakeStore) -> Callable[..., None]:
    """Wire the surface: role, summarizer (or None), and a gate over the fake store."""

    def _as(role: str = "manager", *, keyless: bool = False) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        app.dependency_overrides[get_assist_summarizer] = lambda: (None if keyless else summarizer)
        app.dependency_overrides[get_assist_gate] = lambda: CostGate(store, FakeCache())

    return _as


# --------------------------------------------------------------------------- #
# Surface routing (happy path)
# --------------------------------------------------------------------------- #
_EXPECTED_ENDPOINT = {
    "content": "/api/v1/content/jobs",
    "report": "/api/v1/reports/sync",
    "radar": "/api/v1/policy/changes",
    "general": "",
}


async def test_all_four_surfaces_route_and_summarize(
    client: httpx.AsyncClient, summarizer: SpySummarizer, wire: Callable[..., None]
) -> None:
    wire("manager")
    assert set(SURFACES) == {"content", "report", "radar", "general"}
    for surface in SURFACES:
        resp = await client.post(
            "/api/v1/ai/assist", json={"surface": surface, "prompt": "help me with this"}
        )
        assert resp.status_code == 200, surface
        body = resp.json()
        assert body["surface"] == surface
        assert body["status"] == "ok"
        assert body["endpoint"] == _EXPECTED_ENDPOINT[surface]
        assert body["routed_to"]  # a human engine label is always present
        # The summarizer saw the operator's prompt, wrapped in this surface's framing.
        assert "help me with this" in body["result"]
    # Exactly one provider call per surface (no double-spend, no skipped call).
    assert len(summarizer.calls) == len(SURFACES)


async def test_prompt_is_framed_per_surface_with_context_ref(
    client: httpx.AsyncClient, summarizer: SpySummarizer, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/ai/assist",
        json={"surface": "content", "prompt": "draft a page", "context_ref": "cl-42"},
    )
    assert resp.status_code == 200
    framed_prompt = summarizer.calls[0][0]
    assert "content pipeline" in framed_prompt.lower()  # the surface framing
    assert "Request: draft a page" in framed_prompt
    assert "Context ref: cl-42" in framed_prompt  # the optional handle is carried through


async def test_happy_path_commits_one_gated_spend(
    client: httpx.AsyncClient, store: FakeStore, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post("/api/v1/ai/assist", json={"surface": "general", "prompt": "hi"})
    assert resp.status_code == 200
    # One committed (non-cached) cost row against the ai_assist feature.
    assert len(store.recorded) == 1
    ctx, cost, cached = store.recorded[0]
    assert ctx.feature_key == "ai_assist" and ctx.provider == "Anthropic"
    assert cached is False and cost > 0


# --------------------------------------------------------------------------- #
# Cost-gate enforcement: a block degrades, never bypasses
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("mode", "halted", "expected_outcome"),
    [
        ("off", False, "skip"),
        ("byhand", False, "manual"),
        ("api", True, "blocked_daily"),
    ],
)
async def test_gate_block_degrades_without_calling_provider(
    client: httpx.AsyncClient,
    summarizer: SpySummarizer,
    app: FastAPI,
    mode: str,
    halted: bool,
    expected_outcome: str,
) -> None:
    blocked = FakeStore(mode=mode, halted=halted)  # type: ignore[arg-type]
    app.dependency_overrides[get_current_user] = lambda: _user("manager")
    app.dependency_overrides[get_assist_summarizer] = lambda: summarizer
    app.dependency_overrides[get_assist_gate] = lambda: CostGate(blocked, FakeCache())

    resp = await client.post("/api/v1/ai/assist", json={"surface": "content", "prompt": "x"})
    assert resp.status_code == 200  # degrade, never crash
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["reason"] == f"cost_gate:{expected_outcome}"
    # THE INVARIANT: a blocked call never reached the provider (no bypass) and the
    # operator is still pointed at the real workflow.
    assert summarizer.calls == []
    assert body["endpoint"] == "/api/v1/content/jobs"


async def test_daily_spend_stop_threshold_block_degrades(
    client: httpx.AsyncClient, summarizer: SpySummarizer, app: FastAPI
) -> None:
    # ai_assist is org-level (client_id=None), so the per-client cap does not apply and
    # the org daily spend-stop governs. Prove the threshold path (spend + estimate >
    # stop) blocks by SPEND, not just the halt flag exercised above.
    store = FakeStore(mode="api", daily_spent=75.0, daily_stop=75.0)
    app.dependency_overrides[get_current_user] = lambda: _user("owner")
    app.dependency_overrides[get_assist_summarizer] = lambda: summarizer
    app.dependency_overrides[get_assist_gate] = lambda: CostGate(store, FakeCache())

    resp = await client.post("/api/v1/ai/assist", json={"surface": "report", "prompt": "x"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"
    assert resp.json()["reason"] == "cost_gate:blocked_daily"
    assert summarizer.calls == []


# --------------------------------------------------------------------------- #
# Keyless degrade
# --------------------------------------------------------------------------- #
async def test_keyless_degrades_without_touching_the_gate(
    client: httpx.AsyncClient, store: FakeStore, wire: Callable[..., None]
) -> None:
    wire("manager", keyless=True)  # summarizer dependency resolves to None
    resp = await client.post("/api/v1/ai/assist", json={"surface": "radar", "prompt": "x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["reason"] == "anthropic_unconfigured"
    assert body["endpoint"] == "/api/v1/policy/changes"  # still routed to the real engine
    # Keyless short-circuits BEFORE the gate: no cost row is ever recorded.
    assert store.recorded == []


# --------------------------------------------------------------------------- #
# RBAC + validation
# --------------------------------------------------------------------------- #
async def test_portal_client_is_forbidden(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")  # a portal client holds no view_reports
    resp = await client.post("/api/v1/ai/assist", json={"surface": "general", "prompt": "x"})
    assert resp.status_code == 403


async def test_unknown_surface_is_422(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post("/api/v1/ai/assist", json={"surface": "billing", "prompt": "x"})
    assert resp.status_code == 422


async def test_empty_prompt_is_422(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post("/api/v1/ai/assist", json={"surface": "general", "prompt": ""})
    assert resp.status_code == 422
