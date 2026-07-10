"""Read-side helpers for the report subcommand and dashboards."""

from __future__ import annotations

import sqlite3
from typing import Any


def get_run_by_uuid(conn: sqlite3.Connection, run_uuid: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM audit_runs WHERE run_uuid = ?", (run_uuid,)
    ).fetchone()
    return dict(row) if row else None


def get_recent_runs(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM audit_runs ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_runs_for_domain(
    conn: sqlite3.Connection, domain: str, *, limit: int = 20
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM audit_runs WHERE domain = ? ORDER BY started_at DESC LIMIT ?",
        (domain, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_previous_succeeded_run(
    conn: sqlite3.Connection, domain: str, *, before_run_uuid: str | None = None
) -> dict[str, Any] | None:
    """Return the most recent succeeded run for `domain` (optionally before
    `before_run_uuid`). Used by `audit-track` to pick the comparison baseline."""
    if before_run_uuid:
        anchor = conn.execute(
            "SELECT started_at FROM audit_runs WHERE run_uuid = ?", (before_run_uuid,)
        ).fetchone()
        if anchor is None:
            return None
        row = conn.execute(
            """SELECT * FROM audit_runs
               WHERE domain = ? AND status = 'succeeded' AND started_at < ?
               ORDER BY started_at DESC LIMIT 1""",
            (domain, anchor["started_at"]),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT * FROM audit_runs
               WHERE domain = ? AND status = 'succeeded'
               ORDER BY started_at DESC LIMIT 1""",
            (domain,),
        ).fetchone()
    return dict(row) if row else None


def get_finding_by_id(conn: sqlite3.Connection, finding_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
    return dict(row) if row else None


def find_finding(
    conn: sqlite3.Connection,
    *,
    run_uuid: str | None = None,
    check_id: str | None = None,
) -> list[dict[str, Any]]:
    """Locate findings by run_uuid + check_id. Either may be None for broader
    search. Used by `audit-fix` to surface a specific finding's remediation."""
    sql = "SELECT f.* FROM findings f"
    where: list[str] = []
    params: list[Any] = []
    if run_uuid:
        sql += " JOIN audit_runs r ON r.id = f.run_id"
        where.append("r.run_uuid = ?")
        params.append(run_uuid)
    if check_id:
        where.append("f.check_id = ?")
        params.append(check_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY f.id DESC LIMIT 50"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
