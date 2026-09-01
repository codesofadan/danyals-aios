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
    # 0106. `submitted` STOPS meaning done: every write path we have returns it honestly
    # and none can promise more (Data Axle runs teleresearch for up to three business
    # days, Apple returns state SUBMITTED, GBP needs verification before it appears).
    "live",  # fetched live_url and found the business on the page - the ONLY earned one
    "drifted",  # the listing exists but its NAP no longer matches ours: correct, don't rebuild
    "delisted",  # it was live and now it is gone
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
     "ready_for_human",
     # 0106's earned states. These were MISSING here while present in the Literal five
     # lines up, so `from_row`'s guard coerced a genuinely fetch-verified `live` row —
     # the only status this module actually earns — to "not_started" on the wire. The
     # one screen that listed citations could therefore never show a success.
     "live", "drifted", "delisted"}
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
    # 0106's public listing URL — the thing a client can open and track. Empty until a
    # completion was fetch-verified. This is NOT proof_url (a screenshot).
    live_url: str = Field(default="", serialization_alias="liveUrl")
    # Why a row is on hold, as the machine-readable code the frontend maps to a
    # sentence (lib/citationStatus.ts). Empty for rows that are not blocked.
    blocked_reason: str = Field(default="", serialization_alias="blockedReason")

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
        # `citations.proof_url` stores a RELATIVE STORAGE KEY (evidence.py). It used to
        # be serialized raw, so the UI linked "/admin/citations/ab12cd34.png" — a 404,
        # every time, on the one column labelled "proof". Emit the real reader instead.
        proof_key = str(row.get("proof_url") or "")
        proof_link = (
            f"/api/v1/citation-builder/citations/{row['id']}/proof" if proof_key else ""
        )
        return cls(
            id=str(row["id"]),
            client=row.get("client_name", ""),
            directory=row.get("directory", ""),
            nap=nap_v,
            action=action_v,
            submit_status=submit_status_v,
            proof_url=proof_link,
            handoff_url=row.get("handoff_url", ""),
            live_url=str(row.get("live_url") or ""),
            blocked_reason=str(row.get("blocked_reason") or ""),
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
    #: platform -> the credential fields it needs, straight from the publishers' own map.
    #: Served rather than duplicated in the frontend so the registration form cannot
    #: drift from what the publisher actually validates: a hand-copied list would fall
    #: out of date the first time a platform changed its auth, and the operator would
    #: fill in fields that seal into a credential the publisher then rejects.
    credential_fields: dict[str, list[str]] = Field(
        default_factory=dict, serialization_alias="credentialFields"
    )


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


class Web2AnchorCheckRequest(BaseModel):
    """POST /offpage/web2/anchor-check body: is this anchor usable, before we spend?

    Deliberately mirrors the fields ``check_anchor`` actually reads. It is NOT a
    trimmed-down copy of :class:`Web2PlanRequest` - a caller must be able to ask about
    an anchor before it has decided a platform or gathered proof points.
    """

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(min_length=1, alias="clientId")
    anchor: str = Field(default="", max_length=300)
    target_url: str = Field(default="", alias="targetUrl", max_length=2000)
    topic: str = Field(default="", max_length=300)


class Web2AnchorCheckResponse(BaseModel):
    """The anchor verdict, in the shape a form field can render directly."""

    allowed: bool
    verdict: str
    reason: str
    suggestion: str


Web2PacingMode = Literal["immediate", "drip"]
Web2CampaignStatus = Literal[
    "draft", "planning", "needs_approval", "scheduled", "running",
    "completed", "degraded", "cancelled",
]


class Web2PlatformStatusResponse(BaseModel):
    """One row of the three-state platform board for a client.

    ``notEligible`` carries the platform's OWN stated reason rather than a generic
    refusal, because an operator told "dev.to bans promotional content for non-developer
    clients" learns the rule, while one told "not allowed" learns only that the software
    said no. Nothing is hidden from the board - the full catalogue stays visible, which
    is what makes offering "50+ platforms" honest rather than a silently shorter list.
    """

    name: str
    platform: str | None = None
    status: Literal["eligible", "not_connected", "not_eligible", "not_reviewed", "not_supported"]
    reason: str = ""
    authority: str = Field(default="", serialization_alias="authorityTier")
    #: When the platform's terms were last read by a human (ISO date, "" = never) and
    #: where. `not_reviewed` vs `not_eligible` is the difference between "nobody has
    #: looked" and "we looked and it said no" - the date is the evidence for the second.
    terms_checked_on: str = Field(default="", serialization_alias="termsCheckedOn")
    terms_source_url: str = Field(default="", serialization_alias="termsSourceUrl")
    #: HOW TO CONNECT IT, carried on the row that says it is not connected. Telling an
    #: operator a platform is unconnected without telling them what to do about it is
    #: what left provisioning an engineer's errand and clients sitting at zero platforms.
    #: `cost` and `blocker` are load-bearing: a teammate sent to fetch a token that needs
    #: a paid plan, or that expires in seven days, has been sent on an uncosted errand.
    setup_url: str = Field(default="", serialization_alias="setupUrl")
    setup_steps: str = Field(default="", serialization_alias="setupSteps")
    setup_cost: str = Field(default="", serialization_alias="setupCost")
    setup_blocker: str = Field(default="", serialization_alias="setupBlocker")
    account_needed: str = Field(default="", serialization_alias="accountNeeded")
    credential_fields: list[str] = Field(
        default_factory=list, serialization_alias="credentialFields"
    )


class Web2CampaignRequest(BaseModel):
    """POST /offpage/web2/campaigns: one operator request for N properties."""

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(min_length=1, alias="clientId")
    title: str = ""
    article_count: int = Field(ge=1, le=200, alias="articleCount")
    # DISTINCT topics, one per article. Reusing a topic across properties produces
    # byte-identical articles (measured), so the planner refuses rather than publishing
    # duplicates - the count is validated against this list, not padded from it.
    topics: list[str] = Field(default_factory=list, max_length=200)
    platforms: list[str] = Field(default_factory=list, max_length=60)
    anchors: list[str] = Field(default_factory=list, max_length=60)
    target_url: str = Field(min_length=1, alias="targetUrl")
    pacing: Web2PacingMode = "drip"
    drip_window_days: int = Field(default=30, ge=0, le=365, alias="dripWindowDays")
    cost_ceiling_usd: float = Field(default=0.0, ge=0, alias="costCeilingUsd")
    proof_points: list[str] = Field(default_factory=list, alias="proofPoints", max_length=12)
    testimonials: list[str] = Field(default_factory=list, max_length=12)
    unique_data: list[str] = Field(default_factory=list, alias="uniqueData", max_length=12)
    services: list[str] = Field(default_factory=list, max_length=20)


class Web2PlannedPropertyResponse(BaseModel):
    """One property a plan would create - shown in the estimate before committing."""

    platform: str
    topic: str
    anchor: str
    framework: str
    scheduled_for: str = Field(default="", serialization_alias="scheduledFor")


class Web2CampaignEstimateResponse(BaseModel):
    """The pre-commit quote: what it would create, cost, and when it would finish.

    Shown BEFORE anything is queued. Thirty properties is thirty metered drafting runs
    and, at the default pacing, about a month of publishing - both facts belong in front
    of the operator at the moment they decide, not afterwards.
    """

    count: int
    estimated_cost_usd: float = Field(serialization_alias="estimatedCostUsd")
    projected_completion: str = Field(default="", serialization_alias="projectedCompletion")
    properties: list[Web2PlannedPropertyResponse] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Web2CampaignResponse(BaseModel):
    """A campaign as the board shows it. ``client_id`` never leaks."""

    id: str
    client: str
    title: str
    status: Web2CampaignStatus
    article_count: int = Field(serialization_alias="articleCount")
    platforms: list[str] = Field(default_factory=list)
    pacing: Web2PacingMode
    estimated_cost_usd: float = Field(default=0.0, serialization_alias="estimatedCostUsd")
    spent_usd: float = Field(default=0.0, serialization_alias="spentUsd")
    published: int = 0
    total: int = 0
    next_publish: str = Field(default="", serialization_alias="nextPublish")

    @classmethod
    def from_row(cls, row: dict[str, Any], *, published: int = 0, total: int = 0,
                 next_publish: str = "") -> Web2CampaignResponse:
        status = row.get("status")
        pacing = row.get("pacing")
        return cls(
            id=str(row["id"]),
            client=str(row.get("client_name") or ""),
            title=str(row.get("title") or ""),
            status=status if status in _CAMPAIGN_STATUSES else "draft",
            article_count=int(row.get("article_count") or 0),
            platforms=list(row.get("platforms") or []),
            pacing=pacing if pacing in ("immediate", "drip") else "drip",
            estimated_cost_usd=float(row.get("cost_ceiling_usd") or 0.0),
            spent_usd=float(row.get("spent_usd") or 0.0),
            published=published,
            total=total,
            next_publish=next_publish,
        )


class Web2AccountCreateRequest(BaseModel):
    """Register one publishing account (lead-only).

    ``credential`` is field -> value for THIS platform's shape (the board already tells
    the UI which fields it needs). It is sealed into the vault and never read back: no
    response, no log, no error message ever carries it.
    """

    model_config = ConfigDict(populate_by_name=True)

    platform: str
    ownership: str = "per_client"
    client_id: str = Field(default="", alias="clientId")
    handle: str
    email: str = ""
    property_url: str = Field(default="", alias="propertyUrl")
    max_properties: int = Field(default=1, alias="maxProperties", ge=1, le=500)
    credential: dict[str, str] = Field(default_factory=dict)


class Web2AccountResponse(BaseModel):
    """One publishing account on the operator's connection board.

    Carries the vault COORDINATES but never the secret: the board's job is to say where
    a credential lives and whether it works, not what it is. `client_id` never leaks —
    the client NAME is joined for display.
    """

    id: str
    platform: Web2Platform
    ownership: str
    client: str = ""
    handle: str = ""
    property_url: str = Field(default="", serialization_alias="propertyUrl")
    email: str = ""
    health: str = "unverified"
    checked: str = ""
    properties: int = 0
    max_properties: int = Field(default=1, serialization_alias="maxProperties")
    #: Which credential fields this platform needs — drives the form, so a new platform
    #: needs no frontend change.
    required: list[str] = Field(default_factory=list)
    #: True when the sealed credential is structurally complete (a publisher builds).
    complete: bool = False

    @classmethod
    def from_row(
        cls, row: dict[str, Any], *, required: list[str], complete: bool
    ) -> Web2AccountResponse:
        platform = row.get("platform")
        return cls(
            id=str(row["id"]),
            platform=platform if platform in _WEB2_PLATFORMS else "WordPress.com",
            ownership=str(row.get("ownership") or ""),
            client=str(row.get("client_name") or ""),
            handle=str(row.get("handle") or ""),
            property_url=str(row.get("property_url") or ""),
            email=str(row.get("registration_email") or ""),
            health=str(row.get("health") or "unverified"),
            checked=format_date(row.get("health_checked_at"), empty=""),
            properties=int(row.get("property_count") or 0),
            max_properties=int(row.get("max_properties") or 1),
            required=required,
            complete=complete,
        )


class Web2AccountCheckResponse(BaseModel):
    """What a live verification found.

    `state` is tri-state on purpose — ok / bad / unknown. "We could not ask" must stay
    distinguishable from "the platform said no", or the board starts reporting outages
    as revoked tokens and sends people to re-issue credentials that were fine.
    """

    account_id: str = Field(serialization_alias="accountId")
    state: str
    detail: str = ""
    identity: str = ""
    health: str = "unverified"


class Web2PlacementResponse(BaseModel):
    """One Web 2.0 placement, in full - the operator's and the client's audit trail.

    Deliberately WIDER than `Web2PropertyResponse` (8 keys, contract-locked to the
    ledger table) and deliberately a separate model rather than a widening of it. Every
    field here was already stored and none of it was reachable, so a finished campaign
    could not be shown to anyone: no topic, no destination, no live-link proof, and no
    reason when something was held.

    `linkFound` / `linkRel` are the honest part. "Published" only means the platform
    accepted the post; whether OUR link is actually on the page, and whether it is
    followed, is a separate measured fact. Reporting a placement as delivered without it
    is how an agency ends up invoicing for a link that a platform stripped.

    `client_id` never leaks - the client NAME is snapshotted on the row.
    """

    id: str
    client: str
    platform: Web2Platform
    topic: str = ""
    framework: str = ""
    anchor: str = ""
    target_url: str = Field(default="", serialization_alias="targetUrl")
    post_url: str = Field(default="", serialization_alias="postUrl")
    status: Web2PipelineStatus = "draft"
    verified: Web2Verified = "pending"
    # "" until the page has actually been fetched; then the measured rel, e.g. "nofollow".
    link_rel: str = Field(default="", serialization_alias="linkRel")
    link_found: bool | None = Field(default=None, serialization_alias="linkFound")
    link_checked: str = Field(default="", serialization_alias="linkChecked")
    scheduled_for: str = Field(default="", serialization_alias="scheduledFor")
    published: str = ""
    created: str = ""
    account: str = ""
    # 'house' vs 'per_client' - shown because a shared-account placement and a
    # client-owned one look identical on a link report and are not the same asset.
    account_ownership: str = Field(default="", serialization_alias="accountOwnership")
    shared_origin: bool = Field(default=False, serialization_alias="sharedOrigin")
    note: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Web2PlacementResponse:
        platform = row.get("platform")
        verified = row.get("verified")
        status = row.get("status")
        found = row.get("link_found")
        return cls(
            id=str(row["id"]),
            client=str(row.get("client_name") or ""),
            platform=platform if platform in _WEB2_PLATFORMS else "WordPress.com",
            topic=str(row.get("topic") or ""),
            framework=str(row.get("framework") or ""),
            anchor=str(row.get("anchor") or ""),
            target_url=str(row.get("target_url") or ""),
            post_url=str(row.get("post_url") or ""),
            status=status if status in _WEB2_PIPELINE_STATUSES else "draft",
            verified=verified if verified in _WEB2_VERIFIED else "pending",
            link_rel=str(row.get("link_rel") or ""),
            link_found=found if isinstance(found, bool) else None,
            link_checked=format_date(row.get("link_checked_at"), empty=""),
            scheduled_for=format_date(row.get("scheduled_for"), empty=""),
            published=format_date(row.get("published_at"), empty=""),
            created=format_date(row.get("created_at"), empty=""),
            account=str(row.get("account_handle") or ""),
            account_ownership=str(row.get("account_ownership") or ""),
            shared_origin=bool(row.get("shared_origin")),
            note=str(row.get("error") or "")[:200],
        )


class Web2CampaignHold(BaseModel):
    """One property a bulk approval REFUSED to wave through.

    Reported per property rather than as a count, because "three were held" is not
    actionable - the operator needs to know which topic on which platform collided so
    they can redraft that one and approve the rest.
    """

    web2_id: str = Field(serialization_alias="web2Id")
    topic: str = ""
    platform: str = ""
    reason: str = ""


class Web2CampaignApprovalResponse(BaseModel):
    """What one campaign-level decision actually did.

    Deliberately reports approved / held / rejected separately instead of a single
    success flag: an approval that published twenty-seven of thirty and held three is
    NOT a clean approval, and a response that rounded it to "ok" would be the same
    partial-delivery-as-success defect the campaign board exists to prevent.
    """

    campaign_id: str = Field(serialization_alias="campaignId")
    status: Web2CampaignStatus
    approved: int = 0
    held: list[Web2CampaignHold] = Field(default_factory=list)
    rejected: int = 0


_CAMPAIGN_STATUSES = frozenset(
    ["draft", "planning", "needs_approval", "scheduled", "running",
     "completed", "degraded", "cancelled"]
)


class Web2ReviewRequest(BaseModel):
    """POST /offpage/web2/{id}/approve body: the lead's decision at the review gate.

    ``approve`` -> publishing (enqueues the publish worker); ``reject`` -> rejected.
    Defaults to ``approve`` (the endpoint's name).

    ``acknowledge_similarity`` is the lead's explicit "I have read the collision and this
    placement is still genuinely distinct". It is REQUIRED whenever the similarity gate
    recorded a warn or a block on the row. Requiring a separate, named acknowledgement -
    rather than letting a plain approve carry it - is what stops the gate degrading into
    a click-through: an operator who must state that they saw the collision cannot
    approve past it by habit. It is the same shape the content module's QA scorecard
    takes (advisory + mandatory acknowledgement, D-4).
    """

    model_config = ConfigDict(populate_by_name=True)

    action: Web2ReviewAction = "approve"
    acknowledge_similarity: bool = Field(default=False, alias="acknowledgeSimilarity")
