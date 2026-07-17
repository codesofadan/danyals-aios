"""Competitor-intel's PURE analysis core: gap classification, Jaccard overlap, the
share-of-voice maths, and the SERP auto-discovery tally.

No DB, no network, no Celery - this layer is deterministic by construction, which is
exactly why the module's judgement lives here rather than in the worker.

The load-bearing test in this file is
``test_a_client_that_does_not_rank_is_missing_never_position_zero``: ``client_position
is None`` means the client does NOT rank, and conflating that with position 0 would
invert the entire board.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.modules.competitor_intel.schemas import CompetitorStats
from app.modules.competitor_intel.service import (
    DEFAULT_CTR_CURVE,
    WORKSPACE_TABLE_COLS,
    analyze_gaps,
    build_workspace,
    classify_gap,
    ctr_for_position,
    discover_competitors,
    gap_opportunity,
    jaccard_overlap,
    normalize_domain,
    share_of_voice,
    visibility_score,
)
from app.schemas.tool_workspace import ToolCellObj

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class _Ranked:
    """A stand-in for integrations.keyword_data.RankedKeyword (the core duck-types it)."""

    keyword: str
    position: int
    volume: int = 0
    difficulty: float = 0.0
    intent: str | None = None


# --------------------------------------------------------------------------- #
# 1. Gap classification - the module's cardinal rule.
# --------------------------------------------------------------------------- #
def test_a_client_that_does_not_rank_is_missing_never_position_zero() -> None:
    """THE load-bearing rule (see the module docstring).

    ``client_position=None`` means the client does not rank AT ALL - a PURE gap. A
    truthiness test (``if not client_position``) would fold a literal position 0 into
    the same branch, which is the mental model that produces the bug: it treats 0 as a
    legitimate rank. These two inputs must NOT classify the same way.
    """
    # The client does not rank -> a pure gap.
    assert classify_gap(competitor_position=3, client_position=None, volume=10) == "missing"

    # A literal 0 is a REAL (if nonsensical) position, and 0 < 3 means the client is
    # AHEAD of the competitor - the exact opposite of a gap. If this ever returns
    # "missing", the classifier has started reading 0 as "absent".
    assert classify_gap(competitor_position=3, client_position=0, volume=10) == "shared"


def test_missing_becomes_untapped_above_the_volume_threshold() -> None:
    """``untapped`` is triage, not a different fact: it is a ``missing`` gap with real
    demand behind it. The boundary is inclusive."""
    assert classify_gap(
        competitor_position=5, client_position=None, volume=499, untapped_volume=500
    ) == "missing"
    assert classify_gap(
        competitor_position=5, client_position=None, volume=500, untapped_volume=500
    ) == "untapped"


def test_weak_is_both_ranking_with_the_competitor_ahead() -> None:
    """Rank is INVERTED (smaller wins), so the client is behind when its number is
    BIGGER. Getting this backwards would report every term the client leads as a loss."""
    assert classify_gap(competitor_position=3, client_position=9, volume=10) == "weak"
    assert classify_gap(competitor_position=9, client_position=3, volume=10) == "shared"
    assert classify_gap(competitor_position=4, client_position=4, volume=10) == "shared"


def test_an_unknown_competitor_position_never_reads_as_weak() -> None:
    """With no competitor position there is nothing to be behind, so a term both rank
    for stays ``shared`` rather than being invented into a loss."""
    assert classify_gap(competitor_position=None, client_position=9, volume=10) == "shared"


# --------------------------------------------------------------------------- #
# 2. analyze_gaps - the roll-up over a whole ranked set.
# --------------------------------------------------------------------------- #
def test_analyze_gaps_classifies_every_bucket_and_rolls_the_counters() -> None:
    """The four verdicts + the two counters, in one pass.

    ``keyword_gaps_count`` counts OPPORTUNITIES (missing+untapped+weak);
    ``common_keywords`` counts the INTERSECTION (shared+weak). A ``weak`` term is
    legitimately in BOTH - they measure different things - and this test pins that
    overlap rather than letting a future refactor quietly collapse it.
    """
    ranked = [
        _Ranked("pure gap", position=4, volume=10),        # client absent, low volume
        _Ranked("big gap", position=2, volume=5_000),      # client absent, real demand
        _Ranked("losing", position=2, volume=100),         # both rank, client behind
        _Ranked("winning", position=8, volume=100),        # both rank, client ahead
    ]
    client_positions: dict[str, int | None] = {
        "losing": 7,
        "winning": 2,
        # Tracked but unranked: 0036's "checked, not in the top-N". For gap purposes
        # this is the same fact as "not tracked" - the client does not rank.
        "tracked but unranked": None,
        "ours alone": 5,  # the client ranks, the competitor does not (union-only)
    }

    analysis = analyze_gaps(ranked, client_positions, untapped_volume=500)
    verdicts = {g.keyword: g.gap_type for g in analysis.gaps}
    assert verdicts == {
        "pure gap": "missing",
        "big gap": "untapped",
        "losing": "weak",
        "winning": "shared",
    }
    # missing + untapped + weak = 3 opportunities; shared is not a gap.
    assert analysis.keyword_gaps_count == 3
    # Both rank for 'losing' + 'winning' = 2. The competitor's pure gaps are not
    # common, and neither is the client's 'ours alone'.
    assert analysis.common_keywords == 2
    assert [g.keyword for g in analysis.opportunities] == ["pure gap", "big gap", "losing"]


def test_analyze_gaps_treats_untracked_and_unranked_identically() -> None:
    """An ABSENT key (never tracked) and a ``None`` VALUE (tracked, not ranking) are the
    same fact for a gap: the client does not rank. Read through one ``.get()`` so the
    two can never drift apart."""
    ranked = [_Ranked("absent", position=3, volume=10), _Ranked("unranked", position=3, volume=10)]
    analysis = analyze_gaps(ranked, {"unranked": None})
    assert {g.keyword: g.gap_type for g in analysis.gaps} == {
        "absent": "missing", "unranked": "missing"
    }
    assert analysis.common_keywords == 0  # an unranked term is NOT overlap


def test_analyze_gaps_matches_keywords_case_insensitively() -> None:
    """The two vendors do not agree on casing, so a client position keyed 'Dental
    Implants' must still answer the provider's 'dental implants' - otherwise every
    term the client actually ranks for reads as a pure gap."""
    analysis = analyze_gaps([_Ranked("Dental Implants", position=9, volume=10)], {"dental implants": 3})
    assert analysis.gaps[0].gap_type == "shared"
    assert analysis.gaps[0].client_position == 3


def test_analyze_gaps_folds_a_duplicate_provider_row() -> None:
    """One verdict per keyword even when the provider lists a term twice (a domain with
    two stacked results); a second row would double-count the gap total."""
    analysis = analyze_gaps(
        [_Ranked("seo", position=3, volume=10), _Ranked("seo", position=7, volume=10)], {}
    )
    assert len(analysis.gaps) == 1
    assert analysis.gaps[0].competitor_position == 3  # the first (best) hit wins


def test_analyze_gaps_ignores_blank_keywords() -> None:
    analysis = analyze_gaps([_Ranked("  ", position=3), _Ranked("real", position=3)], {})
    assert [g.keyword for g in analysis.gaps] == ["real"]


def test_an_empty_ranked_set_is_an_honest_zero_not_a_crash() -> None:
    analysis = analyze_gaps([], {"ours": 3})
    assert analysis.gaps == []
    assert analysis.keyword_gaps_count == 0
    assert analysis.common_keywords == 0
    assert analysis.overlap_pct == 0.0


# --------------------------------------------------------------------------- #
# 3. Jaccard overlap.
# --------------------------------------------------------------------------- #
def test_overlap_is_a_jaccard_over_the_two_ranked_sets() -> None:
    # {a,b,c} & {b,c,d} = 2 ; union = {a,b,c,d} = 4 -> 50%
    assert jaccard_overlap({"a", "b", "c"}, {"b", "c", "d"}) == 50.0


def test_overlap_is_symmetric() -> None:
    """Symmetry is the whole reason this is a Jaccard and not a coverage ratio: it
    answers "do these two compete", which cannot depend on argument order."""
    a, b = {"x", "y", "z"}, {"y"}
    assert jaccard_overlap(a, b) == jaccard_overlap(b, a)


def test_a_no_overlap_competitor_scores_zero_rather_than_being_hidden() -> None:
    """A rival that contests nothing is a REAL answer to "who do we compete with" - it
    renders at 0%, it does not vanish. An empty union is 0.0 too: no evidence either
    way is not perfect competition, and it must never be a ZeroDivisionError."""
    assert jaccard_overlap({"a"}, {"b"}) == 0.0
    assert jaccard_overlap(set(), set()) == 0.0
    assert jaccard_overlap({"a"}, set()) == 0.0


def test_identical_sets_are_total_overlap() -> None:
    assert jaccard_overlap({"a", "b"}, {"a", "b"}) == 100.0


def test_analyze_gaps_overlap_counts_only_the_clients_ranked_terms() -> None:
    """An unranked tracked keyword is not part of the client's visibility, so counting
    it as overlap would credit them for a term they do not hold."""
    ranked = [_Ranked("shared term", position=3), _Ranked("their term", position=3)]
    # The client ranks for 'shared term' and 'ours'; 'unranked' is tracked but absent.
    analysis = analyze_gaps(ranked, {"shared term": 4, "ours": 2, "unranked": None})
    # Rc = {shared term, their term}; Rk = {shared term, ours} -> 1/3 = 33.33%
    assert analysis.overlap_pct == 33.33


# --------------------------------------------------------------------------- #
# 4. Opportunity - REUSED, never a second formula.
# --------------------------------------------------------------------------- #
def test_gap_opportunity_reuses_the_keyword_research_formula() -> None:
    """"How good is this keyword" is ONE question. Two divergent answers on two screens
    is how a platform loses a user's trust in both - so this must literally be
    keyword_research's own scorer, not a lookalike."""
    from app.modules.keyword_research.service import opportunity_score

    assert gap_opportunity(5_000, 40.0, "missing") == opportunity_score(5_000, 40.0, 1.0)
    assert gap_opportunity(5_000, 40.0, "weak") == opportunity_score(5_000, 40.0, 0.6)
    assert gap_opportunity(5_000, 40.0, "shared") == opportunity_score(5_000, 40.0, 0.3)


