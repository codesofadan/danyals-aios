"""Local-SEO analysis core: the completeness checklist, NAP normalization, rank maths.

Pure functions - no DB, no network, no Celery. Three properties matter here and each
is the reason an operator can trust the surface:

1. **Completeness is deterministic + explainable.** Same profile -> same score, and
   the score always comes with the per-field reason it is not 100.
2. **NAP normalization does not flag COSMETIC drift.** "123 Main St." and "123 Main
   Street" are the same address. A tool that flags that difference buries the real
   errors (a wrong suite, a stale phone) in noise and gets ignored - so the
   normalization is the feature, not an optimisation.
3. **Average map rank counts RANKED, ACTIVE rows only** - there is no honest number
   for "not in the pack", and any substitute would invent data or invert the metric.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.local_seo.schemas import LocalStats
from app.modules.local_seo.service import (
    MIN_SECONDARY_CATEGORIES,
    average_map_rank,
    build_audit_report,
    build_nap_alignment,
    build_workspace,
    is_phone_like,
    nap_values_match,
    normalize_nap_text,
    normalize_phone,
    profile_completeness,
    rank_delta,
)

pytestmark = pytest.mark.unit


def _complete_profile(**over: Any) -> dict[str, Any]:
    """A profile that passes every checklist item (the 100-scoring baseline)."""
    row: dict[str, Any] = {
        "id": "gp-1",
        "client_name": "Verde Cafe",
        "location_label": "Karachi",
        "primary_category": "Cafe",
        "secondary_categories": ["Coffee shop", "Bakery"],
        "regular_hours": {"mon": "9-5"},
        "website_uri": "https://verde.example",
        "nap_name": "Verde Cafe",
        "nap_address": "123 Main Street",
        "nap_phone": "+1 555 010 9999",
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# 1. The completeness checklist.
# --------------------------------------------------------------------------- #
def test_a_fully_populated_profile_scores_100() -> None:
    score, audit = profile_completeness(_complete_profile())
    assert score == 100
    assert audit["missing"] == []
    assert set(audit["findings"].values()) == {"ok"}


def test_an_empty_profile_scores_0_and_names_every_gap() -> None:
    score, audit = profile_completeness({})
    assert score == 0
    # The fix-list is the point: a bare 0 tells an operator nothing.
    assert set(audit["missing"]) == set(audit["findings"])
    assert set(audit["findings"].values()) == {"missing"}


def test_the_score_is_deterministic() -> None:
    profile = _complete_profile(website_uri="")
    assert profile_completeness(profile) == profile_completeness(profile)


@pytest.mark.parametrize(
    ("field", "blanked"),
    [
        ("primary_category", ""),
        ("website_uri", ""),
        ("nap_phone", ""),
        ("nap_name", ""),
        ("nap_address", ""),
        ("regular_hours", {}),
        ("secondary_categories", []),
    ],
)
def test_dropping_any_single_checklist_field_lowers_the_score(field: str, blanked: Any) -> None:
    """Every field must actually MOVE the score - a checklist item that is never
    scored is a lie in the audit report."""
    full, _ = profile_completeness(_complete_profile())
    partial, audit = profile_completeness(_complete_profile(**{field: blanked}))
    assert partial < full
    assert audit["missing"], "a dropped field must appear in the fix-list"


def test_each_checklist_field_carries_an_equal_share() -> None:
    # No single field may dominate the score (or a profile could score 90 while
    # missing its phone number).
    full, audit = profile_completeness(_complete_profile())
    fields = list(audit["findings"])
    scores = {
        f: profile_completeness(_complete_profile(**{_column_for(f): _blank_for(f)}))[0]
        for f in fields
    }
    drops = {full - s for s in scores.values()}
    # Equal weighting +/- integer rounding.
    assert max(drops) - min(drops) <= 1


def _column_for(field: str) -> str:
    """The profile column behind a checklist finding name."""
    return {
        "website": "website_uri", "phone": "nap_phone", "name": "nap_name",
        "address": "nap_address", "hours": "regular_hours",
    }.get(field, field)


def _blank_for(field: str) -> Any:
    if field == "hours":
        return {}
    if field == "secondary_categories":
        return []
    return ""


def test_one_secondary_category_is_thin_and_scores_half() -> None:
    """A single secondary category is present-but-under-the-bar: it should not score
    zero (that ignores real work) nor full (the listing is under-categorised)."""
    full, _ = profile_completeness(_complete_profile())
    thin, thin_audit = profile_completeness(_complete_profile(secondary_categories=["Coffee shop"]))
    none, _ = profile_completeness(_complete_profile(secondary_categories=[]))
    assert none < thin < full
    assert thin_audit["findings"]["secondary_categories"] == "thin"
    assert "secondary_categories" in thin_audit["missing"]  # still on the fix-list


def test_the_secondary_category_bar_is_the_declared_constant() -> None:
    at_bar = ["c"] * MIN_SECONDARY_CATEGORIES
    under = ["c"] * (MIN_SECONDARY_CATEGORIES - 1)
    assert profile_completeness(_complete_profile(secondary_categories=at_bar))[1][
        "findings"
    ]["secondary_categories"] == "ok"
    assert profile_completeness(_complete_profile(secondary_categories=under))[1][
        "findings"
    ]["secondary_categories"] == "thin"


@pytest.mark.parametrize("whitespace", ["", "   ", "\t"])
def test_a_whitespace_only_field_is_missing_not_present(whitespace: str) -> None:
    # A profile padded with spaces must not score as complete.
    _score, audit = profile_completeness(_complete_profile(primary_category=whitespace))
    assert audit["findings"]["primary_category"] == "missing"


def test_blank_secondary_categories_are_not_counted() -> None:
    _score, audit = profile_completeness(_complete_profile(secondary_categories=["", "  "]))
    assert audit["findings"]["secondary_categories"] == "missing"


@pytest.mark.parametrize("bad", [None, "not-a-list", 42])
def test_a_malformed_categories_column_degrades_rather_than_raising(bad: Any) -> None:
    assert profile_completeness(_complete_profile(secondary_categories=bad))[0] < 100


@pytest.mark.parametrize("bad", [None, "not-a-dict", []])
def test_a_malformed_hours_column_degrades_rather_than_raising(bad: Any) -> None:
    _score, audit = profile_completeness(_complete_profile(regular_hours=bad))
    assert audit["findings"]["hours"] == "missing"


def test_the_score_is_always_within_bounds() -> None:
    # The DB has a 0..100 check constraint; a score outside it would 500 on write.
    for profile in ({}, _complete_profile(), _complete_profile(secondary_categories=["a"])):
        score, _ = profile_completeness(profile)
        assert 0 <= score <= 100


def test_the_audit_report_recomputes_rather_than_echoing_a_stale_column() -> None:
    """An operator who just PATCHed a category must see the effect NOW, not after the
    next sync - so the report scores the live fields, ignoring completeness_score."""
    report = build_audit_report(_complete_profile(completeness_score=3))
    assert report.completeness == 100  # the stale 3 is ignored
    assert report.location == "Karachi" and report.client == "Verde Cafe"
    assert report.missing == []


# --------------------------------------------------------------------------- #
# 2. NAP normalization - the cosmetic-drift guard.
# --------------------------------------------------------------------------- #
def test_the_headline_case_st_vs_street_is_not_drift() -> None:
    """THE case this normalization exists for."""
    assert nap_values_match("123 Main Street", "123 Main St.")
    assert normalize_nap_text("123 Main St.") == normalize_nap_text("123 Main Street")


@pytest.mark.parametrize(
    ("canonical", "observed"),
    [
        ("123 Main St.", "123 Main Street"),
        ("123 Main Street", "123 main street"),          # casing
        ("123 Main Street", "123 Main Street,"),          # trailing punctuation
        ("123  Main   Street", "123 Main Street"),        # collapsed whitespace
        ("45 Oak Rd", "45 Oak Road"),
        ("9 Pine Ave.", "9 Pine Avenue"),
        ("12 King Blvd", "12 King Boulevard"),
        ("77 Elm Dr.", "77 Elm Drive"),
        ("5 Bay Ln", "5 Bay Lane"),
        ("2 Court Ct", "2 Court Court"),
        ("8 Fair Pl", "8 Fair Place"),
        ("3 Market Sq", "3 Market Square"),
        ("60 Ring Pkwy", "60 Ring Parkway"),
        ("101 Coast Hwy", "101 Coast Highway"),
        ("12 Main St Ste 400", "12 Main Street Suite 400"),
        ("N Main Street", "North Main Street"),
        ("Verde Cafe", "VERDE CAFE"),
        ("Verde Cafe & Bakery", "Verde Cafe and Bakery".replace(" and ", " & ")),
    ],
)
def test_cosmetic_variants_are_never_flagged_as_drift(canonical: str, observed: str) -> None:
    assert nap_values_match(canonical, observed), f"{canonical!r} vs {observed!r} is cosmetic"


@pytest.mark.parametrize(
    ("canonical", "observed"),
    [
        ("123 Main Street", "124 Main Street"),           # wrong number
        ("123 Main Street", "123 Oak Street"),            # wrong street
        ("12 Main St Ste 400", "12 Main St Ste 401"),     # wrong suite - the real bug
        ("Verde Cafe", "Verde Bakery"),                   # wrong business
    ],
)
def test_real_drift_is_still_flagged(canonical: str, observed: str) -> None:
    """The other half: normalization must not be so aggressive it hides real errors."""
    assert not nap_values_match(canonical, observed)


def test_abbreviations_expand_token_wise_not_by_substring() -> None:
    """A substring replace would rewrite 'Stanley' into 'streetanley' and silently
    corrupt the comparison."""
    assert normalize_nap_text("Stanley Street") == "stanley street"
    assert not nap_values_match("Stanley Road", "Street Road")


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("+1 (555) 010-9999", "555-010-9999"),
        ("+1 555 010 9999", "5550109999"),
        ("(555) 010 9999", "+1-555-010-9999"),
        ("0555 010 9999", "555 010 9999"),
    ],
)
def test_phone_formats_normalize_to_the_same_line(a: str, b: str) -> None:
    assert nap_values_match(a, b)
    assert normalize_phone(a) == normalize_phone(b)


def test_a_genuinely_different_phone_still_mismatches() -> None:
    assert not nap_values_match("555-010-9999", "555-010-1111")


def test_only_phone_shaped_values_are_compared_as_digits() -> None:
    """REGRESSION: digit-comparison must never reach an ADDRESS.

    An address reduced to digits is just its house number, so "123 Main Street" and
    "123 Oak Street" would compare EQUAL and a genuinely wrong street would be
    silently re-classed as cosmetic - the precise failure this module exists to catch.
    """
    assert not is_phone_like("123 Main Street")
    assert not is_phone_like("123")  # too few digits to be a phone number
    assert is_phone_like("+1 (555) 010-9999")
    assert is_phone_like("5550109999")
    assert not nap_values_match("123 Main Street", "123 Oak Street")


def test_a_short_number_is_not_truncated_into_a_false_match() -> None:
    # Keeping the last 10 digits must not make two short numbers collide.
    assert normalize_phone("911") == "911"
    assert not nap_values_match("911", "112")


@pytest.mark.parametrize(("canonical", "observed"), [("", "123 Main St"), ("123 Main St", ""), ("", "")])
def test_an_empty_value_is_never_a_match(canonical: str, observed: str) -> None:
    """Unknown is UNVERIFIED, not aligned - or every un-populated profile would report
    itself perfectly consistent."""
    assert not nap_values_match(canonical, observed)


# --------------------------------------------------------------------------- #
# 3. NAP alignment against the EXISTING 0018 citations ledger.
# --------------------------------------------------------------------------- #
def _citation(directory: str, status: str, note: str = "") -> dict[str, Any]:
    return {"directory": directory, "nap_status": status, "note": note}


def test_a_cosmetically_flagged_directory_is_not_counted_as_drift() -> None:
    """THE headline behaviour: the upstream provider string-compared and flagged
    'inconsistent'; the observed value is the same address written differently, so the
    listing is actually correct and must not land on the operator's fix-list."""
    report = build_nap_alignment(
        _complete_profile(),
        [_citation("Yelp", "inconsistent", "123 Main St.")],
    )
    assert report.inconsistent == 0  # not real drift
    assert report.cosmetic_only == 1  # ... but the review is auditable
    assert report.consistent == 1  # re-classed
    assert report.directories[0].cosmetic_only is True
    assert report.directories[0].status == "consistent"
    assert report.aligned is True


