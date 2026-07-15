"""Data access for the CANONICAL CONTEXT STORE (P6B-2): the ``entity_context``
living-summary + ``facts`` source of truth and the ``context_vectors`` Pinecone
sync ledger.

Two trust levels, mirroring the module split:

* **RLS reads** open ``rls_connection(self._user_id)`` so Postgres RLS is the
  boundary. ``is_staff()`` gates the base tables; a portal client reads ONLY its
  own client-level row through the ``portal_context`` security-barrier view. These
  are the endpoints the retrieval API (P6B-8) will call.
* **service_role writes** open ``privileged_connection()`` (BYPASSRLS). The
  compaction worker (P6B-7) owns every write to ``entity_context`` /
  ``context_vectors`` - there is deliberately NO RLS write policy - so those
  methods never carry a user identity.

Methods are synchronous (psycopg is sync; the caller offloads with
``asyncio.to_thread``). All SQL is parameterized (values always bound, table/
column names static literals); the ``context_entity`` enum is cast in-SQL so a
text bind assigns. The single ``get_context_repo`` dependency makes the layer
trivially replaceable with an in-memory fake in tests.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends
from psycopg.types.json import Jsonb

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection

_Rows = list[dict[str, Any]]

# The columns a compaction fold may set on entity_context (facts is bound as
# jsonb; version/watermark/status are bumped explicitly by upsert_context).
_UPSERT_COLS = (
    "summary",
    "facts",
    "token_budget",
    "token_count",
    "event_watermark",
    "status",
    "model",
    "checksum",
)


class ContextRepo:
    """Repository over ``entity_context`` (source of truth) + ``context_vectors``
    (the Pinecone ledger). RLS reads are user-scoped; writes are service_role."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --------------------------------------------------------------------- #
    # RLS reads (role authenticated; staff via is_staff(), client via view)
    # --------------------------------------------------------------------- #
    def get_entity_context(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        """The living-context row for one entity, or ``None`` (staff-scoped)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.entity_context "
                "where entity_type = %s::public.context_entity and entity_id = %s limit 1",
                (entity_type, entity_id),
            )
            return cur.fetchone()

    def list_contexts(
        self, entity_type: str | None = None, *, limit: int | None = None, offset: int = 0
    ) -> _Rows:
        """Contexts the caller may read (staff), most-recently-updated first.

        Optionally filtered to one ``entity_type``. Powers the org-wide health
        rollup (P6B-8/9); a portal client gets zero rows from this base table.
        """
        query = "select * from public.entity_context"
        params: list[Any] = []
        if entity_type is not None:
            query += " where entity_type = %s::public.context_entity"
            params.append(entity_type)
        query += " order by updated_at desc"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def read_portal_context(self) -> dict[str, Any] | None:
        """The calling client's OWN client-level summary+facts via the
        ``portal_context`` security-barrier view (the view returns exactly one
        row, self-filtered to ``current_client_id()``). ``None`` for staff/anon."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.portal_context limit 1")
            return cur.fetchone()

    # --------------------------------------------------------------------- #
    # service_role writes (BYPASSRLS; the compaction worker owns these)
    # --------------------------------------------------------------------- #
    def get_context_for_update(
        self, entity_type: str, entity_id: str
    ) -> dict[str, Any] | None:
        """Row-lock the entity's context for a compaction fold (``FOR UPDATE``).

        Runs on the privileged path inside its transaction so the worker holds the
        lock for the read-fold-write cycle; returns ``None`` when no row exists yet.
        """
        with privileged_connection() as cur:
            cur.execute(
                "select * from public.entity_context "
                "where entity_type = %s::public.context_entity and entity_id = %s "
                "for update",
                (entity_type, entity_id),
            )
            return cur.fetchone()

    def upsert_context(
        self,
        entity_type: str,
        entity_id: str,
        *,
        summary: str = "",
        facts: dict[str, Any] | None = None,
        token_budget: int = 1200,
        token_count: int = 0,
        event_watermark: int = 0,
        status: str = "summarized",
        model: str = "",
        checksum: str = "",
    ) -> dict[str, Any]:
        """Insert-or-update the entity's living context, bumping version.

        On first write the row is created (version stays 0); on every subsequent
        fold ``version`` increments and ``event_watermark`` advances to the highest
        seq folded in (``greatest`` guards against a stale/out-of-order write). The
        freshness invariant ``event_watermark >= latest_seq`` is asserted by the
        caller for ``status='summarized'``. Returns the persisted row.
        """
        values: dict[str, Any] = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "summary": summary,
            "facts": Jsonb(facts if facts is not None else {}),
            "token_budget": token_budget,
            "token_count": token_count,
            "event_watermark": event_watermark,
            "status": status,
            "model": model,
            "checksum": checksum,
        }
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.entity_context "
                "(entity_type, entity_id, summary, facts, token_budget, token_count, "
                " event_watermark, status, model, checksum) "
                "values (%(entity_type)s::public.context_entity, %(entity_id)s, %(summary)s, "
                " %(facts)s, %(token_budget)s, %(token_count)s, %(event_watermark)s, "
                " %(status)s::public.context_status, %(model)s, %(checksum)s) "
                "on conflict (entity_type, entity_id) do update set "
                " summary         = excluded.summary, "
                " facts           = excluded.facts, "
                " token_budget    = excluded.token_budget, "
                " token_count     = excluded.token_count, "
                " event_watermark = greatest(public.entity_context.event_watermark, "
                "                            excluded.event_watermark), "
                " status          = excluded.status, "
                " model           = excluded.model, "
                " checksum        = excluded.checksum, "
                " version         = public.entity_context.version + 1 "
                "returning *",
                values,
            )
            return cast("dict[str, Any]", cur.fetchone())

    # --------------------------------------------------------------------- #
    # Compaction-worker helpers (P6B-7; service_role, privileged path)
    # --------------------------------------------------------------------- #
    def events_after(self, entity_type: str, entity_id: str, watermark: int) -> _Rows:
        """The entity's activity events with ``seq > watermark``, oldest first.

        This is the fold input: everything the context has NOT yet absorbed, in
        total ``seq`` order. Uses the ``activity_log_entity_seq_idx`` partial index.
        """
        with privileged_connection() as cur:
            cur.execute(
                "select seq, kind, action, target, meta, created_at "
                "from public.activity_log "
                "where entity_type = %s::public.context_entity and entity_id = %s "
                "and seq > %s order by seq",
                (entity_type, entity_id, watermark),
            )
            return cur.fetchall()

    def dirty_last_seq(self, entity_type: str, entity_id: str) -> int | None:
        """The entity's current ``context_dirty.last_seq`` (the highest seq the
        trigger has coalesced), or ``None`` when no dirty row exists.

        The re-dirty check reads this AFTER a fold: if it exceeds the watermark just
        folded, a new event landed mid-compaction and the row must stay ``pending``.
        """
        with privileged_connection() as cur:
            cur.execute(
                "select last_seq from public.context_dirty "
                "where entity_type = %s::public.context_entity and entity_id = %s limit 1",
                (entity_type, entity_id),
            )
            row = cur.fetchone()
        return int(row["last_seq"]) if row is not None else None

    def clear_dirty(self, entity_type: str, entity_id: str) -> None:
        """Delete the entity's dirty row - the claim is fully drained (all events
        folded). A later event re-creates it via the AFTER-INSERT trigger."""
        with privileged_connection() as cur:
            cur.execute(
                "delete from public.context_dirty "
                "where entity_type = %s::public.context_entity and entity_id = %s",
                (entity_type, entity_id),
            )

    def rearm_dirty(
        self, entity_type: str, entity_id: str, *, last_seq: int, backoff_seconds: int
    ) -> None:
        """Re-arm the entity's dirty row ``pending`` with a pushed-out eligibility.

        Upsert (never lost): a ``backoff_seconds`` of 0 makes it eligible NOW (the
        re-dirty fast-path), a positive value pushes ``next_eligible_at`` out so a
        degraded/errored entity retries LATER without hot-spinning. ``last_seq`` only
        ever advances (``greatest``); ``event_count`` is left untouched on conflict.
        """
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.context_dirty as d "
                "(entity_type, entity_id, last_seq, event_count, first_dirty_at, "
                " next_eligible_at, status) "
                "values (%(et)s::public.context_entity, %(eid)s, %(last_seq)s, 0, now(), "
                " now() + make_interval(secs => %(backoff)s), 'pending') "
                "on conflict (entity_type, entity_id) do update set "
                " status           = 'pending', "
                " last_seq         = greatest(d.last_seq, excluded.last_seq), "
                " next_eligible_at = now() + make_interval(secs => %(backoff)s)",
                {"et": entity_type, "eid": entity_id, "last_seq": last_seq, "backoff": backoff_seconds},
            )

    def claim_due_dirty(self, limit: int) -> _Rows:
        """Atomically claim up to ``limit`` DUE dirty rows for compaction.

        One statement: a ``FOR UPDATE SKIP LOCKED`` CTE selects ``pending`` rows
        whose ``next_eligible_at`` has passed (skipping any a concurrent beat tick
        already holds), and the outer ``UPDATE`` flips them to ``processing`` and
        returns them. SKIP LOCKED means two dispatchers never claim the same row -
        the exactly-once-ish backbone. Returns ``entity_type/entity_id/last_seq``.
        """
        with privileged_connection() as cur:
            cur.execute(
                "with due as ( "
                "  select entity_type, entity_id from public.context_dirty "
                "  where status = 'pending' and next_eligible_at <= now() "
                "  order by next_eligible_at "
                "  for update skip locked "
                "  limit %s "
                ") "
                "update public.context_dirty d set status = 'processing' "
                "from due where d.entity_type = due.entity_type and d.entity_id = due.entity_id "
                "returning d.entity_type, d.entity_id, d.last_seq",
                (limit,),
            )
            return cur.fetchall()

    def list_vectors(self, entity_type: str, entity_id: str) -> _Rows:
        """The entity's live vector ledger (drives reconcile/GC/consistency)."""
        with privileged_connection() as cur:
            cur.execute(
                "select * from public.context_vectors "
                "where entity_type = %s::public.context_entity and entity_id = %s "
                "order by chunk_key",
                (entity_type, entity_id),
            )
            return cur.fetchall()

    def record_vector(
        self,
        entity_type: str,
        entity_id: str,
        *,
        chunk_key: str,
        pinecone_id: str,
        content_checksum: str,
        version: int,
        dim: int,
        model: str,
    ) -> dict[str, Any]:
        """Upsert one ledger row for a (re)embedded chunk, keyed by chunk_key.

        A changed ``content_checksum`` for the same chunk overwrites the prior
        ledger entry (and its ``pinecone_id`` / ``version`` / ``embedded_at``), so
        the ledger always names the CURRENT vector for that chunk. Returns the row.
        """
        values: dict[str, Any] = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "chunk_key": chunk_key,
            "pinecone_id": pinecone_id,
            "content_checksum": content_checksum,
            "version": version,
            "dim": dim,
            "model": model,
        }
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.context_vectors "
                "(entity_type, entity_id, chunk_key, pinecone_id, content_checksum, "
                " version, dim, model) "
                "values (%(entity_type)s::public.context_entity, %(entity_id)s, %(chunk_key)s, "
                " %(pinecone_id)s, %(content_checksum)s, %(version)s, %(dim)s, %(model)s) "
                "on conflict (entity_type, entity_id, chunk_key) do update set "
                " pinecone_id      = excluded.pinecone_id, "
                " content_checksum = excluded.content_checksum, "
                " version          = excluded.version, "
                " dim              = excluded.dim, "
                " model            = excluded.model, "
                " embedded_at      = now() "
                "returning *",
                values,
            )
            return cast("dict[str, Any]", cur.fetchone())

    def delete_vector(
        self, entity_type: str, entity_id: str, chunk_key: str
    ) -> dict[str, Any] | None:
        """Drop a superseded chunk from the ledger, returning the deleted row.

        The caller uses the returned ``pinecone_id`` to delete the vector from the
        store too (supersession GC removes it from BOTH stores). ``None`` when the
        chunk was not in the ledger.
        """
        with privileged_connection() as cur:
            cur.execute(
                "delete from public.context_vectors "
                "where entity_type = %s::public.context_entity and entity_id = %s "
                "and chunk_key = %s returning *",
                (entity_type, entity_id, chunk_key),
            )
            return cur.fetchone()


# The compaction worker holds NO user JWT: it only ever calls the service_role
# (privileged) methods above, which ignore ``user_id`` entirely. This nil identity
# makes that explicit; the RLS-read methods MUST NOT be called on a worker repo
# (they would reject the nil uuid at ``rls_connection`` - by design).
_SERVICE_NIL_UUID = "00000000-0000-0000-0000-000000000000"


def service_context_repo() -> ContextRepo:
    """A ``ContextRepo`` for the service_role compaction worker (privileged writes).

    The worker uses only the ``get_context_for_update`` / ``upsert_context`` /
    ``events_after`` / dirty-queue / vector-ledger methods - all on the privileged
    (BYPASSRLS) connection - so it carries the nil identity, never a real user.
    """
    return ContextRepo(_SERVICE_NIL_UUID)


def get_context_repo(user: CurrentUserDep) -> ContextRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped reads).

    Depends on ``get_current_user`` (via ``user``) so auth resolves first; the
    repo carries ``user.id`` for the RLS reads and opens ``privileged_connection``
    directly for the service_role writes.
    """
    return ContextRepo(user.id)


ContextRepoDep = Annotated[ContextRepo, Depends(get_context_repo)]
