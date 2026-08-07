"""Bundle: write MD + HTML (+ PDF when available) in one call.

The CLI commands call this to keep each pipeline tidy. Adds the consolidated
unified-narrative report (free, deterministic Python) as the polished single
deliverable. Optionally adds the Claude-narrated variant when the caller
opts into the paid AI mode and ANTHROPIC_API_KEY is set.
"""

from __future__ import annotations

import importlib.util
import os
import traceback
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

from audit_engine.config import TEMPLATES_DIR, get_branding
from audit_engine.logging_setup import get_logger
from audit_engine.reporters import consolidated as consolidated_reporter
from audit_engine.reporters import html as html_reporter
from audit_engine.reporters import markdown as md_reporter
from audit_engine.reporters import narrative as narrative_reporter
from audit_engine.reporters import pdf as pdf_reporter

log = get_logger(__name__)


def _pdf_generator_candidates() -> list[Path]:
    """Ordered candidate locations for ``scripts/generate_audit_pdf.py``.

    The engine normally runs from its SOURCE tree (the worker invokes
    ``python -m audit_engine.cli.main`` with cwd = ``AUDIT_ENGINE_DIR``), so the
    script sits two parents above this file. But if the package is ever imported
    from an installed location (site-packages) that sibling does not exist, so we
    also probe ``AUDIT_ENGINE_DIR``, the process cwd, and the known container
    path. First existing wins; duplicates are collapsed."""
    raw: list[Path] = [Path(__file__).resolve().parents[2] / "scripts" / "generate_audit_pdf.py"]
    env_dir = os.environ.get("AUDIT_ENGINE_DIR")
    if env_dir:
        raw.append(Path(env_dir) / "scripts" / "generate_audit_pdf.py")
    raw.append(Path.cwd() / "scripts" / "generate_audit_pdf.py")
    raw.append(Path("/app/audit-engine/scripts/generate_audit_pdf.py"))

    ordered: list[Path] = []
    seen: set[str] = set()
    for p in raw:
        try:
            rp = p.resolve()
        except OSError:
            rp = p
        key = str(rp)
        if key not in seen:
            seen.add(key)
            ordered.append(rp)
    return ordered


@lru_cache(maxsize=1)
def _load_pdf_generator() -> ModuleType | None:
    """Load ``scripts/generate_audit_pdf.py`` (the consulting-grade report
    designer) as a module. It is a script, not a package member, so we load it
    by path, probing multiple candidate locations so an installed-package layout
    does not defeat the source-relative lookup. Returns None if it cannot be found
    or imported - callers then fall back to the simpler ``full.html.j2`` report so
    the bundle never crashes. A None return is logged LOUDLY (error) because for a
    PAID run it means the client would receive the legacy layout."""
    candidates = _pdf_generator_candidates()
    script = next((c for c in candidates if c.is_file()), None)
    if script is None:
        log.error(
            "pdf_generator_not_found",
            searched=";".join(str(c) for c in candidates),
        )
        return None
    try:
        spec = importlib.util.spec_from_file_location("audit_pdf_generator", script)
        if spec is None or spec.loader is None:
            log.error("pdf_generator_spec_failed", script=str(script))
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:  # noqa: BLE001
        log.error(
            "pdf_generator_load_failed",
            script=str(script),
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(),
        )
        return None


def _report_date(started_at: Any) -> str:
    """Format the run's start date as ``24 July 2026`` for the report cover.
    Falls back to today when the stored value cannot be parsed."""
    s = str(started_at or "").strip()
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%d %B %Y")
    except (ValueError, TypeError):
        return datetime.now().strftime("%d %B %Y")


