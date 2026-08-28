"""Where the plan's findings come from - and what it refuses to overwrite.

The "Now / Next / Then / Later" board on an audit's Strategy tab is
`audit_roadmaps`, written once by `store_roadmap` at ingest. It read
`audit_findings.audit_id`, which is LAST-WRITER-WINS: the finding upsert conflicts
on (scope_type, scope_key, check_id, fingerprint) and reassigns
`audit_id = excluded.audit_id`, so a second audit of the same site re-points every
shared finding at the newer run. Regenerating an older audit's plan then read zero
findings and wrote an empty roadmap over the one a client had been shown.

The report builder already carried the fix and a docstring explaining it; the
roadmap did not. These pin both halves without a database: the SQL must join
through the audit's own instances, and an empty plan must never supersede a real
one while that audit still has findings stored.
"""

from __future__ import annotations

import pytest

from app.services import audit_ingest as I


class FakeCursor:
    """Records every statement, and answers the two reads store_roadmap makes."""

    def __init__(self, findings: list[dict], site: dict, has_instances: bool) -> None:
        self.sql: list[str] = []
        self._findings = findings
        self._site = site
        self._has_instances = has_instances
        self._next: list | None = None

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        low = sql.lower()
        if "from public.audit_findings" in low:
            self._next = list(self._findings)
        elif "audit_rollups" in low:
            self._next = [self._site]
        elif "from public.audit_finding_instances" in low and "limit 1" in low:
            self._next = [{"x": 1}] if self._has_instances else []
        elif "returning id" in low:
            self._next = [{"id": "rm-1"}]
        else:
            self._next = []

    def executemany(self, sql, rows):
        self.sql.append(" ".join(sql.split()))

    def fetchall(self):
        return self._next or []

    def fetchone(self):
        return (self._next or [None])[0]


@pytest.fixture
def wire(monkeypatch):
    """Point store_roadmap at a fake cursor and hand it back for inspection."""
    def _wire(*, findings, has_instances):
        cur = FakeCursor(findings, {"pages_crawled": 10, "basis_hash": "b"}, has_instances)

        class Ctx:
            def __enter__(self):
                return cur

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(I, "privileged_connection", lambda: Ctx())
        return cur

    return _wire


def _finding(i: int) -> dict:
    return {
        "id": f"f{i}", "check_id": f"ON-{i:03d}", "check_name": f"Issue {i}",
        "pillar": "on-page", "subcategory": "titles", "dimension": "onpage",
        "severity": "major", "locus_kind": "page", "locus_value": "",
        "instance_count": 3, "pages_affected": 3, "confidence": 1.0,
        "remediation": "Fix it.",
    }


def test_the_plan_reads_this_audits_own_instances_not_the_shared_column(wire):
    cur = wire(findings=[_finding(1)], has_instances=True)
    I.store_roadmap(audit_id="aud-1", client_id="c-1")
    reads = [s for s in cur.sql if "from public.audit_findings" in s.lower()]
    assert len(reads) == 1
    sql = reads[0]
    # The join is the fix. Without it the query is keyed on a column a later audit
    # of the same site silently takes ownership of.
    assert "audit_finding_instances" in sql
    assert "f.audit_id = %s" not in sql
    assert "where f.status = 'open'" in sql


def test_an_empty_plan_never_supersedes_a_real_one(wire):
    # No findings came back, but this audit HAS instances stored - so the findings
    # query is what failed, not the site that got healthy.
    wire(findings=[], has_instances=True)
    with pytest.raises(RuntimeError, match="refusing to store an empty roadmap"):
        I.store_roadmap(audit_id="aud-1", client_id="c-1")


def test_the_previous_plan_is_not_superseded_when_the_write_is_refused(wire):
    cur = wire(findings=[], has_instances=True)
    with pytest.raises(RuntimeError):
        I.store_roadmap(audit_id="aud-1", client_id="c-1")
    # The refusal has to come BEFORE the supersede, or the plan is destroyed on the
    # way to raising about it.
    assert not any("set status = 'superseded'" in s for s in cur.sql)


def test_an_audit_that_genuinely_found_nothing_still_gets_an_empty_plan(wire):
    cur = wire(findings=[], has_instances=False)
    out = I.store_roadmap(audit_id="aud-1", client_id="c-1")
    assert out["items"] == 0
    # Nothing to plan is a legitimate result, and it must still write a roadmap row
    # so the Strategy tab says "no work" rather than "no plan".
    assert any("insert into public.audit_roadmaps" in s for s in cur.sql)


def test_a_real_plan_is_written_with_its_items(wire):
    cur = wire(findings=[_finding(i) for i in range(1, 6)], has_instances=True)
    out = I.store_roadmap(audit_id="aud-1", client_id="c-1")
    assert out["items"] == 5
    assert any("insert into public.audit_roadmap_items" in s for s in cur.sql)
    assert any("set status = 'superseded'" in s for s in cur.sql)
