"""P7A-3 unit tests: the content keyword & intent RESEARCH service.

Fully deterministic on fakes (``FakeSerpResearcher`` + ``FakePageFetcher`` + an
in-memory cost gate) - NO network. Proves:

* intent classification off the SERP shape (all four intents);
* the pillar/cluster topical map is built + secondary terms are 3-8;
* the SERP-format gate decides a format + confidence;
* the AI-Overview fan-out questions are present + folded into the brief;
* winnability flags terms KD-vs-DA + the DA-missing => low_confidence fallback;
* the top-10 teardown returns a table-stakes vs differentiator entity split;
* a cache hit avoids a second provider call (~$0);
* a cost-gate block => a degraded brief (never a crash);
* the teardown routes through the SSRF guard (a private/loopback URL is refused).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.core.auth import CurrentUser, get_current_user
from app.db.clients_repo import get_clients_repo
from app.db.content_repo import get_content_repo
from app.routers.content import (
    get_content_enqueuer,
    get_research_gate,
    get_research_researcher,
)
from app.services import pricing
from app.services.content_research import (
    DEGRADE_NO_ANTHROPIC,
    DEGRADE_RESEARCH_FAILED,
    ContentResearchResult,
    ContentSpendBlocked,
    FakePageFetcher,
    GatedResearcher,
    ResearchBrief,
    TeardownFetch,
    analyze_teardown,
    assess_winnability,
    build_recommend_prompt,
    build_recommend_system,
    build_registry,
    build_research_brief,
    cannibalization_conflicts,
    classify_intent,
    decide_format,
    fanout_questions,
    parse_recommendations,
    parse_teardown_page,
    run_content_research,
)
from app.services.content_research import TeardownPage as _TeardownPage
from app.services.cost_gate import CostGate, DialMode, GateContext
from integrations.content_research import (
    FakeSerpResearcher,
    KeywordMetrics,
    OrganicResult,
    SerpResult,
)
from integrations.llm import FakeResearcher, ResearchResult

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# In-memory gate fakes (mirror tests/test_context_cost.py) + a research spy
# --------------------------------------------------------------------------- #
class FakeStore:
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
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self.data.get(key)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value


class SpySerpResearcher:
    """Wraps ``FakeSerpResearcher`` and counts calls, to prove the gate/cache
    front the provider."""

    def __init__(self) -> None:
        self._inner = FakeSerpResearcher()
        self.serp_calls = 0
        self.metric_calls = 0

    def serp(self, keyword: str, geo: str | None = None) -> SerpResult:
        self.serp_calls += 1
        return self._inner.serp(keyword, geo)

    def keyword_metrics(self, keyword: str) -> KeywordMetrics:
        self.metric_calls += 1
        return self._inner.keyword_metrics(keyword)


class StubResearchPort:
    """A minimal in-memory ``ResearchPort`` for the orchestrator tests: canned
    SERP + metrics + teardown, with an optional block trigger per method."""

    def __init__(
        self,
        serp_result: SerpResult,
        teardown_pages: list[_TeardownPage],
        *,
        block: str | None = None,
        metrics: dict[str, KeywordMetrics] | None = None,
    ) -> None:
        self._serp = serp_result
        self._teardown = teardown_pages
        self._block = block
        self._metrics = metrics or {}
        self.metric_calls: list[str] = []

    def serp(self, keyword: str, geo: str | None = None) -> SerpResult:
        if self._block == "serp":
            raise ContentSpendBlocked("blocked_cap")
        return self._serp

    def keyword_metrics(self, keyword: str) -> KeywordMetrics:
        if self._block == "metrics":
            raise ContentSpendBlocked("blocked_halt")
        self.metric_calls.append(keyword)
        return self._metrics.get(keyword, KeywordMetrics(keyword=keyword, volume=1000, difficulty=40.0))

    def teardown(self, urls: list[str], keyword: str, geo: str | None) -> TeardownFetch:
        if self._block == "teardown":
            raise ContentSpendBlocked("skip")
        return TeardownFetch(pages=list(self._teardown), refused=[])


def _settings() -> Settings:
    return Settings(content_research_cost_estimate=0.01, content_teardown_timeout_seconds=1.0)


def _gate(store: FakeStore, cache: FakeCache | None = None) -> CostGate:
    return CostGate(store, cache or FakeCache())


def _permissive(_url: str) -> bool:
    return True


def _serp_with(
    *,
    keyword: str = "topic",
    organic: list[OrganicResult] | None = None,
    paa: list[str] | None = None,
    related: list[str] | None = None,
) -> SerpResult:
    return SerpResult(
        keyword=keyword,
        geo=None,
        organic=organic or [OrganicResult(1, keyword.title(), "https://example.test/a")],
        people_also_ask=paa or [],
        related_searches=related or [],
    )


# --------------------------------------------------------------------------- #
# 1. Intent classification off the SERP shape
# --------------------------------------------------------------------------- #
def test_intent_transactional() -> None:
    serp = _serp_with(
        keyword="buy running shoes",
        organic=[
            OrganicResult(1, "Buy Running Shoes Online", "https://example.test/1"),
            OrganicResult(2, "Running Shoes for Sale - Best Price", "https://example.test/2"),
        ],
        related=["running shoes discount"],
    )
    intent, confidence = classify_intent(serp, "buy running shoes")
    assert intent == "transactional"
    assert 0.0 < confidence <= 1.0


def test_intent_commercial() -> None:
    serp = _serp_with(
        keyword="best crm software",
        organic=[
            OrganicResult(1, "Best CRM Software 2026 - Top Picks", "https://example.test/1"),
            OrganicResult(2, "CRM Software Review & Comparison", "https://example.test/2"),
        ],
        related=["crm vs erp"],
    )
    intent, _ = classify_intent(serp, "best crm software")
    assert intent == "commercial"


def test_intent_informational() -> None:
    serp = _serp_with(
        keyword="how photosynthesis works",
        organic=[OrganicResult(1, "How Photosynthesis Works - A Guide", "https://example.test/1")],
        paa=["What is photosynthesis?", "How does photosynthesis work?"],
        related=["photosynthesis explained"],
    )
    intent, _ = classify_intent(serp, "how photosynthesis works")
    assert intent == "informational"


def test_intent_navigational() -> None:
    serp = _serp_with(
        keyword="acme login",
        organic=[
            OrganicResult(1, "Acme Login - Official Site", "https://example.test/1"),
            OrganicResult(2, "Sign in to your Acme dashboard account", "https://example.test/2"),
        ],
    )
    intent, _ = classify_intent(serp, "acme login")
    assert intent == "navigational"


def test_intent_defaults_informational_when_no_signal() -> None:
    serp = _serp_with(keyword="zzz", organic=[OrganicResult(1, "Zzz", "https://example.test/1")])
    intent, confidence = classify_intent(serp, "zzz")
    assert intent == "informational"
    assert confidence == 0.3


# --------------------------------------------------------------------------- #
# 2. SERP-format gate
# --------------------------------------------------------------------------- #
def test_format_video_from_result_hosts() -> None:
    serp = _serp_with(
        keyword="guitar tutorial",
        organic=[
            OrganicResult(1, "Guitar Tutorial", "https://youtube.com/watch?v=1"),
            OrganicResult(2, "Learn Guitar", "https://youtu.be/2"),
        ],
    )
    decision = decide_format(serp, "informational", "guitar tutorial")
    assert decision.recommended == "video"
    assert decision.confidence > 0.4


def test_format_tool_and_local() -> None:
    tool_serp = _serp_with(
        keyword="mortgage calculator",
        organic=[OrganicResult(1, "Mortgage Calculator Tool", "https://example.test/1")],
    )
    assert decide_format(tool_serp, "informational", "mortgage calculator").recommended == "tool"

    local_serp = _serp_with(
        keyword="plumber near me",
        organic=[OrganicResult(1, "Plumber Near Me - Local Directory", "https://example.test/1")],
        related=["emergency plumber nearby"],
    )
    assert decide_format(local_serp, "commercial", "plumber near me").recommended == "local"


def test_format_blog_default_low_confidence() -> None:
    serp = _serp_with(keyword="history of tea", organic=[OrganicResult(1, "History of Tea", "https://example.test/1")])
    decision = decide_format(serp, "informational", "history of tea")
    assert decision.recommended == "blog"
    assert 0.0 < decision.confidence <= 1.0


# --------------------------------------------------------------------------- #
# 3. AI-Overview fan-out
# --------------------------------------------------------------------------- #
def test_fanout_includes_paa_and_templates() -> None:
    serp = _serp_with(keyword="solar panels", paa=["Are solar panels worth it?"])
    questions = fanout_questions("solar panels", "commercial", serp)
    assert "Are solar panels worth it?" in questions  # PAA preserved
    assert any("best solar panels" in q.lower() for q in questions)  # template added
    assert len(questions) <= 8


# --------------------------------------------------------------------------- #
# 4. Winnability filter + DA-missing fallback
# --------------------------------------------------------------------------- #
def test_winnability_flags_by_da() -> None:
    metrics = [
        KeywordMetrics("easy term", volume=500, difficulty=20.0),
        KeywordMetrics("hard term", volume=9000, difficulty=85.0),
    ]
    report = assess_winnability(metrics, client_da=40.0)
    assert report.neutral_da_assumed is False
    by_kw = {t.keyword: t for t in report.targets}
    assert by_kw["easy term"].winnable is True
    assert by_kw["hard term"].winnable is False


def test_winnability_missing_da_uses_neutral_and_flags() -> None:
    metrics = [KeywordMetrics("term", volume=100, difficulty=30.0)]
    report = assess_winnability(metrics, client_da=None, neutral_da=25.0)
    assert report.neutral_da_assumed is True
    assert report.client_da == 25.0


# --------------------------------------------------------------------------- #
# 5. Top-10 teardown: table-stakes vs differentiator split
# --------------------------------------------------------------------------- #
def _page_html(headings: list[str], entities: list[str], *, words: int, year: bool = True) -> str:
    # Each capitalised token (entity or heading) is wrapped in lowercase context
    # so the multi-word proper-noun regex keeps them SEPARATE (adjacent caps would
    # merge into one entity). Entities are clean single-cap words (the regex
    # splits camelCase + drops ALL-CAPS). The freshness marker is lowercase +
    # placed FIRST so it lands in the leading window the parser scans.
    schema = '<script type="application/ld+json">{"@type": "Article"}</script>'
    parts: list[str] = []
    if year:
        parts.append("last updated 2026 for accuracy.")
    for entity in entities:
        parts.append(f"we recommend {entity} in this section.")
    for heading in headings:
        parts.append(f"<h2>{heading}</h2>")
        parts.append("body copy follows here.")
    parts.append("filler " * words)
    body = schema + " " + " ".join(parts) + "<img src='a.png'>"
    return f"<html><body>{body}</body></html>"


def test_teardown_table_stakes_vs_differentiators() -> None:
    # Three pages: "Google" appears on all (table-stakes); "Bing" on only two
    # (differentiator); "Yahoo" on one (noise, dropped).
    pages = [
        parse_teardown_page("https://a.test", 1, _page_html(["Overview", "Setup"], ["Google", "Bing"], words=300)),
        parse_teardown_page("https://b.test", 2, _page_html(["Overview", "Pricing"], ["Google", "Bing"], words=500)),
        parse_teardown_page("https://c.test", 3, _page_html(["Overview"], ["Google", "Yahoo"], words=400)),
    ]
    teardown = analyze_teardown(pages, refused=[])
    assert "Google" in teardown.table_stakes_entities
    assert "Bing" in teardown.differentiator_entities
    assert "Yahoo" not in teardown.table_stakes_entities
    assert "Yahoo" not in teardown.differentiator_entities
    # word-count target is the competitor median (the middle of the three).
    assert teardown.word_count_target == sorted(p.word_count for p in pages)[1]
    assert "Overview" in teardown.heading_blueprint  # most-shared section
    assert "Article" in teardown.schema_types
    assert teardown.freshness_expected is True
    assert teardown.fetched == 3


def test_teardown_empty_is_safe() -> None:
    teardown = analyze_teardown([], refused=["https://x.test"])
    assert teardown.fetched == 0
    assert teardown.table_stakes_entities == []
    assert teardown.refused == ["https://x.test"]


# --------------------------------------------------------------------------- #
# 6. GatedResearcher: cost-gate + N1 cache + SSRF guard
# --------------------------------------------------------------------------- #
def test_serp_cache_hit_avoids_second_provider_call() -> None:
    store = FakeStore(mode="api")
    cache = FakeCache()
    spy = SpySerpResearcher()
    researcher = GatedResearcher(
        spy, FakePageFetcher(), _gate(store, cache),
        settings=_settings(), client_id="cl-1", serp_date="2026-07-16",
    )
    first = researcher.serp("widgets", "us")
    assert spy.serp_calls == 1
    second = researcher.serp("widgets", "us")
    assert spy.serp_calls == 1  # N1 cache hit: provider NOT called again
    assert second == first
    # One committed (paid) row + one cached ($0) row.
    assert any(cost > 0 and not cached for _, cost, cached in store.recorded)
    assert any(cost == 0.0 and cached for _, cost, cached in store.recorded)


def test_serp_block_raises_content_spend_blocked() -> None:
    store = FakeStore(mode="off")
    spy = SpySerpResearcher()
    researcher = GatedResearcher(
        spy, FakePageFetcher(), _gate(store), settings=_settings(), client_id="cl-1",
    )
    with pytest.raises(ContentSpendBlocked) as excinfo:
        researcher.serp("widgets")
    assert excinfo.value.outcome == "skip"
    assert spy.serp_calls == 0  # no-bypass: provider never reached


def test_teardown_refuses_private_and_loopback_urls() -> None:
    """N2: the teardown fetch routes through the REAL SSRF guard - a loopback /
    private / metadata host is refused and never handed to the fetcher (no
    network: literal IPs + denylist names resolve without DNS)."""
    store = FakeStore(mode="api")
    fetcher = FakePageFetcher()  # returns None for any URL; records what it saw
    # Default url_gate = the REAL app.core.security.is_public_url SSRF guard.
    researcher = GatedResearcher(
        FakeSerpResearcher(), fetcher, _gate(store),
        settings=_settings(), client_id="cl-1", serp_date="2026-07-16",
    )
    urls = [
        "http://127.0.0.1/admin",
        "http://localhost/x",
        "http://169.254.169.254/latest/meta-data/",
    ]
    result = researcher.teardown(urls, "widgets", None)
    assert result.pages == []
    assert set(result.refused) == set(urls)  # all three refused by the guard
    assert fetcher.fetched == []  # the fetcher was never even asked


def test_teardown_fetches_allowed_urls_through_permissive_gate() -> None:
    store = FakeStore(mode="api")
    html = _page_html(["Intro"], ["Acme"], words=200)
    fetcher = FakePageFetcher({"https://example.test/a": html})
    researcher = GatedResearcher(
        FakeSerpResearcher(), fetcher, _gate(store),
        settings=_settings(), client_id="cl-1", serp_date="2026-07-16",
        url_gate=_permissive,
    )
    result = researcher.teardown(["https://example.test/a", "https://example.test/missing"], "widgets", None)
    assert fetcher.fetched == ["https://example.test/a", "https://example.test/missing"]
    assert len(result.pages) == 1  # the missing page (None) is dropped
    assert result.pages[0].url == "https://example.test/a"


# --------------------------------------------------------------------------- #
# 7. build_research_brief orchestration (end-to-end on fakes)
# --------------------------------------------------------------------------- #
def _rich_serp() -> SerpResult:
    return _serp_with(
        keyword="content marketing",
        organic=[
            OrganicResult(1, "Content Marketing Guide by HubSpot", "https://example.test/1", "Learn content marketing."),
            OrganicResult(2, "Content Marketing Strategy - HubSpot", "https://example.test/2", "A HubSpot strategy."),
        ],
        paa=["What is content marketing?", "How to start content marketing?"],
        related=["content marketing examples", "content marketing strategy", "content marketing tools"],
    )


def test_build_brief_full_shape() -> None:
    pages = [
        parse_teardown_page("https://a.test", 1, _page_html(["Intro", "Strategy"], ["Hubspot", "Semrush"], words=800)),
        parse_teardown_page("https://b.test", 2, _page_html(["Intro", "Tactics"], ["Hubspot", "Semrush"], words=1200)),
        parse_teardown_page("https://c.test", 3, _page_html(["Intro"], ["Hubspot", "Ahrefs"], words=1000)),
    ]
    port = StubResearchPort(_rich_serp(), pages)
    brief = build_research_brief("content marketing", researcher=port, client_da=50.0, serp_date="2026-07-16")

    assert isinstance(brief, ResearchBrief)
    assert brief.degraded is False
    assert brief.intent in ("informational", "commercial", "transactional", "navigational")
    # term set: 1 primary + 3-8 secondary
    assert brief.terms.primary == "content marketing"
    assert 3 <= len(brief.terms.secondary) <= 8
    # cluster/topical map built
    assert brief.cluster.pillar == "content marketing"
    assert brief.cluster.supporting
    # format decided
    assert brief.content_format.recommended in ("blog", "product", "tool", "video", "local", "comparison")
    # fan-out present + folded into the term questions
    assert brief.fanout
    assert brief.terms.questions
    # winnability assessed (DA present => not neutral)
    assert brief.winnability.neutral_da_assumed is False
    assert brief.winnability.targets
    # teardown split present
    assert "Hubspot" in brief.teardown.table_stakes_entities
    assert brief.teardown.fetched == 3
    # registry: one primary intent per URL (no cannibalization)
    assert cannibalization_conflicts(brief.registry) == []
    assert all(e.url_slug == "content-marketing" for e in brief.registry)


def test_build_brief_missing_da_is_low_confidence() -> None:
    port = StubResearchPort(_rich_serp(), [])
    brief = build_research_brief("content marketing", researcher=port, client_da=None)
    assert brief.winnability.neutral_da_assumed is True
    assert brief.low_confidence is True
    assert brief.degraded is False  # still a usable brief


def test_build_brief_serp_block_degrades_not_crashes() -> None:
    port = StubResearchPort(_rich_serp(), [], block="serp")
    brief = build_research_brief("content marketing", researcher=port, client_da=50.0)
    assert brief.degraded is True
    assert brief.low_confidence is True
    assert brief.terms.primary == "content marketing"
    assert brief.teardown.fetched == 0
    assert any("serp pull blocked" in note for note in brief.notes)


def test_build_brief_teardown_block_degrades_section_only() -> None:
    port = StubResearchPort(_rich_serp(), [], block="teardown")
    brief = build_research_brief("content marketing", researcher=port, client_da=50.0)
    assert brief.degraded is False  # the SERP still succeeded
    assert brief.teardown.fetched == 0
    assert brief.low_confidence is True
    assert any("teardown blocked" in note for note in brief.notes)


def test_build_brief_metrics_block_degrades_winnability() -> None:
    port = StubResearchPort(_rich_serp(), [], block="metrics")
    brief = build_research_brief("content marketing", researcher=port, client_da=50.0)
    assert brief.degraded is False
    assert brief.winnability.targets == []  # metrics never gathered
    assert any("keyword metrics blocked" in note for note in brief.notes)


def test_build_brief_end_to_end_on_all_fakes() -> None:
    """The whole pipeline on the real GatedResearcher wrapping only fakes: proves
    a zero-network, zero-key run produces a complete brief."""
    store = FakeStore(mode="api")
    fetcher = FakePageFetcher(
        {
            "https://example.test/1": _page_html(["Intro"], ["HubSpot"], words=600),
        }
    )
    researcher = GatedResearcher(
        FakeSerpResearcher(), fetcher, _gate(store, FakeCache()),
        settings=_settings(), client_id="cl-1", serp_date="2026-07-16", url_gate=_permissive,
    )
    brief = build_research_brief("email marketing", researcher=researcher, client_da=45.0, serp_date="2026-07-16")
    assert brief.degraded is False
    assert brief.terms.primary == "email marketing"
    assert brief.winnability.targets  # metrics gathered for primary + secondary
    assert brief.registry
    # some paid rows were logged for the SERP + metrics pulls
    assert any(cost > 0 for _, cost, _ in store.recorded)


# --------------------------------------------------------------------------- #
# 8. Registry / cannibalization guard
# --------------------------------------------------------------------------- #
def test_registry_consolidates_and_guard_detects_conflict() -> None:
    from app.services.content_research import TermSet

    terms = TermSet(primary="best crm", secondary=["crm tools", "crm software"], semantic_entities=[], questions=[])
    registry = build_registry(terms, "commercial")
    assert {e.url_slug for e in registry} == {"best-crm"}  # all consolidated onto the pillar
    assert cannibalization_conflicts(registry) == []

    # Two different intents claiming the SAME slug => a flagged conflict.
    from app.services.content_research import RegistryEntry

    clash = [
        RegistryEntry("best crm", "best-crm", "commercial"),
        RegistryEntry("buy crm", "best-crm", "transactional"),
    ]
    assert cannibalization_conflicts(clash) == ["best-crm"]


# =========================================================================== #
# Research-first bulk content: the page-set RECOMMENDER (run_content_research)
# + the two content-router endpoints. Modelled on tests/test_policy_ask.py: the
# researcher + the cost gate are ALL faked - NO network, NO DB, NO real provider.
# Proves: happy path -> N clamped items + ONE metered commit (token + search) under
# `content_research`; keyless degrades without touching the gate; a gate block
# degrades with no call; a research failure degrades with no spend; the defensive
# parse; and the /content/research/generate fan-out into N jobs.
# =========================================================================== #
def _items_payload(n: int, *, content_type: str = "service") -> str:
    """A strict-JSON ``{"items":[...]}`` reply with ``n`` well-formed recommendations."""
    return json.dumps(
        {
            "items": [
                {
                    "title": f"Recommended Page {i}",
                    "page_type": content_type,
                    "primary_keyword": f"keyword {i}",
                    "secondary_keywords": [f"secondary {i}a", f"secondary {i}b"],
                    "est_volume": 1000 + i,
                    "difficulty": "medium",
                    "rationale": "A competitor ranks for this and the site is missing it.",
                    "city": "Austin" if content_type == "service_location" else "",
                    "service": "Repair" if content_type == "service_location" else "",
                }
                for i in range(n)
            ]
        }
    )


class SpyRecommendResearcher:
    """A ``Researcher`` returning a fixed reply; records each call incl. the ``system=``
    override the recommender passes (the JSON contract)."""

    def __init__(
        self,
        *,
        text: str,
        sources: list[str] | None = None,
        searches: int | None = 1,
        input_tokens: int = 200,
        output_tokens: int = 90,
    ) -> None:
        self._text = text
        self._sources = sources or []
        self._searches = searches
        self._in = input_tokens
        self._out = output_tokens
        self.calls: list[dict[str, Any]] = []

    def research(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        max_searches: int,
        system: str | None = None,
    ) -> ResearchResult:
        self.calls.append({"prompt": prompt, "system": system, "model": model})
        return ResearchResult(
            text=self._text,
            sources=list(self._sources),
            input_tokens=self._in,
            output_tokens=self._out,
            searches=self._searches,
        )


class RaisingRecommendResearcher:
    """A ``Researcher`` that raises (transport error / model can't web-search)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def research(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        max_searches: int,
        system: str | None = None,
    ) -> ResearchResult:
        self.calls.append(prompt)
        raise RuntimeError("web search unavailable")