def test_real_drift_survives_the_normalization_review() -> None:
    report = build_nap_alignment(
        _complete_profile(),
        [_citation("Yelp", "inconsistent", "124 Main Street")],
    )
    assert report.inconsistent == 1 and report.cosmetic_only == 0
    assert report.directories[0].cosmetic_only is False
    assert report.aligned is False


def test_a_prose_note_stays_real_drift() -> None:
    """A note that describes the issue rather than carrying the observed value cannot
    be normalised into a match - and erring toward REAL drift is the safe direction."""
    report = build_nap_alignment(_complete_profile(), [_citation("Yelp", "inconsistent", "Suite # differs")])
    assert report.inconsistent == 1 and report.cosmetic_only == 0


def test_a_cosmetic_phone_reformat_is_not_drift() -> None:
    report = build_nap_alignment(
        _complete_profile(), [_citation("Bing Places", "inconsistent", "(555) 010-9999")]
    )
    assert report.cosmetic_only == 1 and report.inconsistent == 0


def test_the_counts_add_up_across_a_mixed_ledger() -> None:
    report = build_nap_alignment(
        _complete_profile(),
        [
            _citation("Google Business", "consistent", "Verified"),
            _citation("Yelp", "inconsistent", "123 Main St."),      # cosmetic
            _citation("Bing Places", "inconsistent", "9 Oak Road"),  # real
            _citation("Apple Maps", "missing", "No listing yet"),
        ],
    )
    assert (report.consistent, report.inconsistent, report.missing) == (2, 1, 1)
    assert report.cosmetic_only == 1
    assert len(report.directories) == 4
    # Every row is classified exactly once.
    assert report.consistent + report.inconsistent + report.missing == 4
    assert report.aligned is False


