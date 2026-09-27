"""The placed-link ledger: what happened to a link over time, not just how it looks now.

``M05`` §3 and A8. ``web2_properties`` has carried ``link_found`` / ``link_rel`` /
``link_checked_at`` since migration 0028, and those three columns record **the latest
look and nothing else**. Each re-check overwrites the previous answer, so the question a
client report actually asks -

    "this link was live in March; when did we lose it?"

- has no answer anywhere in the system. The row simply changes.

A8 asks the platform to DETECT a removal and a newly-added ``nofollow``. Detection means
comparing against what was true before, which needs the previous fact kept. That is the
whole reason this is a table rather than three more columns.

THE STATE VOCABULARY IS ``live | removed | nofollowed | unknown``, and §3 attaches a rule
to it: *"each set from a fetch, never assumed"*. So:

* ``unknown`` means **nobody has looked** - and it must stay distinguishable from
  ``removed`` ("we looked and it was gone"). Collapsing the two is how a monitoring
  outage becomes a report full of lost links that were never actually lost.
* a transition INTO ``removed`` or ``nofollowed`` stamps ``lost_at`` once, and does not
  keep re-stamping it on every subsequent check - a link lost in March is not lost again
  every night.
* a link that comes BACK clears ``lost_at`` and keeps its original ``first_seen_at``. The
  history that matters is "live since X", and a platform that briefly 404s during a
  deploy should not reset a client's link age.

Pure: no DB, no clock, no network. The caller supplies the current row, the fetched
verdict and ``now``; this returns the fields to write. That keeps the state machine
unit-testable against every transition, which is the part worth being sure about.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

LinkState = Literal["live", "removed", "nofollowed", "unknown"]

#: States that mean the link is not doing its job. Reaching one of these from any other
#: state is the event a client report and an operator task are both built on.
LOST_STATES: frozenset[str] = frozenset({"removed", "nofollowed"})


@dataclass(frozen=True)
class LinkObservation:
    """One measured look at a placed link. Every field comes from a FETCH."""

    #: What the fetch found. ``unknown`` is what an unreachable page yields - never a
    #: guess about what is probably still there.
    state: LinkState
    rel: str = ""


@dataclass(frozen=True)
class LinkTransition:
    """What changed, and what to persist."""

    fields: dict[str, Any]
    previous: str
    current: str

    @property
    def changed(self) -> bool:
        return self.previous != self.current

    @property
    def newly_lost(self) -> bool:
        """The link was doing its job and now is not. The alertable event.

        Deliberately NOT "is currently lost": a link that has been gone for a month is
        not news, and alerting on the state rather than the transition produces a nightly
        alert for every historical loss until someone silences the channel.
        """
        return self.current in LOST_STATES and self.previous not in LOST_STATES

    @property
    def recovered(self) -> bool:
        return self.previous in LOST_STATES and self.current == "live"


def observe(
    existing: dict[str, Any] | None, seen: LinkObservation, *, now: datetime
) -> LinkTransition:
    """Fold one observation into the ledger row, returning the fields to write.

    ``existing`` is the current ``placed_links`` row, or None for a link never recorded.
    """
    previous = str((existing or {}).get("state") or "unknown")
    current = seen.state

    if current == "unknown":
        # WE COULD NOT LOOK. The last known state is kept, and only the check timestamp
        # moves - an unreachable page is a fact about our fetch, not about their link.
        # Overwriting `live` with `unknown` here would turn every transient network
        # failure into a client-visible loss of a link that is still there.
        #
        # EXCEPT on a first sighting, where there is no previous state to preserve. Then
        # `unknown` is written EXPLICITLY rather than left to the column default: a row
        # that exists and says "nobody has successfully looked yet" is a link the
        # re-check sweep will pick up, and it is legible to whoever reads the table. A
        # row whose state arrived by default is indistinguishable from one nothing has
        # decided about.
        fields: dict[str, Any] = {"last_checked_at": now}
        if existing is None:
            fields["state"] = "unknown"
            fields["rel"] = seen.rel
        return LinkTransition(
            fields=fields, previous=previous, current=previous
        )

    changed_fields: dict[str, Any] = {
        "state": current, "rel": seen.rel, "last_checked_at": now,
    }
    if current == "live":
        if not (existing or {}).get("first_seen_at"):
            changed_fields["first_seen_at"] = now
        # A link that came back keeps its ORIGINAL first_seen_at (above) and loses its
        # loss marker: "live since March, briefly unreachable in June" is the truth, and
        # resetting the age would quietly tell a client their oldest link is new.
        changed_fields["lost_at"] = None
    elif current in LOST_STATES and previous not in LOST_STATES:
        # Stamped ONCE, on the transition. Re-stamping every night would make every lost
        # link look freshly lost and destroy the only durable evidence of when it went.
        changed_fields["lost_at"] = now

    return LinkTransition(fields=changed_fields, previous=previous, current=current)


def state_from_check(found: bool | None, rel: str) -> LinkState:
    """Map ``web2_linkcheck``'s verdict onto the M05 state vocabulary.

    ``found`` is deliberately TRI-STATE in the existing checker and stays that way here:
    ``None`` means nobody looked (or the page was unreachable), which is ``unknown`` -
    not ``removed``.

    A link that is present but carries ``nofollow`` is its own state rather than a flavour
    of ``live``: it is on the page, and it passes nothing. Reporting it as live is how a
    campaign reports authority it never received.
    """
    if found is None:
        return "unknown"
    if not found:
        return "removed"
    return "nofollowed" if "nofollow" in (rel or "").lower() else "live"
