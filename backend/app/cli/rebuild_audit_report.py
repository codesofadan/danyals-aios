"""Rebuild the client report (+ PDF), the workbook and the PLAN for audits that already ran.

WHY THIS EXISTS. The report and the workbook are DERIVED artifacts - every number in
them comes from `audit_findings` / `audit_rollups` / `audit_pages`, which are already
stored. So a report can be rebuilt at any time, for free, with no model call and no
crawl. That matters because a run performed before the PDF renderer landed has no
`audit-report.pdf` on disk at all, and the download route falls back to the ENGINE's
own document when the platform one is missing - a differently-branded file built from a
different source with different totals. The operator sees a PDF that does not match the
workbook and reasonably concludes the audit is inconsistent.

Rebuilding is also how a REPORT FIX reaches an old run. A defect corrected in
`audit_report.py` only changes documents generated after it; every past client report
keeps the defect until someone regenerates it.

SAFE TO RE-RUN. It rewrites `audit-report.html`, `audit-report.pdf`, the workbook and
the CSV pack in the audit's own artifact directory. It never touches the audit rows, the
engine's artifacts, or anything a crawl produced - so a rebuild cannot change what the
audit FOUND, only how it is presented.

THE PLAN TOO. The Strategy tab's "Now / Next / Then / Later" board reads
`audit_roadmaps`, which is written once at ingest. A run from before the roadmap
existed, or one whose roadmap step failed (it is deliberately warned-about rather
than raised, so the audit still completes), has an EMPTY Strategy tab for ever.
It is derived from stored findings like everything else here, so it is rebuilt in
the same pass - which is how every audit ends up with a plan, not just the ones
that happened to run on a good day.

    python -m app.cli.rebuild_audit_report --list
    python -m app.cli.rebuild_audit_report --audit-id <uuid> --yes
    python -m app.cli.rebuild_audit_report --all --yes
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import Any

from app.config import get_settings
from app.db.database import build_admin_pool, clear_pools, privileged_connection, set_pools
from app.services import audit_ingest, audit_report, audit_workbook
from app.services.audit_artifacts import local_store_from_settings


def _audits(audit_id: str | None) -> list[dict[str, Any]]:
    """Audits that actually have findings - a run with none has nothing to report on."""
    sql = (
        "select a.id, a.client_id, a.url, a.client_name, a.tier, a.created_at, "
        "       (select count(*) from public.audit_finding_instances i "
        "        where i.audit_id = a.id) as instances "
        "from public.audits a "
        "where exists (select 1 from public.audit_finding_instances i where i.audit_id = a.id)"
    )
    params: tuple[Any, ...] = ()
    if audit_id:
        sql += " and a.id = %s"
        params = (audit_id,)
    sql += " order by a.created_at desc"
    with privileged_connection() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def rebuild(row: dict[str, Any], store: Any) -> tuple[int, int, int]:
    """Rebuild one audit's workbook, report and plan.

    Returns (findings, instances, plan_items). The plan is rebuilt FIRST so the
    report renders the roadmap it just recomputed rather than a stale one.
    """
    audit_id = str(row["id"])
    out_dir = store.sheets_dir(audit_id)
    tier = str(row.get("tier") or "")
    meta_common = {
        "url": str(row.get("url") or ""),
        "client_name": str(row.get("client_name") or ""),
        "tier": tier.title() if tier else "",
    }
    # The plan first: the report prints it, so rebuilding it afterwards would
    # publish a document one regeneration behind its own data.
    planned = audit_ingest.store_roadmap(
        audit_id=audit_id,
        client_id=str(row["client_id"]) if row.get("client_id") else None,
    )
    built = audit_workbook.build(
        audit_id=audit_id,
        out_dir=out_dir,
        meta={**meta_common, "generated_at": datetime.now(UTC).isoformat()},
    )
    audit_report.build(
        audit_id=audit_id,
        out_dir=out_dir,
        meta={**meta_common, "generated_at": datetime.now(UTC).strftime("%d %B %Y")},
    )
    return built.findings, built.instances, int(planned.get("items", 0))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the client report + PDF and the workbook from stored audit rows."
    )
    parser.add_argument("--audit-id", help="rebuild one audit")
    parser.add_argument("--all", action="store_true", help="rebuild every audit with findings")
    parser.add_argument("--list", action="store_true", help="show what would be rebuilt")
    parser.add_argument("--yes", action="store_true", help="actually write; else dry run")
    args = parser.parse_args(argv)

    if not (args.audit_id or args.all or args.list):
        parser.error("pass --audit-id, --all, or --list")

    settings = get_settings()
    pool = build_admin_pool(settings.database_admin_url)
    if pool is None:
        print("ERROR: DATABASE_ADMIN_URL is not configured.", file=sys.stderr)
        return 2
    pool.open()
    set_pools(None, pool)
    try:
        rows = _audits(args.audit_id)
        if not rows:
            print("nothing to do (no audit has any findings recorded).")
            return 0

        print(f"{'audit':<38}{'instances':<11}client / url")
        print("-" * 92)
        for r in rows:
            who = str(r.get("client_name") or "") or str(r.get("url") or "")
            print(f"{r['id']!s:<38}{int(r['instances'] or 0):<11}{who[:44]}")
        print("-" * 92)

        if args.list or not args.yes:
            print(f"DRY RUN - {len(rows)} audit(s) would be rebuilt. Pass --yes to write.")
            return 0

        store = local_store_from_settings(settings)
        if store is None:
            print("ERROR: no local artifact store configured (AUDIT_ARTIFACT_DIR).",
                  file=sys.stderr)
            return 2

        rebuilt = 0
        for r in rows:
            try:
                findings, instances, plan_items = rebuild(r, store)
            except Exception as exc:  # one bad audit must not stop the rest
                print(f"  FAILED {r['id']}: {exc!r}", file=sys.stderr)
                continue
            rebuilt += 1
            print(f"  rebuilt {r['id']} - {findings} findings, {instances} occurrences, "
                  f"{plan_items} plan items")
        print(f"\nrebuilt {rebuilt} of {len(rows)} audit(s).")
        return 0 if rebuilt == len(rows) else 1
    finally:
        pool.close()
        clear_pools()


if __name__ == "__main__":
    raise SystemExit(main())
