"""The provisioning tick: advance every queue item that can move without a human.

WHAT IT ACTUALLY DOES, and what it deliberately does not. Two jobs only:

  1. AUTO LANE - for the platforms with a real API signup, mint the account, seal the
     credential and mark it live. No human touches those at all.
  2. VERIFICATION WATCH - for guided items waiting on a platform's confirmation mail,
     read the client's own mailbox ONCE and, if the mail has arrived, capture the link
     and move the item on. The operator clicks a link that is already in front of them
     instead of hunting through an inbox.

It does NOT drive a browser through a signup form. Tumblr's guidelines forbid registering
accounts "automatically, systematically, or programmatically", and an account created
that way is a client asset built on a terms breach (R2 §3.2 / R2c). The guided lane is a
deliberate design, not a gap waiting to be automated.

ONE CHECK PER TICK, NEVER A SLEEP-LOOP. `wait_for_message` blocks a worker slot for its
whole timeout; twenty pending signups would hold twenty workers asleep. Each tick checks
once and returns, and the next tick checks again - the same total waiting with no held
resources. That is why `ImapMailbox.check_once` exists.

Pure decisions here; the caller owns the DB and the I/O seams.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.services.web2_provisioning_queue import lane_for


@dataclass(frozen=True)
class TickAction:
    """One decided move, ready for the caller to perform."""

    item_id: str
    platform: str
    to_status: str
    note: str = ""
    verify_link: str = ""
    #: Set when the auto lane minted a credential that still needs sealing.
    credential: dict[str, str] = field(default_factory=dict)
    handle: str = ""


@dataclass(frozen=True)
class TickReport:
    """What one sweep did, in the shape the API and the logs both want."""

    checked: int = 0
    advanced: int = 0
    failed: int = 0
    actions: list[TickAction] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"checked": self.checked, "advanced": self.advanced, "failed": self.failed}


def decide_auto_signup(
    item: dict[str, Any], *, signup: Callable[[str, str], tuple[str, dict[str, str], str]]
) -> TickAction | None:
    """Run the API signup for one auto-lane item and decide where it lands.

    ``signup`` is injected (platform, handle) -> (status, credentials, error), so this
    stays testable offline against the same statuses the real providers return.
    """
    platform = str(item.get("platform") or "")
    if lane_for(platform) != "auto":
        return None
    item_id = str(item.get("id") or "")
    handle = str(item.get("handle") or "")
    status, credential, error = signup(platform, handle)
    if status == "created" and credential:
        return TickAction(
            item_id=item_id, platform=platform, to_status="live",
            credential=dict(credential), handle=handle,
        )
    # A blocked signup is a real answer, not a retry: it means the platform refused
    # something only a human can resolve. Saying so beats silently re-attempting.
    return TickAction(
        item_id=item_id, platform=platform, to_status="blocked",
        note=(
            error
            or f"{platform} did not complete an automatic signup ({status}). "
            "Create it by hand and add the token."
        ),
    )


def decide_verification(
    item: dict[str, Any],
    *,
    check: Callable[[str, datetime], tuple[bool, str]],
    since: datetime,
) -> TickAction | None:
    """Look once for this item's confirmation mail and decide whether it can move on.

    Not finding it is NOT a failure - platforms send on their own schedule, so the item
    simply stays where it is and the next tick looks again. Reporting "failed" here
    would turn ordinary waiting into noise an operator learns to ignore.
    """
    item_id = str(item.get("id") or "")
    platform = str(item.get("platform") or "")
    found, link = check(str(item.get("registration_email") or ""), since)
    if not found:
        return None
    return TickAction(
        item_id=item_id,
        platform=platform,
        to_status="awaiting_credential",
        verify_link=link,
        note="Confirmation email found." if link else "Confirmation email found (no link in it).",
    )
