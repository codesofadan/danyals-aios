"""Load one audit's artifacts into the three altitude tables.

Reads what the engine emitted - ``findings.json`` (taxonomy-enriched),
``pages.json`` and ``coverage.json`` - derives templates, causes, instances and
rollups, and writes them as rows.

IDEMPOTENT BY CONSTRUCTION. Re-ingesting the same artifact directory produces the
same rows: pages, instances and rollups for the audit are replaced wholesale, and
findings UPSERT on their cause identity so a re-run refreshes ``last_seen_at``
instead of duplicating. That property is what lets an ingest be retried after a
crash without corrupting a client's history, and it is asserted in the tests.

Writes go through ``privileged_connection`` (service_role), the same seam the
audit worker already uses to update the ``audits`` row. RLS on these tables is
staff-read; nothing writes them through a user JWT.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.db.database import privileged_connection
from app.services import audit_roadmap as RM
from app.services import audit_rollups as R
from app.services.audit_altitude import (
    FINGERPRINT_VERSION,
    Cause,
    assign_templates,
    build_causes,
)

log = logging.getLogger(__name__)

#: Guard rails. A breach is reported LOUDLY (see IngestResult.capped) and the
#: finding keeps its true ``instance_count`` while ``instances_stored`` records
#: what was kept, so a cap can never masquerade as a smaller problem.
MAX_INSTANCES_PER_FINDING = 20_000
MAX_INSTANCES_PER_RUN = 200_000

_INSERT_BATCH = 1_000


@dataclass(slots=True)
class IngestResult:
    audit_id: str
    pages: int = 0
    findings: int = 0
    instances: int = 0
    instances_observed: int = 0
    rollups: int = 0
    capped: bool = False
    scope_key: str = ""
    basis_hash: str = ""

    @property
    def truncated(self) -> int:
        return max(0, self.instances_observed - self.instances)


def _as_bool(value: Any) -> bool | None:
    """SQLite has no boolean: the engine stores 0/1 integers. Postgres will not
    coerce a smallint into a boolean column, so the conversion happens here, at
    the boundary, rather than being papered over with a cast in the SQL."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def url_hash(url: str) -> str:
    return hashlib.sha1((url or "").strip().lower().encode("utf-8")).hexdigest()[:32]


