"""Parasite Poster: rank on somebody else's domain, and MEASURE whether it worked.

``M05`` §6 - "SoMePoster's headline SEO feature, and the reason this module exists for an
SEO agency". Publish a genuinely useful page about a target term onto a high-authority
third-party domain, so the HOST's authority carries it into the SERP for a term the
client's own site cannot yet rank for.

§6 also says which part gets abused, and the guardrails are the module:

* **Only where the terms permit it.** A platform's ``terms_position`` governs. A platform
  that forbids promotional or third-party-client content is not a parasite host, however
  high its authority - and "we did not read the terms" is not permission, so an unreviewed
  platform is refused rather than assumed fine.
* **The content must stand on its own.** The QA scorecard applies unchanged. A parasite
  page that is thin is a thin page on somebody else's domain, which is worse than a thin
  page on your own: you cannot fix it and you cannot take it down.
* **One page per term per host. No doorway sets.** Three pages about one term on one host
  is the doorway pattern, and it is the specific thing that gets an account removed and
  the tactic burned for every client on it.
* **It is tracked and reported.** §6: "the parasite page's own ranking is the deliverable,
  measured, not assumed" - which also means it is visible when the host removes it.

THE THING THAT MADE A11 IMPOSSIBLE UNTIL MIGRATION 0152, worth stating because it looks
like a detail and is not: ``tracked_keywords`` was unique on
``(client_id, normalized_keyword, engine, device, location, language)`` and
``add_keywords`` inserts ``on conflict do nothing``. Subscribing a parasite page for a
term the client already tracked was silently skipped - and §6's whole premise is that
these are terms the client cannot rank for, i.e. terms an SEO agency already tracks. The
feature collided with itself by design, and reported success while nothing measured it.
``hosted_url`` is now part of the key, so the hosted page and the client's own site are
tracked side by side - which is the comparison the tactic exists to produce.

Pure: no DB, no network, no clock. Selection and refusal are decided here; the caller
publishes and subscribes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal

from app.modules.web2.account_health import evaluate as evaluate_account
from app.modules.web2.platform_spec import UNSUPPORTED_PLATFORMS, spec_for

#: Authority tiers as the catalogue records them, ordered. A parasite page borrows the
#: host's authority, so this is the single most load-bearing selection input - a "low"
#: host carries nothing and the exercise is pointless.
_AUTHORITY_RANK: Final[dict[str, int]] = {"high": 3, "medium": 2, "low": 1, "": 0}

#: ``terms_position`` values that PERMIT a third-party promotional placement. An
#: allow-list, not a deny-list: the default for an unreviewed platform must be "no", and a
#: deny-list makes every unrecognised value permission by accident.
_PERMITTING_TERMS: Final[frozenset[str]] = frozenset({"permits", "permitted", "allows", "allowed"})

#: Shapes that can carry a ranking page at all. A 300-character note cannot rank for a
#: commercial term, and publishing one as a "parasite page" is a deliverable that was
#: never going to work.
_RANKABLE_SHAPES: Final[frozenset[str]] = frozenset({"article"})

Refusal = Literal[
    "ok", "unsupported", "terms_unreviewed", "terms_forbid", "not_rankable",
    "low_authority", "account_unusable", "already_placed", "not_verifiable",
]


@dataclass(frozen=True)
class HostVerdict:
    """Whether one platform may host a parasite page for one term."""

    platform: str
    verdict: Refusal
    reason: str = ""
    authority: str = ""

    @property
    def usable(self) -> bool:
        return self.verdict == "ok"


@dataclass(frozen=True)
class ParasitePlan:
    """One term, the host chosen for it, and how it will be measured."""

    term: str
    platform: str
    client_id: str
    client_name: str
    target_url: str
    authority: str = ""
    #: The alternatives, in order, so an operator can see what else was considered and
    #: why the winner won - a single recommendation with no runners-up is a black box.
    considered: tuple[HostVerdict, ...] = ()
    notes: list[str] = field(default_factory=list)


class ParasiteRefused(ValueError):  # noqa: N818 - a selection verdict, not a fault
    """No host can carry this term, with the reasons."""


def assess_host(
    platform: str,
    *,
    catalogue_row: dict[str, Any] | None,
    account: dict[str, Any] | None,
    existing_terms: set[str] | None = None,
    term: str = "",
    min_authority: str = "medium",
) -> HostVerdict:
    """Whether ``platform`` may host a parasite page for ``term``.

    Order is deliberate: the checks that are FACTS about the platform come before the ones
    that are facts about us. "This platform forbids it" is permanent; "our account is
    full" is today's problem, and reporting the second when the first is true sends an
    operator to fix something that would not help.
    """
    row = catalogue_row or {}
    authority = str(row.get("authority_tier") or "")

    if platform in UNSUPPORTED_PLATFORMS:
        return HostVerdict(platform, "unsupported", "no usable publishing API", authority)

    spec = spec_for(platform)
    if spec.shape not in _RANKABLE_SHAPES:
        return HostVerdict(
            platform, "not_rankable",
            f"a {spec.shape}-shaped placement cannot rank for a commercial term - "
            f"{platform} takes at most ~{spec.word_target} words",
            authority,
        )

    terms = str(row.get("terms_position") or "").strip().lower()
    if not terms:
        # NOT read as permission. §6 requires the platform's own rule to govern, and an
        # unread terms page is an unknown, not a yes. 72 of the catalogue's rows sit at
        # an unreviewed default - treating those as permitted would put client content on
        # seventy platforms nobody has checked.
        return HostVerdict(
            platform, "terms_unreviewed",
            "nobody has read this platform's terms yet, so it cannot be used as a "
            "parasite host - read and date them first",
            authority,
        )
    if terms not in _PERMITTING_TERMS:
        return HostVerdict(
            platform, "terms_forbid",
            f"this platform's terms position is '{terms}': promotional or third-party "
            "client content is not permitted here",
            authority,
        )

    if row.get("link_verifiable") is False:
        # A page we cannot fetch cannot be confirmed live, and §6 makes the ranking the
        # deliverable. An unverifiable host produces a deliverable nobody can check.
        return HostVerdict(
            platform, "not_verifiable",
            "placements here produce no fetchable public page, so the ranking could "
            "never be confirmed or reported",
            authority,
        )

    if _AUTHORITY_RANK.get(authority, 0) < _AUTHORITY_RANK.get(min_authority, 2):
        return HostVerdict(
            platform, "low_authority",
            f"authority tier '{authority or 'unknown'}' is below '{min_authority}': the "
            "whole tactic is borrowing the host's authority, and a weak host lends none",
            authority,
        )

    if term and existing_terms and term.strip().lower() in existing_terms:
        # ONE page per term per host. Three pages about one term on one host is the
        # doorway pattern - the specific thing that gets an account removed and burns the
        # tactic for every client on it.
        return HostVerdict(
            platform, "already_placed",
            f"a page for '{term}' already exists on {platform}; a second is a doorway "
            "set, not a second placement",
            authority,
        )

    verdict = evaluate_account(account)
    if not verdict.publishable:
        return HostVerdict(platform, "account_unusable", verdict.reason, authority)

    return HostVerdict(platform, "ok", authority=authority)


def select_host(
    *,
    term: str,
    client_id: str,
    client_name: str,
    target_url: str,
    candidates: list[str],
    catalogue: dict[str, dict[str, Any]],
    accounts: dict[str, dict[str, Any]],
    placed_terms: dict[str, set[str]] | None = None,
    min_authority: str = "medium",
) -> ParasitePlan:
    """Choose the best host for ``term``, or refuse with every reason.

    "Best" is the highest authority tier that passes every guardrail, with ties broken by
    name so the choice is deterministic and reviewable rather than dependent on dict
    ordering.
    """
    if not term.strip():
        raise ParasiteRefused("A parasite placement needs a target term.")

    assessed = [
        assess_host(
            platform,
            catalogue_row=catalogue.get(platform),
            account=accounts.get(platform),
            existing_terms=(placed_terms or {}).get(platform),
            term=term,
            min_authority=min_authority,
        )
        for platform in candidates
    ]
    usable = [verdict for verdict in assessed if verdict.usable]
    if not usable:
        raise ParasiteRefused(
            f"No host can carry '{term}'. "
            + "; ".join(f"{v.platform}: {v.reason}" for v in assessed[:5])
        )

    best = max(usable, key=lambda v: (_AUTHORITY_RANK.get(v.authority, 0), v.platform))
    notes = [
        f"{best.platform} chosen for '{term}' on authority tier '{best.authority}'; "
        f"{len(usable)} of {len(assessed)} candidate hosts passed the guardrails"
    ]
    return ParasitePlan(
        term=term.strip(), platform=best.platform, client_id=client_id,
        client_name=client_name, target_url=target_url, authority=best.authority,
        considered=tuple(assessed), notes=notes,
    )


def tracking_subscription(
    plan: ParasitePlan, hosted_url: str, *, tags: list[str] | None = None
) -> dict[str, Any]:
    """The M07 subscription that makes the parasite page's ranking the deliverable (A11).

    ``hosted_url`` is the published page's real URL, and it is BOTH the thing being
    measured and the discriminator that lets this subscription coexist with the client's
    own tracking of the same term (migration 0152). Passing an empty one would silently
    re-create the collision that made A11 unachievable, so it is refused.

    The ``parasite`` tag is not decoration: a client report has to distinguish "we rank
    3rd" from "a page we put on telegra.ph ranks 3rd", and those are different claims.
    """
    if not hosted_url.strip():
        raise ParasiteRefused(
            "A parasite subscription needs the published page's URL: it is what gets "
            "measured, and it is what keeps this subscription distinct from the client's "
            "own tracking of the same term."
        )
    return {
        "client_id": plan.client_id,
        "client_name": plan.client_name,
        "keyword": plan.term,
        "hosted_url": hosted_url.strip(),
        # The client's own page stays the TARGET - the parasite page links to it, and the
        # report is about whether that borrowed authority moved the client's business.
        "target_url": plan.target_url,
        "tags": sorted({*(tags or []), "parasite", f"host:{plan.platform}"}),
    }
