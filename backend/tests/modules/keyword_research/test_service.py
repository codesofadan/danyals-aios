"""Keyword-research service: the PURE analysis core + the workspace adapter.

The core is DB-free and network-free by construction, so nothing is stubbed here -
these tests call the real functions with real inputs.

SCOPE NOTE: the cost gate is deliberately NOT exercised here. ``service.py`` holds
no gate (it "just reasons" - the R5 pre-check + the degrade-on-block path live in
``tasks.execute_research``), so the cost-gate BLOCK behaviour is pinned in
``test_tasks.py`` where it actually lives.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.keyword_research.schemas import KeywordStats
from app.modules.keyword_research.service import (
    WORKSPACE_TABLE_COLS,
    build_workspace,
    classify_keyword_intent,
    find_cannibalization,
    opportunity_score,
    plan_research,
)
from integrations.keyword_data import FakeKeywordDataProvider, KeywordMetric

pytestmark = pytest.mark.unit


def _m(keyword: str, **over: Any) -> KeywordMetric:
    return KeywordMetric(keyword=keyword, **over)


# --------------------------------------------------------------------------- #
# 1. The intent cascade: provider -> serp_heuristic -> manual.
# --------------------------------------------------------------------------- #
def test_provider_intent_wins_the_cascade_and_stamps_the_source() -> None:
    label, source, confidence = classify_keyword_intent(
        "buy running shoes", [], "commercial investigation"
    )
    # The provider label wins even though the keyword's own text screams
    # transactional ("buy") - step 1 short-circuits before the heuristic runs.
    assert (label, source, confidence) == ("Commercial", "provider", 0.9)


def test_unresolvable_provider_label_falls_through_to_the_serp_heuristic() -> None:
    # normalize_intent returns None for an off-vocabulary label -> step 2, not a crash.
    label, source, confidence = classify_keyword_intent(
        "buy running shoes", [], "not-a-real-intent"
    )
    assert (label, source) == ("Transactional", "serp_heuristic")
    assert 0.0 < confidence <= 1.0


def test_absent_provider_label_uses_the_serp_heuristic() -> None:
    label, source, _c = classify_keyword_intent("buy running shoes", [], None)
    assert (label, source) == ("Transactional", "serp_heuristic")


@pytest.mark.parametrize(
    ("keyword", "expected"),
    [
        ("buy running shoes", "Transactional"),
        ("best crm software", "Commercial"),
        ("how to fix a leaking tap", "Informational"),
        ("acme login", "Navigational"),
    ],
)
def test_serp_heuristic_reads_intent_off_the_keyword_text(keyword: str, expected: str) -> None:
    label, source, _c = classify_keyword_intent(keyword, [], None)
    assert (label, source) == (expected, "serp_heuristic")


def test_empty_keyword_is_the_manual_fallback() -> None:
    # The only path that reaches step 3: classify_intent always returns something,
    # so 'manual' is reserved for a keyword with no text at all.
    assert classify_keyword_intent("   ", [], None) == ("Informational", "manual", 0.0)


def test_provider_label_is_normalised_case_insensitively() -> None:
    assert classify_keyword_intent("x", [], "LOCAL")[0] == "Local"
    assert classify_keyword_intent("x", [], "transactional")[0] == "Transactional"


def test_local_intent_only_ever_comes_from_the_provider() -> None:
    # The content engine's Intent vocabulary has no 'local', so the heuristic can
    # never emit it - only the provider step can.
    assert classify_keyword_intent("plumber near me", [], "local pack")[0] == "Local"
    assert classify_keyword_intent("plumber near me", [], None)[0] != "Local"


def test_cascade_source_is_stamped_onto_every_enriched_keyword() -> None:
    plan = plan_research(
        "plumber",
        [_m("plumber", volume=100), _m("buy plumber tools", volume=50)],
        [],
        provider_intents={"plumber": "Commercial"},
    )
    by_kw = {k.keyword: k for k in plan.keywords}
    # The seed carried a provider label; the spoke fell through to the heuristic.
    assert by_kw["plumber"].intent_source == "provider"
    assert by_kw["plumber"].intent == "Commercial"
    assert by_kw["buy plumber tools"].intent_source == "serp_heuristic"


# --------------------------------------------------------------------------- #
# 2. opportunity_score: 0.25*vol_n + 0.35*diff_n + 0.40*rel.
# --------------------------------------------------------------------------- #
def test_opportunity_weights_are_exactly_25_35_40() -> None:
    """Isolate each term to pin its weight without re-implementing the formula.

    At the 100k volume ceiling vol_n saturates to 1.0, so a zero-easiness,
    zero-relevance keyword scores exactly the volume weight; holding volume at its
    floor, flipping ONLY difficulty (or relevance) end-to-end moves the score by
    exactly that term's weight.
    """
    assert opportunity_score(100_000, 100, 0) == 25.0  # 0.25 * 1.0 * 100
    assert opportunity_score(1, 0, 0) - opportunity_score(1, 100, 0) == 35.0
    assert opportunity_score(1, 100, 1) - opportunity_score(1, 100, 0) == 40.0
    assert opportunity_score(100_000, 0, 1) == 100.0  # the weights sum to 1.0


def test_difficulty_is_inverted_into_easiness() -> None:
    # A LOW-KD term must score HIGHER - the sign of this term is easy to flip.
    assert opportunity_score(1000, 10, 0.5) > opportunity_score(1000, 90, 0.5)


def test_opportunity_score_is_monotonic_in_each_input() -> None:
    assert opportunity_score(10_000, 40, 0.5) > opportunity_score(1_000, 40, 0.5)
    assert opportunity_score(1_000, 40, 0.9) > opportunity_score(1_000, 40, 0.3)


def test_opportunity_score_is_bounded_to_0_100_and_clamps_junk_inputs() -> None:
    # Above the ceiling / below zero / out-of-range relevance all clamp, never
    # overflow past 100 or go negative.
    assert opportunity_score(10_000_000, 0, 1.0) == 100.0  # volume saturates
    assert opportunity_score(999_999, -50, 9.0) == 100.0  # negative KD + rel>1 clamp
    worst = opportunity_score(0, 100, 0)
    assert 0.0 <= worst <= 100.0
    for volume, difficulty, rel in [(0, 100, 0), (50, 50, 0.5), (100_000, 0, 1)]:
        assert 0.0 <= opportunity_score(volume, difficulty, rel) <= 100.0


def test_zero_volume_does_not_explode_the_log() -> None:
    # log10(0) would be a domain error; the floor keeps it finite and honest.
    assert opportunity_score(0, 100, 0) == 1.51


def test_opportunity_score_rounds_to_two_decimals() -> None:
    score = opportunity_score(8_100, 42, 1.0)
    assert score == 79.84
    assert round(score, 2) == score


def test_volume_is_log_scaled_not_linear() -> None:
    """The long tail must stay separable: each DECADE of volume is worth roughly the
    same score, where a linear scale would flatten the whole tail toward zero.

    The steps are near-identical rather than exact because the scale is
    ``log10(volume + 1)`` - the +1 offset shifts the low decade slightly.
    """
    step_low = opportunity_score(1_000, 50, 0.5) - opportunity_score(100, 50, 0.5)
    step_high = opportunity_score(10_000, 50, 0.5) - opportunity_score(1_000, 50, 0.5)
    assert step_low == pytest.approx(step_high, abs=0.05)
    # Under a LINEAR scale the same two steps would differ by ~10x; they do not.
    assert step_low > 4.0 and step_high > 4.0


# --------------------------------------------------------------------------- #
# 3. Relevance + dedupe + determinism.
# --------------------------------------------------------------------------- #
def test_the_seed_itself_scores_maximum_relevance() -> None:
    seed_only = plan_research("plumber", [_m("plumber", volume=1_000, difficulty=50)], [])
    unrelated = plan_research("plumber", [_m("zebra", volume=1_000, difficulty=50)], [])
    # Same volume + difficulty; only relevance differs (1.0 vs the 0.3 floor).
    assert seed_only.keywords[0].opportunity > unrelated.keywords[0].opportunity


def test_loosely_related_terms_keep_the_relevance_floor() -> None:
    plan = plan_research("plumber", [_m("zebra", volume=1_000, difficulty=0)], [])
    # rel floors at 0.3 -> 0.40*0.3 = 12.0 of the score is retained, not zeroed.
    assert plan.keywords[0].opportunity == pytest.approx(
        opportunity_score(1_000, 0, 0.3), abs=0.01
    )


def test_duplicate_and_blank_keywords_are_dropped_case_insensitively() -> None:
    plan = plan_research(
        "plumber",
        [_m("Plumber", volume=100), _m("plumber", volume=999), _m("   ", volume=5)],
        [_m("PLUMBER", volume=1), _m("emergency plumber", volume=50)],
    )
    keywords = [k.keyword for k in plan.keywords]
    assert keywords == ["Plumber", "emergency plumber"]  # first hit wins; blanks dropped
    assert plan.cluster.size == 2


def test_plan_research_is_deterministic_with_the_sha256_seeded_fake() -> None:
    fake = FakeKeywordDataProvider()
    ideas, related = fake.keyword_ideas("plumber"), fake.related_keywords("plumber")
    first = plan_research("plumber", ideas, related)
    second = plan_research("plumber", ideas, related)
    assert first == second  # frozen dataclasses -> structural equality


def test_low_confidence_provider_metrics_are_flagged_not_dropped() -> None:
    plan = plan_research(
        "plumber",
        [_m("plumber", volume=100, low_confidence=True), _m("plumber cost", volume=50)],
        [],
    )
    by_kw = {k.keyword: k.metrics_confidence for k in plan.keywords}
    assert by_kw == {"plumber": "low", "plumber cost": "high"}


# --------------------------------------------------------------------------- #
# 4. Winnability-aware difficulty.
# --------------------------------------------------------------------------- #
def test_unaudited_client_falls_back_to_the_neutral_da() -> None:
    # client_da=None -> neutral 30 + stretch 15 = a KD 45 ceiling.
    plan = plan_research(
        "seo",
        [_m("kd45", difficulty=45.0), _m("kd46", difficulty=46.0)],
        [],
        client_da=None,
        neutral_da=30.0,
        winnable_stretch=15.0,
    )
    by_kw = {k.keyword: k.winnable for k in plan.keywords}
    assert by_kw == {"kd45": True, "kd46": False}


def test_a_high_authority_client_wins_harder_keywords() -> None:
    metrics = [_m("kd90", difficulty=90.0)]
    strong = plan_research("seo", metrics, [], client_da=80.0, winnable_stretch=15.0)
    weak = plan_research("seo", metrics, [], client_da=10.0, winnable_stretch=15.0)
    assert strong.keywords[0].winnable is True   # 80 + 15 >= 90
    assert weak.keywords[0].winnable is False    # 10 + 15 < 90


def test_winnable_stretch_is_honoured_at_the_boundary() -> None:
    metrics = [_m("kd50", difficulty=50.0)]
    assert plan_research("s", metrics, [], client_da=40.0, winnable_stretch=10.0).keywords[0].winnable
    assert not plan_research("s", metrics, [], client_da=40.0, winnable_stretch=9.0).keywords[0].winnable


def test_winnability_is_independent_of_the_opportunity_score() -> None:
    # A high-opportunity keyword can still be unwinnable (big volume, low KD is rare):
    # the two verdicts must not be collapsed into one.
    plan = plan_research(
        "seo", [_m("huge", volume=100_000, difficulty=95.0)], [], client_da=10.0
    )
    kw = plan.keywords[0]
    assert kw.winnable is False
    assert kw.opportunity > 0


# --------------------------------------------------------------------------- #
# 5. Clustering.
# --------------------------------------------------------------------------- #
def test_cluster_pillars_on_the_seed_and_aggregates_the_spokes() -> None:
    plan = plan_research(
        "plumber",
        [_m("plumber", volume=100, difficulty=10.0), _m("plumber cost", volume=50, difficulty=30.0)],
        [_m("emergency plumber", volume=25, difficulty=20.0)],
    )
    cluster = plan.cluster
    assert cluster.name == "plumber" and cluster.pillar_keyword == "plumber"
    assert cluster.size == 3
    assert cluster.total_volume == 175
    assert cluster.avg_difficulty == 20.0  # (10 + 30 + 20) / 3


def test_dominant_intent_is_the_most_common_label() -> None:
    plan = plan_research(
        "a", [_m("a"), _m("b"), _m("c")], [],
        provider_intents={"a": "Commercial", "b": "Commercial", "c": "Informational"},
    )
    assert plan.cluster.dominant_intent == "Commercial"


def test_dominant_intent_tie_breaks_deterministically_by_label_order() -> None:
    # A tie must resolve the SAME way every run (the earliest INTENT_LABELS entry).
    plan = plan_research(
        "a", [_m("a"), _m("b")], [],
        provider_intents={"a": "Commercial", "b": "Informational"},
    )
    assert plan.cluster.dominant_intent == "Informational"
    assert plan_research(
        "a", [_m("a"), _m("b")], [],
        provider_intents={"b": "Informational", "a": "Commercial"},
    ).cluster.dominant_intent == "Informational"  # input order must not matter


def test_empty_research_yields_an_empty_cluster_not_a_zero_division() -> None:
    plan = plan_research("plumber", [], [])
    assert plan.keywords == []
    assert plan.cluster.size == 0
    assert plan.cluster.avg_difficulty == 0.0  # not a ZeroDivisionError
    assert plan.cluster.total_volume == 0
    assert plan.cluster.dominant_intent is None


# --------------------------------------------------------------------------- #
# 6. The cannibalization guard.
# --------------------------------------------------------------------------- #
def test_cannibalization_flags_a_url_claimed_by_two_intents() -> None:
    conflicts = find_cannibalization([
        {"keyword": "plumber cost", "intent": "Transactional", "target_url": "/plumbing"},
        {"keyword": "what is plumbing", "intent": "Informational", "target_url": "/plumbing"},
        {"keyword": "best plumber", "intent": "Commercial", "target_url": "/best"},
    ])
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.target_url == "/plumbing"
    assert conflict.intents == ["Informational", "Transactional"]  # sorted
    assert conflict.keywords == ["plumber cost", "what is plumbing"]


def test_one_url_one_intent_is_not_a_conflict() -> None:
    # Two keywords sharing a URL is FINE - only a clash of INTENTS cannibalises.
    assert find_cannibalization([
        {"keyword": "plumber cost", "intent": "Transactional", "target_url": "/plumbing"},
        {"keyword": "plumber pricing", "intent": "Transactional", "target_url": "/plumbing"},
    ]) == []


def test_cannibalization_ignores_rows_without_a_url_or_an_intent() -> None:
    # An unassigned bank keyword cannot cannibalise anything.
    assert find_cannibalization([
        {"keyword": "a", "intent": "Commercial", "target_url": ""},
        {"keyword": "b", "intent": None, "target_url": "/x"},
        {"keyword": "c", "target_url": "/x"},
        {"keyword": "d", "intent": "Informational"},
    ]) == []


def test_cannibalization_is_empty_for_a_clean_bank() -> None:
    assert find_cannibalization([]) == []


def test_cannibalization_conflicts_are_sorted_by_url() -> None:
    conflicts = find_cannibalization([
        {"keyword": "a", "intent": "Commercial", "target_url": "/zebra"},
        {"keyword": "b", "intent": "Informational", "target_url": "/zebra"},
        {"keyword": "c", "intent": "Commercial", "target_url": "/apple"},
        {"keyword": "d", "intent": "Local", "target_url": "/apple"},
    ])
    assert [c.target_url for c in conflicts] == ["/apple", "/zebra"]


# --------------------------------------------------------------------------- #
# 7. The /workspace adapter.
# --------------------------------------------------------------------------- #
def _stats(saved: int = 640, clusters: int = 28, avg: float = 34.2) -> KeywordStats:
    return KeywordStats(saved=saved, clusters=clusters, avg_difficulty=avg)


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "keyword": "invisalign cost", "volume": 8100, "difficulty": 42.0,
        "intent": "Commercial",
    }
    row.update(over)
    return row


def test_workspace_columns_are_pinned_to_the_tools_ts_order() -> None:
    table = build_workspace(_stats(), [_row()]).table
    assert table is not None
    assert table.cols == ["Keyword", "Volume", "Difficulty", "Intent"]
    assert table.cols == WORKSPACE_TABLE_COLS
    assert table.cols is not WORKSPACE_TABLE_COLS  # a copy: a caller cannot mutate the constant


def test_workspace_kpis_are_the_three_bank_tiles() -> None:
    kpis = build_workspace(_stats(saved=1234, clusters=28, avg=34.6), []).kpis
    assert [k.label for k in kpis] == ["Saved keywords", "Clusters", "Avg. difficulty"]
    assert kpis[0].value == "1,234"  # thousands-separated display string
    assert kpis[1].value == "28"
    assert kpis[2].value == "35"  # rounded for the tile


def test_workspace_row_is_positional_and_formats_each_cell() -> None:
    table = build_workspace(_stats(), [_row()]).table
    assert table is not None
    keyword, volume, difficulty, intent = table.rows[0]
    assert keyword == "invisalign cost"
    assert volume == "8,100"
    assert difficulty.v == "KD 42" and difficulty.tone == "warn"  # type: ignore[union-attr]
    assert intent.v == "Commercial" and intent.tone == "info"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("difficulty", "tone"),
    [(0.0, "ok"), (29.9, "ok"), (30.0, "warn"), (49.9, "warn"), (50.0, "crit"), (99.0, "crit")],
)
def test_workspace_difficulty_tone_boundaries(difficulty: float, tone: str) -> None:
    table = build_workspace(_stats(), [_row(difficulty=difficulty)]).table
    assert table is not None
    assert table.rows[0][2].tone == tone  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("intent", "tone"),
    [
        ("Commercial", "info"), ("Transactional", "info"),  # buyer signal
        ("Informational", "ok"), ("Navigational", "ok"), ("Local", "ok"),
        ("", "mut"),  # unclassified
    ],
)
def test_workspace_intent_tone_marks_buyer_signal(intent: str, tone: str) -> None:
    table = build_workspace(_stats(), [_row(intent=intent)]).table
    assert table is not None
    assert table.rows[0][3].tone == tone  # type: ignore[union-attr]


def test_workspace_unclassified_intent_renders_an_em_dash() -> None:
    table = build_workspace(_stats(), [_row(intent=None)]).table
    assert table is not None
    cell = table.rows[0][3]
    assert cell.v == "—" and cell.tone == "mut"  # type: ignore[union-attr]


def test_workspace_tolerates_null_metrics_in_a_row() -> None:
    table = build_workspace(_stats(), [_row(volume=None, difficulty=None)]).table
    assert table is not None
    assert table.rows[0][1] == "0"
    assert table.rows[0][2].v == "KD 0"  # type: ignore[union-attr]


def test_workspace_caps_the_table_at_eight_rows() -> None:
    table = build_workspace(_stats(), [_row(keyword=f"kw {i}") for i in range(25)]).table
    assert table is not None
    assert len(table.rows) == 8
    assert table.rows[0][0] == "kw 0"  # the repo's ordering is preserved, not re-sorted


def test_workspace_empty_bank_still_renders_the_envelope() -> None:
    extra = build_workspace(_stats(saved=0, clusters=0, avg=0.0), [])
    assert extra.table is not None and extra.table.rows == []
    assert [k.value for k in extra.kpis] == ["0", "0", "0"]  # honest zeros, not blanks
    assert extra.primary is not None
    assert extra.bullets  # the CTA + feature bullets survive an empty bank


def test_workspace_primary_cta_is_pinned() -> None:
    primary = build_workspace(_stats(), []).primary
    assert primary is not None
    assert (primary.label, primary.icon) == ("Research keywords", "search")


def test_workspace_bullets_are_copied_not_shared() -> None:
    first = build_workspace(_stats(), [])
    second = build_workspace(_stats(), [])
    first.bullets.append("mutated")
    assert "mutated" not in second.bullets  # a per-request mutation cannot leak
