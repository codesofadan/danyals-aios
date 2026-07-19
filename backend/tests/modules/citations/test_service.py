"""Citation-builder orchestration (PURE - no DB, no network)."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.modules.citations.service import (
    automatable_directories,
    estimate_campaign_cost,
    job_from_row,
    submit_method_label,
    submitter_for,
)
from integrations.citation_submitters import CitationJob, CitationSubmitResult

pytestmark = pytest.mark.unit


def _dir(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "d-1", "name": "Brownbook", "tier": "bot_fillable", "submit_method": "bot:playwright",
        "market": "US",
    }
    row.update(over)
    return row


def _settings() -> Settings:
    return Settings(_env_file=None, app_env="dev")


# --------------------------------------------------------------------------- #
# automatable_directories
# --------------------------------------------------------------------------- #
def test_manual_only_is_excluded() -> None:
    rows = [_dir(tier="manual_only"), _dir(id="d-2", tier="bot_fillable")]
    result = automatable_directories(rows)
    assert [r["id"] for r in result] == ["d-2"]


def test_fed_by_another_aggregator_is_excluded_even_though_tier_is_aggregator() -> None:
    rows = [
        _dir(id="d-1", tier="aggregator", submit_method="aggregator:fed_by_data_axle_foursquare"),
        _dir(id="d-2", tier="aggregator", submit_method="aggregator:data_axle"),
    ]
    result = automatable_directories(rows)
    assert [r["id"] for r in result] == ["d-2"]


def test_every_automatable_tier_passes() -> None:
    rows = [_dir(id=t, tier=t, submit_method=f"x:{t}") for t in ("aggregator", "api", "bot_fillable", "captcha_assisted")]
    assert {r["id"] for r in automatable_directories(rows)} == {"aggregator", "api", "bot_fillable", "captcha_assisted"}


# --------------------------------------------------------------------------- #
# estimate_campaign_cost
# --------------------------------------------------------------------------- #
def test_cost_estimate_sums_per_tier() -> None:
    settings = _settings()
    rows = [_dir(tier="api"), _dir(tier="bot_fillable"), _dir(tier="captcha_assisted")]
    total = estimate_campaign_cost(rows, settings)
    expected = round(
        settings.citation_api_cost_estimate
        + settings.citation_bot_cost_estimate
        + settings.citation_captcha_cost_estimate,
        4,
    )
    assert total == expected


def test_cost_estimate_of_empty_batch_is_zero() -> None:
    assert estimate_campaign_cost([], _settings()) == 0.0


def test_aggregator_and_api_share_the_same_estimate() -> None:
    settings = _settings()
    assert estimate_campaign_cost([_dir(tier="aggregator")], settings) == estimate_campaign_cost(
        [_dir(tier="api")], settings
    )


# --------------------------------------------------------------------------- #
# submit_method_label
# --------------------------------------------------------------------------- #
def test_submit_method_label_reads_the_catalog_value() -> None:
    assert submit_method_label(_dir(submit_method="api:bing_places")) == "api:bing_places"


def test_submit_method_label_blank_when_missing() -> None:
    row = _dir()
    del row["submit_method"]
    assert submit_method_label(row) == ""


# --------------------------------------------------------------------------- #
# submitter_for - dispatch logic
# --------------------------------------------------------------------------- #
class _StubSubmitter:
    def submit(self, job: CitationJob) -> CitationSubmitResult:
        return CitationSubmitResult(status="submitted")


def test_fed_by_routes_to_no_engine_with_an_honest_reason() -> None:
    sub, reason = submitter_for(
        "aggregator:fed_by_data_axle", api_submitters={}, bot=_StubSubmitter(), apify=_StubSubmitter()
    )
    assert sub is None
    assert "no action needed" in reason


def test_api_prefix_routes_to_the_matching_key() -> None:
    bing = _StubSubmitter()
    sub, reason = submitter_for("api:bing_places", api_submitters={"bing_places": bing}, bot=None, apify=None)
    assert sub is bing and reason == ""


def test_api_prefix_with_no_matching_key_is_a_clean_none() -> None:
    sub, reason = submitter_for("api:foursquare_places", api_submitters={}, bot=None, apify=None)
    assert sub is None and "foursquare_places" in reason


def test_bot_prefix_routes_to_the_bot() -> None:
    bot = _StubSubmitter()
    sub, reason = submitter_for("bot:playwright", api_submitters={}, bot=bot, apify=None)
    assert sub is bot and reason == ""


def test_aggregator_non_fed_prefix_also_routes_to_the_bot() -> None:
    bot = _StubSubmitter()
    sub, _reason = submitter_for("aggregator:data_axle", api_submitters={}, bot=bot, apify=None)
    assert sub is bot


def test_bot_prefix_with_no_bot_configured_is_a_clean_none() -> None:
    sub, reason = submitter_for("bot:playwright", api_submitters={}, bot=None, apify=None)
    assert sub is None and "Playwright" in reason


def test_apify_routes_to_the_fallback() -> None:
    apify = _StubSubmitter()
    sub, reason = submitter_for("apify", api_submitters={}, bot=None, apify=apify)
    assert sub is apify and reason == ""


def test_unrecognised_method_never_raises() -> None:
    sub, reason = submitter_for("mystery:xyz", api_submitters={}, bot=None, apify=None)
    assert sub is None and "mystery:xyz" in reason


# --------------------------------------------------------------------------- #
# job_from_row - the joined-row -> CitationJob mapping
# --------------------------------------------------------------------------- #
def test_job_from_row_reads_the_directory_and_business_profile_columns() -> None:
    row = {
        "directory_name": "Brownbook", "directory_url": "brownbook.net",
        "directory_market": "US", "submit_method": "bot:playwright",
        "bp_business_name": "Acme Dental", "bp_address_line1": "123 Main St",
        "bp_address_line2": "", "bp_city": "Bellevue", "bp_region": "WA",
        "bp_postal_code": "98004", "bp_phone": "555-0100",
        "bp_website_url": "https://acme.example", "bp_categories": ["dentist", "family"],
        "external_ref": None,
    }
    job = job_from_row(row)
    assert job.directory_name == "Brownbook"
    assert job.market == "US"
    assert job.business_name == "Acme Dental"
    assert job.categories == ("dentist", "family")
    assert job.external_ref is None


def test_job_from_row_falls_back_to_the_legacy_directory_text_column() -> None:
    # A monitoring-originated row (pre-0045) has no directory_name join hit but does
    # have the legacy free-text `directory` column - job_from_row must not crash.
    row = {"directory": "Yelp", "submit_method": "", "bp_categories": None}
    job = job_from_row(row)
    assert job.directory_name == "Yelp"
    assert job.categories == ()
