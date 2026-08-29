"""The Experience questionnaire: reading the questions, and answering them.

The doctrine pipeline halts every page whose first-party facts nobody supplied,
writes the questions into `sme_slots`, and stops. Until these routes existed
there was no way to read those questions or send an answer back, so a halted page
stayed halted permanently - a gate that worked attached to a door with no handle.

The rules worth holding here are about what an answer may NOT do: it may not
invent a slot, and it may not leave the status stale.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.content_experience.router import get_experience, put_experience

pytestmark = pytest.mark.unit


class _Repo:
    """Stands in for the RLS-scoped ContentPlanningRepo."""

    def __init__(self, slots: list[dict[str, Any]] | None, *, dossier_id: str = "dos-1") -> None:
        self._slots = slots
        self._dossier_id = dossier_id
        self.written: list[dict[str, Any]] = []
        self.status = "partial"

    def dossier_for_job(self, code: str) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        if self._slots is None:
            return None
        return ({"id": self._dossier_id, "status": self.status, "cluster_key": "plumbing"},
                self._slots)

    def answer_slots(self, dossier_id: str, answers: list[dict[str, Any]]) -> str:
        self.written.extend(answers)
        by_key = {s["slot_key"]: s for s in (self._slots or [])}
        for a in answers:
            slot = by_key.get(str(a.get("slot_key")))
            if slot is not None:
                slot["answer"] = str(a.get("answer") or "")
                slot["artifact_url"] = str(a.get("artifact_url") or "")
        answered = sum(
            1 for s in (self._slots or [])
            if (s.get("answer") or "").strip() or (s.get("artifact_url") or "").strip()
        )
        total = len(self._slots or [])
        self.status = "complete" if total and answered == total else (
            "partial" if answered else "empty"
        )
        return self.status


def _slots() -> list[dict[str, Any]]:
    return [
        {"slot_key": "founding_date", "question": "What year did you start trading?",
         "answer": "", "artifact_url": ""},
        {"slot_key": "license_permit", "question": "What is the licence number?",
         "answer": "", "artifact_url": ""},
    ]


class TestReadingTheQuestions:
    def test_a_job_that_has_not_run_reports_not_started_rather_than_erroring(self) -> None:
        body = get_experience("CJ-4200", None, _Repo(None))  # type: ignore[arg-type]
        assert body["status"] == "not_started"
        assert body["slots"] == []
        assert body["dossierId"] is None

    def test_the_questions_come_back_with_their_answered_state(self) -> None:
        body = get_experience("CJ-4200", None, _Repo(_slots()))  # type: ignore[arg-type]
        assert [s["slotKey"] for s in body["slots"]] == ["founding_date", "license_permit"]
        assert all(s["answered"] is False for s in body["slots"])
        assert body["slots"][0]["question"].startswith("What year")

    def test_an_artifact_alone_counts_as_answered(self) -> None:
        """A dated photo or a licence document IS the evidence; demanding prose
        alongside it would reject the strongest answer an operator can give."""
        slots = _slots()
        slots[0]["artifact_url"] = "https://files.example.com/licence.pdf"
        body = get_experience("CJ-4200", None, _Repo(slots))  # type: ignore[arg-type]
        assert body["slots"][0]["answered"] is True


class TestAnsweringThemResumesTheHaltedPage:
    """Without this the questionnaire is a dead end: the halt holds the job at
    `drafting`, the worker's guard refuses anything that is not `queued`, and the
    operator answers every question to no effect."""

    def test_a_completed_dossier_re_queues_the_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: list[tuple[str, bool]] = []

        class _Task:
            def delay(self, code: str, resume: bool = False) -> None:
                sent.append((code, resume))

        import workers.tasks.content_pipeline as mod

        monkeypatch.setattr(mod, "run_content_pipeline_job", _Task())
        body = put_experience(
            "CJ-4200", None, _Repo(_slots()),  # type: ignore[arg-type]
            [{"slot_key": "founding_date", "answer": "2011"},
             {"slot_key": "license_permit", "answer": "M-41982"}],
        )
        assert sent == [("CJ-4200", True)], "a completed dossier must resume the page"
        assert body["resumed"] is True

    def test_a_partial_dossier_does_not_resume(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: list[tuple[str, bool]] = []

        class _Task:
            def delay(self, code: str, resume: bool = False) -> None:
                sent.append((code, resume))

        import workers.tasks.content_pipeline as mod

        monkeypatch.setattr(mod, "run_content_pipeline_job", _Task())
        body = put_experience(
            "CJ-4200", None, _Repo(_slots()),  # type: ignore[arg-type]
            [{"slot_key": "founding_date", "answer": "2011"}],
        )
        assert sent == [], "a page still missing facts must stay halted"
        assert body["resumed"] is False

    def test_a_broker_that_is_down_does_not_lose_the_answers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The answers are already committed; the response says plainly that the
        page was not re-queued rather than implying it was."""

        class _Task:
            def delay(self, code: str, resume: bool = False) -> None:
                raise RuntimeError("broker unreachable")

        import workers.tasks.content_pipeline as mod

        monkeypatch.setattr(mod, "run_content_pipeline_job", _Task())
        body = put_experience(
            "CJ-4200", None, _Repo(_slots()),  # type: ignore[arg-type]
            [{"slot_key": "founding_date", "answer": "2011"},
             {"slot_key": "license_permit", "answer": "M-41982"}],
        )
        assert body["status"] == "complete", "the answers still landed"
        assert body["resumed"] is False


class TestAnsweringThem:
    def test_an_answer_is_recorded_and_the_status_re_derived(self) -> None:
        repo = _Repo(_slots())
        body = put_experience(
            "CJ-4200", None, repo,  # type: ignore[arg-type]
            [{"slot_key": "founding_date", "answer": "March 2011, SOS reg 0801442917"},
             {"slot_key": "license_permit", "answer": "M-41982, issued by TSBPE"}],
        )
        assert body["status"] == "complete", "every slot answered must clear the halt"
        assert all(s["answered"] for s in body["slots"])

    def test_a_partial_answer_does_not_clear_the_halt(self) -> None:
        repo = _Repo(_slots())
        body = put_experience(
            "CJ-4200", None, repo,  # type: ignore[arg-type]
            [{"slot_key": "founding_date", "answer": "March 2011"}],
        )
        assert body["status"] == "partial"

    def test_an_invented_slot_key_is_refused(self) -> None:
        """The SME stage decides which proof categories a page type requires.
        Accepting a made-up key would let a caller mark the dossier complete
        without answering what was actually asked."""
        from fastapi import HTTPException

        repo = _Repo(_slots())
        with pytest.raises(HTTPException) as exc:
            put_experience(
                "CJ-4200", None, repo,  # type: ignore[arg-type]
                [{"slot_key": "totally_made_up", "answer": "anything"}],
            )
        assert exc.value.status_code == 400
        assert "totally_made_up" in str(exc.value.detail)
        assert repo.written == [], "nothing may be written when any key is unknown"

    def test_answering_a_job_that_never_ran_is_a_conflict_not_a_silent_no_op(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            put_experience("CJ-4200", None, _Repo(None),  # type: ignore[arg-type]
                           [{"slot_key": "founding_date", "answer": "x"}])
        assert exc.value.status_code == 409
