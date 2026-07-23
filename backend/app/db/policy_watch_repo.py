"""Privileged (service_role) write surface for the Policy-Radar change-detection
WATCHER (0019 + the 0050 seed).

The watcher runs on ``privileged_connection`` (role ``service_role``, BYPASSRLS): it
is the ONLY production writer of ``policy_sources.last_hash`` / ``change_events`` /
``kb_entries`` / ``recommendations``, so it BYPASSes the human RLS policies (0019) by
design (those govern the staff read + the lead confirm/apply surface). This repo is
that write surface; the RLS-scoped READ surface (staff read, lead transitions,
baseline merge) lives in ``app/db/policy_repo.py`` and is untouched here.

SQL rule (same as the rest of the codebase): every VALUE is a bound param; the only
dynamic SQL is the server-built column list of the KB / recommendation inserts, quoted
via ``psycopg.sql.Identifier`` (mirrors ``policy_repo.insert_overlay``). psycopg3 sends
Python ``str`` as an unknown-typed param, so a text value resolves cleanly into an enum
column (severity / category / region / target_module / status) without a hand cast.
"""

from __future__ import annotations

from typing import Any, cast

from psycopg import sql

from app.db.database import privileged_connection

_Rows = list[dict[str, Any]]


def _bump_version(current: str | None) -> str:
    """The next ``vN`` label after ``current`` ('v1' -> 'v2'); 'v2' on a bad value."""
    text = str(current or "v1").strip()
    if text.startswith("v") and text[1:].isdigit():
        return f"v{int(text[1:]) + 1}"
    return "v2"


class PolicyWatchRepo:
    """The watcher's privileged write surface over the four Policy-Radar tables."""

    # --- the source sweep --------------------------------------------------- #
    def claim_due_sources(self, limit: int) -> _Rows:
        """Claim up to ``limit`` sources to poll, least-recently-checked first.

        ``FOR UPDATE SKIP LOCKED`` means two concurrent beat ticks never grab the same
        source (mirrors ``context_repo.claim_due_dirty``); the row lock releases when
        this short claim transaction commits, and the per-source ``mark_unchanged`` /
        ``capture_baseline`` / ``record_change`` writes then run in their own
        transactions (each polls the network, so the claim must not hold locks across
        the fetch). ``last_checked`` NULLs (never polled) sort first, so a fresh source
        is picked up on the next tick. Returns ``id, name, url, last_hash`` (the anchor).
        """
        with privileged_connection() as cur:
            cur.execute(
                "select id, name, url, last_hash from public.policy_sources "
                "order by last_checked asc nulls first "
                "for update skip locked "
                "limit %s",
                (limit,),
            )
            return cur.fetchall()

    def mark_unchanged(self, source_id: str) -> None:
        """Record a completed poll that found NO change: touch ``last_checked`` and keep
        ``status='ok'``. ``last_hash`` is left untouched (still the diff anchor)."""
        with privileged_connection() as cur:
            cur.execute(
                "update public.policy_sources "
                "set last_checked = now(), status = 'ok' where id = %s",
                (source_id,),
            )

    def capture_baseline(self, source_id: str, new_hash: str) -> None:
        """Record the FIRST poll of a source (empty ``last_hash``): store the baseline
        hash and keep ``status='ok'`` WITHOUT emitting a change_event.

        Without this, a source seeded with an empty ``last_hash`` (0050) would diff as
        'changed' on its very first poll and flag every source at once; the baseline
        capture makes the first observation the anchor, so only a LATER diff is a real,
        analysable change."""
        with privileged_connection() as cur:
            cur.execute(
                "update public.policy_sources "
                "set last_hash = %s, last_checked = now(), status = 'ok' where id = %s",
                (new_hash, source_id),
            )

    def record_change(
        self,
        source_id: str,
        name: str,
        new_hash: str,
        summary: str,
        severity: str,
        diff_ref: str,
    ) -> str:
        """Persist a detected change ATOMICALLY and return the new change_event id.

        In ONE privileged transaction: advance the source's ``last_hash`` to the new
        anchor + flip ``status='change'`` + touch ``last_checked``, AND append the
        ``change_events`` ledger row. ``source_name`` is a display snapshot so
        ``source_id`` never has to surface; ``diff_ref`` is the content fingerprint the
        change points at."""
        with privileged_connection() as cur:
            cur.execute(
                "update public.policy_sources "
                "set last_hash = %s, status = 'change', last_checked = now() where id = %s",
                (new_hash, source_id),
            )
            cur.execute(
                "insert into public.change_events "
                "(source_id, source_name, summary, severity, diff_ref) "
                "values (%s, %s, %s, %s::public.policy_severity, %s) returning id",
                (source_id, name, summary, severity, diff_ref),
            )
            row = cur.fetchone()
        return str(cast("dict[str, Any]", row)["id"])

    # --- the KB + recommendation the analysis produces ---------------------- #
    def insert_kb_entry(self, row: dict[str, Any]) -> dict[str, Any]:
        """Insert one ``kb_entries`` row (DEDUPED by ``hash``) and return the persisted
        row.

        DEDUPE / VERSIONING (0019:111-117): if a KB entry with the same ``hash`` already
        exists, the source is re-stating a finding we already hold, so we BUMP that
        row's ``version`` (v1 -> v2 ...) and re-stamp ``detected_at`` instead of
        inserting a duplicate. Otherwise a fresh row is inserted. The column list is
        server-built + quoted (``sql.Identifier``); every value is a bound param."""
        kb_hash = str(row.get("hash") or "")
        with privileged_connection() as cur:
            if kb_hash:
                cur.execute(
                    "select id, version from public.kb_entries "
                    "where hash = %s order by created_at desc limit 1",
                    (kb_hash,),
                )
                existing = cur.fetchone()
                if existing is not None:
                    cur.execute(
                        "update public.kb_entries set version = %s, detected_at = now() "
                        "where id = %s returning *",
                        (_bump_version(existing.get("version")), existing["id"]),
                    )
                    return cast("dict[str, Any]", cur.fetchone())
            cols = list(row.keys())
            stmt = sql.SQL(
                "insert into public.kb_entries ({cols}) values ({vals}) returning *"
            ).format(
                cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
                vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
            )
            cur.execute(stmt, list(row.values()))
            return cast("dict[str, Any]", cur.fetchone())

    def insert_recommendation(self, row: dict[str, Any]) -> dict[str, Any]:
        """Insert one ``recommendations`` row (the Command Center action) and return it.
        Column list server-built + quoted; every value bound. ``kb_ref`` is the public
        ``kb-live-*`` snapshot; ``kb_entry_id`` is the internal FK back to the KB entry.
        """
        cols = list(row.keys())
        stmt = sql.SQL(
            "insert into public.recommendations ({cols}) values ({vals}) returning *"
        ).format(
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with privileged_connection() as cur:
            cur.execute(stmt, list(row.values()))
            return cast("dict[str, Any]", cur.fetchone())

    def set_triggered_job(self, change_event_id: str, kb_job: str) -> None:
        """Stamp the change_event with the KB/research job it kicked off (the 0019
        ``triggered_job`` hook), closing the change -> KB link."""
        with privileged_connection() as cur:
            cur.execute(
                "update public.change_events set triggered_job = %s where id = %s",
                (kb_job, change_event_id),
            )


def service_policy_watch_repo() -> PolicyWatchRepo:
    """The privileged repo the watcher worker uses (service_role, BYPASSRLS)."""
    return PolicyWatchRepo()
