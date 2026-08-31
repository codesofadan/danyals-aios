"""Clients + sites CRUD. Reads require any provisioned staff; writes require
``manage_clients`` (owner/admin/manager). Responses match the frontend shapes.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, require_perm, require_staff
from app.core.deps import RedisDep, SettingsDep
from app.core.pagination import PageDep
from app.db.clients_repo import ClientsRepo, ClientsRepoDep
from app.db.database import DatabaseNotConfiguredError
from app.db.deliverables_repo import DeliverablesRepoDep
from app.db.report_grants_repo import ReportGrantsRepoDep
from app.logging_setup import get_logger
from app.modules.client_onboarding.service import seed_onboarding_for_client
from app.schemas.clients import (
    ClientCreate,
    ClientResponse,
    ClientUpdate,
    ReportGrantsUpdate,
    SiteCreate,
    SiteResponse,
    StaffDeliverableResponse,
)
from app.schemas.clients_business import (
    ClientBusinessProfileInput,
    ClientBusinessProfileResponse,
)
from app.schemas.identity import (
    MemberCredentials,
    MemberResponse,
    PortalUserRequest,
    SetPasswordRequest,
)
from app.services.activity import record_activity
from app.services.credentials import generate_password
from app.services.login_credentials import reveal_password, set_password
from app.services.notifications import notify
from app.services.provisioning import provision_user
from app.services.token_denylist import revoke_all_for_user

router = APIRouter(tags=["clients"])
logger = get_logger("app.clients")

ManageClients = Annotated[CurrentUser, Depends(require_perm("manage_clients"))]
# The five client READS below carried CurrentUserDep alone. The outcome was already
# correct - `clients_select` is `using (is_staff())`, so a portal client got zero rows
# or a 404 - but the app tier granted nothing of its own, leaving one RLS policy as the
# only thing between a client and the agency's book of business. Every sibling WRITE
# already required a permission. Same completion as the /rbac/* and /cost/* sweep.
Staff = Annotated[CurrentUser, Depends(require_staff())]

_CLIENT_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
_DELIVERABLE_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Deliverable not found"
)


@router.get("/clients", response_model=list[ClientResponse])
async def list_clients(
    repo: ClientsRepoDep, page: PageDep, _user: Staff
) -> list[ClientResponse]:
    rows = await asyncio.to_thread(repo.list_clients, limit=page.limit, offset=page.offset)
    counts = await asyncio.to_thread(repo.site_counts)
    return [ClientResponse.from_row(r, site_count=counts.get(str(r["id"]), 0)) for r in rows]


@router.post("/clients", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(body: ClientCreate, repo: ClientsRepoDep, actor: ManageClients) -> ClientResponse:
    """Create a client and immediately give it an onboarding run.

    The onboarding seed is BEST-EFFORT and never raises (it is written to that
    contract, like ``record_activity``): a new client must not be able to exist
    without an activation checklist - that is how onboarding gets forgotten and how a
    client goes missing from the onboarding KPI - but a seeding hiccup must never
    fail, or roll back, a client creation that has otherwise succeeded.
    """
    row = await asyncio.to_thread(repo.insert_client, body.to_row())
    client_id = str(row["id"])
    await record_activity(
        actor, kind="client", action="created client", target=body.cn,
        entity_type="client", entity_id=client_id,
    )
    # Persist the client's own NAP when the wizard collected one. BEST-EFFORT (same
    # contract as the onboarding seed below): a NAP hiccup must never fail, or roll
    # back, a client creation that already succeeded - the operator can still add it
    # from the Edit modal. Only written when the operator actually entered something.
    if body.business is not None and body.business.has_content():
        try:
            await asyncio.to_thread(
                repo.upsert_business_profile,
                client_id=client_id, client_name=body.cn, fields=body.business.to_row(),
            )
        except Exception:
            logger.warning("client_business_profile_seed_failed", client_id=client_id)
    await asyncio.to_thread(
        seed_onboarding_for_client, actor.id, client_id, body.cn, actor.id, actor.name
    )
    return ClientResponse.from_row(row, site_count=0)


@router.get("/clients/report-grants", response_model=dict[str, list[str]])
async def get_all_report_grants(
    grants: ReportGrantsRepoDep, _user: Staff
) -> dict[str, list[str]]:
    """Every client's report-grant keys at once ({client_id: keys[]}). The admin
    directory needs the whole table; per-client GETs made that an N+1. Declared
    BEFORE /clients/{client_id} so "report-grants" never binds as an id."""
    return await asyncio.to_thread(grants.list_all_keys)


@router.get("/clients/{client_id}", response_model=ClientResponse)
async def get_client(client_id: str, repo: ClientsRepoDep, _user: Staff) -> ClientResponse:
    row = await asyncio.to_thread(repo.get_client, client_id)
    if row is None:
        raise _CLIENT_NOT_FOUND
    count = await asyncio.to_thread(repo.site_counts)
    return ClientResponse.from_row(row, site_count=count.get(client_id, 0))


@router.get("/clients/{client_id}/business-profile", response_model=ClientBusinessProfileResponse)
async def get_client_business_profile(
    client_id: str, repo: ClientsRepoDep, _user: Staff
) -> ClientBusinessProfileResponse:
    """The client's stored NAP (name/address/phone/categories/hours). 404s if the
    client is unknown/invisible OR if no NAP was ever captured for it (the caller then
    knows to collect one before running a citation campaign). RLS-scoped."""
    client = await asyncio.to_thread(repo.get_client, client_id)
    if client is None:
        raise _CLIENT_NOT_FOUND
    row = await asyncio.to_thread(repo.get_business_profile, client_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No business profile for this client"
        )
    return ClientBusinessProfileResponse.from_row(row)


@router.put("/clients/{client_id}/business-profile", response_model=ClientBusinessProfileResponse)
async def put_client_business_profile(
    client_id: str, body: ClientBusinessProfileInput, repo: ClientsRepoDep, actor: ManageClients
) -> ClientBusinessProfileResponse:
    """Create or replace a client's NAP (lead-only, upsert - one record per client).
    Backs the Edit modal's business-profile fields. 404s if the client is unknown."""
    client = await asyncio.to_thread(repo.get_client, client_id)
    if client is None:
        raise _CLIENT_NOT_FOUND
    row = await asyncio.to_thread(
        repo.upsert_business_profile,
        client_id=client_id, client_name=client.get("name", ""), fields=body.to_row(),
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Could not save the business profile"
        )
    await record_activity(
        actor, kind="client", action="updated business profile", target=client.get("name", client_id),
        entity_type="client", entity_id=client_id,
    )
    return ClientBusinessProfileResponse.from_row(row)


