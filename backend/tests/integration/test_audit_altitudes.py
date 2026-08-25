"""The altitude spine against real Postgres.

Verified against real run 837b75d6 (smileon.pk, 197 pages): 15,617 findings ->
197 pages + 461 causes + 8,077 instances + 105 rollups, ingested in 1.3s, and
byte-for-byte identical on a second ingest.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.config import get_settings
from app.db.database import (
    build_admin_pool,
    build_rls_pool,
    clear_pools,
    privileged_connection,
    set_pools,
)
from app.services import audit_ingest

pytestmark = pytest.mark.integration


def _require_local_stack():
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")
    return settings


@pytest.fixture()
def pools():
    settings = _require_local_stack()
    rls = build_rls_pool(settings.database_url)
    admin = build_admin_pool(settings.database_admin_url)
    rls.open()
    admin.open()
    set_pools(rls, admin)
    try:
        yield
    finally:
        clear_pools()
        rls.close()
        admin.close()


def _artifacts(tmp_path: Path, findings: list[dict], pages: list[dict], coverage: dict) -> Path:
    d = tmp_path / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "findings.json").write_text(json.dumps(findings))
    (d / "pages.json").write_text(json.dumps(pages))
    (d / "coverage.json").write_text(json.dumps(coverage))
    return d


def _seed_audit(url: str = "https://alt.test") -> str:
    audit_id = str(uuid.uuid4())
    with privileged_connection() as cur:
        cur.execute(
            """insert into public.audits (id, url, client_name, tier, status)
               values (%s, %s, 'Alt Test', 'paid', 'done')""",
            (audit_id, url),
        )
    return audit_id


def _finding(check_id, page_id, *, status="fail", severity="major", evidence=None):
    return {
        "check_id": check_id, "check_name": f"{check_id} name", "category": "on-page",
        "pillar": "on-page", "subcategory": "headings", "dimension": "onpage",
        "owner_agent": "A3", "automation": "full", "status": status,
        "severity": severity, "page_id": page_id, "confidence": 0.9,
        "evidence_json": json.dumps(evidence or {"n": page_id}), "remediation": "fix it",
    }


def _coverage(ran: list[str]) -> dict:
    return {
        "registry_total": 2,
        "ran": ran,
        "skipped": [{"check_id": "ON-002", "reason": "no_finding_emitted"}] if "ON-002" not in ran else [],
        "checks": {
            "ON-001": {"name": "one", "pillar": "on-page", "subcategory": "headings",
                       "dimension": "onpage", "owner_agent": "A3",
                       "severity_default": "major", "automation": "full"},
            "ON-002": {"name": "two", "pillar": "on-page", "subcategory": "headings",
                       "dimension": "onpage", "owner_agent": "A3",
                       "severity_default": "major", "automation": "full"},
        },
    }


PAGES = [
    {"page_id": 1, "url": "https://alt.test/s/a", "http_status": 200, "indexable": 1},
    {"page_id": 2, "url": "https://alt.test/s/b", "http_status": 200, "indexable": 1},
    {"page_id": 3, "url": "https://alt.test/s/c", "http_status": 200, "indexable": 0},
]


def test_one_cause_many_instances_lands_at_three_altitudes(pools, tmp_path):
    """The headline: three page-level rows become ONE finding with THREE
    instances, and the page dimension is queryable on its own."""
    audit_id = _seed_audit()
    d = _artifacts(
        tmp_path,
        [_finding("ON-001", p) for p in (1, 2, 3)],
        PAGES,
        _coverage(["ON-001"]),
    )
    res = audit_ingest.ingest(
        audit_id=audit_id, client_id=None, artifact_dir=d,
        site_url="https://alt.test", tier="paid", types=[],
    )
    assert (res.pages, res.findings, res.instances) == (3, 1, 3)
    assert res.scope_key == "alt.test"

    with privileged_connection() as cur:
        cur.execute(
            "select locus_kind, locus_value, instance_count, pages_affected "
            "from public.audit_findings where audit_id = %s", (audit_id,))
        f = cur.fetchone()
        assert f["locus_kind"] == "template"
        assert f["locus_value"] == "/s/{slug}"
        assert f["instance_count"] == 3 and f["pages_affected"] == 3

        cur.execute(
            "select url from public.audit_finding_instances where audit_id = %s order by url",
            (audit_id,))
        assert [r["url"] for r in cur.fetchall()] == [
            "https://alt.test/s/a", "https://alt.test/s/b", "https://alt.test/s/c"]


def test_a_page_row_carries_the_url_a_finding_never_had(pools, tmp_path):
    audit_id = _seed_audit()
    d = _artifacts(tmp_path, [_finding("ON-001", 1)], PAGES, _coverage(["ON-001"]))
    audit_ingest.ingest(audit_id=audit_id, client_id=None, artifact_dir=d,
                        site_url="https://alt.test", tier="paid", types=[])
    with privileged_connection() as cur:
        cur.execute("select url, template_id, indexable, issues_total, health_pass "
                    "from public.audit_pages where audit_id=%s order by url", (audit_id,))
        rows = cur.fetchall()
        assert len(rows) == 3
        assert rows[0]["template_id"] == "/s/{slug}"
        # SQLite emits 0/1; the column is boolean and must not have been cast away
        assert rows[0]["indexable"] is True and rows[2]["indexable"] is False


def test_rollups_record_coverage_and_never_score_an_unmeasured_dimension(pools, tmp_path):
    audit_id = _seed_audit()
    d = _artifacts(tmp_path, [_finding("ON-001", 1)], PAGES, _coverage(["ON-001"]))
    audit_ingest.ingest(audit_id=audit_id, client_id=None, artifact_dir=d,
                        site_url="https://alt.test", tier="paid", types=[])
    with privileged_connection() as cur:
        cur.execute("select level, key, score, checks_ran, checks_applicable "
                    "from public.audit_rollups where audit_id=%s and level='site'", (audit_id,))
        site = cur.fetchone()
        assert site["checks_ran"] == 1 and site["checks_applicable"] == 2
        assert site["score"] is not None


def test_re_ingest_is_idempotent_and_upserts_rather_than_duplicates(pools, tmp_path):
    """Retrying a crashed ingest must not corrupt a client's history."""
    audit_id = _seed_audit()
    d = _artifacts(tmp_path, [_finding("ON-001", p) for p in (1, 2, 3)], PAGES, _coverage(["ON-001"]))
    kw = dict(audit_id=audit_id, client_id=None, artifact_dir=d,
              site_url="https://alt.test", tier="paid", types=[])
    first = audit_ingest.ingest(**kw)
    second = audit_ingest.ingest(**kw)
    assert (first.pages, first.findings, first.instances) == \
           (second.pages, second.findings, second.instances)
    with privileged_connection() as cur:
        cur.execute("select count(*) c from public.audit_findings where audit_id=%s", (audit_id,))
        assert cur.fetchone()["c"] == 1
        cur.execute("select first_seen_at < last_seen_at as advanced "
                    "from public.audit_findings where audit_id=%s", (audit_id,))
        assert cur.fetchone()["advanced"] is True


