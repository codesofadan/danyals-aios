"""Bundle: write MD + HTML (+ PDF when available) in one call.

The CLI commands call this to keep each pipeline tidy. Adds the consolidated
unified-narrative report (free, deterministic Python) as the polished single
deliverable. Optionally adds the Claude-narrated variant when the caller
opts into the paid AI mode and ANTHROPIC_API_KEY is set.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audit_engine.config import TEMPLATES_DIR, get_branding
from audit_engine.reporters import consolidated as consolidated_reporter
from audit_engine.reporters import html as html_reporter
from audit_engine.reporters import markdown as md_reporter
from audit_engine.reporters import narrative as narrative_reporter
from audit_engine.reporters import pdf as pdf_reporter


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

    html_paths = html_reporter.render_all(
        findings=findings,
        run_metadata=run_meta,
        artifact_dir=artifact_dir,
        brand=brand,
    )

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

    # ----- AI narrative (opt-in, paid) -----
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

    pdf_paths = pdf_reporter.write_all_pdfs(html_paths)

    return {**md_paths, "report_consolidated_md": consolidated_md_path, **html_paths, **pdf_paths}
