"""7B-4 unit gate: the citation-SUBMISSION engines - no network, no keys, no browser.

Post Phase 3 (plan C1) the engine roster is SMALL and that is the point: the shared
Protocol + the deterministic fake, the two legitimate API submitters' dispatch, and
the guards that keep the deleted engines deleted - the Playwright bot, its CAPTCHA
solver and the signup bot all retired 2026-09-05 alongside the earlier Bing/Foursquare
ghosts.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import get_settings
from app.modules.citations.service import submitter_for
from app.modules.citations.tasks import _api_submitters
from integrations.citation_submitters import (
    CitationJob,
    CitationSubmitter,
    FakeCitationSubmitter,
)

pytestmark = pytest.mark.unit


def _job(**over: Any) -> CitationJob:
    body: dict[str, Any] = {
        "directory_name": "Brownbook", "directory_url": "brownbook.net", "market": "US",
        "submit_method": "bot:playwright", "business_name": "Acme Dental",
        "address_line1": "123 Main St", "address_line2": "", "city": "Bellevue",
        "region": "WA", "postal_code": "98004", "phone": "555-0100",
        "website_url": "https://acme.example", "categories": ("dentist",),
        "external_ref": None,
    }
    body.update(over)
    return CitationJob(**body)


# --------------------------------------------------------------------------- #
# 1. The shared Protocol + the deterministic fake.
# --------------------------------------------------------------------------- #
def test_fake_citation_submitter_satisfies_the_protocol() -> None:
    assert isinstance(FakeCitationSubmitter(), CitationSubmitter)


def test_fake_citation_submitter_is_deterministic_and_varies() -> None:
    fake = FakeCitationSubmitter()
    a, b = fake.submit(_job()), fake.submit(_job())
    assert a == b
    other = fake.submit(_job(directory_name="Hotfrog"))
    assert other.proof_url != a.proof_url


def test_fake_citation_submitter_echoes_external_ref_on_update() -> None:
    result = FakeCitationSubmitter().submit(_job(external_ref="existing-123"))
    assert result.external_ref == "existing-123"


# --------------------------------------------------------------------------- #
# 2. The engines that were DELETED, and the guards that keep them gone.
# --------------------------------------------------------------------------- #
# `integrations/citation_apis.py` held BingPlacesSubmitter + FoursquareSubmitter and was
# deleted in the 0106 pass - both wrote to endpoints that do not exist (probed
# unauthenticated 2026-08-23; see integrations/citation_status.py's retirement record).
#
# `integrations/citation_bot.py`, `integrations/captcha_solver.py` and
# `integrations/citation_signup.py` were deleted 2026-09-05 (Phase 3, plan C1): the bot
# shipped with stealth launch args, fingerprint masking, human-cadence typing, a
# residential proxy and live CAPTCHA solving - anti-abuse evasion this platform has
# ruled out - and the signup bot inherited it wholesale with zero catalogue rows ever
# routed to it. Form directories are operator-queue work; earned specs power extension
# autofill (`integrations/directory_specs.py`).
def test_the_dead_direct_api_submitters_stay_deleted() -> None:
    """A guard, not a formality. Both submitters looked entirely plausible - typed,
    key-gated, unit-tested against a mock transport that happily returned 200 for a
    route the vendor does not serve. That is exactly how they survived so long."""
    with pytest.raises(ModuleNotFoundError):
        import integrations.citation_apis  # noqa: F401


def test_the_retired_bot_and_solver_stay_deleted() -> None:
    """If any of these re-appears from git history, this fails and points at the
    retirement record in integrations/citation_status.py."""
    with pytest.raises(ModuleNotFoundError):
        import integrations.citation_bot
    with pytest.raises(ModuleNotFoundError):
        import integrations.captcha_solver
    with pytest.raises(ModuleNotFoundError):
        import integrations.citation_signup  # noqa: F401


def test_no_api_submitter_is_configured_so_an_api_row_blocks_cleanly() -> None:
    """With no keys, an `api:` directory must BLOCK with an honest reason - never look
    like a success."""
    submitter, reason = submitter_for(
        "api:bing_places", api_submitters=_api_submitters(get_settings())
    )
    assert submitter is None
    assert "no API submitter configured" in reason


def test_bot_routes_resolve_to_human_work_not_an_engine() -> None:
    """The replacement behavior, pinned at the dispatcher: a form route names the
    honest disposition rather than a machine."""
    submitter, reason = submitter_for("bot:playwright", api_submitters={})
    assert submitter is None
    assert "human work" in reason and "retired" in reason
