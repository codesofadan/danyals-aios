"""Off-page module request/response models in the frontend shapes (``lib/offpage.ts``).

Three response models mirror their TS types EXACTLY (order-independent, but the
emitted keys must equal the TS field set - the contract-lock test enforces it):

* ``BacklinkResponse``  <-> ``Backlink``   ({id, client, refDomain, anchor,
  authority, spam, firstSeen, status}).
* ``CitationResponse``  <-> ``Citation``   ({id, client, directory, nap, action,
  note}).
* ``Web2PropertyResponse`` <-> ``Web2Property`` ({id, client, platform, postUrl,
  anchor, verified, published}).

Python attributes stay snake_case and re-alias to the camelCase wire key via
``serialization_alias`` (ruff N815 forbids a raw camelCase attribute). ``id`` is the
row uuid (a string) used purely as a React key; the internal ``client_id`` never
leaks (``client`` is the snapshotted display name). ``firstSeen`` / ``published``
are calendar-formatted ("Jul 08, 2026").

§3 ENUM FIDELITY: every union is pinned verbatim to ``offpage.ts`` - in particular
``Web2Platform`` MUST include ``"Medium"`` (WordPress.com|Blogger|Tumblr|Medium).

``action_for(nap_status)`` is the pure server rule the router + ingest reuse: a
``missing`` listing needs a Submit, anything else an Update - mirroring the
``offpage.ts`` comment ("missing -> Submit, otherwise -> Update").
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.util.timefmt import format_date

# Web 2.0 article page type - mirrors content.ts PageType (service|blog|local); a
# branded property defaults to a blog post.
Web2PageType = Literal["service", "blog", "local"]
Web2ReviewAction = Literal["approve", "reject"]

# Unions verbatim from offpage.ts. Same values front + back - no display remapping.
BacklinkStatus = Literal["new", "lost", "toxic"]
NapStatus = Literal["consistent", "inconsistent", "missing"]
CitationAction = Literal["Submit", "Update"]
# 7B-4: the citation SUBMISSION pipeline's state - verbatim from
# public.citation_submit_status (0045) / frontend CitationSubmitStatus (offpage.ts).
CitationSubmitStatus = Literal[
    "not_started", "queued", "submitting", "submitted", "verified", "failed", "blocked",
    "ready_for_human",  # account created + listing prepared; a human finishes at handoff_url
]
Web2Platform = Literal[
    "WordPress.com", "Blogger", "Tumblr", "Medium",
    "dev.to", "Write.as", "Telegra.ph", "Mataroa", "Ghost", "Mastodon",
    "GitHub Pages", "GitLab Pages", "Micro.blog", "Hashnode", "Hatena Blog",
    "LiveJournal", "Dreamwidth",
    "Webflow", "HubSpot CMS", "Drupal", "Joomla",
    "HackMD", "GitHub Gist", "GitLab Snippets", "paste.ee", "Pastebin.com",
    "Netlify", "Neocities", "rentry.co", "dpaste.org",
    "Misskey", "Lemmy", "Bluesky", "WhiteWind",
    "Disqus", "Plurk", "Pixelfed", "Notion", "Gravatar", "Minds",
    "Zenodo", "Internet Archive", "OSF", "Figshare", "Codeberg Pages",
    "Livedoor Blog", "FC2 Blog", "Seesaa Blog", "Warpcast", "Sourcehut Pages",
    "Sanity", "Storyblok", "Hygraph", "WriteFreely",
]
Web2Verified = Literal["verified", "pending"]
# The publish PIPELINE's internal state machine (0028) - distinct from `verified`,
# which is the live/indexable check on an ALREADY-published row.
Web2PipelineStatus = Literal[
    "draft", "needs_review", "publishing", "published", "failed", "rejected"
]

_BACKLINK_STATUSES: frozenset[str] = frozenset({"new", "lost", "toxic"})
_NAP_STATUSES: frozenset[str] = frozenset({"consistent", "inconsistent", "missing"})
_CITATION_ACTIONS: frozenset[str] = frozenset({"Submit", "Update"})
_CITATION_SUBMIT_STATUSES: frozenset[str] = frozenset(
    {"not_started", "queued", "submitting", "submitted", "verified", "failed", "blocked",
     "ready_for_human"}
)
# Verbatim from integrations.web2_publishers.WEB2_PLATFORMS (7B-4's platform expansion).
_WEB2_PLATFORMS: frozenset[str] = frozenset(
    {
        "WordPress.com", "Blogger", "Tumblr", "Medium",
        "dev.to", "Write.as", "Telegra.ph", "Mataroa", "Ghost", "Mastodon",
        "GitHub Pages", "GitLab Pages", "Micro.blog", "Hashnode", "Hatena Blog",
        "LiveJournal", "Dreamwidth",
        "Webflow", "HubSpot CMS", "Drupal", "Joomla",
        "HackMD", "GitHub Gist", "GitLab Snippets", "paste.ee", "Pastebin.com",
        "Netlify", "Neocities", "rentry.co", "dpaste.org",
        "Misskey", "Lemmy", "Bluesky", "WhiteWind",
        "Disqus", "Plurk", "Pixelfed", "Notion", "Gravatar", "Minds",
        "Zenodo", "Internet Archive", "OSF", "Figshare", "Codeberg Pages",
        "Livedoor Blog", "FC2 Blog", "Seesaa Blog", "Warpcast", "Sourcehut Pages",
        "Sanity", "Storyblok", "Hygraph", "WriteFreely",
    }
)
_WEB2_VERIFIED: frozenset[str] = frozenset({"verified", "pending"})
_WEB2_PIPELINE_STATUSES: frozenset[str] = frozenset(
    {"draft", "needs_review", "publishing", "published", "failed", "rejected"}
)

# --- Web 2.0 platform CATALOG (public.web2_platforms, 0062/0063) ---------------
# The web2 analogue of the citation-directory catalog: reference data, not tenant
# data. `auth_type` is verbatim from the public.web2_auth_type enum (0062); the
# catalog `name` is FREE TEXT (decoupled from the web2_platform PUBLISHING enum), so
# it is NOT the Web2Platform union above - a catalog row can name a platform we have
# no publisher for yet.
Web2AuthType = Literal["api", "oauth", "automation", "anonymous"]
Web2AuthorityTier = Literal["high", "medium", "low"]
_WEB2_AUTH_TYPES: frozenset[str] = frozenset({"api", "oauth", "automation", "anonymous"})
_WEB2_AUTHORITY_TIERS: frozenset[str] = frozenset({"high", "medium", "low"})


def action_for(nap_status: str) -> CitationAction:
    """The action a NAP state calls for: ``missing`` -> ``Submit`` (create the
    listing), anything else -> ``Update`` (fix drift / re-verify). Mirrors the
    ``offpage.ts`` rule."""
    return "Submit" if nap_status == "missing" else "Update"


class BacklinkResponse(BaseModel):
    """One backlink in the frontend ``Backlink`` shape - and ONLY those 8 keys.
    ``id`` is the row uuid (a string); ``client`` is the snapshotted display name so
    the internal ``client_id`` never leaks."""

    id: str
    client: str
    ref_domain: str = Field(serialization_alias="refDomain")
    anchor: str
    authority: int
    spam: int
    first_seen: str = Field(serialization_alias="firstSeen")
    status: BacklinkStatus

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> BacklinkResponse:
        status = row.get("status")
        return cls(
            id=str(row["id"]),
            client=row.get("client_name", ""),
            ref_domain=row.get("ref_domain", ""),
            anchor=row.get("anchor", ""),
            authority=int(row.get("authority", 0) or 0),
            spam=int(row.get("spam", 0) or 0),
            first_seen=format_date(row.get("first_seen"), empty="—"),
            status=status if status in _BACKLINK_STATUSES else "new",
        )


class CitationResponse(BaseModel):
    """One citation in the frontend ``Citation`` shape - and ONLY those 8 keys.
    ``action`` is the stored verb (kept in sync with ``nap`` via ``action_for`` on
    write); the internal ``client_id`` never leaks (``client`` is the snapshot).

    ``submit_status``/``proof_url`` are 7B-4's SUBMISSION-pipeline fields (additive
    on the same row, 0045) - distinct from ``nap``, which is the MONITORING verdict.
    A pre-0045 (monitoring-only) row has no ``submit_status`` at all, which reads as
    ``not_started`` here - honest, since nothing has ever tried to submit it."""

    id: str
    client: str
    directory: str
    nap: NapStatus
    action: CitationAction
    note: str
    submit_status: CitationSubmitStatus = Field(serialization_alias="submitStatus")
    proof_url: str = Field(serialization_alias="proofUrl")
    handoff_url: str = Field(default="", serialization_alias="handoffUrl")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> CitationResponse:
        nap = row.get("nap_status")
        nap_v: NapStatus = nap if nap in _NAP_STATUSES else "missing"
        action = row.get("action")
        # Prefer the stored action, but fall back to the derived rule so the value is
        # always coherent with the NAP state even for a partially-populated row.
        action_v: CitationAction = (
            action if action in _CITATION_ACTIONS else action_for(nap_v)
        )
        submit_status = row.get("submit_status")
        submit_status_v: CitationSubmitStatus = (
            submit_status if submit_status in _CITATION_SUBMIT_STATUSES else "not_started"
        )
        return cls(
            id=str(row["id"]),
            client=row.get("client_name", ""),
            directory=row.get("directory", ""),
            nap=nap_v,
            action=action_v,
            submit_status=submit_status_v,
            proof_url=row.get("proof_url", ""),
            handoff_url=row.get("handoff_url", ""),
            note=row.get("note", ""),
        )


class Web2PropertyResponse(BaseModel):
    """One Web 2.0 property in the frontend ``Web2Property`` shape - and ONLY those
    8 keys. ``id`` is the row uuid; the internal ``client_id`` never leaks.

    ``status`` (0028's pipeline state machine) is additive: a pre-pipeline row (one
    that already had a ``post_url`` before 0028 landed) defaults to ``published`` in
    the DB, so surfacing it here is a strict widening - the dashboard can now show
    the plan/approve UI's queue (``needs_review`` awaiting a lead) without a second
    endpoint, and every EXISTING consumer that only reads platform/postUrl/anchor/
    verified/published is unaffected."""

    id: str
    client: str
    platform: Web2Platform
    post_url: str = Field(serialization_alias="postUrl")
    anchor: str
    verified: Web2Verified
    published: str
    status: Web2PipelineStatus

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Web2PropertyResponse:
        platform = row.get("platform")
        verified = row.get("verified")
        status = row.get("status")
        return cls(
            id=str(row["id"]),
            client=row.get("client_name", ""),
            platform=platform if platform in _WEB2_PLATFORMS else "WordPress.com",
            post_url=row.get("post_url", ""),
            anchor=row.get("anchor", ""),
            verified=verified if verified in _WEB2_VERIFIED else "pending",
            published=format_date(row.get("published_at"), empty="—"),
            status=status if status in _WEB2_PIPELINE_STATUSES else "published",
        )


class OffpageKpisResponse(BaseModel):
    """The off-page summary tiles (frontend ``offpageKpis``). ``referringDomains`` is
    the live profile size (distinct referring domains); ``newLinks30d`` /
    ``lostLinks30d`` are the 30-day monitoring deltas; ``toxicFlagged`` is the
    disavow-review queue size (backlinks in ``toxic`` status)."""

    referring_domains: int = Field(serialization_alias="referringDomains")
    new_links_30d: int = Field(serialization_alias="newLinks30d")
    lost_links_30d: int = Field(serialization_alias="lostLinks30d")
    toxic_flagged: int = Field(serialization_alias="toxicFlagged")


class Web2PlatformCatalogResponse(BaseModel):
    """One row of the Web 2.0 platform CATALOG (``public.web2_platforms``, 0062/0063) -
    reference data, not tenant data (there is no ``client_id`` to leak).

    ``automationReady`` marks a platform the pipeline can publish to TODAY (a real
    ``Web2Publisher`` class + the ``web2_platform`` enum value both exist - the 0063 seed
    shipped 17 of these, since grown by 0068 + 0070's catalog upserts to match
    ``integrations.web2_publishers.WEB2_PLATFORMS``); every other row is a catalogued
    build target. ``authType`` is verbatim from the ``web2_auth_type`` enum;
    ``authorityTier`` is a directional high/medium/low (not a DA number)."""

    id: str
    name: str
    homepage_url: str = Field(serialization_alias="homepageUrl")
    signup_url: str = Field(serialization_alias="signupUrl")
    publish_method: str = Field(serialization_alias="publishMethod")
    auth_type: Web2AuthType = Field(serialization_alias="authType")
    authority_tier: Web2AuthorityTier = Field(serialization_alias="authorityTier")
    market: str
    automation_ready: bool = Field(serialization_alias="automationReady")
    notes: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Web2PlatformCatalogResponse:
        auth = row.get("auth_type")
        tier = row.get("authority_tier")
        return cls(
            id=str(row["id"]),
            name=row.get("name", ""),
            homepage_url=row.get("homepage_url", ""),
            signup_url=row.get("signup_url", ""),
            publish_method=row.get("publish_url_or_method", ""),
            auth_type=auth if auth in _WEB2_AUTH_TYPES else "automation",
            authority_tier=tier if tier in _WEB2_AUTHORITY_TIERS else "medium",
            market=row.get("market", "global") or "global",
            automation_ready=bool(row.get("automation_ready", False)),
            notes=row.get("notes", ""),
        )


class Web2CatalogResponse(BaseModel):
    """The Web 2.0 platform catalog plus a one-line rollup header: how many platforms
    total, how many are ``automationReady`` (the pipeline can publish to now), and the
    per-``authType`` breakdown - the web2 analogue of the citation engine board."""

    total: int
    automation_ready: int = Field(serialization_alias="automationReady")
    by_auth_type: dict[str, int] = Field(serialization_alias="byAuthType")
    platforms: list[Web2PlatformCatalogResponse]


# --- Request models -----------------------------------------------------------


class CitationActionRequest(BaseModel):
    """POST /offpage/citations/{id}/action body: mark a single listing handled.

    ``Submit`` (a missing listing was created) or ``Update`` (a drifted listing was
    fixed / re-verified) both resolve the NAP to ``consistent``. ``note`` optionally
    records the detail; omitted leaves the existing note.
    """

    action: CitationAction
    note: str | None = None


class CitationBulkRequest(BaseModel):
    """POST /offpage/citations/bulk body: mark many listings consistent at once.

    ``ids`` is the set of citation row ids the operator submitted/updated in a batch;
    each resolves to ``consistent`` (action -> ``Update``).
    """

    ids: list[str] = Field(min_length=1)


class FlagToxicRequest(BaseModel):
    """POST /offpage/backlinks/flag-toxic body: run the disavow-review flagger.

    Every monitored backlink whose ``spam`` score is at or above ``spam_threshold``
    is flagged ``toxic`` (queued for a disavow review). The threshold defaults to a
    conservative 60/100 and is capped to the 0-100 score range.
    """

    spam_threshold: int = Field(default=60, ge=0, le=100)


class Web2PlanRequest(BaseModel):
    """POST /offpage/web2/plan body: queue a new Web 2.0 property (lead-only).

    The article is drafted about ``topic`` (defaults to the ``anchor``) and carries ONE
    editorial backlink: ``anchor`` -> ``target_url`` (the client page). ``framework``
    accepts the ``"Auto"`` sentinel (the writer resolves it per page type). Nothing is
    published: the write worker parks it at ``needs_review`` for a lead to approve.
    """

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(min_length=1, alias="clientId")
    platform: Web2Platform
    anchor: str = Field(min_length=1)
    target_url: str = Field(min_length=1, alias="targetUrl")
    topic: str | None = None
    page_type: Web2PageType = Field(default="blog", alias="pageType")
    framework: str = "Auto"
    # First-hand grounding the writer grounds against (same contract as a content
    # job). Optional, but a property planned with NONE of these drafts with
    # ``[NEEDS:]`` gaps and holds at review, un-publishable - so supply real proof.
    # The endpoint seeds them verbatim into the property's ``source_pack``.
    proof_points: list[str] = Field(default_factory=list, alias="proofPoints", max_length=12)
    testimonials: list[str] = Field(default_factory=list, max_length=12)
    unique_data: list[str] = Field(default_factory=list, alias="uniqueData", max_length=12)
    services: list[str] = Field(default_factory=list, max_length=20)


class Web2ReviewRequest(BaseModel):
    """POST /offpage/web2/{id}/approve body: the lead's decision at the review gate.

    ``approve`` -> publishing (enqueues the publish worker); ``reject`` -> rejected.
    Defaults to ``approve`` (the endpoint's name).
    """

    action: Web2ReviewAction = "approve"
