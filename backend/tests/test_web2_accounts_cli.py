"""The Web 2.0 account registry's identity-hygiene rules (R2-08).

These tests cover the PURE half of ``app.cli.web2_accounts`` - the validation that
decides whether a proposed account may exist at all. That half carries the safety
property, so it is the half worth pinning:

the retired signup generator derived every handle from ``alias_for(platform, client_id)``,
which emitted TWO machine-readable tells - a shared platform slug at the front and the
first 10 hex characters of ``sha1(client_id)`` at the back - plus one shared catch-all
registration domain across the entire client base. Three joinable keys, so a platform
trust-and-safety team that suspended ONE account could enumerate the rest by prefix, by
suffix, and by registrant domain. No content-level check can see that, which is why it
is enforced at registration instead.

NO DB and NO vault here: ``build_spec`` and its validators are pure by construction.
"""

from __future__ import annotations

import pytest

from app.cli.web2_accounts import (
    OWNERSHIP_HOUSE,
    OWNERSHIP_PER_CLIENT,
    AccountSpec,
    HandleRejectedError,
    build_spec,
    platform_slug,
    validate_handle,
)

pytestmark = pytest.mark.unit

_CATCHALL = {"mail.qanry.com"}


def _spec(**over: object) -> AccountSpec:
    kwargs: dict[str, object] = {
        "platform": "Blogger",
        "ownership": OWNERSHIP_PER_CLIENT,
        "handle": "acmeroofing",
        "client_id": "11111111-1111-1111-1111-111111111111",
        "registration_email": "web@acmeroofing.co.uk",
        "property_url": "",
        "max_properties": 1,
        "credential": {"oauth_token": "t", "blog_id": "b"},
        "shared_domains": _CATCHALL,
    }
    kwargs.update(over)
    return build_spec(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# The two footprint tells the generated identities used to emit.
# --------------------------------------------------------------------------- #
def test_a_handle_embedding_the_platform_name_is_refused() -> None:
    with pytest.raises(HandleRejectedError, match="platform name"):
        validate_handle("blogger-acmeroofing", platform="Blogger")


def test_the_platform_check_ignores_punctuation_and_case() -> None:
    """'WordPress.com' reduces to 'wordpresscom', so 'WordPressCom-acme' is the same
    tell wearing different punctuation and must not slip through."""
    assert platform_slug("WordPress.com") == "wordpresscom"
    with pytest.raises(HandleRejectedError, match="platform name"):
        validate_handle("WordPressCom-acme", platform="WordPress.com")


def test_a_handle_carrying_a_hex_run_is_refused() -> None:
    # This is the exact shape the retired generator produced: sha1(client_id)[:10].
    with pytest.raises(HandleRejectedError, match="hex run"):
        validate_handle("acme-3f9a2b7c14", platform="Blogger")


def test_a_shorter_hex_fragment_is_still_caught() -> None:
    """The threshold is 8, not 10, so truncating the tell does not defeat the check."""
    with pytest.raises(HandleRejectedError, match="hex run"):
        validate_handle("acme-3f9a2b7c", platform="Blogger")


def test_a_real_brand_handle_passes() -> None:
    assert validate_handle("acmeroofing", platform="Blogger") == "acmeroofing"
    assert validate_handle("leeds-drainage-co", platform="Blogger") == "leeds-drainage-co"


def test_a_brand_handle_that_merely_contains_hex_letters_is_not_a_false_positive() -> None:
    """'decade' is all hex letters but only 6 long; 'facade' likewise. A brand whose
    name happens to use a/b/c/d/e/f must not be blocked - a validator that cries wolf
    gets routed around, and then the real tells ship."""
    assert validate_handle("facade-interiors", platform="Blogger") == "facade-interiors"


def test_an_empty_or_tiny_handle_is_refused() -> None:
    with pytest.raises(HandleRejectedError):
        validate_handle("   ", platform="Blogger")
    with pytest.raises(HandleRejectedError):
        validate_handle("ab", platform="Blogger")


# --------------------------------------------------------------------------- #
# Registration domain: the third joinable key.
# --------------------------------------------------------------------------- #
def test_a_per_client_account_may_not_register_on_the_shared_catchall() -> None:
    with pytest.raises(HandleRejectedError, match="catch-all"):
        _spec(registration_email="blogger-3f9a2b7c14@mail.qanry.com")


def test_a_per_client_account_requires_a_registration_email() -> None:
    with pytest.raises(HandleRejectedError, match="own domain"):
        _spec(registration_email="")


def test_a_house_account_may_use_the_shared_catchall() -> None:
    """House accounts are openly agency-owned and impersonate nobody, so the catch-all
    is honest there - the rule targets accounts that claim to be a client's."""
    spec = _spec(
        ownership=OWNERSHIP_HOUSE,
        client_id=None,
        handle="aios-house-telegraph",
        platform="Telegra.ph",
        registration_email="telegraph@mail.qanry.com",
        credential={"access_token": "t"},
    )
    assert spec.ownership == OWNERSHIP_HOUSE
    assert spec.registration_domain == "mail.qanry.com"


def test_a_house_handle_is_exempt_from_the_brand_rules() -> None:
    """'aios-house-telegraph' names the platform on purpose. Applying the per-client
    rule here would block the one naming scheme that is actually honest."""
    spec = _spec(
        ownership=OWNERSHIP_HOUSE, client_id=None, platform="Telegra.ph",
        handle="aios-house-telegraph", registration_email="", credential={"access_token": "t"},
    )
    assert spec.handle == "aios-house-telegraph"


# --------------------------------------------------------------------------- #
# The ownership contract (mirrors the DB CHECK constraints in 0100).
# --------------------------------------------------------------------------- #
def test_a_per_client_account_without_a_client_is_refused() -> None:
    with pytest.raises(ValueError, match="requires --client-id"):
        _spec(client_id=None)


def test_a_house_account_naming_a_client_is_refused() -> None:
    with pytest.raises(ValueError, match="must NOT name a client"):
        _spec(ownership=OWNERSHIP_HOUSE, client_id="11111111-1111-1111-1111-111111111111")


def test_an_unknown_platform_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown platform"):
        _spec(platform="NotARealPlatform")


# --------------------------------------------------------------------------- #
# Incomplete credentials are recorded, not rejected (they hold at review).
# --------------------------------------------------------------------------- #
def test_an_incomplete_credential_is_recorded_and_named() -> None:
    """Registering the account early is honest visibility - the credential factory
    already degrades an incomplete row to hold-at-review, so nothing can publish on
    it. Refusing here would just push the operator to invent a placeholder token."""
    spec = _spec(credential={"oauth_token": "t", "blog_id": ""})
    assert spec.missing_fields() == ["blog_id"]


def test_a_complete_credential_reports_nothing_missing() -> None:
    assert _spec().missing_fields() == []
