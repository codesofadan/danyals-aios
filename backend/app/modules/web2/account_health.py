"""Whether an account may publish RIGHT NOW - health, and the property cap.

``M05`` §1 names the failure this prevents in one line: *"Keep publishing to a limited
account and you lose it. We stop."* And §4 names the other: a house account with no cap
"can link 40 unrelated local businesses to one account", which hands a platform exactly
the pattern it polices.

BOTH CONTROLS EXISTED ON PAPER AND NEITHER WAS ENFORCED.

* ``web2_accounts.health`` has five states (``active`` / ``degraded`` / ``suspended`` /
  ``deleted`` / ``unverified``) and the credential check writes them. The publish path
  refused only ``suspended`` and ``deleted`` - so ``degraded``, the state that exists
  precisely to mean "this account is going wrong, stop before you lose it", published
  exactly as if it were healthy. The one state that is an early warning was the one
  state nothing acted on.
* ``web2_accounts.property_count`` and ``max_properties`` are declared in migration 0100,
  read by the repo, and rendered on the account board. ``property_count`` is **never
  incremented anywhere in the codebase** - verified by grep across ``app/``, ``workers/``
  and every migration. So the cap that bounds a shared account's blast radius reads 0/10
  forever and can never trip. A6 was unenforceable, not merely unenforced.

WHY A PURE MODULE. The same verdict is needed in three places - the publish worker
(refuse now), the campaign planner (do not plan onto an account that cannot take it) and
the account board (tell the operator why) - and three copies of a safety rule is how they
drift. This takes a row and returns a verdict; the DB work lives with its callers.

FAIL-CLOSED. An unreadable or unknown health value is treated as NOT publishable. The
cost of being wrong in that direction is a held placement an operator can release; the
cost in the other direction is a suspended account and every property on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

#: The states migration 0100 defines. Named here so a new state added to the enum without
#: a decision about what it MEANS for publishing fails the test rather than silently
#: falling into whichever branch happens to catch it.
HEALTH_ACTIVE: Final = "active"
HEALTH_DEGRADED: Final = "degraded"
HEALTH_SUSPENDED: Final = "suspended"
HEALTH_DELETED: Final = "deleted"
HEALTH_UNVERIFIED: Final = "unverified"

KNOWN_HEALTH: Final[frozenset[str]] = frozenset(
    {HEALTH_ACTIVE, HEALTH_DEGRADED, HEALTH_SUSPENDED, HEALTH_DELETED, HEALTH_UNVERIFIED}
)

#: The only state that may publish. Deliberately an ALLOW-list: a deny-list means every
#: future state is publishable by default, which is the wrong default for a control whose
#: failure mode is losing a client's account.
PUBLISHABLE_HEALTH: Final[frozenset[str]] = frozenset({HEALTH_ACTIVE})

Verdict = Literal["ok", "degraded", "suspended", "unverified", "capped", "unknown"]


@dataclass(frozen=True)
class AccountVerdict:
    """Whether this account may take another property, and why not if not."""

    verdict: Verdict
    reason: str = ""
    #: Whether an operator should be given a TASK about this, rather than just a refusal.
    #: `M05` REQ-W2-013: "a suspended account raises a task; it does not silently drop
    #: posts". A cap being reached is planning information, not an incident.
    raises_task: bool = False
    properties: int = 0
    cap: int = 0

    @property
    def publishable(self) -> bool:
        return self.verdict == "ok"

    @property
    def headroom(self) -> int:
        """Properties this account can still take. Negative is impossible by construction
        but clamped anyway - a negative headroom rendered on a board reads as a bug in the
        board rather than as data that was already wrong."""
        return max(self.cap - self.properties, 0)


def evaluate(row: dict[str, Any] | None) -> AccountVerdict:
    """Decide whether ``row`` (a ``web2_accounts`` record) may publish another property.

    Order matters and is not arbitrary: HEALTH is checked before the CAP, because
    "this account is suspended" and "this account is full" send an operator to completely
    different actions, and an account that is both should report the one that cannot be
    fixed by planning.
    """
    if row is None:
        return AccountVerdict(
            "unknown", "no account row: the placement has no publishing identity"
        )

    health = str(row.get("health") or "").strip().lower()
    if health not in KNOWN_HEALTH:
        # Fail closed. An unrecognised state is one nobody has reasoned about, and
        # publishing through it is a bet with an account as the stake.
        return AccountVerdict(
            "unknown",
            f"unrecognised account health {health or '(blank)'!r}: refusing to publish "
            "through an account whose state nothing has decided the meaning of",
        )

    if health == HEALTH_SUSPENDED:
        return AccountVerdict(
            "suspended",
            "the platform has suspended this account: publishing again risks the "
            "properties already on it",
            raises_task=True,
        )
    if health == HEALTH_DELETED:
        return AccountVerdict(
            "suspended", "this account no longer exists on the platform", raises_task=True
        )
    if health == HEALTH_DEGRADED:
        # THE STATE THAT WAS BEING IGNORED. `degraded` is the early warning - rate limits,
        # failed publishes, a challenge on login - and the whole point of having it is to
        # stop BEFORE the platform escalates to a suspension we cannot undo.
        return AccountVerdict(
            "degraded",
            "this account is degraded (failing publishes or rate-limited). M05 §1: keep "
            "publishing to a limited account and you lose it - it is out of scheduling "
            "until a credential check returns it to active",
            raises_task=True,
        )
    if health == HEALTH_UNVERIFIED:
        return AccountVerdict(
            "unverified",
            "this account has never passed a credential check, so nothing is known about "
            "it; run one before publishing through it",
        )

    properties = _int(row.get("property_count"))
    cap = _int(row.get("max_properties"))
    if cap > 0 and properties >= cap:
        return AccountVerdict(
            "capped",
            f"this account holds {properties} of its {cap} permitted properties. A house "
            "account that can link many unrelated businesses is the exact pattern a "
            "platform polices, so the cap is a hard stop rather than a suggestion",
            properties=properties,
            cap=cap,
        )
    return AccountVerdict("ok", properties=properties, cap=cap)


def selectable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The accounts a planner may choose from - those that can take another property.

    Used at PLAN time so a campaign is not laid out onto accounts that will refuse it at
    publish time. Planning onto a capped account and discovering it thirty drafts later
    is how a campaign silently delivers half of what was approved.
    """
    return [row for row in rows if evaluate(row).publishable]


def _int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0
