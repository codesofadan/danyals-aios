"""Compose once, publish everywhere - as variants, never as copies.

THE MEASUREMENT THAT DECIDES THE DESIGN, recorded in ``web2_campaign`` from a real
generator run::

    same client, SAME topic, 30 platforms  -> body r = 1.000, heading r = 1.000  (BLOCK)
    same client, DISTINCT topics           -> body r = 0.034, heading r = 0.406  (pass)

"One article to thirty platforms" produces thirty BYTE-IDENTICAL articles. The similarity
gate then blocks all thirty - after thirty metered drafting runs have already been paid
for. So "publish everywhere" has to mean one SUBJECT and N genuinely different posts, and
these tests pin the three axes that make them different: shape, angle, framework.

The second contract here is that a selection is never silently shrunk. An operator who
ticks twenty platforms and is quietly given six discovers it in a report weeks later.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.web2 import broadcast as bc
from app.services.web2_campaign import CampaignRefusedError

pytestmark = pytest.mark.unit

AVAILABLE = [
    "Ghost", "Blogger", "dev.to", "Mataroa", "Telegra.ph",
    "Bluesky", "Mastodon", "Pastebin.com",
]


def _accounts(**over: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {
        platform: {
            "id": f"acc-{platform}", "health": "active",
            "property_count": 0, "max_properties": 10,
        }
        for platform in AVAILABLE
    }
    for platform, patch in over.items():
        rows.setdefault(platform, {}).update(patch)
    return rows


def _plan(**over: Any) -> bc.BroadcastPlan:
    kwargs: dict[str, Any] = {
        "client_id": "c1",
        "client_name": "Leeds Drainage Co",
        "subject": "cctv drain survey",
        "target_url": "https://leedsdrainage.co.uk/cctv-drain-survey",
        "selected": [bc.ALL_PLATFORMS],
        "available": AVAILABLE,
        "anchors": ["Leeds Drainage Co"],
        "accounts": _accounts(),
    }
    kwargs.update(over)
    return bc.plan_broadcast(**kwargs)


# --------------------------------------------------------------------------- #
# One subject, N different posts
# --------------------------------------------------------------------------- #
def test_all_selects_every_platform_the_client_can_publish_to() -> None:
    plan = _plan()
    assert {p.platform for p in plan.posts} == set(AVAILABLE)


def test_each_platform_gets_its_own_shape_not_the_same_article() -> None:
    """A 900-word HTML article on Ghost and a 29-word plain-text note on Bluesky are not
    the same text shortened - the note is composed separately, because the article
    generator clamps to a 600-word floor and cannot produce one."""
    posts = {p.platform: p for p in _plan().posts}

    assert posts["Ghost"].shape == "article"
    assert posts["Ghost"].word_target == 900
    assert posts["Bluesky"].shape == "note"
    assert posts["Bluesky"].word_target < 40
    assert posts["Pastebin.com"].shape == "snippet"


def test_every_article_placement_gets_a_distinct_angle() -> None:
    """THE test that stands between this feature and a duplicate-content incident.

    Two blog platforms handed the same subject with no angle produce the same 900 words
    (measured r = 1.000). A distinct facet per placement is what makes them two real
    articles rather than one article posted twice.
    """
    articles = [p for p in _plan().posts if p.shape == "article"]

    assert len(articles) > 1
    angles = [p.angle for p in articles]
    assert len(set(angles)) == len(angles), "two articles share an angle"
    assert all(p.angle for p in articles), "an article with no angle is the duplicate case"

    topics = [p.topic for p in articles]
    assert len(set(topics)) == len(topics), "the topic must differ, not just a label"
    assert all("cctv drain survey" in t for t in topics), "still one subject throughout"


def test_the_framework_is_rotated_across_the_article_set() -> None:
    """Measured: rotating halves worst-case heading resemblance (0.406 -> 0.208), because
    same-framework articles share a fixed heading table."""
    articles = [p for p in _plan().posts if p.shape == "article"]
    frameworks = [p.framework for p in articles]
    assert len(set(frameworks)) > 1
    assert all(frameworks)


def test_short_form_placements_get_no_angle_because_they_are_one_thought() -> None:
    """Giving a 29-word post a facet over-specifies it, and its SHAPE already
    differentiates it from every article in the set."""
    notes = [p for p in _plan().posts if p.shape in ("note", "snippet")]
    assert notes
    assert all(p.angle == "" for p in notes)
    assert all(p.topic == "cctv drain survey" for p in notes)


def test_running_out_of_distinct_angles_is_reported_not_hidden() -> None:
    """The one way this can still collide. More article platforms than angles means the
    rotation repeats, and a repeat is the duplicate case again - so it is said out loud
    BEFORE the drafts are paid for, not discovered at the review gate."""
    many = [f"Blog{i}" for i in range(len(bc.ANGLES) + 3)]
    plan = _plan(
        selected=many, available=many,
        accounts={p: {"id": p, "health": "active", "property_count": 0, "max_properties": 9} for p in many},
    )
    assert any("rotation repeats" in note for note in plan.notes)


# --------------------------------------------------------------------------- #
# A selection is never silently shrunk
# --------------------------------------------------------------------------- #
def test_a_degraded_account_is_excluded_at_plan_time_with_its_reason() -> None:
    """Planning onto an account that refuses at publish time means a campaign silently
    delivers less than was approved - discovered one failed publish at a time."""
    plan = _plan(accounts=_accounts(Mastodon={"health": "degraded"}))

    assert "Mastodon" not in {p.platform for p in plan.posts}
    excluded = dict(plan.excluded)
    assert "degraded" in excluded["Mastodon"]


def test_an_account_at_its_property_cap_is_excluded() -> None:
    plan = _plan(accounts=_accounts(Blogger={"property_count": 10, "max_properties": 10}))
    assert "Blogger" not in {p.platform for p in plan.posts}
    assert "permitted properties" in dict(plan.excluded)["Blogger"]


def test_a_platform_with_no_account_is_excluded_rather_than_attempted() -> None:
    accounts = _accounts()
    del accounts["Ghost"]
    plan = _plan(accounts=accounts)
    assert "no publishing account" in dict(plan.excluded)["Ghost"]


def test_an_unsupported_platform_is_excluded_even_if_explicitly_selected() -> None:
    plan = _plan(selected=["Ghost", "Medium"], available=[*AVAILABLE, "Medium"])
    assert "Medium" not in {p.platform for p in plan.posts}
    assert "no usable publishing API" in dict(plan.excluded)["Medium"]


def test_every_exclusion_is_surfaced_in_the_notes() -> None:
    plan = _plan(accounts=_accounts(Mastodon={"health": "suspended"}))
    assert any("will receive nothing" in note for note in plan.notes)


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #
def test_an_empty_selection_is_refused_rather_than_treated_as_all() -> None:
    """"None selected" and "All" are different intentions, and an empty list must never
    quietly mean everything - that would publish to every platform by accident."""
    with pytest.raises(CampaignRefusedError, match="No platforms were selected"):
        _plan(selected=[])


def test_a_selection_with_nothing_publishable_is_refused_not_returned_empty() -> None:
    """An empty plan returned as a success reads as "done"."""
    with pytest.raises(CampaignRefusedError, match="can take a post right now"):
        _plan(accounts=_accounts(**{p: {"health": "suspended"} for p in AVAILABLE}))


def test_a_subject_is_required() -> None:
    with pytest.raises(CampaignRefusedError, match="needs a subject"):
        _plan(subject="   ")


# --------------------------------------------------------------------------- #
# Anchors
# --------------------------------------------------------------------------- #
def test_an_exact_match_commercial_anchor_is_refused_and_reported() -> None:
    """Reuses ``web2_anchor.check_anchor`` rather than re-deciding - that rule must not
    have a second, more permissive implementation in the broadcast path. And the refusal
    is REPORTED: an operator whose anchors are quietly replaced never learns the rule."""
    plan = _plan(anchors=["cctv drain survey"])
    assert any("was not used" in note for note in plan.notes)
    assert all(p.anchor == "Leeds Drainage Co" for p in plan.posts)


def test_the_brand_is_the_safe_floor_when_no_anchor_survives() -> None:
    plan = _plan(anchors=[])
    assert all(p.anchor == "Leeds Drainage Co" for p in plan.posts)
