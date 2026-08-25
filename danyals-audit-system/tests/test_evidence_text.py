"""What a client is allowed to read.

Every case below is real output that shipped, or the shape that produced it.
The rule the module enforces: say something true and useful, or say nothing.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from audit_engine.evidence_text import (
    BOOL_PHRASING,
    INTERNAL_KEYS,
    evidence_is_client_safe,
    humanise_evidence,
)

# --- the three shapes we refuse ---------------------------------------------

def test_a_nested_dict_is_never_rendered():
    """Real shipped output: "status_breakdown: {'fail': 34, 'warn': 36, ...}"."""
    out = humanise_evidence(
        {"inputs_declared": 24, "verdicts_counted": 93,
         "status_breakdown": {"fail": 34, "warn": 36, "pass": 23}}
    )
    assert out == ""
    assert evidence_is_client_safe(out)


def test_a_module_path_is_never_rendered():
    """Real shipped output: the string "scorers.aggregator" in a column headed
    Evidence."""
    assert humanise_evidence({"weighting": "scorers.aggregator"}) == ""
    assert humanise_evidence({"detail": "app.services.audit_rollups"}) == ""


def test_a_bare_boolean_with_no_phrasing_is_dropped():
    """Real shipped output: "element_identified: False", which tells a client
    nothing at all."""
    assert humanise_evidence({"element_identified": False}) == ""
    assert humanise_evidence({"some_new_flag": True}) == ""


def test_a_boolean_with_phrasing_becomes_a_finding():
    assert humanise_evidence({"has_etag": False}) == "sends no ETag"
    assert humanise_evidence({"covers_host": False}).startswith("the certificate does NOT")


# --- the contradiction ------------------------------------------------------

def test_a_value_we_did_not_record_is_dropped_not_called_not_captured():
    """The TECH-053 contradiction: the card said "cache_control: not captured"
    while the fix beneath it said "No Cache-Control, Expires, ETag or
    Last-Modified". A value we did not record is not a finding about the site."""
    out = humanise_evidence(
        {"cache_control": None, "max_age_seconds": None, "expires": None,
         "has_etag": False, "has_last_modified": False}
    )
    assert "not captured" not in out
    assert "None" not in out
    assert out == "sends no ETag; sends no Last-Modified"


def test_nothing_worth_saying_returns_empty_not_a_stub_sentence():
    """Callers omit the clause. Printing an empty observation is how
    "Observed: ." reached a report."""
    assert humanise_evidence({}) == ""
    assert humanise_evidence(None) == ""
    assert humanise_evidence({"inputs_ran": [], "partial_rollup": True}) == ""


# --- real measurements survive ----------------------------------------------

@pytest.mark.parametrize("evidence,expected", [
    ({"response_ms": 5638}, "server response: 5.6s"),
    ({"response_ms": 315}, "server response: 315ms"),
    ({"lcp_ms": 7238.0}, "largest contentful paint: 7.2s"),
    ({"bytes": 363899}, "page weight: 355.4 KB"),
    ({"content_encoding": "gzip"}, "compression gzip"),
    ({"not_found_count": 12}, "pages returning 404: 12"),
    ({"share_thin": 0.42}, "share of pages under the threshold: 42%"),
    ({"cls": 0.0034}, "layout shift score: 0"),
])
def test_a_real_measurement_reads_as_words(evidence, expected):
    assert humanise_evidence(evidence) == expected


def test_several_facts_are_joined_and_bounded():
    out = humanise_evidence(
        {"images_seen": 150, "without_alt": 35, "image_sitemap_present": False,
         "images_per_page": 30},
        limit=3,
    )
    assert out == "images: 150; images with no alt text: 35; has no image sitemap"


def test_a_written_reason_is_preferred_over_reconstructing_one():
    assert humanise_evidence(
        {"reason": "no pages were crawled", "pages_crawled": 0}
    ) == "no pages were crawled"


def test_an_exception_string_is_not_a_reason():
    """`analyzer_error` carries "ValueError: ..." - a crash, not a finding."""
    assert humanise_evidence({"reason": "ValueError: bad input"}) == ""


# --- lists ------------------------------------------------------------------

def test_a_short_list_is_named_and_a_long_one_is_counted():
    assert humanise_evidence({"types": ["Article", "Organization"]}) == \
        "schema types: Article, Organization"
    out = humanise_evidence({"types": [f"Type{i}" for i in range(9)]})
    assert out == "9 schema types"


def test_a_list_of_dicts_is_dropped():
    assert humanise_evidence({"incomplete": [{"type": "Recipe", "missing": ["x"]}]}) == ""


# --- the guard --------------------------------------------------------------

def test_the_safety_predicate_catches_each_refused_shape():
    assert not evidence_is_client_safe("Observed: {'fail': 3}")
    assert not evidence_is_client_safe("app.services.audit_rollups")
    assert not evidence_is_client_safe("covers_host: False")
    assert evidence_is_client_safe("server response: 5.6s; compression gzip")


def test_every_real_evidence_blob_on_disk_renders_safely():
    """The load-bearing sweep: every evidence dict from every recorded run.

    A unit test over invented dicts proves the rules; this proves the rules
    cover what the engine ACTUALLY emits.
    """
    root = pathlib.Path(__file__).resolve().parents[1] / "data" / "audits"
    seen = 0
    for findings in root.glob("*/*/findings.json"):
        try:
            rows = json.loads(findings.read_text())
        except (ValueError, OSError):  # pragma: no cover - a truncated run
            continue
        rows = rows if isinstance(rows, list) else rows.get("findings", [])
        for row in rows:
            raw = row.get("evidence_json") or row.get("evidence")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw or "{}")
                except ValueError:
                    continue
            if not isinstance(raw, dict):
                continue
            seen += 1
            out = humanise_evidence(raw)
            assert evidence_is_client_safe(out), (
                f"{row.get('check_id')} rendered unsafely: {out!r} from {raw!r}"
            )
    if seen == 0:  # pragma: no cover - a fresh checkout with no recorded runs
        pytest.skip("no recorded runs on disk to sweep")
    assert seen > 100, f"only {seen} evidence blobs swept; the sweep is too thin to trust"


def test_the_internal_key_list_covers_the_provenance_keys_rollups_emit():
    for key in ("inputs_ran", "inputs_missing", "partial_rollup", "weighting",
                "verdicts_counted", "status_breakdown", "analyzer_error",
                "threshold_basis", "operator_note"):
        assert key in INTERNAL_KEYS


def test_every_bool_phrasing_reads_as_a_statement_not_a_field_name():
    for key, (yes, no) in BOOL_PHRASING.items():
        assert "_" not in yes and "_" not in no, key
        assert yes != no, key