@router.patch("/clients/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: str, body: ClientUpdate, repo: ClientsRepoDep, actor: ManageClients
) -> ClientResponse:
    changes = body.to_row()
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    row = await asyncio.to_thread(repo.update_client, client_id, changes)
    if row is None:
        raise _CLIENT_NOT_FOUND
    await record_activity(
        actor, kind="client", action="updated client", target=row.get("name", client_id),
        entity_type="client", entity_id=client_id,
    )
    counts = await asyncio.to_thread(repo.site_counts)
    return ClientResponse.from_row(row, site_count=counts.get(client_id, 0))


@router.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(client_id: str, repo: ClientsRepoDep, actor: ManageClients) -> None:
    deleted = await asyncio.to_thread(repo.delete_client, client_id)
    if not deleted:
        raise _CLIENT_NOT_FOUND
    await record_activity(
        actor, kind="client", action="deleted client", target=client_id,
        entity_type="client", entity_id=client_id,
    )


@router.get(
    "/clients/{client_id}/deliverables", response_model=list[StaffDeliverableResponse]
)
async def list_client_deliverables(
    client_id: str,
    repo: ClientsRepoDep,
    deliverables: DeliverablesRepoDep,
    _user: Staff,
) -> list[StaffDeliverableResponse]:
    """Every document produced for this client, INCLUDING the ones awaiting review.

    The portal's own list is a different surface with a different filter: it shows
    what the client may see. This is the staff view of the same table, which is where
    the approval decision is taken.
    """
    client = await asyncio.to_thread(repo.get_client, client_id)
    if client is None:
        raise _CLIENT_NOT_FOUND
    rows = await asyncio.to_thread(deliverables.list_for_client, client_id)
    return [StaffDeliverableResponse.from_row(r) for r in rows]


