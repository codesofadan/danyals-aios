"""Wave 4 unit gate: the PURE citation gap-analysis + NAP-derive logic, plus the
Web 2.0 / citation-engine API status boards. No DB, no network, no keys.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.modules.citations.service import (
    compute_citation_gap,
    derive_business_profile_fields,
)
from integrations.citation_status import citation_engine_status
from integrations.web2_status import web2_platform_status, web2_status_board

pytestmark = pytest.mark.unit


def _dir(did: str, name: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": did, "name": name, "url": f"https://{name.lower()}.example", "market": "US",
        "tier": "bot_fillable", "submit_method": "bot:playwright", "link_rel": "dofollow",
        "price_note": "", "automation_note": "", "active": True, "authority": 60,
        "authority_tier": "core", "access": "open", "is_marketplace": False, "verticals": [],
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# derive_business_profile_fields: client NAP -> submission profile
# --------------------------------------------------------------------------- #
def test_derive_maps_nap_and_leads_categories_with_primary() -> None:
    client_nap = {
        "business_name": "Acme Dental", "address_line1": "123 Main St", "city": "Bellevue",
        "region": "WA", "postal_code": "98004", "market": "US", "phone": "555-0100",
        "website_url": "https://acme.example", "primary_category": "Dentist",
        "extra_categories": ["Cosmetic dentistry", "Dentist"], "hours": {"mon": "9-5"},
    }
    fields = derive_business_profile_fields(client_nap)
    assert fields["business_name"] == "Acme Dental"
    assert fields["market"] == "US"
    assert fields["is_primary"] is True
    assert fields["label"] == "Primary"
    # primary leads; the duplicate "Dentist" in extras is dropped.
    assert fields["categories"] == ["Dentist", "Cosmetic dentistry"]
    assert fields["hours"] == {"mon": "9-5"}


def test_derive_tolerates_empty_nap() -> None:
    fields = derive_business_profile_fields({})
    assert fields["business_name"] == ""
    assert fields["categories"] == []
    assert fields["market"] == "US"


# --------------------------------------------------------------------------- #
# compute_citation_gap: covered vs missing, live URLs, tallies
# --------------------------------------------------------------------------- #
def test_gap_missing_excludes_covered_by_id_and_name() -> None:
    directories = [_dir("d1", "Yelp"), _dir("d2", "Bing Places"), _dir("d3", "Hotfrog")]
    existing = [
        # covered by directory_id (in-flight submission)
        {"id": "c1", "directory": "Yelp", "directory_id": "d1", "submit_status": "submitted",
         "nap_status": "missing", "proof_url": "https://proof/1"},
        # covered by NAME only (legacy monitoring row, no directory_id), consistent NAP
        {"id": "c2", "directory": "Bing Places", "directory_id": None,
         "submit_status": "not_started", "nap_status": "consistent", "proof_url": ""},
    ]
    gap = compute_citation_gap(directories=directories, existing_citations=existing)
    missing_names = {d["name"] for d in gap.missing}
    assert missing_names == {"Hotfrog"}  # Yelp + Bing already covered
    assert gap.existing_count == 2
    assert gap.covered_count == 2
    # the submitted row with a proof url surfaces as a live URL
    assert gap.live_urls == [{"directory": "Yelp", "url": "https://proof/1", "status": "submitted"}]
    assert gap.by_submit_status == {"submitted": 1, "not_started": 1}


def test_gap_failed_and_blocked_rows_are_still_missing() -> None:
    directories = [_dir("d1", "Yelp"), _dir("d2", "Hotfrog")]
    existing = [
        {"id": "c1", "directory": "Yelp", "directory_id": "d1", "submit_status": "failed",
         "nap_status": "missing", "proof_url": ""},
        {"id": "c2", "directory": "Hotfrog", "directory_id": "d2", "submit_status": "blocked",
         "nap_status": "missing", "proof_url": ""},
    ]
    gap = compute_citation_gap(directories=directories, existing_citations=existing)
    # both are retryable outcomes -> still open gaps to close
    assert {d["name"] for d in gap.missing} == {"Yelp", "Hotfrog"}
    assert gap.covered_count == 0
    assert gap.by_submit_status == {"failed": 1, "blocked": 1}


def test_gap_manual_only_directories_are_never_missing() -> None:
    directories = [_dir("d1", "Data Axle", tier="manual_only", submit_method="")]
    gap = compute_citation_gap(directories=directories, existing_citations=[])
    assert gap.missing == []  # manual_only has no worker path -> never a build target


# --------------------------------------------------------------------------- #
# Web 2.0 status board
# --------------------------------------------------------------------------- #
def test_web2_board_connected_missing_and_draft_only() -> None:
    statuses = {p.platform: p for p in web2_platform_status({"WordPress.com": 3})}
    wp = statuses["WordPress.com"]
    assert wp.connected is True and wp.configured_count == 3
    assert "oauth_token" in wp.required_fields
    devto = statuses["dev.to"]
    assert devto.connected is False and "Missing" in devto.reason
    medium = statuses["Medium"]
    assert medium.draft_only is True and medium.connected is False
    assert "retired" in medium.reason and medium.external_note == ""
    # a connected, live platform always carries the external caveat
    assert "external" in wp.external_note.lower()


def test_web2_board_rollup_counts() -> None:
    board = web2_status_board({"WordPress.com": 1, "Tumblr": 2})
    assert board.connected_count == 2
    assert board.total_count == len(board.platforms)
    # 17 platforms, Medium is the only draft-only one
    assert board.live_count == board.total_count - 1


# --------------------------------------------------------------------------- #
# Citation engine status board
# --------------------------------------------------------------------------- #
def test_engine_status_all_missing_on_keyless_settings() -> None:
    settings = Settings(_env_file=None, app_env="dev")  # type: ignore[call-arg]
    engines = {e.key: e for e in citation_engine_status(settings)}
    assert engines["bing_places"].connected is False
    assert engines["apify"].connected is False
    assert engines["playwright_bot"].connected is False  # optional extra, never a key
    # every engine names its required config + carries an honest reason
    for e in engines.values():
        assert e.reason
        assert e.required_config


def test_engine_status_reflects_configured_keys() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, app_env="dev",
        bing_places_api_key="k", apify_api_token="t", apify_citation_actor_id="actor-1",
    )
    engines = {e.key: e for e in citation_engine_status(settings)}
    assert engines["bing_places"].connected is True
    assert engines["apify"].connected is True
    assert engines["foursquare"].connected is False  # still unset
