"""User administration: the roster, provisioning, feature-grant editing.

There is no public signup. ``POST /admin/users`` (explicit password) and
``POST /admin/users/invite`` (server-generated one-time credentials) are the only
ways an account is created; both require ``manage_team`` and only an owner may
mint owner/admin accounts (privilege-escalation guard). ``GET``/``PUT
/admin/users/{id}/grants`` read and edit a user's per-feature access and require
``access_control`` (owner-only by the default matrix); an owner is all-on and
locked, so their grants can never be edited.

The roster (``GET /admin/users`` and ``GET /me``) is overlaid with real
performance metrics from :mod:`app.services.team_metrics` (7F-3).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import SUSPENDED_STATUS, CurrentUser, require_perm
from app.core.deps import RedisDep, SettingsDep
from app.core.pagination import PageDep
from app.db.database import (
    DatabaseNotConfiguredError,
    privileged_connection,
    rls_connection,
)
from app.logging_setup import get_logger
from app.rbac import FEATURE_KEYS, AccessLevel, effective_feature_level
from app.schemas.identity import (
    InviteMemberRequest,
    MemberCredentials,
    MemberInviteResponse,
    MemberResponse,
    ProvisionUserRequest,
    SetPasswordRequest,
    SuspendUserRequest,
    SuspensionResponse,
    UpdateGrantsRequest,
    UserGrantsResponse,
)
from app.services.activity import record_activity
from app.services.credentials import generate_password, generate_username
from app.services.login_credentials import reveal_password, set_password
from app.services.notifications import notify
from app.services.provisioning import provision_user
from app.services.team_metrics import ZERO_METRICS, TeamMetricsDep
from app.services.token_denylist import revoke_all_for_user

router = APIRouter(prefix="/admin/users", tags=["admin"])
logger = get_logger("app.admin_users")

_ELEVATED_ROLES = frozenset({"owner", "admin"})

ManageTeam = Annotated[CurrentUser, Depends(require_perm("manage_team"))]
# Editing feature access is the access_control permission (owner-only by default).
AccessControl = Annotated[CurrentUser, Depends(require_perm("access_control"))]

_DB_NOT_CONFIGURED = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured"
)
_USER_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


def _fetch_all_users(
    user_id: str, *, limit: int | None = None, offset: int = 0
) -> list[dict[str, Any]]:
    """Read the STAFF roster via the RLS-scoped ``rls_connection`` (staff sees all).

    Portal clients (role='client') are excluded in SQL (``role <> 'client'``):
    they are tenant logins, not agency team members, and must never appear in the
    Team screen. Blocking; the caller offloads with ``to_thread``.
    """
    query = "select * from public.users where role <> 'client' order by created_at"
    params: list[Any] = []
    if limit is not None:
        query += " limit %s offset %s"
        params += [limit, offset]
    with rls_connection(user_id) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def _load_user_min(caller_id: str, target_id: str) -> dict[str, Any] | None:
    """Load ``{id, role, status, name}`` for ``target_id`` via the RLS-scoped path."""
    with rls_connection(caller_id) as cur:
        cur.execute(
            "select id, role, status, name from public.users where id = %s limit 1", (target_id,)
        )
        return cur.fetchone()


def _count_active_owners() -> int:
    """How many owners can still sign in.

    Privileged read: RLS-scoped counting would be filtered by the caller's own
    visibility, and this is a SAFETY interlock - it must see the true count, not
    the caller's view of it.
    """
    with privileged_connection() as cur:
        cur.execute(
            "select count(*) as n from public.users "
            "where role = 'owner' and status <> %s",
            (SUSPENDED_STATUS,),
        )
        row = cur.fetchone()
        return int(row["n"]) if row else 0


def _set_suspension(
    *, target_id: str, actor_id: str, suspended: bool, reason: str
) -> dict[str, Any] | None:
    """Flip a user's access state and stamp the audit columns, atomically.

    Privileged, not RLS-scoped: `users_update` policy permits a staff member to
    edit a roster row, but access revocation is a SERVER decision that must not
    depend on the actor's own row visibility. Authorization for it is enforced in
    the endpoint (permission + escalation + interlocks) before we get here.

    One statement, so status and the audit stamp can never disagree - a row that
    says `suspended` with no `suspended_at` would make an incident timeline
    unreconstructable.
    """
    with privileged_connection() as cur:
        if suspended:
            cur.execute(
                """
                update public.users
                   set status = %s,
                       suspended_at = now(),
                       suspended_by = %s,
                       suspended_reason = %s
                 where id = %s
             returning id, name, role, status
                """,
                (SUSPENDED_STATUS, actor_id, reason, target_id),
            )
        else:
            # Reactivation returns the person to `active`, not to whatever
            # presence state they held before - "away" or "offline" would be a
            # stale claim about someone who has not signed in since.
            cur.execute(
                """
                update public.users
                   set status = 'active',
                       suspended_at = null,
                       suspended_by = null,
                       suspended_reason = ''
                 where id = %s
             returning id, name, role, status
                """,
                (target_id,),
            )
        return cur.fetchone()


def _load_cred_target(caller_id: str, target_id: str) -> dict[str, Any] | None:
    """Load ``{id, role, username, email, name}`` for the credential tool (RLS path)."""
    with rls_connection(caller_id) as cur:
        cur.execute(
            "select id, role, username, email, name from public.users where id = %s limit 1",
            (target_id,),
        )
        return cur.fetchone()


def _read_grant_overrides(caller_id: str, target_id: str) -> dict[str, AccessLevel]:
    """Read a user's stored per-feature overrides (RLS-scoped; staff may read any)."""
    with rls_connection(caller_id) as cur:
        cur.execute(
            "select feature_key, level from public.user_feature_grants where user_id = %s",
            (target_id,),
        )
        return {r["feature_key"]: r["level"] for r in cur.fetchall()}


