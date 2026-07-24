"""Unit gate for the on-demand Policy-Radar lookup (``POST /policy/ask``).

The lookup now lets Claude do the WEB SEARCH ITSELF (Anthropic server-side ``web_search``
tool) and synthesize a cited answer - replacing the old Serper + SSRF-fetch + Haiku
pipeline. Proven with the researcher + gate ALL faked - NO network, NO DB, NO real
provider:

* the pure core (:func:`run_policy_ask`):
  - happy path -> a structured answer (answer / urgency / rules / sources) with the
    web_search citation URLs cited; the SINGLE paid call is metered under the ``policy``
    dial and committed as the ACTUAL token cost + web-search cost;
  - the search count is read from usage when present, else estimated at ``max_uses``;
  - a non-JSON reply still yields a structured answer (cleaned text + heuristic urgency);
  - a cost-gate block (dial off / by-hand / spend-stop) DEGRADES and NO provider call
    happens (no bypass, no spend);
  - keyless (no researcher) DEGRADES without touching the gate;
  - a research failure DEGRADES cleanly with no spend committed.
* the route: staff-only (a portal client is 403'd), an empty topic is 422, and a keyless
  deploy returns 200 ``status='degraded'`` (never a crash).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.core.auth import CurrentUser, get_current_user
from app.routers.policy import get_ask_gate, get_ask_researcher
from app.services import pricing
from app.services.cost_gate import CostGate, DialMode, GateContext
from app.services.policy_ask import (
    DEGRADE_NO_ANTHROPIC,
    DEGRADE_RESEARCH_FAILED,
    build_research_prompt,
    run_policy_ask,
)
from integrations.llm import FakeResearcher, ResearchResult

pytestmark = pytest.mark.unit

_GOOGLE_URL = "https://developers.google.com/search/docs/essentials/spam-policies"
_STATUS_URL = "https://status.search.google.com/incidents"


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class SpyResearcher:
    """A ``Researcher`` returning a fixed reply + sources + search count; records calls."""

    def __init__(
        self,
        *,
        text: str,
        sources: list[str] | None = None,
        searches: int | None = 1,
        input_tokens: int = 120,
        output_tokens: int = 60,
    ) -> None:
        self._text = text
        self._sources = sources or []
        self._searches = searches
        self._in = input_tokens
        self._out = output_tokens
        self.calls: list[str] = []

    def research(
        self, prompt: str, *, model: str, max_tokens: int, max_searches: int
    ) -> ResearchResult:
        self.calls.append(prompt)
        return ResearchResult(
            text=self._text,
            sources=list(self._sources),
            input_tokens=self._in,
            output_tokens=self._out,
            searches=self._searches,
        )


class RaisingResearcher:
    """A ``Researcher`` that raises (transport error / model can't web-search)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def research(
        self, prompt: str, *, model: str, max_tokens: int, max_searches: int
    ) -> ResearchResult:
        self.calls.append(prompt)
        raise RuntimeError("web search unavailable")


class SpyCostStore:
    """A ``CostStore`` with a fixed dial mode; records every ``record_cost`` (commit)."""

    def __init__(self, mode: DialMode = "api", *, halted: bool = False) -> None:
        self._mode = mode
        self._halted = halted
        self.commits: list[tuple[str, str, float, bool]] = []

    def dial_mode(self, feature_key: str) -> DialMode:
        return self._mode

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return None

    def daily_spent(self) -> float:
        return 0.0

    def daily_stop(self) -> float:
        return 75.0

    def is_halted(self) -> bool:
        return self._halted

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.commits.append((ctx.feature_key, ctx.provider, cost, cached))


class NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="dev", **over)


def _gate(mode: DialMode = "api", *, halted: bool = False) -> tuple[CostGate, SpyCostStore]:
    store = SpyCostStore(mode=mode, halted=halted)
    return CostGate(store, NullCache()), store


