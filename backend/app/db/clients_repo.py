"""Data access for clients + sites via the RLS-respecting user-JWT client.

Every method uses ``client_for_user`` so Postgres RLS enforces access; the repo
holds only the caller's token. Methods are synchronous (supabase-py is sync) -
the router offloads them with ``asyncio.to_thread``. A single ``get_clients_repo``
dependency makes the whole layer trivially replaceable with an in-memory fake
in tests.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends, Request

from app.db.supabase import client_for_user

_Rows = list[dict[str, Any]]


class ClientsRepo:
    """Thin repository over the ``clients`` and ``sites`` tables."""

    def __init__(self, access_token: str) -> None:
        self._token = access_token

    def _client(self) -> Any:
        return client_for_user(self._token)

    # --- clients --------------------------------------------------------------
    def list_clients(self) -> _Rows:
        resp = self._client().table("clients").select("*").order("name").execute()
        return cast("_Rows", resp.data or [])

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        resp = self._client().table("clients").select("*").eq("id", client_id).limit(1).execute()
        rows = cast("_Rows", resp.data or [])
        return rows[0] if rows else None

    def insert_client(self, row: dict[str, Any]) -> dict[str, Any]:
        resp = self._client().table("clients").insert(row).execute()
        rows = cast("_Rows", resp.data or [])
        return rows[0]

    def update_client(self, client_id: str, row: dict[str, Any]) -> dict[str, Any] | None:
        resp = self._client().table("clients").update(row).eq("id", client_id).execute()
        rows = cast("_Rows", resp.data or [])
        return rows[0] if rows else None

    def delete_client(self, client_id: str) -> bool:
        resp = self._client().table("clients").delete().eq("id", client_id).execute()
        return bool(cast("_Rows", resp.data or []))

    # --- sites ----------------------------------------------------------------
    def site_counts(self) -> dict[str, int]:
        resp = self._client().table("sites").select("client_id").execute()
        counts: dict[str, int] = {}
        for r in cast("_Rows", resp.data or []):
            key = str(r["client_id"])
            counts[key] = counts.get(key, 0) + 1
        return counts

    def list_sites(self, client_id: str) -> _Rows:
        resp = (
            self._client().table("sites").select("*").eq("client_id", client_id).order("domain").execute()
        )
        return cast("_Rows", resp.data or [])

    def insert_site(self, row: dict[str, Any]) -> dict[str, Any]:
        resp = self._client().table("sites").insert(row).execute()
        rows = cast("_Rows", resp.data or [])
        return rows[0]

    def delete_site(self, site_id: str) -> bool:
        resp = self._client().table("sites").delete().eq("id", site_id).execute()
        return bool(cast("_Rows", resp.data or []))


def get_clients_repo(request: Request) -> ClientsRepo:
    """Dependency: a repo bound to the caller's access token (RLS-scoped)."""
    token: str = getattr(request.state, "access_token", "")
    return ClientsRepo(token)


ClientsRepoDep = Annotated[ClientsRepo, Depends(get_clients_repo)]
