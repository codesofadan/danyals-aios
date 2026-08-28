"""DataForSEO: the backlink profile.

Thirty-nine checks declared a Moz data source and none of them could ever run -
``MOZ_ACCESS_ID`` and ``MOZ_SECRET_KEY`` are empty, and Moz was never reachable.
The owner authorised DataForSEO on 2026-08-25, superseding an earlier
prohibition in CLAUDE.md.

**One call answers most of the wave.** ``backlinks/summary`` returns the
profile: rank, referring domains, referring IPs and subnets, the spam score,
broken backlinks, and distributions by TLD, country, platform, link type, link
attribute and semantic location. A second call fetches the anchor distribution.
Two requests, about five cents, for thirty-nine checks - which is why they are
built around a single fetched profile rather than one call per check.

Billed per request, so every check that reads this is classed ``billable`` and
cannot run on a free tier.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

from audit_engine.integrations.base import BaseClient
from audit_engine.logging_setup import get_logger
from audit_engine.security import PrivateAddressError, validate_public_host

log = get_logger(__name__)

DFS_API = "https://api.dataforseo.com/v3"

#: Anchors returned per request. The distribution's SHAPE is what the checks
#: read, and the long tail past a few hundred does not change it.
ANCHOR_LIMIT = 200


@dataclass
class BacklinkProfile:
    """One site's backlink profile, or the reason there isn't one.

    Field names mirror DataForSEO's so a reader can check any number against
    the raw response without a translation table.
    """

    target: str
    error: str | None = None

    rank: int | None = None                    # 0-1000 domain strength
    backlinks: int = 0
    referring_domains: int = 0
    referring_main_domains: int = 0
    referring_domains_nofollow: int = 0
    referring_pages: int = 0
    referring_pages_nofollow: int = 0
    referring_ips: int = 0
    referring_subnets: int = 0
    broken_backlinks: int = 0
    broken_pages: int = 0
    backlinks_spam_score: int | None = None
    target_spam_score: int | None = None
    first_seen: str | None = None
    lost_date: str | None = None
    crawled_pages: int = 0
    external_links_count: int = 0
    internal_links_count: int = 0

    #: Distributions, each a name -> count map straight from the response.
    tld: dict[str, int] = field(default_factory=dict)
    countries: dict[str, int] = field(default_factory=dict)
    platform_types: dict[str, int] = field(default_factory=dict)
    link_types: dict[str, int] = field(default_factory=dict)
    link_attributes: dict[str, int] = field(default_factory=dict)
    semantic_locations: dict[str, int] = field(default_factory=dict)
    #: anchor text -> referring-domain count, biggest first.
    anchors: dict[str, int] = field(default_factory=dict)
    #: The target's own server/CMS/country, as the provider sees it.
    info: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def has_links(self) -> bool:
        """A site with no backlinks is a valid, common answer - not an error."""
        return self.ok and self.referring_domains > 0


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class DataForSeoClient(BaseClient):
    """Backlink endpoints only. Everything here is billed per request."""

    provider_name = "dataforseo"
    base_url = DFS_API

    def __init__(
        self, *, login: str | None = None, password: str | None = None,
        timeout: float = 90.0,
    ) -> None:
        super().__init__(timeout=timeout, max_retries=2)
        self._login = login
        self._password = password

    @property
    def _auth_header(self) -> dict[str, str]:
        token = base64.b64encode(f"{self._login}:{self._password}".encode()).decode()
        return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

    async def profile(self, target: str) -> BacklinkProfile:
        """The whole profile in two calls. Never raises."""
        if not (self._login and self._password):
            return BacklinkProfile(target=target, error="no DataForSEO credentials configured")
        try:
            host = validate_public_host(target)
        except (PrivateAddressError, ValueError) as e:
            return BacklinkProfile(target=target, error=f"refused: {e}")

        summary = await self._summary(host)
        if summary.error:
            return summary
        summary.anchors = await self._anchors(host)
        return summary

    async def _summary(self, host: str) -> BacklinkProfile:
        try:
            resp = await self.post(
                "/backlinks/summary/live",
                json_body=[{
                    "target": host, "internal_list_limit": 10,
                    "backlinks_status_type": "live",
                }],
                headers=self._auth_header,
            )
            payload = resp.json()
        except Exception as e:
            log.warning("dataforseo_summary_failed", error=type(e).__name__)
            return BacklinkProfile(target=host, error=f"{type(e).__name__}: {str(e)[:160]}")

        task = (payload.get("tasks") or [{}])[0]
        if task.get("status_code") != 20000:
            return BacklinkProfile(
                target=host, error=str(task.get("status_message") or "provider error")[:160]
            )
        r = (task.get("result") or [{}])[0] or {}
        info = r.get("info") or {}
        return BacklinkProfile(
            target=host,
            rank=_as_int(r.get("rank"), 0) or None,
            backlinks=_as_int(r.get("backlinks")),
            referring_domains=_as_int(r.get("referring_domains")),
            referring_main_domains=_as_int(r.get("referring_main_domains")),
            referring_domains_nofollow=_as_int(r.get("referring_domains_nofollow")),
            referring_pages=_as_int(r.get("referring_pages")),
            referring_pages_nofollow=_as_int(r.get("referring_pages_nofollow")),
            referring_ips=_as_int(r.get("referring_ips")),
            referring_subnets=_as_int(r.get("referring_subnets")),
            broken_backlinks=_as_int(r.get("broken_backlinks")),
            broken_pages=_as_int(r.get("broken_pages")),
            backlinks_spam_score=_as_int(r.get("backlinks_spam_score"), -1) if
            r.get("backlinks_spam_score") is not None else None,
            target_spam_score=_as_int(info.get("target_spam_score"), -1) if
            info.get("target_spam_score") is not None else None,
            first_seen=r.get("first_seen"),
            lost_date=r.get("lost_date"),
            crawled_pages=_as_int(r.get("crawled_pages")),
            external_links_count=_as_int(r.get("external_links_count")),
            internal_links_count=_as_int(r.get("internal_links_count")),
            tld=dict(r.get("referring_links_tld") or {}),
            countries=dict(r.get("referring_links_countries") or {}),
            platform_types=dict(r.get("referring_links_platform_types") or {}),
            link_types=dict(r.get("referring_links_types") or {}),
            link_attributes=dict(r.get("referring_links_attributes") or {}),
            semantic_locations=dict(r.get("referring_links_semantic_locations") or {}),
            info=dict(info),
        )

    async def _anchors(self, host: str) -> dict[str, int]:
        """Anchor text distribution. A failure here loses the anchor checks,
        not the profile, so it returns empty rather than propagating."""
        try:
            resp = await self.post(
                "/backlinks/anchors/live",
                json_body=[{
                    "target": host, "limit": ANCHOR_LIMIT,
                    "backlinks_status_type": "live",
                    "order_by": ["referring_domains,desc"],
                }],
                headers=self._auth_header,
            )
            payload = resp.json()
        except Exception as e:
            log.warning("dataforseo_anchors_failed", error=type(e).__name__)
            return {}
        task = (payload.get("tasks") or [{}])[0]
        if task.get("status_code") != 20000:
            return {}
        items = ((task.get("result") or [{}])[0] or {}).get("items") or []
        out: dict[str, int] = {}
        for item in items:
            anchor = (item.get("anchor") or "").strip()
            if anchor:
                out[anchor] = _as_int(item.get("referring_domains"))
        return out
