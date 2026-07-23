"""Data access for clients + sites via the RLS-scoped ``rls_connection`` seam.

Every method opens ``rls_connection(self._user_id)`` so Postgres RLS enforces
access; the repo holds only the caller's verified user id (never a raw JWT).
Methods are synchronous (psycopg is sync) - the router offloads them with
``asyncio.to_thread``. A single ``get_clients_repo`` dependency makes the whole
layer trivially replaceable with an in-memory fake in tests.

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``),
never string-formatted, because any statement on the authenticated pool can set
``app.user_id``; a value-injection would be a tenant compromise. Table/column
names are static literals - the only dynamic column lists (insert/update) come
from server-built dicts and are quoted via ``psycopg.sql.Identifier``.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends
from psycopg import sql
from psycopg.types.json import Jsonb

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class ClientsRepo:
    """Thin repository over the ``clients`` and ``sites`` tables."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- clients --------------------------------------------------------------
    def list_clients(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        query = "select * from public.clients order by name"
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.clients where id = %s limit 1", (client_id,))
            return cur.fetchone()

    def insert_client(self, row: dict[str, Any]) -> dict[str, Any]:
        cols = list(row.keys())
        stmt = sql.SQL("insert into public.clients ({cols}) values ({vals}) returning *").format(
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(row.values()))
            return cast("dict[str, Any]", cur.fetchone())

    def update_client(self, client_id: str, row: dict[str, Any]) -> dict[str, Any] | None:
        cols = list(row.keys())
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols
        )
        stmt = sql.SQL("update public.clients set {sets} where id = %s returning *").format(
            sets=assignments
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*row.values(), client_id])
            return cur.fetchone()

    def delete_client(self, client_id: str) -> bool:
        with rls_connection(self._user_id) as cur:
            cur.execute("delete from public.clients where id = %s returning id", (client_id,))
            return bool(cur.fetchall())

    # --- client business profile (NAP, 0051) ----------------------------------
    def get_business_profile(self, client_id: str) -> dict[str, Any] | None:
        """The client's stored NAP (``client_business_profiles``), or ``None`` when the
        wizard skipped it. RLS-scoped, so a client the caller cannot see reads ``None``."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.client_business_profiles where client_id = %s limit 1",
                (client_id,),
            )
            return cur.fetchone()

    def upsert_business_profile(
        self, *, client_id: str, client_name: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Insert or update the ONE NAP record for a client (``unique (client_id)``), so a
        re-save from the Edit modal overwrites rather than duplicates. ``hours`` is a
        jsonb column, so it is wrapped in ``Jsonb`` (psycopg3 will not adapt a raw dict
        through a ``%s`` placeholder); ``extra_categories`` is ``text[]``, adapted natively.
        client_id/client_name come from the verified client, never from the wire."""
        if isinstance(fields.get("hours"), dict):
            fields = {**fields, "hours": Jsonb(fields["hours"])}
        cols = ["client_id", "client_name", *fields.keys()]
        placeholders = sql.SQL(", ").join([sql.Placeholder()] * len(cols))
        updates = sql.SQL(", ").join(
            sql.SQL("{} = excluded.{}").format(sql.Identifier(c), sql.Identifier(c))
            for c in ("client_name", *fields.keys())
        )
        stmt = sql.SQL(
            "insert into public.client_business_profiles ({cols}) values ({vals}) "
            "on conflict (client_id) do update set {updates} returning *"
        ).format(
            cols=sql.SQL(", ").join(sql.Identifier(c) for c in cols),
            vals=placeholders,
            updates=updates,
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [client_id, client_name, *fields.values()])
            return cur.fetchone()

    # --- sites ----------------------------------------------------------------
    def site_counts(self) -> dict[str, int]:
        with rls_connection(self._user_id) as cur:
            cur.execute("select client_id from public.sites")
            rows = cur.fetchall()
        counts: dict[str, int] = {}
        for r in rows:
            key = str(r["client_id"])
            counts[key] = counts.get(key, 0) + 1
        return counts

    def list_all_sites(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        """Every visible site ACROSS clients, each carrying its client's name + status.

        Additive read for the ``client_setup`` tool workspace (Part 8 Phase 2.5).
        ``list_sites`` is scoped to ONE client by signature, so a cross-client board had
        no way to render without one query per client (and ``sites`` carries no
        client-name snapshot, unlike the ledger tables - it is joined live here).

        INNER join, deliberately: ``sites.client_id`` is ``not null references clients``,
        so a site without a client cannot exist and the join drops nothing. Only the
        display columns are selected - ``client_id`` is never among them, so the
        internal id cannot reach a response by accident. Both tables are RLS-scoped
        (staff see all; a portal client has no ``sites`` select policy).
        """
        query = (
            "select s.id, s.domain, s.cms_type, "
            "c.name as client_name, c.status as client_status "
            "from public.sites s "
            "join public.clients c on c.id = s.client_id "
            "order by c.name, s.domain"
        )
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def list_sites(self, client_id: str, *, limit: int | None = None, offset: int = 0) -> _Rows:
        query = "select * from public.sites where client_id = %s order by domain"
        params: list[Any] = [client_id]
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def insert_site(self, row: dict[str, Any]) -> dict[str, Any]:
        cols = list(row.keys())
        stmt = sql.SQL("insert into public.sites ({cols}) values ({vals}) returning *").format(
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(row.values()))
            return cast("dict[str, Any]", cur.fetchone())

    def delete_site(self, site_id: str) -> bool:
        with rls_connection(self._user_id) as cur:
            cur.execute("delete from public.sites where id = %s returning id", (site_id,))
            return bool(cur.fetchall())


def get_clients_repo(user: CurrentUserDep) -> ClientsRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped).

    Depends on ``get_current_user`` (via ``user``) so auth resolves first; the
    repo carries ``user.id`` and opens ``rls_connection`` per method.
    """
    return ClientsRepo(user.id)


ClientsRepoDep = Annotated[ClientsRepo, Depends(get_clients_repo)]
