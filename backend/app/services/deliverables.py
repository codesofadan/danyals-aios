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
    status: str = "pending_review",
) -> None:
    """Queue ONE deliverable for a client's Reports library. Best-effort: never
    raises. ``client_id`` is server-pinned by the caller (the producing worker already
    owns the tenant); ``requires`` is the grant key that gates its visibility.

    THE DEFAULT IS `pending_review`, NOT `ready`. Every producer used to write straight
    to `ready`, and `portal_deliverables` shows any ready row whose grant key the
    client holds - so a document was in front of the client the moment a job finished,
    with no review and no way to hold one back short of revoking the whole report grant
    (which would remove every other document of that kind at the same time).

    A staff member releases it with ``POST /deliverables/{id}/publish``. The gate is in
    the VIEW (0116), so a row awaiting review is never selected for a client by any
    route, present or future.

    ``issued_at`` is stamped when a deliverable becomes `ready` - at publish for the
    normal path - and left NULL while `pending_review` or `generating`, so "when did
    this client get this" is the release date rather than the production date."""
    # A "ready" deliverable is an OFFER OF A FILE. The client's Reports library renders
    # View and Download for it, and `GET /portal/deliverables/{id}/download` resolves
    # `artifact_key` -> a path; with no key it raises 404. So a ready row without an
    # artifact is a download button that cannot work, shown to a paying client.
    #
    # Two producers did exactly that: the Google-Sheets workbook sync ("Monthly SEO
    # Report") and the off-page worker ("Backlink Profile") both emitted with the
    # default `artifact_key=None` and the default `status="ready"`. Neither renders a
    # PDF at all, so `generating` would be no more honest - it reads "In progress"
    # forever for a file nobody is producing.
    #
    # Refusing the write is the honest outcome and matches the portal rule that it must
    # never offer an artefact it has not verified exists. Best-effort like the rest of
    # this function: it logs and returns rather than raising into the producing job.
    #
    # The guard covers `pending_review` too, now that it is the default. Such a row is
    # invisible to the client, so it cannot break a download - but it CANNOT BE
    # PUBLISHED either (the publish route refuses a deliverable with no file, for the
    # reason above), so writing one only fills the review queue with rows no one can
    # ever act on. A queue of permanently unactionable items is its own dishonesty.
    # `generating` remains exempt: it is an explicit promise that a file is coming.
    if status != "generating" and not artifact_key:
        logger.warning(
            "emit_deliverable_skipped_no_artifact",
            title=title, kind=kind, requires=requires, client=client_name,
        )
        return

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
            # No status override: a backfilled document has never been in front of
            # this client (the row did not exist), so it enters review like any other
            # new emission rather than appearing unannounced.
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
