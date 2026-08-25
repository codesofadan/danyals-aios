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
    d.mkdir()
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