def _write_grant_overrides(target_id: str, grants: Mapping[str, str]) -> None:
    """Upsert per-feature levels via the PRIVILEGED (service_role) connection.

    Editing another user's grants is a privileged system operation - the RLS
    ``user_feature_grants_modify`` policy is keyed to ``auth.uid()``'s app role,
    which the privileged pool does not set - so it runs on service_role like
    provisioning. The ``updated_at`` trigger stamps the change automatically.
    """
    with privileged_connection() as cur:
        cur.executemany(
            "insert into public.user_feature_grants (user_id, feature_key, level) "
            "values (%s, %s, %s) "
            "on conflict (user_id, feature_key) do update set level = excluded.level",
            [(target_id, key, level) for key, level in grants.items()],
        )


def _resolve_grants(role: str, overrides: dict[str, AccessLevel]) -> dict[str, AccessLevel]:
    """Effective level for all 17 features (owner = all full; else override or off)."""
    return {
        key: effective_feature_level(cast("Any", role), overrides, key) for key in FEATURE_KEYS
    }


async def _overlay_metrics(
    metrics: TeamMetricsDep, members: list[MemberResponse]
) -> list[MemberResponse]:
    """Overlay real performance metrics onto roster rows (best-effort).

    If the metrics aggregation is unavailable (e.g. the DB is not configured on
    this path) the roster still renders with zeroed metrics rather than failing.
    """
    if not members:
        return members
    try:
        scored = await asyncio.to_thread(metrics.member_metrics, [m.id for m in members])
    except DatabaseNotConfiguredError:
        logger.warning("roster_metrics_unavailable")
        return members
    out: list[MemberResponse] = []
    for m in members:
        s = scored.get(m.id, ZERO_METRICS)
        out.append(
            m.model_copy(
                update={
                    "active_tasks": s.active_tasks,
                    "completed": s.completed,
                    "on_time": s.on_time,
                    "utilization": s.utilization,
                    "quality": s.quality,
                }
            )
        )
    return out


@router.get("", response_model=list[MemberResponse])
async def list_users(
    page: PageDep,
    metrics: TeamMetricsDep,
    user: ManageTeam,
) -> list[MemberResponse]:
    """List the agency roster (frontend ``TeamMemberRecord`` shape) with live metrics."""
    try:
        rows = await asyncio.to_thread(
            _fetch_all_users, user.id, limit=page.limit, offset=page.offset
        )
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    members = [MemberResponse.from_row(r) for r in rows]
    return await _overlay_metrics(metrics, members)