def _rec_settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="dev", **over)


def _rec_gate(mode: DialMode = "api", *, halted: bool = False) -> tuple[CostGate, FakeStore]:
    store = FakeStore(mode=mode, halted=halted)
    return CostGate(store, FakeCache()), store


def _expected_recommend_cost(
    settings: Settings, *, input_tokens: int, output_tokens: int, searches: int
) -> float:
    token = pricing.anthropic_cost(
        settings,
        model=settings.content_research_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    return token + pricing.web_search_cost(settings, searches=searches)


# --------------------------------------------------------------------------- #
# Prompt + system contract
# --------------------------------------------------------------------------- #
def test_recommend_prompt_and_system_carry_site_type_and_contract() -> None:
    prompt = build_recommend_prompt("  https://acme.test  ", "service", 8)
    assert "https://acme.test" in prompt  # whitespace normalized
    assert "service" in prompt
    assert "8" in prompt

    system = build_recommend_system("service")
    assert "STRICT JSON" in system
    assert '"items"' in system
    assert "difficulty" in system
    # A plain type does NOT get the city x service instruction...
    assert "city x service" not in system.lower()
    # ...but service_location DOES.
    sl_system = build_recommend_system("service_location")
    assert "city x service" in sl_system.lower()


# --------------------------------------------------------------------------- #
# Happy path: N clamped items + a single metered spend (token + web-search)
# --------------------------------------------------------------------------- #
def test_recommend_happy_path_clamps_items_and_meters_token_plus_search() -> None:
    researcher = SpyRecommendResearcher(text=_items_payload(5), searches=2, input_tokens=200, output_tokens=90)
    gate, store = _rec_gate("api")
    settings = _rec_settings()

    result = run_content_research(
        researcher=researcher, gate=gate, settings=settings,
        site="https://acme.test", content_type="service", count=3,
    )

    assert isinstance(result, ContentResearchResult)
    assert result.status == "ok"
    assert len(result.items) == 3  # 5 returned, clamped to count=3
    assert result.items[0].title == "Recommended Page 0"
    assert result.items[0].page_type == "service"
    assert result.items[0].secondary_keywords == ["secondary 0a", "secondary 0b"]
    # exactly one paid research call, carrying the JSON-contract system override.
    assert len(researcher.calls) == 1
    assert researcher.calls[0]["system"] and '"items"' in researcher.calls[0]["system"]
    # ONE committed cost row under the content_research dial for Anthropic = token + search.
    assert len(store.recorded) == 1
    ctx, cost, cached = store.recorded[0]
    assert (ctx.feature_key, ctx.provider, cached) == ("content_research", "Anthropic", False)
    assert cost == _expected_recommend_cost(settings, input_tokens=200, output_tokens=90, searches=2)
    assert cost > 0


def test_recommend_count_defaults_to_setting() -> None:
    researcher = SpyRecommendResearcher(text=_items_payload(10))
    gate, _ = _rec_gate("api")
    settings = _rec_settings(content_research_count=4)
    result = run_content_research(
        researcher=researcher, gate=gate, settings=settings,
        site="https://acme.test", content_type="service", count=None,
    )
    assert len(result.items) == 4  # capped at the content_research_count default


def test_recommend_absent_usage_estimates_max_searches_for_cost() -> None:
    settings = _rec_settings()
    researcher = SpyRecommendResearcher(text=_items_payload(1), searches=None, input_tokens=100, output_tokens=40)
    gate, store = _rec_gate("api")
    result = run_content_research(
        researcher=researcher, gate=gate, settings=settings,
        site="https://acme.test", content_type="blog",
    )
    assert result.status == "ok"
    _, cost, _ = store.recorded[0]
    assert cost == _expected_recommend_cost(
        settings, input_tokens=100, output_tokens=40, searches=settings.content_research_max_searches
    )


def test_recommend_service_location_keeps_city_and_service() -> None:
    researcher = SpyRecommendResearcher(text=_items_payload(2, content_type="service_location"))
    gate, _ = _rec_gate("api")
    result = run_content_research(
        researcher=researcher, gate=gate, settings=_rec_settings(),
        site="https://acme.test", content_type="service_location",
    )
    assert result.items[0].city == "Austin"
    assert result.items[0].service == "Repair"


# --------------------------------------------------------------------------- #
# Cost-gate enforcement: a block degrades, never bypasses
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("mode", "halted", "expected"),
    [("off", False, "skip"), ("byhand", False, "manual"), ("api", True, "blocked_halt")],
)
def test_recommend_gate_block_degrades_without_calling_researcher(
    mode: str, halted: bool, expected: str
) -> None:
    researcher = SpyRecommendResearcher(text=_items_payload(2))
    gate, store = _rec_gate(mode, halted=halted)  # type: ignore[arg-type]

    result = run_content_research(
        researcher=researcher, gate=gate, settings=_rec_settings(),
        site="https://acme.test", content_type="service",
    )

    assert result.status == "degraded"
    assert result.reason == f"cost_gate:{expected}"
    assert result.items == []
    # THE INVARIANT: no bypass - no research call, no spend committed.
    assert researcher.calls == [] and store.recorded == []


