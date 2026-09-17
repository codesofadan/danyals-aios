"""Moz Links API client.

Auth via API Token (Moz Links API v3). Provides backlink profile, referring
domains, anchor distribution, and spam score. Graceful degrade if no key.

Endpoint base: https://lsapi.seomoz.com/v2/
Auth: Basic (access_id : secret_key). For 2026 Links API v3 the token model is
used; we expose both for flexibility.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

from audit_engine.integrations.base import BaseClient
from audit_engine.logging_setup import get_logger

log = get_logger(__name__)

MOZ_BASE = "https://lsapi.seomoz.com/v2"


@dataclass(frozen=True)
class DomainAuthority:
    target: str
    domain_authority: float | None
    page_authority: float | None
    spam_score: float | None
    linking_root_domains: int | None
    external_pages_to_root_domain: int | None
    error: str | None = None


@dataclass
class Backlink:
    source_url: str
    target_url: str
    source_domain: str
    anchor_text: str | None
    is_dofollow: bool
    source_da: float | None
    source_spam_score: float | None


@dataclass
class BacklinkProfile:
    target: str
    referring_domains: int | None
    backlink_count: int | None
    sample_links: list[Backlink] = field(default_factory=list)
    anchor_distribution: dict[str, int] = field(default_factory=dict)
    error: str | None = None


class MozClient(BaseClient):
    provider_name = "moz"
    base_url = MOZ_BASE

    def __init__(
        self,
        *,
        access_id: str | None = None,
        secret_key: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if access_id and secret_key:
            token = base64.b64encode(f"{access_id}:{secret_key}".encode()).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
            self._enabled = True
        else:
            self._enabled = False
        super().__init__(timeout=timeout, max_retries=2, headers=headers)

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def domain_authority(self, target: str) -> DomainAuthority:
        if not self._enabled:
            return DomainAuthority(
                target=target,
                domain_authority=None,
                page_authority=None,
                spam_score=None,
                linking_root_domains=None,
                external_pages_to_root_domain=None,
                error="MOZ_ACCESS_ID/MOZ_SECRET_KEY not set",
            )
        try:
            resp = await self.post(
                "url_metrics",
                json_body={"targets": [target]},
            )
            data = resp.json()
            results = data.get("results") or []
            row = results[0] if results else {}
        except Exception as e:  # noqa: BLE001
            log.error("moz_domain_authority_failed", target=target, error=type(e).__name__)
            return DomainAuthority(
                target=target,
                domain_authority=None,
                page_authority=None,
                spam_score=None,
                linking_root_domains=None,
                external_pages_to_root_domain=None,
                error=f"{type(e).__name__}: {e}",
            )

        return DomainAuthority(
            target=target,
            domain_authority=row.get("domain_authority"),
            page_authority=row.get("page_authority"),
            spam_score=row.get("spam_score"),
            linking_root_domains=row.get("root_domains_to_root_domain"),
            external_pages_to_root_domain=row.get("external_pages_to_root_domain"),
        )

    async def backlinks(self, target: str, *, limit: int = 50) -> BacklinkProfile:
        if not self._enabled:
            return BacklinkProfile(
                target=target,
                referring_domains=None,
                backlink_count=None,
                error="MOZ_ACCESS_ID/MOZ_SECRET_KEY not set",
            )
        try:
            resp = await self.post(
                "links",
                json_body={
                    "target": target,
                    "target_scope": "page",
                    "filter": "external",
                    "limit": limit,
                },
            )
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            log.error("moz_backlinks_failed", target=target, error=type(e).__name__)
            return BacklinkProfile(
                target=target,
                referring_domains=None,
                backlink_count=None,
                error=f"{type(e).__name__}: {e}",
            )

        sample: list[Backlink] = []
        anchor_counts: dict[str, int] = {}
        for row in data.get("results") or []:
            anchor = (row.get("anchor_text") or "").strip().lower()
            anchor_counts[anchor] = anchor_counts.get(anchor, 0) + 1
            sample.append(
                Backlink(
                    source_url=row.get("source", {}).get("page") or row.get("source") or "",
                    target_url=row.get("target", {}).get("page") or row.get("target") or "",
                    source_domain=row.get("source", {}).get("root_domain") or "",
                    anchor_text=row.get("anchor_text"),
                    is_dofollow=row.get("flags", {}).get("dofollow", False) if isinstance(row.get("flags"), dict) else False,
                    source_da=row.get("source", {}).get("domain_authority") if isinstance(row.get("source"), dict) else None,
                    source_spam_score=row.get("source", {}).get("spam_score") if isinstance(row.get("source"), dict) else None,
                )
            )

        return BacklinkProfile(
            target=target,
            referring_domains=data.get("referring_domains_count"),
            backlink_count=data.get("total_count") or len(sample),
            sample_links=sample,
            anchor_distribution=anchor_counts,
        )
