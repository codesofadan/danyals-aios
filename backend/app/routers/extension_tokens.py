"""Pairing the citation extension: mint, list and revoke a device credential.

The raw token is shown EXACTLY ONCE, at mint, and never again - only its sha256 is
stored. That is the model 0030 already committed this codebase to for skill tokens, and
reusing it means pairing introduces no new concepts and no new unauthenticated surface.

WHY COPY-PASTE AND NOT A DEVICE FLOW. A device/OAuth-style flow needs an unauthenticated
`pair/start` endpoint plus an unauthenticated poll. That means adding an entry to
`_PUBLIC_PREFIXES` in `tests/test_route_auth_guard.py` - deliberately punching a hole in
the sweep that asserts every route 401s unauthenticated - to save a copy-paste for a
handful of internal operators. The trade is not worth it.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import CurrentUser, require_staff
from app.services.activity import record_activity
from app.services.operator_tokens import (
    DEFAULT_TTL_SECONDS,
    EXTENSION_SCOPES,
    cap_scopes,
    list_operator_tokens,
    mint_operator_token,
    revoke_operator_token,
)

router = APIRouter(prefix="/extension", tags=["extension"])

Staff = Annotated[CurrentUser, Depends(require_staff())]


class ExtensionTokenRequest(BaseModel):
    """Pair a device. Scopes default to the queue only - revealing a directory
    credential is a different act and has to be asked for explicitly."""

    device_label: str = Field(default="", alias="deviceLabel", max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["citation_queue"])
    # NO ttl FIELD, DELIBERATELY. It used to be `ge=60, le=MAX_TTL_SECONDS`, which let any
    # operator self-mint a SEVEN-DAY token on a self-service endpoint - while the
    # extension README states "expires in twelve hours" as a fact and says in bold not to
    # lengthen the TTL for convenience. A policy that every holder can opt out of is not a
    # policy, and convenience is the only reason anyone would have set this field. The
    # lifetime is now DEFAULT_TTL_SECONDS for everyone, and changing it takes a deploy -
    # which is what the README's warning already assumed was true.
    model_config = ConfigDict(populate_by_name=True)


class ExtensionTokenMinted(BaseModel):
    """The one and only time the raw token exists outside the operator's clipboard."""

    id: str
    token: str
    scopes: list[str]
    expires_at: str = Field(serialization_alias="expiresAt")
    device_label: str = Field(serialization_alias="deviceLabel")
    # Said in the response, not only in the docs: the operator sees this at the exact
    # moment it matters.
    warning: str = (
        "Copy this now - it is never shown again. It expires on its own, and it can only "
        "reach the citation queue."
    )


class ExtensionTokenRow(BaseModel):
    """Masked metadata. The hash never leaves the database."""

    id: str
    prefix: str
    scopes: list[str]
    device_label: str = Field(serialization_alias="deviceLabel")
    expires_at: str = Field(serialization_alias="expiresAt")
    revoked: bool
    last_used_at: str | None = Field(default=None, serialization_alias="lastUsedAt")


def _iso(value: Any) -> str:
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value or "")


@router.post("/tokens", response_model=ExtensionTokenMinted, status_code=status.HTTP_201_CREATED)
async def mint_extension_token(body: ExtensionTokenRequest, actor: Staff) -> ExtensionTokenMinted:
    """Pair a browser extension to YOUR OWN account.

    Self-service on purpose: an operator whose 12-hour token expires mid-shift must be
    able to pair again without waiting for an owner. It cannot be minted for anybody
    else - `user_id` is the caller, never a field in the request - so this endpoint
    cannot be used to hand someone a credential in another person's name."""
    capped = cap_scopes(body.scopes)
    if not capped:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Scopes must be a subset of {sorted(EXTENSION_SCOPES)}.",
        )
    row, raw = await asyncio.to_thread(
        mint_operator_token,
        user_id=actor.id,
        actor_id=actor.id,
        scopes=capped,
        device_label=body.device_label,
        ttl_seconds=DEFAULT_TTL_SECONDS,
    )
    await record_activity(
        actor, kind="access", action="paired a citation extension",
        target=body.device_label or "unnamed device",
        meta=f"scopes={','.join(capped)}",
    )
    return ExtensionTokenMinted(
        id=str(row["id"]),
        token=raw,
        scopes=capped,
        expires_at=_iso(row.get("expires_at")),
        device_label=str(row.get("device_label") or ""),
    )


@router.get("/tokens", response_model=list[ExtensionTokenRow])
async def list_extension_tokens(actor: Staff) -> list[ExtensionTokenRow]:
    """Your paired devices - or everyone's, if you are an owner or admin. RLS decides."""
    rows = await asyncio.to_thread(list_operator_tokens, actor_id=actor.id)
    return [
        ExtensionTokenRow(
            id=str(r["id"]),
            prefix=str(r["token_prefix"]),
            scopes=[str(s) for s in (r.get("scopes") or [])],
            device_label=str(r.get("device_label") or ""),
            expires_at=_iso(r.get("expires_at")),
            revoked=bool(r.get("revoked")),
            last_used_at=_iso(r["last_used_at"]) if r.get("last_used_at") else None,
        )
        for r in rows
    ]


@router.post("/tokens/{token_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_extension_token(token_id: str, actor: Staff) -> None:
    """Revoke a paired device. RLS decides who may: its owner, or an owner/admin."""
    ok = await asyncio.to_thread(revoke_operator_token, actor_id=actor.id, token_id=token_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Token not found, or already revoked."
        )
    await record_activity(
        actor, kind="access", action="revoked a citation extension token", target=token_id,
    )