def _expected_cost(settings: Settings, *, input_tokens: int, output_tokens: int, searches: int) -> float:
    token = pricing.anthropic_cost(
        settings,
        model=settings.policy_research_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    return token + pricing.web_search_cost(settings, searches=searches)


# --------------------------------------------------------------------------- #
# build_research_prompt: carries the topic + asks for a live search
# --------------------------------------------------------------------------- #
def test_prompt_carries_topic_and_asks_to_search() -> None:
    prompt = build_research_prompt("  site reputation   abuse ")
    assert "site reputation abuse" in prompt  # whitespace normalized
    assert "search" in prompt.lower()


# --------------------------------------------------------------------------- #
# Happy path: structured answer + a single metered spend (token + web-search)
# --------------------------------------------------------------------------- #
def test_happy_path_returns_structured_answer_and_meters_token_plus_search() -> None:
    researcher = SpyResearcher(
        text=(
            '{"answer": "Site reputation abuse now covers first-party subfolders.", '
            '"urgency": "urgent", "key_rules": ["No parasite hosting", "Gate third-party content"], '
            '"sources": ["https://developers.google.com/search/docs/essentials/spam-policies"]}'
        ),
        sources=[_GOOGLE_URL],
        searches=2,
        input_tokens=200,
        output_tokens=90,
    )
    gate, store = _gate("api")
    settings = _settings()

    result = run_policy_ask("site reputation abuse", researcher=researcher, gate=gate, settings=settings)

    assert result.status == "ok"
    assert result.urgency == "urgent"
    assert "first-party subfolders" in result.answer
    assert result.rules == ["No parasite hosting", "Gate third-party content"]
    assert _GOOGLE_URL in result.sources and result.sources.count(_GOOGLE_URL) == 1
    assert len(researcher.calls) == 1  # exactly one paid research call
    # ONE committed cost row under the policy dial for Anthropic = token cost + search cost.
    assert len(store.commits) == 1
    feature, provider, cost, cached = store.commits[0]
    assert (feature, provider, cached) == ("policy", "Anthropic", False)
    assert cost == _expected_cost(settings, input_tokens=200, output_tokens=90, searches=2)
    assert cost > 0


def test_web_search_urls_lead_and_dedupe_against_json_sources() -> None:
    # The web_search citation URLs (what Claude actually retrieved) lead the source list;
    # a JSON-declared URL not already present is appended; duplicates collapse.
    researcher = SpyResearcher(
        text='{"answer": "x", "urgency": "informational", "sources": ["' + _GOOGLE_URL + '"]}',
        sources=[_STATUS_URL, _GOOGLE_URL],
        searches=1,
    )
    gate, _ = _gate("api")
    result = run_policy_ask("indexing incident", researcher=researcher, gate=gate, settings=_settings())
    assert result.sources == [_STATUS_URL, _GOOGLE_URL]  # web sources first, deduped


def test_non_json_reply_still_yields_a_structured_answer() -> None:
    # A non-JSON reply is not lost: the cleaned prose becomes the answer, urgency is
    # heuristic, and the web_search URLs are still cited.
    researcher = SpyResearcher(
        text="A core update is actively rolling out and may require content changes.",
        sources=[_GOOGLE_URL],
        searches=1,
    )
    gate, store = _gate("api")
    result = run_policy_ask("core update", researcher=researcher, gate=gate, settings=_settings())
    assert result.status == "ok"
    assert result.urgency == "urgent"  # "rolling out" is an urgency hint
    assert "core update" in result.answer.lower()
    assert result.sources == [_GOOGLE_URL]
    assert len(store.commits) == 1


def test_absent_usage_count_estimates_max_uses_for_the_search_cost() -> None:
    # When the SDK does not surface the server-tool usage (searches=None), the web-search
    # cost is estimated at the tool's max_uses (defensive high, never silently free).
    settings = _settings()
    researcher = SpyResearcher(
        text='{"answer": "x", "urgency": "informational"}', sources=[], searches=None,
        input_tokens=100, output_tokens=40,
    )
    gate, store = _gate("api")
    result = run_policy_ask("topic", researcher=researcher, gate=gate, settings=settings)
    assert result.status == "ok"
    _, _, cost, _ = store.commits[0]
    assert cost == _expected_cost(
        settings, input_tokens=100, output_tokens=40, searches=settings.policy_research_max_searches
    )


# --------------------------------------------------------------------------- #
# Cost-gate enforcement: a block degrades, never bypasses
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("mode", "halted", "expected"),
    [("off", False, "skip"), ("byhand", False, "manual"), ("api", True, "blocked_daily")],
)
def test_gate_block_degrades_without_calling_the_researcher(
    mode: str, halted: bool, expected: str
) -> None:
    researcher = SpyResearcher(text="{}")
    gate, store = _gate(mode, halted=halted)  # type: ignore[arg-type]

    result = run_policy_ask("spam policy", researcher=researcher, gate=gate, settings=_settings())

    assert result.status == "degraded"
    assert result.reason == f"cost_gate:{expected}"
    # THE INVARIANT: no bypass - no research call, no spend committed.
    assert researcher.calls == [] and store.commits == []


