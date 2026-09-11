"""Operator SESSIONS (0130, off-page redesign Phase 4): batch-based citation building.

The 0110 queue hands an operator one item at a time. A session hands them a BATCH
(default 10): the extension opens every released task's add-listing form in its own tab,
autofills where a spec is earned, and the person walks the tabs reviewing and submitting.
When the last task of the current batch goes terminal, the NEXT batch releases - in the
SAME transaction, so there is no cron, no sweeper, and no moment where a finished batch
sits waiting for a schedule.

WHAT A SESSION IS NOT. It is not a second evidence path. Claims ride the EXISTING
``citations`` lease columns (claimed_by / claimed_at / claim_expires_at); the ONLY
writers of evidence remain ``/queue/{id}/complete`` (probe-verified) and ``/blocked``
(closed vocabulary). A session task's ``ui_state`` is UI telemetry with zero authority:
the forward, non-terminal half (pending -> released -> opened -> form_detected ->
filled -> awaiting_submit) is extension-reported; the terminal values
{submitted, skipped, deferred, blocked} are written only server-side by the terminal
handlers.

Everything here runs on ``rls_connection`` (the operator's own identity), and each
public method is ONE transaction - which is what makes the batch release transactional:
marking the last task terminal and releasing batch N+1 either both happen or neither
does. The session row is taken ``FOR UPDATE`` inside that transaction so two terminal
handlers racing on the same batch serialize instead of double-releasing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends
from psycopg import Cursor
from psycopg.errors import UniqueViolation
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from app.db.database import rls_connection
from app.logging_setup import get_logger
from app.modules.citations.operator_auth import AnyQueueScopeDep, OperatorOrUserWriteDep
from app.modules.citations.repo import CitationQueueRepo

logger = get_logger("app.modules.citations.sessions")

#: Same lease the per-item queue uses (router's _QUEUE_LEASE_SECONDS): long enough for a
#: prepared item, short enough that a closed laptop returns work within a coffee break.
SESSION_LEASE_SECONDS = 20 * 60

#: The forward, non-terminal ui_state ladder, in order. The telemetry endpoint accepts
#: ONLY strictly-forward moves within this ladder; anything else is a 409, and the
#: terminal vocabulary below is not even representable in its request schema.
UI_STATE_ORDER: dict[str, int] = {
    "pending": 0,
    "released": 1,
    "opened": 2,
    "form_detected": 3,
    "filled": 4,
    "awaiting_submit": 5,
}

#: Written ONLY server-side, by the terminal handlers (complete/blocked/skip/defer).
TERMINAL_UI_STATES: frozenset[str] = frozenset({"submitted", "skipped", "deferred", "blocked"})

#: The evidence tiers a from-gaps session may pull. A citation-BUILDING session is for
#: directories where the business is genuinely NOT listed - `no_evidence` (the audit
#: looked and found nothing). `uncertain` is deliberately EXCLUDED: a weak/unconfirmed
#: signal means a listing may ALREADY exist, and building a second one risks a duplicate
#: - those belong to the separate "verify first" review, not the build queue. `confirmed`
#: and `inconsistent_nap` are existing listings and were never pulled. (`ready_for_human`
#: rows - the campaign's queued gaps - are always included, independent of this set.)
FROM_GAPS_TIERS: frozenset[str] = frozenset({"no_evidence"})

#: The session kinds 0130 reserved; 'web2_placement' went live with 0136 (Phase 7).
SESSION_KINDS: frozenset[str] = frozenset({"citation", "web2_placement"})

#: The closed blocked vocabulary for a web2 placement task - REUSED verbatim from the
#: citation queue's (QueueBlockedRequest) rather than minted anew: the obstacles an
#: operator hits in an editor are the same family (a captcha, a paywall, a changed
#: form), and one vocabulary keeps the "which platforms waste our time?" rollup
#: answerable across both lanes. Unlike a citation block, this writes ONLY the session
#: task (terminal `blocked` + the reason in telemetry): the PROPERTY stays parked at
#: `publishing` - an operator's obstacle is not evidence about the placement itself,
#: and un-approving paid, reviewed work needs a lead's decision, not a task button.
WEB2_BLOCK_REASONS: frozenset[str] = frozenset({
    "captcha_wall", "account_required", "paid_only", "form_changed",
    "duplicate_listing", "directory_dead", "phone_verification",
    "postcard_verification", "other",
})

_NON_TERMINAL_SQL = "('pending', 'released', 'opened', 'form_detected', 'filled', 'awaiting_submit')"
_ACTIVE_UI_SQL = "('released', 'opened', 'form_detected', 'filled', 'awaiting_submit')"


# --------------------------------------------------------------------------- #
# Pure helpers (no DB) - the unit-testable half of the state machine.
# --------------------------------------------------------------------------- #
def telemetry_transition_allowed(current: str, new: str) -> bool:
    """Whether the EXTENSION may move a task ``current -> new``.

    Forward-only within the non-terminal ladder, strictly: the extension may never
    repeat a state, never go backwards, and never write a terminal value - terminal is
    the server's verdict, produced by the probe-verified complete / closed-vocab
    blocked / skip / defer handlers, and a UI report must not be able to fake it."""
    if new in TERMINAL_UI_STATES or current in TERMINAL_UI_STATES:
        return False
    if new not in UI_STATE_ORDER or current not in UI_STATE_ORDER:
        return False
    return UI_STATE_ORDER[new] > UI_STATE_ORDER[current]


def batch_no_for(index: int, batch_size: int) -> int:
    """Which batch the ``index``-th selected citation lands in (1-based batches)."""
    return index // max(1, batch_size) + 1


def session_is_stale(
    updated_at: datetime | None, now: datetime, lease_seconds: int = SESSION_LEASE_SECONDS
) -> bool:
    """Whether an ACTIVE session has been abandoned in fact if not in status.

    The session heartbeat bumps ``updated_at`` every minute while the extension is
    alive; silence past the claim lease means the browser is gone. The reap is LAZY
    (checked on the next read/create - no cron, per the platform's no-beat rule), and
    it is what keeps the one-active-session index from wedging an operator whose
    browser crashed mid-shift."""
    if updated_at is None:
        return True
    anchored = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=UTC)
    return (now - anchored) >= timedelta(seconds=lease_seconds)


class NoSessionWorkError(Exception):
    """Raised (rolling the creation transaction back) when nothing is selectable."""


class ActiveSessionExistsError(Exception):
    """Raised when the operator already holds a live active session."""


# --------------------------------------------------------------------------- #
# The repo. RLS-scoped; one public method = one transaction.
# --------------------------------------------------------------------------- #
class OperatorSessionsRepo:
    """``operator_sessions`` / ``operator_session_tasks`` (0130), RLS-scoped.

    Never touches the privileged pool: an operator can only ever session-ize citations
    for a client they can already see, and Postgres decides that, not a WHERE clause
    remembered in five methods."""

    #: The joined card SELECT: the task columns, then EXACTLY the queue's own joined
    #: row (c.* + directory + business-profile aliases) so the router's `_queue_fields`
    #: reads a session card and a queue item identically - one shape, one serializer.
    _CARD_SELECT = (
        CitationQueueRepo._QUEUE_SELECT.replace(
            "select c.*",
            "select t.id as task_id, t.batch_no, t.position, t.ui_state, "
            "t.ui_state_at, t.telemetry, c.*",
            1,
        )
        + "join public.operator_session_tasks t on t.citation_id = c.id "
    )

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- the one-active-session rule (and its lazy reap) ------------------------
    def active_session(self, *, reap_stale: bool = True) -> dict[str, Any] | None:
        """This operator's ACTIVE session, or None.

        With ``reap_stale`` (the default), a session whose heartbeat went silent past
        the lease is flipped to ``abandoned`` and its claims released IN THIS CALL -
        so a crashed browser can never wedge the one-active-session index, and the
        ad-hoc claim refusal never cites a session that is only nominally alive."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.operator_sessions "
                "where operator_id = %s::uuid and status = 'active' "
                "for update limit 1",
                (self._user_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            if reap_stale and session_is_stale(row.get("updated_at"), datetime.now(UTC)):
                self._abandon(cur, str(row["id"]))
                return None
            return row

    def _abandon(self, cur: Cursor[DictRow], session_id: str) -> None:
        """Lease-reap: release every claim this session still holds, close it out."""
        cur.execute(
            "update public.citations c set "
            "  claimed_by = null, claimed_at = null, claim_expires_at = null "
            "from public.operator_session_tasks t "
            "where t.session_id = %s::uuid and t.citation_id = c.id "
            f"  and t.ui_state in {_NON_TERMINAL_SQL} "
            "  and c.claimed_by = %s::uuid",
            (session_id, self._user_id),
        )
        cur.execute(
            "update public.operator_sessions set "
            "  status = 'abandoned', closed_at = now(), updated_at = now() "
            "where id = %s::uuid",
            (session_id,),
        )

    # --- creation ---------------------------------------------------------------
    def create_session(
        self,
        *,
        client_id: str,
        client_name: str,
        batch_size: int,
        params: dict[str, Any],
        tiers: list[str] | None,
        limit: int,
        citation_ids: list[str] | None,
        kind: str = "citation",
    ) -> dict[str, Any]:
        """Create a session + its tasks + release (and, for citations, claim) batch 1,
        in ONE transaction.

        ``kind='citation'``: selection is ``FOR UPDATE SKIP LOCKED`` over claimable
        citations only - a row someone else holds (unexpired claim) or is claiming
        right now is excluded at creation, never fought over. ``citation_ids`` is the
        explicit "build exactly these" path; otherwise the from-gaps path pulls this
        client's queue rows (`ready_for_human`) plus its candidate-gap / verify-first
        discoveries (`no_evidence` / `uncertain`, filtered by ``tiers``).

        ``kind='web2_placement'`` (0136, Phase 7): selection is this client's parked
        extension-lane properties (`publishing` + `publish_method='extension'` - the
        state approval routes them to) not already inside any ACTIVE session. Web2
        properties carry NO lease columns; a batch is exclusive because the row is
        inside a live session's non-terminal task, and the lazy session reap is what
        returns it to the pool. Batch mechanics are otherwise identical.

        Raises ``ActiveSessionExistsError`` / ``NoSessionWorkError`` - both roll the whole
        transaction back, so a refused creation leaves no session row behind."""
        if kind not in SESSION_KINDS:
            raise ValueError(f"unknown session kind: {kind!r}")
        with rls_connection(self._user_id) as cur:
            try:
                cur.execute(
                    "insert into public.operator_sessions "
                    "(client_id, client_name, operator_id, kind, batch_size, params) "
                    "values (%s, %s, %s::uuid, %s, %s, %s) returning *",
                    (client_id, client_name, self._user_id, kind, batch_size, Jsonb(params)),
                )
            except UniqueViolation as exc:  # the partial unique index: one active each
                raise ActiveSessionExistsError() from exc
            session = cur.fetchone()
            if session is None:
                raise NoSessionWorkError()
            session_id = str(session["id"])

            if kind == "web2_placement":
                candidates = self._select_web2_candidates(cur, client_id=client_id, limit=limit)
            else:
                candidates = self._select_candidates(
                    cur, client_id=client_id, tiers=tiers, limit=limit,
                    citation_ids=citation_ids,
                )
            if not candidates:
                raise NoSessionWorkError()

            target_col = "web2_id" if kind == "web2_placement" else "citation_id"
            batch1: list[str] = []
            for i, row in enumerate(candidates):
                batch = batch_no_for(i, batch_size)
                if batch == 1:
                    batch1.append(str(row["id"]))
                cur.execute(
                    "insert into public.operator_session_tasks "
                    f"(session_id, {target_col}, batch_no, position) values (%s, %s, %s, %s)",
                    (session_id, str(row["id"]), batch, i),
                )

            if kind == "web2_placement":
                self._release_web2_tasks(cur, session_id, batch_no=1, web2_ids=batch1)
            else:
                # Claim batch 1. The rows are already locked by our SKIP LOCKED select,
                # so this cannot conflict; `human_attempts` counts like a queue claim.
                self._claim_and_release(cur, session_id, batch_no=1, citation_ids=batch1)
            return session

    def _select_web2_candidates(
        self, cur: Cursor[DictRow], *, client_id: str, limit: int
    ) -> list[dict[str, Any]]:
        """This client's parked extension-lane placements, LOCKED for this txn.

        A property inside ANY active session's non-terminal task is excluded - the
        exclusivity rule the citation lease provides, expressed for a table that has
        no lease columns. ``FOR UPDATE SKIP LOCKED`` on the property rows serializes
        two operators creating sessions at the same instant."""
        cur.execute(
            "select w.id from public.web2_properties w "
            "where w.client_id = %s "
            "  and w.status = 'publishing' and w.publish_method = 'extension' "
            "  and not exists ( "
            "    select 1 from public.operator_session_tasks t "
            "    join public.operator_sessions s on s.id = t.session_id "
            "    where t.web2_id = w.id and s.status = 'active' "
            f"      and t.ui_state in {_NON_TERMINAL_SQL}) "
            "order by w.created_at "
            "for update of w skip locked "
            "limit %s",
            (client_id, max(1, limit)),
        )
        return cur.fetchall()

    def _release_web2_tasks(
        self, cur: Cursor[DictRow], session_id: str, *, batch_no: int, web2_ids: list[str]
    ) -> None:
        """Mark a web2 batch released. No claim stamping - web2 exclusivity IS the
        live session task (see ``_select_web2_candidates``)."""
        if web2_ids:
            cur.execute(
                "update public.operator_session_tasks set "
                "  ui_state = 'released', ui_state_at = now() "
                "where session_id = %s::uuid and batch_no = %s "
                "  and web2_id = any(%s::uuid[])",
                (session_id, batch_no, web2_ids),
            )

    def _select_candidates(
        self,
        cur: Cursor[DictRow],
        *,
        client_id: str,
        tiers: list[str] | None,
        limit: int,
        citation_ids: list[str] | None,
    ) -> list[dict[str, Any]]:
        """The claimable citations this session will work, LOCKED for this txn.

        Route-F rows never enter (the terms check the queue's own claim makes);
        already-claimed rows are excluded; a row another transaction is claiming this
        instant is skipped, not waited on."""
        if citation_ids:
            # Explicit choice - not second-guessed beyond safety: right client, not
            # route F, not claimed, and not already in flight or live.
            cur.execute(
                "select c.id from public.citations c "
                "left join public.directories d on d.id = c.directory_id "
                "where c.id = any(%s::uuid[]) and c.client_id = %s "
                "  and coalesce(d.route, 'C') <> 'F' "
                "  and (c.claimed_by is null or c.claim_expires_at < now()) "
                "  and coalesce(c.submit_status::text, 'not_started') "
                "      not in ('queued', 'submitting', 'live') "
                "order by c.created_at "
                "for update of c skip locked",
                (citation_ids, client_id),
            )
            return cur.fetchall()
        wanted = [t for t in (tiers or sorted(FROM_GAPS_TIERS)) if t in FROM_GAPS_TIERS]
        cur.execute(
            "select c.id from public.citations c "
            "left join public.directories d on d.id = c.directory_id "
            "where c.client_id = %s "
            "  and coalesce(d.route, 'C') <> 'F' "
            "  and (c.claimed_by is null or c.claim_expires_at < now()) "
            "  and (c.submit_status = 'ready_for_human' "
            "       or (coalesce(c.submit_status::text, 'not_started') = 'not_started' "
            "           and c.live_url = '' and c.evidence_level = any(%s))) "
            "order by c.created_at "
            "for update of c skip locked "
            "limit %s",
            # An all-invalid tier list matches NOTHING - '' would quietly match the
            # pre-tier legacy rows, which nobody asked for.
            (client_id, wanted or ["__none__"], max(1, limit)),
        )
        return cur.fetchall()

    def _claim_and_release(
        self, cur: Cursor[DictRow], session_id: str, *, batch_no: int, citation_ids: list[str]
    ) -> None:
        """Stamp the queue's OWN claim columns on a batch and mark its tasks released."""
        if citation_ids:
            cur.execute(
                "update public.citations set "
                "  claimed_by = %s::uuid, claimed_at = now(), "
                "  claim_expires_at = now() + make_interval(secs => %s), "
                "  human_attempts = human_attempts + 1 "
                "where id = any(%s::uuid[])",
                (self._user_id, SESSION_LEASE_SECONDS, citation_ids),
            )
            cur.execute(
                "update public.operator_session_tasks set "
                "  ui_state = 'released', ui_state_at = now() "
                "where session_id = %s::uuid and batch_no = %s "
                "  and citation_id = any(%s::uuid[])",
                (session_id, batch_no, citation_ids),
            )

    # --- reads ------------------------------------------------------------------
    #: Session row + the two aggregates every summary needs (never a guessed default:
    #: a session with 23 tasks must not render as 0-task because the list was cheap).
    _SESSION_SELECT = (
        "select s.*, "
        "  (select count(*) from public.operator_session_tasks t "
        "     where t.session_id = s.id) as task_count, "
        "  (select coalesce(max(t.batch_no), 1) from public.operator_session_tasks t "
        "     where t.session_id = s.id) as total_batches "
        "from public.operator_sessions s "
    )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(self._SESSION_SELECT + "where s.id = %s::uuid limit 1", (session_id,))
            return cur.fetchone()

    def list_sessions(
        self, *, mine: bool = True, active: bool = False, limit: int = 20
    ) -> list[dict[str, Any]]:
        query = self._SESSION_SELECT
        clauses: list[str] = []
        params: list[Any] = []
        if mine:
            clauses.append("s.operator_id = %s::uuid")
            params.append(self._user_id)
        if active:
            clauses.append("s.status = 'active'")
        if clauses:
            query += "where " + " and ".join(clauses) + " "
        query += "order by s.created_at desc limit %s"
        params.append(limit)
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def session_task_rows(self, session_id: str) -> list[dict[str, Any]]:
        """Every task joined with its citation + directory + canonical NAP - the card
        rows. Same joined shape as a queue item, so the router serializes both with
        the same `_queue_fields`."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                self._CARD_SELECT
                + "where t.session_id = %s::uuid order by t.batch_no, t.position",
                (session_id,),
            )
            return cur.fetchall()

    def web2_task_rows(self, session_id: str) -> list[dict[str, Any]]:
        """The web2_placement card rows (0136): each task joined with its property
        (the approved draft), the platform's catalogue row (homepage host = the Open
        fallback) and the platform's ACTIVE placement spec, if one is earned.

        The LATERAL platform lookup prefers the ``platform_enum`` mapping over the
        free-text name and takes exactly one row, so a property can never fan out
        into two cards. A missing spec row is the fail-closed normal: the serializer
        then ships copy-blocks only."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select t.id as task_id, t.batch_no, t.position, t.ui_state, "
                "       t.ui_state_at, t.telemetry, "
                "       w.id, w.client_id, w.client_name, w.platform, w.topic, "
                "       w.body_md, w.anchor, w.target_url, w.status, w.post_url, "
                "       pl.id as platform_id, pl.name as platform_name, "
                "       pl.homepage_url as platform_homepage_url, "
                "       sp.id as spec_id, sp.spec as placement_spec "
                "from public.operator_session_tasks t "
                "join public.web2_properties w on w.id = t.web2_id "
                "left join lateral ( "
                "  select p.id, p.name, p.homepage_url from public.web2_platforms p "
                "  where p.platform_enum = w.platform::text or p.name = w.platform::text "
                "  order by (p.platform_enum = w.platform::text) desc, p.name limit 1 "
                ") pl on true "
                "left join public.web2_placement_specs sp "
                "  on sp.platform_id = pl.id and sp.active "
                "where t.session_id = %s::uuid "
                "order by t.batch_no, t.position",
                (session_id,),
            )
            return cur.fetchall()

    # --- heartbeat --------------------------------------------------------------
    def heartbeat(self, session_id: str, *, worked_seconds: int) -> dict[str, Any] | None:
        """Extend the lease on every released, non-terminal task and bank the time.

        Mirrors the per-item heartbeat semantics - the lease pushes out, the seconds
        ACCUMULATE - with one deliberate difference: the reported delta is SPREAD
        across the open items (integer share + remainder to the first rows) so the
        TOTAL banked equals the wall-clock worked. Banking the full delta onto every
        open tab would multiply minutes by the batch size and quietly corrupt the
        median the whole loaded-cost model rests on."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.operator_sessions set updated_at = now() "
                "where id = %s::uuid and operator_id = %s::uuid and status = 'active' "
                "returning id, kind",
                (session_id, self._user_id),
            )
            beat = cur.fetchone()
            if beat is None:
                return None
            if str(beat.get("kind") or "citation") == "web2_placement":
                # No lease columns on web2_properties: the heartbeat's whole job here
                # is the session-liveness bump above (which is what the lazy reap
                # reads). Reported seconds are dropped rather than mis-banked - there
                # is no worked_seconds ledger on the property row to keep honest.
                cur.execute(
                    "select count(*) as n from public.operator_session_tasks "
                    f"where session_id = %s::uuid and ui_state in {_ACTIVE_UI_SQL}",
                    (session_id,),
                )
                open_row = cur.fetchone()
                return {"ok": True, "extended": int(open_row["n"]) if open_row else 0}
            secs = max(0, worked_seconds)
            cur.execute(
                "with held as ( "
                "  select c.id, row_number() over (order by t.batch_no, t.position) as rn, "
                "         count(*) over () as n "
                "  from public.operator_session_tasks t "
                "  join public.citations c on c.id = t.citation_id "
                "  where t.session_id = %(sid)s::uuid "
                f"    and t.ui_state in {_ACTIVE_UI_SQL} "
                "    and c.claimed_by = %(uid)s::uuid "
                ") "
                "update public.citations c set "
                "  claim_expires_at = now() + make_interval(secs => %(lease)s), "
                "  worked_seconds = c.worked_seconds + (%(secs)s / h.n) "
                "    + case when h.rn <= (%(secs)s %% h.n) then 1 else 0 end "
                "from held h where c.id = h.id",
                {
                    "sid": session_id,
                    "uid": self._user_id,
                    "lease": SESSION_LEASE_SECONDS,
                    "secs": secs,
                },
            )
            return {"ok": True, "extended": int(cur.rowcount or 0)}

    # --- close ------------------------------------------------------------------
    def close_session(self, session_id: str) -> dict[str, Any] | None:
        """Explicit close: release every claim still held, then record the honest
        outcome - ``completed`` when every task is terminal, else ``abandoned``."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.operator_sessions "
                "where id = %s::uuid and operator_id = %s::uuid "
                "  and status in ('active', 'paused') for update limit 1",
                (session_id, self._user_id),
            )
            session = cur.fetchone()
            if session is None:
                return None
            cur.execute(
                "update public.citations c set "
                "  claimed_by = null, claimed_at = null, claim_expires_at = null "
                "from public.operator_session_tasks t "
                "where t.session_id = %s::uuid and t.citation_id = c.id "
                f"  and t.ui_state in {_NON_TERMINAL_SQL} "
                "  and c.claimed_by = %s::uuid",
                (session_id, self._user_id),
            )
            cur.execute(
                "select count(*) as open_tasks from public.operator_session_tasks "
                f"where session_id = %s::uuid and ui_state in {_NON_TERMINAL_SQL}",
                (session_id,),
            )
            row = cur.fetchone()
            outcome = "completed" if row and int(row["open_tasks"]) == 0 else "abandoned"
            cur.execute(
                "update public.operator_sessions set "
                "  status = %s, closed_at = now(), updated_at = now() "
                "where id = %s::uuid returning *",
                (outcome, session_id),
            )
            return cur.fetchone()

    # --- telemetry (forward-only, non-terminal) ---------------------------------
    def record_telemetry(
        self, session_id: str, task_id: str, *, new_state: str, detail: str = ""
    ) -> dict[str, Any] | None:
        """Advance a task's ui_state on the extension's report. Returns the updated
        task, ``None`` when the session/task is not this operator's live work, and
        raises ``ValueError`` on a non-forward or terminal transition (the router
        turns that into a 409 rather than a silent overwrite)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select t.id, t.ui_state from public.operator_session_tasks t "
                "join public.operator_sessions s on s.id = t.session_id "
                "where t.id = %s::uuid and t.session_id = %s::uuid "
                "  and s.operator_id = %s::uuid and s.status = 'active' "
                "for update of t limit 1",
                (task_id, session_id, self._user_id),
            )
            task = cur.fetchone()
            if task is None:
                return None
            current = str(task["ui_state"])
            if not telemetry_transition_allowed(current, new_state):
                raise ValueError(f"telemetry may not move a task {current} -> {new_state}")
            patch: dict[str, Any] = {new_state + "_at": datetime.now(UTC).isoformat()}
            if detail:
                patch[new_state + "_detail"] = detail[:500]
            cur.execute(
                "update public.operator_session_tasks set "
                "  ui_state = %s, ui_state_at = now(), telemetry = telemetry || %s "
                "where id = %s::uuid returning *",
                (new_state, Jsonb(patch), task_id),
            )
            return cur.fetchone()

    # --- terminal handlers (server-side ONLY) -----------------------------------
    def mark_citation_terminal(
        self, citation_id: str, terminal_state: str, *, meta: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """The post-terminal hook complete/blocked call: mark the matching task in this
        operator's ACTIVE session and run the batch-release check, one transaction.

        Returns ``{sessionId, batchNo, released}`` or ``None`` when the citation is not
        part of the caller's active session (the ad-hoc queue still works outside
        sessions; the hook is a no-op there)."""
        if terminal_state not in TERMINAL_UI_STATES:
            raise ValueError(f"not a terminal ui_state: {terminal_state!r}")
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.operator_session_tasks t set "
                "  ui_state = %s, ui_state_at = now(), telemetry = t.telemetry || %s "
                "from public.operator_sessions s "
                "where s.id = t.session_id and s.operator_id = %s::uuid "
                "  and s.status = 'active' and t.citation_id = %s::uuid "
                f"  and t.ui_state in {_NON_TERMINAL_SQL} "
                "returning t.session_id, t.batch_no",
                (terminal_state, Jsonb(meta or {}), self._user_id, citation_id),
            )
            marked = cur.fetchone()
            if marked is None:
                return None
            session_id = str(marked["session_id"])
            released = self._release_next_batches(cur, session_id)
            return {
                "sessionId": session_id,
                "batchNo": int(marked["batch_no"]),
                "released": released,
            }

    def mark_web2_terminal(
        self, web2_id: str, terminal_state: str, *, meta: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """``mark_citation_terminal``'s web2 twin (0136): the placement-complete hook.

        Marks the matching web2_placement task in this operator's ACTIVE session and
        runs the batch-release check, one transaction. ``None`` when the property is
        not part of the caller's active session - completion outside a session is
        fine, and the hook is a no-op there."""
        if terminal_state not in TERMINAL_UI_STATES:
            raise ValueError(f"not a terminal ui_state: {terminal_state!r}")
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.operator_session_tasks t set "
                "  ui_state = %s, ui_state_at = now(), telemetry = t.telemetry || %s "
                "from public.operator_sessions s "
                "where s.id = t.session_id and s.operator_id = %s::uuid "
                "  and s.status = 'active' and t.web2_id = %s::uuid "
                f"  and t.ui_state in {_NON_TERMINAL_SQL} "
                "returning t.session_id, t.batch_no",
                (terminal_state, Jsonb(meta or {}), self._user_id, web2_id),
            )
            marked = cur.fetchone()
            if marked is None:
                return None
            session_id = str(marked["session_id"])
            released = self._release_next_batches(cur, session_id)
            return {
                "sessionId": session_id,
                "batchNo": int(marked["batch_no"]),
                "released": released,
            }

    def block_web2_task(
        self, session_id: str, task_id: str, *, reason: str, detail: str = ""
    ) -> dict[str, Any] | None:
        """Terminal ``blocked`` for a WEB2 task, server-written, closed vocabulary.

        Web2-only by construction (``require_kind``): a citation task's block must
        travel through /queue/{id}/blocked, which also writes the citation row and
        the drift hook - this method must never offer a second, thinner door there.
        The PROPERTY is untouched: it stays parked for a lead to re-route or a later
        session to retry; the reason lives on the task telemetry."""
        if reason not in WEB2_BLOCK_REASONS:
            raise ValueError(f"not a known blocked reason: {reason!r}")
        return self._task_terminal(
            session_id, task_id, state="blocked",
            patch={
                "blocked_reason": reason,
                "blocked_detail": detail[:500],
                "blocked_at": datetime.now(UTC).isoformat(),
            },
            release_claim=False,
            require_kind="web2_placement",
        )

    def skip_task(
        self, session_id: str, task_id: str, *, reason: str
    ) -> dict[str, Any] | None:
        """Terminal ``skipped``: the operator chose not to work this one. The citation
        claim is released (the row returns to the pool untouched - nothing was
        attempted, so nothing is asserted) and the reason rides the task telemetry.
        (`citations.skip_reason` was dropped in 0121 as a zombie column; the task row
        is where this fact now lives.)"""
        return self._task_terminal(
            session_id, task_id, state="skipped",
            patch={"skip_reason": reason[:200], "skipped_at": datetime.now(UTC).isoformat()},
            release_claim=True,
        )

    def defer_task(self, session_id: str, task_id: str) -> dict[str, Any] | None:
        """Terminal-for-this-batch ``deferred``: the task re-batches to the TAIL (a
        fresh batch past the last), its claim is released, and when its new batch
        releases it comes back as ``released`` and is claimed again. The forward-only
        rule binds only the telemetry endpoint - this server-side flip is the designed
        exception."""
        return self._task_terminal(
            session_id, task_id, state="deferred",
            patch={"deferred_at": datetime.now(UTC).isoformat()},
            release_claim=True, rebatch_to_tail=True,
        )

    def _task_terminal(
        self,
        session_id: str,
        task_id: str,
        *,
        state: str,
        patch: dict[str, Any],
        release_claim: bool,
        rebatch_to_tail: bool = False,
        require_kind: str | None = None,
    ) -> dict[str, Any] | None:
        """Shared skip/defer/web2-block body: mark, release the claim (citation tasks
        only - a web2 task holds none), run the batch-release check - one transaction.
        ``require_kind`` refuses a task of the wrong kind as not-found, so a
        kind-specific door can never act on the other lane's task."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select t.id, t.kind, t.citation_id, t.web2_id, t.batch_no "
                "from public.operator_session_tasks t "
                "join public.operator_sessions s on s.id = t.session_id "
                "where t.id = %s::uuid and t.session_id = %s::uuid "
                "  and s.operator_id = %s::uuid and s.status = 'active' "
                f"  and t.ui_state in {_NON_TERMINAL_SQL} "
                "for update of t limit 1",
                (task_id, session_id, self._user_id),
            )
            task = cur.fetchone()
            if task is None:
                return None
            if require_kind is not None and str(task.get("kind") or "citation") != require_kind:
                return None
            new_batch: int | None = None
            if rebatch_to_tail:
                cur.execute(
                    "select coalesce(max(batch_no), 1) as tail "
                    "from public.operator_session_tasks where session_id = %s::uuid",
                    (session_id,),
                )
                tail = cur.fetchone()
                new_batch = int(tail["tail"]) + 1 if tail else int(task["batch_no"]) + 1
            cur.execute(
                "update public.operator_session_tasks set "
                "  ui_state = %s, ui_state_at = now(), telemetry = telemetry || %s, "
                "  batch_no = coalesce(%s, batch_no) "
                "where id = %s::uuid",
                (state, Jsonb(patch), new_batch, task_id),
            )
            if release_claim and task.get("citation_id"):
                cur.execute(
                    "update public.citations set "
                    "  claimed_by = null, claimed_at = null, claim_expires_at = null "
                    "where id = %s::uuid and claimed_by = %s::uuid",
                    (str(task["citation_id"]), self._user_id),
                )
            released = self._release_next_batches(cur, session_id)
            return {
                "sessionId": session_id,
                "taskId": task_id,
                "state": state,
                "batchNo": new_batch or int(task["batch_no"]),
                "released": released,
                # For the web2 block door's drift hook (0136): which property this
                # task worked, so the router can deactivate a drifted placement spec.
                "web2Id": str(task["web2_id"]) if task.get("web2_id") else None,
            }

    # --- the transactional batch release ----------------------------------------
    def _release_next_batches(self, cur: Cursor[DictRow], session_id: str) -> int:
        """If the CURRENT batch is fully terminal, release the next - claiming its
        citations and bumping ``current_batch`` - and keep going while released
        batches immediately empty out (every row unclaimable). Runs inside the
        caller's transaction; the session row is locked FOR UPDATE so two terminal
        handlers racing on the last item serialize rather than double-release.

        A next-batch citation someone ELSE now holds (claimed ad hoc while it sat
        pending) is marked terminal ``skipped`` with a ``claim_conflict`` receipt -
        it must not wedge the batch, and silently working a row another operator
        holds is exactly what the lease exists to prevent. When no batch remains,
        the session closes itself ``completed``."""
        released_total = 0
        while True:
            cur.execute(
                "select current_batch, batch_size, kind from public.operator_sessions "
                "where id = %s::uuid and status = 'active' for update limit 1",
                (session_id,),
            )
            session = cur.fetchone()
            if session is None:
                return released_total
            current = int(session["current_batch"])
            kind = str(session.get("kind") or "citation")
            cur.execute(
                "select count(*) as open_tasks from public.operator_session_tasks "
                "where session_id = %s::uuid and batch_no = %s "
                f"  and ui_state in {_NON_TERMINAL_SQL}",
                (session_id, current),
            )
            row = cur.fetchone()
            if row is None or int(row["open_tasks"]) > 0:
                return released_total
            # The current batch is done. Find the next batch that still has work.
            cur.execute(
                "select min(batch_no) as next_batch from public.operator_session_tasks "
                "where session_id = %s::uuid and batch_no > %s "
                "  and ui_state in ('pending', 'deferred')",
                (session_id, current),
            )
            nxt = cur.fetchone()
            next_batch = nxt.get("next_batch") if nxt else None
            if next_batch is None:
                cur.execute(
                    "update public.operator_sessions set "
                    "  status = 'completed', closed_at = now(), updated_at = now() "
                    "where id = %s::uuid",
                    (session_id,),
                )
                return released_total
            if kind == "web2_placement":
                # A property may have left the placement pool while its task sat
                # pending (a lead re-routed it, or someone completed it outside this
                # session) - such a task is conflict-skipped with a receipt, exactly
                # as a re-claimed citation is, so it can never wedge the batch.
                cur.execute(
                    "select t.id as task_id, w.id as wid, "
                    "       (w.status = 'publishing' "
                    "        and w.publish_method = 'extension') as placeable "
                    "from public.operator_session_tasks t "
                    "join public.web2_properties w on w.id = t.web2_id "
                    "where t.session_id = %s::uuid and t.batch_no = %s "
                    "  and t.ui_state in ('pending', 'deferred') "
                    "for update of w skip locked",
                    (session_id, int(next_batch)),
                )
                rows = cur.fetchall()
                claimable = [str(r["wid"]) for r in rows if r["placeable"]]
                conflicted = [str(r["task_id"]) for r in rows if not r["placeable"]]
                if conflicted:
                    cur.execute(
                        "update public.operator_session_tasks set "
                        "  ui_state = 'skipped', ui_state_at = now(), "
                        "  telemetry = telemetry || %s "
                        "where id = any(%s::uuid[])",
                        (
                            Jsonb({"skip_reason": "state_conflict",
                                   "skipped_at": datetime.now(UTC).isoformat()}),
                            conflicted,
                        ),
                    )
                self._release_web2_tasks(
                    cur, session_id, batch_no=int(next_batch), web2_ids=claimable
                )
            else:
                # Lock the batch's citations; SKIP LOCKED so a row mid-claim elsewhere
                # neither blocks nor deadlocks this release.
                cur.execute(
                    "select t.id as task_id, c.id as cid, "
                    "       (c.claimed_by is null or c.claim_expires_at < now() "
                    "        or c.claimed_by = %s::uuid) as claimable "
                    "from public.operator_session_tasks t "
                    "join public.citations c on c.id = t.citation_id "
                    "where t.session_id = %s::uuid and t.batch_no = %s "
                    "  and t.ui_state in ('pending', 'deferred') "
                    "for update of c skip locked",
                    (self._user_id, session_id, int(next_batch)),
                )
                rows = cur.fetchall()
                claimable = [str(r["cid"]) for r in rows if r["claimable"]]
                conflicted = [str(r["task_id"]) for r in rows if not r["claimable"]]
                if conflicted:
                    cur.execute(
                        "update public.operator_session_tasks set "
                        "  ui_state = 'skipped', ui_state_at = now(), "
                        "  telemetry = telemetry || %s "
                        "where id = any(%s::uuid[])",
                        (
                            Jsonb({"skip_reason": "claim_conflict",
                                   "skipped_at": datetime.now(UTC).isoformat()}),
                            conflicted,
                        ),
                    )
                self._claim_and_release(
                    cur, session_id, batch_no=int(next_batch), citation_ids=claimable
                )
            cur.execute(
                "update public.operator_sessions set current_batch = %s, updated_at = now() "
                "where id = %s::uuid",
                (int(next_batch), session_id),
            )
            released_total += len(claimable)
            if claimable:
                return released_total
            # Everything in that batch conflicted away - keep walking forward.

    # --- the client selector's cheap counts read --------------------------------
    def client_work_counts(self) -> list[dict[str, Any]]:
        """Per-client counts of session-able work: queue rows waiting for a human,
        verify-first discoveries, candidate gaps - and (0136) parked extension-lane
        placements awaiting a web2_placement session. Cheap on purpose - the
        extension's client selector polls this instead of running a full gap
        analysis per client."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select c.client_id, max(c.client_name) as client_name, "
                "  count(*) filter (where c.submit_status = 'ready_for_human' "
                "    and (c.claimed_by is null or c.claim_expires_at < now())) as ready, "
                "  count(*) filter (where coalesce(c.submit_status::text, 'not_started') "
                "      = 'not_started' and c.live_url = '' "
                "    and c.evidence_level = 'uncertain') as verify_first, "
                "  count(*) filter (where coalesce(c.submit_status::text, 'not_started') "
                "      = 'not_started' and c.live_url = '' "
                "    and c.evidence_level = 'no_evidence') as candidate_gaps "
                "from public.citations c "
                "left join public.directories d on d.id = c.directory_id "
                "where coalesce(d.route, 'C') <> 'F' and c.client_id is not null "
                "group by c.client_id "
                "order by 2",
            )
            rows = cur.fetchall()
            # Parked placements. A property already inside an active session's
            # non-terminal task still COUNTS - the count answers "is there placement
            # work for this client?", and the selection query is what enforces
            # exclusivity at creation time.
            cur.execute(
                "select w.client_id, max(w.client_name) as client_name, "
                "  count(*) as web2_placements "
                "from public.web2_properties w "
                "where w.status = 'publishing' and w.publish_method = 'extension' "
                "  and w.client_id is not null "
                "group by w.client_id",
            )
            web2_rows = cur.fetchall()
        merged: dict[str, dict[str, Any]] = {str(r["client_id"]): dict(r) for r in rows}
        for r in web2_rows:
            key = str(r["client_id"])
            entry = merged.setdefault(
                key,
                {"client_id": r["client_id"], "client_name": r.get("client_name") or ""},
            )
            entry["web2_placements"] = int(r.get("web2_placements") or 0)
        out = sorted(merged.values(), key=lambda r: str(r.get("client_name") or ""))
        return [
            r for r in out
            if int(r.get("ready") or 0) + int(r.get("verify_first") or 0)
            + int(r.get("candidate_gaps") or 0) + int(r.get("web2_placements") or 0) > 0
        ]


def get_operator_sessions_repo(user: AnyQueueScopeDep) -> OperatorSessionsRepo:
    """Scoped to whoever is calling - dashboard session OR extension. The floor here
    is ANY queue scope (0136: a web2-only token must reach its own web2 sessions),
    which is identity + containment only - every session route declares its OWN
    verb-and-kind-correct floor FIRST in its signature, so that stricter guard runs
    before this dependency ever touches the DB."""
    return OperatorSessionsRepo(user.id)


def get_operator_sessions_repo_write(user: OperatorOrUserWriteDep) -> OperatorSessionsRepo:
    """The sessions repo as used INSIDE the citation queue's mutation routes (the
    claim refusal check + the post-terminal hooks on complete/blocked). Floored on
    `citation_queue:write` and bound to the same `resolve_operator_write` object as
    those routes' own guards, so the credential resolves once per request and a
    wrong-verb token is a deterministic 401 before any epoch/DB work."""
    return OperatorSessionsRepo(user.id)


OperatorSessionsRepoDep = Annotated[OperatorSessionsRepo, Depends(get_operator_sessions_repo)]
OperatorSessionsRepoWriteDep = Annotated[
    OperatorSessionsRepo, Depends(get_operator_sessions_repo_write)
]
