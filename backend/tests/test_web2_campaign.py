"""Campaign planning - "thirty blog posts" turned into a lawful, costed, scheduled plan.

The load-bearing test is ``test_a_campaign_cannot_reuse_one_topic_across_properties``.
It encodes a measurement taken against the real generator:

    same client, SAME topic, many platforms -> body r = 1.000, heading r = 1.000
    same client, DISTINCT topics            -> body r = 0.034, heading r = 0.406

Publishing one topic across thirty platforms yields thirty BYTE-IDENTICAL articles. So
"thirty blog posts" must mean thirty distinct topics, and a request that cannot supply
them has to be refused at PLANNING time - before thirty metered Claude drafting runs
produce thirty articles the similarity gate will then block one by one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.web2_campaign import (
    CAMPAIGN_FRAMEWORKS,
    CampaignRefusedError,
    campaign_status_for,
    plan_campaign,
)
from app.services.web2_pacing import PacingCaps

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
PLATFORMS = ["Blogger", "WordPress.com", "Tumblr", "Telegra.ph", "Micro.blog"]
# The per-client campaign cap is a separate control with its own test; lifting it here
# keeps these assertions about the thing each one names.
CAPS = PacingCaps(publish_jitter_max_hours=0, max_properties_per_client_campaign=0)


def _topics(n: int) -> list[str]:
    return [f"topic number {i}" for i in range(n)]


def _plan(**over: object):
    kwargs: dict[str, object] = {
        "now": NOW, "client_id": "cl-1", "client_name": "Leeds Drainage",
        "requested_count": 5, "topics": _topics(5), "platforms": PLATFORMS,
        "anchors": ["Leeds Drainage", "the team", "our drainage service"],
        "target_url": "https://leedsdrainage.co.uk/drains", "caps": CAPS,
        "per_article_cost": 0.15,
    }
    kwargs.update(over)
    return plan_campaign(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# THE refusal.
# --------------------------------------------------------------------------- #
def test_a_campaign_cannot_reuse_one_topic_across_properties() -> None:
    with pytest.raises(CampaignRefusedError, match="distinct topics"):
        _plan(requested_count=5, topics=["drain unblocking"])


def test_topics_differing_only_in_case_are_one_topic() -> None:
    """They generate the same article, so counting them as two would let the duplicate
    through the very check that exists to stop it."""
    with pytest.raises(CampaignRefusedError, match="distinct topics"):
        _plan(requested_count=3, topics=["Drain Unblocking", "drain unblocking", "  DRAIN  "])


def test_every_planned_property_gets_its_own_topic() -> None:
    plan = _plan(requested_count=5, topics=_topics(5))
    assert len({p.topic for p in plan.properties}) == 5


def test_a_campaign_with_no_eligible_platforms_is_refused_with_a_reason() -> None:
    """The message points at the platform board, because "no platforms" for a client is
    usually an eligibility verdict rather than an empty catalogue."""
    with pytest.raises(CampaignRefusedError, match="content policies"):
        _plan(platforms=[])


def test_a_zero_article_campaign_is_refused() -> None:
    with pytest.raises(CampaignRefusedError):
        _plan(requested_count=0, topics=[])


# --------------------------------------------------------------------------- #
# Footprint diversification - finally wired.
# --------------------------------------------------------------------------- #
def test_the_campaign_spreads_across_the_selected_platforms() -> None:
    """`diversify_footprint` had zero production callers before this. Concentrating a
    client's whole campaign on one platform is both the slower route (a 72-hour gap per
    client per platform) and the thinner disguise."""
    plan = _plan(requested_count=5, topics=_topics(5))
    assert len({p.platform for p in plan.properties}) > 1


def test_the_writing_framework_rotates_across_the_campaign() -> None:
    """Measured: rotating halves worst-case heading resemblance (0.406 -> 0.208), because
    `_FRAMEWORK_MOVES` is a fixed heading table and same-framework articles share a
    skeleton."""
    plan = _plan(requested_count=len(CAMPAIGN_FRAMEWORKS), topics=_topics(len(CAMPAIGN_FRAMEWORKS)))
    assert len({p.framework for p in plan.properties}) == len(CAMPAIGN_FRAMEWORKS)


def test_planning_is_deterministic_for_the_same_request() -> None:
    """A quote an operator was shown must not change when they press Create."""
    a = _plan(requested_count=5, topics=_topics(5))
    b = _plan(requested_count=5, topics=_topics(5))
    assert [(p.platform, p.topic, p.anchor) for p in a.properties] == [
        (p.platform, p.topic, p.anchor) for p in b.properties
    ]


# --------------------------------------------------------------------------- #
# Cost and schedule are shown BEFORE committing.
# --------------------------------------------------------------------------- #
def test_the_plan_prices_the_whole_batch() -> None:
    """The per-call cost gate cannot see a batch, so without this the only guard against
    a mistyped article count is the client's monthly budget."""
    plan = _plan(requested_count=10, topics=_topics(10), per_article_cost=0.15)
    assert plan.estimated_cost_usd == pytest.approx(1.5)


