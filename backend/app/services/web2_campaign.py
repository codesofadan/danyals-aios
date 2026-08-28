"""Campaign planning: turn "thirty blog posts for this client" into a lawful plan.

THE MEASUREMENT THAT DEFINES THIS MODULE. Running the real generator across a fan-out
produced a result that decides the whole design:

    same client, SAME topic, 30 platforms  -> body r = 1.000, heading r = 1.000  (BLOCK)
    same client, DISTINCT topics           -> body r = 0.034, heading r = 0.406  (pass)

Publishing one topic to thirty platforms produces thirty BYTE-IDENTICAL articles. That is
precisely the "fans ONE branded article out to every selected platform" behaviour the old
UI advertised and WEB2-002 forbids, and the similarity gate now blocks all thirty. So
"thirty blog posts" cannot mean thirty copies: the planner must produce **thirty distinct
topics**, and a campaign that cannot is refused at planning time rather than after
thirty metered drafting runs.

A second measured fact shapes the layout: rotating the writing framework across the set
halves worst-case heading resemblance (0.406 -> 0.208), because `_FRAMEWORK_MOVES` is a
fixed heading table and same-framework articles share a skeleton. And a third: spreading
across platforms is both FASTER (the 24-hour any-platform rule instead of the 72-hour
same-platform one: ~30 days versus ~87 for thirty properties) and lower-footprint. The
fast route and the safe route are the same route.

Pure: no DB, no clock, no network. The caller supplies the catalogue, the history and
``now``; this returns a plan it can price, show, and then commit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.services.web2_anchor import check_anchor
from app.services.web2_pacing import PacingCaps, Placement, schedule_campaign
from integrations.web2_publishers import diversify_footprint

# The frameworks the generator can drive. Rotated across a campaign so the set does not
# share one heading skeleton (measured: halves worst-case heading resemblance).
CAMPAIGN_FRAMEWORKS: tuple[str, ...] = ("PAS", "AIDA", "BAB", "FAB", "4 Ps", "PASTOR", "4 U's")


class CampaignRefusedError(ValueError):
    """The request cannot be planned into something safe to publish."""


@dataclass(frozen=True)
class PlannedProperty:
    """One property the campaign would create."""

    index: int
    platform: str
    topic: str
    anchor: str
    framework: str
    scheduled_for: datetime | None = None

    @property
    def placeholder_id(self) -> str:
        """A stable id for pre-commit scheduling, before real rows exist."""
        return f"plan-{self.index}"


@dataclass(frozen=True)
class CampaignPlan:
    """A costed, scheduled plan - everything the operator needs BEFORE committing."""

    client_id: str
    client_name: str
    properties: list[PlannedProperty] = field(default_factory=list)
    estimated_cost_usd: float = 0.0
    projected_completion: datetime | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.properties)


def plan_campaign(
    *,
    now: datetime,
    client_id: str,
    client_name: str,
    requested_count: int,
    topics: Sequence[str],
    platforms: Sequence[str],
    anchors: Sequence[str],
    target_url: str,
    caps: PacingCaps,
    per_article_cost: float,
    history: Sequence[Placement] = (),
    cost_ceiling_usd: float = 0.0,
) -> CampaignPlan:
    """Lay out a campaign, or refuse it with a reason an operator can act on.

    Refusals are deliberate and specific. "Not enough distinct topics" is actionable;
    silently publishing duplicates, or silently shrinking a thirty-article request to
    four without saying so, is not.
    """
    if requested_count <= 0:
        raise CampaignRefusedError("A campaign needs at least one article.")
    if not platforms:
        raise CampaignRefusedError(
            "No eligible platforms were selected. Check the platform board for this "
            "client - some platforms are restricted by their own content policies."
        )

    clean_topics = _unique(topics)
    if len(clean_topics) < requested_count:
        # The refusal that matters most. Reusing a topic across properties produces
        # identical articles (measured r=1.000), so this is not a nicety - it is the
        # difference between a campaign and a duplicate-content incident.
        raise CampaignRefusedError(
            f"{requested_count} articles need {requested_count} distinct topics, but "
            f"only {len(clean_topics)} were supplied. Publishing one topic across "
            "several platforms produces identical articles, which the similarity gate "
            "blocks and which reads as duplicate content."
        )

    # R2-14: refuse exact-match commercial anchors BEFORE they can be selected. An
    # anchor that is exactly the phrase the destination ranks for has no editorial
    # justification at any ratio, so it is filtered out of the pool rather than
    # rationed. Refusals are REPORTED - an operator whose anchors were silently
    # replaced would not learn the rule, and would supply the same list next time.
    requested_anchors = _unique(anchors) or [client_name]
    clean_anchors: list[str] = []
    notes: list[str] = []
    for candidate in requested_anchors:
        verdict = check_anchor(
            candidate, target_url=target_url, topic=clean_topics[0] if clean_topics else "",
            client_name=client_name,
        )
        if verdict.allowed:
            clean_anchors.append(candidate)
        else:
            notes.append(f"Anchor '{candidate}' was not used: {verdict.reason}.")
    if not clean_anchors:
        # Never leave a placement with no link text - the brand is the safe floor.
        clean_anchors = [client_name]
        notes.append(
            f"No supplied anchor was usable, so '{client_name}' (the brand) was used. "
            "Brand, brand + location, a natural sentence fragment, or a bare URL all work."
        )

    # The per-client-per-campaign cap. Enforced, and REPORTED - a request quietly
    # shrunk from thirty to four is a lie the operator would discover weeks later.
    count = requested_count
    if caps.max_properties_per_client_campaign > 0:
        allowed = caps.max_properties_per_client_campaign
        if count > allowed:
            notes.append(
                f"Requested {requested_count} properties; the per-client campaign cap is "
                f"{allowed}, so {allowed} were planned. Raise the cap deliberately if "
                "this client genuinely warrants more."
            )
            count = allowed

    properties: list[PlannedProperty] = []
    used_pairs: list[tuple[str, str]] = [(p.platform, "") for p in history]
    for i in range(count):
        # `diversify_footprint` finally gets its production caller: it prefers an unused
        # (platform, anchor) pair and rotates deterministically, which is exactly the
        # selection job it was written for. It is a SELECTION helper, never a gate.
        choice = diversify_footprint(
            seed=f"{client_id}|{i}|{target_url}",
            platforms=list(platforms),
            accounts=["default"],
            anchors=clean_anchors,
            existing=used_pairs,
        )
        properties.append(
            PlannedProperty(
                index=i,
                platform=choice.platform,
                topic=clean_topics[i],
                anchor=choice.anchor,
                # Rotate the skeleton as well as the platform: same-framework articles
                # share a fixed heading table, and rotating halves the collision.
                framework=CAMPAIGN_FRAMEWORKS[i % len(CAMPAIGN_FRAMEWORKS)],
            )
        )
        used_pairs.append((choice.platform, choice.anchor))

    schedule = schedule_campaign(
        now=now,
        caps=caps,
        client_id=client_id,
        properties=[(p.placeholder_id, p.platform) for p in properties],
        history=history,
    )
    slots = dict(schedule)
    properties = [
        PlannedProperty(
            index=p.index, platform=p.platform, topic=p.topic, anchor=p.anchor,
            framework=p.framework, scheduled_for=slots.get(p.placeholder_id),
        )
        for p in properties
    ]

    estimated = round(count * max(0.0, per_article_cost), 4)
    if cost_ceiling_usd > 0 and estimated > cost_ceiling_usd:
        raise CampaignRefusedError(
            f"This campaign would cost about ${estimated:.2f}, above the ${cost_ceiling_usd:.2f} "
            "ceiling set for it. Raise the ceiling or reduce the article count."
        )

    completion = max((p.scheduled_for for p in properties if p.scheduled_for), default=None)
    if completion is not None:
        days = max(0, (completion - now).days)
        notes.append(
            f"Pacing spreads these {count} properties over about {days} day(s); the last "
            "one publishes around then. Spreading across more platforms shortens this "
            "materially - a single platform is governed by a 72-hour gap per client, "
            "several platforms by a 24-hour one."
        )

    return CampaignPlan(
        client_id=client_id,
        client_name=client_name,
        properties=properties,
        estimated_cost_usd=estimated,
        projected_completion=completion,
        notes=notes,
    )


def campaign_status_for(
    *, total: int, published: int, failed: int, cancelled: bool = False
) -> str:
    """The campaign's honest status.

    ``completed`` requires EVERY property to have published. A campaign that claimed
    thirty and delivered twenty-eight is ``degraded`` - the same rule the content
    dispatcher enforces ("a partial dispatch is degraded, not done"), and the same defect
    P0-4 removed elsewhere: a green tick over work that reached nobody.
    """
    if cancelled:
        return "cancelled"
    if total <= 0:
        return "draft"
    settled = published + failed
    if settled < total:
        return "running" if published or failed else "scheduled"
    if published == total:
        return "completed"
    return "degraded"


def _unique(values: Sequence[str]) -> list[str]:
    """Trimmed, de-duplicated, order-preserving - case-insensitively.

    Case-insensitive because "Drain Unblocking" and "drain unblocking" are the same topic
    and would generate the same article; counting them as two distinct topics would let a
    duplicate through the very check that exists to stop it.
    """
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        cleaned = (value or "").strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out
