"""Offboarding a CLIENT: what is destroyed, what is kept, and what is said out loud.

(Distinct from ``test_offboarding.py``, which is about removing a PERSON's access.)

The dangerous shape here is not deleting too much - it is deleting the row and leaving the
data. ``audits.client_id`` links ``on delete set null`` by design, so removing a client used
to leave every audit of theirs in place, INCLUDING any published public report page, which
stayed openable by anyone holding the URL.

So four properties are pinned:

  * THE LINKS DIE FIRST. Withdrawal happens before any row is deleted, because it is the
    one consequence visible to the outside world.
  * THE PREVIEW IS THE NUMBER THE PURGE ACTS ON. A destructive action nobody can inspect
    first is one nobody uses, and then the data stays anyway.
  * WHAT IS KEPT IS STATED. The cost ledger, the activity log and hash-shared images are
    deliberately kept, so "delete everything" is never a promise the platform breaks.
  * A PATH OUTSIDE THE ARTIFACT ROOT IS NOT OURS TO DELETE, however it got into the column,
    and a file the OS will not release must not leave the client's ROWS behind - the rows
    are the half that keeps the platform rendering their data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services import client_offboarding
from app.services.client_offboarding import KEPT_ALWAYS, preview, purge

pytestmark = pytest.mark.unit


class _Cur:
    """A psycopg-cursor double that answers by SQL shape and records every statement."""

    def __init__(self, dirs: list[str], *, counts: dict[str, Any] | None = None) -> None:
        self.dirs = dirs
        self.counts = counts or {}
        self.sql: list[str] = []
        self.rowcount = 0
        self._rows: list[dict[str, Any]] = []
        self._row: dict[str, Any] | None = None

    def execute(self, sql: str, params: Any = None) -> None:
        flat = " ".join(sql.split()).lower()
        self.sql.append(flat)
        self._rows, self._row, self.rowcount = [], None, 0
        if flat.startswith("select name from public.clients"):
            self._row = {"name": "Acme Plumbing"}
        elif "from public.audits where client_id" in flat and "count(*)" in flat:
            self._row = {"n": self.counts.get("audits", 3), "dirs": len(self.dirs)}
        elif "public_audit_pages" in flat and "count(*)" in flat:
            self._row = {"n": self.counts.get("pages", 1)}
        elif "from public.content_jobs where client_id" in flat and "count(*)" in flat:
            self._row = {"n": self.counts.get("content", 2), "live": self.counts.get("live", 1)}
        elif flat.startswith("update public.public_audit_pages"):
            self.rowcount = self.counts.get("pages", 1)
        elif "select artifact_dir from public.audits" in flat:
            self._rows = [{"artifact_dir": d} for d in self.dirs]
        elif flat.startswith("delete from public.audits"):
            self.rowcount = self.counts.get("audits", 3)
        elif flat.startswith("delete from public.content_jobs"):
            self.rowcount = self.counts.get("content", 2)
        elif flat.startswith("delete from public.clients"):
            self.rowcount = 1

    def fetchone(self) -> dict[str, Any] | None:
        return self._row

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


@pytest.fixture
def cursor(monkeypatch: pytest.MonkeyPatch) -> Any:
    """One cursor shared across both ``privileged_connection`` blocks, so the ORDER of
    statements across them is observable - which is the property under test."""
    state: dict[str, Any] = {}

    def _install(dirs: list[str], **counts: Any) -> _Cur:
        cur = _Cur(dirs, counts=counts)
        state["cur"] = cur

        class _Ctx:
            def __enter__(self) -> _Cur:
                return cur

            def __exit__(self, *_a: Any) -> None:
                return None

        monkeypatch.setattr(client_offboarding, "privileged_connection", lambda: _Ctx())
        return cur

    return _install


def test_the_preview_counts_real_rows_and_touches_nothing(cursor: Any) -> None:
    cur = cursor([], audits=3, pages=1, content=2, live=1)
    plan = preview("cl-1")
    assert (plan.client_name, plan.audits, plan.published_pages, plan.content_jobs) == (
        "Acme Plumbing", 3, 1, 2,
    )
    assert all(s.startswith("select") for s in cur.sql), cur.sql


def test_the_preview_says_what_will_survive(cursor: Any) -> None:
    cursor([], live=2)
    plan = preview("cl-1")
    for kept in KEPT_ALWAYS:
        assert kept in plan.kept
    # Pages already on the CLIENT'S OWN site are theirs, and only they can remove them.
    assert any("2 page(s)" in k and "own" in k for k in plan.kept), plan.kept


def test_no_live_pages_means_no_misleading_keep_line(cursor: Any) -> None:
    cursor([], live=0)
    plan = preview("cl-1")
    assert not any("page(s)" in k for k in plan.kept)
    assert plan.as_dict()["publishedContent"] == 0


def test_the_public_links_are_withdrawn_before_a_single_row_is_deleted(
    cursor: Any, tmp_path: Path
) -> None:
    cur = cursor([], audits=2, pages=1, content=1)
    purge("cl-1")
    withdrawn = next(i for i, s in enumerate(cur.sql) if s.startswith("update public.public_audit_pages"))
    first_delete = next(i for i, s in enumerate(cur.sql) if s.startswith("delete"))
    assert withdrawn < first_delete, cur.sql


def test_the_artifacts_are_removed_and_counted(cursor: Any, tmp_path: Path) -> None:
    live = tmp_path / "audit-1"
    (live / "sheets").mkdir(parents=True)
    (live / "report.pdf").write_bytes(b"pdf")
    cursor([str(live)])
    out = purge("cl-1", artifact_root=str(tmp_path))
    assert out.artifact_dirs_removed == 1
    assert not live.exists()
    assert out.client_deleted is True
    assert out.notes == []


def test_a_path_outside_the_artifact_root_is_reported_not_deleted(
    cursor: Any, tmp_path: Path
) -> None:
    outside = tmp_path.parent / "not-ours"
    outside.mkdir(exist_ok=True)
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    cursor([str(outside)])
    try:
        out = purge("cl-1", artifact_root=str(tmp_path / "store"))
        assert out.artifact_dirs_removed == 0
        assert any("outside the store" in n for n in out.notes)
        assert (outside / "keep.txt").exists()
        # ...and the rows still went, because the rows are what keeps rendering their data.
        assert out.client_deleted is True
    finally:
        (outside / "keep.txt").unlink()
        outside.rmdir()


def test_a_directory_that_cannot_be_removed_still_lets_the_rows_go(
    cursor: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stuck = tmp_path / "audit-2"
    stuck.mkdir()
    cursor([str(stuck)])

    def _boom(_path: Any) -> None:
        raise OSError("file in use")

    monkeypatch.setattr(client_offboarding.shutil, "rmtree", _boom)
    out = purge("cl-1", artifact_root=str(tmp_path))
    assert out.artifact_dirs_removed == 0
    assert any("could not remove" in n for n in out.notes)
    assert out.client_deleted is True


def test_the_result_reports_what_was_actually_destroyed(cursor: Any) -> None:
    cursor([], audits=3, pages=1, content=2)
    out = purge("cl-1").as_dict()
    assert out["auditsDeleted"] == 3
    assert out["contentJobsDeleted"] == 2
    assert out["pagesWithdrawn"] == 1
    assert out["client"] == "Acme Plumbing"


def test_nothing_in_the_purge_touches_the_cost_ledger_or_activity_log(cursor: Any) -> None:
    cur = cursor([])
    purge("cl-1")
    joined = " ".join(cur.sql)
    assert "cost_log" not in joined
    assert "activity_log" not in joined
