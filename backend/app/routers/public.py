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
* FOUR independent abuse controls, because this is the only route on the platform
  an anonymous caller can use to cause real work (P0-2 / MT-005 / ADM-026):
    1. **SSRF-guarded** target URL (no internal address is ever crawled).
    2. **One free audit per email** (409 on a repeat), enforced by a DB unique
       index on ``lower(email)``, not only by the pre-check.
    3. **Per-IP rate limit, FAILING CLOSED.** If Redis cannot be consulted the
       request is refused, not waved through: a fail-open limiter means a cache
       outage silently removes the control.
    4. **An agency-wide daily cap** counted from Postgres. Per-IP limiting bounds
       one abuser; the daily cap bounds a distributed one and is the ceiling on
       the platform's total daily exposure. It also fails closed.
  Plus the **cost gate**: the ``public_audit`` dial and the agency-global spend
  halt are consulted before a row is even created, so an operator can switch the
  lead magnet off during an abuse episode without touching the paid product.
* The free audit is **CONDENSED and GENUINELY FREE** (DECISIONS_LOG D-1): the
  engine runs ``--mode free``, which hard-clears every paid integration, so a run
  calls no paid provider and costs $0 by construction rather than by assertion.
  It previously ran ``--mode auto`` with Serper + Places + citations + PSI on
  while committing a hardcoded $0.00 to the ledger - real spend, invisible.
* The tokenized report is CURATED: it returns the score/status/flags + the upsell
  link, and NEVER the internal id, the email, the stored error, or artifact paths.
"""

from __future__ import annotations

import asyncio
import re
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
from app.schemas.audits import AuditTypeKey
from app.services.audit_artifacts import (
    REPORT_HTML_VIEW_HEADERS,
    LocalArtifactStore,
    local_store_from_settings,
)
from app.services.content_images import (
    LocalContentImageStore,
    content_image_store_from_settings,
)
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore

logger = get_logger("app.public")


class _NoCostCache:
    """A no-op ``CostCache``. The funnel pre-check asks the gate a policy question
    (halt? dial?) and makes no provider call, so there is nothing to cache."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None

router = APIRouter(prefix="/public", tags=["public"])

# The funnel's OWN dial feature (registered in app.schemas.cost.DIAL_FEATURES).
# Deliberately NOT the paid audit's "tech_audit": an operator must be able to
# switch the unauthenticated lead magnet off without disabling the paid product.
_COST_FEATURE = "public_audit"
_COST_PROVIDER = "audit_engine"
_COST_JOB_TYPE = "public_audit"

# The dimensions the condensed free run reports on. The engine's deterministic
# analyzers cover these without any paid provider; the paid dimensions
# (off-page/local via Serper + Places) are the authenticated product.
_DEFAULT_TYPES: tuple[AuditTypeKey, ...] = (
    "onpage",
    "offpage",
    "technical",
    "local",
    "geo",
    "strategy",
)

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
# One message for every "not accepting free audits right now" case - a daily cap
# hit, an operator-disabled dial, a spend halt, or a cap check that could not run.
# Deliberately uniform: an anonymous caller learns the funnel is closed, never
# which control closed it or where the ceiling sits.
_FUNNEL_UNAVAILABLE = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="Free audits are temporarily unavailable. Please try again later.",
    headers={"Retry-After": "3600"},
)


