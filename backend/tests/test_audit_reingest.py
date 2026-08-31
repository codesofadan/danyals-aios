"""Rebuilding a completed audit's findings from the artifacts it already produced.

THE GAP THIS CLOSES. An audit's report and its queryable findings come from two
different steps, and the second one is deliberately non-fatal. That is the right
call - losing a finished client deliverable because a supplementary transform
failed would be strictly worse - but it left no way back. An audit whose ingest
failed was green in the list and a dead end when opened ("No altitude data for
this audit"), while the report it described sat intact on disk. The QA session hit
this from the report side: the audit ran, the report exists, the findings will not
open.

The properties that matter here are the ones that would let a repair LIE:

  * a run with no artifacts must REFUSE, not report a successful rebuild of zero
    findings - which is exactly the empty state it was supposed to fix;
  * a partial rebuild (rows yes, workbook no) must say which half failed;
  * it must never re-run the audit, because that spends money.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services import audit_reingest
from app.services.audit_reingest import ReingestUnavailableError, reingest_audit

pytestmark = pytest.mark.unit


class _Ingested:
    def __init__(self, pages: int, findings: int, instances: int) -> None:
        self.pages = pages
        self.findings = findings
        self.instances = instances
        self.truncated = False


class _Store:
    """Stands in for LocalArtifactStore: only sheets_dir() is used here."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def sheets_dir(self, audit_id: str) -> Path:
        d = self._root / audit_id
        d.mkdir(parents=True, exist_ok=True)
        return d


def _row(tmp: Path, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "aud-1",
        "url": "https://example.com",
        "status": "done",
        "tier": "paid",
        "client_id": "cl-1",
        "client_name": "Verde Cafe",
        "artifact_dir": str(tmp),
        "run_uuid": "u-1",
        "types": [],
        "finished_at": None,
    }
    row.update(over)
    return row


@pytest.fixture
def artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Store:
    monkeypatch.setattr(
        audit_reingest.audit_ingest, "ingest",
        lambda **kw: _Ingested(197, 15617, 8077),
    )
    monkeypatch.setattr(
        audit_reingest.audit_ingest, "store_roadmap", lambda **kw: {"items": 42}
    )
    monkeypatch.setattr(audit_reingest.audit_workbook, "build", lambda **kw: None)
    monkeypatch.setattr(audit_reingest.audit_report, "build", lambda **kw: None)
    return _Store(tmp_path / "sheets")


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #
def test_rebuilds_rows_roadmap_workbook_and_report(tmp_path: Path, artifacts: _Store) -> None:
    art = tmp_path / "run"
    art.mkdir()
    result = reingest_audit(_row(art), artifacts=artifacts)  # type: ignore[arg-type]

    assert (result.pages, result.findings, result.instances) == (197, 15617, 8077)
    assert result.roadmap_items == 42
    assert result.workbook_built and result.report_built
    assert result.notes == []


def test_reads_the_stored_artifact_dir_rather_than_re_running_the_audit(
    tmp_path: Path, artifacts: _Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repair that re-ran the engine would spend real money to fix a bookkeeping
    problem. Assert the ingest is pointed at the run's OWN stored directory."""
    art = tmp_path / "run"
    art.mkdir()
    seen: dict[str, Any] = {}

    def _capture(**kw: Any) -> _Ingested:
        seen.update(kw)
        return _Ingested(1, 2, 3)

    monkeypatch.setattr(audit_reingest.audit_ingest, "ingest", _capture)
    reingest_audit(_row(art, tier="free"), artifacts=artifacts)  # type: ignore[arg-type]

    assert seen["artifact_dir"] == str(art)
    assert seen["audit_id"] == "aud-1"
    assert seen["client_id"] == "cl-1"
    assert seen["site_url"] == "https://example.com"
    assert seen["tier"] == "free"


# --------------------------------------------------------------------------- #
# Refusals: the cases where a "successful" rebuild would be a lie
# --------------------------------------------------------------------------- #
def test_refuses_when_the_artifacts_are_gone(tmp_path: Path, artifacts: _Store) -> None:
    # The directory is recorded but no longer on disk. Rebuilding from nothing
    # would produce zero findings and report success - i.e. reproduce the empty
    # state this endpoint exists to cure, while claiming to have fixed it.
    with pytest.raises(ReingestUnavailableError) as exc:
        reingest_audit(_row(tmp_path / "missing"), artifacts=artifacts)  # type: ignore[arg-type]
    assert "no longer on disk" in str(exc.value)


def test_refuses_when_the_run_recorded_no_artifact_dir(tmp_path: Path, artifacts: _Store) -> None:
    with pytest.raises(ReingestUnavailableError) as exc:
        reingest_audit(_row(tmp_path, artifact_dir=""), artifacts=artifacts)  # type: ignore[arg-type]
    assert "nothing to rebuild" in str(exc.value)


@pytest.mark.parametrize("status", ["queued", "running", "failed"])
def test_refuses_a_run_that_never_completed(
    tmp_path: Path, artifacts: _Store, status: str
) -> None:
    art = tmp_path / "run"
    art.mkdir()
    with pytest.raises(ReingestUnavailableError) as exc:
        reingest_audit(_row(art, status=status), artifacts=artifacts)  # type: ignore[arg-type]
    assert status in str(exc.value)


# --------------------------------------------------------------------------- #
# Partial success must be reported as partial
# --------------------------------------------------------------------------- #
def test_a_workbook_failure_does_not_discard_the_findings_it_did_rebuild(
    tmp_path: Path, artifacts: _Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    art = tmp_path / "run"
    art.mkdir()

    def _boom(**kw: Any) -> None:
        raise RuntimeError("openpyxl exploded")

    monkeypatch.setattr(audit_reingest.audit_workbook, "build", _boom)
    result = reingest_audit(_row(art), artifacts=artifacts)  # type: ignore[arg-type]

    # The rows are the point; the workbook is a download built from them.
    assert result.findings == 15617
    assert result.workbook_built is False
    assert result.report_built is True
    assert any("workbook" in n for n in result.notes)


def test_a_roadmap_failure_is_named_rather_than_hidden(
    tmp_path: Path, artifacts: _Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    art = tmp_path / "run"
    art.mkdir()

    def _boom(**kw: Any) -> dict[str, int]:
        raise RuntimeError("no capacity configured")

    monkeypatch.setattr(audit_reingest.audit_ingest, "store_roadmap", _boom)
    result = reingest_audit(_row(art), artifacts=artifacts)  # type: ignore[arg-type]

    assert result.findings == 15617
    assert result.roadmap_items == 0
    assert any("roadmap" in n for n in result.notes)


def test_an_ingest_failure_is_raised_not_reported_as_an_empty_success(
    tmp_path: Path, artifacts: _Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rows ARE the deliverable here. If they cannot be built the caller must
    see an error, not a cheerful zero."""
    art = tmp_path / "run"
    art.mkdir()

    def _boom(**kw: Any) -> _Ingested:
        raise RuntimeError("malformed findings.json")

    monkeypatch.setattr(audit_reingest.audit_ingest, "ingest", _boom)
    with pytest.raises(RuntimeError, match="malformed"):
        reingest_audit(_row(art), artifacts=artifacts)  # type: ignore[arg-type]


def test_no_artifact_store_still_rebuilds_the_rows_and_says_what_was_skipped(
    tmp_path: Path, artifacts: _Store
) -> None:
    art = tmp_path / "run"
    art.mkdir()
    result = reingest_audit(_row(art), artifacts=None)

    assert result.findings == 15617
    assert result.workbook_built is False
    assert any("artifact store" in n for n in result.notes)
