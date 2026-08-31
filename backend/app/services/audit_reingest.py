"""Rebuild a completed audit's stored findings from the artifacts it left behind.

WHY THIS EXISTS. An audit's report and its queryable findings are produced by two
different steps. The engine writes the report (``report.html`` / the PDF /
``findings.json``) and the audit is marked ``done``; a SEPARATE, deliberately
non-fatal transform then loads those artifacts into ``audit_pages`` /
``audit_findings`` / ``audit_finding_instances`` / ``audit_rollups`` and builds the
workbook and the platform report on top of them.

Non-fatal was the right call - losing a finished client deliverable because a
supplementary transform failed would be strictly worse - but it left no way back.
An audit whose ingest failed, or that ran before the altitude tables existed, is
green in the list and a dead end when opened: "No altitude data for this audit."
The report exists, the artifacts are still on disk, and nothing could turn one into
the other. That is the gap the QA session found from the report side.

So: one canonical stored result, rebuildable from the artifacts at any time. This is
the same code path the worker runs, called against a stored ``artifact_dir`` instead
of a fresh run, which is what makes it a repair rather than a second implementation
that can drift.

It does NOT re-run the audit and it spends nothing: no engine invocation, no
provider call. Failure to find the artifacts is reported honestly rather than
producing an empty rebuild that looks like a success.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.logging_setup import get_logger
from app.services import audit_ingest, audit_report, audit_workbook
from app.services.audit_artifacts import LocalArtifactStore

logger = get_logger("app.services.audit_reingest")


class ReingestUnavailableError(RuntimeError):
    """The audit cannot be rebuilt, with the reason a caller can show a human."""


@dataclass(frozen=True, slots=True)
class ReingestResult:
    pages: int
    findings: int
    instances: int
    roadmap_items: int
    workbook_built: bool
    report_built: bool
    notes: list[str]


def _utc_label(dt: Any) -> str:
    """The run's own finish date, for the rebuilt documents' "generated" line.

    Deliberately the STORED timestamp rather than now(): the workbook describes a
    run that happened, and stamping today's date on a rebuild of a month-old audit
    would misdate the evidence.
    """
    try:
        return str(dt.strftime("%d %B %Y"))
    except Exception:
        return ""


def reingest_audit(
    row: dict[str, Any],
    *,
    artifacts: LocalArtifactStore | None,
) -> ReingestResult:
    """Rebuild one audit's rows, roadmap, workbook and platform report.

    ``row`` is the ``audits`` row. Raises :class:`ReingestUnavailableError` when there is
    nothing to rebuild FROM - which is a real answer ("this run's artifacts are
    gone"), not a failure to be retried.
    """
    audit_id = str(row["id"])
    status = str(row.get("status") or "")
    if status != "done":
        raise ReingestUnavailableError(
            f"this audit is {status or 'unfinished'}; only a completed run has "
            "artifacts to rebuild from"
        )

    artifact_dir = str(row.get("artifact_dir") or "")
    if not artifact_dir:
        raise ReingestUnavailableError(
            "this run recorded no artifact directory, so there is nothing to rebuild "
            "from. Run the audit again."
        )
    if not Path(artifact_dir).is_dir():
        raise ReingestUnavailableError(
            "this run's artifacts are no longer on disk, so its findings cannot be "
            "rebuilt. The stored report is still available; run the audit again to "
            "restore the findings."
        )

    tier_label = "Paid" if str(row.get("tier") or "") == "paid" else "Free"
    client_id = str(row["client_id"]) if row.get("client_id") else None
    notes: list[str] = []

    ingested = audit_ingest.ingest(
        audit_id=audit_id,
        client_id=client_id,
        artifact_dir=artifact_dir,
        site_url=str(row.get("url") or ""),
        run_uuid=str(row.get("run_uuid") or ""),
        tier=tier_label.lower(),
        types=list(row.get("types") or []),
    )
    logger.info(
        "audit_reingest_rows",
        audit_id=audit_id,
        pages=ingested.pages,
        findings=ingested.findings,
        instances=ingested.instances,
    )

    # The roadmap and the workbook are each built from the rows above, and each is
    # independently non-fatal: a rebuild that produced findings but no workbook is a
    # better outcome than one that produced nothing, and the caller is told which.
    roadmap_items = 0
    try:
        planned = audit_ingest.store_roadmap(audit_id=audit_id, client_id=client_id)
        roadmap_items = int(planned.get("items", 0) or 0)
    except Exception as exc:
        notes.append(f"the roadmap could not be rebuilt ({type(exc).__name__})")
        logger.warning("audit_reingest_roadmap_failed", audit_id=audit_id, error=str(exc))

    workbook_built = False
    report_built = False
    if artifacts is not None:
        out_dir = artifacts.sheets_dir(audit_id)
        meta = {
            "url": str(row.get("url") or ""),
            "client_name": str(row.get("client_name") or ""),
            "tier": tier_label,
        }
        try:
            audit_workbook.build(
                audit_id=audit_id,
                out_dir=out_dir,
                artifact_dir=artifact_dir,
                meta={**meta, "generated_at": _utc_label(row.get("finished_at"))},
            )
            workbook_built = True
        except Exception as exc:
            notes.append(f"the workbook could not be rebuilt ({type(exc).__name__})")
            logger.warning("audit_reingest_workbook_failed", audit_id=audit_id, error=str(exc))
        try:
            audit_report.build(
                audit_id=audit_id,
                out_dir=out_dir,
                meta={**meta, "generated_at": _utc_label(row.get("finished_at"))},
            )
            report_built = True
        except Exception as exc:
            notes.append(f"the client report could not be rebuilt ({type(exc).__name__})")
            logger.warning("audit_reingest_report_failed", audit_id=audit_id, error=str(exc))
    else:
        notes.append("no local artifact store is configured, so no workbook was written")

    return ReingestResult(
        pages=ingested.pages,
        findings=ingested.findings,
        instances=ingested.instances,
        roadmap_items=roadmap_items,
        workbook_built=workbook_built,
        report_built=report_built,
        notes=notes,
    )


__all__ = ["ReingestResult", "ReingestUnavailableError", "reingest_audit"]
