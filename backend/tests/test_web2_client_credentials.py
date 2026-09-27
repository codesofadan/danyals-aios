"""One client login reused everywhere - and the honest accounting of where it cannot be.

THE REQUIREMENT: the agency enters a client's username and password once, and every
platform uses that same login.

THE PART THAT CANNOT BE WISHED AWAY, and which these tests exist to keep visible:
measured against the adapters, a username and password publishes directly on **8** of 53
platforms. Two more take an app password generated inside the account. The remaining 43 -
including WordPress.com, Blogger, dev.to, Hashnode, Mastodon, GitHub and every mainstream
social network - require an OAuth grant or a personal access token, which no password can
substitute for.

A system that reported "connected" on the strength of a password alone would be claiming
a capability it does not have: the operator approves a campaign and watches it fail one
platform at a time, with nothing anywhere saying why. So the contract under test is that
every platform lands in exactly one of three honest buckets, and that ``ready`` is never
claimed on a guess.
"""

from __future__ import annotations

import pytest

from app.modules.web2 import client_credentials as cc
from integrations.web2_publishers import PLATFORM_CREDENTIAL_FIELDS

pytestmark = pytest.mark.unit


def _identity(**over: object) -> cc.ClientIdentity:
    kwargs: dict[str, object] = {
        "client_id": "c1", "username": "leedsdrainageco",
        "email": "web@leedsdrainage.co.uk", "reveal_password": lambda: "s3cret",
    }
    kwargs.update(over)
    return cc.ClientIdentity(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# The three buckets
# --------------------------------------------------------------------------- #
def test_a_password_platform_publishes_with_the_shared_login_alone() -> None:
    """LiveJournal's adapter takes ``(username, password)`` and nothing else. This is
    what the requirement asks for, and on these platforms it is exactly true."""
    plan = cc.plan_for_platform("LiveJournal", _identity())
    assert plan.ready
    assert set(plan.satisfied) == {"username", "password"}
    assert plan.missing_tokens == ()


def test_a_token_platform_needs_one_sign_in_step_and_says_which() -> None:
    """dev.to needs an API key from its settings page. The login gets the operator in;
    it cannot mint the key. Naming the action turns a mystery into a task."""
    plan = cc.plan_for_platform("dev.to", _identity())
    assert plan.readiness == "one_step"
    assert "api_key" in plan.missing_tokens
    assert "sign in to dev.to" in plan.action
    assert "leedsdrainageco" in plan.action, "the action names WHICH login to use"


def test_an_app_password_platform_is_distinguished_from_an_oauth_one() -> None:
    """Bluesky's app password is generated INSIDE the account - a different action from
    an OAuth consent screen, and an operator sent to the wrong one wastes the trip."""
    plan = cc.plan_for_platform("Bluesky", _identity())
    assert plan.readiness == "one_step"
    assert "generate an app password" in plan.action


def test_a_platform_missing_only_a_destination_is_not_a_credential_problem() -> None:
    """Drupal takes username + password + base_url. The credential is complete; what is
    missing is WHICH site. Reporting that as a connection failure sends an operator
    hunting for a password that is already there."""
    plan = cc.plan_for_platform("Drupal", _identity())
    assert plan.readiness == "one_step"
    assert plan.missing_targets == ("base_url",)
    assert plan.missing_tokens == ()
    assert "choose the destination" in plan.action


def test_an_unsupported_platform_is_blocked_whatever_the_credential() -> None:
    plan = cc.plan_for_platform("Medium", _identity())
    assert plan.readiness == "blocked"
    assert "no usable publishing API" in plan.reason


def test_a_platform_with_no_adapter_is_blocked_rather_than_assumed_fine() -> None:
    plan = cc.plan_for_platform("Threads", _identity())
    assert plan.readiness == "blocked"
    assert "no credential shape" in plan.reason


# --------------------------------------------------------------------------- #
# Fail-closed
# --------------------------------------------------------------------------- #
def test_an_unrecognised_credential_field_counts_as_missing_not_satisfied() -> None:
    """THE fail-closed rule. Guessing that an unknown field is covered produces a
    platform that reports ready and fails at publish time - the exact failure this module
    exists to prevent. A new adapter field is missing until somebody classifies it."""
    original = dict(PLATFORM_CREDENTIAL_FIELDS)
    try:
        PLATFORM_CREDENTIAL_FIELDS["Testville"] = ("username", "mystery_handshake")
        plan = cc.plan_for_platform("Testville", _identity())
        assert plan.readiness == "one_step"
        assert "mystery_handshake" in plan.missing_tokens
    finally:
        PLATFORM_CREDENTIAL_FIELDS.clear()
        PLATFORM_CREDENTIAL_FIELDS.update(original)


def test_a_client_with_no_password_cannot_publish_even_where_one_would_do() -> None:
    plan = cc.plan_for_platform("LiveJournal", _identity(reveal_password=None))
    assert not plan.ready
    assert "password" in plan.missing_tokens


def test_a_sealed_token_makes_a_platform_ready_without_asking_again() -> None:
    """A token fetched last month must not keep appearing as outstanding work."""
    asking = cc.plan_for_platform("dev.to", _identity())
    assert asking.readiness == "one_step"

    sealed = cc.plan_for_platform(
        "dev.to", _identity(), sealed_fields=frozenset({"api_key"})
    )
    assert sealed.ready


# --------------------------------------------------------------------------- #
# The operator-facing whole
# --------------------------------------------------------------------------- #
def test_the_plan_leads_with_what_works_and_names_what_remains() -> None:
    plan = cc.build_plan(["LiveJournal", "dev.to", "Bluesky", "Medium"], _identity())

    assert [p.platform for p in plan.ready] == ["LiveJournal"]
    assert {p.platform for p in plan.one_step} == {"dev.to", "Bluesky"}
    assert [p.platform for p in plan.blocked] == ["Medium"]
    assert "1 platform(s) publish now" in plan.summary()


def test_a_client_with_no_login_is_told_before_anything_else() -> None:
    plan = cc.build_plan(["LiveJournal"], _identity(username="", reveal_password=None))
    assert any("no shared login is set" in note for note in plan.notes)


def test_the_plan_explains_that_the_token_requirement_is_the_platforms_design() -> None:
    """An operator who supplied a correct password and sees 40 platforms still asking for
    something needs to know it is the API's design, not their mistake."""
    plan = cc.build_plan(sorted(PLATFORM_CREDENTIAL_FIELDS), _identity())
    assert any("the platform's API design" in note for note in plan.notes)


# --------------------------------------------------------------------------- #
# Building a real credential
# --------------------------------------------------------------------------- #
def test_a_credential_is_built_from_the_shared_login_where_that_suffices() -> None:
    credential = cc.credential_for("LiveJournal", _identity())
    assert credential == {"username": "leedsdrainageco", "password": "s3cret"}


def test_a_partial_credential_is_never_returned() -> None:
    """Half a credential fails at the API with an error that looks like a platform
    problem rather than a configuration one - and an operator debugs the wrong thing."""
    assert cc.credential_for("dev.to", _identity()) is None


def test_operator_supplied_destinations_complete_a_password_credential() -> None:
    credential = cc.credential_for(
        "Drupal", _identity(), extra={"base_url": "https://blog.leedsdrainage.co.uk"}
    )
    assert credential == {
        "base_url": "https://blog.leedsdrainage.co.uk",
        "username": "leedsdrainageco",
        "password": "s3cret",
    }


def test_the_password_is_only_revealed_when_a_credential_is_actually_built() -> None:
    """The callable exists so the secret is fetched at the moment of use, never held in a
    dataclass that could be logged, repr'd into an exception or checkpointed."""
    reveals = 0

    def reveal() -> str:
        nonlocal reveals
        reveals += 1
        return "s3cret"

    identity = _identity(reveal_password=reveal)
    cc.build_plan(sorted(PLATFORM_CREDENTIAL_FIELDS), identity)
    assert reveals == 0, "planning must never touch the password"

    cc.credential_for("LiveJournal", identity)
    assert reveals == 1


def test_the_directly_publishable_set_is_derived_from_the_adapters() -> None:
    """Hand-listing it would drift the moment an adapter changes its credential shape."""
    direct = cc.direct_login_platforms()
    assert "LiveJournal" in direct
    assert "Dreamwidth" in direct
    assert "dev.to" not in direct
    assert 0 < len(direct) < len(PLATFORM_CREDENTIAL_FIELDS)
