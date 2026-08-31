"""Every platform an operator can be ASKED to connect must say how to connect it.

THE FAILURE THIS PREVENTS. The board tells an operator a platform is `not_connected`.
Without a guide on that row, the only honest next step is "ask an engineer" - which is
exactly why provisioning stalled and a client could sit at zero connected platforms
indefinitely. A platform that can appear as connectable, and cannot explain itself, is a
dead end wearing a call to action.
"""

from __future__ import annotations

import pytest

from app.services.web2_provisioning import GUIDES
from integrations.web2_publishers import PLATFORM_CREDENTIAL_FIELDS

pytestmark = pytest.mark.unit


def test_every_guide_names_a_place_and_the_steps() -> None:
    for platform, guide in GUIDES.items():
        assert guide.where.strip(), f"{platform}: no URL to go to"
        assert guide.steps.strip(), f"{platform}: no steps"
        assert guide.account_needed.strip(), f"{platform}: does not say whose account"


def test_a_guide_names_the_exact_credential_fields_the_publisher_wants() -> None:
    """A guide that ends without naming the fields sends someone back a second time."""
    for platform, guide in GUIDES.items():
        required = PLATFORM_CREDENTIAL_FIELDS.get(platform)
        if not required:
            continue
        blob = f"{guide.steps} {guide.fields_note}".lower()
        missing = [f for f in required if f.lower() not in blob]
        assert not missing, f"{platform}: steps never mention {missing}"


def test_a_cost_or_blocker_is_stated_before_anyone_is_sent() -> None:
    """Measured 2026-08-30: Hashnode retired free API access, so a token issued on a free
    account is rejected. A teammate sent to fetch one has been sent on an errand nobody
    costed - so the guide must carry the cost and the blocker, not just the steps."""
    hashnode = GUIDES["Hashnode"]
    assert "PAID" in hashnode.cost
    assert hashnode.blocker.strip(), "a platform that cannot work on a free account must say so"

    for platform, guide in GUIDES.items():
        assert guide.cost.strip(), f"{platform}: no cost stated"
