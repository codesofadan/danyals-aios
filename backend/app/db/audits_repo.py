"""Data access for the ``audits`` job ledger via the RLS-scoped ``rls_connection``
seam. Reads + the queued-row insert are tenant-scoped by Postgres RLS; the
worker's status updates use the service_role path instead (see
``workers/tasks/audit.py``). Methods are synchronous - the router offloads them
with ``asyncio.to_thread`` - and the single ``get_audits_repo`` dependency makes
the layer trivially replaceable with an in-memory fake in tests.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class AuditsRepo:
    """Thin repository over the ``audits`` table (RLS-scoped)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_audits(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        query = "select * from public.audits order by created_at desc"
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.audits where id = %s limit 1", (audit_id,))
            return cur.fetchone()

    def previous_audit(self, audit_id: str) -> dict[str, Any] | None:
        """The completed audit of the SAME SITE immediately before this one.

        What "the same site" means here is the audited URL as stored, not the client: the
        comparison is about a site's own history, and an agency legitimately audits a
        prospect's site before that prospect is a client - so keying on the client would
        make the first month of every engagement incomparable to the audit that won it.

        Only ``done`` runs qualify. A failed or queued run has no findings to compare, and
        offering one as the baseline would produce a delta claiming every problem was
        fixed. RLS-scoped, so a caller who cannot see the earlier audit gets nothing rather
        than a comparison against a row they may not read.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                """select prev.* from public.audits prev
                   join public.audits cur on cur.id = %s
                   where prev.url = cur.url
                     and prev.id <> cur.id
                     and prev.status = 'done'
                     and prev.created_at < cur.created_at
                   order by prev.created_at desc
                   limit 1""",
                (audit_id,),
            )
            return cur.fetchone()

    def audits_of_same_site(self, audit_id: str, *, limit: int = 20) -> _Rows:
        """Every completed audit of this audit's site, newest first (for the run picker).

        Includes the audit itself, so a UI can render "compare with" from one call and show
        which row is the current one without a second query.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                """select prev.id, prev.created_at, prev.depth, prev.tier, prev.score,
                          prev.status
                   from public.audits prev
                   join public.audits cur on cur.id = %s
                   where prev.url = cur.url and prev.status = 'done'
                   order by prev.created_at desc
                   limit %s""",
                (audit_id, limit),
            )
            return cur.fetchall()

    def set_visibility(self, audit_id: str, *, visible: bool) -> dict[str, Any] | None:
        """Share this audit with the client's portal, or stop sharing it.

        Returns the updated row, or None when nothing was updated.

        The None case is load-bearing. ``audits_modify`` is a ``for all`` policy
        scoped to owner/admin/manager/specialist/analyst, so a ``viewer`` hitting
        this path is refused by RLS - and an RLS refusal does NOT raise, it
        matches zero rows. Returning the row and making the caller check it is
        what stops a silent no-op being reported to an operator as "shared".
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.audits set visible_to_client = %s "
                "where id = %s returning *",
                (visible, audit_id),
            )
            return cur.fetchone()

    def public_page(self, audit_id: str) -> dict[str, Any] | None:
        """This audit's public-page registry row (slug + published), or None.

        The registry (0126) mints a slug for every completed audit, but a PAID
        audit's page is `published = false` by default because it is client
        deliverable work. So the presence of a row means "a link could exist",
        never "a link is live" - callers must read `published`.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select slug, kind, published, views, last_viewed_at, expires_at "
                "from public.public_audit_pages where audit_id = %s limit 1",
                (audit_id,),
            )
            return cur.fetchone()

    def published_pages(self) -> dict[str, str]:
        """``{audit_id: slug}`` for every audit whose public page is LIVE.

        One query for the whole board rather than one per row: the audit list is
        paginated but still renders many rows, and a per-row lookup would be an
        N+1 on a page an operator opens constantly.

        Only published rows are returned, so a caller cannot accidentally render
        a link to a page that 404s for the person it was sent to.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select audit_id, slug from public.public_audit_pages "
                "where published and audit_id is not null"
            )
            return {str(r["audit_id"]): str(r["slug"]) for r in cur.fetchall()}

    def set_public_page_published(
        self, audit_id: str, *, published: bool
    ) -> dict[str, Any] | None:
        """Publish this audit's public page, or take it back down.

        Returns the registry row, or None when nothing was updated - which is
        the same load-bearing distinction as `set_visibility` above: an RLS
        refusal matches zero rows rather than raising, so reporting success
        without checking would tell an operator a link is live when it is not.

        This does NOT mint a page. Minting happens on completion in the worker,
        which is what keeps slug derivation in one place; publishing a report
        that was never generated has nothing to point at.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.public_audit_pages set published = %s "
                "where audit_id = %s "
                "returning slug, kind, published, views, last_viewed_at, expires_at",
                (published, audit_id),
            )
            return cur.fetchone()

    def set_public_page_expiry(
        self, audit_id: str, *, expires_at: Any | None
    ) -> dict[str, Any] | None:
        """Set (or clear, with ``None``) when this audit's public link stops resolving.

        Separate from ``set_published`` because they are different decisions: publishing
        opens a link to anyone holding it, and an expiry bounds how long that stays true.
        An operator routinely does the first without the second, and pairing them in one
        write would make "publish" silently reset an expiry somebody had set.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.public_audit_pages set expires_at = %s "
                "where audit_id = %s "
                "returning slug, kind, published, views, last_viewed_at, expires_at",
                (expires_at, audit_id),
            )
            return cur.fetchone()

    def clear_error(self, audit_id: str) -> dict[str, Any] | None:
        """Drop the recorded reason a completed audit's findings were unavailable.

        ``audits.error`` on a ``done`` row means "the run finished but its findings
        were not stored as rows, and here is why". Once a rebuild has produced those
        rows the sentence is false, so it is cleared rather than left to describe a
        state that no longer exists.

        Narrow on purpose, like ``set_visibility``: a generic update on this table
        would let a route reviewed as a repair edit a completed run's url, tier or
        cost. Returns None when RLS matched no row (a refusal does not raise).
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.audits set error = null where id = %s returning *",
                (audit_id,),
            )
            return cur.fetchone()

    def insert_audit(self, row: dict[str, Any]) -> dict[str, Any]:
        cols = list(row.keys())
        stmt = sql.SQL("insert into public.audits ({cols}) values ({vals}) returning *").format(
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(row.values()))
            return cast("dict[str, Any]", cur.fetchone())


def get_audits_repo(user: CurrentUserDep) -> AuditsRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped).

    Depends on ``get_current_user`` (via ``user``) so auth resolves first; the
    repo carries ``user.id`` and opens ``rls_connection`` per method.
    """
    return AuditsRepo(user.id)


AuditsRepoDep = Annotated[AuditsRepo, Depends(get_audits_repo)]
