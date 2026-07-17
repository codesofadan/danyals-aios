"""On-page detectors: each one AT ITS THRESHOLD BOUNDARY, plus the ranking model.

Pure functions only - no DB, no network, no Celery.

WHY THE BOUNDARIES, SPECIFICALLY. A detector that fires "roughly around 60 chars" is
worse than useless: it invents work on compliant pages and lets real problems through.
The band edges are the ONLY places the behaviour changes, so that is where these tests
push - a title of exactly 30 and exactly 60 must be SILENT, 29 and 61 must FIRE. An
off-by-one here is a false finding on every client page in the book, and no other test
in the suite would notice.
"""

from __future__ import annotations

import pytest

from app.modules.on_page.schemas import OnPageStats
from app.modules.on_page.service import (
    CONTENT_SCORE_FLOOR,
    META_MAX_CHARS,
    META_MIN_CHARS,
    READABILITY_MIN_FLESCH,
    THIN_CONTENT_MIN_WORDS,
    TITLE_MAX_CHARS,
    TITLE_MIN_CHARS,
    analyze_parsed_page,
    build_workspace,
    detect_canonical,
    detect_headings,
    detect_images,
    detect_links,
    detect_meta,
    detect_schema,
    detect_title,
    expected_internal_links,
    keyword_density,
    map_audit_findings,
    normalize_url,
    parse_page,
    priority_score,
    quick_win,
    score_page_content,
)

pytestmark = pytest.mark.unit


def _codes(recs: list) -> set[str]:
    return {r.issue_code for r in recs}


def _page(**over):
    """A ParsedPage built from HTML so the parser is exercised too (a hand-built
    dataclass would let a parser regression hide behind a green detector suite)."""
    from app.modules.on_page.service import ParsedPage

    return ParsedPage(**over)


# --------------------------------------------------------------------------- #
# 1. The parser.
# --------------------------------------------------------------------------- #
_FULL_HTML = """
<html><head>
  <title>Invisalign Cost In Austin - What You Will Actually Pay</title>
  <meta name="description" content="A straight answer on Invisalign cost in Austin.">
  <link rel="canonical" href="https://np.example/invisalign-cost">
  <script type="application/ld+json">{"@type":"Article"}</script>
</head><body class="postid-4471">
  <h1>Invisalign cost in Austin</h1>
  <h2>What drives the price</h2>
  <p>Treatment runs about three thousand dollars for most patients here.</p>
  <a href="/services/braces">braces</a>
  <a href="https://other.example/x">elsewhere</a>
  <img src="/a.png" alt="a clear aligner tray">
  <img src="/b.png">
</body></html>
"""


def test_parser_harvests_every_on_page_signal_in_one_pass() -> None:
    page = parse_page(_FULL_HTML, "https://np.example/invisalign-cost")
    assert page.title == "Invisalign Cost In Austin - What You Will Actually Pay"
    assert page.meta_description == "A straight answer on Invisalign cost in Austin."
    assert page.canonical == "https://np.example/invisalign-cost"
    assert [(h.level, h.text) for h in page.headings] == [
        (1, "Invisalign cost in Austin"), (2, "What drives the price")
    ]
    assert page.internal_links == ["/services/braces"]
    assert page.external_links == ["https://other.example/x"]
    assert page.json_ld_raw == ['{"@type":"Article"}']
    assert page.images_total == 2


def test_parser_counts_a_missing_alt_but_not_an_empty_one() -> None:
    """``alt=""`` is the CORRECT markup for a decorative image - flagging it would be
    a false finding on every well-built page."""
    page = parse_page('<img src="a.png" alt=""><img src="b.png">', "https://x.example")
    assert page.images_total == 2
    assert page.images_missing_alt == 1  # only the one with NO alt attribute


def test_parser_keeps_script_and_style_text_out_of_the_body_copy() -> None:
    """Script/style text must never count as prose - it would inflate the word count
    past the thin-content floor and skew every readability + density measure."""
    page = parse_page(
        "<body><script>var x = 1; alert('padding padding padding');</script>"
        "<style>.a{color:red}</style><p>Real words here.</p></body>",
        "https://x.example",
    )
    assert page.body_text == "Real words here."


def test_parser_degrades_on_malformed_html_rather_than_raising() -> None:
    """A broken page is exactly the kind we most need to report on, so a truncated /
    unclosed document must yield a PARTIAL parse, never an exception. (An unclosed
    ``<title>`` correctly yields no title - the tag genuinely never closes, and a
    `title_missing` finding on such a page is the honest verdict.)"""
    page = parse_page(
        '<html><head><title>Half a page</title><meta name="description" content="d">'
        "<body><h1>Unclosed",
        "https://x.example",
    )
    assert page.title == "Half a page"       # what WAS harvestable comes back
    assert page.meta_description == "d"
    assert parse_page("<<<not html at all", "https://x.example").title == ""