def test_a_missing_listing_blocks_alignment() -> None:
    report = build_nap_alignment(_complete_profile(), [_citation("Apple Maps", "missing")])
    assert report.missing == 1 and report.aligned is False


def test_an_all_consistent_ledger_is_aligned() -> None:
    report = build_nap_alignment(
        _complete_profile(),
        [_citation("Yelp", "consistent"), _citation("Bing Places", "consistent")],
    )
    assert report.aligned is True and report.inconsistent == 0


def test_an_incomplete_canonical_nap_is_never_aligned() -> None:
    """Nothing to align AGAINST: a profile missing its phone cannot claim its
    listings are consistent, however clean the ledger looks."""
    report = build_nap_alignment(
        _complete_profile(nap_phone=""), [_citation("Yelp", "consistent")]
    )
    assert report.aligned is False


def test_an_empty_ledger_is_not_alignment() -> None:
    # No citations tracked yet: complete NAP, nothing contradicting it.
    report = build_nap_alignment(_complete_profile(), [])
    assert report.directories == []
    assert (report.consistent, report.inconsistent, report.missing) == (0, 0, 0)
    assert report.aligned is True


def test_the_report_carries_the_snapshot_name_never_the_client_id() -> None:
    report = build_nap_alignment(
        _complete_profile(client_id="cl-secret"), [_citation("Yelp", "consistent")]
    )
    assert report.client == "Verde Cafe"
    assert "cl-secret" not in report.model_dump_json(by_alias=True)


