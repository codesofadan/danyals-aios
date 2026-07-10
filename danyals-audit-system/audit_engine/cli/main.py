"""SEO-AUDIT-OS CLI.

`seo-audit quick <domain>` runs the deterministic Phase 1A pipeline:
sitemap discovery, crawl, on-page analyzers, scoring, and a Markdown report.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from audit_engine.analyzers.onpage import (
    check_broken_internal_links,
    check_https,
    check_keyword_cannibalization,
    check_link_equity_distribution,
    check_meta_description_uniqueness,
    check_orphan_pages,
    check_title_uniqueness,
    iter_per_page_checks,
)
from audit_engine.agents.dispatcher import (
    AgentRunResult,
    dispatch_agents,
    load_check_specs,
)
from audit_engine.analyzers.ai_search import iter_per_page_ai_search
from audit_engine.analyzers.semantic_seo import (
    iter_per_page_semantic_seo,
    iter_site_wide_semantic_seo,
)
from audit_engine.analyzers.extras import (
    check_about_contact_pages,
    check_ai_bot_crawlability,
    check_click_depth,
    check_duplicate_content,
    check_http_version,
    check_llms_txt,
    iter_cwv_findings,
    iter_per_page_extras,
    iter_psi_quality_findings,
)
from audit_engine.analyzers.local import iter_local_findings
from audit_engine.analyzers.offpage import iter_off_page_findings
from audit_engine.analyzers.technical import iter_site_wide_technical
from audit_engine.config import AUDITS_DIR, CrawlConfig, ensure_dirs, get_keys
from audit_engine.crawlers.basic import crawl
from audit_engine.db.repository import (
    AuditRun,
    AuditRunRepository,
    Finding,
    FindingRepository,
    PageRepository,
    connection,
    encode_evidence,
    initialize,
)
from audit_engine.integrations.citations import CitationsClient, CitationSummary
from audit_engine.integrations.google_nl import GoogleNLClient, NLAnalysis
from audit_engine.integrations.moz import MozClient
from audit_engine.integrations.pagespeed import PageSpeedClient
from audit_engine.integrations.places import Place, PlacesClient
from audit_engine.integrations.serper import SerperClient
from audit_engine.logging_setup import configure, get_logger
from audit_engine.security import PrivateAddressError, validate_public_host
from audit_engine.reporters import markdown as md_reporter
from audit_engine.reporters.bundle import write_full_bundle
from audit_engine.scorers.aggregator import aggregate

PKT = timezone(timedelta(hours=5), name="PKT")

app = typer.Typer(
    no_args_is_help=True,
    help="SEO-AUDIT-OS - multi-agent SEO audit system, CLI entrypoint.",
    add_completion=False,
)
console = Console()
log = get_logger(__name__)


def _now_pkt_iso() -> str:
    return datetime.now(PKT).isoformat(timespec="seconds")


def _domain_to_slug(domain: str) -> str:
    return domain.replace("https://", "").replace("http://", "").rstrip("/").replace("/", "_")


def _safe_slug(text: str) -> str:
    """Filesystem-safe slug from a free-text query."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:40] or "query"


def _title_case_slug(slug: str) -> str:
    """'amsofastudio' -> 'Amsofastudio' (last-resort brand fallback)."""
    return (slug or "").strip().capitalize() or "Brand"


def _extract_brand_name(slug: str, parsed_pages: list, business_name: str | None) -> str:
    """Pick a human-readable brand name.

    Priority: explicit override > homepage title suffix (brand usually sits after
    " | ", " · ", or " - ") > schema Organization.name > www-stripped domain slug.
    Never returns the literal "www" — that bug cost the prior run a usable brand SERP.
    """
    if business_name and business_name.strip():
        return business_name.strip()
    if parsed_pages:
        first = parsed_pages[0]
        # Schema first: Organization / LocalBusiness / *Store name property.
        for block in getattr(first, "schema_blocks", []) or []:
            if isinstance(block, dict):
                t = block.get("@type") or block.get("type") or ""
                if isinstance(t, list):
                    t = ",".join(str(x) for x in t)
                if any(k in str(t) for k in ("Organization", "LocalBusiness", "Store")):
                    n = block.get("name")
                    if isinstance(n, str) and 2 <= len(n.strip()) <= 80:
                        return n.strip()
        # Title pattern: "<value-prop> | Brand" or "Brand | <tagline>".
        title = (getattr(first, "title", "") or "").strip()
        if title:
            for sep in (" | ", " · ", " — "):
                if sep in title:
                    parts = [p.strip() for p in title.split(sep) if p.strip()]
                    if parts:
                        # Brand is usually the shortest segment (and not the value-prop).
                        return min(parts, key=len)
            # No separator: take the whole title up to 60 chars.
            return title[:60]
    # Last resort: domain slug minus a leading "www." and the TLD.
    slug_clean = re.sub(r"^www\.", "", slug or "", flags=re.IGNORECASE)
    return _title_case_slug(slug_clean.split(".")[0])


def _extract_niche_phrase(parsed_pages: list) -> str:
    """Pull a short niche/value-prop phrase from the homepage H1 — used to
    construct commercial SERP queries when no industry flag was supplied.
    e.g. H1 'Custom Sofas, Deewans & Beds Handcrafted in Lahore' -> 'Custom Sofas'."""
    if not parsed_pages:
        return ""
    h1 = ""
    h1s = getattr(parsed_pages[0], "h1s", None) or []
    if h1s:
        h1 = h1s[0]
    if not h1:
        return ""
    # Strip "in <City>", "for <Audience>", trailing brand suffix after pipes.
    h1 = re.split(r"\s+\|\s+", h1)[0]
    h1 = re.sub(r"\bin\s+[A-Z][\w-]+(\s+[A-Z][\w-]+)?\b.*$", "", h1).strip()
    # First 2-3 noun-ish words: trim at first comma / ampersand / dash.
    h1 = re.split(r"[,&]| - | — ", h1)[0].strip()
    words = h1.split()
    return " ".join(words[:3]).rstrip(",.&|") if words else ""


def _extract_city_from_corpus(parsed_pages: list) -> str | None:
    """Look for 'in <Capitalised City>' in homepage title/H1 — fallback when
    --city wasn't passed."""
    if not parsed_pages:
        return None
    blobs: list[str] = []
    first = parsed_pages[0]
    if getattr(first, "title", None):
        blobs.append(first.title)
    for h in getattr(first, "h1s", None) or []:
        blobs.append(h)
    for blob in blobs:
        m = re.search(r"\bin\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", blob or "")
        if m:
            return m.group(1).strip()
    return None


def _derive_serp_queries(
    *,
    slug: str,
    parsed_pages: list,
    business_name: str | None,
    city: str | None,
) -> list[tuple[str, str]]:
    """Build a small batch of meaningful SERP queries from the audit context.

    Always returns at least the brand query. When a city or niche phrase can be
    inferred, expands to brand+city, niche+city, and a 'best <niche> <city>'
    competitor query so C3/C4/D4 get the data they need to benchmark.
    """
    brand = _extract_brand_name(slug, parsed_pages, business_name)
    city_inferred = city or _extract_city_from_corpus(parsed_pages)
    niche = _extract_niche_phrase(parsed_pages)

    queries: list[tuple[str, str]] = [("brand", brand)]
    seen = {brand.lower()}

    def _add(label: str, q: str) -> None:
        q = " ".join(q.split())
        if q and q.lower() not in seen:
            queries.append((label, q))
            seen.add(q.lower())

    if city_inferred:
        _add("brand_geo", f"{brand} {city_inferred}")
    if niche and city_inferred:
        _add("niche_geo", f"{niche} {city_inferred}")
        _add("best_niche_geo", f"best {niche.lower()} {city_inferred}")
    elif niche:
        _add("niche", niche)
    # Cap at 5 to bound cost (Serper bills per call).
    return queries[:5]


def _enforce_public_target(domain: str) -> None:
    """SSRF + empty-input guard. Refuses to audit private/loopback/link-local
    /reserved hosts AND rejects empty or whitespace-only DOMAIN arguments.

    Runs BEFORE any side-effect (UUID, artifact dir, DB row, HTTP request)
    so a rejected target leaves no trace on disk or in the database. Exit
    code 2 matches typer's standard for bad arguments.

    Without this guard, an empty domain would: (a) skip the SSRF check
    cleanly, (b) normalize to 'https://' inside the crawler, (c) fail the
    homepage fetch with InvalidURL, (d) still walk the deterministic
    analyzer + scorer pipeline (yielding bogus 100/100 scorecards), and
    (e) write a full artifact bundle under data/audits/<uuid>/. Catching
    it here aborts cleanly with exit code 2.
    """
    if not (domain or "").strip():
        raise typer.BadParameter(
            "DOMAIN must be a non-empty domain or URL", param_hint="DOMAIN"
        )
    try:
        validate_public_host(domain)
    except PrivateAddressError as e:
        raise typer.BadParameter(str(e), param_hint="DOMAIN") from e


@app.command()
def init_db() -> None:
    """Initialize the SQLite database. Idempotent."""
    initialize()
    console.print("[green]DB initialized[/green]")


def _finding(*, run_id: int, page_id: int | None, check_id: str, owner: str, verdict: Any) -> Finding:
    """Compact builder so analyzer loops stay readable."""
    name, category, subcategory = _meta_for(check_id)
    return Finding(
        run_id=run_id,
        page_id=page_id,
        check_id=check_id,
        check_name=name,
        category=category,
        subcategory=subcategory,
        owner_agent=owner,
        status=verdict.status,
        severity=verdict.severity,
        score=verdict.score,
        confidence=verdict.confidence,
        evidence_json=encode_evidence(verdict.evidence),
        remediation=verdict.remediation,
        references_json=None,
        impact_usd=None,
    )