# --------------------------------------------------------------------------- #
# Keyless + failure degrades
# --------------------------------------------------------------------------- #
def test_no_researcher_degrades_without_touching_the_gate() -> None:
    gate, store = _gate("api")
    result = run_policy_ask("core update", researcher=None, gate=gate, settings=_settings())
    assert result.status == "degraded"
    assert result.reason == DEGRADE_NO_ANTHROPIC
    assert store.commits == []  # short-circuits before the gate


def test_research_failure_degrades_with_no_spend() -> None:
    researcher = RaisingResearcher()
    gate, store = _gate("api")
    result = run_policy_ask("core update", researcher=researcher, gate=gate, settings=_settings())
    assert result.status == "degraded"
    assert result.reason == DEGRADE_RESEARCH_FAILED
    assert researcher.calls  # the gate allowed the attempt (the estimate is pre-committed)
    assert store.commits == []  # but nothing is billed - usage is unknown


def test_fake_researcher_is_deterministic_and_structured() -> None:
    # The shared FakeResearcher (used for degraded golden runs) yields a structured answer.
    gate, _ = _gate("api")
    result = run_policy_ask("topic", researcher=FakeResearcher(), gate=gate, settings=_settings())
    assert result.status == "ok"
    assert result.answer and result.urgency in ("urgent", "informational")


# --------------------------------------------------------------------------- #
# Route: RBAC + validation + degrade wiring
# --------------------------------------------------------------------------- #
def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def wire(app: FastAPI) -> Callable[..., SpyCostStore]:
    """Wire the route: role + a faked researcher / gate."""

    def _as(role: str = "manager", *, keyless: bool = False, mode: DialMode = "api") -> SpyCostStore:
        store = SpyCostStore(mode=mode)
        researcher = None if keyless else FakeResearcher(sources=[_GOOGLE_URL])
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        app.dependency_overrides[get_ask_researcher] = lambda: researcher
        app.dependency_overrides[get_ask_gate] = lambda: CostGate(store, NullCache())
        return store

    return _as


async def test_route_answers_for_staff(
    client: httpx.AsyncClient, wire: Callable[..., SpyCostStore]
) -> None:
    wire("manager")
    resp = await client.post("/api/v1/policy/ask", json={"topic": "site reputation abuse"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["urgency"] in ("urgent", "informational")
    assert body["sources"][0] == _GOOGLE_URL  # the web_search citation URL leads
    assert body["topic"] == "site reputation abuse"


async def test_route_keyless_degrades_200(
    client: httpx.AsyncClient, wire: Callable[..., SpyCostStore]
) -> None:
    store = wire("manager", keyless=True)
    resp = await client.post("/api/v1/policy/ask", json={"topic": "core update"})
    assert resp.status_code == 200  # degrade, never crash
    assert resp.json()["status"] == "degraded"
    assert resp.json()["reason"] == DEGRADE_NO_ANTHROPIC
    assert store.commits == []


async def test_route_forbids_portal_client(
    client: httpx.AsyncClient, wire: Callable[..., SpyCostStore]
) -> None:
    wire("client")  # a portal client holds no view_reports
    resp = await client.post("/api/v1/policy/ask", json={"topic": "core update"})
    assert resp.status_code == 403


async def test_route_empty_topic_is_422(
    client: httpx.AsyncClient, wire: Callable[..., SpyCostStore]
) -> None:
    wire("manager")
    resp = await client.post("/api/v1/policy/ask", json={"topic": ""})
    assert resp.status_code == 422
