"""Keyword discovery - real demand, once per engagement.

TWO DEFECTS THIS REPLACES, and they compound.

  1. FABRICATED METRICS. `integrations/content_research.py` derives "volume" and
     "difficulty" from the SERP's total-results count:

         difficulty = min(100, log10(total_results) * 8)
         volume     = min(500_000, 10 ** (log10(total_results) / 2))

     Those are invented numbers rendered identically to a Google Ads figure. Nothing
     downstream - not the operator, not the QA gate, not the client report - can tell
     a measurement from a guess.

  2. IT WAS PER PAGE. Each page paid ~10 Serper credits to invent its own numbers.

Both are fixed by the same move: pull REAL metrics from DataForSEO ONCE PER
ENGAGEMENT and store them with `estimated=False`. Measured cost is $0.198 for the ten
calls, which across a 50-page site is $0.004/page - cheaper per page than the
fabricated numbers were, and true.

WHAT MAKES A TERM "MEASURED". Only a provider figure with `estimated=False`. When
DataForSEO is unavailable the stage still runs, but every term it stores is marked
`serp_derived` and `estimated=True`. That is the honest degradation: a keyword outside
the plan still needs a sort order, and a plan built without the provider is still
better than none - it just can never again be reported to a client as demand data.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.modules.content_planning.schemas import KeywordTerm
from app.modules.keyword_research.service import _relevance as _kr_relevance
from app.modules.keyword_research.service import opportunity_score
from app.services.content_pipeline.context import PipelineContext, StageResult

STAGE = "keyword_discovery"

# The provider's per-request cost is dominated by the per-RESULT charge
# ($0.012/request + $0.00012/result), so `limit` is the cost dial, not a detail.
# At 50 it is ~$0.018 a call; at 700 it is ~$0.096. Named here because "let's get more
# keywords" is a plausible edit that would quintuple the bill silently.
DEFAULT_LIMIT = 50
MAX_BULK_METRICS = 200


class KeywordProvider(Protocol):
    def keyword_ideas(self, seed: str, *, geo: str | None = ..., limit: int = ...) -> list[Any]: ...
    def related_keywords(self, keyword: str, *, geo: str | None = ..., limit: int = ...) -> list[Any]: ...
    def search_intent(self, keyword: str) -> str | None: ...


class PlanStore(Protocol):
    def create_keyword_plan(self, **kwargs: Any) -> str: ...
    def add_keyword_terms(self, plan_id: str, terms: list[KeywordTerm]) -> int: ...
    def keyword_terms(self, plan_id: str, *, measured_only: bool = ...) -> list[KeywordTerm]: ...


# REUSED, not reimplemented. `keyword_research.service` already owns the deterministic
# scoring the platform uses, it is tested, and its `opportunity_score` is bounded 0-100
# with a LOG-scaled volume term - which is both better than a linear one and the reason
# it fits `numeric(7,4)`. My first pass here invented a parallel volume-scaled score,
# which overflowed the column on the first real keyword (8,100 volume -> ~2,600). A
# second scoring implementation would also have meant two "opportunity" numbers in one
# product meaning different things.
_relevance = _kr_relevance
_opportunity = opportunity_score


def _cluster_key(keyword: str, seed: str) -> str:
    """Group by the keyword's modifier-stripped head.

    Crude on purpose: clustering is refined at the topical-map stage with the whole
    term set in view. Here it only needs to be stable and free.
    """
    stop = {"in", "near", "me", "the", "a", "for", "of", "best", "top", "cheap"}
    tokens = [t for t in keyword.lower().split() if t not in stop]
    return " ".join(tokens[:2]) if tokens else seed.lower()


def run_keyword_discovery(
    ctx: PipelineContext,
    *,
    store: PlanStore,
    provider: KeywordProvider | None,
    seeds: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
    related_depth: int = 3,
) -> StageResult:
    """Build the engagement's keyword plan. Idempotent per engagement by design -
    the plan is reused by every page, which is the whole cost model."""
    if not ctx.engagement_id:
        return ctx.record(StageResult(
            STAGE, outcome="skipped",
            notes=("no engagement: keyword plans are engagement-scoped",),
        ))

    seed_terms = seeds or ([ctx.primary_keyword] if ctx.primary_keyword else [])
    if not seed_terms:
        return ctx.record(StageResult(
            STAGE, outcome="skipped", notes=("no seed terms",)))

    notes: list[str] = []
    plan_id = store.create_keyword_plan(
        engagement_id=ctx.engagement_id, seed_terms=seed_terms,
        geo=ctx.geo, provider="dataforseo" if provider else "",
    )

    if provider is None:
        # Honest degradation: record the seeds so the engagement has a plan, and mark
        # every one estimated. A plan of seeds is not demand data and must not read
        # as any.
        notes.append(
            "DataForSEO unavailable: the plan holds seed terms only, all marked "
            "estimated - these are NOT demand figures and must not be reported as such"
        )
        store.add_keyword_terms(plan_id, [
            KeywordTerm(keyword=s, source="operator", estimated=True,
                        relevance=1.0, cluster_key=_cluster_key(s, s))
            for s in seed_terms
        ])
        return ctx.record(StageResult(
            STAGE, outcome="degraded", notes=tuple(notes),
            data={"plan_id": plan_id, "measured": 0, "total": len(seed_terms)},
        ))

    collected: dict[str, Any] = {}
    calls = 0
    for seed in seed_terms:
        try:
            for metric in provider.keyword_ideas(seed, geo=ctx.geo or None, limit=limit):
                collected.setdefault(metric.keyword.lower(), (metric, seed))
            calls += 1
        except Exception as exc:
            notes.append(f"keyword_ideas failed for {seed!r} ({type(exc).__name__})")

    for seed in seed_terms[:related_depth]:
        try:
            for metric in provider.related_keywords(seed, geo=ctx.geo or None, limit=limit):
                collected.setdefault(metric.keyword.lower(), (metric, seed))
            calls += 1
        except Exception as exc:
            notes.append(f"related_keywords failed for {seed!r} ({type(exc).__name__})")

    if not collected:
        notes.append("the provider returned nothing; falling back to the seeds")
        store.add_keyword_terms(plan_id, [
            KeywordTerm(keyword=s, source="operator", estimated=True, relevance=1.0,
                        cluster_key=_cluster_key(s, s))
            for s in seed_terms
        ])
        return ctx.record(StageResult(
            STAGE, outcome="degraded", notes=tuple(notes),
            data={"plan_id": plan_id, "measured": 0, "total": len(seed_terms)},
            llm_calls=0,
        ))

    primary_intent = None
    try:
        primary_intent = provider.search_intent(seed_terms[0])
        calls += 1
    except Exception as exc:
        notes.append(f"search_intent unavailable ({type(exc).__name__})")

    terms: list[KeywordTerm] = []
    for _lower, (metric, seed) in collected.items():
        relevance = _relevance(seed, metric.keyword)
        volume = int(getattr(metric, "volume", 0) or 0)
        difficulty = float(getattr(metric, "difficulty", 0.0) or 0.0)
        # `low_confidence` is the provider telling us its own pull was thin. Carrying
        # that through as `estimated` keeps the honesty end to end rather than
        # laundering a weak figure into a confident one.
        thin = bool(getattr(metric, "low_confidence", False))
        terms.append(KeywordTerm(
            keyword=metric.keyword,
            source="dataforseo",
            estimated=thin,
            volume=volume or None,
            difficulty=difficulty or None,
            cpc=float(getattr(metric, "cpc", 0.0) or 0.0) or None,
            competition=float(getattr(metric, "competition", 0.0) or 0.0) or None,
            intent=primary_intent or "",
            relevance=relevance,
            opportunity=_opportunity(volume, difficulty, relevance),
            cluster_key=_cluster_key(metric.keyword, seed),
        ))

    store.add_keyword_terms(plan_id, terms)
    measured = sum(1 for t in terms if t.is_measured)
    if measured == 0:
        notes.append("no term carries a measured figure; treat this plan as indicative")

    return ctx.record(StageResult(
        STAGE, outcome="ok" if measured else "degraded", notes=tuple(notes),
        data={"plan_id": plan_id, "measured": measured, "total": len(terms),
              "provider_calls": calls},
    ))
