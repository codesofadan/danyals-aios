"""Compose once, publish everywhere - as platform-shaped VARIANTS, never as copies.

THE OPERATOR'S REQUIREMENT: write the content, tick the platforms (or tick "All"), and it
goes out everywhere - as an article where the platform takes articles, as a post where it
takes posts.

THE MEASUREMENT THAT DECIDES HOW THIS IS BUILT. Running the real generator across a
fan-out produced the finding recorded in ``web2_campaign``::

    same client, SAME topic, 30 platforms  -> body r = 1.000, heading r = 1.000  (BLOCK)
    same client, DISTINCT topics           -> body r = 0.034, heading r = 0.406  (pass)

"One article to thirty platforms" produces thirty BYTE-IDENTICAL articles. That is not a
broadcast, it is duplicate content, and the similarity gate blocks all thirty after
thirty metered drafting runs have already been paid for. `M05` REQ-W2-006 states the rule
directly: *"every post is produced by the M03 pipeline in a platform-shaped variant.
Never spun, never duplicated across properties."*

SO "PUBLISH EVERYWHERE" MEANS ONE SUBJECT, N GENUINELY DIFFERENT POSTS - and there are
three independent axes that make them different, two of which are measured:

1. **Shape** (`platform_spec`): a 900-word HTML article on Ghost, a 29-word plain-text
   note on Bluesky, a plain document on a paste host. These are not the same text
   shortened - a note is composed separately, because the article generator clamps to a
   600-word floor and cannot produce one.
2. **Angle**: each article-shaped placement is given a different facet of the subject.
   This is what stops two blog platforms receiving the same 900 words.
3. **Framework**: rotated across the set. MEASURED to halve worst-case heading
   resemblance (0.406 -> 0.208), because same-framework articles share a heading table.

WHAT THIS MODULE IS. A pure planner: subject + selected platforms + what the client can
actually publish to -> one placement plan per platform, or a REFUSAL naming what an
operator would have to change. It plans; it does not draft, publish, or touch the
database. The graph drafts each planned placement, and the human gate still approves
every one of them before anything goes live.

IT REFUSES RATHER THAN SILENTLY SHRINKING. A request for 20 platforms that can only
lawfully support 6 comes back as a refusal with the reason, not as 6 placements and a
quiet hope nobody counts. An operator who is silently given a third of what they asked
for discovers it weeks later in a report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.web2.account_health import evaluate as evaluate_account
from app.modules.web2.platform_spec import UNSUPPORTED_PLATFORMS, PostShape, spec_for
from app.services.web2_anchor import check_anchor
from app.services.web2_campaign import CAMPAIGN_FRAMEWORKS, CampaignRefusedError

#: The selection token meaning "every platform this client can lawfully publish to".
#: A literal rather than an empty list, because "all" and "none selected" are different
#: intentions and an empty list must never silently mean everything.
ALL_PLATFORMS = "__all__"

#: Distinct facets of one subject, used to differentiate article-shaped placements.
#: These are ANGLES, not topics: every placement is still about the client's subject, and
#: each asks a different question about it - which is what a human writing for several
#: outlets does, and what "never spun" means in practice.
ANGLES: tuple[str, ...] = (
    "what it actually involves, step by step",
    "how to tell whether you need it yet",
    "what it costs and what drives the price",
    "the mistakes that make it more expensive",
    "how to choose who does it",
    "what happens if it is left too long",
    "what the process looks like from the customer's side",
    "how it differs for older properties",
)


@dataclass(frozen=True)
class PlannedPost:
    """One platform's variant of the subject."""

    platform: str
    shape: PostShape
    #: The facet of the subject this placement covers. Empty for note/snippet shapes,
    #: where the whole post is one thought and an angle would over-specify it.
    angle: str = ""
    framework: str = ""
    word_target: int = 0
    anchor: str = ""
    account_id: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def topic(self) -> str:
        """What this placement is actually about - the subject narrowed by its angle."""
        return self._topic

    _topic: str = ""


@dataclass(frozen=True)
class BroadcastPlan:
    """What "publish this everywhere" resolves to."""

    client_id: str
    subject: str
    posts: tuple[PlannedPost, ...] = ()
    #: Platforms the operator selected that will NOT receive a post, each with a reason.
    #: Reported rather than dropped: a selection silently shrunk is a lie the operator
    #: discovers in a report weeks later.
    excluded: tuple[tuple[str, str], ...] = ()
    notes: list[str] = field(default_factory=list)

    @property
    def article_count(self) -> int:
        return sum(1 for p in self.posts if p.shape == "article")

    def summary(self) -> str:
        shapes: dict[str, int] = {}
        for post in self.posts:
            shapes[post.shape] = shapes.get(post.shape, 0) + 1
        rendered = ", ".join(f"{count} {shape}" for shape, count in sorted(shapes.items()))
        return (
            f"{len(self.posts)} placement(s) planned ({rendered})"
            + (f"; {len(self.excluded)} platform(s) excluded" if self.excluded else "")
        )