# --------------------------------------------------------------------------- #
# Request / response shapes
# --------------------------------------------------------------------------- #
class PublicAuditCreate(BaseModel):
    """Landing-page payload. ``email`` is validated (``EmailStr``).

    ``types`` is accepted for wire compatibility with the existing landing page
    but does NOT scope the run, and never did: the engine has no per-dimension
    flag on its light path (see ``integrations.audit_engine.build_argv``). The
    public funnel runs one fixed CONDENSED shape - the deterministic on-page,
    technical and AI-search analyzers, no paid provider (DECISIONS_LOG D-1).

    The report renders whatever score categories that run actually produced, so a
    caller asking for a dimension the condensed run does not cover simply does not
    see it - it is never fabricated to match the request."""

    email: EmailStr
    url: str = Field(min_length=1, max_length=2048)
    types: list[AuditTypeKey] = Field(default_factory=lambda: list(_DEFAULT_TYPES))


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
    # The readable /leads/<brand> page for THIS audit, when one is published.
    #
    # The page has always been created on completion (`audit_public_pages.ensure_page`,
    # free pages publish by default) and was reachable only if you already knew the
    # slug -- which the person who ran the audit never saw. So the shareable artifact
    # existed and its owner could not find it. Empty string when no published page
    # exists yet (the audit is still running, or publishing was skipped).
    public_slug: str = Field(default="", serialization_alias="publicSlug")


# --------------------------------------------------------------------------- #
# Data gateway (privileged path, filtered to ONE lead per call)
# --------------------------------------------------------------------------- #
class PublicAuditsGateway(Protocol):
    """The narrow DB seam the public routes need (server-side, single-row scoped)."""

    def find_by_email(self, email: str) -> dict[str, Any] | None: ...
    def insert(self, email: str, url: str, source: str) -> dict[str, Any]: ...
    def get_by_token(self, report_token: str) -> dict[str, Any] | None: ...
    def delete_by_id(self, public_audit_id: str) -> None: ...
    def count_today(self) -> int: ...


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

    def delete_by_id(self, public_audit_id: str) -> None:
        with privileged_connection() as cur:
            cur.execute("delete from public.public_audits where id = %s", (public_audit_id,))

    def count_today(self) -> int:
        """Public audits created so far in the current UTC day.

        Counted in Postgres, not Redis: the agency-wide ceiling is a spend control
        and must survive a cache flush or a cold cache. ``created_at`` is the row's
        own insert timestamp, so the count cannot drift from what was accepted.
        """
        with privileged_connection() as cur:
            cur.execute(
                "select count(*) as n from public.public_audits "
                "where created_at >= date_trunc('day', now() at time zone 'utc')"
            )
            row = cur.fetchone()
            return int(row["n"]) if row else 0


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


def get_public_funnel_gate() -> Callable[[], bool]:
    """Dependency: is the free-audit funnel currently open?

    Consults the SAME cost gate every paid call passes, under the funnel's own
    ``public_audit`` dial. Returns True only for an ``api`` dial with no
    agency-global spend halt engaged.

    This REPLACES a "funnel-entry $0 cost" writer that logged a hardcoded $0.00
    into the money ledger at request time. That row asserted a cost before any
    work had happened and was a duplicate of the worker's own commit - the
    worker now writes exactly one ledger row per run, with the cost DERIVED from
    what the run actually did (``workers/tasks/audit.py``). What the request path
    needs from the gate is not a ledger entry: it is permission to proceed.

    Overridable in tests (the default reads through the privileged cost store).
    """

    def _open() -> bool:
        ctx = GateContext(
            feature_key=_COST_FEATURE,
            client_id=None,
            provider=_COST_PROVIDER,
            estimated_cost=0.0,
            job_id="",
            job_type=_COST_JOB_TYPE,
            client_name="",
        )
        return CostGate(PostgresCostStore(), _NoCostCache()).evaluate(ctx).allowed

    return _open


PublicFunnelGateDep = Annotated[Callable[[], bool], Depends(get_public_funnel_gate)]


def get_public_artifact_store(settings: SettingsDep) -> LocalArtifactStore | None:
    """Dependency: the configured artifact store, or ``None`` when unset."""
    return local_store_from_settings(settings)


PublicArtifactStoreDep = Annotated["LocalArtifactStore | None", Depends(get_public_artifact_store)]


def get_content_image_store(settings: SettingsDep) -> LocalContentImageStore | None:
    """Dependency: the content-image hosting store, or ``None`` when unconfigured."""
    return content_image_store_from_settings(settings)


ContentImageStoreDep = Annotated[
    "LocalContentImageStore | None", Depends(get_content_image_store)
]