# --------------------------------------------------------------------------- #
# 2. Title - the band edges.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("length", [TITLE_MIN_CHARS, 45, TITLE_MAX_CHARS])
def test_title_inside_the_band_is_silent(length: int) -> None:
    title = "kw " + "a" * (length - 3)
    assert len(title) == length
    assert _codes(detect_title(_page(title=title), "kw", "")) == set()


def test_title_one_char_under_the_minimum_fires_short() -> None:
    title = "kw " + "a" * (TITLE_MIN_CHARS - 4)
    assert len(title) == TITLE_MIN_CHARS - 1
    assert "title_short" in _codes(detect_title(_page(title=title), "kw", ""))


def test_title_one_char_over_the_maximum_fires_long() -> None:
    title = "kw " + "a" * (TITLE_MAX_CHARS - 2)
    assert len(title) == TITLE_MAX_CHARS + 1
    recs = detect_title(_page(title=title), "kw", "")
    assert "title_long" in _codes(recs)
    # The proposal must actually FIT the band it is fixing.
    assert len(recs[0].fix_payload["proposed_value"]) <= TITLE_MAX_CHARS


def test_missing_title_is_a_single_high_finding_with_a_usable_proposal() -> None:
    recs = detect_title(_page(title=""), "invisalign cost", "NorthPeak")
    assert [r.issue_code for r in recs] == ["title_missing"]  # not also short/keyword
    assert recs[0].impact == "High"
    assert recs[0].current_value is None  # nothing was there to snapshot
    assert "invisalign cost" in recs[0].fix_payload["proposed_value"]


def test_title_keyword_and_brand_are_detected_independently() -> None:
    codes = _codes(detect_title(_page(title="A" * 40), "invisalign", "NorthPeak"))
    assert codes == {"title_keyword_missing", "title_no_brand"}


def test_title_snapshots_the_live_value_for_the_drift_guard() -> None:
    recs = detect_title(_page(title="Short"), "kw", "")
    assert recs[0].current_value == "Short"


# --------------------------------------------------------------------------- #
# 3. Meta - the band edges.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("length", [META_MIN_CHARS, 140, META_MAX_CHARS])
def test_meta_inside_the_band_is_silent(length: int) -> None:
    assert _codes(detect_meta(_page(meta_description="a" * length), "")) == set()


@pytest.mark.parametrize(
    ("length", "code"),
    [(META_MIN_CHARS - 1, "meta_short"), (META_MAX_CHARS + 1, "meta_long")],
)
def test_meta_one_char_outside_the_band_fires(length: int, code: str) -> None:
    assert code in _codes(detect_meta(_page(meta_description="a" * length), ""))


def test_missing_meta_is_high_and_proposes_one_inside_the_band() -> None:
    page = _page(meta_description="", body_text="Invisalign in Austin. " * 40)
    recs = detect_meta(page, "invisalign")
    assert [r.issue_code for r in recs] == ["meta_missing"]
    assert recs[0].impact == "High"
    assert len(recs[0].fix_payload["proposed_value"]) <= META_MAX_CHARS


def test_meta_duplicate_only_fires_when_an_audit_says_so() -> None:
    """A single-page fetch CANNOT know another page shares the description, so this
    must never self-detect - it arrives from an audit run or not at all."""
    page = _page(meta_description="a" * 140)
    assert _codes(detect_meta(page, "")) == set()
    assert "meta_duplicate" in _codes(detect_meta(page, "", duplicate_of="/other"))


# --------------------------------------------------------------------------- #
# 4. Headings.
# --------------------------------------------------------------------------- #
def _h(*levels: int):
    from app.modules.on_page.service import Heading

    return [Heading(level=level, text=f"h{level} text") for level in levels]


def test_exactly_one_h1_is_silent() -> None:
    assert _codes(detect_headings(_page(headings=_h(1, 2, 3)), "")) == set()


def test_zero_h1s_fires_missing_and_two_fires_multiple() -> None:
    assert "h1_missing" in _codes(detect_headings(_page(headings=_h(2, 3)), ""))
    assert "h1_multiple" in _codes(detect_headings(_page(headings=_h(1, 1)), ""))