def plan_broadcast(
    *,
    client_id: str,
    client_name: str,
    subject: str,
    target_url: str,
    selected: list[str],
    available: list[str],
    anchors: list[str] | None = None,
    accounts: dict[str, dict[str, Any]] | None = None,
) -> BroadcastPlan:
    """Turn one subject plus a platform selection into one variant per platform.

    ``selected`` is the operator's tick-list, or ``[ALL_PLATFORMS]``. ``available`` is
    what this client may lawfully publish to (the eligibility board's verdict, computed by
    the caller - this module does not re-decide policy). ``accounts`` maps platform ->
    account row, so a degraded or capped account is excluded HERE, at plan time, rather
    than discovered one failed publish at a time.

    Raises :class:`CampaignRefusedError` when nothing lawful remains, because an empty
    plan returned as a success reads as "done".
    """
    clean_subject = subject.strip()
    if not clean_subject:
        raise CampaignRefusedError("A broadcast needs a subject to write about.")

    wanted = _resolve_selection(selected, available)
    if not wanted:
        raise CampaignRefusedError(
            "No platforms were selected. Tick the platforms to publish to, or choose "
            "All to use every platform this client is connected to."
        )

    excluded: list[tuple[str, str]] = []
    eligible: list[str] = []
    for platform in wanted:
        reason = _exclusion_reason(platform, available, accounts or {})
        if reason:
            excluded.append((platform, reason))
        else:
            eligible.append(platform)

    if not eligible:
        raise CampaignRefusedError(
            "None of the selected platforms can take a post right now. "
            + "; ".join(f"{name}: {why}" for name, why in excluded[:4])
        )

    usable_anchors = _usable_anchors(anchors or [], client_name, target_url, clean_subject)
    notes: list[str] = list(usable_anchors.notes)

    posts: list[PlannedPost] = []
    article_index = 0
    for platform in eligible:
        spec = spec_for(platform)
        anchor = usable_anchors.values[len(posts) % len(usable_anchors.values)]
        account = (accounts or {}).get(platform) or {}
        if spec.shape == "article":
            # THE DIFFERENTIATION THAT STOPS A DUPLICATE-CONTENT INCIDENT. Two blog
            # platforms given the same subject with no angle produce the same 900 words
            # (measured r = 1.000). A distinct facet plus a rotated framework is what
            # makes them two real articles rather than one article posted twice.
            angle = ANGLES[article_index % len(ANGLES)]
            framework = CAMPAIGN_FRAMEWORKS[article_index % len(CAMPAIGN_FRAMEWORKS)]
            article_index += 1
            posts.append(
                PlannedPost(
                    platform=platform, shape=spec.shape, angle=angle, framework=framework,
                    word_target=spec.word_target, anchor=anchor,
                    account_id=str(account.get("id") or ""),
                    _topic=f"{clean_subject}: {angle}",
                )
            )
        else:
            # A note, snippet or profile placement is ONE thought. Giving it an angle
            # would over-specify a 29-word post, and its shape already differentiates it
            # from every article in the set.
            posts.append(
                PlannedPost(
                    platform=platform, shape=spec.shape, word_target=spec.word_target,
                    anchor=anchor, account_id=str(account.get("id") or ""),
                    _topic=clean_subject,
                )
            )

    if article_index > len(ANGLES):
        # Honest about the one way this can still collide: more article platforms than
        # distinct angles means the rotation repeats, and two repeats of one angle are
        # the duplicate case all over again.
        notes.append(
            f"{article_index} article-shaped platforms were selected but only "
            f"{len(ANGLES)} distinct angles exist, so the rotation repeats. The "
            "similarity gate will catch the repeats at review - supply more subjects, or "
            "select fewer blog platforms, to avoid paying for drafts that get blocked."
        )
    if excluded:
        notes.append(
            f"{len(excluded)} selected platform(s) were excluded and will receive nothing: "
            + "; ".join(f"{name} ({why})" for name, why in excluded[:3])
            + ("; ..." if len(excluded) > 3 else "")
        )

    return BroadcastPlan(
        client_id=client_id, subject=clean_subject, posts=tuple(posts),
        excluded=tuple(excluded), notes=notes,
    )


def _resolve_selection(selected: list[str], available: list[str]) -> list[str]:
    """The operator's tick-list, with ``All`` expanded. Order-stable and de-duplicated."""
    if ALL_PLATFORMS in selected:
        return list(dict.fromkeys(available))
    return list(dict.fromkeys(selected))


def _exclusion_reason(
    platform: str, available: list[str], accounts: dict[str, dict[str, Any]]
) -> str:
    """Why this platform cannot take a post, or '' if it can."""
    if platform in UNSUPPORTED_PLATFORMS:
        return "no usable publishing API (M05 REQ-W2-002)"
    if platform not in available:
        return "this client is not connected to it, or its terms rule it out"
    account = accounts.get(platform)
    if account is None:
        return "no publishing account is registered for this client on it"
    verdict = evaluate_account(account)
    if not verdict.publishable:
        return verdict.reason
    return ""


@dataclass(frozen=True)
class _Anchors:
    values: list[str]
    notes: list[str] = field(default_factory=list)


def _usable_anchors(
    anchors: list[str], client_name: str, target_url: str, subject: str
) -> _Anchors:
    """The anchors this broadcast may use, with refusals REPORTED.

    Reuses ``web2_anchor.check_anchor`` rather than re-deciding: an exact-match commercial
    anchor has no editorial justification at any ratio, and that rule must not have a
    second, more permissive implementation living in the broadcast path.
    """
    notes: list[str] = []
    usable: list[str] = []
    for candidate in dict.fromkeys(a.strip() for a in anchors if a.strip()):
        verdict = check_anchor(
            candidate, target_url=target_url, topic=subject, client_name=client_name
        )
        if verdict.allowed:
            usable.append(candidate)
        else:
            # Reported, never silently swapped: an operator whose anchors were quietly
            # replaced never learns the rule and supplies the same list next time.
            notes.append(f"Anchor '{candidate}' was not used: {verdict.reason}.")
    if not usable:
        usable = [client_name]
        if anchors:
            notes.append(
                f"No supplied anchor was usable, so '{client_name}' (the brand) was used."
            )
    return _Anchors(values=usable, notes=notes)