def _render_consulting_report_html(
    *,
    artifact_dir: Path,
    domain: str,
    run_metadata: dict[str, Any],
    condensed: bool,
) -> str | None:
    """Build the self-contained consulting report.html via the shared designer,
    then run the deterministic M5 report-design contract loop (validate -> patch
    -> re-validate, up to 3 iterations) so the report never renders below the
    design contract. The verdict is persisted to ``qa-report-contract.json`` in
    the artifact dir. Returns the (possibly patched) HTML string, or None on any
    failure (missing module, raised exception) so the caller can fall back to the
    simpler template."""
    tier = "free" if condensed else "paid"
    mod = _load_pdf_generator()
    if mod is None or not hasattr(mod, "build_report_html"):
        log.error(
            "consulting_report_generator_unavailable",
            tier=tier,
            reason="module_not_loaded" if mod is None else "missing_build_report_html",
        )
        return None
    try:
        html = mod.build_report_html(
            artifact_dir,
            client=domain,
            industry="",
            location="",
            date=_report_date(run_metadata.get("started_at")),
            condensed=condensed,
        )
    except Exception as exc:  # noqa: BLE001
        # build_report_html is written to NEVER raise; if it somehow does, log
        # LOUDLY with the full traceback so the PAID fallback to the legacy
        # single-file report can never regress invisibly.
        log.error(
            "consulting_report_html_failed",
            tier=tier,
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(),
        )
        return None

    # Deterministic M5 report-design contract loop. Never fatal: on a residual
    # structural blocker we still return the best-effort HTML and log the verdict.
    try:
        from audit_engine.quality import report_contract as rc

        branding_email = ""
        try:
            branding_email = str(getattr(mod, "BRANDING", {}).get("contact_email") or "")
        except Exception:  # noqa: BLE001
            branding_email = ""

        html, verdict, iterations = rc.enforce_report_contract(
            html, branding_email=branding_email, max_iterations=3
        )
        try:
            import json as _json

            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "qa-report-contract.json").write_text(
                _json.dumps(
                    {
                        "passed": verdict.passed,
                        "iterations": iterations,
                        "blockers": verdict.blockers,
                        "warnings": verdict.warnings,
                        "facts": verdict.facts,
                        "tier": "free" if condensed else "paid",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            pass
        if not verdict.passed:
            log.warning(
                "report_contract_residual_blockers",
                blockers=",".join(verdict.blockers),
                iterations=iterations,
            )
        else:
            log.info("report_contract_passed", iterations=iterations)
    except Exception as exc:  # noqa: BLE001
        # The contract loop must never break report generation.
        log.warning("report_contract_loop_failed", error=f"{type(exc).__name__}: {exc}")

    return html


def _markdown_to_html(md_text: str) -> str:
    try:
        import markdown as md_lib  # type: ignore

        return md_lib.markdown(
            md_text,
            extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
        )
    except ImportError:
        # Minimal fallback: wrap in <pre> so the content still ships.
        from html import escape

        return f'<pre class="raw-markdown">{escape(md_text)}</pre>'


def _render_consolidated_html(
    *,
    narrative_md: str,
    artifact_dir: Path,
    run_metadata: dict[str, Any],
    brand: html_reporter.BrandConfig | None,
    stylesheet_basename: str = "print.css",
) -> Path:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR / "report")),
        autoescape=select_autoescape(["html"]),
        keep_trailing_newline=True,
    )
    brand = brand or html_reporter.BrandConfig()
    duration_sec = float(run_metadata.get("duration_sec") or 0)
    if duration_sec < 60:
        duration_str = f"{duration_sec:.1f}s"
    else:
        m, s = divmod(int(duration_sec), 60)
        duration_str = f"{m}m {s}s"

    html_body = _markdown_to_html(narrative_md)
    out = env.get_template("consolidated.html.j2").render(
        title=f"SEO Audit Report - {run_metadata.get('domain')}",
        domain=run_metadata.get("domain"),
        run_uuid=run_metadata.get("run_uuid"),
        profile=run_metadata.get("profile"),
        pages_crawled=run_metadata.get("pages_crawled"),
        duration_sec_str=duration_str,
        started_at_pkt=run_metadata.get("started_at"),
        brand_name=brand.name,
        stylesheet_href=stylesheet_basename,
        narrative_html=html_body,
    )
    path = artifact_dir / "report-consolidated.html"
    path.write_text(out, encoding="utf-8")
    return path