def test_hierarchy_skip_fires_only_on_a_descent_of_more_than_one_level() -> None:
    """H2 -> H4 skips H3 and is a finding. Coming back UP (H3 -> H2) is legal and
    ordinary - flagging it would fire on almost every real page."""
    assert "heading_hierarchy_skip" in _codes(detect_headings(_page(headings=_h(1, 2, 4)), ""))
    assert "heading_hierarchy_skip" not in _codes(
        detect_headings(_page(headings=_h(1, 2, 3, 2)), "")
    )


def test_h1_keyword_check_only_runs_when_an_h1_exists() -> None:
    # A missing H1 is already reported; also claiming "the H1 lacks the keyword"
    # would be a second finding about a thing that does not exist.
    codes = _codes(detect_headings(_page(headings=_h(2)), "invisalign"))
    assert codes == {"h1_missing"}


# --------------------------------------------------------------------------- #
# 5. Content: thin / density / readability.
# --------------------------------------------------------------------------- #
def test_thin_content_fires_below_the_floor_and_is_silent_at_it() -> None:
    from app.modules.on_page.service import detect_content

    at_floor = _page(body_text="word " * THIN_CONTENT_MIN_WORDS)
    below = _page(body_text="word " * (THIN_CONTENT_MIN_WORDS - 1))
    assert "thin_content" not in _codes(detect_content(at_floor, ""))
    assert "thin_content" in _codes(detect_content(below, ""))


def test_keyword_density_counts_the_phrase_not_the_words() -> None:
    """"invisalign cost" twice in 100 words = 4/100 tokens, not 2/100: a two-word
    phrase occupies two word slots. Counting hits-over-words would under-report
    stuffing by exactly the phrase length."""
    body = ("invisalign cost " + "filler " * 48) + "invisalign cost "
    assert len(body.split()) == 52
    assert keyword_density(body, "invisalign cost") == pytest.approx(4 / 52)


def test_keyword_density_is_zero_for_an_empty_body_or_keyword() -> None:
    assert keyword_density("", "kw") == 0.0
    assert keyword_density("some words", "") == 0.0


def test_density_bands_fire_high_over_the_ceiling_and_low_under_the_target() -> None:
    from app.modules.on_page.service import detect_content

    stuffed = _page(body_text="kw " * 40 + "filler " * 60)  # ~40% density
    sparse = _page(body_text="kw " + "filler " * 999)       # ~0.1% density
    assert "keyword_density_high" in _codes(detect_content(stuffed, "kw"))
    assert "keyword_density_low" in _codes(detect_content(sparse, "kw"))


def test_readability_fires_below_the_flesch_floor() -> None:
    from app.modules.on_page.service import detect_content, flesch_reading_ease

    dense = _page(
        body_text=(
            "Notwithstanding the aforementioned considerations, the implementation "
            "methodology necessitates comprehensive interdisciplinary evaluation "
            "utilizing sophisticated quantitative instrumentation throughout."
        )
    )
    assert flesch_reading_ease(dense.body_text) < READABILITY_MIN_FLESCH
    assert "readability_low" in _codes(detect_content(dense, ""))


# --------------------------------------------------------------------------- #
# 6. Schema / links / images / canonical.
# --------------------------------------------------------------------------- #
def test_schema_missing_vs_invalid_are_distinguished() -> None:
    assert _codes(detect_schema(_page(json_ld_raw=[]))) == {"schema_missing"}
    assert _codes(detect_schema(_page(json_ld_raw=["{not json"]))) == {"schema_invalid"}
    assert _codes(detect_schema(_page(json_ld_raw=['{"@type":"Article"}']))) == set()


@pytest.mark.parametrize(
    ("words", "expected"), [(0, 0), (200, 1), (1000, 2), (1001, 3), (2000, 4)]
)
def test_expected_internal_links_scales_per_1000_words(words: int, expected: int) -> None:
    assert expected_internal_links(words) == expected


def test_internal_links_fire_only_below_the_expected_count() -> None:
    page = _page(body_text="word " * 1000, internal_links=["/a", "/b"])
    assert _codes(detect_links(page)) == set()
    thin = _page(body_text="word " * 1000, internal_links=["/a"])
    assert "internal_links_few" in _codes(detect_links(thin))


def test_orphan_only_arrives_from_an_audit_run() -> None:
    page = _page(body_text="word " * 100, internal_links=["/a"])
    assert "internal_link_orphan" not in _codes(detect_links(page))
    assert "internal_link_orphan" in _codes(detect_links(page, orphan=True))


def test_image_alt_fires_only_when_an_alt_is_actually_absent() -> None:
    assert _codes(detect_images(_page(images_total=3, images_missing_alt=0))) == set()
    assert _codes(detect_images(_page(images_total=3, images_missing_alt=1))) == {
        "image_alt_missing"
    }


