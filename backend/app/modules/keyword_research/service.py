"""Keyword-research orchestration - the PURE analysis core + the tool-workspace
adapter.

This module is DB-free and network-free (mirrors ``content_research``'s pure core):
it takes the provider's fetched metrics and turns them into enriched keyword rows -
intent (a provider -> SERP-heuristic -> manual cascade), a 0-100 opportunity score, a
winnability verdict, and a single topical cluster - all deterministic given the same
inputs. The cost-gated fetch + the DB upsert live in ``tasks.py``; the RLS reads live
in ``repo.py``; this layer just reasons.

It REUSES the Part-7 content engine instead of reinventing it:

* ``classify_intent`` reads intent off a (here, synthetic) SERP text pool.
* ``cluster_terms`` groups the seed + spokes into one pillar/cluster map.
* ``assess_winnability`` judges each keyword's difficulty against the client's
  authority (a neutral DA is assumed when the client is un-audited).
* ``cannibalization_conflicts`` flags a landing URL claimed by more than one intent.

``build_workspace`` is the ``GET /keyword-research/workspace`` adapter: it emits the
frontend ``lib/tools.ts`` ``keyword_research`` EXTRA shape with table columns pinned
EXACTLY to ``["Keyword", "Volume", "Difficulty", "Intent"]`` (the tool-workspace
contract test asserts this byte-for-byte).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, cast

from app.modules.keyword_research.schemas import (
    CannibalizationConflict,
    KeywordStats,
)
from app.schemas.tool_workspace import (
    ToolCell,
    ToolCellObj,
    ToolExtraResponse,
    ToolKpi,
    ToolPrimary,
    ToolTable,
)
from app.services.content_research import (
    Intent,
    RegistryEntry,
    TermSet,
    assess_winnability,
    cannibalization_conflicts,
    classify_intent,
    cluster_terms,
)
from integrations.content_research import KeywordMetrics, OrganicResult, SerpResult
from integrations.keyword_data import INTENT_LABELS, KeywordMetric, normalize_intent

# Defaults reused from the content research service (a task overrides from Settings).
_DEFAULT_NEUTRAL_DA = 30.0
_DEFAULT_WINNABLE_STRETCH = 15.0

# Volume normaliser: a 100k-monthly-search ceiling, log-scaled so the score spreads
# across the long tail instead of saturating at the head.
_VOLUME_CEILING = 100_000.0

# The lowercase content intents -> the capitalised display / DB labels. 'Local' has
# no content-engine equivalent (it comes only from the provider), so it is absent.
_INTENT_DISPLAY: dict[Intent, str] = {
    "informational": "Informational",
    "commercial": "Commercial",
    "transactional": "Transactional",
    "navigational": "Navigational",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# --- tool-workspace contract constants (pinned to lib/tools.ts keyword_research) ---
WORKSPACE_TABLE_COLS: list[str] = ["Keyword", "Volume", "Difficulty", "Intent"]
_WORKSPACE_TABLE_TITLE = "Opportunity keywords"
_WORKSPACE_TABLE_ICON = "search"
_WORKSPACE_PRIMARY = ToolPrimary(label="Research keywords", icon="search")
_WORKSPACE_BULLETS = [
    "Find & group keyword opportunities",
    "See volume, difficulty & intent",
    "Assign keywords to clients",
]
_WORKSPACE_ROW_LIMIT = 8


@dataclass(frozen=True)
class EnrichedKeyword:
    """One researched keyword with everything the bank upsert needs."""

    keyword: str
    volume: int
    difficulty: float
    cpc: float
    competition: float
    intent: str | None
    intent_source: str
    intent_confidence: float
    opportunity: float
    winnable: bool
    metrics_confidence: str


@dataclass(frozen=True)
class ClusterPlan:
    """The single cluster a research run produces (pillar + aggregates)."""

    name: str
    pillar_keyword: str
    dominant_intent: str | None
    size: int
    total_volume: int
    avg_difficulty: float


@dataclass(frozen=True)
class ResearchPlan:
    """The full result of one research run: the cluster + its enriched keywords."""

    cluster: ClusterPlan
    keywords: list[EnrichedKeyword] = field(default_factory=list)


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 1}


def _relevance(seed: str, keyword: str) -> float:
    """Token-overlap relevance of ``keyword`` to ``seed`` (Jaccard), floored at 0.3
    so even a loosely-related term keeps some opportunity weight; the seed is 1.0."""
    if keyword.strip().lower() == seed.strip().lower():
        return 1.0
    a, b = _tokens(seed), _tokens(keyword)
    if not a or not b:
        return 0.3
    overlap = len(a & b) / len(a | b)
    return round(max(0.3, overlap), 3)


def opportunity_score(volume: int, difficulty: float, relevance: float) -> float:
    """The 0-100 opportunity score: reward demand + easiness + relevance.

    ``vol_n`` log-scales volume to a 100k ceiling; ``diff_n`` is EASINESS (the inverse
    of difficulty, so a low-KD term scores higher); ``rel`` is the 0-1 seed relevance.
    Weights per the module spec: ``0.25*vol_n + 0.35*diff_n + 0.40*rel``."""
    vol_n = min(1.0, math.log10(max(volume, 1) + 1) / math.log10(_VOLUME_CEILING + 1))
    diff_n = 1.0 - min(1.0, max(0.0, difficulty) / 100.0)
    rel = min(1.0, max(0.0, relevance))
    return round(100.0 * (0.25 * vol_n + 0.35 * diff_n + 0.40 * rel), 2)


def _synthetic_serp(keyword: str, related: list[str]) -> SerpResult:
    """A minimal SERP shell for the intent classifier when we hold no live SERP: the
    keyword + its related terms ARE the text pool ``classify_intent`` scans (the
    keyword-research module reads intent from term text, not a fetched SERP)."""
    return SerpResult(
        keyword=keyword,
        geo=None,
        organic=[OrganicResult(position=1, title=keyword, link="", snippet=None)],
        people_also_ask=[],
        related_searches=list(related),
    )


def classify_keyword_intent(
    keyword: str, related: list[str], provider_intent: str | None
) -> tuple[str, str, float]:
    """The intent cascade: provider -> SERP heuristic -> manual.

    1. A provider-supplied label (normalised to one of the five) wins with high
       confidence. 2. Else ``classify_intent`` reads it off the keyword + related text
       (``serp_heuristic``). 3. ``classify_intent`` always returns a value (defaulting
       to informational at low confidence), so the ``manual`` fallback is only reached
       for an empty keyword."""
    label = normalize_intent(provider_intent)
    if label is not None:
        return (label, "provider", 0.9)
    if not keyword.strip():
        return ("Informational", "manual", 0.0)
    lc_intent, confidence = classify_intent(_synthetic_serp(keyword, related), keyword)
    return (_INTENT_DISPLAY[lc_intent], "serp_heuristic", confidence)


def _dedupe(metrics: list[KeywordMetric]) -> list[KeywordMetric]:
    """Dedupe by lowercased keyword, keeping the first (highest-volume-ordered) hit;
    drops blank keywords."""
    seen: set[str] = set()
    out: list[KeywordMetric] = []
    for m in metrics:
        key = m.keyword.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(m)
    return out


def plan_research(
    seed: str,
    ideas: list[KeywordMetric],
    related: list[KeywordMetric],
    *,
    provider_intents: dict[str, str] | None = None,
    client_da: float | None = None,
    neutral_da: float = _DEFAULT_NEUTRAL_DA,
    winnable_stretch: float = _DEFAULT_WINNABLE_STRETCH,
) -> ResearchPlan:
    """Turn the provider's fetched metrics into an enriched, clustered plan.

    ``provider_intents`` maps a keyword to a provider-classified label (the first step
    of the intent cascade); everything else falls back to the SERP-text heuristic.
    ``client_da`` drives winnability (a neutral DA is assumed when ``None``). Pure +
    deterministic: same inputs -> same plan."""
    provider_intents = provider_intents or {}
    combined = _dedupe([*ideas, *related])
    related_terms = [m.keyword for m in combined if m.keyword.strip().lower() != seed.strip().lower()]

    # Winnability over the whole set in one pass (reuses the content engine).
    kmetrics = [KeywordMetrics(keyword=m.keyword, volume=m.volume, difficulty=m.difficulty) for m in combined]
    report = assess_winnability(
        kmetrics, client_da, neutral_da=neutral_da, winnable_stretch=winnable_stretch
    )
    winnable_by_kw = {t.keyword: t.winnable for t in report.targets}

    enriched: list[EnrichedKeyword] = []
    for m in combined:
        # The seed classifies against the full related pool; a spoke against itself.
        related_pool = related_terms if m.keyword.strip().lower() == seed.strip().lower() else []
        intent, source, confidence = classify_keyword_intent(
            m.keyword, related_pool, provider_intents.get(m.keyword)
        )
        relevance = _relevance(seed, m.keyword)
        enriched.append(
            EnrichedKeyword(
                keyword=m.keyword,
                volume=m.volume,
                difficulty=round(m.difficulty, 2),
                cpc=round(m.cpc, 2),
                competition=round(m.competition, 3),
                intent=intent,
                intent_source=source,
                intent_confidence=round(confidence, 3),
                opportunity=opportunity_score(m.volume, m.difficulty, relevance),
                winnable=bool(winnable_by_kw.get(m.keyword, False)),
                metrics_confidence="low" if m.low_confidence else "high",
            )
        )

    cluster = _build_cluster(seed, related_terms, enriched)
    return ResearchPlan(cluster=cluster, keywords=enriched)


def _build_cluster(seed: str, related_terms: list[str], enriched: list[EnrichedKeyword]) -> ClusterPlan:
    """Fold the seed + spokes into ONE pillar/cluster (reuses ``cluster_terms``) and
    aggregate its size / volume / difficulty / dominant intent."""
    term_set = TermSet(primary=seed, secondary=related_terms, semantic_entities=[], questions=[])
    topical = cluster_terms(term_set)  # pillar + supporting (the content engine)
    size = len(enriched)
    total_volume = sum(k.volume for k in enriched)
    avg_difficulty = round(sum(k.difficulty for k in enriched) / size, 2) if size else 0.0
    return ClusterPlan(
        name=topical.pillar,
        pillar_keyword=topical.pillar,
        dominant_intent=_dominant_intent(enriched),
        size=size,
        total_volume=total_volume,
        avg_difficulty=avg_difficulty,
    )


def _dominant_intent(enriched: list[EnrichedKeyword]) -> str | None:
    """The most common intent across the cluster (ties broken by the label order), or
    ``None`` when nothing classified."""
    counts: dict[str, int] = {}
    for k in enriched:
        if k.intent:
            counts[k.intent] = counts.get(k.intent, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda label: (counts[label], -INTENT_LABELS.index(label)))


def find_cannibalization(rows: list[dict[str, Any]]) -> list[CannibalizationConflict]:
    """The cannibalization guard over the bank: a landing URL claimed by MORE than one
    intent is a conflict (two pages competing for the same URL/intent). Reuses the
    content engine's ``cannibalization_conflicts`` to find the offending URLs, then
    attaches each URL's intents + keywords."""
    entries = [
        RegistryEntry(
            keyword=str(r.get("keyword", "")),
            url_slug=str(r.get("target_url", "")),
            intent=cast("Intent", r.get("intent")),  # capitalised label; compared by equality only
        )
        for r in rows
        if r.get("target_url") and r.get("intent")
    ]
    conflict_urls = set(cannibalization_conflicts(entries))
    out: list[CannibalizationConflict] = []
    for url in sorted(conflict_urls):
        intents = sorted({e.intent for e in entries if e.url_slug == url})
        keywords = sorted({e.keyword for e in entries if e.url_slug == url})
        out.append(
            CannibalizationConflict(
                target_url=url, intents=list(intents), keywords=keywords
            )
        )
    return out