# Content images are served immutable (the filename is a content hash), so a long,
# public cache is safe and keeps a WordPress-embedded image fast on repeat views.
_IMAGE_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


# --------------------------------------------------------------------------- #
# Endpoints (UNAUTHENTICATED - note: NO CurrentUser dependency anywhere here)
# --------------------------------------------------------------------------- #
@router.post(
    "/audits",
    response_model=PublicAuditCreated,
    status_code=status.HTTP_201_CREATED,
    # FAIL CLOSED. On every other route the limiter is one control among several
    # (authentication, permissions, budget caps); here it is the only thing between
    # an anonymous caller and a crawl, so "we cannot count" must mean "no".
    dependencies=[Depends(rate_limit_ip("public_audit", 5, fail_closed=True))],
)
async def create_public_audit(
    body: PublicAuditCreate,
    gateway: PublicGatewayDep,
    enqueue: PublicEnqueuerDep,
    funnel_open: PublicFunnelGateDep,
    settings: SettingsDep,
) -> PublicAuditCreated:
    """Create ONE condensed free audit for an email (lead capture). SSRF-guarded.

    Order of checks is deliberate, cheapest-and-most-decisive first: the funnel
    gate and the daily cap decide whether we are accepting ANY request right now,
    and both run before the SSRF DNS lookup so a closed funnel costs no work. The
    per-request guards (SSRF, one-per-email) follow.
    """
    # 1. Is the funnel open at all? The operator dial + the agency-global spend
    #    halt. A gate failure is treated as CLOSED: if we cannot establish that
    #    spending is permitted, we do not spend.
    try:
        is_open = await asyncio.to_thread(funnel_open)
    except Exception:
        logger.error("public_audit_gate_check_failed")
        raise _FUNNEL_UNAVAILABLE from None
    if not is_open:
        logger.info("public_audit_funnel_closed")
        raise _FUNNEL_UNAVAILABLE

    # 2. The agency-wide daily ceiling. Per-IP limiting bounds ONE abuser; this
    #    bounds a distributed one. FAILS CLOSED for the same reason as the gate:
    #    an uncountable ceiling is an unenforced ceiling.
    cap = settings.public_audit_daily_cap
    if cap > 0:
        try:
            used = await asyncio.to_thread(gateway.count_today)
        except Exception:
            logger.error("public_audit_daily_cap_check_failed")
            raise _FUNNEL_UNAVAILABLE from None
        if used >= cap:
            logger.warning("public_audit_daily_cap_reached", used=used, cap=cap)
            raise _FUNNEL_UNAVAILABLE

    # 3. SSRF guard: getaddrinfo blocks, so validate off the event loop.
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
    # Enqueue the worker. If the broker (Redis) is unreachable the job can NEVER run,
    # so don't leave an orphaned 'queued' row that also blocks this email forever
    # (one-audit-per-email → a permanent 409). Roll the row back and return a clean
    # 503 the funnel can retry, instead of a raw 500.
    try:
        enqueue(public_audit_id)
    except Exception as exc:
        logger.warning("public_audit_enqueue_failed", public_audit_id=public_audit_id)
        try:
            await asyncio.to_thread(gateway.delete_by_id, public_audit_id)
        except Exception:
            logger.warning("public_audit_rollback_failed", public_audit_id=public_audit_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The audit service is temporarily unavailable. Please try again shortly.",
        ) from exc
    # No cost row is written here. The WORKER commits exactly one ledger entry per
    # run, priced from what the run actually did - see workers/tasks/audit.py. A $0
    # row written at request time asserted a cost before any work existed.
    return PublicAuditCreated(report_token=str(row["report_token"]), status=str(row["status"]))