def test_a_pure_gap_outscores_the_same_keyword_already_shared() -> None:
    """Same demand, same difficulty - the difference is how much is left to win."""
    assert gap_opportunity(5_000, 40.0, "missing") > gap_opportunity(5_000, 40.0, "weak")
    assert gap_opportunity(5_000, 40.0, "weak") > gap_opportunity(5_000, 40.0, "shared")


def test_an_unknown_gap_type_scores_conservatively_rather_than_crashing() -> None:
    assert gap_opportunity(5_000, 40.0, "nonsense") == gap_opportunity(5_000, 40.0, "shared")


# --------------------------------------------------------------------------- #
# 5. Share of voice + the CTR curve.
# --------------------------------------------------------------------------- #
def test_the_ctr_curve_is_the_named_module_constant() -> None:
    """The curve is a NAMED constant, not a literal buried in the maths - so ops can
    re-fit it per vertical and every SoV number stays reproducible."""
    assert ctr_for_position(1) == DEFAULT_CTR_CURVE[0]
    assert ctr_for_position(10) == DEFAULT_CTR_CURVE[9]
    assert DEFAULT_CTR_CURVE[0] > DEFAULT_CTR_CURVE[1] > DEFAULT_CTR_CURVE[9]


def test_the_ctr_curve_is_config_driven_not_hard_wired() -> None:
    """Passing a different curve must actually change the answer - otherwise the
    "config-overridable" claim is decoration."""
    flat = (0.5, 0.5, 0.5)
    assert ctr_for_position(1, flat) == 0.5
    assert ctr_for_position(3, flat) == 0.5
    assert ctr_for_position(1, flat) != ctr_for_position(1, DEFAULT_CTR_CURVE)