@router.post(
    "/deliverables/{deliverable_id}/publish", response_model=StaffDeliverableResponse
)
async def publish_deliverable(
    deliverable_id: str, deliverables: DeliverablesRepoDep, actor: ManageClients
) -> StaffDeliverableResponse:
    """Release a document to the client's portal.

    Producers write documents as `pending_review`, so this is the act that puts one in
    front of a client - the same decision for an audit PDF, a scheduled monthly report
    and a client-requested one. Lead-only, like every other outward-facing act
    (sharing an audit, editing report grants).

    A document with no stored artifact is REFUSED. The portal renders View and
    Download for a ready row and the download endpoint resolves an artifact key; with
    no key those buttons 404, so releasing one would hand a paying client a file that
    does not exist.
    """
    row = await asyncio.to_thread(deliverables.get, deliverable_id)
    if row is None:
        raise _DELIVERABLE_NOT_FOUND
    if not row.get("artifact_key"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This deliverable has no stored file, so publishing it would show the "
                "client a download that cannot work. Re-run the job that produces it."
            ),
        )
    updated = await asyncio.to_thread(deliverables.set_status, deliverable_id, status="ready")
    if updated is None:
        raise _DELIVERABLE_NOT_FOUND
    await record_activity(
        actor, kind="access", action="published a report to the client portal",
        target=str(updated.get("title") or deliverable_id),
        entity_type="client",
        entity_id=str(updated["client_id"]) if updated.get("client_id") else None,
    )
    return StaffDeliverableResponse.from_row(updated)


@router.post(
    "/deliverables/{deliverable_id}/unpublish", response_model=StaffDeliverableResponse
)
async def unpublish_deliverable(
    deliverable_id: str, deliverables: DeliverablesRepoDep, actor: ManageClients
) -> StaffDeliverableResponse:
    """Pull a document back out of the client's portal, into review.

    The counterpart to publish, and the reason the approval state is worth having: a
    document released by mistake could previously only be hidden by revoking the whole
    report grant, which removes every other document of that kind at the same time.
    """
    updated = await asyncio.to_thread(
        deliverables.set_status, deliverable_id, status="pending_review"
    )
    if updated is None:
        raise _DELIVERABLE_NOT_FOUND
    await record_activity(
        actor, kind="access", action="withdrew a report from the client portal",
        target=str(updated.get("title") or deliverable_id),
        entity_type="client",
        entity_id=str(updated["client_id"]) if updated.get("client_id") else None,
    )
    return StaffDeliverableResponse.from_row(updated)


@router.get("/clients/{client_id}/report-grants", response_model=list[str])
async def get_report_grants(
    client_id: str, repo: ClientsRepoDep, grants: ReportGrantsRepoDep, _user: Staff
) -> list[str]:
    """The report keys a client is granted to see in its portal (sorted)."""
    client = await asyncio.to_thread(repo.get_client, client_id)
    if client is None:
        raise _CLIENT_NOT_FOUND
    return await asyncio.to_thread(grants.list_keys, client_id)


@router.put("/clients/{client_id}/report-grants", response_model=list[str])
async def put_report_grants(
    client_id: str,
    body: ReportGrantsUpdate,
    repo: ClientsRepoDep,
    grants: ReportGrantsRepoDep,
    actor: ManageClients,
) -> list[str]:
    """Replace a client's report-access set (the full grant list). Lead-only; the
    replace runs atomically. Records an ``access`` activity entry."""
    client = await asyncio.to_thread(repo.get_client, client_id)
    if client is None:
        raise _CLIENT_NOT_FOUND
    keys = await asyncio.to_thread(grants.replace_keys, client_id, body.reports)
    await record_activity(
        actor, kind="access", action="updated report access",
        target=client.get("name", client_id),
        entity_type="client", entity_id=client_id,
    )
    return keys


