"""Pairing the citation extension: mint, list, revoke and ROTATE a device credential.

The raw token is shown EXACTLY ONCE, at mint, and never again - only its sha256 is
stored. That is the model 0030 already committed this codebase to for skill tokens, and
reusing it means pairing introduces no new concepts and no new unauthenticated surface.

WHY COPY-PASTE AND NOT A DEVICE FLOW. A device/OAuth-style flow needs an unauthenticated
`pair/start` endpoint plus an unauthenticated poll. That means adding an entry to
`_PUBLIC_PREFIXES` in `tests/test_route_auth_guard.py` - deliberately punching a hole in
the sweep that asserts every route 401s unauthenticated - to save a copy-paste for a
handful of internal operators. The trade is not worth it.

ROTATION (0131) is what makes the 12-hour lifetime livable: the extension exchanges its
live token for a successor before it expires, chained under a 30-day installation
identity, so the copy-paste happens once a month rather than once a shift. The rotate
endpoint is authenticated by the operator token ITSELF - no bearer fallback, no scope
requirement - and any failure is a plain 401, which is exactly the signal the extension
turns into its re-pair state. Replaying an already-rotated token revokes the whole
install (see `app/services/operator_tokens.py`).
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings, get_settings
from app.core.auth import CurrentUser, require_staff
from app.core.deps import RedisDep
from app.core.ratelimit import _enforce, rate_limit
from app.modules.citations.operator_auth import RotationGrantDep
from app.services.activity import record_activity
from app.services.operator_tokens import (
    DEFAULT_MINT_SCOPES,
    DEFAULT_TTL_SECONDS,
    EXTENSION_SCOPES,
    cap_scopes,
    list_operator_tokens,
    mint_operator_token,
    revoke_operator_token,
    rotate_operator_token,
)

router = APIRouter(prefix="/extension", tags=["extension"])

Staff = Annotated[CurrentUser, Depends(require_staff())]

# Fail-OPEN like the audit-create limits: the caller is already authenticated and
# bounded, so the limiter is a brake on runaway loops, never the reason a legitimate
# request 500s during a cache blip. Mint is a human copy-paste; rotate fires roughly
# twice a shift per device - both limits are far above honest use.
_MINT_LIMIT = Depends(rate_limit("extension_token_mint", limit=10, per_seconds=60))
_ROTATE_LIMIT_PER_MINUTE = 6


async def _rotate_rate_limit(redis: RedisDep, user_id: str) -> None:
    """Per-user fixed window for rotation, keyed exactly like `rate_limit` would key it.

    Wired by hand because `rate_limit()`'s dependency resolves `get_current_user`
    (bearer), and the rotation caller deliberately has no bearer identity - only the
    operator principal this router already resolved."""
    window = int(time.time()) // 60
    await _enforce(
        redis,
        f"rl:extension_token_rotate:{user_id}:{window}",
        "extension_token_rotate",
        _ROTATE_LIMIT_PER_MINUTE,
        60,
        fail_closed=False,
    )


class ExtensionTokenRequest(BaseModel):
    """Pair a device. Scopes default to the granular citation-queue working set -
    revealing a directory credential (or touching the web2 queue) is a different act
    and has to be asked for explicitly."""

    device_label: str = Field(default="", alias="deviceLabel", max_length=120)
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_MINT_SCOPES))
    # Re-pairing an EXISTING device mid-window: the panel sends its installId back so
    # the new token chains under the same 30-day identity instead of minting a fresh
    # install per paste. Omitted (the normal case) = a new install.
    install_id: str | None = Field(default=None, alias="installId", max_length=64)
    # NO ttl FIELD, DELIBERATELY. It used to be `ge=60, le=MAX_TTL_SECONDS`, which let any
    # operator self-mint a SEVEN-DAY token on a self-service endpoint - while the
    # extension README states "expires in twelve hours" as a fact and says in bold not to
    # lengthen the TTL for convenience. A policy that every holder can opt out of is not a
    # policy, and convenience is the only reason anyone would have set this field. The
    # lifetime is now DEFAULT_TTL_SECONDS for everyone, and changing it takes a deploy -
    # which is what the README's warning already assumed was true.
    model_config = ConfigDict(populate_by_name=True)


class ExtensionTokenMinted(BaseModel):
    """The one and only time the raw token exists outside the operator's clipboard.

    Also the ROTATION response shape: a successor token is a mint by other means, and
    two shapes for one secret would mean two client paths to keep right."""

    id: str
    token: str
    scopes: list[str]
    expires_at: str = Field(serialization_alias="expiresAt")
    device_label: str = Field(serialization_alias="deviceLabel")
    # The 30-day installation this token chains under, and when that pairing runs out -
    # the extension stores both so it can say "re-pair by <date>" instead of failing.
    install_id: str = Field(serialization_alias="installId")
    pairing_expires_at: str = Field(serialization_alias="pairingExpiresAt")
    # The address the extension must be paired against, stated BY THE SERVER. The
    # 2026-09-01 pairing outage was partly an operator pointing the extension at a stale
    # backend on another port — a token and the address it works against now travel
    # together, so the instructions can never name a different server than the one that
    # minted the credential.
    api_base: str = Field(serialization_alias="apiBase")
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
    # Install identity (0131). Null on a legacy token minted before installs existed.
    install_id: str | None = Field(default=None, serialization_alias="installId")
    pairing_expires_at: str | None = Field(default=None, serialization_alias="pairingExpiresAt")


def _iso(value: Any) -> str:
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value or "")


def _pair_api_base(settings: Settings, request: Request) -> str:
    """The address the extension should call, stated by the server itself.

    Configured (`EXTENSION_PAIR_API_BASE`) wins; otherwise it is derived from the
    request's own scheme+host — the dashboard reaches this API through a same-origin
    rewrite whose upstream IS the live backend, so the Host the API sees here is the
    address that works. Never guessed client-side."""
    configured = settings.extension_pair_api_base.strip().rstrip("/")
    if configured:
        return configured
    return f"{request.url.scheme}://{request.url.netloc}"


class PairingInfo(BaseModel):
    """What Settings → Extension renders beside the pairing instructions."""

    api_base: str = Field(serialization_alias="apiBase")
    # The chrome-extension:// origins the API's CORS layer currently allows. Empty is
    # normal in dev (loopback host permissions cover it); the settings screen uses this
    # to show whether a pasted extension id is already allow-listed.
    allowed_extension_origins: list[str] = Field(serialization_alias="allowedExtensionOrigins")


@router.get("/pairing-info", response_model=PairingInfo)
async def pairing_info(request: Request, actor: Staff) -> PairingInfo:
    """The facts an operator needs BEFORE minting: where to point the extension, and
    which extension identities the server already trusts for CORS."""
    settings = get_settings()
    return PairingInfo(
        api_base=_pair_api_base(settings, request),
        allowed_extension_origins=settings.extension_origins_list,
    )


def _minted_response(row: dict[str, Any], raw: str, scopes: list[str], api_base: str) -> ExtensionTokenMinted:
    return ExtensionTokenMinted(
        id=str(row["id"]),
        token=raw,
        scopes=scopes,
        expires_at=_iso(row.get("expires_at")),
        device_label=str(row.get("device_label") or ""),
        install_id=str(row.get("install_id") or ""),
        pairing_expires_at=_iso(row.get("pairing_expires_at")),
        api_base=api_base,
    )


@router.post(
    "/tokens",
    response_model=ExtensionTokenMinted,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MINT_LIMIT],
)
async def mint_extension_token(
    body: ExtensionTokenRequest, request: Request, actor: Staff
) -> ExtensionTokenMinted:
    """Pair a browser extension to YOUR OWN account.

    Self-service on purpose: an operator whose pairing window lapses must be able to
    pair again without waiting for an owner. It cannot be minted for anybody else -
    `user_id` is the caller, never a field in the request - so this endpoint cannot be
    used to hand someone a credential in another person's name. An `installId` the
    caller owns re-pairs that device; anything else is refused."""
    capped = cap_scopes(body.scopes)
    if not capped:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Scopes must be a subset of {sorted(EXTENSION_SCOPES)}.",
        )
    try:
        row, raw = await asyncio.to_thread(
            mint_operator_token,
            user_id=actor.id,
            actor_id=actor.id,
            scopes=capped,
            device_label=body.device_label,
            ttl_seconds=DEFAULT_TTL_SECONDS,
            install_id=body.install_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    await record_activity(
        actor, kind="access", action="paired a citation extension",
        target=body.device_label or "unnamed device",
        meta=f"scopes={','.join(capped)}",
    )
    return _minted_response(row, raw, capped, _pair_api_base(get_settings(), request))


@router.post("/tokens/rotate", response_model=ExtensionTokenMinted)
async def rotate_extension_token(
    request: Request, redis: RedisDep, grant: RotationGrantDep
) -> ExtensionTokenMinted:
    """Exchange a live operator token for its 12-hour successor.

    Authenticated ONLY by `X-Operator-Token` - the extension's own credential, resolved
    by a dependency that runs the full verification (including the fail-closed epoch
    check) but no scope check: rotation is how a token stays alive, not a capability it
    holds. EVERY failure is a 401 so the panel shows the re-pair state rather than a
    riddle. The service refuses a revoked or pairing-expired install, and treats a
    replayed (already-rotated) token as theft: the whole install chain is revoked."""
    await _rotate_rate_limit(redis, grant.principal.user_id)
    result = await asyncio.to_thread(rotate_operator_token, grant.raw_token)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    row, raw = result
    return _minted_response(
        row, raw, [str(s) for s in (row.get("scopes") or [])],
        _pair_api_base(get_settings(), request),
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
            install_id=str(r["install_id"]) if r.get("install_id") else None,
            pairing_expires_at=(
                _iso(r["pairing_expires_at"]) if r.get("pairing_expires_at") else None
            ),
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