def test_ctr_decays_past_the_curve_rather_than_cutting_to_zero_or_holding_flat() -> None:
    """Page 2 is worth LESS than page 1 but more than nothing; position 90 is worth
    less than position 11. Both alternatives (a hard 0, or a flat tail) are wrong."""
    tail_11 = ctr_for_position(11)
    tail_12 = ctr_for_position(12)
    assert 0 < tail_11 < DEFAULT_CTR_CURVE[-1]
    assert 0 < tail_12 < tail_11


def test_an_unranked_or_nonsense_position_earns_no_visibility() -> None:
    assert ctr_for_position(None) == 0.0
    assert ctr_for_position(0) == 0.0
    assert ctr_for_position(-3) == 0.0


def test_visibility_is_volume_times_ctr_over_the_ranked_terms() -> None:
    positions: dict[str, int | None] = {"a": 1, "b": 2, "unranked": None}
    volumes = {"a": 1_000, "b": 1_000, "unranked": 99_999}
    expected = 1_000 * DEFAULT_CTR_CURVE[0] + 1_000 * DEFAULT_CTR_CURVE[1]
    assert visibility_score(positions, volumes) == pytest.approx(expected)


def test_an_unranked_term_contributes_nothing_however_big_its_volume() -> None:
    """The 99,999-volume unranked term above must not leak into the sum: you earn no
    clicks from a term you do not rank for."""
    assert visibility_score({"unranked": None}, {"unranked": 99_999}) == 0.0


