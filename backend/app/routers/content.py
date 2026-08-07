"""Part 7 Module 02 (Content) endpoints: the content-job board, the create-and-
enqueue seam, and the human review gate. Reads require any provisioned staff
(``view_reports`` - a portal client holds none, so clients are 403'd off the whole
surface); creating a job requires ``publish_content``; the review/edit decisions
are LEAD-only (owner/admin/manager).

Responses are the frontend ``ContentJob`` shape (``id`` = the public ``CJ-####``
code; ``client``/``color`` are display SNAPSHOTS so ``client_id`` never leaks). The
app-layer 403/409 here are clean UX; the REAL lifecycle boundary is the
``content_jobs_guard_update`` DB trigger (the 3-actor model: the worker advances
``queued->drafting->needs_review`` + ``publishing->done`` on the privileged pool;
LEADS own the review exit ``needs_review->publishing/rejected/drafting`` on the RLS
pool; a non-lead can drive NOTHING). Every human mutation therefore stays on the
RLS path (``ContentRepo`` -> ``rls_connection``); only the worker touches the
privileged pool. Blocking psycopg calls are offloaded with ``asyncio.to_thread``
and every mutation appends an activity entry.

The create seam SNAPSHOTS the client name/color, RESOLVES the framework (``Auto`` ->
``auto_framework(pageType)`` with ``auto=true``) + the JSON-LD ``schema_type``
(``schema_for(pageType)``) server-side, and SEEDS ``source_pack`` (client facts +
WordPress publish config) so the worker draws grounding + the publish target from
the row, never from a request body. The worker enqueue + the publish enqueue are
overridable dependencies so the endpoints unit-test with zero broker.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg.types.json import Jsonb

from app.config import Settings
from app.core.auth import CurrentUser, require_perm, require_role
from app.core.deps import HttpClientDep, SettingsDep
from app.core.pagination import PageDep
from app.core.security import PrivateAddressError, validate_public_host
from app.db.clients_repo import ClientsRepo, ClientsRepoDep
from app.db.content_repo import ContentRepo, ContentRepoDep
from app.logging_setup import get_logger
from app.schemas.content import (
    ContentBulkGenerateRequest,
    ContentBulkGenerateResponse,
    ContentJobCreate,
    ContentJobResponse,
    ContentJobUpdate,
    ContentResearchRequest,
    ContentResearchResponse,
    ContentReviewRequest,
    ContentStatsResponse,
    SiteDesignProfile,
    SiteDesignRequest,
    SiteDesignResponse,
    auto_framework,
    compute_content_stats,
    job_page_type_for,
    schema_for,
)
from app.services.activity import record_activity
from app.services.content_research import (
    build_recommend_gate,
    build_recommend_researcher,
    run_content_research,
)
from app.services.cost_gate import CostGate
from app.services.site_design import (
    DesignResult,
    SystemSummarizer,
    build_design_gate,
    build_design_summarizer,
    extract_site_design,
)
from integrations.firecrawl import Firecrawl, firecrawl_from_settings
from integrations.llm import Researcher

router = APIRouter(tags=["content"])

# All six staff roles hold view_reports; a portal client does NOT, confining
# clients out of the staff content namespace (mirrors audits.py / tasks.py).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# Creating (queueing) a content job = the publish_content permission (owner/admin/
# manager/specialist hold it). The closest content perm in the 8-permission matrix.
PublishContent = Annotated[CurrentUser, Depends(require_perm("publish_content"))]
# The review gate + limited edits are LEAD-only (owner/admin/manager) - the exact
# set the DB guard's path-2 recognises for the needs_review exit.
LeadOnly = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

# The server-only rich columns each rich-retrieval endpoint returns (never in the
# 15-key ContentJob contract). Keyed by the URL suffix.
_RICH_COLUMNS: dict[str, str] = {
    "draft": "draft_md",
    "keywords": "keyword_map",
    "qa": "qa_score",
    "schema": "json_ld",
    "outline": "outline",          # headings + layout + meta (title/description)
    "links": "internal_links",     # internal-link coverage
    "entities": "entity_coverage", # entity/keyword coverage
}

_JOB_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content job not found")
_NOT_IN_REVIEW = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="Content job is not awaiting review"
)


# --------------------------------------------------------------------------- #
# Enqueuer dependencies (overridable in tests; the worker task is imported lazily
# so the API process never pulls in Celery task modules just to import the router).
# --------------------------------------------------------------------------- #
def get_content_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the content PIPELINE worker for a job code."""

    def _enqueue(code: str) -> None:
        from workers.tasks.content import run_content_job

        run_content_job.delay(code)

    return _enqueue