def _cap_report_pdf_pages(pdf_path: Path | None, *, max_pages: int) -> None:
    """Hard safety net: truncate ``report.pdf`` to ``max_pages`` if it somehow
    renders longer. The source-level caps in generate_audit_pdf.py already keep it
    well under this, so this is a last line of defense - and a graceful no-op when
    PyMuPDF is not installed (its absence must never break the bundle)."""
    if pdf_path is None:
        return
    p = Path(pdf_path)
    if not p.is_file():
        return
    try:
        import fitz  # type: ignore  # PyMuPDF; lazy import so absence is non-fatal
    except Exception:  # noqa: BLE001
        return
    try:
        doc = fitz.open(str(p))
    except Exception as exc:  # noqa: BLE001
        log.warning("report_pdf_page_cap_open_failed", error=f"{type(exc).__name__}: {exc}")
        return

    tmp = p.with_suffix(".capped.pdf")
    truncated = False
    try:
        if doc.page_count > max_pages:
            log.warning(
                "report_pdf_page_cap_applied",
                pages=doc.page_count,
                cap=max_pages,
                path=str(p),
            )
            # Keep the first (cap - 1) pages PLUS the last page - the closing CTA
            # (it carries the contact email the M5 contract checks and the free-tier
            # upsell). This keeps the deliverable exactly ``max_pages`` long without
            # ever dropping that final page when the net has to fire.
            if max_pages >= 2:
                keep = [*range(max_pages - 1), doc.page_count - 1]
            else:
                keep = list(range(max_pages))
            doc.select(keep)
            doc.save(str(tmp))
            truncated = True
    except Exception as exc:  # noqa: BLE001
        log.warning("report_pdf_page_cap_failed", error=f"{type(exc).__name__}: {exc}")
        truncated = False
    finally:
        doc.close()

    # Swap in the truncated copy only after the handle is closed (Windows-safe).
    if truncated and tmp.is_file():
        os.replace(str(tmp), str(p))


