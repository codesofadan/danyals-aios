"""The Web 2.0 account provisioning queue: lanes, legal transitions, and readiness.

WHAT THIS MODULE IS FOR. Turning "this client should publish on nine platforms" into
nine tracked pieces of work that survive being half-finished. The old shape - a form per
account - is fine once and unusable at twenty clients, because nothing recorded an
account we INTENDED, so there was no progress to resume, nothing to hand to a colleague,
and no answer to "what is left?".

WHY THE STATE MACHINE IS EXPLICIT RATHER THAN A BOOLEAN. Account creation genuinely has
distinct waits with different owners: we decide the identity, a HUMAN (or an API) creates
the account, the PLATFORM sends mail on its own schedule, and only then does a token
exist to seal. Collapsing those into "done / not done" is what makes an operator re-read
a guide to work out where they got to. Each state names who is holding the ball.

Pure: takes rows and facts, returns decisions. No DB, no clock of its own, no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

Status = Literal[
    "queued",
    "identity_ready",
    "awaiting_account",
    "awaiting_verification",
    "awaiting_credential",
    "live",
    "blocked",
    "cancelled",
]
Lane = Literal["auto", "guided"]

#: Platforms whose signup we can drive end to end through a documented API.
#: Deliberately short and measured, not aspirational: `api_signup_provider_for` returns
#: a provider for exactly these, and claiming a lane the code cannot drive would park
#: work in `awaiting_account` forever while reporting it automatic.
AUTO_LANE_PLATFORMS: frozenset[str] = frozenset({"Telegra.ph", "Write.as"})

#: What may follow what. A transition missing here is not an oversight - it is a claim
#: the queue refuses to record (e.g. jumping straight to `live` without a credential,
#: which would leave the accounts board green with nothing sealed behind it).
_ALLOWED: dict[str, frozenset[str]] = {
    "queued": frozenset({"identity_ready", "blocked", "cancelled"}),
    "identity_ready": frozenset({"awaiting_account", "blocked", "cancelled"}),
    "awaiting_account": frozenset(
        {"awaiting_verification", "awaiting_credential", "blocked", "cancelled"}
    ),
    # Verification can be skipped by platforms that never send mail, so it may go
    # straight to the credential step - but never straight to live.
    "awaiting_verification": frozenset({"awaiting_credential", "blocked", "cancelled"}),
    "awaiting_credential": frozenset({"live", "blocked", "cancelled"}),
    # A live account can still degrade back into the queue (a revoked token), which is
    # how a suspended account becomes visible work again rather than a silent failure.
    "live": frozenset({"blocked", "cancelled"}),
    "blocked": frozenset(
        {"identity_ready", "awaiting_account", "awaiting_verification",
         "awaiting_credential", "cancelled"}
    ),
    "cancelled": frozenset(),
}


class TransitionRefusedError(ValueError):
    """A move the queue will not record, named so the caller can explain it."""


@dataclass(frozen=True)
class IdentityFacts:
    """What the client's standing identity (0122) provides to a signup."""

    handle_base: str = ""
    contact_email: str = ""
    mailbox_ready: bool = False

    @classmethod
    def from_row(cls, row: dict[str, Any] | None) -> IdentityFacts:
        if not row:
            return cls()
        host = str(row.get("web2_imap_host") or "")
        user = str(row.get("web2_imap_user") or "")
        label = str(row.get("web2_imap_vault_label") or "")
        return cls(
            handle_base=str(row.get("web2_handle_base") or ""),
            contact_email=str(row.get("web2_contact_email") or ""),
            mailbox_ready=bool(host and user and label),
        )


def lane_for(platform: str) -> Lane:
    """Which lane this platform's signup runs in. A fact about the platform."""
    return "auto" if platform in AUTO_LANE_PLATFORMS else "guided"


def handle_for(platform: str, identity: IdentityFacts) -> str:
    """The account handle this signup will use.

    Derived from the client's BRAND stem, never generated. R2-08, measured: a handle
    built from the platform slug plus a hash of the client id gives every account of
    ours two joinable keys, so suspending one account is enough to enumerate the rest.
    A brand handle carries neither. Returns "" when no stem is set, which is a
    `blocked` reason rather than a licence to invent one.
    """
    stem = "".join(ch for ch in identity.handle_base.lower() if ch.isalnum())
    return stem[:24]


@dataclass(frozen=True)
class Readiness:
    """Whether a queued item can start, and what is missing if it cannot."""

    ready: bool
    reason: str = ""


def readiness_for(platform: str, identity: IdentityFacts) -> Readiness:
    """Can this item leave `queued`?

    The two blockers are the two things only a human can supply, and naming which one is
    missing is the difference between a two-minute fix and a support ticket.
    """
    if not handle_for(platform, identity):
        return Readiness(
            False,
            "No handle base is set for this client. Set the publishing identity first - "
            "handles come from the client's brand, never generated.",
        )
    if not identity.contact_email:
        return Readiness(
            False,
            "No client email is set. Platform verification mail has to land somewhere on "
            "the CLIENT's own domain - set the publishing identity first.",
        )
    return Readiness(True)


def next_status(current: str, target: str) -> Status:
    """Validate a move, or refuse it by name."""
    allowed = _ALLOWED.get(current, frozenset())
    if target not in allowed:
        raise TransitionRefusedError(
            f"A provisioning item cannot go from {current!r} to {target!r}. "
            f"From {current!r} the queue accepts: {', '.join(sorted(allowed)) or 'nothing'}."
        )
    return target  # type: ignore[return-value]


def plan_items(
    platforms: Iterable[str],
    *,
    identity: IdentityFacts,
    existing: Sequence[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    """What queueing these platforms for this client would create.

    Idempotent by construction: a platform already in flight is REPORTED rather than
    duplicated, because the table's partial unique index would refuse the insert anyway
    and an operator re-running the builder should see "already queued", not an error.
    """
    live = {
        str(row.get("platform")): str(row.get("status"))
        for row in existing
        if str(row.get("status")) != "cancelled"
    }
    out: list[dict[str, Any]] = []
    for platform in platforms:
        if platform in live:
            out.append(
                {"platform": platform, "action": "skipped", "note": f"already {live[platform]}"}
            )
            continue
        check = readiness_for(platform, identity)
        out.append(
            {
                "platform": platform,
                "action": "queued",
                "lane": lane_for(platform),
                "handle": handle_for(platform, identity),
                "registration_email": identity.contact_email,
                "status": "identity_ready" if check.ready else "blocked",
                "note": "" if check.ready else check.reason,
            }
        )
    return out