def test_share_of_voice_splits_the_measured_market() -> None:
    shares = share_of_voice({"client.com": 75.0, "rival.com": 25.0})
    assert shares == {"client.com": 75.0, "rival.com": 25.0}
    assert sum(shares.values()) == pytest.approx(100.0)


def test_share_of_voice_denominator_is_only_the_domains_measured() -> None:
    """Adding a third domain re-slices the SAME pie - this is share of the voice we
    MEASURE, not of the whole internet, and the test pins that scope."""
    two = share_of_voice({"a": 50.0, "b": 50.0})
    three = share_of_voice({"a": 50.0, "b": 50.0, "c": 100.0})
    assert two["a"] == 50.0
    assert three["a"] == 25.0


def test_an_all_zero_market_is_zero_for_everyone_not_an_even_split() -> None:
    """No visibility anywhere is not "everyone holds 50%" - and it must not be a
    ZeroDivisionError either."""
    assert share_of_voice({"a": 0.0, "b": 0.0}) == {"a": 0.0, "b": 0.0}


def test_share_of_voice_of_an_empty_market_is_empty() -> None:
    assert share_of_voice({}) == {}


# --------------------------------------------------------------------------- #
# 6. Domain normalisation - one competitor, one bill.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw",
    [
        "brightsmile.com",
        "www.brightsmile.com",
        "BrightSmile.com",
        "  BrightSmile.COM  ",
        "https://brightsmile.com",
        "https://www.brightsmile.com/services?x=1",
        "http://brightsmile.com:8080/x",
    ],
)
def test_every_spelling_of_a_domain_folds_to_one_competitor(raw: str) -> None:
    """0036's ``normalize_keyword`` lesson applied to a domain: without folding, these
    are seven competitor rows, seven analyses and seven BILLS for one rival."""
    assert normalize_domain(raw) == "brightsmile.com"


def test_a_subdomain_is_not_folded_away() -> None:
    """A subdomain can be a genuinely different property; folding it into the apex
    would silently merge two competitors' analyses."""
    assert normalize_domain("blog.brightsmile.com") == "blog.brightsmile.com"


def test_an_unusable_domain_normalises_to_empty_never_a_wildcard() -> None:
    assert normalize_domain("") == ""
    assert normalize_domain("   ") == ""


# --------------------------------------------------------------------------- #
# 7. Auto-discovery.
# --------------------------------------------------------------------------- #
def _serp(keyword: str, volume: int, *urls: str) -> tuple[str, int, list[str]]:
    return (keyword, volume, list(urls))


def test_discovery_ranks_by_frequency_times_volume() -> None:
    """Neither signal alone is a competitor: appearances alone crowns a site shadowing
    the client across worthless long-tail; volume alone crowns a one-hit wonder on the
    single biggest term. The product demands both."""
    serps = [
        _serp("big term", 10_000, "https://everywhere.com/a", "https://onehit.com/a"),
        _serp("small term", 10, "https://everywhere.com/b"),
        _serp("other term", 10, "https://everywhere.com/c"),
    ]
    found = discover_competitors(
        serps, client_domain="client.com", existing_domains=set(), min_appearances=2
    )
    # everywhere.com: 3 appearances x 10,020 volume = 30,060. onehit.com appears once,
    # so it is below the noise floor and never proposed at all.
    assert [c.domain for c in found] == ["everywhere.com"]
    assert found[0].appearances == 3
    assert found[0].volume == 10_020
    assert found[0].score == 3 * 10_020


def test_discovery_excludes_the_clients_own_domain() -> None:
    """A client is not their own competitor - including subdomains of their own site."""
    serps = [
        _serp("t1", 100, "https://client.com/a", "https://rival.com/a"),
        _serp("t2", 100, "https://blog.client.com/b", "https://rival.com/b"),
    ]
    found = discover_competitors(
        serps, client_domain="client.com", existing_domains=set(), min_appearances=2
    )
    assert [c.domain for c in found] == ["rival.com"]


def test_discovery_excludes_domains_an_analyst_already_ruled_on() -> None:
    """``existing_domains`` carries EVERY known competitor including the PARKED ones -
    excluding only the tracked ones would resurrect a parked rival every single run."""
    serps = [
        _serp("t1", 100, "https://known.com/a", "https://fresh.com/a"),
        _serp("t2", 100, "https://known.com/b", "https://fresh.com/b"),
    ]
    found = discover_competitors(
        serps,
        client_domain="client.com",
        existing_domains={"known.com"},
        min_appearances=2,
    )
    assert [c.domain for c in found] == ["fresh.com"]


