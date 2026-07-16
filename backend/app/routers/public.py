"""The PUBLIC free-audit funnel - the platform's ONLY unauthenticated routes (P6C).

A landing-page visitor (no login) requests ONE free audit per email; the result
is later fetched by an opaque, unguessable ``report_token`` and shown with a
Fiverr upsell link. Security posture (read before touching this file):

* UNAUTHENTICATED yet TENANT-ISOLATED. These routes carry NO ``CurrentUser``
  dependency. They touch exactly one table - ``public.public_audits`` - which has
  NO ``client_id`` and no path to any tenant row. All access goes through the
  privileged (service_role) path, but every query is filtered to a single lead
  (by ``lower(email)`` on write, by ``report_token`` on read), so no tenant data
  (``clients``/``users``/``audits``) is ever reachable from here.
* The ``report_token`` IS the capability: 24 random bytes (hex) minted by the DB.
  Knowing it grants read of exactly that one curated report - nothing else.
* One free audit per email (409 on a repeat), Free tier only (no paid audit
  types), SSRF-guarded target URL, and per-IP rate limited (abuse control).
* The tokenized report is CURATED: it returns the score/status/flags + the upsell
  link, and NEVER the internal id, the email, the stored error, or artifact paths.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from psycopg import errors as psycopg_errors
from pydantic import BaseModel, EmailStr, Field

from app.core.deps import SettingsDep
from app.core.ratelimit import rate_limit_ip
from app.core.security import PrivateAddressError, validate_public_host
from app.db.database import privileged_connection
from app.logging_setup import get_logger
from app.schemas.audits import PAID_AUDIT_TYPES, AuditTypeKey
from app.services.audit_artifacts import LocalArtifactStore, local_store_from_settings
from app.services.cost_gate import GateContext
from app.services.cost_store import PostgresCostStore

logger = get_logger("app.public")

router = APIRouter(prefix="/public", tags=["public"])

# Cost grouping for the funnel-entry $0 log (mirrors the worker's constants).
_COST_FEATURE = "tech_audit"
_COST_PROVIDER = "audit_engine"
_COST_JOB_TYPE = "public_audit"

_DEFAULT_TYPES: tuple[AuditTypeKey, ...] = ("technical", "actionable")

_DUPLICATE_EMAIL = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="A free audit already exists for this email",
)
_REPORT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Report not found"
)
_ARTIFACT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not available"
)


# --------------------------------------------------------------------------- #
# Request / response shapes
# --------------------------------------------------------------------------- #
class PublicAuditCreate(BaseModel):
    """Landing-page payload. ``email`` is validated (``EmailStr``); ``types`` is
    optional and defaults to the non-paid set - any paid type is rejected."""

    email: EmailStr
    url: str = Field(min_length=1, max_length=2048)
    types: list[AuditTypeKey] = Field(default_factory=lambda: list(_DEFAULT_TYPES))

    def paid_types(self) -> list[str]:
        return [t for t in self.types if t in PAID_AUDIT_TYPES]


class PublicAuditCreated(BaseModel):
    """201 response: the capability token + initial status. NOT the internal id."""

    report_token: str
    status: str


class PublicReport(BaseModel):
    """The CURATED public report. No internal id, no email, no error, no paths."""

    status: str
    score: int | None
    scores: dict[str, Any]
    has_pdf: bool
    has_report: bool
    url: str
    when: str | None
    fiverr_url: str


# --------------------------------------------------------------------------- #
# Data gateway (privileged path, filtered to ONE lead per call)
# --------------------------------------------------------------------------- #
class PublicAuditsGateway(Protocol):
    """The narrow DB seam the public routes need (server-side, single-row scoped)."""

    def find_by_email(self, email: str) -> dict[str, Any] | None: ...
    def insert(self, email: str, url: str, source: str) -> dict[str, Any]: ...
    def get_by_token(self, report_token: str) -> dict[str, Any] | None: ...


class PrivilegedPublicAuditsGateway:
    """Concrete gateway over ``privileged_connection`` (service_role, BYPASSRLS).

    Every method is filtered to a single lead - by ``lower(email)`` or by
    ``report_token`` - so no scan across leads (and never any tenant table) is
    reachable. Blocking (psycopg is sync); callers offload with ``to_thread``.
    """

    def find_by_email(self, email: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute(
                "select id from public.public_audits where lower(email) = lower(%s) limit 1",
                (email,),
            )
            return cur.fetchone()

    def insert(self, email: str, url: str, source: str) -> dict[str, Any]:
        with privileged_connection() as cur:
            cur.execute(
                """
                insert into public.public_audits (email, url, source)
                values (%s, %s, %s)
                returning id, report_token, status
                """,
                (email, url, source),
            )
            row = cur.fetchone()
            assert row is not None  # RETURNING on a successful insert always yields a row
            return row

    def get_by_token(self, report_token: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute(
                "select * from public.public_audits where report_token = %s limit 1",
                (report_token,),
            )
            return cur.fetchone()


def get_public_gateway() -> PublicAuditsGateway:
    """Dependency: the privileged public-audits gateway (overridable in tests)."""
    return PrivilegedPublicAuditsGateway()


PublicGatewayDep = Annotated[PublicAuditsGateway, Depends(get_public_gateway)]


def get_public_audit_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the public-audit worker (overridable in tests).

    The task is imported lazily so the API process never pulls in Celery modules
    just to import this router.
    """

    def _enqueue(public_audit_id: str) -> None:
        from workers.tasks.audit import run_public_audit_job

        run_public_audit_job.delay(public_audit_id)

    return _enqueue


