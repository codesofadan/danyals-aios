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
    def from_row(cls, row: dict[str, Any]) -> PublicAuditLead:
        def _iso(value: Any) -> str | None:
            return value.isoformat() if isinstance(value, datetime) else (str(value) if value else None)

        created = _iso(row.get("created_at")) or ""
        return cls(
            id=str(row["id"]),
            email=str(row["email"]),
            url=str(row["url"]),
            status=str(row["status"]),
            score=row.get("score"),
            source=str(row.get("source") or "landing"),
            report_token=str(row["report_token"]),
            has_pdf=bool(row.get("pdf_path")),
            has_report=bool(row.get("json_path")),
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


@router.get("", response_model=list[PublicAuditLead])
async def list_public_audits(page: PageDep, user: ViewReports) -> list[PublicAuditLead]:
    """List the free-audit leads captured by the public funnel (staff-only)."""
    try:
        rows = await asyncio.to_thread(_fetch_leads, user.id, limit=page.limit, offset=page.offset)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    return [PublicAuditLead.from_row(r) for r in rows]
