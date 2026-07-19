"""Site Analytics request/response models - SERVER-AUTHORITATIVE.

No ``frontend/lib/*.ts`` type mirrors this module yet, so these shapes are owned
here (unlike the contract-locked Part-2/7 responses) - the module's own unit tests
freeze the emitted key set, the server-authoritative equivalent of the contract
lock. Python attributes stay snake_case; a multi-word wire key re-aliases to
camelCase via ``serialization_alias``.

``oauth_vault_ref`` NEVER leaks - each response model has no such field at all (not
an excluded one), mirroring ``GbpProfileResponse``. The only thing the wire says
about a token is the boolean ``oauthConnected``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TopQuery(BaseModel):
    query: str
    clicks: int
    impressions: int


class GscPropertyResponse(BaseModel):
    """One connected (or pending) Search Console property."""

    id: str
    client: str
    site_url: str = Field(serialization_alias="siteUrl")
    oauth_connected: bool = Field(serialization_alias="oauthConnected")
    last_synced_at: str | None = Field(serialization_alias="lastSyncedAt")
    clicks_28d: int = Field(serialization_alias="clicks28d")
    impressions_28d: int = Field(serialization_alias="impressions28d")
    ctr_28d: float = Field(serialization_alias="ctr28d")
    avg_position_28d: float = Field(serialization_alias="avgPosition28d")
    top_queries: list[TopQuery] = Field(serialization_alias="topQueries")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> GscPropertyResponse:
        synced = row.get("last_synced_at")
        queries = row.get("top_queries") or []
        return cls(
            id=str(row.get("id", "")),
            client=str(row.get("client_name", "") or ""),
            site_url=str(row.get("site_url", "") or ""),
            oauth_connected=bool(row.get("oauth_connected", False)),
            last_synced_at=synced.isoformat() if synced else None,
            clicks_28d=int(row.get("clicks_28d", 0) or 0),
            impressions_28d=int(row.get("impressions_28d", 0) or 0),
            ctr_28d=float(row.get("ctr_28d", 0) or 0),
            avg_position_28d=float(row.get("avg_position_28d", 0) or 0),
            top_queries=[TopQuery(**q) for q in queries if isinstance(q, dict)],
        )


class Ga4PropertyResponse(BaseModel):
    """One connected (or pending) GA4 property."""

    id: str
    client: str
    property_id: str = Field(serialization_alias="propertyId")
    oauth_connected: bool = Field(serialization_alias="oauthConnected")
    last_synced_at: str | None = Field(serialization_alias="lastSyncedAt")
    sessions_28d: int = Field(serialization_alias="sessions28d")
    users_28d: int = Field(serialization_alias="users28d")
    conversions_28d: int = Field(serialization_alias="conversions28d")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Ga4PropertyResponse:
        synced = row.get("last_synced_at")
        return cls(
            id=str(row.get("id", "")),
            client=str(row.get("client_name", "") or ""),
            property_id=str(row.get("property_id", "") or ""),
            oauth_connected=bool(row.get("oauth_connected", False)),
            last_synced_at=synced.isoformat() if synced else None,
            sessions_28d=int(row.get("sessions_28d", 0) or 0),
            users_28d=int(row.get("users_28d", 0) or 0),
            conversions_28d=int(row.get("conversions_28d", 0) or 0),
        )


class GscPropertyCreate(BaseModel):
    client_id: str = Field(min_length=1, alias="clientId")
    site_url: str = Field(min_length=1, alias="siteUrl")

    model_config = {"populate_by_name": True}


class Ga4PropertyCreate(BaseModel):
    client_id: str = Field(min_length=1, alias="clientId")
    property_id: str = Field(min_length=1, alias="propertyId")

    model_config = {"populate_by_name": True}


class ConnectGoogleResponse(BaseModel):
    """The result of a connect attempt: either a consent-screen URL to send the
    browser to, or an honest HOLD (mirrors ``RefreshQueuedResponse``'s ``held``
    vocabulary) when no Google OAuth client is configured yet."""

    authorize_url: str | None = Field(serialization_alias="authorizeUrl")
    held: bool = False
    reason: str = ""


class RefreshQueuedResponse(BaseModel):
    """The accepted-for-sync acknowledgement: what was queued, and that it was.

    ``held`` is the honest degraded answer for a sync that cannot run yet (no
    OAuth client / no connected token): the request was understood and NOT
    queued, rather than silently dropped or crashed. Mirrors local_seo's own copy.
    """

    id: str
    queued: bool
    held: bool = False
    reason: str = ""