@router.post("", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: ProvisionUserRequest,
    current: ManageTeam,
) -> MemberResponse:
    """Provision a local credential + identity row (owner-only for owner/admin)."""
    if body.role in _ELEVATED_ROLES and not current.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a super-admin can create owner/admin users",
        )
    try:
        row = await asyncio.to_thread(
            provision_user,
            email=str(body.email),
            password=body.password.get_secret_value(),
            name=body.name,
            role=body.role,
            username=body.username,
            title=body.title,
            avatar_color=body.avatar_color,
            template_key=body.template,
        )
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    except Exception as exc:
        # Duplicate email / auth rejection / write failure. Log server-side (no
        # secret in the payload) and return a generic client error, never a 500.
        logger.warning("provision_user_failed", actor=current.id, error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create user (email may already exist)",
        ) from exc

    await record_activity(
        current, kind="member", action="provisioned member", target=body.name, meta=body.role,
        entity_type="user", entity_id=str(row["id"]),
    )
    # Welcome the new member by email + in-app (best-effort). The password was set
    # by the admin, so it is NOT echoed here - only the username + a sign-in nudge.
    await notify(
        str(row["id"]),
        kind="member_welcome",
        title="Your team account is ready",
        body=(
            f"Hi {body.name}, your account has been created with the {body.role} role. "
            f"Sign in to your team portal with the username \"{body.username or str(body.email)}\" "
            "to see your dashboard and assigned work."
        ),
    )
    return MemberResponse.from_row(row)


@router.post("/invite", response_model=MemberInviteResponse, status_code=status.HTTP_201_CREATED)
async def invite_member(
    body: InviteMemberRequest,
    current: ManageTeam,
) -> MemberInviteResponse:
    """Add a team member with server-generated credentials (mirrors the wizard).

    Picks a role template (or an explicit feature list) to seed ``user_feature_grants``,
    stamps the ``must_reset`` / ``must_setup_2fa`` intent flags, and returns
    ``{username, tempPassword}`` in the response. The wizard that already DISPLAYED a
    credential pair sends that same pair in the body — the stored hash must match what
    the admin copied; absent fields are server-generated. Owner-only for owner/admin
    roles (escalation guard).

    The password is NOT single-use, whatever the field name suggests: nothing enforces
    ``must_reset``, so it keeps working until an owner/admin rotates it from Team
    Management. It is recoverable rather than shown-once — ``provision_user`` also
    seals an AES-256-GCM copy, which ``GET /admin/users/{id}/credentials`` reopens.
    See the comment at the ``notify`` call below for why both facts are stated here.
    """
    if body.role in _ELEVATED_ROLES and not current.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a super-admin can create owner/admin users",
        )
    username = body.username or generate_username(body.name)
    temp_password = (
        body.password.get_secret_value() if body.password is not None else generate_password()
    )
    # Explicit custom toggles win over a template; each granted feature is 'full'.
    feature_grants: dict[str, AccessLevel] | None = (
        cast("dict[str, AccessLevel]", dict.fromkeys(body.features, "full"))
        if body.features is not None
        else None
    )
    try:
        row = await asyncio.to_thread(
            provision_user,
            email=str(body.email),
            password=temp_password,
            name=body.name,
            role=body.role,
            username=username,
            title=body.title,
            avatar_color=body.avatar_color,
            template_key=body.template,
            feature_grants=feature_grants,
            must_reset=True,
            must_setup_2fa=True,
        )
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    except Exception as exc:
        logger.warning("invite_member_failed", actor=current.id, error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create user (email or username may already exist)",
        ) from exc

    await record_activity(
        current, kind="member", action="invited member", target=body.name, meta=body.role,
        entity_type="user", entity_id=str(row["id"]),
    )
    # Send the invitation email with the credentials (best-effort); the admin also
    # sees the pair in the response to copy manually.
    #
    # `must_reset` / `must_setup_2fa` above are RECORDED, NOT ENFORCED. Nothing
    # reads either column — not `login()`, not `get_current_user`, not one line of
    # frontend — so no reset is demanded and no 2FA enrolment is triggered. They
    # are kept because they are the correct record of intent for the day a reset
    # screen exists; until then, read them as a note, never as a control.
    #
    # This copy used to promise both ("you'll be asked to set a new password",
    # "only works once") and neither was true: the same password signs in again
    # tomorrow, and self-service password change was REMOVED from the product on
    # the owner's instruction (see `AccountSettings.tsx`), so the person receiving
    # this mail has no way to change it themselves even if they want to. Telling
    # them to expect a prompt that will never appear sends them looking for a
    # screen that does not exist. The words now match the product: this is the
    # password, keep it, and an owner/admin rotates it from Team Management.
    await notify(
        str(row["id"]),
        kind="member_welcome",
        title="You've been invited to the team portal",
        body=(
            f"Hi {body.name}, an account has been created for you ({body.role}).\n\n"
            f"Username: {username}\n"
            f"Password: {temp_password}\n\n"
            "Sign in to your team portal with these details, and keep them somewhere "
            "safe — this is your password from now on. If you ever need it changed, "
            "an owner or admin resets it for you from Team Management."
        ),
    )
    return MemberInviteResponse(
        member=MemberResponse.from_row(row), username=username, temp_password=temp_password
    )


