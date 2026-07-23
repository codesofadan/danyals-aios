"""User provisioning - the ONLY path that creates a login (no public signup).

Since the P6A-7 cutover this writes to LOCAL Postgres, not Supabase GoTrue. A
super-admin calls it to mint the credential row (``auth.users`` with an argon2id
``password_hash``) AND the matching ``public.users`` identity row (plus any
per-feature grants seeded from a template OR an explicit toggle list) in ONE
atomic ``privileged_connection`` transaction (service_role, BYPASSRLS - creating
an account is a privileged system operation). The plaintext password never leaves
this call and is never logged.

Future path (NOT implemented): importing existing bcrypt hashes would insert the
``$2b$`` hash directly and let ``verify_password`` re-hash to argon2id on first
login. This is a fresh local start, so only argon2id is produced here.

All calls here are blocking (psycopg is sync); the caller offloads them with
``asyncio.to_thread``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from app.db.database import privileged_connection
from app.logging_setup import get_logger
from app.rbac import AccessLevel, UserRole
from app.rbac.matrix import TEMPLATES
from app.services.login_credentials import store_login_password
from app.services.passwords import hash_password

logger = get_logger("app.provisioning")


def _template_grants(template_key: str | None) -> tuple[str, ...]:
    """Feature keys a template switches on, or empty if no/unknown template."""
    if not template_key:
        return ()
    for tpl in TEMPLATES:
        if tpl.key == template_key:
            return tpl.grants
    return ()


def _resolve_grants(
    template_key: str | None, feature_grants: Mapping[str, AccessLevel] | None
) -> list[tuple[str, str]]:
    """Resolve the (feature_key, level) rows to seed at provisioning time.

    An explicit ``feature_grants`` map WINS (the wizard's per-toggle output);
    ``'off'`` entries are dropped (absence already means off). With no explicit
    map, a template seeds its granted features at ``'full'``. Either way returns a
    list ready for ``executemany``.
    """
    if feature_grants is not None:
        return [(key, level) for key, level in feature_grants.items() if level != "off"]
    return [(key, "full") for key in _template_grants(template_key)]


def provision_user(
    *,
    email: str,
    password: str,
    name: str,
    role: UserRole,
    username: str | None = None,
    title: str = "",
    avatar_color: str = "#7B69EE",
    template_key: str | None = None,
    feature_grants: Mapping[str, AccessLevel] | None = None,
    must_reset: bool = False,
    must_setup_2fa: bool = False,
    client_id: str | None = None,
) -> dict[str, Any]:
    """Create the credential + identity rows (+ grants); return the new row.

    ``role='client'`` provisions a portal login and REQUIRES ``client_id`` (the
    tenant it is scoped to); a staff role must leave ``client_id`` None. This
    mirrors the DB CHECK (client_id set iff role='client') and fails fast before
    the write rather than surfacing a raw constraint error.

    ``feature_grants`` (an explicit per-feature level map) overrides ``template_key``
    when given; ``must_reset`` / ``must_setup_2fa`` stamp the first-login onboarding
    flags used by the generated-credential invite flow (7F-4).

    Idempotency is intentionally NOT assumed: a duplicate email or username fails
    on the unique constraint, surfacing as an error the router maps to 400 rather
    than silently overwriting an account. The whole write is one transaction, so a
    failure on any statement rolls back the credential AND the identity together -
    never a half-created user.
    """
    if role == "client" and not client_id:
        raise ValueError("a client login requires client_id")
    if role != "client" and client_id is not None:
        raise ValueError("only a client login may set client_id")

    uid = str(uuid.uuid4())
    password_hash = hash_password(password)
    grants = _resolve_grants(template_key, feature_grants)

    with privileged_connection() as cur:
        # 1) credential (argon2id) -> auth.users. 2) identity -> public.users
        # (same id, FK-linked). Both inside one txn: atomic all-or-nothing.
        cur.execute(
            "insert into auth.users (id, email, password_hash) values (%s, %s, %s)",
            (uid, email, password_hash),
        )
        cur.execute(
            """
            insert into public.users
                (id, email, username, name, role, title, avatar_color, status,
                 must_reset, must_setup_2fa, client_id)
            values (%s, %s, %s, %s, %s, %s, %s, 'invited', %s, %s, %s)
            """,
            (uid, email, username, name, role, title, avatar_color,
             must_reset, must_setup_2fa, client_id),
        )
        if grants:
            cur.executemany(
                "insert into public.user_feature_grants (user_id, feature_key, level) "
                "values (%s, %s, %s)",
                [(uid, key, level) for key, level in grants],
            )
        cur.execute("select * from public.users where id = %s limit 1", (uid,))
        row = cur.fetchone()

    if not row:  # pragma: no cover - the insert above just wrote this row
        raise RuntimeError("provisioned user row could not be read back")

    # Store a sealed copy of the login password for the owner/admin credential-reveal
    # tool (separate from the argon2id hash; reuses vault_keys, no DDL). Best-effort:
    # a vault/DB hiccup here must never fail an otherwise-successful account creation.
    try:
        store_login_password(uid, password)
    except Exception:  # reveal is a convenience — never block a successful provision
        logger.warning("login_password_store_failed", user_id=uid)

    return row
