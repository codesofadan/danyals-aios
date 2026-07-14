"""User provisioning - the ONLY path that creates a login (no public signup).

A super-admin calls this to mint a Supabase Auth user *and* the matching
``public.users`` row (plus any per-feature grants seeded from a template). It
uses the service_role admin client because creating an auth user and writing the
initial identity row are privileged system operations that must bypass RLS. The
service_role key stays server-side and is never returned or logged.

All calls here are blocking (supabase-py is sync); the caller offloads them with
``asyncio.to_thread``.
"""

from __future__ import annotations

from typing import Any, cast

from supabase import Client

from app.rbac import UserRole
from app.rbac.matrix import TEMPLATES


def _template_grants(template_key: str | None) -> tuple[str, ...]:
    """Feature keys a template switches on, or empty if no/unknown template."""
    if not template_key:
        return ()
    for tpl in TEMPLATES:
        if tpl.key == template_key:
            return tpl.grants
    return ()


def provision_user(
    admin: Client,
    *,
    email: str,
    password: str,
    name: str,
    role: UserRole,
    title: str = "",
    avatar_color: str = "#7B69EE",
    template_key: str | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
    """Create the auth user + users row (+ template grants); return the new row.

    ``role='client'`` provisions a portal login and REQUIRES ``client_id`` (the
    tenant it is scoped to); a staff role must leave ``client_id`` None. This
    mirrors the DB CHECK (client_id set iff role='client') and fails fast before
    the write rather than surfacing a raw constraint error.

    Idempotency is intentionally NOT assumed: a duplicate email fails at the auth
    layer (and the unique constraint on ``users.email``), surfacing as an error
    the router maps to 409/400 rather than silently overwriting an account.
    """
    if role == "client" and not client_id:
        raise ValueError("a client login requires client_id")
    if role != "client" and client_id is not None:
        raise ValueError("only a client login may set client_id")

    created = admin.auth.admin.create_user(
        {"email": email, "password": password, "email_confirm": True}
    )
    auth_user: Any = getattr(created, "user", None) or created
    uid = str(auth_user.id)

    admin.table("users").insert(
        {
            "id": uid,
            "email": email,
            "name": name,
            "role": role,
            "title": title,
            "avatar_color": avatar_color,
            "status": "invited",
            "client_id": client_id,
        }
    ).execute()

    grants = _template_grants(template_key)
    if grants:
        admin.table("user_feature_grants").insert(
            [{"user_id": uid, "feature_key": key, "level": "full"} for key in grants]
        ).execute()

    resp = admin.table("users").select("*").eq("id", uid).limit(1).execute()
    rows = cast("list[dict[str, Any]]", resp.data or [])
    if not rows:  # pragma: no cover - the insert above just wrote this row
        raise RuntimeError("provisioned user row could not be read back")
    return rows[0]
