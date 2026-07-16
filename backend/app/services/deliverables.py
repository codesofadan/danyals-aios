"""Deliverable emit: the producers' write path into ``client_deliverables`` (0032).

Every producing worker (audit / content / reports / offpage) calls
:func:`emit_deliverable` at its completion point to publish a downloadable
deliverable to the client's Reports library. It is BEST-EFFORT - wrapped in
try/except, it logs a warning and NEVER raises, so a deliverable-emit hiccup can
never fail the job it is recording (exactly like ``record_activity``). It writes
on the ``privileged_connection`` (service_role, BYPASSRLS) because the producers
run server-side and the deliverables table has no client write path.

The client never sees ``client_id`` / ``artifact_key`` / ``media_type`` /
``source_*`` (the ``portal_deliverables`` view hides them); the download endpoint
resolves the artifact server-side.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from app.db.database import privileged_connection
from app.logging_setup import get_logger

logger = get_logger("app.deliverables")

# The columns emit writes (client_name is a caller snapshot for logging only - the
# deliverables table carries no client identity, and the view exposes none).
_COLUMNS: tuple[str, ...] = (
    "client_id", "title", "kind", "icon", "period", "issued_at", "size_label",
    "status", "requires", "artifact_key", "media_type", "source_kind", "source_id",
)


def emit_deliverable(
    *,
    client_id: str,
    client_name: str,
    title: str,
    kind: str,
    requires: str,
    source_kind: str,
    source_id: str | None,
    icon: str,
    artifact_key: str | None = None,
    media_type: str = "application/pdf",
    period: str = "",
    size_label: str = "",
    status: str = "ready",
) -> None:
    """Publish ONE deliverable to a client's Reports library. Best-effort: never
    raises. ``issued_at`` is stamped now for a ``ready`` deliverable and left NULL
    while ``generating``. ``client_id`` is server-pinned by the caller (the producing
    worker already owns the tenant); ``requires`` is the grant key that gates its
    visibility."""
    issued_at = datetime.now(UTC) if status == "ready" else None
    row: dict[str, Any] = {
        "client_id": client_id,
        "title": title,
        "kind": kind,
        "icon": icon,
        "period": period,
        "issued_at": issued_at,
        "size_label": size_label,
        "status": status,
        "requires": requires,
        "artifact_key": artifact_key,
        "media_type": media_type,
        "source_kind": source_kind,
        "source_id": source_id,
    }
    try:
        stmt = sql.SQL(
            "insert into public.client_deliverables ({cols}) values ({vals})"
        ).format(
            cols=sql.SQL(", ").join(sql.Identifier(c) for c in _COLUMNS),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(_COLUMNS)),
        )
        with privileged_connection() as cur:
            cur.execute(stmt, [row[c] for c in _COLUMNS])
    except Exception:
        # A missing/unreachable privileged pool (or any write failure) must never
        # break the job that produced the deliverable.
        logger.warning(
            "emit_deliverable_failed", kind=kind, requires=requires, client=client_name
        )


def backfill_audit_deliverables() -> int:
    """Insert an ``Audit`` deliverable for every existing completed audit that has a
    stored PDF but no deliverable yet. Idempotent (skips audits already backfilled by
    ``source_id``). Returns the number of deliverables created. Server-only + best
    effort at the row level; a single bad row never aborts the pass."""
    created = 0
    try:
        with privileged_connection() as cur:
            cur.execute(
                "select a.id, a.client_id, a.client_name, a.url, a.pdf_path, a.finished_at "
                "from public.audits a "
                "where a.pdf_path is not null and a.client_id is not null "
                "and not exists ("
                "  select 1 from public.client_deliverables d "
                "  where d.source_kind = 'audit' and d.source_id = a.id"
                ")"
            )
            rows = cur.fetchall()
    except Exception:
        logger.warning("backfill_audit_deliverables_query_failed")
        return 0

    for row in rows:
        period = _period_label(row.get("finished_at"))
        emit_deliverable(
            client_id=str(row["client_id"]),
            client_name=row.get("client_name", ""),
            title="Technical SEO Audit",
            kind="Audit",
            requires="audit_scores",
            source_kind="audit",
            source_id=str(row["id"]),
            icon="fact_check",
            artifact_key=row.get("pdf_path"),
            media_type="application/pdf",
            period=period,
            status="ready",
        )
        created += 1
    return created


def _period_label(value: Any) -> str:
    """Humanize a timestamp to a "July 2026" period label (empty if unset)."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%B %Y")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%B %Y")
    except ValueError:
        return ""
