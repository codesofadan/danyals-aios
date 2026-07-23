"""Read access to vault key METADATA via the RLS-scoped ``rls_connection`` seam.

Only the masked list is read here (RLS restricts it to owner/admin). The raw
secret is never touched on this path - reveal goes through the service layer.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class VaultRepo:
    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_keys(self) -> _Rows:
        # Excludes the reserved '__login__' rows (members' own login passwords, kept
        # for the Team-screen credential-reveal tool) - they are not integration keys
        # and must never surface on the Key Vault screen.
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.vault_keys where provider <> '__login__' order by created_at"
            )
            return cur.fetchall()


def get_vault_repo(user: CurrentUserDep) -> VaultRepo:
    """Depends on ``get_current_user`` (via ``user``) so auth resolves first; the
    repo carries ``user.id`` and opens ``rls_connection`` per method.
    """
    return VaultRepo(user.id)


VaultRepoDep = Annotated[VaultRepo, Depends(get_vault_repo)]
