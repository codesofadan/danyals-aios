"""One client login, reused everywhere it can be - and an honest plan for where it cannot.

THE OPERATOR'S REQUIREMENT: the agency enters a client's username and password once, and
every platform that client publishes to uses that same login. No thirty forms.

THE PART THAT CANNOT BE WISHED AWAY, measured against the adapters rather than assumed::

    username + password publishes directly     8 platforms
    an APP PASSWORD generated in-account       2 platforms  (Bluesky, WhiteWind)
    a token or an OAuth grant is required     43 platforms  (WordPress.com, Blogger,
                                                            dev.to, Hashnode, Mastodon,
                                                            GitHub, every social network)

So the shared credential is the client's IDENTITY on all 53, and the PUBLISHING credential
on 43 of them is a token that identity still has to go and fetch. A system that reported
"connected" on the strength of a password alone would be reporting a capability it does
not have - the operator would approve a campaign and watch it fail one platform at a time.

WHAT THIS MODULE DOES INSTEAD. It takes the client's one credential and produces a plan
per platform, in three honest buckets:

* ``ready``    - publishes right now with the shared login, or with a token already sealed
                 in the vault for this client's account;
* ``one_step`` - the shared login is enough to SIGN IN, and one human action (generate an
                 app password / click through an OAuth consent) yields the token. The
                 action is named, so it is a task rather than a mystery;
* ``blocked``  - the platform has no usable API at all (`M05` REQ-W2-002), so no credential
                 of any kind helps.

An operator then sees "12 ready, 9 need one click, 3 unsupported" rather than a grid of
cards that all say Connect and a campaign that half-publishes.

THE CREDENTIAL ITSELF IS NEVER HELD HERE. This module takes a :class:`ClientIdentity`
carrying the username and a *callable* that reveals the password from the vault, and it
never logs either. The password unlocks every platform the client is on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from app.modules.web2.platform_spec import UNSUPPORTED_PLATFORMS
from integrations.web2_publishers import PLATFORM_CREDENTIAL_FIELDS

Readiness = Literal["ready", "one_step", "blocked"]

#: Credential field names that the shared client login satisfies directly.
_USERNAME_FIELDS: Final[frozenset[str]] = frozenset({"username", "user", "identifier", "hatena_id"})
_PASSWORD_FIELDS: Final[frozenset[str]] = frozenset({"password", "pass"})

#: Fields a human generates INSIDE the account once signed in. The shared login gets them
#: there; it cannot mint the value itself.
_APP_PASSWORD_FIELDS: Final[frozenset[str]] = frozenset({"app_password"})

#: Fields that are an OAuth grant or a personal access token - a consent click or a
#: settings page, never derivable from a password.
_TOKEN_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "oauth_token", "access_token", "token", "api_key", "api_token", "pat",
        "admin_api_key", "access_key", "secret_key", "app_key", "consumer_key",
        "client_secret", "refresh_token",
    }
)

#: Fields that are neither secret nor derivable: WHICH blog, WHICH repo, WHICH instance.
#: An operator supplies them once per account; they are not a credential problem.
_TARGET_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "site", "blog_id", "blog", "owner", "repo", "project_id", "publication_id",
        "instance_url", "base_url", "api_url", "endpoint", "community", "content_group_id",
    }
)


@dataclass(frozen=True)
class ClientIdentity:
    """The one login a client uses everywhere.

    ``reveal_password`` is a callable rather than a string so the secret is fetched from
    the vault only at the moment a credential is actually built, and never sits in a
    dataclass that might be logged, repr'd into an exception, or checkpointed into graph
    state.
    """

    client_id: str
    username: str
    email: str = ""
    reveal_password: Callable[[], str] | None = None

    @property
    def usable(self) -> bool:
        """Whether there is enough here to authenticate anywhere at all."""
        return bool(self.username.strip()) and self.reveal_password is not None


@dataclass(frozen=True)
class PlatformPlan:
    """What this platform needs before it can publish for this client."""

    platform: str
    readiness: Readiness
    #: The one human action that moves ``one_step`` to ``ready``. Empty when ready.
    action: str = ""
    #: Credential fields the shared login satisfies by itself.
    satisfied: tuple[str, ...] = ()
    #: Fields that still need a value, and what kind each is.
    missing_tokens: tuple[str, ...] = ()
    missing_targets: tuple[str, ...] = ()
    reason: str = ""

    @property
    def ready(self) -> bool:
        return self.readiness == "ready"


@dataclass(frozen=True)
class ConnectionPlan:
    """The whole picture for one client, as an operator would read it."""

    client_id: str
    plans: tuple[PlatformPlan, ...] = ()
    notes: list[str] = field(default_factory=list)

    @property
    def ready(self) -> tuple[PlatformPlan, ...]:
        return tuple(p for p in self.plans if p.readiness == "ready")

    @property
    def one_step(self) -> tuple[PlatformPlan, ...]:
        return tuple(p for p in self.plans if p.readiness == "one_step")

    @property
    def blocked(self) -> tuple[PlatformPlan, ...]:
        return tuple(p for p in self.plans if p.readiness == "blocked")

    def summary(self) -> str:
        """The one line a connection screen shows.

        Deliberately leads with what WORKS, then names the work remaining, because the
        honest answer to "is this client connected?" is a number, not a yes or a no.
        """
        return (
            f"{len(self.ready)} platform(s) publish now, {len(self.one_step)} need one "
            f"sign-in step, {len(self.blocked)} have no usable API"
        )


def plan_for_platform(
    platform: str,
    identity: ClientIdentity,
    *,
    sealed_fields: frozenset[str] = frozenset(),
) -> PlatformPlan:
    """What ``platform`` needs before it can publish for this client.

    ``sealed_fields`` names credential fields already held in the vault for this client's
    account on this platform - so a platform whose token was fetched last month reports
    ``ready`` rather than asking for it again.
    """
    if platform in UNSUPPORTED_PLATFORMS:
        return PlatformPlan(
            platform, "blocked",
            reason=(
                f"{platform} has no usable publishing API (M05 REQ-W2-002), so no "
                "credential of any kind makes it publishable"
            ),
        )

    required = PLATFORM_CREDENTIAL_FIELDS.get(platform)
    if required is None:
        return PlatformPlan(
            platform, "blocked",
            reason=f"no credential shape is defined for {platform}: the pipeline has no adapter",
        )

    satisfied: list[str] = []
    tokens: list[str] = []
    targets: list[str] = []
    app_passwords: list[str] = []

    for raw in required:
        field_name = raw.lower()
        # Three DIFFERENT reasons a field is already covered, kept as three branches on
        # purpose: "a token is sealed in the vault", "the shared username supplies it" and
        # "the shared password supplies it" are distinct facts about this platform, and a
        # future reader deciding whether to add a fourth needs to see which is which. A
        # linter will offer to collapse them into one `or`; it is the same boolean and a
        # worse explanation.
        if field_name in sealed_fields:  # noqa: SIM114 - see above
            satisfied.append(raw)
        elif field_name in _USERNAME_FIELDS and identity.username.strip():  # noqa: SIM114
            satisfied.append(raw)
        elif field_name in _PASSWORD_FIELDS and identity.reveal_password is not None:
            satisfied.append(raw)
        elif field_name in _APP_PASSWORD_FIELDS:
            app_passwords.append(raw)
        elif field_name in _TOKEN_FIELDS:
            tokens.append(raw)
        elif field_name in _TARGET_FIELDS:
            targets.append(raw)
        else:
            # An unrecognised field is treated as a TOKEN, not as satisfied. Fail-closed:
            # guessing that an unknown field is covered produces a platform that reports
            # ready and fails at publish time, which is the failure this module exists to
            # prevent.
            tokens.append(raw)

    if not tokens and not app_passwords and not targets:
        return PlatformPlan(platform, "ready", satisfied=tuple(satisfied))

    if app_passwords and not tokens:
        return PlatformPlan(
            platform, "one_step",
            action=(
                f"sign in to {platform} as {identity.username or 'the client'} and "
                f"generate an app password ({', '.join(app_passwords)})"
            ),
            satisfied=tuple(satisfied), missing_tokens=tuple(app_passwords),
            missing_targets=tuple(targets),
        )

    if not tokens and targets:
        # Only "which blog / which repo" is missing. Not a credential problem at all -
        # an operator types it once, so it is reported as a setup step rather than as a
        # connection failure an operator might go hunting for a password to solve.
        return PlatformPlan(
            platform, "one_step",
            action=f"choose the destination on {platform} ({', '.join(targets)})",
            satisfied=tuple(satisfied), missing_targets=tuple(targets),
        )

    return PlatformPlan(
        platform, "one_step",
        action=(
            f"sign in to {platform} as {identity.username or 'the client'} and authorise "
            f"the app, then record {', '.join(tokens)}"
            + (f" and {', '.join(targets)}" if targets else "")
        ),
        satisfied=tuple(satisfied), missing_tokens=tuple(tokens),
        missing_targets=tuple(targets),
    )


def build_plan(
    platforms: list[str],
    identity: ClientIdentity,
    *,
    sealed_by_platform: dict[str, frozenset[str]] | None = None,
) -> ConnectionPlan:
    """The full connection picture for one client across ``platforms``."""
    sealed = sealed_by_platform or {}
    notes: list[str] = []
    if not identity.usable:
        notes.append(
            "no shared login is set for this client: add a username and password before "
            "connecting platforms - without one, even the platforms that accept a "
            "password directly cannot publish"
        )
    plans = tuple(
        plan_for_platform(
            platform, identity, sealed_fields=sealed.get(platform, frozenset())
        )
        for platform in platforms
    )
    one_step = sum(1 for p in plans if p.readiness == "one_step")
    if one_step:
        notes.append(
            f"{one_step} platform(s) accept the client's login to SIGN IN but need a "
            "token to publish - that is the platform's API design, not a gap in the "
            "credential: 43 of the 53 adapters require an OAuth grant or a personal "
            "access token that no password can substitute for"
        )
    return ConnectionPlan(client_id=identity.client_id, plans=plans, notes=notes)


def credential_for(
    platform: str, identity: ClientIdentity, *, extra: dict[str, Any] | None = None
) -> dict[str, str] | None:
    """Build the platform credential from the shared login, or None if it cannot be.

    Only ever returns a credential for a platform whose every required field is covered
    by the shared login plus ``extra`` (the operator-supplied destination fields). A
    partial credential is never returned: half a credential fails at the API with an
    error that looks like a platform problem rather than a configuration one.
    """
    required = PLATFORM_CREDENTIAL_FIELDS.get(platform)
    if required is None or not identity.usable or platform in UNSUPPORTED_PLATFORMS:
        return None

    supplied = {key.lower(): str(value) for key, value in (extra or {}).items() if value}
    credential: dict[str, str] = {}
    for raw in required:
        key = raw.lower()
        if key in supplied:
            credential[raw] = supplied[key]
        elif key in _USERNAME_FIELDS:
            credential[raw] = identity.username
        elif key in _PASSWORD_FIELDS and identity.reveal_password is not None:
            credential[raw] = identity.reveal_password()
        else:
            return None
    return credential


def direct_login_platforms() -> tuple[str, ...]:
    """Platforms publishable with the shared login alone - the list an operator can act on.

    Derived from the adapters rather than hand-listed, so a new adapter that accepts a
    password appears here without anyone remembering to add it.
    """
    probe = ClientIdentity(client_id="", username="probe", reveal_password=lambda: "x")
    return tuple(
        platform
        for platform in sorted(PLATFORM_CREDENTIAL_FIELDS)
        if plan_for_platform(platform, probe).ready
    )