# --------------------------------------------------------------------------- #
# Keyless + failure degrades
# --------------------------------------------------------------------------- #
def test_recommend_no_researcher_degrades_without_touching_gate() -> None:
    gate, store = _rec_gate("api")
    result = run_content_research(
        researcher=None, gate=gate, settings=_rec_settings(),
        site="https://acme.test", content_type="service",
    )
    assert result.status == "degraded"
    assert result.reason == DEGRADE_NO_ANTHROPIC
    assert store.recorded == []  # short-circuits before the gate


def test_recommend_research_failure_degrades_with_no_spend() -> None:
    researcher = RaisingRecommendResearcher()
    gate, store = _rec_gate("api")
    result = run_content_research(
        researcher=researcher, gate=gate, settings=_rec_settings(),
        site="https://acme.test", content_type="service",
    )
    assert result.status == "degraded"
    assert result.reason == DEGRADE_RESEARCH_FAILED
    assert researcher.calls  # the gate allowed the attempt
    assert store.recorded == []  # but nothing is billed - usage is unknown


def test_recommend_fake_researcher_yields_no_items_but_stays_ok() -> None:
    # The shared FakeResearcher's default payload is policy-shaped (no "items"): the
    # parse degrades to an EMPTY set, but the run still succeeds + meters (status ok).
    gate, store = _rec_gate("api")
    result = run_content_research(
        researcher=FakeResearcher(), gate=gate, settings=_rec_settings(),
        site="https://acme.test", content_type="service",
    )
    assert result.status == "ok"
    assert result.items == []
    assert len(store.recorded) == 1  # still a real paid call