def test_canonical_missing_conflict_and_match() -> None:
    url = "https://np.example/page"
    assert _codes(detect_canonical(_page(url=url, canonical=""))) == {"canonical_missing"}
    assert _codes(detect_canonical(_page(url=url, canonical=url))) == set()
    assert _codes(
        detect_canonical(_page(url=url, canonical="https://np.example/other"))
    ) == {"canonical_conflict"}


def test_canonical_tolerates_cosmetic_url_spelling_differences() -> None:
    """A trailing slash / an uppercase host / a fragment is the SAME page. Reporting a
    conflict for those would be a false High-impact finding on ordinary sites."""
    assert normalize_url("https://NP.example/page/#top") == normalize_url("https://np.example/page")
    assert _codes(
        detect_canonical(_page(url="https://np.example/page", canonical="https://NP.example/page/"))
    ) == set()


# --------------------------------------------------------------------------- #
# 7. Impact x Effort: the ranking + the quick-win flag.
# --------------------------------------------------------------------------- #
def test_priority_ranks_a_cheap_medium_fix_above_an_expensive_high_one() -> None:
    """The whole point of Impact x EFFORT: a High-impact fix that costs a human a day
    must not outrank a Med-impact one-field edit that lands in a click."""
    assert priority_score("Med", "title") > priority_score("High", "manual")


def test_priority_orders_within_the_same_effort_by_impact() -> None:
    assert (
        priority_score("High", "title")
        > priority_score("Med", "title")
        > priority_score("Low", "title")
    )


def test_priority_orders_within_the_same_impact_by_effort() -> None:
    assert (
        priority_score("High", "title")
        > priority_score("High", "heading")
        > priority_score("High", "content")
        > priority_score("High", "manual")
    )


@pytest.mark.parametrize("kind", ["title", "meta", "schema"])
def test_low_effort_auto_applicable_kinds_are_quick_wins(kind: str) -> None:
    assert quick_win("High", kind) is True
    assert quick_win("Med", kind) is True


@pytest.mark.parametrize("kind", ["heading", "content", "manual"])
def test_higher_effort_kinds_are_never_quick_wins(kind: str) -> None:
    assert quick_win("High", kind) is False


def test_a_low_impact_tweak_is_applicable_but_not_a_win() -> None:
    assert quick_win("Low", "title") is False


# --------------------------------------------------------------------------- #
# 8. The content score - and its honest degradation.
# --------------------------------------------------------------------------- #
def _good_page():
    return _page(
        url="https://np.example/p",
        title="Invisalign cost in Austin - a straight answer for patients",
        body_text=("Invisalign cost is fair here. " + "We help patients smile. " * 120),
        headings=_h(1, 2),
    )


def test_score_without_entities_degrades_honestly_and_still_scores() -> None:
    """No Serper key -> no SERP teardown -> no entity list. The score must OMIT that
    dimension, say so, and still return the deterministic ones - never crash, and
    never invent a number for a thing it could not measure."""
    score = score_page_content(_good_page(), "invisalign cost", entities=None)
    assert score.degraded is True
    assert "entity_coverage" not in score.sub_scores
    assert {"keyword_handling", "structure_readability", "depth"} <= set(score.sub_scores)
    assert 0.0 < score.total <= 100.0
    assert any("Serper" in note for note in score.notes)


def test_score_with_entities_includes_coverage_and_is_not_degraded() -> None:
    score = score_page_content(
        _good_page(), "invisalign cost", entities=["Invisalign", "patients"]
    )
    assert score.degraded is False
    assert score.sub_scores["entity_coverage"] == 100.0


def test_score_reuses_the_content_qa_entity_coverage_rubric() -> None:
    """Half the table-stakes entities covered => 50. Pinned so a local re-implementation
    of coverage (instead of reusing content_qa) is caught."""
    score = score_page_content(
        _good_page(), "invisalign cost", entities=["Invisalign", "nowhere-near-this-page"]
    )
    assert score.sub_scores["entity_coverage"] == 50.0


def test_score_never_crashes_on_an_empty_page() -> None:
    score = score_page_content(_page(), "", entities=None)
    assert score.degraded is True
    assert score.total >= 0.0


def test_a_keyword_stuffed_page_is_punished_by_the_content_qa_bands() -> None:
    stuffed = _page(title="kw", body_text="kw " * 100, headings=_h(1))
    assert score_page_content(stuffed, "kw", entities=None).sub_scores["keyword_handling"] == 25.0


