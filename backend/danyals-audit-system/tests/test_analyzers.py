"""Analyzer regression tests against golden HTML fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from audit_engine.analyzers.onpage import (
    check_h1_optimization,
    check_image_alt_text,
    check_indexability,
    check_meta_description,
    check_schema_validation,
    check_thin_content,
    check_title_tag,
    check_viewport,
)
from audit_engine.parsers import html as html_parser

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def clean_parsed():
    raw = (FIXTURES / "clean.html").read_text(encoding="utf-8")
    return html_parser.parse(raw, "https://acmeplumbing.test/")


@pytest.fixture
def thin_parsed():
    raw = (FIXTURES / "thin.html").read_text(encoding="utf-8")
    return html_parser.parse(raw, "https://example.test/")


@pytest.fixture
def broken_schema_parsed():
    raw = (FIXTURES / "broken-schema.html").read_text(encoding="utf-8")
    return html_parser.parse(raw, "https://example.test/")


def test_clean_title_passes(clean_parsed):
    v = check_title_tag(clean_parsed)
    assert v.status == "pass"
    assert v.score == 10.0


def test_clean_meta_description_passes(clean_parsed):
    v = check_meta_description(clean_parsed)
    assert v.status in ("pass", "warn")
    # Fixture's description is 180 chars - inside hard_max but above ideal_max.
    # Acceptable warn band: score >= 6.
    assert v.score >= 6.0


def test_clean_h1_single(clean_parsed):
    v = check_h1_optimization(clean_parsed)
    assert v.status == "pass"


def test_clean_thin_content_passes(clean_parsed):
    # Fixture content is intentionally compact; use a 150-word threshold for the test
    # so the analyzer's logic (not the fixture length) is what's under test.
    v = check_thin_content(clean_parsed, threshold=150)
    assert v.status == "pass"


def test_clean_image_alt_passes(clean_parsed):
    v = check_image_alt_text(clean_parsed)
    assert v.status == "pass"


def test_clean_viewport_passes(clean_parsed):
    v = check_viewport(clean_parsed)
    assert v.status == "pass"


def test_clean_schema_passes(clean_parsed):
    v = check_schema_validation(clean_parsed)
    assert v.status == "pass"


def test_thin_multiple_h1_fails(thin_parsed):
    v = check_h1_optimization(thin_parsed)
    assert v.status == "fail"
    assert v.severity == "major"


def test_thin_content_fails(thin_parsed):
    v = check_thin_content(thin_parsed)
    assert v.status == "fail"
    assert v.severity == "critical"


def test_thin_missing_alt(thin_parsed):
    v = check_image_alt_text(thin_parsed)
    assert v.status in ("fail", "warn")
    assert v.evidence["missing_alt"] >= 1


def test_thin_missing_viewport(thin_parsed):
    v = check_viewport(thin_parsed)
    assert v.status == "fail"


def test_broken_schema_fails(broken_schema_parsed):
    v = check_schema_validation(broken_schema_parsed)
    assert v.status in ("warn", "fail")
    assert v.evidence["errors_total"] >= 1


def test_indexability_default_pass(clean_parsed):
    v = check_indexability(clean_parsed)
    assert v.status == "pass"


# --------------------------------------------------------------------------
# ON-027 Expertise signal detection.
#
# This counted DIGIT CHARACTERS anywhere in the body and scored
# min(10, digits * 0.2 + citations * 2). Fifty digits - a phone number, a price
# list, opening hours - was a perfect expertise score with no citation of any
# kind. On a local business site that is close to guaranteed, so the check
# reported "expertise" for having a contact block.
# --------------------------------------------------------------------------

def _page(body: str, external: tuple[str, ...] = ()) -> object:
    from types import SimpleNamespace

    return SimpleNamespace(
        body_text=body,
        links=[SimpleNamespace(href=h, is_internal=False) for h in external],
    )


def test_a_phone_number_and_an_address_are_not_expertise():
    """The exact false positive: digits from a contact block scored full marks."""
    from audit_engine.analyzers.onpage import check_expertise_signals

    v = check_expertise_signals(
        _page("Call 0331 1234567. Open 9-5. Suite 12, 45 Main Road, Lahore 54000.")
    )
    assert v.status == "warn"
    assert v.evidence["statistics"] == 0
    assert v.evidence["citations"] == 0


def test_a_figure_carrying_a_unit_counts_as_a_statistic():
    from audit_engine.analyzers.onpage import check_expertise_signals

    v = check_expertise_signals(
        _page("Implants succeed in 98% of cases. Treatment takes 6 months. "
              "1 in 4 adults delay care. Fees start at £1,200.")
    )
    assert v.evidence["statistics"] >= 4


def test_an_authoritative_citation_is_recognised():
    from audit_engine.analyzers.onpage import check_expertise_signals

    v = check_expertise_signals(
        _page("Evidence shows 40% improvement.",
              ("https://www.nih.gov/study", "https://example.com/blog"))
    )
    assert v.evidence["citations"] == 1
    assert v.evidence["external_links"] == 2


def test_neither_signal_alone_can_carry_the_score():
    """A wall of numbers with no sources, and a wall of sources with no
    specifics, are each half the signal."""
    from audit_engine.analyzers.onpage import check_expertise_signals

    stats_only = check_expertise_signals(_page("5% 10% 15% 20% 25% 30% 35% 40%"))
    cites_only = check_expertise_signals(
        _page("No figures here.", tuple(f"https://nih.gov/{i}" for i in range(8)))
    )
    assert stats_only.score <= 6.0
    assert cites_only.score <= 6.0


def test_a_page_that_evidences_its_claims_passes():
    from audit_engine.analyzers.onpage import check_expertise_signals

    v = check_expertise_signals(
        _page("Success is 98% at 5 years. Recovery takes 6 weeks. Cost is £1,200. "
              "Around 1 in 4 patients need a graft. Healing spans 12 weeks.",
              ("https://www.nih.gov/a", "https://pubmed.ncbi.nlm.nih.gov/b")),
    )
    assert v.status == "pass"


def test_the_remediation_names_what_was_actually_counted():
    from audit_engine.analyzers.onpage import check_expertise_signals

    v = check_expertise_signals(_page("Treatment takes 6 months."))
    assert "1 specific figures" in v.remediation or "figures" in v.remediation
