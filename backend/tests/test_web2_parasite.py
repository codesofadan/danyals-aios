"""Parasite Poster: borrow a host's authority, and MEASURE whether it worked.

``M05`` §6 - publish a useful page about a target term onto a high-authority third-party
domain, so the host's authority carries it into the SERP for a term the client's own site
cannot yet rank for. §6 is also explicit that this is "the part that gets abused", and the
guardrails are the feature:

* only where the platform's own terms permit it - and an UNREAD terms page is an unknown,
  not a yes;
* one page per term per host, because three is a doorway set;
* the ranking is the deliverable, "measured, not assumed".

The last one is why ``tracking_subscription`` exists and why migration 0152 had to widen
``tracked_keywords``' uniqueness key: subscribing a parasite page for a term the client
already tracked was silently skipped by ``on conflict do nothing``, and §6's premise is
that parasite pages target exactly those terms. The feature collided with itself and
reported success while nothing measured it.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.web2 import parasite as pp

pytestmark = pytest.mark.unit

TERM = "emergency drain unblocking"


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "authority_tier": "high", "terms_position": "permits",
        "link_verifiable": True, "mechanism": "api",
    }
    row.update(over)
    return row


def _account(**over: Any) -> dict[str, Any]:
    account: dict[str, Any] = {
        "id": "acc-1", "health": "active", "property_count": 0, "max_properties": 10,
    }
    account.update(over)
    return account


def _assess(platform: str = "Ghost", **over: Any) -> pp.HostVerdict:
    return pp.assess_host(
        platform,
        catalogue_row=over.pop("catalogue_row", _row(**over.pop("row", {}))),
        account=over.pop("account", _account()),
        existing_terms=over.pop("existing_terms", None),
        term=over.pop("term", TERM),
        min_authority=over.pop("min_authority", "medium"),
    )


# --------------------------------------------------------------------------- #
# The guardrails §6 names
# --------------------------------------------------------------------------- #
def test_a_permitted_high_authority_host_is_usable() -> None:
    assert _assess().usable


def test_an_unreviewed_terms_page_is_refused_rather_than_assumed_fine() -> None:
    """72 of the catalogue's rows sit at an unreviewed default. Reading that as permission
    would put client content on seventy platforms nobody has checked - and "we did not
    read the terms" is not permission."""
    verdict = _assess(row={"terms_position": ""})
    assert verdict.verdict == "terms_unreviewed"
    assert "read and date them" in verdict.reason


def test_a_platform_whose_terms_forbid_promotion_is_never_a_host() -> None:
    """§6: a platform that forbids promotional or third-party-client content is not a
    parasite host, however high its authority."""
    verdict = _assess(row={"terms_position": "forbids_promotional", "authority_tier": "high"})
    assert verdict.verdict == "terms_forbid"


def test_terms_permission_is_an_allow_list_not_a_deny_list() -> None:
    """A deny-list makes every unrecognised value permission by accident - including a
    value somebody adds later meaning the opposite."""
    for position in ("restricted", "unclear", "case_by_case", "do_not_use", "unknown"):
        assert _assess(row={"terms_position": position}).verdict == "terms_forbid"


def test_only_one_page_per_term_per_host() -> None:
    """Three pages about one term on one host is the doorway pattern - the specific thing
    that gets an account removed and burns the tactic for every client on it."""
    verdict = _assess(existing_terms={TERM})
    assert verdict.verdict == "already_placed"
    assert "doorway" in verdict.reason


def test_the_same_host_may_carry_a_different_term() -> None:
    assert _assess(existing_terms={"a completely different service"}).usable


def test_a_low_authority_host_is_refused_because_it_lends_nothing() -> None:
    """The entire tactic is borrowing the host's authority."""
    assert _assess(row={"authority_tier": "low"}).verdict == "low_authority"
    assert _assess(row={"authority_tier": "low"}, min_authority="low").usable


def test_a_short_form_platform_cannot_carry_a_ranking_page() -> None:
    """A 300-character note cannot rank for a commercial term, and shipping one as a
    "parasite page" is a deliverable that was never going to work."""
    verdict = _assess("Bluesky")
    assert verdict.verdict == "not_rankable"
    assert "words" in verdict.reason


def test_a_host_with_no_fetchable_page_is_refused() -> None:
    """§6 makes the RANKING the deliverable. A placement nobody can fetch produces a
    deliverable nobody can confirm - or notice the removal of."""
    assert _assess(row={"link_verifiable": False}).verdict == "not_verifiable"