@router.get("/{user_id}/grants", response_model=UserGrantsResponse)
async def get_grants(user_id: str, current: AccessControl) -> UserGrantsResponse:
    """Read a user's effective access level for all 17 features (access_control)."""
    try:
        target = await asyncio.to_thread(_load_user_min, current.id, user_id)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    if target is None:
        raise _USER_NOT_FOUND
    role = str(target["role"])
    if role == "client":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Clients have no feature grants"
        )
    overrides = await asyncio.to_thread(_read_grant_overrides, current.id, user_id)
    return UserGrantsResponse(grants=_resolve_grants(role, overrides))


@router.put("/{user_id}/grants", response_model=UserGrantsResponse)
async def set_grants(
    user_id: str, body: UpdateGrantsRequest, current: AccessControl
) -> UserGrantsResponse:
    """Set a user's per-feature access levels (access_control). Owner is locked all-on."""
    try:
        target = await asyncio.to_thread(_load_user_min, current.id, user_id)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    if target is None:
        raise _USER_NOT_FOUND
    role = str(target["role"])
    if role == "owner":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Owner access is all-on and cannot be edited",
        )
    if role == "client":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Clients have no feature grants"
        )

    if body.grants:
        await asyncio.to_thread(_write_grant_overrides, user_id, body.grants)
        await record_activity(
            current, kind="access", action="updated feature access", target=role,
            entity_type="user", entity_id=user_id,
        )
        # LEAD/ADMIN -> TEAM: tell the member their access changed (best-effort;
        # honours their notification_prefs; never blocks the grant write).
        # access_change is a NOTIF_EVENTS key (email default on).
        await notify(
            user_id,
            kind="access_change",
            title="Your access was updated",
            body=(
                "An administrator updated your feature access. Sign in to your team "
                "portal to see what changed."
            ),
        )

    overrides = await asyncio.to_thread(_read_grant_overrides, current.id, user_id)
    return UserGrantsResponse(grants=_resolve_grants(role, overrides))


# --- Reversible login credentials (resend-credentials tool) ------------------
#
# By product decision the Team screen can show + copy a member's login password so
# an admin can hand it over at any time. The password is stored sealed (AES-256-GCM
# under VAULT_MASTER_KEY, migration 0051) and opened here for an owner/admin. These
# are the ONLY routes that return a plaintext login password; every reveal/reset is
# recorded in the activity log, and only an owner may touch an owner/admin account
# (the same escalation guard as create_user).


def _guard_elevated_target(current: CurrentUser, role: str) -> None:
    """Only a super-admin may reveal/reset an owner or admin account's credentials."""
    if role in _ELEVATED_ROLES and not current.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a super-admin can access an owner/admin account's credentials",
        )


@router.get("/{user_id}/credentials", response_model=MemberCredentials)
async def get_member_credentials(user_id: str, current: ManageTeam) -> MemberCredentials:
    """Reveal a member's login + password (owner/admin; sealed copy opened server-side)."""
    try:
        target = await asyncio.to_thread(_load_cred_target, current.id, user_id)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    if target is None:
        raise _USER_NOT_FOUND
    _guard_elevated_target(current, str(target["role"]))

    password = await asyncio.to_thread(reveal_password, user_id)
    await record_activity(
        current, kind="access", action="revealed login credentials",
        target=str(target.get("name") or target.get("username") or ""),
        entity_type="user", entity_id=user_id,
    )
    return MemberCredentials(
        id=str(target["id"]),
        username=target.get("username"),
        email=str(target.get("email") or ""),
        password=password,
        available=password is not None,
    )