def _emit_extras(*, run_id: int, page_id_by_url: dict[str, int], crawl_result: Any, parsed_pages: list) -> list[Finding]:
    """Run the free deterministic extras analyzers and return their findings."""
    out: list[Finding] = []
    for cp in crawl_result.pages:
        if not cp.parsed:
            continue
        pid = page_id_by_url.get(cp.url)
        for check_id, owner, verdict in iter_per_page_extras(cp.parsed):
            out.append(_finding(run_id=run_id, page_id=pid, check_id=check_id, owner=owner, verdict=verdict))
        # Deterministic AI-search / GEO checks. Run on every page so Section
        # 04 (AI Search Visibility) is populated even when A5 LLM is skipped.
        for check_id, owner, verdict in iter_per_page_ai_search(cp.parsed):
            out.append(_finding(run_id=run_id, page_id=pid, check_id=check_id, owner=owner, verdict=verdict))
        # Module 3 - Semantic SEO + Topical Authority + Koray Framework
        # (per-page slice). Site-wide checks fire in the run-level loop.
        for check_id, owner, verdict in iter_per_page_semantic_seo(cp.parsed):
            out.append(_finding(run_id=run_id, page_id=pid, check_id=check_id, owner=owner, verdict=verdict))
    # Module 3 site-wide rollups: topical clusters, hub-spoke links,
    # cross-page n-gram overlap, knowledge-domain consistency.
    if parsed_pages:
        for check_id, owner, verdict in iter_site_wide_semantic_seo(parsed_pages):
            out.append(_finding(run_id=run_id, page_id=None, check_id=check_id, owner=owner, verdict=verdict))
    # Site-wide
    if parsed_pages:
        v_dup = check_duplicate_content(parsed_pages)
        out.append(_finding(run_id=run_id, page_id=None, check_id="ON-090", owner="A1", verdict=v_dup))
        v_ac = check_about_contact_pages(parsed_pages)
        out.append(_finding(run_id=run_id, page_id=None, check_id="ON-107", owner="A1", verdict=v_ac))
        v_meta = check_meta_description_uniqueness(parsed_pages)
        for url, verdict in v_meta.items():
            out.append(_finding(run_id=run_id, page_id=page_id_by_url.get(url), check_id="ON-040", owner="A3", verdict=verdict))
    v_equity = check_link_equity_distribution(crawl_result.pages)
    out.append(_finding(run_id=run_id, page_id=None, check_id="ON-062", owner="A4", verdict=v_equity))
    v_depth = check_click_depth(crawl_result.pages, crawl_result.site_url)
    out.append(_finding(run_id=run_id, page_id=None, check_id="TECH-090", owner="B1", verdict=v_depth))
    out.append(_finding(run_id=run_id, page_id=None, check_id="ON-060", owner="A4", verdict=v_depth))
    # HTTP version (use homepage CrawledPage)
    home = next((cp for cp in crawl_result.pages if cp.url == crawl_result.site_url), None) or (crawl_result.pages[0] if crawl_result.pages else None)
    if home is not None:
        out.append(_finding(run_id=run_id, page_id=page_id_by_url.get(home.url), check_id="TECH-069", owner="B5", verdict=check_http_version(home)))
    # AI bot crawlability (from robots.txt raw body)
    robots_raw = None
    robots = getattr(crawl_result, "robots", None)
    if robots is not None:
        robots_raw = getattr(robots, "raw", None)
    v_ai = check_ai_bot_crawlability(robots_raw)
    out.append(_finding(run_id=run_id, page_id=None, check_id="TECH-040", owner="A5", verdict=v_ai))
    return out


def _emit_psi_findings(*, run_id: int, page_id: int | None, psi_result: Any) -> list[Finding]:
    """Per-metric CWV findings + Lighthouse category findings from a PSI result."""
    out: list[Finding] = []
    for check_id, owner, verdict in iter_cwv_findings(psi_result):
        out.append(_finding(run_id=run_id, page_id=page_id, check_id=check_id, owner=owner, verdict=verdict))
    for check_id, owner, verdict in iter_psi_quality_findings(psi_result):
        out.append(_finding(run_id=run_id, page_id=page_id, check_id=check_id, owner=owner, verdict=verdict))
    return out


async def _emit_llms_txt(*, run_id: int, site_url: str) -> Finding:
    v = await check_llms_txt(site_url)
    return _finding(run_id=run_id, page_id=None, check_id="TECH-041", owner="A5", verdict=v)