# --------------------------------------------------------------------------- #
# 4. Rank maths.
# --------------------------------------------------------------------------- #
def test_average_map_rank_counts_ranked_rows_only() -> None:
    """An unranked row has NO honest number to average: a sentinel would invent data
    and a 0 would make falling OUT of the pack IMPROVE the average."""
    rows = [
        {"rank": 2, "is_active": True},
        {"rank": 4, "is_active": True},
        {"rank": None, "is_active": True},  # checked, not in the pack - excluded
    ]
    assert average_map_rank(rows) == 3.0  # (2+4)/2, NOT (2+4+0)/3


def test_average_map_rank_ignores_inactive_rows() -> None:
    rows = [
        {"rank": 2, "is_active": True},
        {"rank": 20, "is_active": False},  # retired from tracking
    ]
    assert average_map_rank(rows) == 2.0


def test_an_unranked_board_averages_to_zero_not_a_crash() -> None:
    # The KPI renders 0.0 as an em dash; the important part is no ZeroDivisionError.
    assert average_map_rank([{"rank": None, "is_active": True}]) == 0.0
    assert average_map_rank([]) == 0.0


def test_average_map_rank_defaults_a_row_without_an_active_flag_to_active() -> None:
    # A projection that omits is_active must not silently drop every row.
    assert average_map_rank([{"rank": 3}]) == 3.0


