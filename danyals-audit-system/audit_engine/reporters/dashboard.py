"""HTML dashboard generator.

Writes a static `data/dashboard/index.html` that lists every audit run, scores,
finding counts, and links to per-run report bundles. Standalone Tailwind via
CDN at runtime; works offline once cached. No backend, no auth.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from audit_engine.config import DATA_DIR
from audit_engine.db.repository import connection
from audit_engine.db.queries import get_recent_runs


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SEO-AUDIT-OS dashboard</title>
  <style>
    :root {{
      --ink: #111;
      --ink-soft: #444;
      --rule: #d9d9d9;
      --accent: #1f3a5f;
      --good: #2d6a4f;
      --warn: #c97a16;
      --bad: #b32a2a;
      --bg: #fafafa;
      --card: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, "Helvetica Neue", "Inter", Arial, sans-serif;
      color: var(--ink);
      background: var(--bg);
      font-size: 14px;
    }}
    header {{
      padding: 28px 32px 16px;
      border-bottom: 1px solid var(--rule);
      background: var(--card);
    }}
    header h1 {{ margin: 0 0 4px; font-size: 22px; font-weight: 600; letter-spacing: -0.01em; }}
    header .sub {{ color: var(--ink-soft); font-size: 13px; }}
    main {{ padding: 24px 32px; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
      margin-bottom: 24px;
    }}
    .stat {{
      background: var(--card);
      border: 1px solid var(--rule);
      padding: 16px 18px;
    }}
    .stat-label {{
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: var(--ink-soft);
      margin-bottom: 6px;
    }}
    .stat-value {{ font-size: 24px; font-weight: 600; }}
    table {{
      width: 100%;
      background: var(--card);
      border: 1px solid var(--rule);
      border-collapse: collapse;
      font-size: 13px;
    }}
    th {{
      text-align: left;
      font-weight: 600;
      font-size: 11px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--ink-soft);
      padding: 10px 12px;
      border-bottom: 1px solid var(--rule);
      background: #f3f3f3;
    }}
    td {{
      padding: 10px 12px;
      border-bottom: 1px solid #ececec;
      vertical-align: top;
    }}
    tr:last-child td {{ border-bottom: none; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .score {{ font-variant-numeric: tabular-nums; font-weight: 600; }}
    .score-good {{ color: var(--good); }}
    .score-warn {{ color: var(--warn); }}
    .score-bad  {{ color: var(--bad); }}
    .badge {{
      display: inline-block;
      font-size: 10px;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      padding: 2px 7px;
      border: 1px solid var(--rule);
      border-radius: 2px;
      color: var(--ink-soft);
    }}
    .badge-succeeded {{ color: var(--good); border-color: var(--good); }}
    .badge-failed    {{ color: var(--bad); border-color: var(--bad); }}
    .badge-running   {{ color: var(--warn); border-color: var(--warn); }}
    .mono {{ font-family: "SF Mono", Consolas, Menlo, monospace; font-size: 12px; color: var(--ink-soft); }}
    footer {{
      padding: 24px 32px;
      font-size: 12px;
      color: var(--ink-soft);
    }}
    .empty {{ padding: 40px; text-align: center; color: var(--ink-soft); font-style: italic; }}
  </style>
</head>
<body>
  <header>
    <h1>SEO-AUDIT-OS dashboard</h1>
    <div class="sub">{generated_at} PKT &middot; {run_count} runs &middot; {domain_count} unique domains</div>
  </header>
  <main>
    <section class="stats">
      <div class="stat"><div class="stat-label">Total runs</div><div class="stat-value">{run_count}</div></div>
      <div class="stat"><div class="stat-label">Unique domains</div><div class="stat-value">{domain_count}</div></div>
      <div class="stat"><div class="stat-label">Median overall score</div><div class="stat-value">{median_score}</div></div>
      <div class="stat"><div class="stat-label">Total findings</div><div class="stat-value">{total_findings}</div></div>
    </section>

    <table>
      <thead>
        <tr>
          <th>Started (PKT)</th>
          <th>Domain</th>
          <th>Cmd</th>
          <th>Status</th>
          <th>Overall</th>
          <th>On-Page</th>
          <th>Tech</th>
          <th>Off-Page</th>
          <th>Local</th>
          <th>Pages</th>
          <th>Run</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </main>
  <footer>
    Static dashboard. To regenerate after new runs: <span class="mono">seo-audit dashboard</span>
  </footer>
</body>
</html>
"""


