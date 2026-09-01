"""Admin view of the PUBLIC free-audit leads (the landing-page funnel inbox).

The unauthenticated funnel in :mod:`app.routers.public` captures one free audit
per email into ``public.public_audits``. Those rows are LEADS - an email + a
target URL + the audit outcome - and were previously write-only (no staff could
see them). This router is the staff-facing read surface over that same table.

Security posture:

* STAFF-ONLY. Every route is gated by ``require_perm("view_reports")`` - held by
  all six staff roles and by NO portal ``client`` (mirrors the staff ``GET
  /audits*`` convention). The read runs on ``rls_connection(user.id)``; the
  ``public_audits_select`` / ``is_staff()`` policy authorizes it, so a leaked
  portal credential (role ``client``) sees zero rows even here.
* ``public.public_audits`` has NO ``client_id`` and no path to any tenant table,
  so the email/error columns curated OUT of the public token report are safe to
  show a staff operator (they are lead data, not another tenant's data).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.auth import CurrentUser, require_perm
from app.core.pagination import PageDep
from app.db.database import DatabaseNotConfiguredError, rls_connection
from app.logging_setup import get_logger
from app.routers.public import PublicArtifactStoreDep
from app.services.audit_artifacts import LocalArtifactStore, honest_artifact_flags

router = APIRouter(prefix="/admin/public-audits", tags=["admin"])
logger = get_logger("app.admin_public_audits")

# All six staff roles hold view_reports; the portal client role does not.
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]

_DB_NOT_CONFIGURED = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured"
)


class PublicAuditLead(BaseModel):
    """One free-audit lead, with the FULL info a staff operator needs.

    Unlike the tokenized public report (which is curated down to score/status),
    this staff view exposes the captured ``email``, the ``source``, the stored
    ``error`` on a failure, and the ``report_token`` so the operator can open the
    exact report the visitor sees. No tenant data is reachable from this table.
    """

    id: str
    email: str
    url: str
    status: str
    score: int | None
    source: str
    report_token: str
    has_pdf: bool
    has_report: bool
    run_uuid: str | None
    error: str | None
    created_at: str
    updated_at: str | None

    @classmethod
    def from_row(
        cls, row: dict[str, Any], store: LocalArtifactStore | None = None
    ) -> PublicAuditLead:
        def _iso(value: Any) -> str | None:
            return value.isoformat() if isinstance(value, datetime) else (str(value) if value else None)

        created = _iso(row.get("created_at")) or ""
        # NOT `bool(row["pdf_path"])`. A public audit reaches status "done" even when
        # the artifact copy never happened - `audit_artifact_dir` is unset by default,
        # so `_store_artifacts` returns (None, None) and the run still completes. The
        # columns then say a report exists while the disk says otherwise, and the
        # operator gets a download button that 404s. Ask the store.
        pdf_ok, json_ok = honest_artifact_flags(store, row)
        return cls(
            id=str(row["id"]),
            email=str(row["email"]),
            url=str(row["url"]),
            status=str(row["status"]),
            score=row.get("score"),
            source=str(row.get("source") or "landing"),
            report_token=str(row["report_token"]),
            has_pdf=pdf_ok,
            has_report=json_ok,
            run_uuid=(str(row["run_uuid"]) if row.get("run_uuid") else None),
            error=(str(row["error"]) if row.get("error") else None),
            created_at=created,
            updated_at=_iso(row.get("updated_at")),
        )


def _fetch_leads(user_id: str, *, limit: int, offset: int) -> list[dict[str, Any]]:
    """Read the free-audit leads, newest first, via the RLS-scoped staff path.

    The ``is_staff()`` SELECT policy on ``public.public_audits`` authorizes this;
    a portal client on the same seam sees nothing. Blocking (psycopg) - the caller
    offloads with ``to_thread``.
    """
    with rls_connection(user_id) as cur:
        cur.execute(
            "select * from public.public_audits order by created_at desc limit %s offset %s",
            (limit, offset),
        )
        return cur.fetchall()


def _fetch_lead_by_token(user_id: str, report_token: str) -> dict[str, Any] | None:
    """Read ONE free-audit lead by its report token, on the same RLS-scoped staff path.

    ``report_token`` is ``not null unique`` (0015), so this is an index scan.
    """
    with rls_connection(user_id) as cur:
        cur.execute(
            "select * from public.public_audits where report_token = %s limit 1",
            (report_token,),
        )
        return cur.fetchone()


@router.get("", response_model=list[PublicAuditLead])
async def list_public_audits(
    page: PageDep, user: ViewReports, store: PublicArtifactStoreDep
) -> list[PublicAuditLead]:
    """List the free-audit leads captured by the public funnel (staff-only)."""
    try:
        rows = await asyncio.to_thread(_fetch_leads, user.id, limit=page.limit, offset=page.offset)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    return [PublicAuditLead.from_row(r, store) for r in rows]


@router.get("/{report_token}", response_model=PublicAuditLead)
async def get_public_audit(
    report_token: str, user: ViewReports, store: PublicArtifactStoreDep
) -> PublicAuditLead:
    """One free-audit lead by its report token (staff-only).

    WHY THIS EXISTS. The lead detail page used to find its lead by scanning the
    paginated list, so a link to any lead outside the newest page resolved to
    "not found" - a shared link silently rotted as the funnel filled up. The
    token is the lead's identity; reading by it is the fix.

    Same dep, same seam and same policy as the list, so a portal client still
    sees nothing here.
    """
    try:
        row = await asyncio.to_thread(_fetch_lead_by_token, user.id, report_token)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return PublicAuditLead.from_row(row, store)