PublicEnqueuerDep = Annotated[Callable[[str], None], Depends(get_public_audit_enqueuer)]


def get_public_cost_logger() -> Callable[[str], None]:
    """Dependency: log the funnel-entry $0 cost (Free) via the Part-2 cost path.

    Public runs never spend, but the funnel entry is still recorded at $0 so the
    money-dial ledger accounts for every audit the platform initiates. Overridable
    in tests (the default writes through the privileged cost store).
    """

    def _log(public_audit_id: str) -> None:
        ctx = GateContext(
            feature_key=_COST_FEATURE,
            client_id=None,
            provider=_COST_PROVIDER,
            estimated_cost=0.0,
            job_id=public_audit_id,
            job_type=_COST_JOB_TYPE,
            client_name="",
        )
        PostgresCostStore().record_cost(ctx, 0.0, cached=False)

    return _log


PublicCostLoggerDep = Annotated[Callable[[str], None], Depends(get_public_cost_logger)]


def get_public_artifact_store(settings: SettingsDep) -> LocalArtifactStore | None:
    """Dependency: the configured artifact store, or ``None`` when unset."""
    return local_store_from_settings(settings)


PublicArtifactStoreDep = Annotated["LocalArtifactStore | None", Depends(get_public_artifact_store)]


# --------------------------------------------------------------------------- #
# Endpoints (UNAUTHENTICATED - note: NO CurrentUser dependency anywhere here)
# --------------------------------------------------------------------------- #
@router.post(
    "/audits",
    response_model=PublicAuditCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_ip("public_audit", 5))],
)
async def create_public_audit(
    body: PublicAuditCreate,
    gateway: PublicGatewayDep,
    enqueue: PublicEnqueuerDep,
    log_cost: PublicCostLoggerDep,
) -> PublicAuditCreated:
    """Create ONE free audit for an email (lead capture). Free-only, SSRF-guarded."""
    # Free tier only: reject any paid audit type up front (zero paid-provider spend).
    paid = body.paid_types()
    if paid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The free audit does not support paid audit types: {', '.join(paid)}",
        )

    # SSRF guard: getaddrinfo blocks, so validate off the event loop.
    try:
        await asyncio.to_thread(validate_public_host, body.url)
    except PrivateAddressError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL is not a public address: {exc}",
        ) from exc

    email = str(body.email)
    # One free audit per email. Check first for a clean 409; the DB unique index
    # on lower(email) is the real guard (closes the check-then-insert race below).
    if await asyncio.to_thread(gateway.find_by_email, email) is not None:
        raise _DUPLICATE_EMAIL

    try:
        row = await asyncio.to_thread(gateway.insert, email, body.url, "landing")
    except psycopg_errors.UniqueViolation as exc:
        # Concurrent duplicate slipped past the pre-check -> same 409.
        raise _DUPLICATE_EMAIL from exc

    public_audit_id = str(row["id"])
    enqueue(public_audit_id)
    # Funnel-entry $0 cost (Free). Never fail the 201 on a cost-logging hiccup.
    try:
        await asyncio.to_thread(log_cost, public_audit_id)
    except Exception:
        logger.warning("public_audit_cost_log_failed", public_audit_id=public_audit_id)

    return PublicAuditCreated(report_token=str(row["report_token"]), status=str(row["status"]))


@router.get("/audits/{report_token}", response_model=PublicReport)
async def get_public_report(report_token: str, gateway: PublicGatewayDep, settings: SettingsDep) -> PublicReport:
    """Fetch the curated public report for a token (the token is the capability)."""
    row = await asyncio.to_thread(gateway.get_by_token, report_token)
    if row is None:
        raise _REPORT_NOT_FOUND
    when = row.get("created_at")
    when_iso = when.isoformat() if isinstance(when, datetime) else (str(when) if when else None)
    return PublicReport(
        status=str(row["status"]),
        score=row.get("score"),
        scores=row.get("scores") or {},
        has_pdf=bool(row.get("pdf_path")),
        has_report=bool(row.get("json_path")),
        url=str(row["url"]),
        when=when_iso,
        fiverr_url=settings.fiverr_upsell_url,
    )


@router.get("/audits/{report_token}/report.pdf")
async def download_public_report_pdf(
    report_token: str, gateway: PublicGatewayDep, store: PublicArtifactStoreDep
) -> FileResponse:
    """Serve the report PDF for a token, if present. The token is the only guard."""
    if store is None:
        raise _ARTIFACT_NOT_FOUND
    row = await asyncio.to_thread(gateway.get_by_token, report_token)
    if row is None:
        raise _REPORT_NOT_FOUND
    key = row.get("pdf_path")
    path = store.resolve(key) if key else None
    if path is None:
        raise _ARTIFACT_NOT_FOUND
    return FileResponse(path, media_type="application/pdf", filename="free-audit-report.pdf")