def _score_class(score: float | None) -> str:
    if score is None:
        return ""
    if score >= 80:
        return "score-good"
    if score >= 50:
        return "score-warn"
    return "score-bad"


def _fmt(score: float | None) -> str:
    if score is None:
        return '<span class="mono">&ndash;</span>'
    return f'<span class="score {_score_class(score)}">{score:g}</span>'


def _relative_link(artifact_dir: str, dashboard_dir: Path) -> str:
    """Build a relative href to the audit's executive HTML from the dashboard dir."""
    p = Path(artifact_dir)
    candidate = p / "report-executive.html"
    if not candidate.exists():
        return "#"
    try:
        return str(candidate.resolve().relative_to(dashboard_dir.resolve().parent)).replace("\\", "/")
    except ValueError:
        return candidate.as_uri()


def generate(*, limit: int = 50) -> Path:
    """Render the dashboard. Returns the index.html path."""
    dashboard_dir = DATA_DIR / "dashboard"
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    with connection() as conn:
        runs = get_recent_runs(conn, limit=limit)
        total_findings_row = conn.execute(
            "SELECT COUNT(*) AS c FROM findings"
        ).fetchone()
        total_findings = total_findings_row["c"] if total_findings_row else 0

    if not runs:
        idx = dashboard_dir / "index.html"
        idx.write_text(
            _HTML_TEMPLATE.format(
                generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                run_count=0,
                domain_count=0,
                median_score="-",
                total_findings=0,
                rows_html='<tr><td colspan="11" class="empty">No runs yet. Run /audit, /audit-quick, or /audit-local to generate one.</td></tr>',
            ),
            encoding="utf-8",
        )
        return idx

    domains = {r["domain"] for r in runs}
    scores = sorted([r.get("overall_score") for r in runs if r.get("overall_score") is not None])
    median_score = (
        f"{scores[len(scores) // 2]:g}" if scores else "-"
    )

    rows: list[str] = []
    for r in runs:
        artifact_dir = r.get("artifact_dir") or ""
        link = _relative_link(artifact_dir, dashboard_dir)
        status = r.get("status") or "?"
        badge_class = (
            "badge-succeeded" if status == "succeeded"
            else "badge-failed" if status == "failed"
            else "badge-running"
        )
        rows.append(
            f"<tr>"
            f"<td class=\"mono\">{r.get('started_at') or ''}</td>"
            f"<td><a href=\"{link}\">{r.get('domain') or ''}</a></td>"
            f"<td class=\"mono\">{r.get('command') or ''}</td>"
            f"<td><span class=\"badge {badge_class}\">{status}</span></td>"
            f"<td>{_fmt(r.get('overall_score'))}</td>"
            f"<td>{_fmt(r.get('on_page_score'))}</td>"
            f"<td>{_fmt(r.get('technical_score'))}</td>"
            f"<td>{_fmt(r.get('off_page_score'))}</td>"
            f"<td>{_fmt(r.get('local_score'))}</td>"
            f"<td>{r.get('pages_crawled') or 0}</td>"
            f"<td class=\"mono\">{(r.get('run_uuid') or '')[:8]}</td>"
            f"</tr>"
        )

    idx = dashboard_dir / "index.html"
    idx.write_text(
        _HTML_TEMPLATE.format(
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            run_count=len(runs),
            domain_count=len(domains),
            median_score=median_score,
            total_findings=total_findings,
            rows_html="\n".join(rows),
        ),
        encoding="utf-8",
    )
    return idx