def scope_key_for(url: str) -> str:
    """The site a finding belongs to.

    A client may hold several domains and a finding on one is not a finding on
    another, so the host - not the client - is the scope. Lower-cased and
    ``www.``-stripped so http/https and www/non-www do not fork a site's history.
    """
    host = (urlsplit(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def load_artifacts(
    artifact_dir: str | Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Read the three artifacts. A missing file is an empty one, not a crash:
    an older engine build simply has nothing to ingest at these altitudes."""
    d = Path(artifact_dir)

    def _read(name: str, default: Any) -> Any:
        p = d / name
        if not p.is_file():
            return default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            log.warning("audit_ingest_unreadable_artifact name=%s error=%s", name, type(e).__name__)
            return default

    findings = _read("findings.json", [])
    pages = _read("pages.json", [])
    coverage = _read("coverage.json", {})
    return (
        findings if isinstance(findings, list) else [],
        pages if isinstance(pages, list) else [],
        coverage if isinstance(coverage, dict) else {},
    )


class IngestError(RuntimeError):
    """A write the ingest needed did not happen."""


def _one(cur: Any, what: str) -> dict[str, Any]:
    """The row an INSERT ... RETURNING must have produced.

    ``fetchone()`` returns None when the statement matched nothing, and an RLS
    refusal does exactly that: it does not raise, it writes zero rows. Indexing
    the result directly turned that into a bare `TypeError: 'NoneType' object is
    not subscriptable` several frames from the cause. This says which write was
    refused.
    """
    row = cur.fetchone()
    if row is None:
        raise IngestError(
            f"{what} returned no row. The write was refused - most likely by "
            f"row-level security for this user - rather than failing outright."
        )
    return dict(row)


def prepare(
    findings: list[dict[str, Any]], pages: list[dict[str, Any]],
    coverage: dict[str, Any], *, site_url: str = "",
) -> tuple[list[Cause], list[dict[str, Any]], list[R.Rollup], str]:
    """The pure half: artifacts in, causes + templated pages + rollups out.

    Separated from the write so the whole derivation can be tested without a
    database, and so a caller can preview an ingest without performing it.
    """
    templates = assign_templates([p.get("url", "") for p in pages if p.get("url")])
    for p in pages:
        p["template_id"] = templates.get(p.get("url", ""), "")
    by_engine_id = {
        int(p["page_id"]): p for p in pages if p.get("page_id") is not None
    }
    causes = build_causes(findings, by_engine_id)
    registry = R.registry_from_coverage(coverage)
    rollups = R.build_rollups(
        causes=causes, coverage=coverage, registry=registry, pages=pages,
        tier="", types=(), fingerprint_version=FINGERPRINT_VERSION,
    )
    scope = scope_key_for(site_url) or scope_key_for(
        next((p.get("url", "") for p in pages if p.get("url")), "")
    )
    return causes, pages, rollups, scope


def _page_issue_counts(causes: list[Cause]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for c in causes:
        for inst in c.instances:
            if not inst.url:
                continue
            b = out.setdefault(inst.url, {"total": 0, "critical": 0, "major": 0, "minor": 0, "info": 0})
            b["total"] += 1
            sev = (inst.severity or c.severity or "info").lower()
            if sev in b:
                b[sev] += 1
    return out


def ingest(
    *,
    audit_id: str,
    client_id: str | None,
    artifact_dir: str | Path,
    site_url: str = "",
    run_uuid: str = "",
    tier: str = "",
    types: list[str] | None = None,
) -> IngestResult:
    """Load one audit's artifacts into ``audit_pages`` / ``audit_findings`` /
    ``audit_finding_instances`` / ``audit_rollups``."""
    findings, pages, coverage = load_artifacts(artifact_dir)
    causes, pages, rollups, scope = prepare(findings, pages, coverage, site_url=site_url)

    basis = R.compute_basis_hash(
        tier=tier, types=types or [], checks_ran=coverage.get("ran") or [],
        fingerprint_version=FINGERPRINT_VERSION,
    )
    for r in rollups:
        r.basis_hash = basis

    result = IngestResult(audit_id=audit_id, scope_key=scope, basis_hash=basis)
    result.instances_observed = sum(c.instance_count for c in causes)

    counts = _page_issue_counts(causes)

    with privileged_connection() as cur:
        # --- pages (replace wholesale: they belong to this run) ---
        cur.execute("delete from public.audit_pages where audit_id = %s", (audit_id,))
        page_rows = []
        for p in pages:
            url = p.get("url") or ""
            # Named, not `c`. The same name was reused below for a Cause, so
            # mypy narrowed it to dict[str, int] and could not check any of the
            # finding-ingest loop - 21 of this package's errors came from here.
            sev = counts.get(url, {})
            page_rows.append((
                audit_id, client_id, run_uuid, p.get("page_id"), url, url_hash(url),
                p.get("canonical_url"), p.get("page_type"), p.get("template_id") or "",
                p.get("http_status"), p.get("response_ms"), p.get("title"),
                p.get("meta_description"), p.get("h1"), p.get("word_count"),
                _as_bool(p.get("indexable")), p.get("crawl_depth"),
                bool(_as_bool(p.get("is_orphan"))),
                sev.get("total", 0), sev.get("critical", 0), sev.get("major", 0),
                sev.get("minor", 0), sev.get("info", 0), sev.get("critical", 0) == 0,
            ))
        if page_rows:
            cur.executemany(
                """insert into public.audit_pages
                   (audit_id, client_id, run_uuid, engine_page_id, url, url_hash,
                    canonical_url, page_type, template_id, http_status, response_ms,
                    title, meta_description, h1, word_count, indexable, crawl_depth,
                    is_orphan, issues_total, issues_critical, issues_major,
                    issues_minor, issues_info, health_pass)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (audit_id, url_hash) do nothing""",
                page_rows,
            )
            result.pages = len(page_rows)

        cur.execute(
            "select id, engine_page_id from public.audit_pages where audit_id = %s",
            (audit_id,),
        )
        page_uuid_by_engine = {
            r["engine_page_id"]: r["id"] for r in cur.fetchall() if r["engine_page_id"] is not None
        }

        # --- findings: UPSERT on cause identity so a re-run refreshes rather
        # --- than duplicates. This is what makes first_seen/last_seen real.
        run_total = 0
        for c in causes:
            keep = min(c.instance_count, MAX_INSTANCES_PER_FINDING)
            if run_total + keep > MAX_INSTANCES_PER_RUN:
                keep = max(0, MAX_INSTANCES_PER_RUN - run_total)
            if keep < c.instance_count:
                result.capped = True
            run_total += keep

            cur.execute(
                """insert into public.audit_findings
                     (client_id, audit_id, scope_type, scope_key, check_id, check_name,
                      fingerprint, fingerprint_version, locus_kind, locus_value,
                      discriminator, pillar, subcategory, dimension, owner_agent,
                      automation, severity, status, confidence, instance_count,
                      instances_stored, pages_affected, evidence, remediation,
                      first_seen_audit, last_seen_audit, last_seen_at)
                   values (%s,%s,'site',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',
                           %s,%s,%s,%s,%s,%s,%s,%s, now())
                   on conflict (scope_type, scope_key, check_id, fingerprint) do update set
                     audit_id         = excluded.audit_id,
                     check_name       = excluded.check_name,
                     severity         = excluded.severity,
                     confidence       = excluded.confidence,
                     instance_count   = excluded.instance_count,
                     instances_stored = excluded.instances_stored,
                     pages_affected   = excluded.pages_affected,
                     evidence         = excluded.evidence,
                     remediation      = excluded.remediation,
                     last_seen_audit  = excluded.last_seen_audit,
                     last_seen_at     = now(),
                     -- a finding that had been closed and is seen again REGRESSED
                     regressed_at     = case when public.audit_findings.status = 'closed_verified'
                                             then now() else public.audit_findings.regressed_at end,
                     status           = 'open'
                   returning id""",
                (
                    client_id, audit_id, scope, c.check_id, c.check_name, c.fingerprint,
                    FINGERPRINT_VERSION, c.locus_kind, c.locus_value, c.discriminator,
                    c.pillar, c.subcategory, c.dimension, c.owner_agent, c.automation,
                    c.severity, c.confidence, c.instance_count, keep, c.pages_affected,
                    json.dumps(c.evidence), c.remediation, audit_id, audit_id,
                ),
            )
            finding_id = _one(cur, "audit_findings upsert")["id"]
            result.findings += 1

            # --- instances: replaced for this finding, then re-inserted. The
            # --- unique key is (finding_id, instance_key), never url - an entity
            # --- instance has no url and every one would collide on ''.
            # SCOPED TO THIS AUDIT, and that scope is the whole point.
            #
            # A finding is a persistent CAUSE that many audits observe; an
            # instance is what ONE audit saw. Deleting by finding_id alone made a
            # re-run destroy the previous run's evidence: re-ingesting a later
            # 12-page audit of the same site cut the earlier 197-page audit from
            # 8,077 occurrences to 3,225, because the two share causes. A report
            # that cannot be regenerated from its own audit is not a record.
            cur.execute(
                "delete from public.audit_finding_instances "
                "where finding_id = %s and audit_id = %s",
                (finding_id, audit_id),
            )
            rows = []
            for inst in c.instances[:keep]:
                rows.append((
                    finding_id, client_id, audit_id, inst.instance_key, inst.instance_kind,
                    inst.url, page_uuid_by_engine.get(inst.engine_page_id),
                    inst.template_id, json.dumps({}), inst.observed, inst.expected,
                    inst.detail, json.dumps(inst.evidence),
                    "" if inst.severity == c.severity else inst.severity,
                ))
            for i in range(0, len(rows), _INSERT_BATCH):
                cur.executemany(
                    """insert into public.audit_finding_instances
                         (finding_id, client_id, audit_id, instance_key, instance_kind,
                          url, page_id, template_id, locator, observed, expected,
                          detail, evidence, severity_override)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       on conflict do nothing""",
                    rows[i:i + _INSERT_BATCH],
                )
            result.instances += len(rows)

        # --- rollups (replace wholesale: they describe THIS run) ---
        cur.execute("delete from public.audit_rollups where audit_id = %s", (audit_id,))
        roll_rows = [
            (
                audit_id, client_id, run_uuid, r.level, r.key, r.label,
                r.checks_applicable, r.checks_planned, r.checks_ran, r.checks_skipped,
                json.dumps(r.skip_reasons), r.findings_open, r.instances_open,
                r.pages_affected, r.pages_crawled, json.dumps(r.severity_counts),
                json.dumps(r.status_counts), r.score, r.url_health_pct,
                r.basis_hash, r.scoring_model_version,
            )
            for r in rollups
        ]
        if roll_rows:
            cur.executemany(
                """insert into public.audit_rollups
                     (audit_id, client_id, run_uuid, level, key, label,
                      checks_applicable, checks_planned, checks_ran, checks_skipped,
                      skip_reasons, findings_open, instances_open, pages_affected,
                      pages_crawled, severity_counts, status_counts, score,
                      url_health_pct, basis_hash, scoring_model_version)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (audit_id, level, key) do nothing""",
                roll_rows,
            )
            result.rollups = len(roll_rows)

        # Report what is STORED, not what was attempted. An `on conflict do
        # nothing` that silently swallowed rows would otherwise be invisible, and
        # "no truncation in the export" has to be a checked property.
        cur.execute(
            "select count(*) as c from public.audit_finding_instances where audit_id = %s",
            (audit_id,),
        )
        result.instances = _one(cur, "audit_finding_instances count")["c"]

    if result.capped:
        log.warning(
            "audit_ingest_instance_cap audit_id=%s observed=%s stored=%s",
            audit_id, result.instances_observed, result.instances,
        )
    return result


# --------------------------------------------------------------------------- #
# Roadmap
# --------------------------------------------------------------------------- #

def store_roadmap(
    *,
    audit_id: str,
    client_id: str | None,
    capacity_points_per_month: int = RM.DEFAULT_CAPACITY_POINTS_PER_MONTH,
    project_id: str | None = None,
) -> dict[str, int]:
    """Generate the roadmap from this audit's stored findings and persist it.

    Reads findings back OUT of the database rather than taking them from the
    ingest in memory, deliberately: the roadmap must describe what was actually
    stored, including any instance cap that applied. A plan built from richer
    in-memory data than the client can see would be a plan they cannot verify.

    Regenerating supersedes: the previous roadmap for this audit is marked
    ``superseded`` rather than deleted, so a plan a client was shown is still
    retrievable after a re-run.
    """
    with privileged_connection() as cur:
        # Through THIS AUDIT'S OWN INSTANCES, not `audit_findings.audit_id`.
        #
        # That column is last-writer-wins: the finding upsert conflicts on
        # (scope_type, scope_key, check_id, fingerprint) and reassigns
        # `audit_id = excluded.audit_id`, so the moment a second audit of the same
        # site runs, every shared finding is re-pointed at the newer run. Keyed on
        # the column, regenerating an older audit's plan then reads zero findings
        # and writes an EMPTY roadmap over the one the client was shown - which is
        # exactly the "the plan was there and now it is gone" report. The report
        # builder was already fixed this way; this is the same join.
        cur.execute(
            """select f.* from public.audit_findings f
               where f.status = 'open'
                 and exists (select 1 from public.audit_finding_instances i
                             where i.finding_id = f.id and i.audit_id = %s)""",
            (audit_id,),
        )
        findings = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "select pages_crawled, basis_hash from public.audit_rollups "
            "where audit_id = %s and level = 'site' limit 1",
            (audit_id,),
        )
        site = cur.fetchone() or {}

        roadmap = RM.build(
            findings,
            pages_crawled=int(site.get("pages_crawled") or 0),
            capacity_points_per_month=capacity_points_per_month,
        )

        # An empty plan never supersedes a real one. An audit that genuinely found
        # nothing has no instances either, so the two cases are distinguishable -
        # and replacing a plan a client was shown with a blank one, because a query
        # went wrong upstream, is the one outcome this function must not produce.
        if not roadmap.items:
            cur.execute(
                "select 1 from public.audit_finding_instances where audit_id = %s limit 1",
                (audit_id,),
            )
            if cur.fetchone() is not None:
                raise RuntimeError(
                    f"refusing to store an empty roadmap for audit {audit_id}: it has "
                    "stored findings, so a plan with no items means the findings query "
                    "failed, not that there is no work to do"
                )

        cur.execute(
            "update public.audit_roadmaps set status = 'superseded' "
            "where audit_id = %s and status <> 'superseded'",
            (audit_id,),
        )
        cur.execute(
            """insert into public.audit_roadmaps
                 (audit_id, client_id, project_id, status, capacity_points_per_month,
                  basis_hash, scoring_model_version, items_total, items_planned,
                  items_backlog)
               values (%s,%s,%s,'active',%s,%s,%s,%s,%s,%s)
               returning id""",
            (
                audit_id, client_id, project_id, roadmap.capacity_points_per_month,
                site.get("basis_hash") or "", RM.SCORING_MODEL_VERSION,
                len(roadmap.items), len(roadmap.planned), len(roadmap.backlog),
            ),
        )
        roadmap_id = _one(cur, "audit_roadmaps insert")["id"]

        rows = [
            (
                roadmap_id, client_id, i.finding_id or None, i.phase, i.sequence,
                i.title, i.check_id, i.pillar, i.subcategory, i.dimension,
                i.owner_role, i.locus_kind, i.locus_value, i.instance_count,
                i.pages_affected, i.severity, i.impact_score, i.effort_points,
                i.priority, i.exit_criterion, i.verification_check,
            )
            for i in roadmap.items
        ]
        for start in range(0, len(rows), _INSERT_BATCH):
            cur.executemany(
                """insert into public.audit_roadmap_items
                     (roadmap_id, client_id, finding_id, phase, sequence, title,
                      check_id, pillar, subcategory, dimension, owner_role,
                      locus_kind, locus_value, instance_count, pages_affected,
                      severity, impact_score, effort_points, priority,
                      exit_criterion, verification_check)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                rows[start:start + _INSERT_BATCH],
            )

    return {
        "items": len(roadmap.items),
        "planned": len(roadmap.planned),
        "backlog": len(roadmap.backlog),
    }