@router.post("/{user_id}/password", response_model=MemberCredentials)
async def set_member_password(
    user_id: str,
    body: SetPasswordRequest,
    current: ManageTeam,
    redis: RedisDep,
    settings: SettingsDep,
) -> MemberCredentials:
    """Set/rotate a member's login password and return it once (owner/admin).

    With no ``password`` in the body the server generates a strong one. The new
    password is hashed (argon2id) AND sealed for future reveal; ``must_reset`` is
    cleared so the shared password logs in directly.

    **Rotating the password also ends every session the OLD password opened.**
    Without that, changing a password after a suspected compromise accomplished
    nothing for days: the attacker's existing bearer token kept working until its
    own expiry, because the token never consults the password again. One
    per-user revocation epoch closes all of them (see
    `app.services.token_denylist`).
    """
    try:
        target = await asyncio.to_thread(_load_cred_target, current.id, user_id)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    if target is None:
        raise _USER_NOT_FOUND
    role = str(target["role"])
    _guard_elevated_target(current, role)
    if role == "client":
        # Portal-client passwords are managed through the client surface, not here.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use the client portal to manage a client login",
        )

    new_password = (
        body.password.get_secret_value() if body.password is not None else generate_password()
    )
    ok = await asyncio.to_thread(set_password, user_id, new_password)
    if not ok:
        raise _USER_NOT_FOUND

    # End the sessions the OLD password opened. Best-effort by design: the
    # password change itself has already taken effect in Postgres, and failing
    # the request here would leave the operator believing the rotation did not
    # happen when it did. Logged loudly so the gap is visible.
    if not await revoke_all_for_user(
        redis, user_id=user_id, max_token_ttl=settings.jwt_access_ttl_seconds
    ):
        logger.warning(
            "password_rotation_token_revocation_unavailable", target=user_id, actor=current.id
        )

    await record_activity(
        current, kind="access", action="reset login password",
        target=str(target.get("name") or target.get("username") or ""),
        entity_type="user", entity_id=user_id,
    )
    return MemberCredentials(
        id=str(target["id"]),
        username=target.get("username"),
        email=str(target.get("email") or ""),
        password=new_password,
        available=True,
    )


# --------------------------------------------------------------------------- #
# Offboarding (P0-6 / P0-7)
# --------------------------------------------------------------------------- #
# Until this existed there was NO WAY to remove a person from the platform. The
# `user_status` enum had no access state, `login()` never read status, and the
# multi-day bearer token could not be revoked - so a departing team member kept
# full access to every client's data until their token expired on its own, while
# `manage_team` advertised the capability in the UI.
#
# Suspension, not deletion: `tasks.assignee_id`, `activity_log.actor_id` and every
# audit trail reference the user id. Deleting the row would cascade away history
# or break those references - so an offboarded person's record is kept and their
# ACCESS is closed.


def _load_full_user(caller_id: str, target_id: str) -> dict[str, Any] | None:
    """The full roster row for one user (RLS path), for a MemberResponse."""
    with rls_connection(caller_id) as cur:
        cur.execute("select * from public.users where id = %s limit 1", (target_id,))
        return cur.fetchone()


async def _member_with_metrics(
    metrics: TeamMetricsDep, caller_id: str, user_id: str
) -> MemberResponse:
    """One roster row in the same shape (and with the same metrics overlay) the
    list endpoint returns, so a suspend/reactivate response drops straight into
    whatever the caller already renders."""
    row = await asyncio.to_thread(_load_full_user, caller_id, user_id)
    if row is None:
        raise _USER_NOT_FOUND
    overlaid = await _overlay_metrics(metrics, [MemberResponse.from_row(row)])
    return overlaid[0]


def _suspension_guard(actor: CurrentUser, target: dict[str, Any]) -> None:
    """Refuse the three suspensions that would damage the platform itself.

    These are interlocks, not permission checks - `manage_team` has already been
    verified by the dependency. Each one prevents an action that is authorised but
    catastrophic:

    1. **Self-suspension.** An operator would revoke their own session mid-request
       and could not undo it. Always a mistake, never a legitimate offboarding -
       a person leaving is offboarded BY someone.
    2. **Suspending an owner or admin without being an owner.** The mirror of the
       existing escalation guard on provisioning: if an admin cannot CREATE an
       admin, an admin must not be able to REMOVE one. Otherwise the weaker role
       can neutralise the stronger.
    3. **Suspending the last owner.** Owner is the only role that can restore
       another owner, so this would leave the platform permanently ownerless with
       no in-product recovery path.
    """
    target_id = str(target["id"])
    target_role = str(target["role"])

    if target_id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot suspend your own account.",
        )
    if target_role in _ELEVATED_ROLES and not actor.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a super-admin can suspend an owner or admin.",
        )
    if target_role == "owner" and _count_active_owners() <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot suspend the last remaining super-admin.",
        )


