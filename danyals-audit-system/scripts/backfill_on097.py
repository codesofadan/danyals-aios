"""Backfill ON-097 (URL optimization) findings into an existing run's
findings.json from the cached `pages` table - zero network, no paid API.

ON-097 was dormant (iter_per_page_extras was empty) so existing audits never
recorded it. This computes the same URL-hygiene verdict the now-activated
analyzer produces - long URLs, underscores, uppercase, query params,
slug-title mismatch - directly from the pages table and appends warn rows to
findings.json so regenerated PDFs show the check. Idempotent: strips any
prior ON-097 rows before appending. Atomic write via a temp file.

Usage: python scripts/backfill_on097.py <artifact_dir> [<artifact_dir> ...]
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

DB = Path("data/seo_audit.db")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((s or "").lower()) if len(t) > 2}


def _url_issues(url: str, title: str | None):
    parsed = urlparse(url)
    path = parsed.path or "/"
    issues: list[str] = []
    if len(url) > 200:
        issues.append(f"length={len(url)} (>200 chars)")
    if "_" in path:
        issues.append("uses underscores (prefer hyphens)")
    if any(c.isupper() for c in path):
        issues.append("contains uppercase")
    if parsed.query:
        issues.append(f"query params: {parsed.query[:40]}")
    st, tt = _tokens(path.replace("/", " ").replace("-", " ")), _tokens(title or "")
    overlap = (len(st & tt) / max(len(st | tt), 1)) if (st and tt) else None
    if overlap is not None and overlap < 0.2 and path != "/":
        issues.append(f"slug-title overlap low ({overlap:.2f})")
    return issues, path, overlap


def backfill(artifact_dir: str) -> None:
    d = Path(artifact_dir)
    fp = d / "findings.json"
    if not fp.exists():
        print(f"[skip] no findings.json in {artifact_dir}")
        return
    payload = json.loads(fp.read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else payload.get("findings", [])
    run_id = next((r.get("run_id") for r in rows if r.get("run_id")), None)
    if run_id is None:
        print(f"[skip] could not resolve run_id for {artifact_dir}")
        return
    # Idempotent: drop any previously backfilled ON-097 rows.
    rows = [r for r in rows if r.get("check_id") != "ON-097"]
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    prows = con.execute(
        "SELECT id, url, title FROM pages WHERE run_id = ?", (run_id,)
    ).fetchall()
    con.close()
    base_id = max([(r.get("id") or 0) for r in rows], default=0) + 1
    added = 0
    for pr in prows:
        issues, path, overlap = _url_issues(pr["url"], pr["title"])
        if not issues:
            continue
        sev = "minor" if len(issues) <= 2 else "major"
        score = max(0.0, 10.0 - len(issues) * 2.0)
        rows.append({
            "id": base_id + added, "run_id": run_id, "page_id": pr["id"],
            "check_id": "ON-097", "check_name": "URL optimization analysis",
            "category": "on-page", "subcategory": "url", "owner_agent": "A3",
            "status": "warn", "severity": sev, "score": score, "confidence": 0.85,
            "evidence_json": json.dumps({"path": path, "issues": issues, "slug_title_overlap": overlap}),
            "remediation": ("URL issues: " + ", ".join(issues) +
                            ". Use lowercase, hyphens, no query params, and a slug derived from the page title."),
            "references_json": None, "impact_usd": None,
            "created_at": "2026-06-10 00:00:00",
        })
        added += 1
    out = rows if isinstance(payload, list) else {**payload, "findings": rows}
    tmp = fp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, fp)
    print(f"[ok] {artifact_dir}: run_id={run_id} pages={len(prows)} ON-097_warn_rows={added}")


if __name__ == "__main__":
    for a in sys.argv[1:]:
        backfill(a)
