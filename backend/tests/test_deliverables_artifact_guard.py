"""A ``ready`` deliverable must carry an artifact, or it is a broken download button.

``client_deliverables`` rows are what the client's Reports library renders. A row with
``status='ready'`` gets View and Download controls; the download resolves
``artifact_key`` to a path on disk and 404s when the key is NULL.

THE DEFECT THIS PREVENTS (measured 2026-08-25). Two producers emitted with the
function's own defaults - ``artifact_key=None``, ``status="ready"``:

* ``app/routers/reports.py`` on a Google-Sheets workbook sync ("Monthly SEO Report")
* ``workers/tasks/offpage.py`` at the end of a backlink sweep ("Backlink Profile")

Neither renders a PDF, so both published a permanent, guaranteed 404 into a paying
client's report library. The audit and content workers pass a real key and are
unaffected - which is why no test caught it: the two correct callers were the tested
ones.

``generating`` would not have been honest either. It renders as "In progress", which
is a claim that a file is coming; for these two producers nothing is coming.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services import deliverables

pytestmark = pytest.mark.unit


def _emit(**over: Any) -> MagicMock:
    """Call emit_deliverable with a valid base payload, capturing any DB write."""
    cur = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cur)
    ctx.__exit__ = MagicMock(return_value=False)
    base: dict[str, Any] = {
        "client_id": "c-1",
        "client_name": "Bellevue Dental",
        "title": "Monthly SEO Report",
        "kind": "Monthly",
        "requires": "monthly_report",
        "source_kind": "report",
        "source_id": "wb-1",
        "icon": "summarize",
    }
    base.update(over)
    with patch.object(deliverables, "privileged_connection", return_value=ctx):
        deliverables.emit_deliverable(**base)
    return cur


def test_ready_without_an_artifact_is_not_published() -> None:
    """The exact shape both broken producers used: defaults, and no key."""
    cur = _emit()
    assert cur.execute.call_count == 0, (
        "a ready deliverable with no artifact_key was written - the client would see a "
        "Download button whose endpoint 404s"
    )


def test_ready_with_an_artifact_is_published() -> None:
    cur = _emit(artifact_key="audits/run-1/report.pdf")
    assert cur.execute.call_count == 1


def test_generating_is_still_allowed_without_an_artifact() -> None:
    """A real in-progress row has no key YET; that is a promise, not a lie."""
    cur = _emit(status="generating")
    assert cur.execute.call_count == 1


@pytest.mark.parametrize("empty", ["", None])
def test_an_empty_key_counts_as_no_artifact(empty: str | None) -> None:
    cur = _emit(artifact_key=empty)
    assert cur.execute.call_count == 0


def test_the_guard_never_raises_into_the_producing_job() -> None:
    """emit_deliverable is best-effort by contract - a skip must not break the job."""
    _emit()  # would raise out of the helper if it did


def test_the_two_known_producers_still_pass_no_artifact_key() -> None:
    """Documents WHY those two now publish nothing, so the skip is not read as a bug.

    If either learns to render a real file, it will pass `artifact_key` and this test
    should be updated along with it.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for rel in ("app/routers/reports.py", "workers/tasks/offpage.py"):
        src = (root / rel).read_text(encoding="utf-8")
        assert "emit_deliverable" in src, f"{rel} no longer emits a deliverable"
        head = src.split("emit_deliverable", 1)[1][:600]
        assert "artifact_key" not in head, (
            f"{rel} now passes artifact_key - it renders a real file, so update this "
            f"test and confirm its deliverable is genuinely downloadable"
        )


# --------------------------------------------------------------------------- #
# The review gate: a document reaches a client because someone decided it should.
#
# Every producer used to write straight to `ready`, and `portal_deliverables` shows
# any ready row whose grant key the client holds - so an audit PDF was in front of
# the client the moment the job finished, with no review, and no way to hold one
# back short of revoking the whole report grant (which removes every other document
# of that kind at the same time).
# --------------------------------------------------------------------------- #
def _written(cur: MagicMock) -> dict[str, Any]:
    """The parameters emit_deliverable actually wrote, keyed by column."""
    params = cur.execute.call_args.args[1]
    return dict(zip(deliverables._COLUMNS, params, strict=True))


def test_a_produced_document_waits_for_a_decision_by_default() -> None:
    cur = _emit(artifact_key="audits/a-1/report.pdf")
    assert cur.execute.call_count == 1
    assert _written(cur)["status"] == "pending_review"


def test_a_document_awaiting_review_carries_no_issue_date() -> None:
    """`issued_at` is when the CLIENT got the document, not when it was produced -
    so it is stamped at publish. A date set here would tell a client they had been
    given something days before anyone released it."""
    cur = _emit(artifact_key="audits/a-1/report.pdf")
    assert _written(cur)["issued_at"] is None


def test_an_explicit_ready_status_is_still_honoured() -> None:
    """The parameter is not decorative: a caller that has already made the decision
    (a restore, a migration) can still write a released document."""
    cur = _emit(artifact_key="audits/a-1/report.pdf", status="ready")
    row = _written(cur)
    assert row["status"] == "ready"
    assert row["issued_at"] is not None
