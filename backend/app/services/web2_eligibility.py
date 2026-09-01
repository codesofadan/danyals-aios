"""Which Web 2.0 platforms may THIS client publish to, and why (R2-04 / R2-05).

THE DISTINCTION THIS MODULE EXISTS TO HOLD. The catalogue's ``automation_ready`` answers
"can the pipeline publish here?". That is a fact about our code. It says nothing about
the question that decides whether a placement is defensible: "should this client publish
here at all?" - a fact about the CLIENT and the platform's own terms.

Conflating them produces the module's worst possible output: a plumber's marketing
article on a developer community, which dev.to's Content Policy forbids in as many words
("not designed primarily for the purposes of promotion or creating backlinks"), and
which is also simply bad work. The adapter is not the problem; pointing it at the wrong
client is.

WHY THIS MAKES THE PRODUCT MORE CAPABLE, NOT LESS. The whole catalogue stays on the
board. What varies is which rows are ELIGIBLE for the client in front of you, and every
ineligible row carries its reason. A dev-tools SaaS legitimately unlocks the developer
platforms; a local plumber sees the topic-agnostic set. Nothing is hidden, so an operator
can see the full reach of the system and understand exactly why a given platform is not
offered for this client - which is a better answer than a silently shorter list.

Pure: takes rows, returns verdicts. The caller owns the query.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

TIER_PER_CLIENT = "per_client"
TIER_HOUSE = "house"
TIER_DO_NOT_USE = "do_not_use"

# A platform whose content suits any real brand. Always eligible, which is why an
# unclassified client still has a usable set rather than an empty board.
SCOPE_AGNOSTIC = "agnostic"

Status = Literal["eligible", "not_connected", "not_eligible", "not_reviewed", "not_supported"]


@dataclass(frozen=True)
class PlatformVerdict:
    """One row of the five-state board (WEB2-012).

    ``not_connected`` is deliberately distinct from ``not_eligible``: the first is a
    missing credential an operator can go and fix in ten minutes, the second is a
    judgement about this client that no credential changes. Collapsing them into one
    "unavailable" state would send operators hunting for a token that would not help.

    ``not_reviewed`` and ``not_supported`` were split OUT of ``not_eligible`` for the
    same honesty reason: 72 of the 90 catalogue rows sit at the migration DEFAULT of
    ``do_not_use`` because nobody has read their terms yet, and presenting that default
    as a reviewed policy verdict ("its own terms make a placement indefensible") was a
    lie the board told with a straight face. A safe default is not a judgement.
    """

    name: str
    platform_enum: str | None
    status: Status
    reason: str
    ownership_tier: str = TIER_DO_NOT_USE
    topical_scope: str = ""
    authority_tier: str = ""
    terms_position: str = ""
    terms_checked_on: str = ""
    terms_source_url: str = ""

    @property
    def eligible(self) -> bool:
        return self.status == "eligible"

    @property
    def advisable(self) -> bool:
        """Whether an operator may CHOOSE this platform for this client.

        The distinction that makes "any platform for any client" honest without making
        it reckless. Two states are hard facts about the machine and can never be
        overridden - there is no publisher (``not_supported``) or there is no credential
        (``not_connected``), and no amount of operator conviction publishes through
        either. The other two are JUDGEMENTS about fit: a topical mismatch
        (``not_eligible``) or an unread terms page (``not_reviewed``). Those are the
        operator's call to make with the platform's own rule in front of them, so they
        are advisory - selectable against a recorded acknowledgement, not refused.
        """
        return self.status in ("eligible", "not_eligible", "not_reviewed")

    @property
    def needs_acknowledgement(self) -> bool:
        """Selectable, but only against an explicit, recorded acknowledgement."""
        return self.status in ("not_eligible", "not_reviewed")


def evaluate_platform(
    row: dict[str, Any], *, client_scope: str, connected: bool
) -> PlatformVerdict:
    """Classify one catalogue row for one client.

    Order matters. Eligibility is judged BEFORE connectivity, because "we hold a token
    for a platform this client must not use" is not a reason to offer it - and telling
    an operator it is merely unconnected would invite them to fix the wrong thing.
    """
    name = str(row.get("name") or "")
    enum_value = row.get("platform_enum")
    platform_enum = str(enum_value) if enum_value else None
    tier = str(row.get("ownership_tier") or TIER_DO_NOT_USE)
    scope = str(row.get("topical_scope") or "")
    terms = str(row.get("terms_position") or "")
    checked_on = row.get("terms_checked_on")
    checked_on_iso = checked_on.isoformat() if isinstance(checked_on, date) else str(checked_on or "")
    # Migration 0103 stamped terms_checked_on on every row a human actually adjudicated,
    # so its absence IS the "never reviewed" signal. A written terms_position counts as
    # review too - someone read something to write it.
    reviewed = bool(checked_on) or bool(terms)

    def verdict(status: Status, reason: str) -> PlatformVerdict:
        return PlatformVerdict(
            name=name,
            platform_enum=platform_enum,
            status=status,
            reason=reason,
            ownership_tier=tier,
            topical_scope=scope,
            authority_tier=str(row.get("authority_tier") or ""),
            terms_position=terms,
            terms_checked_on=checked_on_iso,
            terms_source_url=str(row.get("terms_source_url") or ""),
        )

    if not row.get("automation_ready"):
        return verdict(
            "not_supported",
            "No publisher exists for this platform yet - it is a catalogued build "
            "target, not something the pipeline can drive.",
        )
    if platform_enum is None:
        # Unmappable to the publishing enum: the pipeline could not name it even if the
        # catalogue says it is ready. Reporting it eligible would offer a platform that
        # fails at plan time.
        return verdict(
            "not_supported",
            "This catalogue entry has no publishing-enum mapping, so the pipeline "
            "cannot target it.",
        )
    if tier == TIER_DO_NOT_USE and not reviewed:
        return verdict(
            "not_reviewed",
            "Not yet reviewed: nobody has read this platform's terms, so it stays "
            "unusable by default. A safe default, not a verdict - reviewing its terms "
            "is what would settle it.",
        )
    if tier == TIER_DO_NOT_USE:
        return verdict(
            "not_eligible",
            terms
            or "Excluded on review: its own terms, its link value, or its content "
            "model make a placement here indefensible.",
        )
    if scope != SCOPE_AGNOSTIC and scope != client_scope:
        return verdict(
            "not_eligible",
            f"Restricted to {scope} clients; this client is {client_scope}. Publishing "
            "off-topic promotional content here breaches the platform's own content "
            "policy.",
        )
    if not connected:
        return verdict(
            "not_connected", "Eligible for this client, but no account is connected yet."
        )
    return verdict("eligible", "")


def evaluate_catalog(
    rows: Iterable[dict[str, Any]],
    *,
    client_scope: str,
    connected_platforms: Sequence[str] | set[str] = (),
) -> list[PlatformVerdict]:
    """Classify the whole catalogue for one client, preserving input order."""
    connected = set(connected_platforms)
    return [
        evaluate_platform(
            row,
            client_scope=client_scope or SCOPE_AGNOSTIC,
            connected=bool(row.get("platform_enum")) and str(row["platform_enum"]) in connected,
        )
        for row in rows
    ]


def eligible_platform_names(verdicts: Iterable[PlatformVerdict]) -> list[str]:
    """The publishing-enum names a campaign may actually target.

    Includes only ``eligible`` rows - a platform with no connected account cannot
    publish, so offering it as a campaign target would queue work that can only hold.
    """
    return [v.platform_enum for v in verdicts if v.eligible and v.platform_enum]


@dataclass(frozen=True)
class SelectionVerdict:
    """What an operator's platform selection resolves to.

    Three lists, because three different things must happen to them: ``allowed`` is
    planned, ``blocked`` is refused with the machine reason, and ``advisories`` is
    planned ONLY if the operator has acknowledged it - and is refused with the
    platform's own words if they have not.
    """

    allowed: list[str]
    blocked: list[str]  # "platform: reason" - cannot publish, no override exists
    advisories: list[str]  # "platform: reason" - the operator's call, needs an ack


def resolve_selection(
    verdicts: Iterable[PlatformVerdict],
    selected: Iterable[str],
    *,
    acknowledged: bool = False,
) -> SelectionVerdict:
    """Narrow an operator's chosen platforms into plan / refuse / ask.

    THE CHANGE THIS EXISTS TO MAKE. The board previously refused four states
    identically, which capped a default client at the four topic-agnostic platforms and
    left the operator no way to say "I know, use it anyway" - so 35 platforms holding
    real, working publisher code were unreachable for every client in the system. The
    hard blocks stay hard (no publisher, no credential: those are facts, not opinions);
    the two judgement states become the operator's decision, taken with the platform's
    own rule quoted to them and their acknowledgement recorded.
    """
    by_name: dict[str, PlatformVerdict] = {}
    for verdict in verdicts:
        by_name[verdict.name] = verdict
        if verdict.platform_enum:
            by_name.setdefault(verdict.platform_enum, verdict)

    allowed: list[str] = []
    blocked: list[str] = []
    advisories: list[str] = []
    for name in selected:
        chosen = by_name.get(name)
        if chosen is None:
            blocked.append(f"{name}: not in the platform catalogue.")
            continue
        target = chosen.platform_enum or chosen.name
        if chosen.eligible:
            allowed.append(target)
        elif not chosen.advisable:
            blocked.append(f"{name}: {chosen.reason}")
        elif acknowledged:
            allowed.append(target)
        else:
            advisories.append(f"{name}: {chosen.reason}")
    return SelectionVerdict(allowed=allowed, blocked=blocked, advisories=advisories)


def refuse_reason(verdicts: Iterable[PlatformVerdict], platform: str) -> str:
    """Why ``platform`` may not be used for this client, or ``""`` if it may.

    Used by the planner to refuse an ineligible target with the platform's OWN stated
    reason rather than a generic rejection - an operator who is told "dev.to bans
    promotional content for non-developer clients" learns the rule; one who is told
    "not allowed" learns only that the software said no.
    """
    for verdict in verdicts:
        if verdict.platform_enum == platform or verdict.name == platform:
            return "" if verdict.eligible else verdict.reason
    return f"{platform} is not in the platform catalogue."
