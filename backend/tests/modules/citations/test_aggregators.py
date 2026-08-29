"""Route A: the spine that is written, wired, and deliberately not running.

Two facts hold it shut, and both are tested here because either one silently failing
would mean spending real money against a number nobody has confirmed:

  1. a KEY alone does not enable Data Axle — the price must also be known;
  2. no submitter may EVER return `verified`.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.modules.citations.tasks import _api_submitters
from integrations.citation_aggregators import AppleBusinessSubmitter, DataAxleSubmitter
from integrations.citation_submitters import CitationJob
from integrations.errors import ProviderNotConfiguredError

pytestmark = pytest.mark.unit


def _settings(**over: object) -> Settings:
    return Settings(_env_file=None, app_env="dev", **over)  # type: ignore[arg-type]


def _job(**over: object) -> CitationJob:
    row = {
        "directory_name": "Data Axle (Local Listings)", "directory_url": "data-axle.com",
        "market": "US", "submit_method": "api:data_axle", "business_name": "Acme Dental",
        "address_line1": "123 Main St", "address_line2": "", "city": "Bellevue",
        "region": "WA", "postal_code": "98004", "phone": "555-0100",
        "website_url": "https://acme.example", "client_id": "cl-1",
    }
    row.update(over)
    return CitationJob(**row)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# THE PRICE GATE.
# --------------------------------------------------------------------------- #
def test_a_key_alone_does_not_enable_data_axle() -> None:
    """The unusual gate, and the one that matters. Data Axle's per-Add price is published
    nowhere reachable; at the modelled $5/$10/$30 the per-unit cost is 17x-100x the 10c
    commitment. A key without a price is a way to spend money by accident."""
    s = _settings(data_axle_api_key="real-key")
    assert s.data_axle_submits_enabled is False
    assert "data_axle" not in _api_submitters(s)


def test_a_price_alone_does_not_enable_it_either() -> None:
    s = _settings(data_axle_add_cost_estimate=10.0)
    assert s.data_axle_submits_enabled is True
    assert "data_axle" not in _api_submitters(s), "no key, so nothing to call with"


def test_a_key_and_a_real_price_enables_it() -> None:
    s = _settings(data_axle_api_key="real-key", data_axle_add_cost_estimate=10.0)
    assert "data_axle" in _api_submitters(s)


def test_the_default_configuration_enables_nothing() -> None:
    """The honest shipped state: the spine exists in code and runs nowhere."""
    assert _api_submitters(_settings()) == {}


def test_apple_needs_both_a_key_and_an_org_id() -> None:
    assert "apple_business" not in _api_submitters(_settings(apple_business_api_key="k"))
    assert "apple_business" not in _api_submitters(_settings(apple_business_org_id="org1"))
    assert "apple_business" in _api_submitters(
        _settings(apple_business_api_key="k", apple_business_org_id="org1")
    )


@pytest.mark.parametrize(
    ("cls", "kwargs"),
    [
        (DataAxleSubmitter, {"api_key": ""}),
        (AppleBusinessSubmitter, {"api_key": "", "org_id": "o"}),
        (AppleBusinessSubmitter, {"api_key": "k", "org_id": ""}),
    ],
)
def test_a_blank_credential_refuses_to_construct(cls: type, kwargs: dict[str, str]) -> None:
    with pytest.raises(ProviderNotConfiguredError):
        cls(**kwargs)


# --------------------------------------------------------------------------- #
# NOTHING MAY RETURN `verified`.
# --------------------------------------------------------------------------- #
def test_no_aggregator_can_ever_report_verified() -> None:
    """Each of these platforms reviews a submission before publishing it: Data Axle
    telephones the business up to three times over three business days, Apple returns
    state SUBMITTED, Google requires verification before a location appears at all.

    A 200 from any of them means ACCEPTED, which is a different fact from a listing
    existing. Only the liveness probe promotes a row to `live`. Asserted on the source
    because the alternative is a live vendor account."""
    import inspect

    import integrations.citation_aggregators as mod

    src = inspect.getsource(mod)
    # No code path constructs a verified result.
    assert 'status="verified"' not in src
    assert "'verified'" not in src.replace('never ``verified``', "").replace("never `verified`", "")
    assert src.count('status="submitted"') >= 2


def test_an_existing_record_is_updated_not_re_added() -> None:
    """Billing is on Adds and Renewals only; updates are free. Re-adding to fix a phone
    number would be charged, would create a duplicate, and would restart the verification
    clock."""
    import inspect

    src = inspect.getsource(DataAxleSubmitter.submit)
    assert '"U" if job.external_ref else "A"' in src


def test_apple_pins_our_own_id_so_a_retry_is_idempotent() -> None:
    """Without a stable `partnersLocationId` a re-run creates a SECOND Apple location for
    the same business - a duplicate listing, which is the problem the module exists to
    prevent."""
    import inspect

    assert "partnersLocationId" in inspect.getsource(AppleBusinessSubmitter.submit)


def test_the_dead_submitters_are_not_quietly_back() -> None:
    """Bing and Foursquare were deleted because their endpoints return 404, not because
    they were unconfigured. Reintroducing them here would look like progress."""
    import inspect

    import integrations.citation_aggregators as mod

    src = inspect.getsource(mod).lower()
    # Named in the header as deleted; never as a class.
    assert "class bingplacessubmitter" not in src
    assert "class foursquaresubmitter" not in src
