"""Client-portal response shapes (the tenant-facing dashboard).

These carry only client-safe data sourced from the ``portal_*`` security-barrier
views - a client's own name/industry/tier, its sites (id + domain), and headline
audit figures. No agency-internal fields (mrr, contacts, cost, paths) appear.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.audits import PortalAuditResponse
from app.util.timefmt import format_when


class PortalSiteResponse(BaseModel):
    """One of the caller's sites (id + domain only)."""

    id: str
    domain: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> PortalSiteResponse:
        return cls(id=str(row["id"]), domain=row.get("domain", ""))


class ClientDashboard(BaseModel):
    """The portal landing summary for the authenticated client."""

    client: str  # the client's own name
    delivery_tier: str = Field(serialization_alias="deliveryTier")
    latest_score: int | None = Field(default=None, serialization_alias="latestScore")
    latest_audit_when: str = Field(default="", serialization_alias="latestAuditWhen")
    total_audits: int = Field(default=0, serialization_alias="totalAudits")
    sites: list[PortalSiteResponse] = Field(default_factory=list)

    @classmethod
    def build(
        cls,
        client_row: dict[str, Any],
        audits: list[dict[str, Any]],
        sites: list[dict[str, Any]],
    ) -> ClientDashboard:
        """Assemble the dashboard from the client's own view rows.

        ``audits`` is newest-first. The headline ``latestScore`` is the most
        recent audit that actually has a score (a queued/running run has none),
        while ``latestAuditWhen`` reflects the most recent run of any status.
        """
        latest_when = format_when(audits[0].get("created_at")) if audits else ""
        latest_score: int | None = None
        for a in audits:
            score = a.get("score")
            if score is not None:
                latest_score = int(score)
                break
        return cls(
            client=client_row.get("name", ""),
            delivery_tier=str(client_row.get("delivery_tier", "free")),
            latest_score=latest_score,
            latest_audit_when=latest_when,
            total_audits=len(audits),
            sites=[PortalSiteResponse.from_row(s) for s in sites],
        )


__all__ = ["ClientDashboard", "PortalAuditResponse", "PortalSiteResponse"]
