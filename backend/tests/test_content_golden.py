"""P7A-10: the LIVE golden-set eval harness (R4) for the CONTENT pipeline.

This is the dormant, key-gated twin of ``test_content_worker.py`` (which runs the
same pipeline with FAKES). It runs a CURATED set of ``{brief -> expected-quality
assertions}`` through the REAL research (Serper SERP + entity mining) + the REAL
writer (Claude), then scores each result with the merged ``content_qa`` §11
scorecard and asserts the PROVISIONAL publish bar. No DB, no broker: the pipeline
core is driven with an in-memory ``ContentStore`` + a permissive in-memory cost
gate, so ONLY the two external providers are real.

    AUTO-SKIPS unless BOTH ``SERPER_API_KEY`` AND ``ANTHROPIC_API_KEY`` are set
    (mirrors ``test_audit_engine_live`` / ``test_context_live``). Those keys are
    DEFERRED today, so this SKIPS cleanly and NEVER fails the gate.

=======================  CALIBRATION HONESTY (READ THIS)  =======================
The pass bar this harness asserts - ``content_qa.WEIGHTED_TOTAL_THRESHOLD`` (>= 85)
and ``MIN_DIMENSION_SCORE`` (>= 70), rolled up with ``DIMENSION_WEIGHTS`` - is
**PROVISIONAL (R4)**. The weight vector and the 85 bar are engineering estimates,
NOT yet validated against real ranking outcomes or a human SEO grade. They become
authoritative only after this harness runs WITH keys against the golden set AND a
human SEO grades the drafts - that reconciliation is the **P7A-11** milestone (the
post-key calibration). Until then, a failure here when keys land is a CALIBRATION
SIGNAL (tune the weights/threshold or the generator), not necessarily a regression.
================================================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.config import Settings, get_settings
from app.services.content_qa import MIN_DIMENSION_SCORE, WEIGHTED_TOTAL_THRESHOLD
from app.services.cost_gate import GateContext
from integrations.content_providers import ContentProviders, content_providers_from_settings
from workers.tasks.content import MeteredCostGate, execute_content_job

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# The curated golden set: brief -> expected-quality assertions. Each case pins a
# realistic client + topic and the minimum bar a ranking-grade draft must clear.
# Kept small (real SERP + real Claude cost money per run); expand at calibration.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GoldenCase:
    name: str
    page_type: str
    framework: str
    topic: str
    source_pack: dict[str, Any]
    min_words: int
    must_contain: tuple[str, ...]  # case-insensitive substrings expected in the draft


GOLDEN_SET: tuple[GoldenCase, ...] = (
    GoldenCase(
        name="local_brunch",
        page_type="local",
        framework="BAB",
        topic="best brunch in Portland's Pearl District",
        source_pack={
            "client_name": "Verde Cafe",
            "facts": {"founded": "2015", "seating": "farm-to-table brunch"},
            "services": ["weekend brunch", "single-origin espresso"],
            "proof_points": ["Named best brunch by the Portland food guide"],
            "unique_data": ["Our 2025 survey of 400 regular diners"],
            "locations": [{"city": "Portland", "proof": ["Pearl District storefront since 2015"]}],
            "internal_urls": {"brunch menu": "/menu"},
        },
        min_words=600,
        must_contain=("brunch",),
    ),
    GoldenCase(
        name="service_emergency_dental",
        page_type="service",
        framework="AIDA",
        topic="emergency dental care in Denver",
        source_pack={
            "client_name": "NorthPeak Dental",
            "facts": {"founded": "2009", "hours": "same-day emergency slots"},
            "services": ["emergency extractions", "same-day crowns"],
            "proof_points": ["4.9-star average over 1,200 reviews"],
            "unique_data": ["Average 38-minute wait for walk-in emergencies"],
            "locations": [{"city": "Denver", "proof": ["Two Denver-metro clinics"]}],
            "internal_urls": {"book online": "/book"},
        },
        min_words=600,
        must_contain=("dental",),
    ),
)


def _require_live() -> Settings:
    """Skip unless BOTH the real research + writer keys are set."""
    settings = get_settings()
    if not (settings.serper_api_key and settings.anthropic_api_key):
        pytest.skip("content golden-set requires SERPER_API_KEY + ANTHROPIC_API_KEY")
    return settings


def _real_providers(settings: Settings) -> ContentProviders:
    """Build the REAL content bundle; skip (not fail) if it degrades despite keys."""
    providers = content_providers_from_settings(settings)
    if providers is None:  # keys were checked above; None means partial config
        pytest.skip("real content providers unavailable despite keys (partial config)")
    return providers


class _MemStore:
    """In-memory ``ContentStore`` (mirrors the privileged repo) - no DB."""

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = dict(row)

    def load(self, code: str) -> dict[str, Any] | None:
        return dict(self.row) if self.row.get("code") == code else None

    def update(self, code: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        self.row.update(fields)
        return dict(self.row)


class _PermissiveCostStore:
    """A cost store that never blocks (the golden run is deliberately un-capped)."""

    def dial_mode(self, feature_key: str) -> str:
        return "api"

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return None

    def daily_spent(self) -> float:
        return 0.0

    def daily_stop(self) -> float:
        return 1_000_000.0

    def is_halted(self) -> bool:
        return False

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        return None


class _NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


@pytest.mark.parametrize("case", GOLDEN_SET, ids=lambda c: c.name)
def test_golden_case_meets_provisional_quality_bar(case: GoldenCase) -> None:
    settings = _require_live()
    providers = _real_providers(settings)

    row = {
        "code": "CJ-GOLDEN",
        "client_id": "00000000-0000-0000-0000-000000000001",
        "client_name": case.source_pack["client_name"],
        "page_type": case.page_type,
        "topic": case.topic,
        "framework": case.framework,
        "target": "PDF/Markdown",
        "status": "queued",
        "source_pack": case.source_pack,
    }
    store = _MemStore(row)
    gate = MeteredCostGate(_PermissiveCostStore(), _NullCache())

    out = execute_content_job(store, providers, "CJ-GOLDEN", settings=settings, gate=gate)

    # The pipeline must reach the human gate with a scored draft (never stuck).
    assert out.state == "advanced", f"{case.name}: pipeline did not advance ({out.reason})"
    assert out.status == "needs_review"

    final = store.row
    draft = str(final.get("draft_md") or "")
    words = int(final.get("words") or 0)
    qa = final.get("qa_score") or {}

    # Structural quality: a real long-form draft that grounds the topic.
    assert words >= case.min_words, f"{case.name}: {words} words < {case.min_words}"
    lower = draft.lower()
    for term in case.must_contain:
        assert term.lower() in lower, f"{case.name}: draft missing expected term {term!r}"

    # The §11 scorecard is attached with all 14 dimensions.
    dims = qa.get("dimensions") or {}
    assert len(dims) == 14, f"{case.name}: expected 14 QA dimensions, got {len(dims)}"

    # --- PROVISIONAL (R4) publish bar - the P7A-11 calibration target. ---
    # No single dimension below the floor, and the weighted roll-up clears the bar.
    low = {d: s for d, s in dims.items() if int(s) < MIN_DIMENSION_SCORE}
    assert not low, (
        f"{case.name}: dimensions below the PROVISIONAL floor {MIN_DIMENSION_SCORE}: {low} "
        "(calibrate at P7A-11 if this is the real quality)"
    )
    weighted = int(qa.get("weighted_total") or 0)
    assert weighted >= WEIGHTED_TOTAL_THRESHOLD, (
        f"{case.name}: weighted_total {weighted} < PROVISIONAL bar {WEIGHTED_TOTAL_THRESHOLD} "
        "(this is a CALIBRATION SIGNAL for P7A-11, not necessarily a regression)"
    )