async def _emit_google_nl_snapshot(
    *,
    artifact_dir: Path,
    crawl_result: Any,
) -> NLAnalysis | None:
    """Run Google Cloud NL on the homepage body text (+ top 2 deep pages).

    Writes the merged entities + categories + sentiment to
    `artifact_dir/google-nl.json` for downstream agent context. Returns None
    when no key is configured. The data is also consumed inline by the
    semantic-SEO entity-coverage analyzer when available.
    """
    keys = get_keys()
    if not keys.google_nl:
        return None
    parsed = [cp.parsed for cp in crawl_result.pages if cp.parsed and (cp.parsed.body_text or "")]
    if not parsed:
        return None
    home = next((p for p in parsed if p.url == crawl_result.site_url), parsed[0])
    # Sample: homepage + top-2 longest content pages so we capture domain
    # entities without burning the quota on the entire crawl.
    others = sorted(
        (p for p in parsed if p.url != home.url),
        key=lambda p: -(p.word_count or 0),
    )[:2]
    sample = [home, *others]
    combined_text = "\n\n".join((p.body_text or "")[:8000] for p in sample)
    if len(combined_text.strip()) < 200:
        return None
    try:
        async with GoogleNLClient(api_key=keys.google_nl) as client:
            result = await client.analyze(combined_text, want_categories=True, want_sentiment=True)
    except Exception as e:  # noqa: BLE001
        console.print(f"  [yellow]Google NL failed: {type(e).__name__}: {e}[/yellow]")
        return None
    payload = {
        "sample_pages": [p.url for p in sample],
        "entities": [
            {"name": e.name, "type": e.type, "salience": round(e.salience, 4),
             "wikipedia_url": e.wikipedia_url, "mid": e.mid,
             "mention_count": e.mention_count}
            for e in result.top_entities
        ],
        "categories": [{"name": c.name, "confidence": round(c.confidence, 3)} for c in result.categories],
        "sentiment_score": result.sentiment_score,
        "sentiment_magnitude": result.sentiment_magnitude,
        "language": result.language,
        "error": result.error,
    }
    (artifact_dir / "google-nl.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    if result.error:
        console.print(f"  [yellow]Google NL: {result.error}[/yellow]")
    else:
        console.print(
            f"  Google NL: [cyan]{len(result.entities)} entities[/cyan], "
            f"[cyan]{len(result.categories)} categories[/cyan], "
            f"sentiment {result.sentiment_score:.2f}" if result.sentiment_score is not None else
            f"  Google NL: [cyan]{len(result.entities)} entities[/cyan], "
            f"[cyan]{len(result.categories)} categories[/cyan]"
        )
    return result


async def _emit_agent_findings(
    *,
    run_id: int,
    page_id_by_url: dict[str, int],
    crawl_result: Any,
    deterministic_findings: list[dict[str, Any]],
    teams: list[str] | None = None,
    only_agents: list[str] | None = None,
) -> list[Finding]:
    """Run the 21 specialist agents in parallel and convert their JSON output
    into Finding rows. Empty if no key or SDK missing.
    """
    result = await dispatch_agents(
        crawl_result=crawl_result,
        deterministic_findings=deterministic_findings,
        teams=teams,
        only_agents=only_agents,
    )
    if not result.findings:
        console.print("[dim]Agents returned no findings (no key or all skipped).[/dim]")
        return []

    # Per-agent + check lookup so we can hydrate name/category for each finding
    specs = {c.id: c for c in load_check_specs()}
    out: list[Finding] = []
    for f in result.findings:
        cid = f["check_id"]
        spec = specs.get(cid)
        url = f.get("url")
        pid = page_id_by_url.get(url) if url else None
        name, category, subcategory = _meta_for(cid)
        if spec:
            name = name if name != cid else spec.name
            category = category if category != "on-page" else spec.category
            subcategory = subcategory if subcategory is not None else spec.subcategory
        out.append(
            Finding(
                run_id=run_id,
                page_id=pid,
                check_id=cid,
                check_name=name,
                category=category,
                subcategory=subcategory,
                owner_agent=f.get("_agent", spec.owner_agent if spec else ""),
                status=f["status"],
                severity=f["severity"],
                score=f["score"],
                confidence=f["confidence"],
                evidence_json=encode_evidence(f["evidence"] or {}),
                remediation=f.get("remediation"),
                references_json=None,
                impact_usd=None,
            )
        )

    table = Table(title="Agent dispatch")
    table.add_column("Agent")
    table.add_column("Findings", justify="right")
    for short, count in sorted(result.per_agent_counts.items()):
        table.add_row(short, str(count))
    console.print(table)
    console.print(
        f"[green]Agents emitted {len(out)} findings across {len(result.per_agent_counts)} specialists.[/green]"
    )
    return out


def _resolve_optional_ai(mode: str, label: str, cost_hint: str) -> bool:
    """Translate off/on/ask into a bool, prompting the user if 'ask'."""
    mode = (mode or "ask").lower()
    if mode == "on":
        return True
    if mode == "off":
        return False
    keys = get_keys()
    if not keys.anthropic:
        console.print(f"[dim]No ANTHROPIC_API_KEY set; skipping {label}.[/dim]")
        return False
    try:
        import sys as _sys

        if not _sys.stdin.isatty():
            return False
        console.print()
        return bool(typer.confirm(f"Run {label}? ({cost_hint})", default=False))
    except Exception:  # noqa: BLE001
        return False


async def _maybe_dispatch_ai_search_agents(
    *,
    run_id: int,
    page_id_by_url: dict[str, int],
    crawl_result: Any,
    findings: list[Finding],
    include_brand_authority: bool,
) -> list[Finding]:
    """Always-on AI-search fallback dispatch.

    When the user said NO to the full agents pass but ANTHROPIC_API_KEY is
    set, run only A5 (GEO/AI Search) and optionally C4 (Brand/AI Authority)
    so Section 04 of the report never falls back to canned placeholders.

    Total cost: ~$0.10-0.30 per audit on Sonnet 4.6 (one or two agent calls).
    """
    keys = get_keys()
    if not keys.anthropic:
        return []
    only = ["A5"] + (["C4"] if include_brand_authority else [])
    console.print(f"[bold]> Dispatching AI-search analysts ({', '.join(only)})...[/bold]")
    deterministic_shaped = [
        {
            "check_id": f.check_id,
            "check_name": f.check_name,
            "status": f.status,
            "severity": f.severity,
            "score": f.score,
            "evidence_json": f.evidence_json,
        }
        for f in findings
    ]
    try:
        return await _emit_agent_findings(
            run_id=run_id,
            page_id_by_url=page_id_by_url,
            crawl_result=crawl_result,
            deterministic_findings=deterministic_shaped,
            only_agents=only,
        )
    except Exception as e:  # noqa: BLE001
        console.print(f"  [yellow]AI-search fallback dispatch failed: {type(e).__name__}: {e}[/yellow]")
        return []


def _resolve_ai_narrative(mode: str) -> bool:
    """Translate --ai-narrative mode into a bool. See _resolve_optional_ai."""
    return _resolve_optional_ai(mode, "the AI-narrated report", "~$0.05-0.15 per audit")


def _resolve_agents(mode: str) -> bool:
    """Translate --agents mode into a bool. Fires the 21 specialist agents."""
    return _resolve_optional_ai(mode, "the 21 specialist agents", "~$0.50-2 per audit on Sonnet 4.6")


@app.command()
def quick(
    domain: str = typer.Argument(..., help="Domain or full URL to audit"),
    profile: str = typer.Option("general", "--profile", help="local | ecommerce | saas | content | general"),
    max_pages: int = typer.Option(20, "--max-pages", help="Cap on pages crawled"),
    mode: str = typer.Option(
        "auto",
        "--mode",
        help="auto | paid | free. 'free' disables every paid integration (PSI, Moz, agents, AI narrative); "
             "'paid' is equivalent to 'auto' for quick mode; 'auto' uses whatever keys are configured.",
    ),
    psi: bool = typer.Option(True, "--psi/--no-psi", help="Run PageSpeed Insights on homepage"),
    moz: bool = typer.Option(False, "--moz/--no-moz", help="Quick mode does not call Moz; flag accepted for parity with /audit (full)."),
    ai_narrative: str = typer.Option("ask", "--ai-narrative", help="off | on | ask (prompt at runtime)"),
    agents: str = typer.Option("ask", "--agents", help="off | on | ask - run the 21 specialist agents (paid)"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Run the fast deterministic audit pipeline (Phase 1A)."""
    _enforce_public_target(domain)
    configure(log_level)
    ensure_dirs()
    mode = (mode or "auto").lower().strip()
    if mode not in ("auto", "paid", "free"):
        console.print(f"[red]Invalid --mode {mode!r}. Use auto, paid, or free.[/red]")
        raise typer.Exit(code=2)
    if mode == "free":
        # Hard guard: free mode never touches paid integrations regardless of
        # whether the caller passed --psi/--agents/--ai-narrative explicitly.
        psi = False
        ai_narrative = "off"
        agents = "off"
    use_ai = _resolve_ai_narrative(ai_narrative)
    use_agents = _resolve_agents(agents)
    asyncio.run(_run_quick(domain=domain, profile=profile, max_pages=max_pages, psi=psi, use_ai=use_ai, use_agents=use_agents))


async def _run_quick(*, domain: str, profile: str, max_pages: int, psi: bool, use_ai: bool = False, use_agents: bool = False) -> None:
    run_uuid = str(uuid.uuid4())
    started_at = _now_pkt_iso()
    slug = _domain_to_slug(domain)
    artifact_dir = AUDITS_DIR / slug / run_uuid
    artifact_dir.mkdir(parents=True, exist_ok=True)

    console.rule(f"[bold]/audit-quick {domain}[/bold]")
    console.print(f"Run UUID: [cyan]{run_uuid}[/cyan]")
    console.print(f"Artifact dir: [cyan]{artifact_dir}[/cyan]")
    console.print()

    t0 = time.monotonic()

    # ----- Persist run in DB -----
    with connection() as conn:
        run = AuditRunRepository.create(
            conn,
            AuditRun(
                run_uuid=run_uuid,
                domain=domain,
                profile=profile,
                command="/audit-quick",
                args_json=json.dumps({"max_pages": max_pages, "psi": psi}),
                status="running",
                started_at=started_at,
                artifact_dir=str(artifact_dir),
            ),
        )
    run_id = run.id
    assert run_id is not None
    console.print(f"DB run id: [cyan]{run_id}[/cyan]")

    # ----- Crawl -----
    console.print("[bold]> Crawling...[/bold]")
    cfg = CrawlConfig(max_pages_quick=max_pages)
    crawl_result = await crawl(domain, config=cfg, max_pages=max_pages)
    parsed_pages = [cp.parsed for cp in crawl_result.pages if cp.parsed]
    console.print(
        f"  discovered={len(crawl_result.discovered_urls)} fetched={len(crawl_result.pages)} parsed={len(parsed_pages)} "
        f"crawl_time={crawl_result.duration_sec:.1f}s"
    )

    # ----- Persist pages -----
    page_id_by_url: dict[str, int] = {}
    with connection() as conn:
        for cp in crawl_result.pages:
            pid = PageRepository.upsert(
                conn,
                run_id,
                url=cp.url,
                canonical_url=(cp.parsed.canonical if cp.parsed else None),
                http_status=cp.http_status,
                response_ms=cp.response_ms,
                title=(cp.parsed.title if cp.parsed else None),
                meta_description=(cp.parsed.meta_description if cp.parsed else None),
                h1=(cp.parsed.h1s[0] if cp.parsed and cp.parsed.h1s else None),
                word_count=(cp.parsed.word_count if cp.parsed else None),
                indexable=(cp.parsed and not cp.parsed.has_noindex) if cp.parsed else None,
            )
            page_id_by_url[cp.url] = pid

    # ----- PSI (homepage only for quick) -----
    psi_findings: list[Finding] = []
    keys = get_keys()
    if psi:
        console.print("[bold]> Running PageSpeed Insights (homepage)...[/bold]")
        try:
            async with PageSpeedClient(api_key=keys.google_pagespeed) as client:
                psi_result = await client.analyze(crawl_result.site_url, strategy="mobile")
            ev = {
                "lighthouse_scores": psi_result.lighthouse_scores,
                "lab_metrics": [m.__dict__ for m in psi_result.lab_metrics],
                "field_metrics": [m.__dict__ for m in psi_result.field_metrics],
                "opportunity_count": len(psi_result.opportunities),
            }
            perf_score = psi_result.lighthouse_scores.get("performance")
            if perf_score is not None:
                score = round(perf_score / 10.0, 1)
                psi_findings.append(
                    Finding(
                        run_id=run_id,
                        page_id=page_id_by_url.get(crawl_result.site_url),
                        check_id="TECH-010",
                        check_name="Website speed checker by page speed insight",
                        category="technical",
                        subcategory="performance",
                        owner_agent="B2",
                        status=("pass" if score >= 9 else "warn" if score >= 6 else "fail"),
                        severity=("info" if score >= 9 else "major"),
                        score=score,
                        confidence=1.0,
                        evidence_json=encode_evidence(ev),
                        remediation=(
                            None
                            if score >= 9
                            else f"Lighthouse perf score {perf_score}/100; address top opportunities."
                        ),
                        references_json=None,
                        impact_usd=None,
                    )
                )
            else:
                console.print("  [yellow]PSI returned no performance score[/yellow]")
            # Per-metric CWV + Lighthouse category findings (free, derived from same PSI call)
            psi_findings.extend(_emit_psi_findings(
                run_id=run_id,
                page_id=page_id_by_url.get(crawl_result.site_url),
                psi_result=psi_result,
            ))
        except Exception as e:  # noqa: BLE001
            console.print(f"  [red]PSI failed: {type(e).__name__}: {e}[/red]")

    # ----- Run per-page analyzers -----
    console.print("[bold]> Running on-page analyzers...[/bold]")
    findings: list[Finding] = list(psi_findings)

    # Per-page checks
    for cp in crawl_result.pages:
        if not cp.parsed:
            continue
        pid = page_id_by_url.get(cp.url)
        for check_id, owner, verdict in iter_per_page_checks(cp.parsed):
            findings.append(
                Finding(
                    run_id=run_id,
                    page_id=pid,
                    check_id=check_id,
                    check_name=_check_name_for(check_id),
                    category=_category_for(check_id),
                    subcategory=None,
                    owner_agent=owner,
                    status=verdict.status,
                    severity=verdict.severity,
                    score=verdict.score,
                    confidence=verdict.confidence,
                    evidence_json=encode_evidence(verdict.evidence),
                    remediation=verdict.remediation,
                    references_json=None,
                    impact_usd=None,
                )
            )
        # HTTPS (page-level check applied to homepage only for quick)
        if cp.url == crawl_result.site_url:
            v = check_https(cp)
            findings.append(
                Finding(
                    run_id=run_id,
                    page_id=pid,
                    check_id="ON-099",
                    check_name="HTTPS validation",
                    category="on-page",
                    subcategory="security",
                    owner_agent="B5",
                    status=v.status,
                    severity=v.severity,
                    score=v.score,
                    confidence=v.confidence,
                    evidence_json=encode_evidence(v.evidence),
                    remediation=v.remediation,
                    references_json=None,
                    impact_usd=None,
                )
            )

    # Site-wide checks
    if parsed_pages:
        v_uniq = check_title_uniqueness(parsed_pages)
        for url, verdict in v_uniq.items():
            findings.append(
                Finding(
                    run_id=run_id,
                    page_id=page_id_by_url.get(url),
                    check_id="ON-036",
                    check_name="Title uniqueness check",
                    category="on-page",
                    subcategory="titles",
                    owner_agent="A3",
                    status=verdict.status,
                    severity=verdict.severity,
                    score=verdict.score,
                    confidence=verdict.confidence,
                    evidence_json=encode_evidence(verdict.evidence),
                    remediation=verdict.remediation,
                    references_json=None,
                    impact_usd=None,
                )
            )
        v_cann = check_keyword_cannibalization(parsed_pages)
        findings.append(
            Finding(
                run_id=run_id,
                page_id=None,
                check_id="ON-013",
                check_name="Keyword cannibalization detection",
                category="on-page",
                subcategory="keywords",
                owner_agent="A2",
                status=v_cann.status,
                severity=v_cann.severity,
                score=v_cann.score,
                confidence=v_cann.confidence,
                evidence_json=encode_evidence(v_cann.evidence),
                remediation=v_cann.remediation,
                references_json=None,
                impact_usd=None,
            )
        )

    v_broken = check_broken_internal_links(crawl_result.pages)
    findings.append(
        Finding(
            run_id=run_id,
            page_id=None,
            check_id="ON-063",
            check_name="Broken internal links detection",
            category="on-page",
            subcategory="internal-links",
            owner_agent="A4",
            status=v_broken.status,
            severity=v_broken.severity,
            score=v_broken.score,
            confidence=v_broken.confidence,
            evidence_json=encode_evidence(v_broken.evidence),
            remediation=v_broken.remediation,
            references_json=None,
            impact_usd=None,
        )
    )

    if crawl_result.discovered_urls:
        v_orphan = check_orphan_pages(crawl_result.discovered_urls, crawl_result.pages)
        findings.append(
            Finding(
                run_id=run_id,
                page_id=None,
                check_id="ON-061",
                check_name="Orphan page detection",
                category="on-page",
                subcategory="internal-links",
                owner_agent="A4",
                status=v_orphan.status,
                severity=v_orphan.severity,
                score=v_orphan.score,
                confidence=v_orphan.confidence,
                evidence_json=encode_evidence(v_orphan.evidence),
                remediation=v_orphan.remediation,
                references_json=None,
                impact_usd=None,
            )
        )

    # ----- Free extras (URL slug, image filenames, readability, etc) -----
    console.print("[bold]> Running free deterministic extras + AI-search analyzers...[/bold]")
    findings.extend(_emit_extras(run_id=run_id, page_id_by_url=page_id_by_url, crawl_result=crawl_result, parsed_pages=parsed_pages))
    try:
        findings.append(await _emit_llms_txt(run_id=run_id, site_url=crawl_result.site_url))
    except Exception as e:  # noqa: BLE001
        console.print(f"  [yellow]llms.txt check failed: {type(e).__name__}: {e}[/yellow]")

    # ----- Google Cloud NL: entity + category + sentiment snapshot -----
    # Free for the first ~5k units/month. Skipped silently when no key.
    try:
        await _emit_google_nl_snapshot(artifact_dir=artifact_dir, crawl_result=crawl_result)
    except Exception as e:  # noqa: BLE001
        console.print(f"  [yellow]Google NL snapshot failed: {type(e).__name__}: {e}[/yellow]")

    # ----- Specialist agents (paid, opt-in) -----
    if use_agents:
        console.print("[bold]> Dispatching the 21 specialist agents (parallel)...[/bold]")
        deterministic_shaped = [
            {
                "check_id": f.check_id,
                "check_name": f.check_name,
                "status": f.status,
                "severity": f.severity,
                "score": f.score,
                "evidence_json": f.evidence_json,
            }
            for f in findings
        ]
        try:
            agent_findings = await _emit_agent_findings(
                run_id=run_id,
                page_id_by_url=page_id_by_url,
                crawl_result=crawl_result,
                deterministic_findings=deterministic_shaped,
                teams=["onpage", "technical", "local"],  # /quick: skip off-page
            )
            findings.extend(agent_findings)
        except Exception as e:  # noqa: BLE001
            console.print(f"  [yellow]Agent dispatch failed: {type(e).__name__}: {e}[/yellow]")
    else:
        # Always run A5 (AI Search) when an Anthropic key exists - quick mode
        # skips C4 to keep cost minimal.
        findings.extend(
            await _maybe_dispatch_ai_search_agents(
                run_id=run_id,
                page_id_by_url=page_id_by_url,
                crawl_result=crawl_result,
                findings=findings,
                include_brand_authority=False,
            )
        )

    # ----- Persist findings -----
    with connection() as conn:
        FindingRepository.insert_many(conn, findings)
        all_findings = FindingRepository.by_run(conn, run_id)

    # ----- Score -----
    scores = aggregate(all_findings, profile=profile)

    # ----- Report bundle (MD + HTML + PDF) -----
    duration = time.monotonic() - t0
    paths = write_full_bundle(
        artifact_dir=artifact_dir,
        domain=domain,
        run_uuid=run_uuid,
        profile=profile,
        started_at=started_at,
        duration_sec=duration,
        pages_crawled=len(crawl_result.pages),
        scores=scores,
        findings=all_findings,
        ai_narrative=use_ai,
    )

    # ----- Finalize DB row -----
    with connection() as conn:
        AuditRunRepository.finalize(
            conn,
            run_id,
            status="succeeded",
            duration_sec=duration,
            pages_crawled=len(crawl_result.pages),
            scores=scores,
        )

    # ----- Print summary table -----
    console.print()
    table = Table(title="Scorecard")
    table.add_column("Dimension")
    table.add_column("Score", justify="right")
    table.add_row("Overall", str(scores.get("overall") or "-"))
    table.add_row("On-Page", str(scores.get("on_page") or "-"))
    table.add_row("Technical", str(scores.get("technical") or "-"))
    table.add_row("Off-Page", str(scores.get("off_page") or "-"))
    table.add_row("Local SEO", str(scores.get("local") or "-"))
    console.print(table)
    console.print()
    console.print(f"Findings: [cyan]{len(all_findings)}[/cyan]")
    sev_counts = {}
    for f in all_findings:
        sev_counts[f["severity"]] = sev_counts.get(f["severity"], 0) + 1
    console.print(f"  by severity: {sev_counts}")
    console.print()
    console.print(f"[green]Done in {duration:.1f}s[/green]")
    console.print(f"Reports: [cyan]{paths['report_executive']}[/cyan]")


# ----- Check name + category lookup -----
_CHECKLIST_META: dict[str, tuple[str, str, str | None]] = {
    spec.id: (spec.name, spec.category, spec.subcategory)
    for spec in load_check_specs()
}

_CHECK_META_OVERRIDES = {
    "TECH-040": ("AI bot crawlability (robots.txt scan)", "technical", "geo-ai"),
    "TECH-041": ("llms.txt presence check", "technical", "geo-ai"),
    "TECH-069": ("HTTP version (HTTP/2 or HTTP/3)", "technical", "performance"),
    "TECH-090": ("Click-depth distribution", "technical", "site-structure"),
    "ON-090": ("Duplicate content detection (Jaccard)", "on-page", "content-quality"),
    "ON-107": ("About + Contact page presence (E-E-A-T trust)", "on-page", "content-quality"),
    "ON-099": ("HTTPS validation", "on-page", "security"),
}


@app.command()
def full(
    domain: str = typer.Argument(..., help="Domain or full URL to audit"),
    profile: str = typer.Option("general", "--profile", help="local | ecommerce | saas | content | general. Use 'local' for local-market businesses to unlock Places + citations + Team D."),
    max_pages: int = typer.Option(100, "--max-pages"),
    mode: str = typer.Option(
        "auto",
        "--mode",
        help="auto | paid | free. 'free' disables every paid integration regardless of keys; "
             "'paid' requires all paid integrations to be configured; 'auto' uses what is configured.",
    ),
    psi: bool = typer.Option(True, "--psi/--no-psi"),
    moz: bool = typer.Option(False, "--moz/--no-moz", help="Backlink data is out of scope; off by default. Set --moz only if you've explicitly added Moz keys for a one-off run."),
    serper: bool = typer.Option(True, "--serper/--no-serper"),
    places: bool = typer.Option(True, "--places/--no-places", help="When profile=local, query Google Places for GBP data (categories, photos, hours, reviews)."),
    citations: bool = typer.Option(True, "--citations/--no-citations", help="When profile=local, discover tier-1 directory presence + infer NAP via Serper."),
    business_name: str = typer.Option(None, "--business-name", help="Override the business name passed to Places (default: derive from homepage title)."),
    city: str = typer.Option(None, "--city", help="City to scope Places search (recommended for accuracy)."),
    ai_narrative: str = typer.Option("ask", "--ai-narrative", help="off | on | ask (prompt at runtime)"),
    agents: str = typer.Option("ask", "--agents", help="off | on | ask - run the 21 specialist agents (paid)"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Run the full audit pipeline (Phase 2): on-page + technical + local + AI visibility.

    Required paid integrations (when in paid/auto mode): Serper + Google API
    (PSI + Places). Citation discovery is Serper-driven; no separate citations
    provider is needed. AI visibility is handled without a paid API via
    Serper's AI Overview block + optional Claude probe + manual checklist.

    Backlinks are intentionally out of scope. Moz is disabled by default.

    Modes:
      auto  (default) - use whichever paid APIs have keys in .env
      free            - skip Serper, Places entirely; produce a structurally
                        complete audit using only crawl + schema + on-site
                        signals + free PSI (rate-limited)
      paid            - require Serper + Google to be configured;
                        fail loudly otherwise
    """
    _enforce_public_target(domain)
    configure(log_level)
    ensure_dirs()
    mode = mode.lower().strip()
    if mode not in ("auto", "paid", "free"):
        console.print(f"[red]Invalid --mode {mode!r}. Use auto, paid, or free.[/red]")
        raise typer.Exit(code=2)
    if mode == "free":
        psi = False
        moz = False
        serper = False
        places = False
        citations = False
    elif mode == "paid":
        # Every paid integration is OPTIONAL. When a key is missing the
        # affected integration returns a stub and the audit continues -
        # findings.json will simply not contain that dimension's data and
        # the PDF will render against everything else. We warn so the
        # operator knows what was skipped, but never fail the run.
        keys = get_keys()
        missing: list[str] = []
        if not keys.serper:
            missing.append("SERPER_API_KEY (SERP + competitor identification will be skipped)")
            serper = False
        if not keys.google_pagespeed:
            missing.append("GOOGLE_PAGESPEED_API_KEY (page speed scores will be skipped)")
            psi = False
        if not keys.google_places:
            missing.append("GOOGLE_PLACES_API_KEY (GBP discovery will be skipped)")
            places = False
        if missing:
            console.print(
                f"[yellow]--mode paid: continuing without these keys: {missing}. "
                "Each missing integration is skipped gracefully; the rest of the audit runs.[/yellow]"
            )
    use_ai = _resolve_ai_narrative(ai_narrative)
    use_agents = _resolve_agents(agents)
    asyncio.run(
        _run_full(
            domain=domain,
            profile=profile,
            max_pages=max_pages,
            psi=psi,
            use_ai=use_ai,
            use_agents=use_agents,
            moz=moz,
            serper=serper,
            places=places,
            citations=citations,
            business_name=business_name,
            city=city,
            mode=mode,
        )
    )


async def _run_full(
    *,
    domain: str,
    profile: str,
    max_pages: int,
    psi: bool,
    moz: bool,
    serper: bool,
    places: bool = True,
    citations: bool = True,
    business_name: str | None = None,
    city: str | None = None,
    use_ai: bool = False,
    use_agents: bool = False,
    mode: str = "auto",
) -> None:
    run_uuid = str(uuid.uuid4())
    started_at = _now_pkt_iso()
    slug = _domain_to_slug(domain)
    artifact_dir = AUDITS_DIR / slug / run_uuid
    artifact_dir.mkdir(parents=True, exist_ok=True)

    console.rule(f"[bold]/audit {domain} (full)[/bold]")
    console.print(f"Run UUID: [cyan]{run_uuid}[/cyan]")
    console.print(f"Artifact dir: [cyan]{artifact_dir}[/cyan]")
    console.print()

    t0 = time.monotonic()

    with connection() as conn:
        run = AuditRunRepository.create(
            conn,
            AuditRun(
                run_uuid=run_uuid,
                domain=domain,
                profile=profile,
                command="/audit",
                args_json=json.dumps(
                    {
                        "max_pages": max_pages,
                        "psi": psi,
                        "moz": moz,
                        "serper": serper,
                        "places": places,
                        "citations": citations,
                        "business_name": business_name,
                        "city": city,
                        "mode": mode,
                    }
                ),
                status="running",
                started_at=started_at,
                artifact_dir=str(artifact_dir),
            ),
        )
    run_id = run.id
    assert run_id is not None

    # ----- Crawl -----
    console.print("[bold]> Crawling...[/bold]")
    cfg = CrawlConfig(max_pages_full=max_pages, max_pages_quick=max_pages)
    crawl_result = await crawl(domain, config=cfg, max_pages=max_pages)
    parsed_pages = [cp.parsed for cp in crawl_result.pages if cp.parsed]
    console.print(
        f"  discovered={len(crawl_result.discovered_urls)} fetched={len(crawl_result.pages)} parsed={len(parsed_pages)}"
        f" crawl_time={crawl_result.duration_sec:.1f}s"
    )

    # ----- Persist pages -----
    page_id_by_url: dict[str, int] = {}
    with connection() as conn:
        for cp in crawl_result.pages:
            pid = PageRepository.upsert(
                conn,
                run_id,
                url=cp.url,
                canonical_url=(cp.parsed.canonical if cp.parsed else None),
                http_status=cp.http_status,
                response_ms=cp.response_ms,
                title=(cp.parsed.title if cp.parsed else None),
                meta_description=(cp.parsed.meta_description if cp.parsed else None),
                h1=(cp.parsed.h1s[0] if cp.parsed and cp.parsed.h1s else None),
                word_count=(cp.parsed.word_count if cp.parsed else None),
                indexable=(cp.parsed and not cp.parsed.has_noindex) if cp.parsed else None,
            )
            page_id_by_url[cp.url] = pid

    findings: list[Finding] = []
    keys = get_keys()

    # ----- PSI (homepage only for now) -----
    if psi:
        console.print("[bold]> PageSpeed Insights (homepage)...[/bold]")
        try:
            async with PageSpeedClient(api_key=keys.google_pagespeed) as psi_client:
                psi_result = await psi_client.analyze(crawl_result.site_url, strategy="mobile")
            perf_score = psi_result.lighthouse_scores.get("performance")
            if perf_score is not None:
                score = round(perf_score / 10.0, 1)
                findings.append(
                    Finding(
                        run_id=run_id,
                        page_id=page_id_by_url.get(crawl_result.site_url),
                        check_id="TECH-010",
                        check_name=_check_name_for("TECH-010"),
                        category="technical",
                        subcategory="performance",
                        owner_agent="B2",
                        status=("pass" if score >= 9 else "warn" if score >= 6 else "fail"),
                        severity=("info" if score >= 9 else "major"),
                        score=score,
                        confidence=1.0,
                        evidence_json=encode_evidence(
                            {
                                "lighthouse_scores": psi_result.lighthouse_scores,
                                "field_metrics": [m.__dict__ for m in psi_result.field_metrics],
                                "opportunity_count": len(psi_result.opportunities),
                            }
                        ),
                        remediation=(
                            None if score >= 9 else f"Lighthouse perf {perf_score}/100; address top opportunities."
                        ),
                        references_json=None,
                        impact_usd=None,
                    )
                )
            # Per-metric CWV + Lighthouse category findings
            findings.extend(_emit_psi_findings(
                run_id=run_id,
                page_id=page_id_by_url.get(crawl_result.site_url),
                psi_result=psi_result,
            ))
        except Exception as e:  # noqa: BLE001
            console.print(f"  [yellow]PSI failed: {type(e).__name__}: {e}[/yellow]")

    # ----- Per-page on-page analyzers -----
    console.print("[bold]> Running on-page analyzers...[/bold]")
    for cp in crawl_result.pages:
        if not cp.parsed:
            continue
        pid = page_id_by_url.get(cp.url)
        for check_id, owner, verdict in iter_per_page_checks(cp.parsed):
            findings.append(
                Finding(
                    run_id=run_id,
                    page_id=pid,
                    check_id=check_id,
                    check_name=_check_name_for(check_id),
                    category=_category_for(check_id),
                    subcategory=None,
                    owner_agent=owner,
                    status=verdict.status,
                    severity=verdict.severity,
                    score=verdict.score,
                    confidence=verdict.confidence,
                    evidence_json=encode_evidence(verdict.evidence),
                    remediation=verdict.remediation,
                    references_json=None,
                    impact_usd=None,
                )
            )
        if cp.url == crawl_result.site_url:
            v = check_https(cp)
            findings.append(
                Finding(
                    run_id=run_id,
                    page_id=pid,
                    check_id="ON-099",
                    check_name=_check_name_for("ON-099"),
                    category="on-page",
                    subcategory="security",
                    owner_agent="B5",
                    status=v.status,
                    severity=v.severity,
                    score=v.score,
                    confidence=v.confidence,
                    evidence_json=encode_evidence(v.evidence),
                    remediation=v.remediation,
                    references_json=None,
                    impact_usd=None,
                )
            )

    # Site-wide on-page rollups
    if parsed_pages:
        for url, verdict in check_title_uniqueness(parsed_pages).items():
            findings.append(
                Finding(
                    run_id=run_id,
                    page_id=page_id_by_url.get(url),
                    check_id="ON-036",
                    check_name=_check_name_for("ON-036"),
                    category="on-page",
                    subcategory="titles",
                    owner_agent="A3",
                    status=verdict.status,
                    severity=verdict.severity,
                    score=verdict.score,
                    confidence=verdict.confidence,
                    evidence_json=encode_evidence(verdict.evidence),
                    remediation=verdict.remediation,
                    references_json=None,
                    impact_usd=None,
                )
            )
        v_cann = check_keyword_cannibalization(parsed_pages)
        findings.append(
            Finding(
                run_id=run_id, page_id=None, check_id="ON-013",
                check_name=_check_name_for("ON-013"), category="on-page",
                subcategory="keywords", owner_agent="A2",
                status=v_cann.status, severity=v_cann.severity, score=v_cann.score,
                confidence=v_cann.confidence,
                evidence_json=encode_evidence(v_cann.evidence),
                remediation=v_cann.remediation, references_json=None, impact_usd=None,
            )
        )

    v_broken = check_broken_internal_links(crawl_result.pages)
    findings.append(
        Finding(
            run_id=run_id, page_id=None, check_id="ON-063",
            check_name=_check_name_for("ON-063"), category="on-page",
            subcategory="internal-links", owner_agent="A4",
            status=v_broken.status, severity=v_broken.severity, score=v_broken.score,
            confidence=v_broken.confidence,
            evidence_json=encode_evidence(v_broken.evidence),
            remediation=v_broken.remediation, references_json=None, impact_usd=None,
        )
    )
    if crawl_result.discovered_urls:
        v_orphan = check_orphan_pages(crawl_result.discovered_urls, crawl_result.pages)
        findings.append(
            Finding(
                run_id=run_id, page_id=None, check_id="ON-061",
                check_name=_check_name_for("ON-061"), category="on-page",
                subcategory="internal-links", owner_agent="A4",
                status=v_orphan.status, severity=v_orphan.severity, score=v_orphan.score,
                confidence=v_orphan.confidence,
                evidence_json=encode_evidence(v_orphan.evidence),
                remediation=v_orphan.remediation, references_json=None, impact_usd=None,
            )
        )

    # ----- Site-wide technical analyzers -----
    console.print("[bold]> Running technical analyzers...[/bold]")
    for check_id, category, owner, verdict in iter_site_wide_technical(
        sitemaps=crawl_result.sitemaps,
        robots=crawl_result.robots,
        pages=crawl_result.pages,
    ):
        findings.append(
            Finding(
                run_id=run_id, page_id=None, check_id=check_id,
                check_name=_check_name_for(check_id), category=category,
                subcategory=_meta_for(check_id)[2],
                owner_agent=owner,
                status=verdict.status, severity=verdict.severity, score=verdict.score,
                confidence=verdict.confidence,
                evidence_json=encode_evidence(verdict.evidence),
                remediation=verdict.remediation, references_json=None, impact_usd=None,
            )
        )

    # ----- Off-page analyzers (Moz) -----
    if moz:
        console.print("[bold]> Off-page analysis (Moz)...[/bold]")
        try:
            async with MozClient(
                access_id=keys.moz_access_id, secret_key=keys.moz_secret_key
            ) as mz:
                da = await mz.domain_authority(crawl_result.site_url)
                bl = await mz.backlinks(crawl_result.site_url, limit=50)
            (artifact_dir / "moz-domain-authority.json").write_text(
                json.dumps(da.__dict__, indent=2, default=str), encoding="utf-8"
            )
            (artifact_dir / "moz-backlinks.json").write_text(
                json.dumps(
                    {
                        "target": bl.target,
                        "referring_domains": bl.referring_domains,
                        "backlink_count": bl.backlink_count,
                        "sample_count": len(bl.sample_links),
                        "anchor_distribution": bl.anchor_distribution,
                        "error": bl.error,
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            for check_id, category, owner, verdict in iter_off_page_findings(
                da=da, profile=bl, domain=domain
            ):
                findings.append(
                    Finding(
                        run_id=run_id, page_id=None, check_id=check_id,
                        check_name=_check_name_for(check_id), category=category,
                        subcategory=_meta_for(check_id)[2],
                        owner_agent=owner,
                        status=verdict.status, severity=verdict.severity, score=verdict.score,
                        confidence=verdict.confidence,
                        evidence_json=encode_evidence(verdict.evidence),
                        remediation=verdict.remediation, references_json=None, impact_usd=None,
                    )
                )
        except Exception as e:  # noqa: BLE001
            console.print(f"  [yellow]Moz failed: {type(e).__name__}: {e}[/yellow]")

    # ----- Serper SERP sampling -----
    if serper and keys.serper:
        console.print("[bold]> SERP sampling (Serper)...[/bold]")
        try:
            queries = _derive_serp_queries(
                slug=slug,
                parsed_pages=parsed_pages,
                business_name=business_name,
                city=city,
            )
            serps: dict[str, dict] = {}
            async with SerperClient(api_key=keys.serper) as sc:
                for label, q in queries:
                    resp = await sc.search(q, results=10)
                    serps[label] = resp.__dict__
                    console.print(
                        f"  [{label}] '{q}' -> {len(resp.organic)} organic, "
                        f"features={resp.features}"
                    )
            # Keep the legacy single-keyword filename for back-compat (first query),
            # plus the full multi-query bundle for downstream agents.
            primary_label, primary_q = queries[0]
            (artifact_dir / f"serper-{_safe_slug(primary_q)}.json").write_text(
                json.dumps(serps[primary_label], indent=2, default=str), encoding="utf-8"
            )
            (artifact_dir / "serper-queries.json").write_text(
                json.dumps(
                    {
                        "queries": [{"label": l, "query": q} for l, q in queries],
                        "responses": serps,
                    },
                    indent=2, default=str,
                ),
                encoding="utf-8",
            )
        except Exception as e:  # noqa: BLE001
            console.print(f"  [yellow]Serper failed: {type(e).__name__}: {e}[/yellow]")

    # ----- Local data: Places + citations + local analyzers (profile=local only) -----
    place: Place | None = None
    citations_summary: CitationSummary | None = None
    if profile == "local" and places and keys.google_places:
        console.print("[bold]> Google Places lookup...[/bold]")
        derived_name = business_name or (
            (parsed_pages[0].title.split("|")[0].split("-")[0].strip())
            if parsed_pages and parsed_pages[0].title
            else slug.split(".")[0]
        )
        query = f"{derived_name}" + (f" {city}" if city else "")
        try:
            async with PlacesClient(api_key=keys.google_places) as places_client:
                place = await places_client.find_place(query)
            if place and place.place_id:
                (artifact_dir / "places.json").write_text(
                    json.dumps(place.__dict__, indent=2, default=str), encoding="utf-8"
                )
                console.print(f"  Place found: [cyan]{place.name}[/cyan] ({place.place_id})")
            elif place and place.error:
                console.print(f"  [yellow]Places: {place.error}[/yellow]")
            else:
                console.print(f"  [yellow]No Place match for '{query}'[/yellow]")
        except Exception as e:  # noqa: BLE001
            console.print(f"  [yellow]Places failed: {type(e).__name__}: {e}[/yellow]")

    if profile == "local" and citations and keys.serper:
        console.print("[bold]> Citations (Serper discovery)...[/bold]")
        try:
            async with CitationsClient(api_key=keys.serper) as cc:
                citations_summary = await cc.citation_status(
                    business_name or (place.name if place else slug.split(".")[0]),
                    address=place.formatted_address if place else None,
                    phone=place.phone if place else None,
                )
            (artifact_dir / "citations.json").write_text(
                json.dumps(
                    {
                        "business_query": citations_summary.business_query,
                        "total_checked": citations_summary.total_checked,
                        "found_count": citations_summary.found_count,
                        "missing_count": citations_summary.missing_count,
                        "inconsistent_count": citations_summary.inconsistent_count,
                        "average_nap_score": citations_summary.average_nap_score,
                        "per_source": [
                            {
                                "source": s.source,
                                "found": s.found,
                                "listing_url": s.listing_url,
                                "name_match": s.name_match,
                                "address_match": s.address_match,
                                "phone_match": s.phone_match,
                                "nap_score": s.nap_score,
                            }
                            for s in citations_summary.per_source
                        ],
                        "error": citations_summary.error,
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            if citations_summary.error:
                console.print(f"  [yellow]Citations: {citations_summary.error}[/yellow]")
            else:
                console.print(
                    f"  citations checked={citations_summary.total_checked}"
                    f" found={citations_summary.found_count}"
                    f" inconsistent={citations_summary.inconsistent_count}"
                )
        except Exception as e:  # noqa: BLE001
            console.print(f"  [yellow]Citations failed: {type(e).__name__}: {e}[/yellow]")

    if profile == "local":
        console.print("[bold]> Running local analyzers...[/bold]")
        for check_id, category, owner, verdict in iter_local_findings(
            place=place, citations=citations_summary, parsed_pages=parsed_pages
        ):
            findings.append(
                Finding(
                    run_id=run_id, page_id=None, check_id=check_id,
                    check_name=_check_name_for(check_id), category=category,
                    subcategory=_meta_for(check_id)[2],
                    owner_agent=owner,
                    status=verdict.status, severity=verdict.severity, score=verdict.score,
                    confidence=verdict.confidence,
                    evidence_json=encode_evidence(verdict.evidence),
                    remediation=verdict.remediation, references_json=None, impact_usd=None,
                )
            )

    # ----- Free extras (URL slug, image filenames, readability, etc) -----
    console.print("[bold]> Running free deterministic extras + AI-search analyzers...[/bold]")
    findings.extend(_emit_extras(run_id=run_id, page_id_by_url=page_id_by_url, crawl_result=crawl_result, parsed_pages=parsed_pages))
    try:
        findings.append(await _emit_llms_txt(run_id=run_id, site_url=crawl_result.site_url))
    except Exception as e:  # noqa: BLE001
        console.print(f"  [yellow]llms.txt check failed: {type(e).__name__}: {e}[/yellow]")

    # ----- Google Cloud NL: entity + category + sentiment snapshot -----
    # Free for the first ~5k units/month. Skipped silently when no key.
    try:
        await _emit_google_nl_snapshot(artifact_dir=artifact_dir, crawl_result=crawl_result)
    except Exception as e:  # noqa: BLE001
        console.print(f"  [yellow]Google NL snapshot failed: {type(e).__name__}: {e}[/yellow]")

    # ----- Specialist agents (paid, opt-in) -----
    if use_agents:
        console.print("[bold]> Dispatching the 21 specialist agents (parallel)...[/bold]")
        deterministic_shaped = [
            {
                "check_id": f.check_id,
                "check_name": f.check_name,
                "status": f.status,
                "severity": f.severity,
                "score": f.score,
                "evidence_json": f.evidence_json,
            }
            for f in findings
        ]
        try:
            agent_findings = await _emit_agent_findings(
                run_id=run_id,
                page_id_by_url=page_id_by_url,
                crawl_result=crawl_result,
                deterministic_findings=deterministic_shaped,
                teams=None,
            )
            findings.extend(agent_findings)
        except Exception as e:  # noqa: BLE001
            console.print(f"  [yellow]Agent dispatch failed: {type(e).__name__}: {e}[/yellow]")
    else:
        # Always-on AI-search fallback dispatch. Even when the operator
        # declines the full 21-agent pass, the AI search section is the most
        # commercially visible part of the report - run A5 + C4 so it stays
        # populated with real, evidence-backed analysis.
        findings.extend(
            await _maybe_dispatch_ai_search_agents(
                run_id=run_id,
                page_id_by_url=page_id_by_url,
                crawl_result=crawl_result,
                findings=findings,
                include_brand_authority=True,
            )
        )

    # ----- Persist + score -----
    with connection() as conn:
        FindingRepository.insert_many(conn, findings)
        all_findings = FindingRepository.by_run(conn, run_id)

    scores = aggregate(all_findings, profile=profile)
    duration = time.monotonic() - t0

    paths = write_full_bundle(
        artifact_dir=artifact_dir,
        domain=domain,
        run_uuid=run_uuid,
        profile=profile,
        started_at=started_at,
        duration_sec=duration,
        pages_crawled=len(crawl_result.pages),
        scores=scores,
        findings=all_findings,
        ai_narrative=use_ai,
        mode=mode,
    )
    with connection() as conn:
        AuditRunRepository.finalize(
            conn, run_id,
            status="succeeded", duration_sec=duration,
            pages_crawled=len(crawl_result.pages), scores=scores,
        )

    console.print()
    table = Table(title="Scorecard")
    table.add_column("Dimension")
    table.add_column("Score", justify="right")
    table.add_row("Overall", str(scores.get("overall") or "-"))
    table.add_row("On-Page", str(scores.get("on_page") or "-"))
    table.add_row("Technical", str(scores.get("technical") or "-"))
    table.add_row("Off-Page", str(scores.get("off_page") or "-"))
    table.add_row("Local SEO", str(scores.get("local") or "-"))
    console.print(table)
    console.print()
    console.print(f"Findings: [cyan]{len(all_findings)}[/cyan]")
    sev_counts: dict[str, int] = {}
    for f in all_findings:
        sev_counts[f["severity"]] = sev_counts.get(f["severity"], 0) + 1
    console.print(f"  by severity: {sev_counts}")
    console.print()
    console.print(f"[green]Done in {duration:.1f}s[/green]")
    console.print(f"Reports: [cyan]{paths['report_executive']}[/cyan]")


def _meta_for(check_id: str) -> tuple[str, str, str | None]:
    if check_id in _CHECK_META_OVERRIDES:
        return _CHECK_META_OVERRIDES[check_id]
    return _CHECKLIST_META.get(check_id, (check_id, "on-page", None))


def _check_name_for(check_id: str) -> str:
    return _meta_for(check_id)[0]


def _category_for(check_id: str) -> str:
    return _meta_for(check_id)[1]


@app.command()
def local(
    domain: str = typer.Argument(..., help="Domain or full URL of a local business to audit"),
    business_name: str = typer.Option(None, "--business-name", help="Override the business name passed to Places (default: derive from domain)"),
    city: str = typer.Option(None, "--city", help="City to scope Places search (recommended for accuracy)"),
    max_pages: int = typer.Option(30, "--max-pages"),
    mode: str = typer.Option(
        "auto",
        "--mode",
        help="auto | paid | free. 'free' forces ai_narrative=off, agents=off, "
             "and disables Places/Citations (Serper) regardless of keys. "
             "Mirrors the harness rule used by `full` for universal compatibility.",
    ),
    places: bool = typer.Option(True, "--places/--no-places"),
    citations: bool = typer.Option(True, "--citations/--no-citations", help="Discover tier-1 directory presence + infer NAP via Serper"),
    moz: bool = typer.Option(False, "--moz/--no-moz", help="Backlink data is out of scope for local; accepted as a no-op so the universal harness `--no-moz` flag works on this subcommand."),
    ai_narrative: str = typer.Option("ask", "--ai-narrative", help="off | on | ask (prompt at runtime)"),
    agents: str = typer.Option("ask", "--agents", help="off | on | ask - run the 21 specialist agents (paid)"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Run the local SEO audit pipeline (Phase 3).

    Crawls the site, identifies the business via Google Places, discovers
    citation presence + NAP drift via Serper, and runs the local analyzer set.
    Graceful degrade when keys are missing.
    """
    _enforce_public_target(domain)
    configure(log_level)
    ensure_dirs()
    mode = (mode or "auto").lower().strip()
    if mode not in ("auto", "paid", "free"):
        console.print(f"[red]Invalid --mode {mode!r}. Use auto, paid, or free.[/red]")
        raise typer.Exit(code=2)
    if mode == "free":
        # Free-tier knobs: kill every paid integration + AI dispatch.
        ai_narrative = "off"
        agents = "off"
        places = False
        citations = False
    use_ai = _resolve_ai_narrative(ai_narrative)
    use_agents = _resolve_agents(agents)
    _ = moz  # noqa: F841 - accepted for harness parity; local has no Moz path
    asyncio.run(
        _run_local(
            domain=domain,
            business_name=business_name,
            city=city,
            max_pages=max_pages,
            use_places=places,
            use_citations=citations,
            use_ai=use_ai,
            use_agents=use_agents,
        )
    )


async def _run_local(
    *,
    domain: str,
    business_name: str | None,
    city: str | None,
    max_pages: int,
    use_places: bool,
    use_citations: bool,
    use_ai: bool = False,
    use_agents: bool = False,
) -> None:
    run_uuid = str(uuid.uuid4())
    started_at = _now_pkt_iso()
    slug = _domain_to_slug(domain)
    artifact_dir = AUDITS_DIR / slug / run_uuid
    artifact_dir.mkdir(parents=True, exist_ok=True)

    console.rule(f"[bold]/audit-local {domain}[/bold]")
    console.print(f"Run UUID: [cyan]{run_uuid}[/cyan]")
    console.print(f"Artifact dir: [cyan]{artifact_dir}[/cyan]")
    console.print()

    t0 = time.monotonic()

    with connection() as conn:
        run = AuditRunRepository.create(
            conn,
            AuditRun(
                run_uuid=run_uuid,
                domain=domain,
                profile="local",
                command="/audit-local",
                args_json=json.dumps(
                    {
                        "max_pages": max_pages,
                        "business_name": business_name,
                        "city": city,
                        "places": use_places,
                        "citations": use_citations,
                    }
                ),
                status="running",
                started_at=started_at,
                artifact_dir=str(artifact_dir),
            ),
        )
    run_id = run.id
    assert run_id is not None

    console.print("[bold]> Crawling...[/bold]")
    cfg = CrawlConfig(max_pages_quick=max_pages, max_pages_full=max_pages)
    crawl_result = await crawl(domain, config=cfg, max_pages=max_pages)
    parsed_pages = [cp.parsed for cp in crawl_result.pages if cp.parsed]
    console.print(
        f"  discovered={len(crawl_result.discovered_urls)} fetched={len(crawl_result.pages)} parsed={len(parsed_pages)}"
        f" crawl_time={crawl_result.duration_sec:.1f}s"
    )

    # ----- Persist pages -----
    page_id_by_url: dict[str, int] = {}
    with connection() as conn:
        for cp in crawl_result.pages:
            pid = PageRepository.upsert(
                conn, run_id,
                url=cp.url,
                canonical_url=(cp.parsed.canonical if cp.parsed else None),
                http_status=cp.http_status,
                response_ms=cp.response_ms,
                title=(cp.parsed.title if cp.parsed else None),
                meta_description=(cp.parsed.meta_description if cp.parsed else None),
                h1=(cp.parsed.h1s[0] if cp.parsed and cp.parsed.h1s else None),
                word_count=(cp.parsed.word_count if cp.parsed else None),
                indexable=(cp.parsed and not cp.parsed.has_noindex) if cp.parsed else None,
            )
            page_id_by_url[cp.url] = pid

    findings: list[Finding] = []
    keys = get_keys()

    # ----- Google Places lookup -----
    place: Place | None = None
    if use_places:
        console.print("[bold]> Google Places lookup...[/bold]")
        derived_name = business_name or (
            (parsed_pages[0].title.split("|")[0].split("-")[0].strip())
            if parsed_pages and parsed_pages[0].title
            else slug.split(".")[0]
        )
        query = f"{derived_name}" + (f" {city}" if city else "")
        try:
            async with PlacesClient(api_key=keys.google_places) as places_client:
                place = await places_client.find_place(query)
            if place and place.place_id:
                (artifact_dir / "places.json").write_text(
                    json.dumps(place.__dict__, indent=2, default=str), encoding="utf-8"
                )
                console.print(f"  Place found: [cyan]{place.name}[/cyan] ({place.place_id})")
            elif place and place.error:
                console.print(f"  [yellow]Places: {place.error}[/yellow]")
            else:
                console.print(f"  [yellow]No Place match for '{query}'[/yellow]")
        except Exception as e:  # noqa: BLE001
            console.print(f"  [yellow]Places failed: {type(e).__name__}: {e}[/yellow]")

    # ----- Citations (Serper-driven discovery + NAP inference) -----
    citations: CitationSummary | None = None
    if use_citations:
        console.print("[bold]> Citations (Serper discovery)...[/bold]")
        try:
            async with CitationsClient(api_key=keys.serper) as cc:
                citations = await cc.citation_status(
                    business_name or (place.name if place else slug.split(".")[0]),
                    address=place.formatted_address if place else None,
                    phone=place.phone if place else None,
                )
            (artifact_dir / "citations.json").write_text(
                json.dumps(
                    {
                        "business_query": citations.business_query,
                        "total_checked": citations.total_checked,
                        "found_count": citations.found_count,
                        "missing_count": citations.missing_count,
                        "inconsistent_count": citations.inconsistent_count,
                        "average_nap_score": citations.average_nap_score,
                        "per_source": [
                            {
                                "source": s.source,
                                "found": s.found,
                                "listing_url": s.listing_url,
                                "name_match": s.name_match,
                                "address_match": s.address_match,
                                "phone_match": s.phone_match,
                                "nap_score": s.nap_score,
                            }
                            for s in citations.per_source
                        ],
                        "error": citations.error,
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            if citations.error:
                console.print(f"  [yellow]Citations: {citations.error}[/yellow]")
            else:
                console.print(
                    f"  citations checked={citations.total_checked} found={citations.found_count}"
                    f" inconsistent={citations.inconsistent_count}"
                )
        except Exception as e:  # noqa: BLE001
            console.print(f"  [yellow]Citations failed: {type(e).__name__}: {e}[/yellow]")

    # ----- Run on-page analyzers (subset relevant to local) -----
    console.print("[bold]> Running on-page analyzers (subset)...[/bold]")
    for cp in crawl_result.pages:
        if not cp.parsed:
            continue
        pid = page_id_by_url.get(cp.url)
        for check_id, owner, verdict in iter_per_page_checks(cp.parsed):
            if check_id in {"ON-073", "ON-079", "ON-080", "TECH-066"} or check_id.startswith("ON-04"):
                findings.append(
                    Finding(
                        run_id=run_id, page_id=pid, check_id=check_id,
                        check_name=_check_name_for(check_id),
                        category=_category_for(check_id),
                        subcategory=_meta_for(check_id)[2],
                        owner_agent=owner,
                        status=verdict.status, severity=verdict.severity, score=verdict.score,
                        confidence=verdict.confidence,
                        evidence_json=encode_evidence(verdict.evidence),
                        remediation=verdict.remediation,
                        references_json=None, impact_usd=None,
                    )
                )

    # ----- Local analyzers -----
    console.print("[bold]> Running local analyzers...[/bold]")
    for check_id, category, owner, verdict in iter_local_findings(
        place=place, citations=citations, parsed_pages=parsed_pages
    ):
        findings.append(
            Finding(
                run_id=run_id, page_id=None, check_id=check_id,
                check_name=_check_name_for(check_id), category=category,
                subcategory=_meta_for(check_id)[2],
                owner_agent=owner,
                status=verdict.status, severity=verdict.severity, score=verdict.score,
                confidence=verdict.confidence,
                evidence_json=encode_evidence(verdict.evidence),
                remediation=verdict.remediation, references_json=None, impact_usd=None,
            )
        )

    # ----- Free extras (URL slug, image filenames, readability, etc) -----
    console.print("[bold]> Running free deterministic extras + AI-search analyzers...[/bold]")
    findings.extend(_emit_extras(run_id=run_id, page_id_by_url=page_id_by_url, crawl_result=crawl_result, parsed_pages=parsed_pages))
    try:
        findings.append(await _emit_llms_txt(run_id=run_id, site_url=crawl_result.site_url))
    except Exception as e:  # noqa: BLE001
        console.print(f"  [yellow]llms.txt check failed: {type(e).__name__}: {e}[/yellow]")

    # ----- Google Cloud NL: entity + category + sentiment snapshot -----
    # Free for the first ~5k units/month. Skipped silently when no key.
    try:
        await _emit_google_nl_snapshot(artifact_dir=artifact_dir, crawl_result=crawl_result)
    except Exception as e:  # noqa: BLE001
        console.print(f"  [yellow]Google NL snapshot failed: {type(e).__name__}: {e}[/yellow]")

    # ----- Specialist agents (paid, opt-in) -----
    if use_agents:
        console.print("[bold]> Dispatching the 21 specialist agents (parallel)...[/bold]")
        deterministic_shaped = [
            {
                "check_id": f.check_id,
                "check_name": f.check_name,
                "status": f.status,
                "severity": f.severity,
                "score": f.score,
                "evidence_json": f.evidence_json,
            }
            for f in findings
        ]
        try:
            agent_findings = await _emit_agent_findings(
                run_id=run_id,
                page_id_by_url=page_id_by_url,
                crawl_result=crawl_result,
                deterministic_findings=deterministic_shaped,
                teams=["onpage", "technical", "local"],
            )
            findings.extend(agent_findings)
        except Exception as e:  # noqa: BLE001
            console.print(f"  [yellow]Agent dispatch failed: {type(e).__name__}: {e}[/yellow]")
    else:
        # Always-on AI-search fallback dispatch (A5 + C4) when Anthropic key
        # is configured. Keeps Section 04 populated even when the full agent
        # pass is declined.
        findings.extend(
            await _maybe_dispatch_ai_search_agents(
                run_id=run_id,
                page_id_by_url=page_id_by_url,
                crawl_result=crawl_result,
                findings=findings,
                include_brand_authority=True,
            )
        )

    # ----- Persist + score -----
    with connection() as conn:
        FindingRepository.insert_many(conn, findings)
        all_findings = FindingRepository.by_run(conn, run_id)

    scores = aggregate(all_findings, profile="local")
    duration = time.monotonic() - t0

    paths = write_full_bundle(
        artifact_dir=artifact_dir,
        domain=domain,
        run_uuid=run_uuid,
        profile="local",
        started_at=started_at,
        duration_sec=duration,
        pages_crawled=len(crawl_result.pages),
        scores=scores,
        findings=all_findings,
        ai_narrative=use_ai,
    )
    with connection() as conn:
        AuditRunRepository.finalize(
            conn, run_id,
            status="succeeded", duration_sec=duration,
            pages_crawled=len(crawl_result.pages), scores=scores,
        )

    console.print()
    table = Table(title="Local Scorecard")
    table.add_column("Dimension")
    table.add_column("Score", justify="right")
    table.add_row("Overall", str(scores.get("overall") or "-"))
    table.add_row("On-Page (subset)", str(scores.get("on_page") or "-"))
    table.add_row("Technical (subset)", str(scores.get("technical") or "-"))
    table.add_row("Local SEO", str(scores.get("local") or "-"))
    console.print(table)
    console.print()
    console.print(f"Findings: [cyan]{len(all_findings)}[/cyan]")
    sev_counts: dict[str, int] = {}
    for f in all_findings:
        sev_counts[f["severity"]] = sev_counts.get(f["severity"], 0) + 1
    console.print(f"  by severity: {sev_counts}")
    console.print()
    console.print(f"[green]Done in {duration:.1f}s[/green]")
    console.print(f"Reports: [cyan]{paths['report_executive']}[/cyan]")


@app.command()
def track(
    domain: str = typer.Argument(..., help="Domain whose history to diff"),
    run_uuid: str = typer.Option(None, "--run", help="Run UUID to compare against the prior run (default: latest)"),
    log_level: str = typer.Option("WARNING", "--log-level"),
) -> None:
    """Compare two audit runs of the same domain. Surfaces score deltas, new
    findings (regressions), resolved findings (improvements)."""
    configure(log_level)
    from audit_engine.db.queries import (
        get_previous_succeeded_run,
        get_run_by_uuid,
        get_runs_for_domain,
    )

    with connection() as conn:
        if run_uuid:
            current = get_run_by_uuid(conn, run_uuid)
        else:
            recents = get_runs_for_domain(conn, domain, limit=1)
            current = recents[0] if recents else None

        if not current:
            console.print(f"[red]No runs found for domain {domain}[/red]")
            raise typer.Exit(1)

        previous = get_previous_succeeded_run(conn, domain, before_run_uuid=current["run_uuid"])
        if not previous:
            console.print(f"[yellow]No prior succeeded run for {domain}; nothing to diff against.[/yellow]")
            raise typer.Exit(0)

        cur_findings = FindingRepository.by_run(conn, current["id"])
        prev_findings = FindingRepository.by_run(conn, previous["id"])

    cur_keys = {(f["check_id"], f["page_id"]) for f in cur_findings if f["status"] in ("warn", "fail")}
    prev_keys = {(f["check_id"], f["page_id"]) for f in prev_findings if f["status"] in ("warn", "fail")}
    new_keys = cur_keys - prev_keys
    resolved_keys = prev_keys - cur_keys
    persisted_keys = cur_keys & prev_keys

    cur_by_key = {(f["check_id"], f["page_id"]): f for f in cur_findings}
    prev_by_key = {(f["check_id"], f["page_id"]): f for f in prev_findings}

    sev_rank = {"critical": 0, "major": 1, "minor": 2, "info": 3}
    new_findings = sorted(
        [cur_by_key[k] for k in new_keys if k in cur_by_key],
        key=lambda f: (sev_rank.get(f["severity"], 9), -(f.get("score") or 0)),
    )
    resolved_findings = sorted(
        [prev_by_key[k] for k in resolved_keys if k in prev_by_key],
        key=lambda f: (sev_rank.get(f["severity"], 9), -(f.get("score") or 0)),
    )

    console.rule(f"[bold]Track {domain}[/bold]")
    console.print(f"Previous run: [cyan]{previous['run_uuid']}[/cyan] ({previous['started_at']})")
    console.print(f"Current  run: [cyan]{current['run_uuid']}[/cyan] ({current['started_at']})")
    console.print()

    table = Table(title="Score deltas")
    table.add_column("Dimension")
    table.add_column("Previous", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("Delta", justify="right")
    for dim, key in (
        ("Overall", "overall_score"),
        ("On-Page", "on_page_score"),
        ("Technical", "technical_score"),
        ("Off-Page", "off_page_score"),
        ("Local SEO", "local_score"),
    ):
        p = previous.get(key)
        c = current.get(key)
        delta = (c - p) if (p is not None and c is not None) else None
        delta_str = "-" if delta is None else f"{delta:+.1f}"
        table.add_row(dim, str(p or "-"), str(c or "-"), delta_str)
    console.print(table)
    console.print()

    console.print(f"[bold]New issues (regressions):[/bold] {len(new_findings)}")
    for f in new_findings[:10]:
        console.print(f"  [{f['severity']}] {f['check_id']} {f['check_name']}")
    if len(new_findings) > 10:
        console.print(f"  ... and {len(new_findings) - 10} more")
    console.print()

    console.print(f"[bold]Resolved issues:[/bold] {len(resolved_findings)}")
    for f in resolved_findings[:10]:
        console.print(f"  [{f['severity']}] {f['check_id']} {f['check_name']}")
    if len(resolved_findings) > 10:
        console.print(f"  ... and {len(resolved_findings) - 10} more")
    console.print()
    console.print(f"[dim]Persisted issues: {len(persisted_keys)}[/dim]")


@app.command(name="fix")
def fix_finding(
    check_id: str = typer.Argument(..., help="Check ID (e.g., ON-023, LOC-013)"),
    run_uuid: str = typer.Option(None, "--run", help="Limit to a specific run UUID"),
    log_level: str = typer.Option("WARNING", "--log-level"),
) -> None:
    """Print a detailed remediation guide for a check from a specific run."""
    configure(log_level)
    from audit_engine.db.queries import find_finding

    with connection() as conn:
        rows = find_finding(conn, run_uuid=run_uuid, check_id=check_id)

    if not rows:
        console.print(f"[red]No findings match check_id={check_id} run_uuid={run_uuid or 'any'}[/red]")
        raise typer.Exit(1)

    console.rule(f"[bold]{check_id} remediation[/bold]")
    for f in rows[:5]:
        console.print()
        console.print(f"[bold]Finding id:[/bold] {f['id']}")
        console.print(f"[bold]Name:[/bold] {f['check_name']}")
        console.print(f"[bold]Category:[/bold] {f['category']} / {f.get('subcategory') or '-'}")
        console.print(
            f"[bold]Severity:[/bold] {f['severity']} / status [bold]{f['status']}[/bold]"
            f" / score {f.get('score') if f.get('score') is not None else '-'}"
        )
        if f.get("confidence") is not None:
            console.print(f"[bold]Confidence:[/bold] {f['confidence']:.2f}")
        if f.get("evidence_json"):
            console.print(f"[bold]Evidence:[/bold]")
            console.print(f"  {f['evidence_json']}")
        if f.get("remediation"):
            console.print(f"[bold]Remediation:[/bold]")
            console.print(f"  {f['remediation']}")
        else:
            console.print("[dim]No remediation text on this finding.[/dim]")
    if len(rows) > 5:
        console.print(f"\n[dim]... and {len(rows) - 5} more matching findings (showing first 5)[/dim]")


@app.command(name="list")
def list_runs(
    domain: str = typer.Option(None, "--domain", help="Filter by domain"),
    limit: int = typer.Option(20, "--limit"),
    log_level: str = typer.Option("WARNING", "--log-level"),
) -> None:
    """List recent audit runs."""
    configure(log_level)
    from audit_engine.db.queries import get_recent_runs, get_runs_for_domain

    with connection() as conn:
        rows = (
            get_runs_for_domain(conn, domain, limit=limit)
            if domain
            else get_recent_runs(conn, limit=limit)
        )

    if not rows:
        console.print("[dim]No audit runs yet.[/dim]")
        return

    table = Table(title=f"Recent audit runs{(' for ' + domain) if domain else ''}")
    table.add_column("Started (PKT)")
    table.add_column("Domain")
    table.add_column("Cmd")
    table.add_column("Status")
    table.add_column("Overall", justify="right")
    table.add_column("Pages", justify="right")
    table.add_column("Run", style="cyan")
    for r in rows:
        table.add_row(
            (r.get("started_at") or "")[:16],
            r.get("domain") or "",
            r.get("command") or "",
            r.get("status") or "",
            str(r.get("overall_score") or "-"),
            str(r.get("pages_crawled") or 0),
            (r.get("run_uuid") or "")[:8],
        )
    console.print(table)


@app.command()
def dashboard(
    limit: int = typer.Option(50, "--limit"),
    log_level: str = typer.Option("WARNING", "--log-level"),
) -> None:
    """Generate the static HTML dashboard at data/dashboard/index.html."""
    configure(log_level)
    from audit_engine.reporters.dashboard import generate

    out = generate(limit=limit)
    console.print(f"[green]Dashboard written:[/green] {out}")
    console.print(f"Open with: [cyan]start {out}[/cyan]")


@app.command(name="kb-refresh")
def kb_refresh(
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Knowledge base refresh stub. Phase 7 implementation will fetch the
    latest Search Status Dashboard and re-summarize confirmed algorithm
    changes into knowledge/2026-updates/algorithm-timeline.md.
    """
    configure(log_level)
    console.print("[yellow]/kb-refresh is not implemented yet (Phase 7).[/yellow]")
    console.print("Manual refresh: edit knowledge/*.md files directly.")
    console.print("Files to update on each quarterly refresh:")
    console.print("  - knowledge/2026-updates/algorithm-timeline.md")
    console.print("  - knowledge/local-seo/playbook-2026.md")
    console.print("  - knowledge/geo-ai-search/playbook-2026.md")


@app.command()
def validate(
    run_uuid: str = typer.Argument(..., help="Run UUID of a previously executed audit"),
    log_level: str = typer.Option("WARNING", "--log-level"),
) -> None:
    """Run L1+L2+L3 quality gates over a cached audit's findings.

    Writes critic-report.json + findings-validated.json into the audit
    artifact directory. Use before regenerating the report to drop bad
    findings and downgrade low-confidence ones.
    """
    configure(log_level)
    from audit_engine.db.queries import get_run_by_uuid
    from audit_engine.quality.gates import run_all_gates

    with connection() as conn:
        run = get_run_by_uuid(conn, run_uuid)
        if not run:
            console.print(f"[red]No run with UUID {run_uuid}[/red]")
            raise typer.Exit(1)
        findings = FindingRepository.by_run(conn, run["id"])

    artifact_dir = Path(run["artifact_dir"])
    summary = run_all_gates(findings, out_dir=artifact_dir)

    console.print()
    table = Table(title="Quality gates")
    table.add_column("Gate")
    table.add_column("Reviewed", justify="right")
    table.add_column("Verified", justify="right")
    table.add_column("Rejected", justify="right")
    table.add_column("Downgraded", justify="right")
    table.add_column("Merged", justify="right")
    for gate_key in ("l1", "l2"):
        g = summary[gate_key]
        table.add_row(
            gate_key.upper(),
            str(g["reviewed"]),
            str(g["verified"]),
            str(g["rejected"]),
            str(g["downgraded"]),
            str(g["merged"]),
        )
    console.print(table)
    console.print()
    console.print(f"L3 council top critical: [cyan]{len(summary['l3_council']['top'])}[/cyan]")
    console.print(
        f"After all gates: [cyan]{summary['totals']['verified_after_all_gates']}[/cyan]"
        f" / {summary['totals']['reviewed']} findings retained"
    )
    console.print(f"  rejected: {summary['totals']['rejected']}")


@app.command()
def report(
    run_uuid: str = typer.Argument(..., help="Run UUID of a previously executed audit"),
    format: str = typer.Option("all", "--format", help="all | md | html | pdf"),
    brand_name: str = typer.Option("", "--brand-name", help="Brand to print on the cover (default: branding.json brand_name)"),
    log_level: str = typer.Option("WARNING", "--log-level"),
) -> None:
    """Regenerate report artifacts from a cached audit run.

    Reads findings from SQLite using `run_uuid`, re-runs the bundle. Useful when
    you have updated templates and want fresh deliverables without re-crawling.
    """
    configure(log_level)
    from audit_engine.db.queries import get_run_by_uuid
    from audit_engine.reporters.html import BrandConfig

    with connection() as conn:
        run = get_run_by_uuid(conn, run_uuid)
        if not run:
            console.print(f"[red]No run with UUID {run_uuid}[/red]")
            raise typer.Exit(1)
        rows = FindingRepository.by_run(conn, run["id"])

    artifact_dir = Path(run["artifact_dir"])
    artifact_dir.mkdir(parents=True, exist_ok=True)

    scores = {
        "overall": run.get("overall_score"),
        "on_page": run.get("on_page_score"),
        "technical": run.get("technical_score"),
        "off_page": run.get("off_page_score"),
        "local": run.get("local_score"),
    }
    paths = write_full_bundle(
        artifact_dir=artifact_dir,
        domain=run["domain"],
        run_uuid=run_uuid,
        profile=run["profile"],
        started_at=run["started_at"],
        duration_sec=run.get("duration_sec") or 0.0,
        pages_crawled=run.get("pages_crawled") or 0,
        scores=scores,
        findings=rows,
        brand=BrandConfig(name=brand_name) if brand_name else BrandConfig(),
    )

    console.print()
    console.print(f"[green]Regenerated reports for run {run_uuid}[/green]")
    for key, path in paths.items():
        console.print(f"  {key:30} {path}")


if __name__ == "__main__":
    app()
