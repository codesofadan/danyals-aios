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