@router.get("/clients/{client_id}/sites", response_model=list[SiteResponse])
async def list_sites(
    client_id: str, repo: ClientsRepoDep, page: PageDep, _user: Staff
) -> list[SiteResponse]:
    rows = await asyncio.to_thread(repo.list_sites, client_id, limit=page.limit, offset=page.offset)
    return [SiteResponse.from_row(r) for r in rows]


@router.post(
    "/clients/{client_id}/sites", response_model=SiteResponse, status_code=status.HTTP_201_CREATED
)
async def create_site(
    client_id: str, body: SiteCreate, repo: ClientsRepoDep, actor: ManageClients
) -> SiteResponse:
    row = await asyncio.to_thread(
        repo.insert_site, {"client_id": client_id, "domain": body.domain, "cms_type": body.cms_type}
    )
    await record_activity(
        actor, kind="client", action="added a site", target=body.domain,
        entity_type="site", entity_id=str(row["id"]),
    )
    return SiteResponse.from_row(row)


@router.post(
    "/clients/{client_id}/portal-users",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_portal_user(
    client_id: str, body: PortalUserRequest, repo: ClientsRepoDep, actor: ManageClients
) -> MemberResponse:
    """Provision a client PORTAL login scoped to ``client_id`` (lead-only).

    Guarded by ``manage_clients`` — the SAME gate as creating the client itself,
    so the Add-Client wizard's final step (this call) can never silently 403 for
    an admin/manager who was just allowed to create the client. Not an
    escalation: the role is fixed to ``client`` and the tenant is pinned from
    the path, so this endpoint can neither mint a staff account nor point a
    login at another client's data. Provisioning uses the service_role admin
    client (server-only).
    """
    client = await asyncio.to_thread(repo.get_client, client_id)
    if client is None:
        raise _CLIENT_NOT_FOUND
    try:
        row = await asyncio.to_thread(
            provision_user,
            email=str(body.email),
            password=body.password.get_secret_value(),
            name=body.name,
            role="client",
            username=body.username,
            client_id=client_id,
        )
    except DatabaseNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured"
        ) from exc
    except Exception as exc:
        # Duplicate email / auth rejection / write failure. Log server-side (no
        # secret in the payload) and return a generic client error, never a 500.
        logger.warning(
            "provision_portal_user_failed", actor=actor.id, error_type=type(exc).__name__
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create portal login (email may already exist)",
        ) from exc
    await record_activity(
        actor,
        kind="client",
        action="provisioned a portal login",
        target=body.name,
        meta=client.get("name", client_id),
        # A portal login is a change to THIS client's world (its team gained a
        # login), so track the client entity, not the freshly-minted user.
        entity_type="client",
        entity_id=client_id,
    )
    # Email the client their brand-new portal credentials (best-effort). This is
    # the "send invitation email" path - the admin still sees the pair once to copy
    # manually. `row["id"]` is the freshly provisioned client user, so notify()
    # resolves the address directly.
    await notify(
        str(row["id"]),
        kind="portal_ready",
        title=f"Your {client.get('name', 'client')} portal is ready",
        body=(
            f"Hi {body.name}, your client portal has been set up. Sign in to track "
            "your SEO progress, reports and deliverables.\n\n"
            f"Username: {body.username or str(body.email)}\n"
            f"Password: {body.password.get_secret_value()}\n\n"
            "We recommend changing your password after your first sign-in."
        ),
    )
    return MemberResponse.from_row(row)


# --------------------------------------------------------------------------- #
# Portal login credentials (the Client Directory's "Show login")
# --------------------------------------------------------------------------- #
# These mirror the team tool (`GET|POST /admin/users/{id}/credentials|password`)
# but are gated on `manage_clients`, NOT `manage_team`. That is the whole reason
# they exist rather than the directory calling the team routes: a MANAGER holds
# manage_clients and not manage_team, so a manager who may create a client - and
# who is shown its password once at creation - could never see it again. The same
# trap `create_portal_user` above already documents for provisioning.
#
# Widening the gate is not an escalation, because every route here re-reads the
# target through `_portal_user_of` and refuses any account that is not a
# `role='client'` login belonging to THIS client. A caller cannot walk an
# arbitrary user id through the client surface to reach a staff account.