def write_full_bundle(
    *,
    artifact_dir: Path,
    domain: str,
    run_uuid: str,
    profile: str,
    started_at: str,
    duration_sec: float,
    pages_crawled: int,
    scores: dict[str, float | None],
    findings: list[dict[str, Any]],
    brand: html_reporter.BrandConfig | None = None,
    ai_narrative: bool = False,
    mode: str = "auto",
    usage: dict[str, Any] | None = None,
) -> dict[str, Path]:
    """Render MD + HTML + PDF (best-effort) + consolidated narrative.

    ``usage`` (optional) is the run's machine-readable AI-spend accounting -- real
    token counts + call count -- persisted into run.json so a downstream consumer
    (the AIOS cost gate) can commit the actual spend instead of a flat estimate.
    """
    usage = dict(usage or {})
    executive_md, full_md, remediation_md = md_reporter.render_audit(
        domain=domain,
        run_uuid=run_uuid,
        profile=profile,
        started_at=started_at,
        duration_sec=duration_sec,
        pages_crawled=pages_crawled,
        scores=scores,
        findings=findings,
        artifact_dir=artifact_dir,
    )
    md_paths = md_reporter.write_artifacts(
        artifact_dir,
        executive_md=executive_md,
        full_md=full_md,
        remediation_md=remediation_md,
        findings_json=findings,
        run_metadata={
            "run_uuid": run_uuid,
            "domain": domain,
            "profile": profile,
            "started_at": started_at,
            "duration_sec": duration_sec,
            "pages_crawled": pages_crawled,
            "scores": scores,
            "mode": mode,
            "usage": usage,
        },
    )

    run_meta = {
        "run_uuid": run_uuid,
        "domain": domain,
        "profile": profile,
        "started_at": started_at,
        "duration_sec": duration_sec,
        "pages_crawled": pages_crawled,
        "scores": scores,
        "mode": mode,
        "usage": usage,
    }

    # The legacy multi-file HTML reports (report-full / executive / remediation).
    # None of these is the SERVED deliverable - the AIOS adapter always prefers
    # report.pdf (built from report.html below) - so a failure here must NEVER
    # abort the bundle and prevent report.pdf from being produced. render_all's
    # per-finding shaper uses hard subscripts, so a single malformed finding
    # (e.g. an older/hand-authored findings.json missing owner_agent) would
    # otherwise raise straight past the report.pdf build. Degrade to no legacy
    # reports instead, and keep going to the consulting report.pdf that matters.
    try:
        html_paths = html_reporter.render_all(
            findings=findings,
            run_metadata=run_meta,
            artifact_dir=artifact_dir,
            brand=brand,
        )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "legacy_html_reports_failed",
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(),
        )
        html_paths = {}

    # The single self-contained deliverable: report.html (CSS inlined) is what the
    # AIOS dashboard viewer shows AND the source report.pdf is rendered from (via
    # write_all_pdfs below, which PDFs every *_html entry), so the on-screen report
    # and the delivered PDF are the SAME document. It uses the CONSULTING-grade
    # design (cover, index, executive summary, strategy, all 7 dimension sections,
    # comprehensive off-page/GMB block, quick wins, methodology, closing CTA) -
    # identical to the reference PDF. Free mode renders the condensed (~10-15 page)
    # variant of that identical layout; paid mode renders the full inventory. If
    # the consulting designer cannot be loaded/run for any reason, we fall back to
    # the simpler full.html.j2 single-file report so a report.html is always
    # produced and the backend has something to serve.
    condensed = str(mode).lower() == "free"
    report_html_path = artifact_dir / "report.html"
    consulting_html = _render_consulting_report_html(
        artifact_dir=artifact_dir,
        domain=domain,
        run_metadata=run_meta,
        condensed=condensed,
    )
    if consulting_html is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        report_html_path.write_text(consulting_html, encoding="utf-8")
    else:
        # LAST-RESORT fallback only (the consulting designer failed and was logged
        # LOUDLY above). Render the legacy single-file report in its CONDENSED form
        # REGARDLESS of tier, so even this fallback stays ~15-20 pages and can never
        # ship the multi-hundred-page uncondensed layout as the client deliverable.
        log.error("consulting_report_fallback_used", tier="free" if condensed else "paid")
        report_html_path = html_reporter.render_report_html(
            findings=findings,
            run_metadata=run_meta,
            artifact_dir=artifact_dir,
            brand=brand,
            condensed=True,
        )
    html_paths["report_html"] = report_html_path

    # ----- Consolidated narrative (free, deterministic) -----
    consolidated_md = consolidated_reporter.render_consolidated(
        domain=domain,
        run_uuid=run_uuid,
        profile=profile,
        started_at=started_at,
        duration_sec=duration_sec,
        pages_crawled=pages_crawled,
        scores=scores,
        findings=findings,
        brand_name=(brand.name if brand else get_branding().brand_name),
    )
    consolidated_md_path = artifact_dir / "report-consolidated.md"
    consolidated_md_path.write_text(consolidated_md, encoding="utf-8")

    consolidated_html_path = _render_consolidated_html(
        narrative_md=consolidated_md,
        artifact_dir=artifact_dir,
        run_metadata=run_meta,
        brand=brand,
    )

    html_paths["report_consolidated_html"] = consolidated_html_path

    # ----- AI narrative (opt-in) -----
    # When enabled and ANTHROPIC_API_KEY + the SDK are present, Claude writes the
    # consulting-grade narrative (exec summary, top findings evidence -> why -> fix,
    # 30-60-90 plan). For a FREE/condensed run this narrative BECOMES the served
    # report.html (so report.pdf renders from it) - the free/public audit then reads
    # like a paid consulting deliverable. The designed condensed report stays the
    # graceful fallback when the narrative is absent (no key/SDK/API error). Paid
    # runs are untouched: the full designed report.html remains the served
    # deliverable and the narrative is only a side artifact.
    ai_narrative_html_path: Path | None = None
    if ai_narrative:
        ctx = narrative_reporter.build_context(
            domain=domain,
            run_uuid=run_uuid,
            profile=profile,
            started_at=started_at,
            duration_sec=duration_sec,
            pages_crawled=pages_crawled,
            scores=scores,
            findings=findings,
        )
        ai_md_path = artifact_dir / "report-ai-narrative.md"
        ai_path = narrative_reporter.write_narrative(ctx, out_path=ai_md_path)
        if ai_path is not None:
            md_paths["report_ai_narrative_md"] = ai_path
            ai_html = _render_consolidated_html(
                narrative_md=ai_path.read_text(encoding="utf-8"),
                artifact_dir=artifact_dir,
                run_metadata=run_meta,
                brand=brand,
                stylesheet_basename="print.css",
            )
            # consolidated.html.j2 always writes to report-consolidated.html;
            # rename for the AI variant.
            ai_html_path = artifact_dir / "report-ai-narrative.html"
            ai_html.replace(ai_html_path)
            html_paths["report_ai_narrative_html"] = ai_html_path
            ai_narrative_html_path = ai_html_path

    # Promote the Claude narrative to the SERVED report for a FREE/condensed run.
    # The backend's public endpoint serves report.html (viewer) + report.pdf, so we
    # overwrite report.html with the (self-contained, CSS-inlined) narrative and let
    # write_all_pdfs below re-render report.pdf from it. Only when the narrative was
    # actually produced - otherwise the designed condensed report already written to
    # report.html is served unchanged (graceful fallback). Never fatal.
    if condensed and ai_narrative_html_path is not None:
        served_html = Path(html_paths.get("report_html") or report_html_path)
        try:
            narrative_doc = ai_narrative_html_path.read_text(encoding="utf-8")
            css = (TEMPLATES_DIR / "report" / "print.css").read_text(encoding="utf-8")
            # The viewer serves report.html as a static file, so it MUST carry its
            # own CSS - inline print.css (never leave a sibling <link>).
            narrative_doc = html_reporter._inline_stylesheet(narrative_doc, css)
            served_html.write_text(narrative_doc, encoding="utf-8")
            html_paths["report_html"] = served_html
            log.info("free_report_served_ai_narrative", path=str(served_html))
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "free_report_ai_narrative_promote_failed",
                error=f"{type(exc).__name__}: {exc}",
            )

    # Render the SERVED consulting report.pdf FIRST so a slow or failing render of
    # the heavy legacy reports (report-full.html can be hundreds of pages on a large
    # crawl) can never leave report.pdf missing - which would make the backend serve
    # the giant report-full.pdf instead. dicts preserve insertion order and
    # write_all_pdfs renders in that order, so hoist report_html to the front.
    ordered_html_paths: dict[str, Path] = {}
    if "report_html" in html_paths:
        ordered_html_paths["report_html"] = html_paths["report_html"]
    ordered_html_paths.update({k: v for k, v in html_paths.items() if k != "report_html"})
    pdf_paths = pdf_reporter.write_all_pdfs(ordered_html_paths)

    # Belt-and-suspenders page cap on the SERVED report.pdf: guarantee it never
    # exceeds the tier ceiling even if a data edge case slipped past the
    # source-level caps in generate_audit_pdf.py. No-op when PyMuPDF is absent (the
    # source-level caps already keep it well under the ceiling).
    _cap_report_pdf_pages(pdf_paths.get("report_pdf"), max_pages=(20 if condensed else 100))

    return {**md_paths, "report_consolidated_md": consolidated_md_path, **html_paths, **pdf_paths}