def test_two_analyzers_on_one_page_are_two_instances_not_one(pools, tmp_path):
    """394 of 8,077 real instances share a (cause, url) pair with DIFFERENT
    evidence. A url-only key silently dropped them."""
    audit_id = _seed_audit()
    findings = [
        _finding("ON-001", 1, evidence={"a": 1}),
        _finding("ON-001", 1, evidence={"b": 2}),
        _finding("ON-001", 2, evidence={"a": 1}),
    ]
    d = _artifacts(tmp_path, findings, PAGES, _coverage(["ON-001"]))
    res = audit_ingest.ingest(audit_id=audit_id, client_id=None, artifact_dir=d,
                              site_url="https://alt.test", tier="paid", types=[])
    assert res.instances == 3 == res.instances_observed
    assert res.truncated == 0


def test_a_missing_artifact_is_an_empty_ingest_not_a_crash(pools, tmp_path):
    """An older engine build simply has nothing to offer at these altitudes."""
    audit_id = _seed_audit()
    empty = tmp_path / "nothing"
    empty.mkdir()
    res = audit_ingest.ingest(audit_id=audit_id, client_id=None, artifact_dir=empty,
                              site_url="https://alt.test", tier="paid", types=[])
    assert (res.pages, res.findings, res.instances) == (0, 0, 0)


def test_deleting_an_audit_removes_its_altitude_rows(pools, tmp_path):
    """No orphan rows: the cascade is what keeps the tables honest over time."""
    audit_id = _seed_audit()
    d = _artifacts(tmp_path, [_finding("ON-001", 1)], PAGES, _coverage(["ON-001"]))
    audit_ingest.ingest(audit_id=audit_id, client_id=None, artifact_dir=d,
                        site_url="https://alt.test", tier="paid", types=[])
    with privileged_connection() as cur:
        cur.execute("delete from public.audits where id=%s", (audit_id,))
        cur.execute("select count(*) c from public.audit_pages where audit_id=%s", (audit_id,))
        assert cur.fetchone()["c"] == 0
        cur.execute("select count(*) c from public.audit_rollups where audit_id=%s", (audit_id,))
        assert cur.fetchone()["c"] == 0


