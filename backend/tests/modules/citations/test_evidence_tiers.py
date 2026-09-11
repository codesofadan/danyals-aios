"""Evidence-tiered citation audit (0129): the pure tier rule and the gap buckets.

The one sentence this file defends: ABSENCE OF EVIDENCE IS NEVER PROOF OF ABSENCE.
`no_evidence` is a *candidate* gap (a directory that blocks crawlers still lists
businesses), `uncertain` is a verify-first bucket and never coverage, and only
`confirmed`/`inconsistent_nap` - evidence that a listing actually exists - may cover a
directory out of the build target.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.citations.evidence import evidence_level_for
from app.modules.citations.service import build_audit_plan, compute_citation_gap

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# evidence_level_for: the truth table.
# --------------------------------------------------------------------------- #
def test_fetched_nap_match_is_confirmed() -> None:
    assert (
        evidence_level_for(url_found=True, nap_matched=True, page_fetched=True, hit_found=True)
        == "confirmed"
    )


def test_two_independent_sources_confirm_without_a_fetch() -> None:
    assert (
        evidence_level_for(
            url_found=True, nap_matched=True, page_fetched=False,
            independent_sources=2, hit_found=True,
        )
        == "confirmed"
    )


def test_one_unfetched_source_is_uncertain_even_when_nap_looks_right() -> None:
    """A single snippet agreeing with the NAP is a hint, not a fact."""
    assert (
        evidence_level_for(
            url_found=True, nap_matched=True, page_fetched=False,
            independent_sources=1, hit_found=True,
        )
        == "uncertain"
    )


def test_nap_drift_is_inconsistent_nap_regardless_of_corroboration() -> None:
    # Drift judged from a fetch...
    assert (
        evidence_level_for(url_found=True, nap_matched=False, page_fetched=True, hit_found=True)
        == "inconsistent_nap"
    )
    # ...and drift judged from the source's own NAP fields: corroboration count can
    # never talk a drifted listing back into `confirmed`.
    assert (
        evidence_level_for(
            url_found=True, nap_matched=False, page_fetched=False,
            independent_sources=5, hit_found=True,
        )
        == "inconsistent_nap"
    )


def test_an_unjudged_hit_is_uncertain_never_confirmed() -> None:
    """``nap_matched=None`` means no judgement was possible - it must not be treated
    as a match however many sources or fetches exist."""
    assert (
        evidence_level_for(url_found=True, nap_matched=None, page_fetched=True, hit_found=True)
        == "uncertain"
    )


def test_a_hit_without_a_url_is_uncertain() -> None:
    assert evidence_level_for(url_found=False, hit_found=True) == "uncertain"


def test_zero_hits_is_no_evidence_and_absence_is_not_proof() -> None:
    """`no_evidence` requires ZERO hits across ALL sources - and it is a tier, not a
    fact: the vocabulary deliberately has no 'absent'/'proven missing' value, because
    the sources cannot prove a negative."""
    assert evidence_level_for(url_found=False, hit_found=False) == "no_evidence"
    # The whole closed vocabulary - nothing in it asserts proven absence.
    levels = {
        evidence_level_for(
            url_found=u, nap_matched=m, page_fetched=f, independent_sources=s, hit_found=h
        )
        for u in (True, False)
        for m in (True, False, None)
        for f in (True, False)
        for s in (0, 1, 2)
        for h in (True, False)
    }
    assert levels == {"confirmed", "inconsistent_nap", "uncertain", "no_evidence"}


# --------------------------------------------------------------------------- #
# Gap buckets: no_evidence -> gap, uncertain -> verifyFirst, confirmed -> covered.
# --------------------------------------------------------------------------- #
def _dir(did: str, name: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": did, "name": name, "url": f"https://{name.lower().replace(' ', '')}.example",
        "market": "US", "tier": "bot_fillable", "submit_method": "bot:playwright",
        "link_rel": "dofollow", "price_note": "", "automation_note": "", "active": True,
        "authority": 60, "authority_tier": "core", "access": "open",
        "is_marketplace": False, "verticals": [],
    }
    row.update(over)
    return row


def _citation(directory: str, did: str | None, level: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": f"c-{directory.lower().replace(' ', '-')}",
        "directory": directory,
        "directory_id": did,
        "submit_status": "not_started",
        "nap_status": {"confirmed": "consistent", "inconsistent_nap": "inconsistent",
                       "uncertain": "consistent", "no_evidence": "missing"}.get(level, "missing"),
        "evidence_level": level,
        "discovered_url": "" if level == "no_evidence" else f"https://{directory.lower()}.example/biz/1",
        "proof_url": "",
    }
    row.update(over)
    return row


_DIRECTORIES = [
    _dir("d1", "Yelp"),
    _dir("d2", "Bing Places"),
    _dir("d3", "Hotfrog"),
    _dir("d4", "Brownbook"),
]


def test_gap_buckets_by_evidence_tier() -> None:
    existing = [
        _citation("Yelp", "d1", "confirmed"),           # covered
        _citation("Bing Places", "d2", "inconsistent_nap"),  # exists w/ drift -> covered
        _citation("Hotfrog", "d3", "uncertain"),        # verify first - neither bucket
        _citation("Brownbook", "d4", "no_evidence"),    # a candidate GAP
    ]
    gap = compute_citation_gap(directories=_DIRECTORIES, existing_citations=existing)

    assert gap.covered_count == 2
    # `no_evidence` is a gap - the directory stays a build target.
    assert {d["name"] for d in gap.missing} == {"Brownbook"}
    # `uncertain` is its own bucket: deduped from missing, never counted covered.
    assert [v["directory"] for v in gap.verify_first] == ["Hotfrog"]
    assert gap.verify_first[0]["url"] == "https://hotfrog.example/biz/1"
    assert gap.verify_first[0]["evidence_level"] == "uncertain"
    assert "Hotfrog" not in {d["name"] for d in gap.missing}
    # The tier tallies ride along.
    assert gap.by_evidence_level == {
        "confirmed": 1, "inconsistent_nap": 1, "uncertain": 1, "no_evidence": 1,
    }


def test_pre_tier_rows_keep_the_legacy_nap_rule() -> None:
    """A row written before 0129 (evidence_level = '') must behave exactly as before:
    consistent/inconsistent covers, missing does not."""
    existing = [
        _citation("Yelp", "d1", "", nap_status="consistent"),
        _citation("Brownbook", "d4", "", nap_status="missing"),
    ]
    gap = compute_citation_gap(directories=_DIRECTORIES, existing_citations=existing)
    assert gap.covered_count == 1
    assert {d["name"] for d in gap.missing} == {"Bing Places", "Hotfrog", "Brownbook"}
    assert gap.verify_first == []
    assert gap.by_evidence_level == {}  # '' rows are not a tier


def test_a_done_submission_outranks_a_weak_tier() -> None:
    """A row the SUBMISSION pipeline finished (live) covers its directory whatever the
    discovery tier says - the probe's verdict is stronger evidence than a snippet."""
    existing = [_citation("Yelp", "d1", "uncertain", submit_status="live")]
    gap = compute_citation_gap(directories=_DIRECTORIES, existing_citations=existing)
    assert gap.covered_count == 1
    assert gap.verify_first == []


def test_audit_plan_tags_uncertain_directories_verify_first() -> None:
    existing = [
        _citation("Yelp", "d1", "confirmed"),
        _citation("Hotfrog", "d3", "uncertain"),
        _citation("Brownbook", "d4", "no_evidence"),
    ]
    plan = build_audit_plan(directories=_DIRECTORIES, existing_citations=existing)
    by_name = {row["name"]: row["_status"] for row in plan.generic + plan.country + plan.niche}
    assert by_name["Yelp"] == "built"
    assert by_name["Hotfrog"] == "verify_first"  # never "built" on an unverified hit
    assert by_name["Brownbook"] == "missing"
    assert by_name["Bing Places"] == "missing"