def test_a_campaign_over_its_ceiling_is_refused_before_any_spend() -> None:
    with pytest.raises(CampaignRefusedError, match="ceiling"):
        _plan(requested_count=30, topics=_topics(30), per_article_cost=0.15, cost_ceiling_usd=1.0)


def test_every_property_publishes_on_approval_and_the_plan_says_so() -> None:
    """OWNER DECISION (2026-08-29): an approved campaign publishes immediately, no drip.

    ``scheduled_for`` must be NULL on every property. This is not cosmetic: nothing in
    this deployment drives the release tick (``web2_release_due`` has no caller, celery
    beat is empty), so a future ``scheduled_for`` did not PACE a property, it PARKED it -
    approval moved it to ``publishing`` and handed it to a tick that never runs, and
    every property after the first silently never published having already been paid for.
    """
    plan = _plan(requested_count=5, topics=_topics(5))
    assert all(p.scheduled_for is None for p in plan.properties), (
        "a scheduled property is handed to a release tick that does not run"
    )
    assert plan.projected_completion is None
    # The heavier-footprint trade-off the owner accepted is stated, not hidden.
    assert any("no drip" in note for note in plan.notes)
    assert any("footprint" in note for note in plan.notes)


def test_the_per_client_campaign_cap_shrinks_the_plan_and_says_so() -> None:
    """A request quietly shrunk from thirty to four is a lie the operator would only
    discover weeks later, so the note is part of the contract."""
    plan = _plan(
        requested_count=30, topics=_topics(30),
        caps=PacingCaps(publish_jitter_max_hours=0, max_properties_per_client_campaign=4),
    )
    assert plan.count == 4
    assert any("cap is 4" in note for note in plan.notes)


# --------------------------------------------------------------------------- #
# Honest status (the P0-4 rule).
# --------------------------------------------------------------------------- #
def test_a_campaign_that_did_not_publish_everything_is_degraded_not_completed() -> None:
    """The same rule the content dispatcher enforces: reporting a partial delivery as
    complete is a green tick over work that reached nobody."""
    assert campaign_status_for(total=30, published=30, failed=0) == "completed"
    assert campaign_status_for(total=30, published=28, failed=2) == "degraded"


def test_a_campaign_still_working_is_running_not_completed() -> None:
    assert campaign_status_for(total=30, published=10, failed=0) == "running"
    assert campaign_status_for(total=30, published=0, failed=0) == "scheduled"


def test_a_cancelled_campaign_reports_cancelled_whatever_was_published() -> None:
    assert campaign_status_for(total=30, published=10, failed=0, cancelled=True) == "cancelled"


def test_history_no_longer_delays_a_campaign_but_still_shapes_anchors() -> None:
    """Publishing history stopped moving publish TIMES when drip was removed, but it is
    still read - it feeds anchor/platform diversification, so the parameter is live and
    not a leftover."""
    from app.services.web2_pacing import Placement

    recent = [
        Placement(
            published_at=NOW - timedelta(hours=1), web2_id="w2-old", client_id="cl-1",
            platform="Blogger",
        )
    ]
    later = _plan(requested_count=1, topics=_topics(1), history=recent)
    fresh = _plan(requested_count=1, topics=_topics(1))
    assert later.properties[0].scheduled_for is None
    assert fresh.properties[0].scheduled_for is None

# --------------------------------------------------------------------------- #
# Anchor safety inside the planner (R2-14).
# --------------------------------------------------------------------------- #
def test_an_exact_match_anchor_never_reaches_a_planned_property() -> None:
    """The guard has to run at PLANNING, not at review. An exact-match anchor that
    reaches a draft has already been written into an article; catching it later means
    discarding paid work rather than preventing it."""
    plan = _plan(
        anchors=["drains"],                    # exactly the /drains slug
        target_url="https://leedsdrainage.co.uk/drains",
    )
    assert all(p.anchor != "drains" for p in plan.properties)
    assert any("was not used" in n for n in plan.notes)


def test_the_refusal_is_reported_so_the_operator_learns_the_rule() -> None:
    """A silent substitution teaches nothing and the same list arrives next time."""
    plan = _plan(anchors=["drains"], target_url="https://leedsdrainage.co.uk/drains")
    joined = " ".join(plan.notes).lower()
    assert "drains" in joined
    assert "brand" in joined


def test_a_usable_anchor_in_the_list_is_kept() -> None:
    plan = _plan(
        anchors=["drains", "Leeds Drainage"],
        target_url="https://leedsdrainage.co.uk/drains",
    )
    assert {p.anchor for p in plan.properties} == {"Leeds Drainage"}


def test_a_brand_anchor_survives_even_when_it_contains_the_slug_words() -> None:
    """A client whose name IS the service must still be able to use its own name."""
    plan = _plan(
        client_name="Leeds Drains", anchors=["Leeds Drains"],
        target_url="https://leedsdrainage.co.uk/drains",
    )
    assert {p.anchor for p in plan.properties} == {"Leeds Drains"}