def get_content_publish_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the content PUBLISH worker for an approved job code."""

    def _enqueue(code: str) -> None:
        from workers.tasks.content import publish_content_job_task

        publish_content_job_task.delay(code)

    return _enqueue


ContentEnqueuerDep = Annotated[Callable[[str], None], Depends(get_content_enqueuer)]
ContentPublishEnqueuerDep = Annotated[Callable[[str], None], Depends(get_content_publish_enqueuer)]


# --------------------------------------------------------------------------- #
# source_pack seeding (client facts + WordPress publish config)
# --------------------------------------------------------------------------- #
def _clean_lines(items: list[str] | None) -> list[str]:
    """Trim + drop blanks from an operator-supplied grounding list."""
    return [s.strip() for s in (items or []) if isinstance(s, str) and s.strip()]


def _design_dict(profile: SiteDesignProfile | None) -> dict[str, Any] | None:
    """A plain (snake_case) dict of a design profile for ``source_pack`` seeding, or
    ``None`` when the create body carried no profile."""
    return profile.model_dump() if profile is not None else None


def _seed_source_pack(
    client: dict[str, Any],
    site: dict[str, Any] | None,
    *,
    target: str,
    proof_points: list[str] | None = None,
    testimonials: list[str] | None = None,
    unique_data: list[str] | None = None,
    services: list[str] | None = None,
    design_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the worker's ``source_pack`` grounding from the client + its site.

    Snapshots the client FACTS (name/industry/founded/contact) the generator grounds
    against, and - for a WordPress target - the publish site URL. Per-site WP app
    passwords live encrypted in the vault (never in a request body); the publish
    chunk reveals them, so this seeds only the non-secret site reference. A missing
    site simply omits the WP config, and the publish path degrades to artifact-only.

    The operator-supplied first-hand grounding (``proof_points``/``testimonials``/
    ``unique_data``/``services``) is seeded verbatim: the generator's §2 Experience
    block + §7 information-gain angle ground against these, so a job that supplies
    them clears the ``fact_grounding``/``eeat_experience`` publish gate instead of
    emitting a ``[NEEDS:]`` marker. Absent, the job still generates but holds at the
    review gate as un-publishable (by design - no first-hand signal, no publish).
    """
    facts: dict[str, str] = {}
    if client.get("industry"):
        facts["industry"] = str(client["industry"])
    if client.get("since_year"):
        facts["founded"] = str(client["since_year"])
    if client.get("contact_name"):
        facts["primary_contact"] = str(client["contact_name"])
    if client.get("contact_role"):
        facts["contact_role"] = str(client["contact_role"])

    pack: dict[str, Any] = {"client_name": client.get("name", ""), "facts": facts}
    proof = _clean_lines(proof_points)
    quotes = _clean_lines(testimonials)
    data = _clean_lines(unique_data)
    svcs = _clean_lines(services)
    if proof:
        pack["proof_points"] = proof
    if quotes:
        pack["testimonials"] = quotes
    if data:
        pack["unique_data"] = data
    if svcs:
        pack["services"] = svcs
    if design_profile:
        # The target site's extracted design profile - the worker's publish path reads
        # ``design_profile["layout"]["section_order"]`` back off here to wrap the page
        # in ordered <section class="aios-<name>"> blocks matching the client's site.
        pack["design_profile"] = design_profile
    if target == "WordPress" and site is not None:
        domain = str(site.get("domain") or "").strip()
        if domain:
            site_url = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
            pack["wp_site_url"] = site_url
            pack["site_url"] = site_url
    return pack


