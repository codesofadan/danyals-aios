"""The anchor bank: a distribution ENFORCED at plan time, not audited afterwards.

``M05`` REQ-W2-010 and A5. ``web2_anchor`` already refuses the one anchor shape that has
no editorial justification at any ratio - an anchor that is exactly the money phrase the
destination is trying to rank. That is a FLOOR, and it is correct.

WHAT IT CANNOT SEE. A floor judges one anchor against one target. A link profile is judged
on its SHAPE: fifty links that are individually defensible are still a pattern if forty of
them are partial-match commercial phrases. REQ-W2-010 asks for "branded / naked /
partial-match / exact-match shares, with a hard cap on exact-match", and A5 for the share
never to exceed its cap "across a full campaign".

WHY ASSIGNMENT AND NOT AUDIT. The requirement says the distribution is "enforced at plan
time, not audited afterwards", and the difference is the whole value: an audit tells you
about a profile you have already built and published. By then the links exist, on pages
you do not control, and the remedy is asking a platform to edit or remove a post. Assigning
from a bank means the profile that gets built is the profile that was approved.

THE CLASSIFICATION IS DERIVED, NOT DECLARED. An operator typing anchors into a form will
not label them, and one who is asked to will label them optimistically. So an anchor's kind
is computed from the anchor and its destination - the same inputs ``web2_anchor`` already
uses - and the bank's shares are checked against what the anchors ARE.

EXACT MATCH IS NOT RATIONED HERE, IT IS ABSENT. ``web2_anchor.check_anchor`` refuses those
outright, so the bank never holds one to ration. The cap below exists as a belt-and-braces
assertion: if one ever reaches the bank, the assignment refuses rather than spending a
budget on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal

from app.services.web2_anchor import check_anchor, money_phrase

AnchorKind = Literal["branded", "naked", "partial", "exact", "generic"]

#: The default distribution. Percentages of a campaign's placements.
#:
#: THESE ARE NOT A PUBLISHED SAFE RATIO - no such number exists, and ``web2_anchor``'s
#: header says so at length about exact-match. They encode the SHAPE a natural editorial
#: profile has: mostly the brand and bare URLs, some descriptive phrases, and no exact
#: money-phrase anchors at all. The shares are configurable per client precisely because
#: they are a posture rather than a finding.
DEFAULT_SHARES: Final[dict[AnchorKind, float]] = {
    "branded": 0.55,
    "naked": 0.20,
    "generic": 0.15,
    "partial": 0.10,
    "exact": 0.0,
}

#: Anchors that are a bare URL. Natural editorial links are full of these.
_URL_PREFIXES: Final[tuple[str, ...]] = ("http://", "https://", "www.")

#: Ordinary link text carrying no commercial phrase - "read more", "this guide".
_GENERIC_ANCHORS: Final[frozenset[str]] = frozenset(
    {
        "here", "this", "this page", "this guide", "this article", "read more",
        "more", "learn more", "find out more", "see more", "click here", "the site",
        "their website", "our website", "the guide", "full details", "details",
    }
)


@dataclass(frozen=True)
class BankedAnchor:
    """One anchor an operator supplied, with what it actually IS and how far it has run."""

    text: str
    kind: AnchorKind
    used: int = 0
    #: A per-anchor ceiling. ``0`` means "no ceiling of its own" - the distribution still
    #: binds it. Matters because one anchor repeated across a whole campaign is its own
    #: footprint even when its KIND is safe.
    cap: int = 0

    @property
    def exhausted(self) -> bool:
        return self.cap > 0 and self.used >= self.cap


@dataclass(frozen=True)
class Assignment:
    """The anchors a campaign will actually use, in placement order."""

    anchors: tuple[str, ...] = ()
    kinds: tuple[AnchorKind, ...] = ()
    notes: list[str] = field(default_factory=list)

    def distribution(self) -> dict[AnchorKind, float]:
        """The share each kind actually got - what A5 asserts against."""
        if not self.kinds:
            return {}
        total = len(self.kinds)
        counts: dict[AnchorKind, int] = {}
        for kind in self.kinds:
            counts[kind] = counts.get(kind, 0) + 1
        return {kind: count / total for kind, count in counts.items()}


class AnchorBankRefused(ValueError):  # noqa: N818 - a planning verdict, not a fault
    """The requested placements cannot be anchored within the distribution."""


def classify(anchor: str, *, target_url: str, client_name: str, topic: str = "") -> AnchorKind:
    """What KIND of anchor this is, derived from the anchor and its destination.

    Derived rather than declared because an operator typing anchors into a form will not
    label them, and one who is asked to will label them optimistically - which turns the
    distribution into a self-report.

    Order matters: a bare URL that happens to contain the brand is a NAKED link, not a
    branded one, and an anchor that is exactly the money phrase is exact-match even if it
    also contains the brand name.
    """
    text = anchor.strip()
    lowered = text.lower()
    if not text:
        return "generic"
    if lowered.startswith(_URL_PREFIXES):
        return "naked"
    if lowered in _GENERIC_ANCHORS:
        return "generic"

    # `check_anchor` owns the exact-match rule. Asking it here rather than re-deriving
    # means there is ONE definition of "this is the money phrase", and the bank cannot
    # drift into a more permissive one than the gate that refuses placements.
    if not check_anchor(
        text, target_url=target_url, topic=topic, client_name=client_name
    ).allowed:
        return "exact"

    brand = {word for word in client_name.lower().split() if len(word) > 2}
    words = {word for word in lowered.replace("-", " ").split() if len(word) > 2}
    if brand and brand <= words:
        return "branded"

    money = {word for word in money_phrase(target_url, topic) if len(word) > 2}
    if money and words & money:
        # Contains some of the money phrase but is not all of it: partial match. The kind
        # a profile can carry a little of and should not be built from.
        return "partial"
    return "generic"


def build_bank(
    anchors: list[str], *, target_url: str, client_name: str, topic: str = ""
) -> tuple[list[BankedAnchor], list[str]]:
    """Turn an operator's anchor list into a classified bank, reporting what was refused.

    A refused anchor is REPORTED rather than silently dropped: an operator whose anchors
    disappear without explanation supplies the same list next time.
    """
    notes: list[str] = []
    bank: list[BankedAnchor] = []
    for raw in dict.fromkeys(a.strip() for a in anchors if a.strip()):
        verdict = check_anchor(
            raw, target_url=target_url, topic=topic, client_name=client_name
        )
        if not verdict.allowed:
            notes.append(f"Anchor '{raw}' was not banked: {verdict.reason}")
            continue
        bank.append(
            classify_into(raw, target_url=target_url, client_name=client_name, topic=topic)
        )
    if not bank:
        # The brand is the safe floor - never leave a placement with no link text.
        bank.append(BankedAnchor(text=client_name, kind="branded"))
        notes.append(
            f"No supplied anchor was usable, so '{client_name}' (the brand) was banked. "
            "Brand, brand + location, a natural sentence fragment, or a bare URL all work."
        )
    return bank, notes


def classify_into(
    anchor: str, *, target_url: str, client_name: str, topic: str = "", cap: int = 0
) -> BankedAnchor:
    """One classified bank entry."""
    return BankedAnchor(
        text=anchor,
        kind=classify(anchor, target_url=target_url, client_name=client_name, topic=topic),
        cap=cap,
    )


def assign(
    bank: list[BankedAnchor],
    count: int,
    *,
    shares: dict[AnchorKind, float] | None = None,
) -> Assignment:
    """Assign ``count`` anchors from ``bank``, holding the distribution.

    Walks the placements in order, each time choosing from the kind that is furthest
    BELOW its target share. That keeps the profile within the distribution at every
    prefix, not merely at the end - which matters because a campaign can be paused, and a
    profile that only balances if every placement publishes is not a profile that was
    controlled.
    """
    if count <= 0:
        raise AnchorBankRefused("A campaign needs at least one placement to anchor.")
    usable = [entry for entry in bank if not entry.exhausted]
    if not usable:
        raise AnchorBankRefused(
            "Every banked anchor has reached its own cap. Add more anchors, or raise a "
            "cap deliberately - reusing one anchor across a campaign is its own footprint."
        )

    targets = dict(shares or DEFAULT_SHARES)
    notes: list[str] = []
    by_kind: dict[AnchorKind, list[BankedAnchor]] = {}
    for entry in usable:
        by_kind.setdefault(entry.kind, []).append(entry)

    if "exact" in by_kind:
        # Belt and braces: `check_anchor` refuses these before they reach a bank, so one
        # arriving here means something bypassed the gate. Refusing is the only safe
        # response - rationing would spend a budget on the exact shape A5 caps at zero.
        raise AnchorBankRefused(
            "An exact-match commercial anchor reached the bank. These have no editorial "
            "justification at any ratio and are refused rather than rationed."
        )

    available = {kind: share for kind, share in targets.items() if kind in by_kind}
    if not available:
        raise AnchorBankRefused(
            "None of the banked anchors match any kind in the distribution policy."
        )
    total_share = sum(available.values())
    if total_share <= 0:
        # Every available kind is capped at zero. Falling back to "use them anyway" would
        # silently ignore the policy, so say what happened.
        available = dict.fromkeys(available, 1.0)
        total_share = float(len(available))
        notes.append(
            "The distribution policy allows none of the banked anchor kinds, so they were "
            "used evenly. Set shares for the kinds you actually supply."
        )
    normalised = {kind: share / total_share for kind, share in available.items()}

    chosen: list[str] = []
    kinds: list[AnchorKind] = []
    used_counts: dict[AnchorKind, int] = dict.fromkeys(normalised, 0)
    rotation: dict[AnchorKind, int] = dict.fromkeys(normalised, 0)

    for placed in range(count):
        # The kind furthest below its target share, measured against what has been placed
        # SO FAR - which is what keeps every prefix of the campaign in policy.
        kind = min(
            normalised,
            key=lambda k: (used_counts[k] / max(placed, 1)) - normalised[k],
        )
        pool = by_kind[kind]
        entry = pool[rotation[kind] % len(pool)]
        rotation[kind] += 1
        used_counts[kind] += 1
        chosen.append(entry.text)
        kinds.append(kind)

    if len(set(chosen)) == 1 and count > 3:
        notes.append(
            f"Every placement uses the same anchor ('{chosen[0]}'). One anchor repeated "
            "across a campaign is its own footprint - supply a few more so the profile "
            "has natural variety."
        )
    return Assignment(anchors=tuple(chosen), kinds=tuple(kinds), notes=notes)


def within_policy(
    assignment: Assignment, *, shares: dict[AnchorKind, float] | None = None
) -> tuple[bool, str]:
    """Whether an assignment holds its distribution - the assertion A5 makes.

    Exposed separately so the check can run over a REAL campaign's anchors after the
    fact as well as over a plan: A5 says the share never exceeds its cap "across a full
    campaign", and a plan that was correct can still be undermined by manual edits.
    """
    targets = dict(shares or DEFAULT_SHARES)
    actual = assignment.distribution()
    for kind, share in actual.items():
        cap = targets.get(kind, 0.0)
        if kind == "exact" and share > 0:
            return False, f"exact-match anchors are {share:.0%} of the profile; the cap is 0%"
        # A tolerance of one placement: with 7 placements a 55% target cannot be hit
        # exactly, and failing a campaign for integer arithmetic would be theatre.
        tolerance = 1.0 / max(len(assignment.kinds), 1)
        if share > cap + tolerance:
            return False, (
                f"{kind} anchors are {share:.0%} of the profile; the policy allows {cap:.0%}"
            )
    return True, ""