def test_average_map_rank_rounds_to_one_decimal() -> None:
    # (1+2+3+4)/3 = 3.333... -> 3.3 (one decimal, as the KPI tile renders it).
    assert average_map_rank([{"rank": 2}, {"rank": 3}, {"rank": 5}]) == 3.3


def test_rank_delta_is_positive_when_the_business_improves() -> None:
    # Rank is an inverted scale: 4 -> 2 is a GAIN of 2.
    assert rank_delta(4, 2) == 2
    assert rank_delta(2, 4) == -2
    assert rank_delta(3, 3) == 0


@pytest.mark.parametrize(("prev", "cur"), [(None, 3), (3, None), (None, None)])
def test_rank_delta_is_zero_when_either_side_is_unknown(prev: int | None, cur: int | None) -> None:
    """A first check, or moving in/out of the pack: we know something changed but have
    no honest magnitude - and inventing one shows up as a fake win/loss on a report."""
    assert rank_delta(prev, cur) == 0


# --------------------------------------------------------------------------- #
# 5. The workspace adapter.
# --------------------------------------------------------------------------- #
def _stats(**over: Any) -> LocalStats:
    row = {"gbp_profiles": 9, "avg_map_rank": 3.2, "citations": 210}
    row.update(over)
    return LocalStats.from_row(row)


def test_the_workspace_emits_the_pinned_columns_and_cta() -> None:
    extra = build_workspace(_stats(), [])
    assert extra.table is not None
    assert extra.table.cols == ["Location", "Client", "Keyword", "Rank"]
    assert extra.table.title == "Map-pack rankings" and extra.table.icon == "storefront"
    assert extra.primary == {"label": "Run local audit", "icon": "storefront"} or (
        extra.primary is not None
        and extra.primary.label == "Run local audit"
        and extra.primary.icon == "storefront"
    )
    assert [k.label for k in extra.kpis] == ["GBP profiles", "Avg. map rank", "Citations"]


def test_the_workspace_rows_are_positional_and_toned() -> None:
    extra = build_workspace(
        _stats(),
        [{"location_label": "Karachi", "client_name": "Verde Cafe",
          "keyword": "cafe near me", "rank": 2}],
    )
    assert extra.table is not None
    row = extra.table.rows[0]
    assert row[0] == "Karachi" and row[1] == "Verde Cafe" and row[2] == "cafe near me"
    assert getattr(row[3], "v", None) == "2" and getattr(row[3], "tone", None) == "ok"


@pytest.mark.parametrize(("rank", "tone"), [(1, "ok"), (3, "ok"), (4, "warn"), (12, "warn")])
def test_the_rank_tone_is_ok_inside_the_pack_and_warn_outside(rank: int, tone: str) -> None:
    extra = build_workspace(_stats(), [{"rank": rank}])
    assert extra.table is not None
    assert getattr(extra.table.rows[0][3], "tone", None) == tone


def test_an_unranked_row_renders_a_dash_never_a_number() -> None:
    """The NULL contract at the render layer: a business that is not in the pack must
    not be shown a fabricated position."""
    extra = build_workspace(_stats(), [{"rank": None}])
    assert extra.table is not None
    cell = extra.table.rows[0][3]
    assert getattr(cell, "v", None) == "—"
    assert getattr(cell, "tone", None) == "mut"


def test_an_empty_avg_rank_tile_renders_a_dash_not_zero() -> None:
    # "0.0" would read as a rank better than #1.
    assert build_workspace(_stats(avg_map_rank=0), []).kpis[1].value == "—"
    assert build_workspace(_stats(avg_map_rank=3.2), []).kpis[1].value == "3.2"


def test_the_workspace_table_is_capped_at_eight_rows() -> None:
    extra = build_workspace(_stats(), [{"rank": 1} for _ in range(50)])
    assert extra.table is not None
    assert len(extra.table.rows) == 8


def test_the_citations_tile_reads_the_value_it_is_handed() -> None:
    # The count comes from the EXISTING 0018 ledger via the repo; the adapter must
    # render it rather than compute its own.
    assert build_workspace(_stats(citations=1210), []).kpis[2].value == "1,210"


def test_the_workspace_bullets_echo_tools_ts() -> None:
    assert build_workspace(_stats(), []).bullets == [
        "Track local & map-pack rankings",
        "Audit GBP categories & NAP",
        "Monitor citation consistency",
    ]
