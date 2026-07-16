"""Skills-gateway endpoints (Part 9 / P9-1).

Two audiences, two auth models:

* OWNER/ADMIN management (``require_role("admin")`` - owner auto-passes): mint a
  per-client skill token (raw shown ONCE), list them masked, revoke one.
* The MCP GATEWAY (``POST /skills/verify``): authenticates a presented skill token
  and returns the resolved :class:`ScopedPrincipal`. It carries NO user identity -
  the token itself is the credential (presented in the ``X-Skill-Token`` header) -
  so an absent/invalid/expired token 401s (this route is therefore still protected;
  see ``tests/test_route_auth_guard.py``). The response is the capped scope only,
  NEVER the secret and NEVER the hash.

Every management mutation is recorded on the append-only activity log. Nothing here
ever logs or echoes a raw secret except the single mint response.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.core.auth import CurrentUser, require_role
from app.db.database import DatabaseNotConfiguredError
from app.schemas.skills import (
    SkillPrincipalResponse,
    SkillTokenCreate,
    SkillTokenMinted,
    SkillTokenResponse,
    SkillTokenRevokeResponse,
)
from app.services.activity import record_activity
from app.services.skill_tokens import (
    ScopedPrincipal,
    list_skill_tokens,
    mint_skill_token,
    revoke_skill_token,
    verify_skill_token,
)

router = APIRouter(prefix="/skills", tags=["skills"])

# Owner or admin only (owner auto-passes require_role); they hold access_control /
# manage_team and are the only principals who may issue a standing credential.
ManageSkills = Annotated[CurrentUser, Depends(require_role("admin"))]

_TOKEN_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill token not found")
_SKILLS_UNCONFIGURED = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Skills gateway is not configured"
)
_UNAUTHORIZED_SKILL = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Missing, invalid, or expired skill token",
    headers={"WWW-Authenticate": "SkillToken"},
)


async def resolve_skill_principal(
    x_skill_token: Annotated[str | None, Header(alias="X-Skill-Token")] = None,
) -> ScopedPrincipal:
    """Authenticate the ``X-Skill-Token`` header -> a :class:`ScopedPrincipal` (else 401).

    A missing header 401s (so an unauthenticated call to ``/skills/verify`` is
    rejected before the handler, satisfying the route-auth guard); an
    invalid/expired/revoked/unknown token also 401s. The token is the ONLY input -
    the resolved principal is capped to its tenant + scopes.
    """
    if not x_skill_token:
        raise _UNAUTHORIZED_SKILL
    try:
        principal = await asyncio.to_thread(verify_skill_token, x_skill_token)
    except DatabaseNotConfiguredError as exc:
        raise _SKILLS_UNCONFIGURED from exc
    if principal is None:
        raise _UNAUTHORIZED_SKILL
    return principal


@router.post("/tokens", response_model=SkillTokenMinted, status_code=status.HTTP_201_CREATED)
async def mint_token(body: SkillTokenCreate, actor: ManageSkills) -> SkillTokenMinted:
    """Mint a scoped, per-client skill token. Returns the raw token EXACTLY ONCE."""
    try:
        row = await asyncio.to_thread(
            mint_skill_token,
            client_id=body.client_id,
            perms=body.perms,
            features=body.features,
            tier=body.tier,
            created_by=actor.id,
            ttl_seconds=body.ttl_seconds,
            label=body.label,
        )
    except DatabaseNotConfiguredError as exc:
        raise _SKILLS_UNCONFIGURED from exc
    raw = str(row.pop("token"))
    base = SkillTokenResponse.from_row(row)
    await record_activity(
        actor, kind="access", action="minted a skill token", target=base.token_prefix
    )
    return SkillTokenMinted(token=raw, **base.model_dump())


@router.get("/tokens", response_model=list[SkillTokenResponse])
async def list_tokens(
    _actor: ManageSkills, client_id: str | None = None
) -> list[SkillTokenResponse]:
    """Masked list of skill tokens (owner/admin) - never carries a secret or hash."""
    try:
        rows = await asyncio.to_thread(list_skill_tokens, _actor.id, client_id=client_id)
    except DatabaseNotConfiguredError as exc:
        raise _SKILLS_UNCONFIGURED from exc
    return [SkillTokenResponse.from_row(r) for r in rows]


@router.post("/tokens/{token_id}/revoke", response_model=SkillTokenRevokeResponse)
async def revoke_token(token_id: str, actor: ManageSkills) -> SkillTokenRevokeResponse:
    """Revoke a skill token (owner/admin). A revoked token fails every future verify."""
    try:
        revoked = await asyncio.to_thread(revoke_skill_token, actor.id, token_id)
    except DatabaseNotConfiguredError as exc:
        raise _SKILLS_UNCONFIGURED from exc
    if not revoked:
        raise _TOKEN_NOT_FOUND
    await record_activity(actor, kind="access", action="revoked a skill token", target=token_id)
    return SkillTokenRevokeResponse(id=token_id, revoked=True)


@router.post("/verify", response_model=SkillPrincipalResponse)
async def verify_token(
    principal: Annotated[ScopedPrincipal, Depends(resolve_skill_principal)],
) -> SkillPrincipalResponse:
    """Internal: the MCP gateway authenticates a token -> the scoped principal.

    Returns ONLY the capped scope (tenant + perms/features/tier). NEVER the secret,
    NEVER the hash. An invalid/absent token was already 401'd by the dependency.
    """
    return SkillPrincipalResponse(
        token_id=principal.token_id,
        client_id=principal.client_id,
        perms=sorted(principal.perms),
        features=sorted(principal.features),
        tier=principal.tier,
        expires_at=principal.expires_at,
    )
