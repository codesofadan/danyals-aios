"""HTML report generator via Jinja2.

Reads validated findings + run metadata; renders the three Jinja templates
(executive, full, remediation) into standalone HTML files in the artifact dir.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from audit_engine.config import TEMPLATES_DIR, get_branding

SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2, "info": 3}


@dataclass
class BrandConfig:
    name: str = field(default_factory=lambda: get_branding().brand_name)
    primary_color: str = "#1f3a5f"
    logo_path: str | None = None


def _evidence_summary(evidence_json: str | None) -> str | None:
    if not evidence_json:
        return None
    try:
        data = json.loads(evidence_json)
    except json.JSONDecodeError:
        return evidence_json[:200]
    if not isinstance(data, dict):
        return str(data)[:200]
    parts: list[str] = []
    for k, v in list(data.items())[:5]:
        sv = v if isinstance(v, (str, int, float, bool, type(None))) else json.dumps(v, default=str)[:80]
        parts.append(f"{k}={sv}")
    return ", ".join(parts)


def _shape_finding(f: dict[str, Any]) -> dict[str, Any]:
    return {
        "check_id": f["check_id"],
        "check_name": f["check_name"],
        "category": f["category"],
        "subcategory": f.get("subcategory"),
        "owner_agent": f["owner_agent"],
        "status": f["status"],
        "severity": f["severity"],
        "score": f.get("score"),
        "confidence": f.get("confidence"),
        "page_id": f.get("page_id"),
        "evidence_summary": _evidence_summary(f.get("evidence_json")),
        "remediation": f.get("remediation"),
    }


def render_all(
    *,
    findings: list[dict[str, Any]],
    run_metadata: dict[str, Any],
    artifact_dir: Path,
    brand: BrandConfig | None = None,
    stylesheet_basename: str = "print.css",
) -> dict[str, Path]:
    """Render executive + full + remediation HTML; return paths."""
    brand = brand or BrandConfig()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR / "report")),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    shaped = [_shape_finding(f) for f in findings]
    severity_counts: Counter[str] = Counter(f["severity"] for f in shaped)

    critical_findings = sorted(
        [f for f in shaped if f["severity"] == "critical" and f["status"] in ("warn", "fail")],
        key=lambda f: -(f.get("score") or 0),
    )[:10]

    quick_wins = sorted(
        [
            f for f in shaped
            if f["status"] in ("warn", "fail") and f["severity"] in ("critical", "major")
            and (f.get("score") or 0) <= 8
        ],
        key=lambda f: (SEVERITY_RANK.get(f["severity"], 99), f.get("score") or 0),
    )[:20]

    by_category: dict[str, list[dict[str, Any]]] = {}
    for f in shaped:
        by_category.setdefault(f["category"], []).append(f)

    category_rows = []
    for cat in ("on-page", "technical", "off-page", "local-seo"):
        items = by_category.get(cat, [])
        category_rows.append(
            {
                "category": cat,
                "total": len(items),
                "critical": sum(1 for f in items if f["severity"] == "critical"),
                "major": sum(1 for f in items if f["severity"] == "major"),
                "minor": sum(1 for f in items if f["severity"] == "minor"),
                "info": sum(1 for f in items if f["severity"] == "info"),
            }
        )

    duration_sec = float(run_metadata.get("duration_sec") or 0)
    if duration_sec < 60:
        duration_str = f"{duration_sec:.1f}s"
    else:
        m, s = divmod(int(duration_sec), 60)
        duration_str = f"{m}m {s}s"

    common_ctx = {
        "title": f"SEO Audit - {run_metadata.get('domain')}",
        "domain": run_metadata.get("domain"),
        "run_uuid": run_metadata.get("run_uuid"),
        "profile": run_metadata.get("profile"),
        "pages_crawled": run_metadata.get("pages_crawled"),
        "duration_sec_str": duration_str,
        "started_at_pkt": run_metadata.get("started_at"),
        "scores": run_metadata.get("scores") or {},
        "brand_name": brand.name,
        "stylesheet_href": stylesheet_basename,
        "findings_total": len(shaped),
        "severity_counts": severity_counts,
    }

    # Write the stylesheet alongside the HTML so file:// links work.
    src_css = TEMPLATES_DIR / "report" / "print.css"
    dst_css = artifact_dir / stylesheet_basename
    dst_css.write_text(src_css.read_text(encoding="utf-8"), encoding="utf-8")

    # Executive
    exec_html = env.get_template("executive.html.j2").render(
        **common_ctx,
        critical_findings=critical_findings,
        quick_wins=quick_wins,
        category_rows=category_rows,
    )
    exec_path = artifact_dir / "report-executive.html"
    exec_path.write_text(exec_html, encoding="utf-8")

    # Full
    categories_for_full = []
    for cat in ("on-page", "technical", "off-page", "local-seo"):
        items = sorted(
            by_category.get(cat, []),
            key=lambda f: (SEVERITY_RANK.get(f["severity"], 99), -(f.get("score") or 0)),
        )
        categories_for_full.append({"category": cat, "findings": items})
    full_html = env.get_template("full.html.j2").render(
        **common_ctx, categories=categories_for_full
    )
    full_path = artifact_dir / "report-full.html"
    full_path.write_text(full_html, encoding="utf-8")

    # Remediation
    ranked = sorted(
        [f for f in shaped if f["status"] in ("warn", "fail") and f.get("remediation")],
        key=lambda f: (SEVERITY_RANK.get(f["severity"], 99), -(f.get("score") or 0)),
    )
    remediation_html = env.get_template("remediation.html.j2").render(**common_ctx, ranked=ranked)
    remediation_path = artifact_dir / "remediation.html"
    remediation_path.write_text(remediation_html, encoding="utf-8")

    return {
        "report_executive_html": exec_path,
        "report_full_html": full_path,
        "remediation_html": remediation_path,
        "stylesheet": dst_css,
    }
