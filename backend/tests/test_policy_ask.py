"""Unit gate for the on-demand Policy-Radar lookup (``POST /policy/ask``).

The lookup now runs entirely on the Cloud API with PURE Claude generation (the Anthropic
Messages API, NO web search) - Claude answers from its OWN current expert knowledge.
Proven with the summarizer + gate ALL faked - NO network, NO DB, NO real provider:

* the pure core (:func:`run_policy_ask`):
  - happy path -> a structured answer (answer / urgency / rules / sources); the SINGLE paid
    call is metered under the ``policy`` dial and committed as the ACTUAL TOKEN cost ONLY
    (no web-search term), and the ask system prompt is passed through;
  - the JSON-declared sources flow through (there is no web retrieval);
  - a non-JSON reply still yields a structured answer (cleaned text + heuristic urgency);
  - a cost-gate block (dial off / by-hand / spend-stop) DEGRADES and NO provider call
    happens (no bypass, no spend);
  - keyless (no summarizer) DEGRADES without touching the gate;
  - a generation failure DEGRADES cleanly with no spend committed.
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
from app.routers.policy import get_ask_gate, get_ask_summarizer
from app.services import pricing
from app.services.cost_gate import CostGate, DialMode, GateContext
from app.services.policy_ask import (
    _ASK_SYSTEM_PROMPT,
    DEGRADE_NO_ANTHROPIC,
    DEGRADE_RESEARCH_FAILED,
    build_ask_user_prompt,
    parse_research,
    run_policy_ask,
)
from integrations.llm import FakeSummarizer, LLMResult

pytestmark = pytest.mark.unit

_GOOGLE_URL = "https://developers.google.com/search/docs/essentials/spam-policies"
_STATUS_URL = "https://status.search.google.com/incidents"


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class SpySummarizer:
    """A ``SystemSummarizer`` returning fixed JSON text; records prompt + system + tokens."""

    def __init__(self, *, text: str, input_tokens: int = 120, output_tokens: int = 60) -> None:
        self._text = text
        self._in = input_tokens
        self._out = output_tokens
        self.calls: list[str] = []
        self.systems: list[str | None] = []

    def summarize(
        self, prompt: str, *, model: str, max_tokens: int, system: str | None = None
    ) -> LLMResult:
        self.calls.append(prompt)
        self.systems.append(system)
        return LLMResult(text=self._text, input_tokens=self._in, output_tokens=self._out)


class RaisingSummarizer:
    """A ``SystemSummarizer`` that raises (transport / SDK failure)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def summarize(
        self, prompt: str, *, model: str, max_tokens: int, system: str | None = None
    ) -> LLMResult:
        self.calls.append(prompt)
        raise RuntimeError("generation unavailable")


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