# --------------------------------------------------------------------------- #
# Defensive parse: non-JSON / missing items / bad item / clamps / caps
# --------------------------------------------------------------------------- #
def test_parse_non_json_and_missing_items_return_empty() -> None:
    assert parse_recommendations("not json at all", content_type="service", count=12) == []
    assert parse_recommendations('{"foo": 1}', content_type="service", count=12) == []
    assert parse_recommendations('{"items": "nope"}', content_type="service", count=12) == []


def test_parse_skips_bad_items_and_clamps_difficulty_and_volume() -> None:
    raw = json.dumps(
        {
            "items": [
                "not-a-dict",
                {"title": "", "primary_keyword": "empty title dropped"},
                {
                    "title": "Good Page",
                    "page_type": "weird-type",  # unknown -> falls back to content_type
                    "difficulty": "impossible",  # clamped -> medium
                    "est_volume": "12,400",  # coerced -> 12400
                    "secondary_keywords": ["a", "a", "b"],  # deduped
                },
            ]
        }
    )
    items = parse_recommendations(raw, content_type="location", count=12)
    assert len(items) == 1  # the string + empty-title items were skipped
    item = items[0]
    assert item.title == "Good Page"
    assert item.page_type == "location"  # unknown page_type fell back to content_type
    assert item.difficulty == "medium"  # clamped from an invalid value
    assert item.est_volume == 12400  # coerced from "12,400"
    assert item.secondary_keywords == ["a", "b"]  # deduped