@router.get("/audits/{report_token}", response_model=PublicReport)
async def get_public_report(report_token: str, gateway: PublicGatewayDep, settings: SettingsDep) -> PublicReport:
    """Fetch the curated public report for a token (the token is the capability)."""
    row = await asyncio.to_thread(gateway.get_by_token, report_token)
    if row is None:
        raise _REPORT_NOT_FOUND
    when = row.get("created_at")
    when_iso = when.isoformat() if isinstance(when, datetime) else (str(when) if when else None)
    store = local_store_from_settings(settings)
    has_pdf, has_report = await asyncio.to_thread(_public_report_flags, store, row)
    slug = await asyncio.to_thread(_published_slug_for, str(row["id"]))
    return PublicReport(
        status=str(row["status"]),
        score=row.get("score"),
        scores=row.get("scores") or {},
        has_pdf=has_pdf,
        has_report=has_report,
        url=str(row["url"]),
        when=when_iso,
        fiverr_url=settings.fiverr_upsell_url,
        public_slug=slug,
    )


def _published_slug_for(public_audit_id: str) -> str:
    """The published slug naming this audit, or "" when there is not one.

    Scoped to a single audit id and to `published` rows, like every other read on
    this router: the public surface must never be able to enumerate slugs. Never
    raises -- a funnel that cannot show a share link is a smaller failure than a
    funnel that 500s, so a missing table or a failed lookup degrades to no link.
    """
    try:
        with privileged_connection() as conn, conn.cursor() as cur:
            cur.execute(
                # ::uuid is REQUIRED. psycopg sends a Python str as text and
                # Postgres has no `uuid = text` operator, so without the cast every
                # call raised and the handler below returned "" -- the share link
                # silently never appeared, which is exactly how this shipped once.
                "select slug from public.public_audit_pages"
                " where public_audit_id = %s::uuid and published"
                " order by created_at desc limit 1",
                (public_audit_id,),
            )
            got = cur.fetchone()
    except Exception as exc:
        # LOGGED, not swallowed. A silent "" is indistinguishable from "this audit
        # has no page", which is what let a uuid/text operator error hide as a
        # missing feature rather than surfacing as the bug it was.
        logger.warning("public_slug_lookup_failed", extra={"error": str(exc)[:200]})
        return ""
    if not got:
        return ""
    return str(got[0] if not isinstance(got, dict) else got.get("slug", ""))


def _public_report_flags(
    store: LocalArtifactStore | None, row: dict[str, Any]
) -> tuple[bool, bool]:
    """(has_pdf, has_report) for the public status response, downgraded to on-disk
    reality when a store is configured so the funnel never shows a dead button.

    ``has_report`` gates the IN-PAGE viewer, which fetches ``report.html`` (resolved
    by convention from the audit id), so it must reflect THAT file - not
    ``findings.json``. When no store is configured we cannot check the disk, so we
    trust the DB columns (prior behavior; keeps the flags meaningful store-less)."""
    if store is None:
        return bool(row.get("pdf_path")), bool(row.get("json_path"))
    has_pdf = bool(row.get("pdf_path")) and store.resolve(str(row.get("pdf_path") or "")) is not None
    has_report = store.resolve_report_html(str(row["id"])) is not None
    return has_pdf, has_report


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


@router.get("/audits/{report_token}/findings.json")
async def download_public_report_json(
    report_token: str, gateway: PublicGatewayDep, store: PublicArtifactStoreDep
) -> FileResponse:
    """Serve the raw findings.json for a token, if present. The token is the only guard.

    Mirrors ``download_public_report_pdf`` exactly (same store, same key convention -
    ``json_path`` is written by the same worker call that writes ``pdf_path``), so the
    staff admin leads screen can offer an honest JSON download alongside the PDF one.
    """
    if store is None:
        raise _ARTIFACT_NOT_FOUND
    row = await asyncio.to_thread(gateway.get_by_token, report_token)
    if row is None:
        raise _REPORT_NOT_FOUND
    key = row.get("json_path")
    path = store.resolve(key) if key else None
    if path is None:
        raise _ARTIFACT_NOT_FOUND
    return FileResponse(path, media_type="application/json", filename="free-audit-findings.json")