def _expected_cost(settings: Settings, *, input_tokens: int, output_tokens: int) -> float:
    return pricing.anthropic_cost(
        settings,
        model=settings.policy_research_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


# --------------------------------------------------------------------------- #
# build_ask_user_prompt: carries the normalized topic (no "search the web")
# --------------------------------------------------------------------------- #
def test_prompt_carries_topic() -> None:
    prompt = build_ask_user_prompt("  site reputation   abuse ")
    assert "site reputation abuse" in prompt  # whitespace normalized
    assert "search the web" not in prompt.lower()


# --------------------------------------------------------------------------- #
# Happy path: structured answer + a single metered spend (TOKEN cost only)
# --------------------------------------------------------------------------- #
def test_happy_path_returns_structured_answer_and_meters_token_only() -> None:
    summarizer = SpySummarizer(
        text=(
            '{"answer": "Site reputation abuse now covers first-party subfolders.", '
            '"urgency": "urgent", "key_rules": ["No parasite hosting", "Gate third-party content"], '
            '"sources": ["https://developers.google.com/search/docs/essentials/spam-policies"]}'
        ),
        input_tokens=200,
        output_tokens=90,
    )
    gate, store = _gate("api")
    settings = _settings()

    result = run_policy_ask("site reputation abuse", summarizer=summarizer, gate=gate, settings=settings)

    assert result.status == "ok"
    assert result.urgency == "urgent"
    assert "first-party subfolders" in result.answer
    assert result.rules == ["No parasite hosting", "Gate third-party content"]
    assert _GOOGLE_URL in result.sources and result.sources.count(_GOOGLE_URL) == 1
    assert len(summarizer.calls) == 1  # exactly one paid generation call
    # the ask system prompt is passed through verbatim
    assert summarizer.systems == [_ASK_SYSTEM_PROMPT]
    # ONE committed cost row under the policy dial for Anthropic = TOKEN cost only.
    assert len(store.commits) == 1
    feature, provider, cost, cached = store.commits[0]
    assert (feature, provider, cached) == ("policy", "Anthropic", False)
    assert cost == _expected_cost(settings, input_tokens=200, output_tokens=90)
    assert cost > 0


def test_json_sources_flow_through_deduped() -> None:
    # There is no web retrieval any more; the JSON-declared sources flow through, deduped.
    summarizer = SpySummarizer(
        text=(
            '{"answer": "x", "urgency": "informational", "sources": ["'
            + _GOOGLE_URL + '", "' + _GOOGLE_URL + '", "' + _STATUS_URL + '"]}'
        ),
    )
    gate, _ = _gate("api")
    result = run_policy_ask("indexing incident", summarizer=summarizer, gate=gate, settings=_settings())
    assert result.sources == [_GOOGLE_URL, _STATUS_URL]  # deduped, JSON order


def test_non_json_reply_still_yields_a_structured_answer() -> None:
    # A non-JSON reply is not lost: the cleaned prose becomes the answer, urgency is heuristic.
    summarizer = SpySummarizer(
        text="A core update is actively rolling out and may require content changes.",
    )
    gate, store = _gate("api")
    result = run_policy_ask("core update", summarizer=summarizer, gate=gate, settings=_settings())
    assert result.status == "ok"
    assert result.urgency == "urgent"  # "rolling out" is an urgency hint
    assert "core update" in result.answer.lower()
    assert result.sources == []  # no JSON sources, no web
    assert len(store.commits) == 1


# --------------------------------------------------------------------------- #
# parse_research is defensive
# --------------------------------------------------------------------------- #
def test_parse_research_is_defensive() -> None:
    empty = parse_research("", web_sources=[], topic="t")
    assert empty.answer and empty.urgency == "informational"  # no-answer fallback message
    prose = parse_research("Just some prose about a manual action risk.", web_sources=[], topic="t")
    assert prose.urgency == "urgent"  # "manual action" hint
    assert "manual action" in prose.answer


# --------------------------------------------------------------------------- #
# Cost-gate enforcement: a block degrades, never bypasses
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("mode", "halted", "expected"),
    [("off", False, "skip"), ("byhand", False, "manual"), ("api", True, "blocked_halt")],
)
def test_gate_block_degrades_without_calling_the_summarizer(
    mode: str, halted: bool, expected: str
) -> None:
    summarizer = SpySummarizer(text="{}")
    gate, store = _gate(mode, halted=halted)  # type: ignore[arg-type]

    result = run_policy_ask("spam policy", summarizer=summarizer, gate=gate, settings=_settings())

    assert result.status == "degraded"
    assert result.reason == f"cost_gate:{expected}"
    # THE INVARIANT: no bypass - no generation call, no spend committed.
    assert summarizer.calls == [] and store.commits == []


# --------------------------------------------------------------------------- #
# Keyless + failure degrades
# --------------------------------------------------------------------------- #
def test_no_summarizer_degrades_without_touching_the_gate() -> None:
    gate, store = _gate("api")
    result = run_policy_ask("core update", summarizer=None, gate=gate, settings=_settings())
    assert result.status == "degraded"
    assert result.reason == DEGRADE_NO_ANTHROPIC
    assert store.commits == []  # short-circuits before the gate


def test_generation_failure_degrades_with_no_spend() -> None:
    summarizer = RaisingSummarizer()
    gate, store = _gate("api")
    result = run_policy_ask("core update", summarizer=summarizer, gate=gate, settings=_settings())
    assert result.status == "degraded"
    assert result.reason == DEGRADE_RESEARCH_FAILED
    assert summarizer.calls  # the gate allowed the attempt (the estimate is pre-committed)
    assert store.commits == []  # but nothing is billed - usage is unknown


def test_fake_summarizer_yields_a_structured_answer() -> None:
    # The shared FakeSummarizer (used for degraded golden runs) yields a structured answer.
    gate, _ = _gate("api")
    result = run_policy_ask("topic", summarizer=FakeSummarizer(), gate=gate, settings=_settings())
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
    """Wire the route: role + a faked summarizer / gate."""

    def _as(role: str = "manager", *, keyless: bool = False, mode: DialMode = "api") -> SpyCostStore:
        store = SpyCostStore(mode=mode)
        summarizer = None if keyless else SpySummarizer(
            text=(
                '{"answer": "A concise answer.", "urgency": "informational", '
                '"key_rules": [], "sources": ["' + _GOOGLE_URL + '"]}'
            ),
        )
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        app.dependency_overrides[get_ask_summarizer] = lambda: summarizer
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
    assert body["sources"][0] == _GOOGLE_URL  # the JSON-declared citation leads
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
