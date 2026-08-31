"""When the canonical NAP moves, the listings built from it are stale that instant.

`business_profiles` is the record every submission is built from. Editing it used to
silently re-point canonical while every already-built listing kept carrying the old
address, and nothing anywhere noticed. An inconsistent citation is worse than no
citation - it splits the local signal instead of reinforcing it - so the edit and the
fan-out are one action.
"""

from __future__ import annotations

import pytest

from app.modules.citations.service import (
    NAP_CRITICAL_FIELDS,
    citations_needing_correction,
    diff_nap_fields,
)

pytestmark = pytest.mark.unit


def _profile(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "business_name": "Bright Harbour Dental",
        "address_line1": "88 Harbour Street",
        "address_line2": "",
        "city": "Southport",
        "region": "QLD",
        "postal_code": "4215",
        "phone": "+61 7 5555 0100",
        "website_url": "https://brightharbour.example",
        "description": "A dental practice.",
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# What counts as a change.
# --------------------------------------------------------------------------- #
def test_a_moved_address_is_a_change_event() -> None:
    events = diff_nap_fields(_profile(), _profile(address_line1="12 Marine Parade"))
    assert events == [
        {
            "field": "address_line1",
            "old_value": "88 Harbour Street",
            "new_value": "12 Marine Parade",
        }
    ]


def test_several_fields_moving_produce_several_events() -> None:
    events = diff_nap_fields(
        _profile(), _profile(city="Brisbane", postal_code="4000", phone="+61 7 5555 0999")
    )
    assert {e["field"] for e in events} == {"city", "postal_code", "phone"}


def test_editing_a_non_asserted_field_flags_nothing() -> None:
    """A listing asserts a name, address, phone and website. It does not assert our
    internal description - flagging every citation over a copy tweak would train
    operators to ignore the flag, which is the same as not having one."""
    assert diff_nap_fields(_profile(), _profile(description="Now with more dentists.")) == []


def test_none_versus_empty_string_is_not_a_change() -> None:
    """The same absence expressed two ways. Raising a correction for every citation over
    this would be noise indistinguishable from a real move."""
    assert diff_nap_fields(_profile(address_line2=""), _profile(address_line2=None)) == []
    assert diff_nap_fields(_profile(address_line2=None), _profile(address_line2="")) == []


def test_whitespace_only_edits_are_not_changes() -> None:
    assert diff_nap_fields(_profile(), _profile(city="  Southport  ")) == []


def test_a_partial_payload_only_diffs_the_fields_it_carries() -> None:
    """A PATCH that omits a field is not asserting that field became empty."""
    assert diff_nap_fields(_profile(), {"phone": "+61 7 5555 0100"}) == []
    assert len(diff_nap_fields(_profile(), {"phone": "+61 7 5555 0999"})) == 1


def test_every_field_a_listing_asserts_is_watched() -> None:
    """A field that appears on a directory form but not in NAP_CRITICAL_FIELDS is a
    silent staleness hole."""
    assert set(NAP_CRITICAL_FIELDS) == {
        "business_name", "address_line1", "address_line2", "city",
        "region", "postal_code", "phone", "website_url",
    }


# --------------------------------------------------------------------------- #
# Which listings are made stale.
# --------------------------------------------------------------------------- #
def _cit(cid: str, status: str) -> dict[str, object]:
    return {"id": cid, "directory": "Example", "submit_status": status}


def test_only_listings_we_believe_exist_are_flagged() -> None:
    rows = [
        _cit("live-1", "live"),
        _cit("drift-1", "drifted"),
        _cit("sent-1", "submitted"),
        _cit("queued-1", "queued"),
        _cit("gone-1", "delisted"),
        _cit("never-1", "not_started"),
        _cit("blocked-1", "blocked"),
        _cit("failed-1", "failed"),
    ]
    assert set(citations_needing_correction(rows)) == {"live-1", "drift-1"}


def test_a_submitted_row_is_not_flagged() -> None:
    """Nothing has confirmed a listing came back, so there may be nothing to correct -
    and if one does appear, the liveness check will compare it against the NEW canonical
    NAP anyway, which is the right comparison. Flagging now invents work that may never
    exist."""
    assert citations_needing_correction([_cit("s", "submitted")]) == []


def test_a_delisted_row_is_not_resurrected_by_a_nap_change() -> None:
    assert citations_needing_correction([_cit("d", "delisted")]) == []


def test_no_listings_is_a_clean_empty_answer() -> None:
    assert citations_needing_correction([]) == []


# --------------------------------------------------------------------------- #
# The projection bug: a correct fix that reads a column nobody selected.
# --------------------------------------------------------------------------- #
def test_the_gap_projection_selects_live_url() -> None:
    """`compute_citation_gap` reads `live_url`. `list_citations_for_client` is the query
    that feeds it, and it originally selected `proof_url` and not `live_url` - so the
    Phase 0 fix was correct and would have produced an empty live list forever.

    That is a WORSE failure than the bug it replaced: an empty result looks like "this
    client has no live citations" rather than like an error, so nobody would investigate.
    Pinned by reading the source, because the alternative is a live database."""
    import inspect

    from app.modules.citations.repo import CitationsRepo

    sql = inspect.getsource(CitationsRepo.list_citations_for_client)
    assert "live_url" in sql, "the gap projection must select live_url"
    assert "proof_url" in sql, "the board still links the proof screenshot"


# --------------------------------------------------------------------------- #
# An unset market is not a US business (0113).
# --------------------------------------------------------------------------- #
def test_an_unrecorded_market_derives_as_global_not_us() -> None:
    """MEASURED with a real Lahore client on 2026-08-30.

    An unset market defaulted to US, so the campaign selected 138 US+GLOBAL directories
    and queued an operator to submit a Pakistani business to YellowPages.com, Chamber of
    Commerce and BBB. Nobody ever said that client was American — a column default did,
    which is the same fabrication class as reporting a screenshot as a live listing.

    A WRONG listing is worse than a missing one: a US directory entry for a Lahore
    business is NAP pollution, the exact harm a citation campaign prevents, and often
    cannot be removed. GLOBAL-only is merely less coverage, and the gap report names it."""
    from app.modules.citations.service import derive_business_profile_fields

    derived = derive_business_profile_fields(
        {"business_name": "Zain Tape Printers", "city": "Lahore", "phone": "03094378717"}
    )
    assert derived["market"] == "GLOBAL"


def test_a_recorded_market_is_always_honoured() -> None:
    """The fix must not override a market somebody actually stated."""
    from app.modules.citations.service import derive_business_profile_fields

    for market in ("US", "UK", "CA", "AU", "GLOBAL"):
        derived = derive_business_profile_fields({"business_name": "X", "market": market})
        assert derived["market"] == market