@router.post("/{user_id}/suspend", response_model=SuspensionResponse)
async def suspend_user(
    user_id: str,
    body: SuspendUserRequest,
    current: ManageTeam,
    redis: RedisDep,
    settings: SettingsDep,
    metrics: TeamMetricsDep,
) -> SuspensionResponse:
    """Offboard a person: close their access and end their live sessions.

    Two layers, and the order matters. The DATABASE flip is the boundary - once
    `status = 'suspended'`, `get_current_user` refuses every subsequent request
    whatever else is broken. The Redis revocation is written AFTERWARDS and is a
    latency optimisation on top of it, so a Redis failure can never leave a
    suspension half-applied.
    """
    try:
        target = await asyncio.to_thread(_load_user_min, current.id, user_id)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    if target is None:
        raise _USER_NOT_FOUND

    # Idempotent: re-suspending an already-suspended account is a no-op, not an
    # error. An operator retrying after a timeout must not see a failure.
    if str(target.get("status") or "") == SUSPENDED_STATUS:
        member = await _member_with_metrics(metrics, current.id, user_id)
        # `tokens_revoked` is False, not True: THIS call revoked nothing. The
        # earlier suspension already did, and claiming otherwise would be exactly
        # the kind of unearned success this recovery is removing.
        return SuspensionResponse(user=member, status=SUSPENDED_STATUS, tokens_revoked=False)

    # `_count_active_owners` inside the guard hits the DB, so run the whole guard
    # off the event loop (psycopg is sync).
    await asyncio.to_thread(_suspension_guard, current, target)

    updated = await asyncio.to_thread(
        _set_suspension,
        target_id=user_id,
        actor_id=current.id,
        suspended=True,
        reason=body.reason,
    )
    if updated is None:
        raise _USER_NOT_FOUND

    # Now end the sessions the person already holds. Reported honestly: a False
    # here means the cache layer did not engage, NOT that they still have access.
    revoked = await revoke_all_for_user(
        redis, user_id=user_id, max_token_ttl=settings.jwt_access_ttl_seconds
    )
    if not revoked:
        logger.warning("suspend_token_revocation_unavailable", target=user_id, actor=current.id)

    logger.info("user_suspended", target=user_id, actor=current.id, tokens_revoked=revoked)
    await record_activity(
        current, kind="access", action="suspended member",
        target=str(updated.get("name") or user_id),
        meta=body.reason or "no reason given",
        entity_type="user", entity_id=user_id,
    )
    member = await _member_with_metrics(metrics, current.id, user_id)
    return SuspensionResponse(user=member, status=SUSPENDED_STATUS, tokens_revoked=revoked)


@router.post("/{user_id}/reactivate", response_model=SuspensionResponse)
async def reactivate_user(
    user_id: str,
    current: ManageTeam,
    metrics: TeamMetricsDep,
) -> SuspensionResponse:
    """Restore a suspended person's access.

    Restoring an OWNER or ADMIN is owner-only, mirroring both the provisioning
    escalation guard and the suspend interlock: an admin who cannot create or
    remove an admin must not be able to reinstate one either.

    No token revocation is undone, and none should be: the old sessions stay dead
    and the person signs in again. `tokens_revoked` is reported as False because
    nothing was revoked by THIS call - it is not a claim that old tokens work.
    """
    try:
        target = await asyncio.to_thread(_load_user_min, current.id, user_id)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    if target is None:
        raise _USER_NOT_FOUND

    if str(target["role"]) in _ELEVATED_ROLES and not current.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a super-admin can reactivate an owner or admin.",
        )

    updated = await asyncio.to_thread(
        _set_suspension, target_id=user_id, actor_id=current.id, suspended=False, reason=""
    )
    if updated is None:
        raise _USER_NOT_FOUND

    logger.info("user_reactivated", target=user_id, actor=current.id)
    await record_activity(
        current, kind="access", action="reactivated member",
        target=str(updated.get("name") or user_id), meta="access restored",
        entity_type="user", entity_id=user_id,
    )
    member = await _member_with_metrics(metrics, current.id, user_id)
    return SuspensionResponse(user=member, status="active", tokens_revoked=False)