@router.get("/audits/{report_token}/report.html")
async def view_public_report_html(
    report_token: str, gateway: PublicGatewayDep, store: PublicArtifactStoreDep
) -> FileResponse:
    """Serve the (condensed) free report.html for a token's in-page viewer.

    The token is the only guard. The file is resolved by convention from the public
    audit's id (sibling of report.pdf), so the viewer works even when no PDF backend
    produced a PDF. Same condensed document the free PDF is rendered from.
    """
    if store is None:
        raise _ARTIFACT_NOT_FOUND
    row = await asyncio.to_thread(gateway.get_by_token, report_token)
    if row is None:
        raise _REPORT_NOT_FOUND
    path = store.resolve_report_html(str(row["id"]))
    if path is None:
        raise _ARTIFACT_NOT_FOUND
    return FileResponse(path, media_type="text/html", headers=REPORT_HTML_VIEW_HEADERS)


@router.get("/content-images/{name}")
async def serve_content_image(
    name: str, store: ContentImageStoreDep
) -> FileResponse:
    """Serve a generated CONTENT IMAGE by its content-hash filename (read-only).

    UNAUTHENTICATED by design: these PNGs are embedded as ``<img>`` in published
    WordPress pages / draft previews and are fetched by a browser with no bearer
    token. The filename is a sha256 content hash and the store resolves it
    traversal-safe (``..``/absolute refused), so a crafted name can never read an
    arbitrary file. A missing store or file is a clean 404, never a crash.
    """
    if store is None:
        raise _ARTIFACT_NOT_FOUND
    path = await asyncio.to_thread(store.resolve, name)
    if path is None:
        raise _ARTIFACT_NOT_FOUND
    return FileResponse(path, media_type="image/png", headers=_IMAGE_CACHE_HEADERS)


# --------------------------------------------------------------------------- #
# Readable public pages: /leads/<slug>
# --------------------------------------------------------------------------- #
# The token routes above stay exactly as they are - every existing link keeps
# working. These add a SECOND, readable address for the same curated report, and
# they are the only public surface a paid audit ever gets.
#
# The resolve is deliberately narrow. It reads ONE row from public_audit_pages by
# slug, and only when `published` is true; an unpublished page is a 404 and not a
# 403, so the URL space leaks nothing about which slugs exist. Free pages are
# published on completion (the lead magnet is meant to be shared, and the report
# is derived wholly from a public crawl); PAID pages default to unpublished and
# additionally carry a random suffix, so a client's deliverable is neither public
# by accident nor reachable by guessing their brand name. See 0126's header.
_PAGE_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Report not found"
)

_PAGE_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,78}[a-z0-9])?$")


class PublicPage(BaseModel):
    """The curated public page payload. Same withholding rules as PublicReport:
    no internal id, no email, no stored error, no artifact path."""

    slug: str
    kind: str
    brand: str
    url: str
    status: str
    score: int | None
    scores: dict[str, Any]
    has_pdf: bool
    has_report: bool
    when: str | None
    fiverr_url: str


def _resolve_page(slug: str) -> dict[str, Any] | None:
    """slug -> the published report row it names, or None.

    Privileged path (the route is unauthenticated) but filtered to a single row by
    primary key, exactly like the token reads above - no tenant table is reachable
    from here. Returns the underlying public_audits/audits row plus the page's own
    `kind`, so the caller can serve one shape for both.
    """
    with privileged_connection() as cur:
        cur.execute(
            "select kind, public_audit_id, audit_id from public.public_audit_pages"
            " where slug = %s and published",
            (slug,),
        )
        page = cur.fetchone()
        if page is None:
            return None
        if page["kind"] == "free":
            cur.execute(
                "select id, url, status, score, scores, pdf_path, json_path, created_at"
                " from public.public_audits where id = %s",
                (page["public_audit_id"],),
            )
        else:
            cur.execute(
                "select id, url, status::text as status, score, scores, pdf_path,"
                " json_path, created_at from public.audits where id = %s",
                (page["audit_id"],),
            )
        row = cur.fetchone()
        if row is None:
            return None
        out = dict(row)
        out["kind"] = page["kind"]
        return out


