"""Markdown report generator. v0 - skeleton output for the deterministic
pipeline. The Claude M4 Report Writer agent rewrites this into the consulting
narrative; this file is what the Python pipeline produces before agents run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

PKT = timezone(timedelta(hours=5), name="PKT")


SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2, "info": 3}


def _group(findings: list[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for f in findings:
        out.setdefault(f[key], []).append(f)
    return out


def _badge(severity: str, status: str) -> str:
    if status in ("pass", "n_a"):
        return "OK"
    return severity.upper()


def render_findings_table(findings: list[dict], *, limit: int | None = None) -> str:
    rows = sorted(
        findings,
        key=lambda f: (SEVERITY_RANK.get(f["severity"], 99), -(f.get("score") or 0)),
    )
    if limit:
        rows = rows[:limit]
    if not rows:
        return "_(no findings in this slice)_\n"

    lines = [
        "| Severity | Check | Status | Score | Evidence |",
        "|---|---|---|---|---|",
    ]
    for f in rows:
        ev = json.loads(f["evidence_json"]) if f.get("evidence_json") else {}
        ev_summary = ", ".join(f"{k}={v}" for k, v in list(ev.items())[:3])
        if len(ev_summary) > 120:
            ev_summary = ev_summary[:117] + "..."
        score = "-" if f.get("score") is None else f"{f['score']:.1f}"
        lines.append(
            f"| {_badge(f['severity'], f['status'])} | `{f['check_id']}` {f['check_name']} | "
            f"{f['status']} | {score} | {ev_summary} |"
        )
    return "\n".join(lines) + "\n"


def render_audit(
    *,
    domain: str,
    run_uuid: str,
    profile: str,
    started_at: str,
    duration_sec: float,
    pages_crawled: int,
    scores: dict[str, float | None],
    findings: list[dict],
    artifact_dir: Path,
) -> tuple[str, str, str]:
    """Returns (executive_md, full_md, remediation_md)."""

    # ----- Executive summary -----
    by_cat = _group(findings, "category")
    by_sev = _group(findings, "severity")
    crit = by_sev.get("critical", [])

    exec_md = [
        f"# SEO Audit — {domain}",
        "",
        f"**Run ID:** `{run_uuid}`  ",
        f"**Started:** {started_at} PKT  ",
        f"**Duration:** {duration_sec:.1f}s  ",
        f"**Pages crawled:** {pages_crawled}  ",
        f"**Profile:** {profile}  ",
        "",
        "## Scorecard",
        "",
        "| Dimension | Score |",
        "|---|---|",
        f"| Overall | **{scores.get('overall') or '-'}** |",
        f"| On-Page | {scores.get('on_page') or '-'} |",
        f"| Technical | {scores.get('technical') or '-'} |",
        f"| Off-Page | {scores.get('off_page') or '-'} |",
        f"| Local SEO | {scores.get('local') or '-'} |",
        "",
        "## Top critical findings",
        "",
        render_findings_table(crit, limit=10) if crit else "_No critical findings detected._\n",
        "",
        "## Findings by category",
        "",
        "| Category | Total | Critical | Major | Minor | Info |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for cat in ("on-page", "technical", "off-page", "local-seo"):
        items = by_cat.get(cat, [])
        c = sum(1 for f in items if f["severity"] == "critical")
        m = sum(1 for f in items if f["severity"] == "major")
        mn = sum(1 for f in items if f["severity"] == "minor")
        i = sum(1 for f in items if f["severity"] == "info")
        exec_md.append(f"| {cat} | {len(items)} | {c} | {m} | {mn} | {i} |")
    exec_md.append("")

    # ----- Full report -----
    full_md = exec_md.copy()
    full_md.extend(["", "## All findings", ""])
    for cat in ("on-page", "technical", "off-page", "local-seo"):
        items = by_cat.get(cat, [])
        if not items:
            continue
        full_md.append(f"### {cat} ({len(items)})")
        full_md.append("")
        full_md.append(render_findings_table(items))
        full_md.append("")

    # ----- Remediation -----
    remediation_md = [
        f"# Remediation playbook — {domain}",
        "",
        f"_Run: `{run_uuid}` — generated {started_at} PKT_",
        "",
        "Ordered by severity then score. Each item has the check ID for traceability.",
        "",
    ]
    ranked = sorted(
        [f for f in findings if f["status"] in ("warn", "fail") and f.get("remediation")],
        key=lambda f: (SEVERITY_RANK.get(f["severity"], 99), -(f.get("score") or 0)),
    )
    if not ranked:
        remediation_md.append("_No remediation items - clean audit._")
    else:
        for f in ranked:
            remediation_md.extend(
                [
                    f"## [{f['severity'].upper()}] `{f['check_id']}` {f['check_name']}",
                    "",
                    f["remediation"],
                    "",
                ]
            )

    return ("\n".join(exec_md), "\n".join(full_md), "\n".join(remediation_md))


def write_artifacts(
    artifact_dir: Path,
    *,
    executive_md: str,
    full_md: str,
    remediation_md: str,
    findings_json: list[dict],
    run_metadata: dict,
) -> dict[str, Path]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "report_executive": artifact_dir / "report-executive.md",
        "report_full": artifact_dir / "report-full.md",
        "remediation": artifact_dir / "remediation.md",
        "findings_json": artifact_dir / "findings.json",
        "run_meta": artifact_dir / "run.json",
    }
    paths["report_executive"].write_text(executive_md, encoding="utf-8")
    paths["report_full"].write_text(full_md, encoding="utf-8")
    paths["remediation"].write_text(remediation_md, encoding="utf-8")
    paths["findings_json"].write_text(
        json.dumps(findings_json, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    paths["run_meta"].write_text(
        json.dumps(run_metadata, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return paths