async def _first_site(clients: ClientsRepoDep, client_id: str) -> dict[str, Any] | None:
    sites = await asyncio.to_thread(clients.list_sites, client_id, limit=1, offset=0)
    return sites[0] if sites else None


async def _seed_and_insert_job(
    repo: ContentRepo,
    clients: ClientsRepo,
    enqueue: Callable[[str], None],
    *,
    client: dict[str, Any],
    client_id: str,
    page_type: str,
    topic: str,
    framework: str,
    target: str,
    proof_points: list[str] | None = None,
    testimonials: list[str] | None = None,
    unique_data: list[str] | None = None,
    services: list[str] | None = None,
    design_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Seed a job's ``source_pack``, insert the queued row (RLS path), enqueue the
    pipeline worker, and return the row. The shared create path behind BOTH
    ``POST /content/jobs`` and the research fan-out, so the two can never diverge:
    it resolves the ``Auto`` framework + the JSON-LD ``schema_type`` server-side and
    snapshots the client name/color. The CALLER records the activity entry (one per
    request, not one per job) - that is the only part not shared here.
    """
    if framework == "Auto":
        framework_resolved: str = auto_framework(page_type)
        auto = True
    else:
        framework_resolved = framework
        auto = False

    site = await _first_site(clients, client_id) if target == "WordPress" else None
    source_pack = _seed_source_pack(
        client,
        site,
        target=target,
        proof_points=proof_points,
        testimonials=testimonials,
        unique_data=unique_data,
        services=services,
        design_profile=design_profile,
    )
    row = await asyncio.to_thread(
        repo.insert_job,
        {
            "client_id": client_id,
            "client_name": client.get("name", ""),
            "color": client.get("contact_color", "#7B69EE"),
            "page_type": page_type,
            "topic": topic,
            "framework": framework_resolved,
            "auto": auto,
            "target": target,
            "status": "queued",
            "schema_type": schema_for(page_type),
            "stage": "Queued",
            "source_pack": Jsonb(source_pack),
        },
    )
    enqueue(str(row["code"]))
    return row


# --------------------------------------------------------------------------- #
# Research-first bulk content: the page-set recommender + the bulk fan-out.
# The researcher/gate are overridable dependencies so the endpoints unit-test on
# fakes with zero network / zero DB (mirrors policy.py's get_ask_researcher/gate).
# --------------------------------------------------------------------------- #
def get_research_researcher(settings: SettingsDep) -> Researcher | None:
    """Dependency: the key-gated web-search researcher (or ``None`` degraded). Overridable in tests."""
    return build_recommend_researcher(settings)


def get_research_gate() -> CostGate:
    """Dependency: the real cost gate over the Postgres store. Overridable in tests."""
    return build_recommend_gate()


ResearchResearcherDep = Annotated[Researcher | None, Depends(get_research_researcher)]
ResearchGateDep = Annotated[CostGate, Depends(get_research_gate)]


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
@router.get("/content/jobs", response_model=list[ContentJobResponse])
async def list_content_jobs(
    repo: ContentRepoDep,
    page: PageDep,
    _user: ViewReports,
    client: Annotated[str | None, Query()] = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
) -> list[ContentJobResponse]:
    """List content jobs (created_at desc). Optional ``?client`` (client_id) and
    ``?status`` filters; paginated via the hard-capped PageDep."""
    rows = await asyncio.to_thread(
        repo.list_jobs, client_id=client, status=status_, limit=page.limit, offset=page.offset
    )
    return [ContentJobResponse.from_row(r) for r in rows]


@router.get("/content/jobs/stats", response_model=ContentStatsResponse)
async def content_stats(repo: ContentRepoDep, _user: ViewReports) -> ContentStatsResponse:
    """The 4 content-board KPIs (in-pipeline, awaiting-review, published-this-month,
    avg cost of priced jobs)."""
    rows = await asyncio.to_thread(repo.list_jobs)
    return compute_content_stats(rows)


@router.get("/content/jobs/{code}", response_model=ContentJobResponse)
async def get_content_job(code: str, repo: ContentRepoDep, _user: ViewReports) -> ContentJobResponse:
    """One content job in the 15-key ContentJob shape."""
    row = await asyncio.to_thread(repo.get_job_by_code, code)
    if row is None:
        raise _JOB_NOT_FOUND
    return ContentJobResponse.from_row(row)


@router.get("/content/jobs/{code}/{column}")
async def get_content_rich(code: str, column: str, repo: ContentRepoDep, _user: ViewReports) -> dict[str, Any]:
    """Rich retrieval (staff-only, NOT contract-locked): the server-only pipeline
    columns a reviewer needs - ``draft`` (markdown), ``keywords`` (keyword_map),
    ``qa`` (the QA scorecard), ``schema`` (the assembled JSON-LD), and ``wp`` (the
    WordPress push URLs captured at publish time). 404 on an unknown column or job."""
    if column == "wp":
        # The WordPress push result (permalink + wp-admin edit link + post id) captured
        # when an approved job was pushed to the client's AIOS Publisher plugin. Kept
        # OUT of the 15-key ContentJob contract, surfaced here so the review preview can
        # link straight to the WP draft to publish it there. All null until pushed.
        row = await asyncio.to_thread(repo.get_job_by_code, code)
        if row is None:
            raise _JOB_NOT_FOUND
        return {
            "id": str(row.get("code", code)),
            "wp": {
                "url": row.get("wp_url"),
                "edit_url": row.get("wp_edit_url"),
                "post_id": row.get("wp_post_id"),
                "status": row.get("status"),
                "target": row.get("target"),
            },
        }

    db_column = _RICH_COLUMNS.get(column)
    if db_column is None:
        raise _JOB_NOT_FOUND
    row = await asyncio.to_thread(repo.get_job_by_code, code)
    if row is None:
        raise _JOB_NOT_FOUND
    return {"id": str(row.get("code", code)), column: row.get(db_column)}


# --------------------------------------------------------------------------- #
# Create (queue + enqueue the pipeline worker)
# --------------------------------------------------------------------------- #
@router.post("/content/jobs", response_model=ContentJobResponse, status_code=status.HTTP_201_CREATED)
async def create_content_job(
    body: ContentJobCreate,
    repo: ContentRepoDep,
    clients: ClientsRepoDep,
    enqueue: ContentEnqueuerDep,
    actor: PublishContent,
) -> ContentJobResponse:
    """Queue a new content job (status=queued) and enqueue the pipeline worker.

    Validates + snapshots the client (name/color - never the client_id), RESOLVES
    the framework (``Auto`` -> ``auto_framework(pageType)`` with ``auto=true``) and
    the JSON-LD ``schema_type`` (``schema_for(pageType)``) server-side, seeds
    ``source_pack`` (client facts + WP publish config), inserts the queued row on
    the RLS path, and enqueues ``run_content_job``.
    """
    client = await asyncio.to_thread(clients.get_client, body.client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    row = await _seed_and_insert_job(
        repo,
        clients,
        enqueue,
        client=client,
        client_id=body.client_id,
        page_type=body.page_type,
        topic=body.topic,
        framework=body.framework,
        target=body.target,
        proof_points=body.proof_points,
        testimonials=body.testimonials,
        unique_data=body.unique_data,
        services=body.services,
        design_profile=_design_dict(body.design_profile),
    )
    await record_activity(
        actor, kind="content", action="queued a content job", target=client.get("name", ""),
        entity_type="client", entity_id=body.client_id,
    )
    return ContentJobResponse.from_row(row)


# --------------------------------------------------------------------------- #
# Research-first bulk content: recommend a page set, then bulk-generate the picks
# --------------------------------------------------------------------------- #
logger = get_logger("app.routers.content")


@router.post("/content/research", response_model=ContentResearchResponse)
async def research_content(
    body: ContentResearchRequest,
    settings: SettingsDep,
    researcher: ResearchResearcherDep,
    gate: ResearchGateDep,
    _actor: PublishContent,
) -> ContentResearchResponse:
    """Recommend a set of pages to build for a site + content type (the "checkboxes").

    Claude researches the site + its competitors LIVE via the Anthropic SERVER-SIDE
    web_search tool and returns a strict-JSON page set. The single paid call is metered
    under the EXISTING ``content_research`` money-dial (committed spend = token cost +
    web-search cost); a missing key, a dial/budget block, or a research failure DEGRADES
    (200, ``status='degraded'``) rather than crashing, and the gate is never bypassed.
    The site URL is SSRF-guarded off the event loop; the blocking Anthropic call + the
    sync gate store run off the loop via ``to_thread``."""
    # SSRF guard: getaddrinfo blocks, so validate off the event loop (invariant #2).
    try:
        await asyncio.to_thread(validate_public_host, body.site)
    except PrivateAddressError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Site is not a public address: {exc}",
        ) from exc
    except Exception as exc:  # a non-resolving / malformed host is a BAD REQUEST, not a 500
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not reach that site URL - check it is a valid, public web address.",
        ) from exc

    def _run() -> ContentResearchResponse:
        # Research must NEVER 500: any unexpected failure (a provider/gate/DB hiccup)
        # degrades to an honest empty result so the dashboard shows a clean message
        # instead of "internal server error".
        try:
            result = run_content_research(
                researcher=researcher,
                gate=gate,
                settings=settings,
                site=body.site,
                content_type=body.content_type,
                count=body.count,
            )
        except Exception:
            logger.exception("content_research_endpoint_error")
            return ContentResearchResponse(status="degraded", items=[], reason="research_error")
        return ContentResearchResponse(
            status=result.status,  # type: ignore[arg-type]
            items=result.items,
            reason=result.reason,
        )

    return await asyncio.to_thread(_run)


@router.post(
    "/content/research/generate",
    response_model=ContentBulkGenerateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_from_research(
    body: ContentBulkGenerateRequest,
    repo: ContentRepoDep,
    clients: ClientsRepoDep,
    enqueue: ContentEnqueuerDep,
    actor: PublishContent,
) -> ContentBulkGenerateResponse:
    """Bulk-generate the SELECTED recommendations: fan each picked page into a content
    job via the SAME create path as ``POST /content/jobs`` (``_seed_and_insert_job`` -
    snapshot client, resolve framework + schema, seed ``source_pack``, enqueue the
    pipeline worker). Each item's ``title`` becomes the job topic and its ``pageType``
    maps to the generator's page type; the client / framework / target / first-hand
    grounding are shared across every job. Records ONE activity entry for the fan-out."""
    client = await asyncio.to_thread(clients.get_client, body.client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    design_profile = _design_dict(body.design_profile)  # shared across every fanned-out job
    codes: list[str] = []
    for item in body.items:
        row = await _seed_and_insert_job(
            repo,
            clients,
            enqueue,
            client=client,
            client_id=body.client_id,
            page_type=job_page_type_for(item.page_type),
            topic=item.title,
            framework=body.framework,
            target=body.target,
            proof_points=body.proof_points,
            testimonials=body.testimonials,
            unique_data=body.unique_data,
            services=body.services,
            design_profile=design_profile,
        )
        codes.append(str(row["code"]))

    await record_activity(
        actor,
        kind="content",
        action=f"bulk-generated {len(codes)} content pages",
        target=client.get("name", ""),
        entity_type="client",
        entity_id=body.client_id,
    )
    return ContentBulkGenerateResponse(jobs=codes)


# --------------------------------------------------------------------------- #
# Site-design EXTRACTOR (POST /content/site-design): gather the target site's
# existing design so a new page can be built to MATCH it before publishing. The
# summarizer / gate / fetcher are overridable dependencies so the endpoint unit-tests
# on fakes with ZERO network + ZERO real provider (mirrors the research endpoints).
# --------------------------------------------------------------------------- #
# A fetcher takes (site_url, max_pages) and returns the fetched page HTML strings.
DesignFetcher = Callable[[str, int], Awaitable[list[str]]]

# Only these link schemes / prefixes are worth crawling for a same-domain page.
_SKIP_HREF_PREFIXES = ("#", "mailto:", "tel:", "javascript:", "data:")
_ASSET_SUFFIXES = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".css", ".js",
    ".pdf", ".zip", ".mp4", ".woff", ".woff2", ".ttf", ".xml", ".json",
)


def get_design_summarizer(settings: SettingsDep) -> SystemSummarizer | None:
    """Dependency: the key-gated design summarizer (or ``None`` degraded). Overridable in tests."""
    return build_design_summarizer(settings)


def get_design_gate() -> CostGate:
    """Dependency: the real cost gate over the Postgres store. Overridable in tests."""
    return build_design_gate()


def get_design_firecrawl(settings: SettingsDep) -> Firecrawl | None:
    """Dependency: the key-gated Firecrawl render+screenshot client (or ``None`` when
    ``FIRECRAWL_API_KEY`` is unset -> the endpoint falls back to the plain fetcher).
    Overridden in tests with a ``FakeFirecrawl`` (no network)."""
    return firecrawl_from_settings(settings)


def _same_domain_links(html: str, base_url: str, *, limit: int) -> list[str]:
    """Extract up to ``limit`` same-domain internal page URLs from the homepage HTML.

    Pure + stdlib only (regex, like the research teardown): absolutises each ``href``
    against ``base_url``, keeps only http(s) links on the SAME host, drops fragments /
    assets / the homepage itself, and dedupes. The caller SSRF-guards each before fetch.
    """
    import re
    from urllib.parse import urljoin, urlparse

    base_host = (urlparse(base_url).hostname or "").lower()
    base_norm = base_url.split("#", 1)[0].rstrip("/")
    seen: set[str] = set()
    out: list[str] = []
    for raw in re.findall(r'href\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE):
        href = raw.strip()
        if not href or href.lower().startswith(_SKIP_HREF_PREFIXES):
            continue
        absolute = urljoin(base_url, href).split("#", 1)[0]
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        if (parsed.hostname or "").lower() != base_host:
            continue
        if parsed.path.lower().endswith(_ASSET_SUFFIXES):
            continue
        if absolute.rstrip("/") == base_norm or absolute in seen:
            continue
        seen.add(absolute)
        out.append(absolute)
        if len(out) >= limit:
            break
    return out


async def _fetch_page_html(http: httpx.AsyncClient, url: str, settings: Settings) -> str | None:
    """Fetch one already-SSRF-validated public URL, trimmed + non-raising.

    Redirects are DISABLED (the SSRF caller contract: a 30x cannot bounce to an
    internal address) and a non-200 is dropped. The body is trimmed to the design
    HTML cap so a huge page cannot balloon memory."""
    try:
        resp = await http.get(
            url,
            follow_redirects=False,
            timeout=settings.content_teardown_timeout_seconds,
            headers={"User-Agent": "AIOSDesignBot/1.0"},
        )
    except Exception:  # any transport error degrades to a skip (never fails the analysis)
        return None
    if resp.status_code != 200:
        return None
    return resp.text[: settings.content_design_max_html_chars]


async def fetch_site_pages(
    http: httpx.AsyncClient, site: str, *, max_pages: int, settings: Settings
) -> list[str]:
    """The default design fetcher: fetch the homepage via the shared async client, then
    up to ``max_pages - 1`` same-domain internal pages (each SSRF-guarded OFF the loop
    before fetch). Returns the collected HTML; a failed homepage yields an empty list."""
    homepage = await _fetch_page_html(http, site, settings)
    if homepage is None:
        return []
    pages = [homepage]
    for link in _same_domain_links(homepage, site, limit=max(0, max_pages - 1)):
        try:
            await asyncio.to_thread(validate_public_host, link)
        except PrivateAddressError:
            continue  # a link that resolves internal is refused (never fetched)
        html = await _fetch_page_html(http, link, settings)
        if html is not None:
            pages.append(html)
        if len(pages) >= max_pages:
            break
    return pages


def get_design_fetcher(http: HttpClientDep, settings: SettingsDep) -> DesignFetcher:
    """Dependency: the default network fetcher bound to the shared async HTTP client.
    Overridden in tests with a fake returning fixed HTML (no network)."""

    async def _fetch(site: str, max_pages: int) -> list[str]:
        return await fetch_site_pages(http, site, max_pages=max_pages, settings=settings)

    return _fetch


DesignSummarizerDep = Annotated[SystemSummarizer | None, Depends(get_design_summarizer)]
DesignGateDep = Annotated[CostGate, Depends(get_design_gate)]
DesignFetcherDep = Annotated[DesignFetcher, Depends(get_design_fetcher)]
DesignFirecrawlDep = Annotated[Firecrawl | None, Depends(get_design_firecrawl)]


async def _gather_design_evidence(
    firecrawl: Firecrawl | None,
    fetcher: DesignFetcher,
    http: httpx.AsyncClient,
    settings: Settings,
    *,
    site: str,
    max_pages: int,
) -> tuple[str, str | None]:
    """Render the target site into ``(content, screenshot_b64)`` for the analysis.

    PREFERRED: Firecrawl renders the page (JS + CSS) and returns clean markdown + a
    full-page screenshot for Claude vision. FALLBACK (Firecrawl unconfigured, or a
    runtime render failure): the plain-httpx fetcher's joined page HTML with NO
    screenshot - the old behaviour, still better than crashing. The URL is already
    SSRF-guarded by the caller."""
    if firecrawl is not None:
        page = await firecrawl.scrape(http, site, want_screenshot=settings.site_design_screenshot)
        if page is not None:
            return page.markdown, page.screenshot_b64
    pages = await fetcher(site, max_pages)
    return "\n\n".join(pages), None


@router.post("/content/site-design", response_model=SiteDesignResponse)
async def analyze_site_design(
    body: SiteDesignRequest,
    http: HttpClientDep,
    settings: SettingsDep,
    summarizer: DesignSummarizerDep,
    gate: DesignGateDep,
    firecrawl: DesignFirecrawlDep,
    fetcher: DesignFetcherDep,
    actor: PublishContent,
) -> SiteDesignResponse:
    """Extract the target site's REAL design profile so a new page can MATCH it.

    RENDERS the site via Firecrawl (runs its JS + CSS) to get clean markdown + a full-page
    SCREENSHOT, then has Claude analyze the screenshot with VISION under a strict-JSON
    design contract that also returns a self-contained ``wireframe_html`` preview. When
    Firecrawl is unconfigured (no key) or a render fails, it FALLS BACK to the plain-httpx
    fetcher (homepage + same-domain pages, no screenshot). The single paid call is metered
    under the EXISTING ``content`` money-dial (committed spend = Anthropic token cost
    only); a missing key, a dial/budget block, or an analysis failure DEGRADES (200,
    ``status='degraded'``, ``profile=null``) rather than crashing, and the gate is never
    bypassed. The site URL is SSRF-guarded OFF the event loop; the blocking Anthropic call
    + the sync gate store run off the loop via ``to_thread``."""
    # SSRF guard: getaddrinfo blocks, so validate off the event loop (invariant #2).
    try:
        await asyncio.to_thread(validate_public_host, body.site)
    except PrivateAddressError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Site is not a public address: {exc}",
        ) from exc

    max_pages = body.max_pages if body.max_pages is not None else settings.content_design_max_pages
    content, screenshot_b64 = await _gather_design_evidence(
        firecrawl, fetcher, http, settings, site=body.site, max_pages=max_pages
    )

    def _run() -> DesignResult:
        return extract_site_design(
            summarizer=summarizer,
            gate=gate,
            settings=settings,
            content=content,
            screenshot_b64=screenshot_b64,
        )

    result = await asyncio.to_thread(_run)
    profile = SiteDesignProfile.model_validate(result.profile.as_dict()) if result.profile else None
    await record_activity(
        actor, kind="content", action="analyzed target site design", target=body.site,
    )
    return SiteDesignResponse(status=result.status, profile=profile, reason=result.reason)


# --------------------------------------------------------------------------- #
# Review gate (LEAD-only; the needs_review exit)
# --------------------------------------------------------------------------- #
@router.post("/content/jobs/{code}/review", response_model=ContentJobResponse)
async def review_content_job(
    code: str,
    body: ContentReviewRequest,
    repo: ContentRepoDep,
    enqueue: ContentEnqueuerDep,
    enqueue_publish: ContentPublishEnqueuerDep,
    actor: LeadOnly,
) -> ContentJobResponse:
    """The human review gate (owner/admin/manager only). ``approve`` -> publishing
    (and enqueue the publish worker), ``edit`` -> drafting (persist the reviewer's
    guided-edit note + RE-ENQUEUE the pipeline for a GUIDED re-draft), ``reject`` ->
    rejected. 409 unless the job is in needs_review (optimistic ``expect_status``).
    All three transitions run on the RLS path, where the DB guard recognises the lead
    (its lead branch allows the status change + the ``edit_instruction`` column edit
    together)."""
    job = await asyncio.to_thread(repo.get_job_by_code, code)
    if job is None:
        raise _JOB_NOT_FOUND
    if job.get("status") != "needs_review":
        raise _NOT_IN_REVIEW

    # QA is ADVISORY, not a gate (product decision): the automated scorecard is shown
    # in the review preview for the lead to read, but approving is NOT blocked by it -
    # the human sign-off IS the quality gate. So approve always moves the draft to
    # publishing; edit/reject remain the ways to fix or drop one.
    new_status = {"approve": "publishing", "edit": "drafting", "reject": "rejected"}[body.action]
    changes: dict[str, Any] = {"status": new_status}
    if body.action == "edit":
        # Persist the reviewer's guided-edit instruction so the worker's re-draft
        # targets exactly what was asked (not a blind regen). Empty note is allowed.
        changes["edit_instruction"] = (body.note or "").strip()
        changes["stage"] = "Edit requested"
    updated = await asyncio.to_thread(
        repo.update_job_by_code, code, changes, "needs_review"
    )
    if updated is None:
        # A racing transition already moved the row (optimistic concurrency), or the
        # DB guard rejected it (defense in depth) - either way it is no longer ours.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Content job changed concurrently")

    if body.action == "approve":
        # The worker owns publishing->done on the privileged pool; hand it off.
        enqueue_publish(code)
    elif body.action == "edit":
        # The job is back at drafting (worker-owned); re-enqueue the pipeline so it
        # re-drafts applying the guided-edit instruction, then returns to review.
        enqueue(code)

    action = {
        "approve": "approved content for publishing",
        "edit": "sent content back for edits",
        "reject": "rejected content",
    }[body.action]
    client_id = job.get("client_id")
    await record_activity(
        actor, kind="content", action=action, target=job.get("client_name", ""),
        entity_type="client" if client_id is not None else None,
        entity_id=str(client_id) if client_id is not None else None,
    )
    return ContentJobResponse.from_row(updated)


# --------------------------------------------------------------------------- #
# Limited edit (LEAD-only)
# --------------------------------------------------------------------------- #
@router.patch("/content/jobs/{code}", response_model=ContentJobResponse)
async def patch_content_job(
    code: str, body: ContentJobUpdate, repo: ContentRepoDep, actor: LeadOnly
) -> ContentJobResponse:
    """Edit a job's inputs (topic/brief) - LEAD-only. Status is untouched (it moves
    only via /review and the worker). Runs on the RLS path (the DB guard's lead
    branch); an empty patch is a no-op."""
    job = await asyncio.to_thread(repo.get_job_by_code, code)
    if job is None:
        raise _JOB_NOT_FOUND

    provided = body.model_dump(exclude_unset=True)
    patch: dict[str, Any] = {}
    if provided.get("topic") is not None:
        patch["topic"] = provided["topic"]
    if "brief" in provided and provided["brief"] is not None:
        patch["brief"] = provided["brief"]

    if not patch:
        return ContentJobResponse.from_row(job)  # nothing to change

    updated = await asyncio.to_thread(repo.update_job_by_code, code, patch)
    if updated is None:
        raise _JOB_NOT_FOUND
    client_id = job.get("client_id")
    await record_activity(
        actor, kind="content", action="edited a content job", target=job.get("client_name", ""),
        entity_type="client" if client_id is not None else None,
        entity_id=str(client_id) if client_id is not None else None,
    )
    return ContentJobResponse.from_row(updated)