def test_an_unusable_account_blocks_the_host() -> None:
    assert _assess(account=_account(health="degraded")).verdict == "account_unusable"
    assert _assess(
        account=_account(property_count=10, max_properties=10)
    ).verdict == "account_unusable"


def test_a_platform_rule_is_reported_before_one_of_our_own_problems() -> None:
    """"This platform forbids it" is permanent; "our account is full" is today's problem.
    Reporting the second when the first is true sends an operator to fix something that
    would not have helped."""
    verdict = _assess(
        row={"terms_position": "forbids_promotional"},
        account=_account(property_count=10, max_properties=10),
    )
    assert verdict.verdict == "terms_forbid"


def test_an_unsupported_platform_is_never_a_host() -> None:
    assert _assess("Medium").verdict == "unsupported"


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #
def _select(**over: Any) -> pp.ParasitePlan:
    kwargs: dict[str, Any] = {
        "term": TERM, "client_id": "c1", "client_name": "Leeds Drainage Co",
        "target_url": "https://leedsdrainage.co.uk/emergency",
        "candidates": ["Ghost", "Mataroa", "Bluesky", "Medium"],
        "catalogue": {
            "Ghost": _row(authority_tier="medium"),
            "Mataroa": _row(authority_tier="high"),
            "Bluesky": _row(authority_tier="high"),
            "Medium": _row(authority_tier="high"),
        },
        "accounts": {p: _account() for p in ("Ghost", "Mataroa", "Bluesky", "Medium")},
    }
    kwargs.update(over)
    return pp.select_host(**kwargs)


def test_the_highest_authority_lawful_host_wins() -> None:
    plan = _select()
    assert plan.platform == "Mataroa", "high authority beats Ghost's medium"
    assert plan.authority == "high"


def test_every_candidate_and_its_verdict_is_reported_not_just_the_winner() -> None:
    """A single recommendation with no runners-up is a black box, and an operator cannot
    tell a considered choice from a coincidence."""
    plan = _select()
    considered = {v.platform: v.verdict for v in plan.considered}
    assert considered == {
        "Ghost": "ok", "Mataroa": "ok", "Bluesky": "not_rankable", "Medium": "unsupported",
    }


def test_selection_is_deterministic() -> None:
    assert _select().platform == _select().platform


def test_no_lawful_host_refuses_with_every_reason() -> None:
    with pytest.raises(pp.ParasiteRefused) as caught:
        _select(catalogue={p: _row(terms_position="") for p in ("Ghost", "Mataroa", "Bluesky", "Medium")})
    assert "No host can carry" in str(caught.value)
    assert "terms" in str(caught.value)


def test_a_blank_term_is_refused() -> None:
    with pytest.raises(pp.ParasiteRefused, match="needs a target term"):
        _select(term="  ")


# --------------------------------------------------------------------------- #
# A11: the ranking is the deliverable
# --------------------------------------------------------------------------- #
def test_the_subscription_carries_the_hosted_url_as_its_discriminator() -> None:
    """THE fix that made A11 achievable. ``hosted_url`` is both the thing measured and
    what keeps this subscription distinct from the client's own tracking of the same term
    - without it, ``on conflict do nothing`` silently dropped the parasite subscription,
    and §6's premise is that these are terms the client already tracks."""
    subscription = pp.tracking_subscription(_select(), "https://mataroa.blog/x/drains")

    assert subscription["hosted_url"] == "https://mataroa.blog/x/drains"
    assert subscription["keyword"] == TERM
    assert subscription["client_id"] == "c1"


def test_the_clients_own_page_stays_the_target_url() -> None:
    """The parasite page LINKS to the client; the report is about whether that borrowed
    authority moved the client's business."""
    subscription = pp.tracking_subscription(_select(), "https://mataroa.blog/x/drains")
    assert subscription["target_url"] == "https://leedsdrainage.co.uk/emergency"


def test_the_subscription_is_tagged_so_a_report_can_tell_the_two_apart() -> None:
    """"We rank 3rd" and "a page we put on mataroa ranks 3rd" are different claims, and a
    client report that conflates them is misleading even when both are true."""
    tags = pp.tracking_subscription(_select(), "https://mataroa.blog/x")["tags"]
    assert "parasite" in tags
    assert "host:Mataroa" in tags


def test_a_subscription_without_the_hosted_url_is_refused() -> None:
    """An empty one silently re-creates the exact collision that made A11 unachievable."""
    with pytest.raises(pp.ParasiteRefused, match="needs the published page's URL"):
        pp.tracking_subscription(_select(), "   ")
