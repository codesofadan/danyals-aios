"""Unit gate for the on-demand Policy-Radar lookup (``POST /policy/ask``).

Proves the contract with the searcher + summarizer + gate ALL faked - NO network, NO
DB, NO real provider:

* the pure core (:func:`run_policy_ask`):
  - happy path -> a live search, an SSRF-guarded fetch, a Haiku distillation, and a
    STRUCTURED answer (answer / urgency / rules / sources); the source is always cited;
  - both paid calls (Serper + Haiku) are metered under the ``policy`` dial and committed;
  - an authoritative Google host is preferred over a non-official result;
  - a cost-gate block (dial off) DEGRADES and NO provider call happens (no bypass);
  - keyless (no Serper / no Anthropic) DEGRADES without touching the gate;
  - no source found / source unreachable DEGRADE cleanly (the Serper query still bills).
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
from app.routers.policy import (
    get_ask_fetcher,
    get_ask_gate,
    get_ask_searcher,
    get_ask_summarizer,
)
from app.services.cost_gate import CostGate, DialMode, GateContext
from app.services.policy_ask import (
    DEGRADE_NO_ANTHROPIC,
    build_query,
    run_policy_ask,
)
from integrations.content_research import KeywordMetrics, OrganicResult, SerpResult
from integrations.llm import FakeSummarizer, LLMResult

pytestmark = pytest.mark.unit

_AUTH_URL = "https://developers.google.com/search/docs/essentials/spam-policies"
_OTHER_URL = "https://seoblog.example.com/opinion"


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class SpySearcher:
    """A ``SerpResearcher`` returning a fixed organic list, recording every query."""

    def __init__(self, organic: list[OrganicResult]) -> None:
        self._organic = organic
        self.queries: list[str] = []

    def serp(self, keyword: str, geo: str | None = None) -> SerpResult:
        self.queries.append(keyword)
        return SerpResult(keyword=keyword, geo=geo, organic=list(self._organic))

    def keyword_metrics(self, keyword: str) -> KeywordMetrics:  # pragma: no cover - unused here
        return KeywordMetrics(keyword=keyword, volume=0, difficulty=0.0)


class FakeFetcher:
    """A ``PolicyFetcher`` backed by a url -> text mapping; records requested urls."""

    def __init__(self, mapping: dict[str, str | None]) -> None:
        self._mapping = mapping
        self.fetched: list[str] = []

    def fetch(self, url: str) -> str | None:
        self.fetched.append(url)
        return self._mapping.get(url)


class JsonSummarizer:
    """A ``Summarizer`` that returns a fixed STRICT-JSON reply, recording every call."""

    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.calls: list[str] = []

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
        self.calls.append(prompt)
        return LLMResult(text=self._payload, input_tokens=120, output_tokens=60)


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


def _organic(url: str, position: int = 1) -> OrganicResult:
    return OrganicResult(position=position, title=f"Result {position}", link=url, snippet="A snippet.")


# --------------------------------------------------------------------------- #
# build_query: scoped to Google's official surfaces
# --------------------------------------------------------------------------- #
def test_query_is_scoped_to_official_google_sources() -> None:
    q = build_query("  site reputation   abuse ")
    assert "site reputation abuse" in q  # whitespace normalized
    assert "site:developers.google.com" in q
    assert "site:blog.google" in q


# --------------------------------------------------------------------------- #
# Happy path: structured answer + metered spend
# --------------------------------------------------------------------------- #
def test_happy_path_returns_structured_answer_and_meters_both_spends() -> None:
    searcher = SpySearcher([_organic(_AUTH_URL)])
    fetcher = FakeFetcher({_AUTH_URL: "<html>Spam policy body about scaled content abuse.</html>"})
    summarizer = JsonSummarizer(
        '{"answer": "Site reputation abuse now covers first-party subfolders.", '
        '"urgency": "urgent", "rules": ["No parasite hosting", "Gate third-party content"], '
        '"sources": ["https://developers.google.com/search/docs/essentials/spam-policies"]}'
    )
    gate, store = _gate("api")

    result = run_policy_ask(
        "site reputation abuse",
        searcher=searcher,
        fetcher=fetcher,
        summarizer=summarizer,
        gate=gate,
        settings=_settings(),
    )

    assert result.status == "ok"
    assert result.urgency == "urgent"
    assert "first-party subfolders" in result.answer
    assert result.rules == ["No parasite hosting", "Gate third-party content"]
    assert _AUTH_URL in result.sources  # the cited source is present (not duplicated)
    assert result.sources.count(_AUTH_URL) == 1
    # One live search + one fetch of the authoritative result + one Haiku call.
    assert searcher.queries and fetcher.fetched == [_AUTH_URL] and len(summarizer.calls) == 1
    # Two committed cost rows under the SAME policy dial: Serper + Anthropic, both > 0.
    assert [c[0] for c in store.commits] == ["policy", "policy"]
    providers = {c[1] for c in store.commits}
    assert providers == {"Serper", "Anthropic"}
    assert all(cost > 0 and cached is False for _, _, cost, cached in store.commits)


def test_unparseable_reply_degrades_to_a_snippet_answer_but_still_structured() -> None:
    # The real FakeSummarizer echoes a (non-JSON) prompt digest; parse_ask must still
    # yield a structured answer from the source snippet rather than dropping the finding.
    searcher = SpySearcher([_organic(_AUTH_URL)])
    fetcher = FakeFetcher({_AUTH_URL: "policy text"})
    gate, store = _gate("api")

    result = run_policy_ask(
        "core update",
        searcher=searcher,
        fetcher=fetcher,
        summarizer=FakeSummarizer(),
        gate=gate,
        settings=_settings(),
    )

    assert result.status == "ok"
    assert result.urgency == "informational"  # neutral default on a parse miss
    assert result.answer  # a non-empty answer (the source snippet)
    assert result.sources == [_AUTH_URL]  # the source is always cited
    assert len(store.commits) == 2  # still a real, metered pair of calls


def test_authoritative_google_host_is_preferred_over_a_non_official_result() -> None:
    # Top organic is a non-official blog; the official Google result is lower - it wins.
    searcher = SpySearcher([_organic(_OTHER_URL, 1), _organic(_AUTH_URL, 2)])
    fetcher = FakeFetcher({_AUTH_URL: "official body", _OTHER_URL: "blog body"})
    gate, _ = _gate("api")

    result = run_policy_ask(
        "helpful content",
        searcher=searcher,
        fetcher=fetcher,
        summarizer=FakeSummarizer(),
        gate=gate,
        settings=_settings(),
    )

    assert result.status == "ok"
    assert fetcher.fetched == [_AUTH_URL]  # the official source, not the top blog


# --------------------------------------------------------------------------- #
# Cost-gate enforcement: a block degrades, never bypasses
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("mode", "halted", "expected"),
    [("off", False, "skip"), ("byhand", False, "manual"), ("api", True, "blocked_daily")],
)
def test_gate_block_degrades_without_calling_a_provider(
    mode: str, halted: bool, expected: str
) -> None:
    searcher = SpySearcher([_organic(_AUTH_URL)])
    fetcher = FakeFetcher({_AUTH_URL: "policy text"})
    summarizer = JsonSummarizer("{}")
    gate, store = _gate(mode, halted=halted)  # type: ignore[arg-type]

    result = run_policy_ask(
        "spam policy",
        searcher=searcher,
        fetcher=fetcher,
        summarizer=summarizer,
        gate=gate,
        settings=_settings(),
    )

    assert result.status == "degraded"
    assert result.reason == f"cost_gate:{expected}"
    # THE INVARIANT: no bypass - no search, no fetch, no summarize, no spend committed.
    assert searcher.queries == [] and fetcher.fetched == [] and summarizer.calls == []
    assert store.commits == []


# --------------------------------------------------------------------------- #
# Keyless degrade (gate never consulted)
# --------------------------------------------------------------------------- #
def test_no_serper_answers_ungrounded_via_anthropic() -> None:
    # No Serper key: grounding is skipped, but Claude STILL answers from its own
    # Google-policy knowledge (a real answer, not a "can't find" dead end).
    gate, store = _gate("api")
    result = run_policy_ask(
        "core update",
        searcher=None,
        fetcher=FakeFetcher({}),
        summarizer=FakeSummarizer(),
        gate=gate,
        settings=_settings(),
    )
    assert result.status == "ok"
    assert result.answer  # a real answer from the model
    assert result.sources == []  # ungrounded: no external source cited
    # Only the Anthropic call is billed (no Serper query ran).
    assert [c[1] for c in store.commits] == ["Anthropic"]


def test_no_anthropic_key_degrades_without_search_or_gate() -> None:
    searcher = SpySearcher([_organic(_AUTH_URL)])
    gate, store = _gate("api")
    result = run_policy_ask(
        "core update",
        searcher=searcher,
        fetcher=FakeFetcher({_AUTH_URL: "policy text"}),
        summarizer=None,
        gate=gate,
        settings=_settings(),
    )
    assert result.status == "degraded"
    assert result.reason == DEGRADE_NO_ANTHROPIC
    assert searcher.queries == [] and store.commits == []  # short-circuits before any spend


# --------------------------------------------------------------------------- #
# No source / unreachable: the Serper query still bills, then Claude answers ungrounded
# --------------------------------------------------------------------------- #
def test_no_source_found_falls_back_to_ungrounded_anthropic() -> None:
    searcher = SpySearcher([])  # the search returned nothing to fetch
    summarizer = JsonSummarizer("A plain-language answer about the topic.")
    gate, store = _gate("api")

    result = run_policy_ask(
        "obscure topic",
        searcher=searcher,
        fetcher=FakeFetcher({}),
        summarizer=summarizer,
        gate=gate,
        settings=_settings(),
    )

    assert result.status == "ok"
    assert result.answer  # Claude answered from its own knowledge
    assert result.sources == []  # nothing authoritative found to cite
    assert len(summarizer.calls) == 1
    # Both paid calls are billed: the Serper query (it ran) AND the Anthropic answer.
    assert {c[1] for c in store.commits} == {"Serper", "Anthropic"}


def test_unreachable_source_falls_back_to_ungrounded_anthropic() -> None:
    searcher = SpySearcher([_organic(_AUTH_URL)])
    fetcher = FakeFetcher({_AUTH_URL: None})  # found but unreachable this tick
    summarizer = JsonSummarizer("A plain-language answer about the topic.")
    gate, store = _gate("api")

    result = run_policy_ask(
        "spam policy",
        searcher=searcher,
        fetcher=fetcher,
        summarizer=summarizer,
        gate=gate,
        settings=_settings(),
    )

    assert result.status == "ok"
    assert result.answer
    assert result.sources == []
    assert len(summarizer.calls) == 1
    assert {c[1] for c in store.commits} == {"Serper", "Anthropic"}


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
    """Wire the route: role + faked searcher / summarizer / fetcher / gate."""

    def _as(role: str = "manager", *, keyless: bool = False, mode: DialMode = "api") -> SpyCostStore:
        store = SpyCostStore(mode=mode)
        searcher = None if keyless else SpySearcher([_organic(_AUTH_URL)])
        summarizer = None if keyless else FakeSummarizer()
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        app.dependency_overrides[get_ask_searcher] = lambda: searcher
        app.dependency_overrides[get_ask_summarizer] = lambda: summarizer
        app.dependency_overrides[get_ask_fetcher] = lambda: FakeFetcher({_AUTH_URL: "policy text"})
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
    assert body["sources"] == [_AUTH_URL]
    assert body["topic"] == "site reputation abuse"


async def test_route_keyless_degrades_200(
    client: httpx.AsyncClient, wire: Callable[..., SpyCostStore]
) -> None:
    store = wire("manager", keyless=True)
    resp = await client.post("/api/v1/policy/ask", json={"topic": "core update"})
    assert resp.status_code == 200  # degrade, never crash
    assert resp.json()["status"] == "degraded"
    # Both keys absent -> Anthropic (the answer engine) is the hard degrade.
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