# --------------------------------------------------------------------------- #
# The /workspace adapter (frontend lib/tools.ts keyword_research EXTRA shape).
# --------------------------------------------------------------------------- #
def _difficulty_tone(difficulty: float) -> str:
    """ok < 30, warn < 50, crit otherwise (the tool-workspace difficulty scale)."""
    if difficulty < 30:
        return "ok"
    if difficulty < 50:
        return "warn"
    return "crit"


def _intent_tone(intent: str) -> str:
    """Commercial / Transactional read as ``info`` (buyer signal); Local /
    Informational / Navigational read as ``ok``; an unclassified keyword is ``mut``."""
    if not intent:
        return "mut"
    return "info" if intent in ("Commercial", "Transactional") else "ok"


def _keyword_row(row: dict[str, Any]) -> list[ToolCell]:
    """One workspace table row: [Keyword, Volume, Difficulty, Intent] with tones."""
    volume = int(row.get("volume", 0) or 0)
    difficulty = float(row.get("difficulty", 0) or 0)
    intent = str(row.get("intent") or "")
    return [
        str(row.get("keyword", "")),
        f"{volume:,}",
        ToolCellObj(v=f"KD {round(difficulty)}", tone=cast("Any", _difficulty_tone(difficulty))),
        ToolCellObj(v=intent or "—", tone=cast("Any", _intent_tone(intent))),
    ]


def build_workspace(stats: KeywordStats, keywords: list[dict[str, Any]]) -> ToolExtraResponse:
    """Assemble the keyword-research tool workspace (KPIs + opportunity table + CTA).

    KPI labels + the primary + the table columns are pinned to ``lib/tools.ts``; the
    columns are EXACTLY ``["Keyword", "Volume", "Difficulty", "Intent"]`` (the
    tool-workspace contract test enforces byte-identity)."""
    kpis = [
        ToolKpi(label="Saved keywords", value=f"{stats.saved:,}"),
        ToolKpi(label="Clusters", value=str(stats.clusters)),
        ToolKpi(label="Avg. difficulty", value=str(round(stats.avg_difficulty))),
    ]
    table = ToolTable(
        title=_WORKSPACE_TABLE_TITLE,
        icon=_WORKSPACE_TABLE_ICON,
        cols=list(WORKSPACE_TABLE_COLS),
        rows=[_keyword_row(r) for r in keywords[:_WORKSPACE_ROW_LIMIT]],
    )
    return ToolExtraResponse(
        kpis=kpis, table=table, primary=_WORKSPACE_PRIMARY, bullets=list(_WORKSPACE_BULLETS)
    )
