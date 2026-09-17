"""Local-audit honesty guards (2026-09-17).

Three defects this file pins, each found by audit and each a case of the engine
claiming more than it measured:

1. ``find_place`` accepted the TOP Places text-search hit with no identity check,
   so an ambiguous business name scored a DIFFERENT company's profile as the
   client's - every GBP finding downstream describing the wrong business.
2. Citation "presence" is inferred from two broad Serper queries, yet a directory
   that did not surface was counted as MISSING and penalised as such. Absence of
   evidence was reported to the client as evidence of absence.
3. The ``local`` subcommand printed "Running on-page analyzers (subset)..." over a
   loop whose body had been dropped - it announced work it never did.

Re-inject any of the three and the matching test fails.
"""

from __future__ import annotations

import asyncio
from typing import Any

from audit_engine.analyzers.local import check_citation_consistency
from audit_engine.integrations.citations import CitationStatus, CitationSummary
from audit_engine.integrations.places import Place, PlacesClient, _bare_host


# --------------------------------------------------------------------------- #
# 1. Places identity verification.
# --------------------------------------------------------------------------- #
def _place_payload(name: str, website: str | None) -> dict[str, Any]:
    return {
        "id": f"id-{name}",
        "displayName": {"text": name},
        "formattedAddress": "1 Main St",
        "websiteUri": website,
        "internationalPhoneNumber": "+1 555 0100",
        "primaryType": "plumber",
    }


class _StubResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


def _client_returning(payload: dict[str, Any]) -> PlacesClient:
    client = PlacesClient(api_key="test-key")

    async def _post(*args: Any, **kwargs: Any) -> _StubResponse:
        return _StubResponse(payload)

    client.post = _post  # type: ignore[method-assign]
    return client


def test_the_matching_domain_wins_over_the_top_hit() -> None:
    """The audited domain decides which candidate is the client - not Google's
    ranking. Re-inject by dropping the expected_domain loop and this fails."""
    payload = {
        "places": [
            _place_payload("Ace Plumbing (Chicago)", "https://ace-plumbing-chicago.com"),
            _place_payload("Ace Plumbing", "https://www.aceplumbing.com"),
        ]
    }
    client = _client_returning(payload)
    place = asyncio.run(client.find_place("Ace Plumbing", expected_domain="aceplumbing.com"))

    assert place is not None
    assert place.identity_verified is True
    assert place.website == "https://www.aceplumbing.com"


def test_no_domain_match_returns_a_candidate_but_never_claims_verification() -> None:
    """A candidate is still useful, but it must be flagged so profile findings are
    treated as low-confidence rather than as the client's own GBP."""
    payload = {"places": [_place_payload("Some Other Plumber", "https://elsewhere.com")]}
    client = _client_returning(payload)
    place = asyncio.run(client.find_place("Ace Plumbing", expected_domain="aceplumbing.com"))

    assert place is not None
    assert place.identity_verified is False


def test_identity_defaults_to_unverified() -> None:
    place = Place(
        place_id="x", name="n", formatted_address=None, phone=None,
        website=None, primary_type=None,
    )
    assert place.identity_verified is False


def test_bare_host_normalises_scheme_and_www() -> None:
    assert _bare_host("https://www.Example.com/path?q=1") == "example.com"
    assert _bare_host("example.com") == "example.com"
    assert _bare_host("") == ""


# --------------------------------------------------------------------------- #
# 2. Citations: not_observed is not absence.
# --------------------------------------------------------------------------- #
def _summary(*, found: int, not_observed: int, inconsistent: int) -> CitationSummary:
    per = [
        CitationStatus(
            source=f"dir-{i}", found=True, listing_url="https://d/x",
            name_match=1.0, address_match=1.0, phone_match=1.0, nap_score=1.0,
        )
        for i in range(found)
    ] + [
        CitationStatus(
            source=f"miss-{i}", found=False, listing_url=None,
            name_match=None, address_match=None, phone_match=None, nap_score=None,
        )
        for i in range(not_observed)
    ]
    return CitationSummary(
        business_query="Ace Plumbing",
        total_checked=len(per),
        found_count=found,
        not_observed_count=not_observed,
        inconsistent_count=inconsistent,
        average_nap_score=1.0 if found else None,
        per_source=per,
    )


def test_an_unsurfaced_directory_is_not_observed_never_absent() -> None:
    listed = CitationStatus(
        source="Yelp", found=True, listing_url="https://yelp.com/x",
        name_match=1.0, address_match=1.0, phone_match=1.0, nap_score=1.0,
    )
    unseen = CitationStatus(
        source="Manta", found=False, listing_url=None,
        name_match=None, address_match=None, phone_match=None, nap_score=None,
    )
    assert listed.state == "listed"
    assert unseen.state == "not_observed"
    # The vocabulary this method is not entitled to use:
    assert unseen.state != "absent"
    assert unseen.state != "missing"


def test_an_unobserved_directory_costs_at_most_a_quarter_point() -> None:
    """The real guard on the weighting. The old code charged 0.5 per unsurfaced
    directory - so four silent directories cost 2.0 points of a client's score on
    no evidence at all. Re-inject ``not_observed * 0.5`` and this fails (8.0 < 9.0).
    """
    v = check_citation_consistency(_summary(found=14, not_observed=4, inconsistent=0))
    assert v.score >= 9.0, f"unobserved directories are being over-penalised: {v.score}"


def test_measured_drift_outweighs_silence_per_directory() -> None:
    """One observed NAP mismatch is real evidence and must cost strictly more than
    one directory that merely did not surface."""
    drift = check_citation_consistency(_summary(found=17, not_observed=0, inconsistent=1))
    unseen = check_citation_consistency(_summary(found=17, not_observed=1, inconsistent=0))

    assert unseen.score > drift.score
    penalty_unseen = 10.0 - unseen.score
    penalty_drift = 10.0 - drift.score
    assert penalty_drift >= penalty_unseen * 4


def test_severity_escalates_on_measured_drift_not_on_silence() -> None:
    """18 directories that merely did not surface must NOT read as a major finding;
    two measured NAP mismatches must."""
    all_silent = check_citation_consistency(_summary(found=0, not_observed=18, inconsistent=0))
    two_drifts = check_citation_consistency(_summary(found=16, not_observed=0, inconsistent=2))

    assert all_silent.severity == "minor"
    assert two_drifts.severity == "major"


def test_the_verdict_states_its_method_and_its_limit() -> None:
    v = check_citation_consistency(_summary(found=10, not_observed=8, inconsistent=0))
    assert v.evidence["method"] == "serper-snippet-inference"
    assert "NOT" in v.evidence["measurement_note"]
    assert "not_observed" in v.evidence


def test_missing_count_survives_as_an_alias_for_existing_readers() -> None:
    """The PDF off-page section parses citations.json by key; the legacy name must
    keep resolving while the honest one is added beside it."""
    s = _summary(found=10, not_observed=8, inconsistent=0)
    assert s.missing_count == s.not_observed_count == 8


# --------------------------------------------------------------------------- #
# 3. The local subcommand runs the analyzers it announces.
# --------------------------------------------------------------------------- #
def test_the_local_subcommand_loop_has_a_body() -> None:
    """A console line claiming work, over an empty loop, is the exact defect class
    this repo exists to prevent. Pin the body: the loop must emit ON-099."""
    import inspect

    from audit_engine.cli import main as cli_main

    src = inspect.getsource(cli_main)
    start = src.index("Running on-page analyzers (subset)")
    segment = src[start : start + 1200]
    assert "check_https(cp)" in segment
    assert "ON-099" in segment
