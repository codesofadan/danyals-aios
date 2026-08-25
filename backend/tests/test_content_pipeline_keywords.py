"""P3: keyword discovery - real demand, and the end of the fabricated metrics.

Fake store and fake provider, so no database and no spend.
"""

from __future__ import annotations

from typing import Any

from app.modules.content_planning.schemas import KeywordTerm
from app.services.content_pipeline.context import PipelineContext
from app.services.content_pipeline.keywords import (
    DEFAULT_LIMIT,
    run_keyword_discovery,
)
from integrations.keyword_data import KeywordMetric


class _Store:
    def __init__(self) -> None:
        self.terms: list[KeywordTerm] = []

    def create_keyword_plan(self, **kw: Any) -> str:
        return "plan-1"

    def add_keyword_terms(self, plan_id: str, terms: list[KeywordTerm]) -> int:
        self.terms.extend(terms)
        return len(terms)

    def keyword_terms(self, plan_id: str, *, measured_only: bool = False) -> list[KeywordTerm]:
        return [t for t in self.terms if t.is_measured] if measured_only else self.terms


class _Provider:
    def __init__(self, ideas: list[KeywordMetric] | None = None) -> None:
        self._ideas = ideas if ideas is not None else [
            KeywordMetric("emergency ac repair san jose", volume=1300, difficulty=41.0),
            KeywordMetric("plumber san jose", volume=12000, difficulty=55.0),
            KeywordMetric("thin term", volume=20, difficulty=5.0, low_confidence=True),
        ]

    def keyword_ideas(self, seed, *, geo=None, limit=50):
        return self._ideas

    def related_keywords(self, keyword, *, geo=None, limit=50):
        return []

    def search_intent(self, keyword):
        return "Transactional"


def _ctx(**kw: Any) -> PipelineContext:
    base = {"engagement_id": "eng-1", "primary_keyword": "emergency ac repair san jose"}
    return PipelineContext(**{**base, **kw})


def test_provider_metrics_are_stored_as_measured() -> None:
    store = _Store()
    result = run_keyword_discovery(_ctx(), store=store, provider=_Provider())
    assert result.outcome == "ok"
    measured = [t for t in store.terms if t.is_measured]
    assert measured and all(t.source == "dataforseo" for t in measured)


def test_a_thin_provider_pull_stays_estimated() -> None:
    """`low_confidence` is the provider telling us its own figure is weak. Carrying it
    through as `estimated` keeps the honesty end to end instead of laundering a weak
    number into a confident one."""
    store = _Store()
    run_keyword_discovery(_ctx(), store=store, provider=_Provider())
    thin = next(t for t in store.terms if t.keyword == "thin term")
    assert thin.estimated and not thin.is_measured


def test_an_off_topic_high_volume_term_ranks_below_a_relevant_smaller_one() -> None:
    """The whole reason opportunity exists rather than sorting by volume. "plumber san
    jose" has 9x the demand of the target term and is the wrong page; ranking by raw
    volume would put it first."""
    store = _Store()
    run_keyword_discovery(_ctx(), store=store, provider=_Provider())
    by_kw = {t.keyword: t for t in store.terms}
    target = by_kw["emergency ac repair san jose"]
    off_topic = by_kw["plumber san jose"]
    assert off_topic.volume > target.volume
    assert (target.opportunity or 0) > (off_topic.opportunity or 0)


def test_opportunity_stays_inside_the_column_bound() -> None:
    """Regression: a volume-scaled score overflowed `numeric(7,4)` on the first real
    keyword (8,100 volume -> ~2,600). The platform's `opportunity_score` is 0-100 with
    a log-scaled volume term, which is why it fits - and why there is only ONE
    opportunity number in the product rather than two meaning different things."""
    store = _Store()
    run_keyword_discovery(
        _ctx(), store=store,
        provider=_Provider([KeywordMetric("huge", volume=500_000, difficulty=1.0)]),
    )
    assert all(0 <= (t.opportunity or 0) <= 100 for t in store.terms)


def test_no_provider_degrades_honestly_rather_than_inventing() -> None:
    """The defect this stage replaces derived volume from log10(total_results) and
    rendered it identically to a Google Ads figure. Without a provider there are NO
    figures - only seeds, all marked estimated."""
    store = _Store()
    result = run_keyword_discovery(_ctx(), store=store, provider=None)
    assert result.outcome == "degraded"
    assert store.terms and all(t.estimated for t in store.terms)
    assert not any(t.is_measured for t in store.terms)
    assert any("NOT demand figures" in n for n in result.notes)


def test_a_provider_that_returns_nothing_does_not_fabricate() -> None:
    store = _Store()
    result = run_keyword_discovery(_ctx(), store=store, provider=_Provider([]))
    assert result.outcome == "degraded"
    assert all(t.estimated for t in store.terms)


def test_a_provider_error_is_noted_and_survived() -> None:
    class _Broken(_Provider):
        def keyword_ideas(self, seed, *, geo=None, limit=50):
            raise RuntimeError("provider down")

    store = _Store()
    result = run_keyword_discovery(_ctx(), store=store, provider=_Broken())
    assert result.outcome == "degraded"
    assert any("keyword_ideas failed" in n for n in result.notes)


def test_the_plan_is_engagement_scoped_not_page_scoped() -> None:
    """The cost model: ~10 provider calls per ENGAGEMENT, reused by every page. Per
    page it would be ten times the calls for the same answer."""
    assert run_keyword_discovery(
        _ctx(engagement_id=None), store=_Store(), provider=_Provider()
    ).outcome == "skipped"


def test_the_result_limit_is_a_named_cost_dial() -> None:
    """Cost is dominated by the per-RESULT charge ($0.012/request + $0.00012/result),
    so raising this from 50 to 700 quintuples the bill. It is named so that edit is
    deliberate."""
    assert DEFAULT_LIMIT == 50