# --------------------------------------------------------------------------- #
# 9. The full analysis pass.
# --------------------------------------------------------------------------- #
def test_analyze_is_deterministic_for_the_same_input() -> None:
    page = parse_page(_FULL_HTML, "https://np.example/invisalign-cost")
    first, score_a = analyze_parsed_page(page, "invisalign cost")
    second, score_b = analyze_parsed_page(page, "invisalign cost")
    assert [r.issue_code for r in first] == [r.issue_code for r in second]
    assert score_a.total == score_b.total


def test_analyze_adds_a_content_score_finding_below_the_floor() -> None:
    thin = _page(url="https://x.example/p", title="", body_text="a few words only")
    recs, score = analyze_parsed_page(thin, "invisalign")
    assert score.total < CONTENT_SCORE_FLOOR
    assert "content_score_low" in _codes(recs)


def test_analyze_is_silent_on_content_score_for_a_healthy_page() -> None:
    recs, score = analyze_parsed_page(
        _good_page(), "invisalign cost", entities=["Invisalign", "patients"]
    )
    assert score.total >= CONTENT_SCORE_FLOOR
    assert "content_score_low" not in _codes(recs)


# --------------------------------------------------------------------------- #
# 10. Mapping an audit run's findings (never re-detecting them).
# --------------------------------------------------------------------------- #
def _finding(**over):
    row = {
        "check_id": "ON-041", "check_name": "H1 optimization", "status": "fail",
        "severity": "critical", "remediation": "Add a single keyword-led H1.",
    }
    row.update(over)
    return row


@pytest.mark.parametrize(
    ("severity", "impact"),
    [("critical", "High"), ("major", "High"), ("minor", "Med"), ("info", "Low")],
)
def test_audit_severity_maps_onto_our_impact_bands(severity: str, impact: str) -> None:
    recs = map_audit_findings([_finding(severity=severity)], "https://x.example/p")
    assert recs[0].impact == impact


def test_only_failing_or_warning_checks_become_recommendations() -> None:
    """A passing check is not work to do. Turning one into a recommendation would put
    a phantom task on a lead's board."""
    findings = [
        _finding(check_id="ON-041", status="pass"),
        _finding(check_id="ON-042", status="warn"),
        _finding(check_id="ON-023", status="fail"),
        _finding(check_id="ON-034", status="n_a"),
    ]
    assert _codes(map_audit_findings(findings, "https://x.example/p")) == {
        "h1_multiple", "thin_content"
    }


def test_unmapped_checks_are_skipped_rather_than_guessed_at() -> None:
    assert map_audit_findings([_finding(check_id="ON-999")], "https://x.example/p") == []


def test_findings_for_other_pages_are_skipped() -> None:
    """An analysis is about ONE url; an audit run covers the whole site."""
    findings = [
        _finding(check_id="ON-041", page_url="https://x.example/other"),
        _finding(check_id="ON-042", page_url="https://x.example/p"),
    ]
    assert _codes(map_audit_findings(findings, "https://x.example/p")) == {"h1_multiple"}


def test_mapping_dedupes_and_survives_junk_rows() -> None:
    findings = [_finding(), _finding(), "not a dict", {}]
    recs = map_audit_findings(findings, "https://x.example/p")
    assert [r.issue_code for r in recs] == ["h1_missing"]


def test_mapped_recommendation_prefers_the_engines_remediation_text() -> None:
    recs = map_audit_findings([_finding()], "https://x.example/p")
    assert recs[0].issue == "Add a single keyword-led H1."
    assert recs[0].detail["source"] == "audit"


# --------------------------------------------------------------------------- #
# 11. The workspace adapter.
# --------------------------------------------------------------------------- #
def test_workspace_emits_the_pinned_shape_with_tones() -> None:
    extra = build_workspace(
        OnPageStats(analyzed=214, open=41, applied=178),
        [{"page_url": "/a", "issue": "Missing meta description", "impact": "High",
          "status": "open"}],
    )
    assert [k.label for k in extra.kpis] == ["Pages analyzed", "Open suggestions", "Applied"]
    assert extra.table is not None
    assert extra.table.cols == ["Page", "Issue", "Impact", "Status"]
    row = extra.table.rows[0]
    assert row[2].model_dump() == {"v": "High", "tone": "crit"}  # type: ignore[union-attr]
    assert row[3].model_dump() == {"v": "Open", "tone": "warn"}  # type: ignore[union-attr]


def test_workspace_caps_the_table_at_eight_rows() -> None:
    rows = [{"page_url": f"/p{i}", "issue": "x", "impact": "Low", "status": "open"}
            for i in range(30)]
    extra = build_workspace(OnPageStats(analyzed=1, open=30, applied=0), rows)
    assert extra.table is not None
    assert len(extra.table.rows) == 8
