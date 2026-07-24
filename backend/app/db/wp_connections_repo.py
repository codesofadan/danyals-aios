"""RLS-scoped reads for the multi-client WordPress Connections registry.

Reads run on ``rls_connection(user_id)`` so Postgres RLS enforces staff-only access
(the ``wp_connections_select`` policy, mirroring ``clients``). Every read is a
``clients LEFT JOIN wp_connections`` so the manager screen lists EVERY client with
its connection state (or an unconfigured placeholder) - and it exposes only a
``configured`` boolean (``secret_sealed is not null``), NEVER the sealed bytea, so a
read can never leak the credential. Writes (seal / delete / status) live in the
privileged service (``app/services/wp_connections.py``), mirroring the vault pattern.

SQL rules (impersonation-review mandate): every VALUE is a bound param; table/column
names are static literals.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

# The manager-screen row: one per client, its connection metadata LEFT-joined (null
# when unconfigured), plus a `configured` flag - never the sealed secret.
_JOIN_SELECT = (
    "select c.id as client_id, c.name as client_name, "
    "w.site_url, w.auth_method, w.username, w.status, w.last_tested_at, "
    "(w.secret_sealed is not null) as configured "
    "from public.clients c "
    "left join public.wp_connections w on w.client_id = c.id"
)


class WpConnectionsRepo:
    """Read-only repository over ``clients`` joined with ``wp_connections`` (RLS)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_with_clients(self) -> list[dict[str, Any]]:
        """Every visible client with its connection metadata (unconfigured -> nulls)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(f"{_JOIN_SELECT} order by c.name")
            return cur.fetchall()

    def get_for_client(self, client_id: str) -> dict[str, Any] | None:
        """One client's row (with connection metadata joined), or None if not visible."""
        with rls_connection(self._user_id) as cur:
            cur.execute(f"{_JOIN_SELECT} where c.id = %s limit 1", (client_id,))
            return cur.fetchone()


def get_wp_connections_repo(user: CurrentUserDep) -> WpConnectionsRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return WpConnectionsRepo(user.id)


WpConnectionsRepoDep = Annotated[WpConnectionsRepo, Depends(get_wp_connections_repo)]
