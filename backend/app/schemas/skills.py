"""Skill-token request/response models (Part 9 Skills gateway).

These are INTERNAL shapes (no frontend TS mirror): a skill token is agency
infrastructure, not a dashboard record. The raw secret appears in exactly ONE
shape - :class:`SkillTokenMinted`, returned once at mint - and NEVER in a list,
read, or verify response. ``token_hash`` is never serialized anywhere.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.rbac import PermKey

# Delivery-tier cap a token may carry (mirrors public.delivery_tier).
SkillTierName = Literal["free", "semi", "fully"]


class SkillTokenCreate(BaseModel):
    """Owner/admin request to mint a per-client skill token (a capped scope)."""

    client_id: str = Field(min_length=1)
    # The RBAC subset the token carries. Unknown perms/features are dropped when
    # capped (see the service); an empty grant is a safe deny-all token.
    perms: list[PermKey] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    tier: SkillTierName = "free"
    # Optional lifetime override (seconds); the service defaults it from settings.
    ttl_seconds: int | None = Field(default=None, ge=60)
    label: str = ""


class SkillTokenResponse(BaseModel):
    """A masked skill-token metadata row - NEVER the secret and NEVER the hash."""

    id: str
    client_id: str
    token_prefix: str
    perms: list[str]
    features: list[str]
    tier: str
    revoked: bool
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> SkillTokenResponse:
        scopes = row.get("scopes") or {}
        return cls(
            id=str(row["id"]),
            client_id=str(row["client_id"]),
            token_prefix=row.get("token_prefix", ""),
            perms=list(scopes.get("perms", [])),
            features=list(scopes.get("features", [])),
            tier=row.get("tier", "free"),
            revoked=bool(row.get("revoked", False)),
            expires_at=row.get("expires_at"),
            last_used_at=row.get("last_used_at"),
            created_at=row.get("created_at"),
        )


class SkillTokenMinted(SkillTokenResponse):
    """The mint result: the masked metadata PLUS the raw token, shown ONCE.

    The ``token`` field is the ONLY place the raw secret is ever returned; the
    caller must persist it immediately (it is unrecoverable - only its hash is
    stored). It is absent from every other response.
    """

    token: str


class SkillPrincipalResponse(BaseModel):
    """The verify result: the SCOPED PRINCIPAL a valid token resolves to.

    Carries only the capped scope - a tenant id, the perm/feature subset, the tier
    cap, and the token id. NEVER the secret, NEVER the hash. This is what the MCP
    gateway authorizes each tool call against.
    """

    token_id: str
    client_id: str
    perms: list[str]
    features: list[str]
    tier: str
    expires_at: datetime | None = None


class SkillTokenRevokeResponse(BaseModel):
    id: str
    revoked: bool