def _validated_slug(slug: str) -> str:
    """Reject anything the slug column could not hold before it reaches the DB."""
    s = (slug or "").strip().lower()
    if not _PAGE_SLUG_RE.match(s):
        raise _PAGE_NOT_FOUND
    return s


def _brand_from_url(url: str) -> str:
    """The readable brand for a page, derived from the AUDITED URL.

    Mirrors the SQL `audit_brand_slug` that produced the slug base: drop the scheme,
    drop `www.`, keep the host, drop the public suffix, scrub to [a-z0-9-].

    Derived from the URL and NOT from the slug, because the slug carries whatever
    machinery was needed to make it unique: a paid slug has a random hex suffix, and
    a free slug gains a counter on collision, so the third audit of one brand becomes
    `acme-3`. Rendering the slug announced that page as "amsofastudio-3". Stripping a
    trailing number instead would be a guess that mangles a brand genuinely ending in
    one ("studio-54" -> "studio"); the URL has the answer and needs no guess.
    """
    host = re.sub(r"^[a-zA-Z]+://", "", url or "")
    host = re.sub(r"^www\.", "", host).split("/")[0].lower()
    host = re.sub(r"\.[a-z.]+$", "", host)          # public suffix
    host = re.sub(r"[^a-z0-9-]+", "-", host)
    return re.sub(r"-{2,}", "-", host).strip("-")


@router.get("/pages/{slug}", response_model=PublicPage)
async def get_public_page(
    slug: str, settings: SettingsDep, store: PublicArtifactStoreDep
) -> PublicPage:
    """The curated report behind a readable slug (free or paid, published only)."""
    s = _validated_slug(slug)
    row = await asyncio.to_thread(_resolve_page, s)
    if row is None or str(row.get("status")) != "done":
        raise _PAGE_NOT_FOUND
    has_pdf, has_report = await asyncio.to_thread(
        _public_report_flags, store or local_store_from_settings(settings), row
    )
    when = row.get("created_at")
    return PublicPage(
        slug=s,
        kind=str(row["kind"]),
        brand=_brand_from_url(str(row["url"])) or s,
        url=str(row["url"]),
        status=str(row["status"]),
        score=row.get("score"),
        scores=row.get("scores") or {},
        has_pdf=has_pdf,
        has_report=has_report,
        when=when.isoformat() if isinstance(when, datetime) else (str(when) if when else None),
        fiverr_url=settings.fiverr_upsell_url,
    )


@router.get("/pages/{slug}/report.html")
async def view_public_page_report(
    slug: str, store: PublicArtifactStoreDep
) -> FileResponse:
    """The full consulting report behind a readable slug.

    Resolves to the SAME document the staff and portal viewers serve
    (``resolve_report_html`` prefers the built consulting report over the engine's
    condensed one), so a free page and a paid page show the same thing.
    """
    if store is None:
        raise _ARTIFACT_NOT_FOUND
    s = _validated_slug(slug)
    row = await asyncio.to_thread(_resolve_page, s)
    if row is None:
        raise _PAGE_NOT_FOUND
    path = store.resolve_report_html(str(row["id"]))
    if path is None:
        raise _ARTIFACT_NOT_FOUND
    return FileResponse(path, media_type="text/html", headers=REPORT_HTML_VIEW_HEADERS)


@router.get("/pages/{slug}/report.pdf")
async def download_public_page_pdf(
    slug: str, store: PublicArtifactStoreDep
) -> FileResponse:
    """The report PDF behind a readable slug."""
    if store is None:
        raise _ARTIFACT_NOT_FOUND
    s = _validated_slug(slug)
    row = await asyncio.to_thread(_resolve_page, s)
    if row is None:
        raise _PAGE_NOT_FOUND
    key = row.get("pdf_path")
    path = store.resolve(str(key)) if key else None
    if path is None:
        raise _ARTIFACT_NOT_FOUND
    return FileResponse(path, media_type="application/pdf", filename=f"{s}-audit-report.pdf")
