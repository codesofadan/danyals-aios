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
Web2Platform = Literal["WordPress.com", "Blogger", "Tumblr", "Medium"]
Web2Verified = Literal["verified", "pending"]

_BACKLINK_STATUSES: frozenset[str] = frozenset({"new", "lost", "toxic"})
_NAP_STATUSES: frozenset[str] = frozenset({"consistent", "inconsistent", "missing"})
_CITATION_ACTIONS: frozenset[str] = frozenset({"Submit", "Update"})
_WEB2_PLATFORMS: frozenset[str] = frozenset(
    {"WordPress.com", "Blogger", "Tumblr", "Medium"}
)
_WEB2_VERIFIED: frozenset[str] = frozenset({"verified", "pending"})


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
    """One citation in the frontend ``Citation`` shape - and ONLY those 6 keys.
    ``action`` is the stored verb (kept in sync with ``nap`` via ``action_for`` on
    write); the internal ``client_id`` never leaks (``client`` is the snapshot)."""

    id: str
    client: str
    directory: str
    nap: NapStatus
    action: CitationAction
    note: str

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
        return cls(
            id=str(row["id"]),
            client=row.get("client_name", ""),
            directory=row.get("directory", ""),
            nap=nap_v,
            action=action_v,
            note=row.get("note", ""),
        )


class Web2PropertyResponse(BaseModel):
    """One Web 2.0 property in the frontend ``Web2Property`` shape - and ONLY those
    7 keys. ``id`` is the row uuid; the internal ``client_id`` never leaks."""

    id: str
    client: str
    platform: Web2Platform
    post_url: str = Field(serialization_alias="postUrl")
    anchor: str
    verified: Web2Verified
    published: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Web2PropertyResponse:
        platform = row.get("platform")
        verified = row.get("verified")
        return cls(
            id=str(row["id"]),
            client=row.get("client_name", ""),
            platform=platform if platform in _WEB2_PLATFORMS else "WordPress.com",
            post_url=row.get("post_url", ""),
            anchor=row.get("anchor", ""),
            verified=verified if verified in _WEB2_VERIFIED else "pending",
            published=format_date(row.get("published_at"), empty="—"),
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


class Web2ReviewRequest(BaseModel):
    """POST /offpage/web2/{id}/approve body: the lead's decision at the review gate.

    ``approve`` -> publishing (enqueues the publish worker); ``reject`` -> rejected.
    Defaults to ``approve`` (the endpoint's name).
    """

    action: Web2ReviewAction = "approve"
