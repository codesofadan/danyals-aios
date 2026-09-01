"""The wire must be able to say "live" — the 2026-09-01 serializer lie, in test form.

`CitationResponse.from_row` guards `submit_status` against a frozenset that was missing
`live`/`drifted`/`delisted` (present in the Literal five lines up), so the ONLY earned
status this module produces was coerced to "not_started" on the wire: a fetch-verified
listing rendered as never attempted, and the citations board could not show a success at
all. The proof column carried a raw storage key that 404'd as a link, every time.
"""

from __future__ import annotations

import pytest

from app.schemas.offpage import CitationResponse

pytestmark = pytest.mark.unit


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "11111111-2222-3333-4444-555555555555",
        "client_name": "Zain Saeed",
        "directory": "Brownbook",
        "nap_status": "consistent",
        "action": "Update",
        "note": "",
        "submit_status": "live",
        "proof_url": "ab12cd34.png",
        "live_url": "https://www.brownbook.net/business/12345/zain-saeed",
        "blocked_reason": "",
    }
    base.update(overrides)
    return base


def test_live_survives_serialization_with_its_url() -> None:
    """Revert the frozenset and this is the first test to go red — `submitStatus`
    silently becomes "not_started" again."""
    out = CitationResponse.from_row(_row()).model_dump(by_alias=True)
    assert out["submitStatus"] == "live"
    assert out["liveUrl"] == "https://www.brownbook.net/business/12345/zain-saeed"


@pytest.mark.parametrize("status", ["drifted", "delisted"])
def test_the_decay_states_survive_too(status: str) -> None:
    out = CitationResponse.from_row(_row(submit_status=status)).model_dump(by_alias=True)
    assert out["submitStatus"] == status


def test_a_genuinely_unknown_status_still_coerces() -> None:
    """The guard itself is right — it exists for pre-0045 rows and future enum drift.
    Only its vocabulary was stale."""
    out = CitationResponse.from_row(_row(submit_status="???")).model_dump(by_alias=True)
    assert out["submitStatus"] == "not_started"


def test_proof_url_is_the_reader_endpoint_never_the_raw_key() -> None:
    out = CitationResponse.from_row(_row()).model_dump(by_alias=True)
    assert out["proofUrl"] == (
        "/api/v1/citation-builder/citations/11111111-2222-3333-4444-555555555555/proof"
    )
    assert "ab12cd34" not in out["proofUrl"]


def test_no_proof_key_means_no_link_not_a_dead_one() -> None:
    out = CitationResponse.from_row(_row(proof_url="")).model_dump(by_alias=True)
    assert out["proofUrl"] == ""


def test_blocked_reason_travels_as_the_machine_code() -> None:
    out = CitationResponse.from_row(
        _row(submit_status="blocked", blocked_reason="price_unknown", live_url="")
    ).model_dump(by_alias=True)
    assert out["blockedReason"] == "price_unknown"
    assert out["liveUrl"] == ""