def test_parse_tolerates_prose_wrapped_json_and_caps_at_count() -> None:
    raw = "Here you go:\n" + _items_payload(6) + "\nHope that helps!"
    items = parse_recommendations(raw, content_type="service", count=2)
    assert len(items) == 2  # capped at count even with surrounding prose


# --------------------------------------------------------------------------- #
# Route wiring: RBAC + SSRF + degrade + the fan-out
# --------------------------------------------------------------------------- #
def _staff_user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


_PUBLIC_SITE = "https://1.1.1.1"  # public IP literal: SSRF guard passes with no DNS


async def test_research_route_ok_for_publish_staff(client: httpx.AsyncClient, app: FastAPI) -> None:
    store = FakeStore(mode="api")
    app.dependency_overrides[get_current_user] = lambda: _staff_user("specialist")
    app.dependency_overrides[get_research_researcher] = lambda: FakeResearcher(payload=_items_payload(3))
    app.dependency_overrides[get_research_gate] = lambda: CostGate(store, FakeCache())

    resp = await client.post(
        "/api/v1/content/research", json={"site": _PUBLIC_SITE, "contentType": "service"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert len(body["items"]) == 3
    assert body["items"][0]["pageType"] == "service"  # camelCase on the wire
    assert body["items"][0]["primaryKeyword"] == "keyword 0"
    assert len(store.recorded) == 1  # one metered call


async def test_research_route_requires_publish_content(client: httpx.AsyncClient, app: FastAPI) -> None:
    app.dependency_overrides[get_current_user] = lambda: _staff_user("analyst")  # no publish_content
    app.dependency_overrides[get_research_researcher] = lambda: FakeResearcher(payload=_items_payload(1))
    app.dependency_overrides[get_research_gate] = lambda: CostGate(FakeStore(), FakeCache())
    resp = await client.post(
        "/api/v1/content/research", json={"site": _PUBLIC_SITE, "contentType": "service"}
    )
    assert resp.status_code == 403


async def test_research_route_keyless_degrades_200(client: httpx.AsyncClient, app: FastAPI) -> None:
    store = FakeStore(mode="api")
    app.dependency_overrides[get_current_user] = lambda: _staff_user("manager")
    app.dependency_overrides[get_research_researcher] = lambda: None  # keyless
    app.dependency_overrides[get_research_gate] = lambda: CostGate(store, FakeCache())
    resp = await client.post(
        "/api/v1/content/research", json={"site": _PUBLIC_SITE, "contentType": "blog"}
    )
    assert resp.status_code == 200  # degrade, never crash
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["reason"] == DEGRADE_NO_ANTHROPIC
    assert store.recorded == []


async def test_research_route_ssrf_rejects_private_site(client: httpx.AsyncClient, app: FastAPI) -> None:
    app.dependency_overrides[get_current_user] = lambda: _staff_user("manager")
    app.dependency_overrides[get_research_researcher] = lambda: FakeResearcher(payload=_items_payload(1))
    app.dependency_overrides[get_research_gate] = lambda: CostGate(FakeStore(), FakeCache())
    resp = await client.post(
        "/api/v1/content/research", json={"site": "http://127.0.0.1/admin", "contentType": "service"}
    )
    assert resp.status_code == 400  # SSRF guard refuses a loopback host


async def test_research_route_empty_site_is_422(client: httpx.AsyncClient, app: FastAPI) -> None:
    app.dependency_overrides[get_current_user] = lambda: _staff_user("manager")
    resp = await client.post("/api/v1/content/research", json={"site": "", "contentType": "service"})
    assert resp.status_code == 422


# --- the bulk fan-out --------------------------------------------------------- #
class _RecorderContentRepo:
    """A minimal ``ContentRepo`` that records each ``insert_job`` and returns a coded row."""

    def __init__(self) -> None:
        self.inserts: list[dict[str, Any]] = []
        self._seq = 5100

    def insert_job(self, row: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        self.inserts.append(dict(row))
        return {"code": f"CJ-{self._seq}", "created_at": "2026-08-05T00:00:00+00:00", **row}


class _StubClientsRepo:
    def get_client(self, client_id: str) -> dict[str, Any] | None:
        return {"id": client_id, "name": "Verde Cafe", "contact_color": "#22C55E"}

    def list_sites(self, client_id: str, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return [{"domain": "verdecafe.co"}]


async def test_generate_route_fans_out_into_n_jobs(
    client: httpx.AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _RecorderContentRepo()
    enqueued: list[str] = []
    activity: list[dict[str, Any]] = []

    async def _fake_record(*_a: Any, **kw: Any) -> None:
        activity.append(kw)

    monkeypatch.setattr("app.routers.content.record_activity", _fake_record)
    app.dependency_overrides[get_current_user] = lambda: _staff_user("specialist")
    app.dependency_overrides[get_content_repo] = lambda: repo
    app.dependency_overrides[get_clients_repo] = lambda: _StubClientsRepo()
    app.dependency_overrides[get_content_enqueuer] = lambda: enqueued.append

    items = [
        {"title": "Emergency Dental Austin", "pageType": "service_location", "primaryKeyword": "emergency dentist"},
        {"title": "Teeth Whitening Guide", "pageType": "blog"},
        {"title": "Dental Implants", "pageType": "service"},
    ]
    resp = await client.post(
        "/api/v1/content/research/generate", json={"clientId": "cl-1", "items": items}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["jobs"]) == 3  # fanned out into 3 jobs
    assert len(repo.inserts) == 3
    assert enqueued == body["jobs"]  # each job's pipeline worker was enqueued
    assert len(activity) == 1  # exactly ONE activity entry for the fan-out
    # the research pageType maps to the generator's page type (location flavour -> local).
    page_types = [ins["page_type"] for ins in repo.inserts]
    assert page_types == ["local", "blog", "service"]
    # every job was queued for the resolved client, snapshotting its name (never client_id).
    assert all(ins["client_name"] == "Verde Cafe" for ins in repo.inserts)


async def test_generate_route_unknown_client_404(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    class _NoClients:
        def get_client(self, client_id: str) -> dict[str, Any] | None:
            return None

    app.dependency_overrides[get_current_user] = lambda: _staff_user("manager")
    app.dependency_overrides[get_content_repo] = lambda: _RecorderContentRepo()
    app.dependency_overrides[get_clients_repo] = lambda: _NoClients()
    app.dependency_overrides[get_content_enqueuer] = lambda: (lambda code: None)
    resp = await client.post(
        "/api/v1/content/research/generate",
        json={"clientId": "nope", "items": [{"title": "X", "pageType": "service"}]},
    )
    assert resp.status_code == 404


async def test_generate_route_requires_publish_content(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    app.dependency_overrides[get_current_user] = lambda: _staff_user("analyst")  # no publish_content
    resp = await client.post(
        "/api/v1/content/research/generate",
        json={"clientId": "cl-1", "items": [{"title": "X", "pageType": "service"}]},
    )
    assert resp.status_code == 403