def test_discovery_credits_a_domain_once_per_serp_however_many_results_it_holds() -> None:
    """A rival with three results on one SERP dominates that term - but it is still ONE
    term of evidence. Counting it three times would let a single stacked SERP invent a
    competitor out of thin air."""
    serps = [
        _serp("t1", 100, "https://stacked.com/a", "https://stacked.com/b", "https://stacked.com/c"),
    ]
    found = discover_competitors(
        serps, client_domain="client.com", existing_domains=set(), min_appearances=1
    )
    assert found[0].appearances == 1


def test_discovery_applies_the_noise_floor() -> None:
    """A single co-appearance is noise (a directory, a news story, one lucky long-tail),
    so it is not proposed."""
    serps = [_serp("t1", 100, "https://once.com/a")]
    assert discover_competitors(
        serps, client_domain="client.com", existing_domains=set(), min_appearances=2
    ) == []


def test_discovery_is_bounded_and_stably_ordered() -> None:
    """A re-run must propose the same set in the same order rather than shuffling the
    board (ties break on the domain name)."""
    serps = [
        _serp("t1", 100, "https://a.com/1", "https://b.com/1", "https://c.com/1"),
        _serp("t2", 100, "https://a.com/2", "https://b.com/2", "https://c.com/2"),
    ]
    kwargs = {"client_domain": "client.com", "existing_domains": set(), "min_appearances": 2}
    found = discover_competitors(serps, limit=2, **kwargs)  # type: ignore[arg-type]
    assert [c.domain for c in found] == ["a.com", "b.com"]
    assert found == discover_competitors(serps, limit=2, **kwargs)  # type: ignore[arg-type]


def test_discovery_of_an_empty_serp_set_is_empty() -> None:
    assert discover_competitors([], client_domain="client.com", existing_domains=set()) == []


# --------------------------------------------------------------------------- #
# 8. The workspace adapter.
# --------------------------------------------------------------------------- #
def _stats(**over: object) -> CompetitorStats:
    row = {"tracked": 18, "keyword_gaps": 92, "share_of_voice": 41.0}
    row.update(over)  # type: ignore[arg-type]
    return CompetitorStats.from_row(row)


def test_workspace_cols_are_the_pinned_contract() -> None:
    assert WORKSPACE_TABLE_COLS == ["Competitor", "Client", "Keyword gaps", "Overlap"]


def test_workspace_renders_the_board() -> None:
    extra = build_workspace(
        _stats(),
        [{"domain": "rival.com", "client_name": "NorthPeak", "keyword_gaps_count": 24,
          "overlap_pct": 38.0}],
    )
    assert [k.label for k in extra.kpis] == [
        "Competitors tracked", "Keyword gaps", "Share of voice"
    ]
    assert [k.value for k in extra.kpis] == ["18", "92", "41%"]
    assert extra.table is not None
    assert extra.table.cols == WORKSPACE_TABLE_COLS
    assert extra.table.rows[0][:3] == ["rival.com", "NorthPeak", "24"]


def test_workspace_never_invents_a_kpi_delta() -> None:
    """No historical share-of-voice baseline is stored, so a delta here would be
    fabricated - and a made-up "up 4%" is a trend the agency answers to its client for."""
    extra = build_workspace(_stats(), [])
    assert all(k.delta is None and k.dir is None for k in extra.kpis)


def test_a_zero_overlap_competitor_still_renders() -> None:
    """The read-side twin of the Jaccard test: a non-competing rival appears on the
    board at 0%, muted. Hiding it would answer "who do we compete with" by omission."""
    extra = build_workspace(
        _stats(),
        [{"domain": "unrelated.com", "client_name": "NorthPeak", "keyword_gaps_count": 0,
          "overlap_pct": 0.0}],
    )
    assert extra.table is not None
    assert len(extra.table.rows) == 1
    # A ToolCellObj at this layer; it serialises to {"v", "tone"} at the route edge
    # (which tests/test_tool_workspace_contract.py pins on the wire).
    assert extra.table.rows[0][3] == ToolCellObj(v="0%", tone="mut")


def test_workspace_row_is_bounded() -> None:
    rows = [
        {"domain": f"r{i}.com", "client_name": "C", "keyword_gaps_count": i, "overlap_pct": 50.0}
        for i in range(20)
    ]
    extra = build_workspace(_stats(), rows)
    assert extra.table is not None
    assert len(extra.table.rows) == 8