def test_a_later_audit_of_the_same_site_does_not_edit_the_earlier_one(pools, tmp_path):
    """The defect this pins, measured on real data.

    A finding is a persistent CAUSE that many audits observe; an instance is what
    ONE audit saw. Two mistakes made a re-run rewrite history:

      * instances were deleted by `finding_id` alone, so a later run erased an
        earlier run's evidence for every cause they shared;
      * instance identity was `(finding_id, instance_key)` with no audit, so the
        second audit to see the same page fail the same check was silently
        dropped by `on conflict do nothing`.

    Together they cut a real 197-page audit from 8,077 occurrences to 7,591 the
    moment a 12-page run of the same site was ingested - with no error. A report
    that a later run can quietly edit is not a record.
    """
    # A findings row is keyed on scope_key and OUTLIVES any single audit - that is
    # the whole point of it. So this test needs its own host, or it counts causes
    # every other test in this file left behind.
    host = f"hist-{uuid.uuid4().hex[:8]}.test"
    first = _seed_audit(f"https://{host}")
    second = _seed_audit(f"https://{host}")
    pages = [dict(p, url=p["url"].replace("alt.test", host)) for p in PAGES]

    # Both audits see the SAME cause on the SAME pages - the overlap is the point.
    d1 = _artifacts(tmp_path / "a", [_finding("ON-001", p) for p in (1, 2, 3)],
                    pages, _coverage(["ON-001"]))
    d2 = _artifacts(tmp_path / "b", [_finding("ON-001", p) for p in (1, 2)],
                    pages[:2], _coverage(["ON-001"]))

    r1 = audit_ingest.ingest(audit_id=first, client_id=None, artifact_dir=d1,
                             site_url=f"https://{host}", tier="paid", types=[])
    assert r1.instances == 3

    r2 = audit_ingest.ingest(audit_id=second, client_id=None, artifact_dir=d2,
                             site_url=f"https://{host}", tier="paid", types=[])
    assert r2.instances == 2, "the second audit must record its own evidence"

    with privileged_connection() as cur:
        # The earlier audit still holds everything it observed.
        cur.execute(
            "select count(*) c from public.audit_finding_instances where audit_id = %s",
            (first,))
        assert cur.fetchone()["c"] == 3, "a later run erased the earlier run's evidence"
        cur.execute(
            "select count(*) c from public.audit_finding_instances where audit_id = %s",
            (second,))
        assert cur.fetchone()["c"] == 2

        # One CAUSE, shared - that part is meant to be shared.
        cur.execute("select count(*) c from public.audit_findings where scope_key = %s",
                    (host,))
        assert cur.fetchone()["c"] == 1


def test_a_report_reads_the_findings_its_own_audit_observed(pools, tmp_path):
    """`audit_findings.audit_id` is last-writer-wins, so a report keyed on it
    loses findings the moment a newer audit of the same site upserts them. The
    report joins through the audit's own instances instead."""
    host = f"obs-{uuid.uuid4().hex[:8]}.test"
    first = _seed_audit(f"https://{host}")
    second = _seed_audit(f"https://{host}")
    pages = [dict(p, url=p["url"].replace("alt.test", host)) for p in PAGES]
    d1 = _artifacts(tmp_path / "a",
                    [_finding("ON-001", 1), _finding("ON-002", 2)], pages,
                    _coverage(["ON-001", "ON-002"]))
    d2 = _artifacts(tmp_path / "b", [_finding("ON-001", 1)], pages[:1],
                    _coverage(["ON-001"]))
    audit_ingest.ingest(audit_id=first, client_id=None, artifact_dir=d1,
                        site_url=f"https://{host}", tier="paid", types=[])
    audit_ingest.ingest(audit_id=second, client_id=None, artifact_dir=d2,
                        site_url=f"https://{host}", tier="paid", types=[])

    with privileged_connection() as cur:
        # ON-001 was re-observed, so its `audit_id` now points at the SECOND run.
        cur.execute("select audit_id from public.audit_findings"
                    " where check_id = 'ON-001' and scope_key = %s", (host,))
        assert str(cur.fetchone()["audit_id"]) == second

        # The first audit's report must still show BOTH of its findings.
        cur.execute(
            "select count(*) c from public.audit_findings f"
            " where exists (select 1 from public.audit_finding_instances i"
            "               where i.finding_id = f.id and i.audit_id = %s)",
            (first,))
        assert cur.fetchone()["c"] == 2