async def _portal_user_of(repo: ClientsRepo, client_id: str, user_id: str) -> dict[str, Any]:
    """The client's portal login row, or 404. Pins the tenant AND the role."""
    rows = await asyncio.to_thread(repo.list_portal_users, client_id)
    for row in rows:
        if str(row["id"]) == str(user_id):
            return row
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="No such portal login for this client"
    )


@router.get("/clients/{client_id}/portal-credentials", response_model=list[MemberCredentials])
async def get_portal_credentials(
    client_id: str, repo: ClientsRepoDep, actor: ManageClients
) -> list[MemberCredentials]:
    """Reveal every portal login this client can sign in with (lead-only).

    Fetched on demand - one click per client, never for the whole directory - so
    plaintext passwords are not sitting in a list response nobody asked for.

    A ``password`` of ``None`` (``available=False``) is the honest answer for a
    login provisioned before the sealed copy existed, or with no ``VAULT_MASTER_KEY``
    set at the time. The caller renders "not captured" and offers a reset; it must
    never render a blank as though the password were empty.
    """
    client = await asyncio.to_thread(repo.get_client, client_id)
    if client is None:
        raise _CLIENT_NOT_FOUND
    rows = await asyncio.to_thread(repo.list_portal_users, client_id)
    out: list[MemberCredentials] = []
    for row in rows:
        password = await asyncio.to_thread(reveal_password, str(row["id"]))
        out.append(
            MemberCredentials(
                id=str(row["id"]),
                username=row.get("username"),
                email=str(row.get("email") or ""),
                password=password,
                available=password is not None,
            )
        )
    # One activity row for the reveal, not one per login: the operator performed a
    # single act. Recorded even when nothing was captured - the ATTEMPT is the event.
    await record_activity(
        actor, kind="access", action="revealed portal credentials",
        target=str(client.get("name") or client_id),
        entity_type="client", entity_id=client_id,
    )
    return out


@router.post(
    "/clients/{client_id}/portal-users/{user_id}/password", response_model=MemberCredentials
)
async def set_portal_password(
    client_id: str,
    user_id: str,
    body: SetPasswordRequest,
    repo: ClientsRepoDep,
    actor: ManageClients,
    redis: RedisDep,
    settings: SettingsDep,
) -> MemberCredentials:
    """Set/rotate a client portal password and return it once (lead-only).

    With no ``password`` in the body the server generates a strong one. This is the
    repair path for a login whose password was never captured, and the reason the
    reveal above can answer "not captured" without stranding the operator.

    Rotating ENDS the sessions the old password opened, for the same reason the team
    route does: a bearer token never consults the password again, so without this a
    rotation would change nothing for days.
    """
    client = await asyncio.to_thread(repo.get_client, client_id)
    if client is None:
        raise _CLIENT_NOT_FOUND
    target = await _portal_user_of(repo, client_id, user_id)

    new_password = (
        body.password.get_secret_value() if body.password is not None else generate_password()
    )
    ok = await asyncio.to_thread(set_password, user_id, new_password)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No such portal login for this client"
        )

    # Best-effort by design: the password has ALREADY changed in Postgres, so failing
    # the request here would tell the operator a rotation did not happen when it did.
    if not await revoke_all_for_user(
        redis, user_id=user_id, max_token_ttl=settings.jwt_access_ttl_seconds
    ):
        logger.warning(
            "portal_password_rotation_token_revocation_unavailable",
            target=user_id,
            actor=actor.id,
        )

    await record_activity(
        actor, kind="access", action="reset a portal password",
        target=str(target.get("name") or target.get("username") or ""),
        meta=str(client.get("name") or client_id),
        entity_type="client", entity_id=client_id,
    )
    return MemberCredentials(
        id=str(target["id"]),
        username=target.get("username"),
        email=str(target.get("email") or ""),
        password=new_password,
        available=True,
    )


@router.delete("/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(site_id: str, repo: ClientsRepoDep, actor: ManageClients) -> None:
    deleted = await asyncio.to_thread(repo.delete_site, site_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    await record_activity(
        actor, kind="client", action="deleted a site", target=site_id,
        entity_type="site", entity_id=site_id,
    )
