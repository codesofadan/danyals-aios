"""Reading and answering the Experience questionnaire."""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.core.auth import CurrentUser, require_perm
from app.modules.content_planning.repo import ContentPlanningRepoDep

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["content-experience"])

ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# Supplying a client's first-party facts is content work, so it takes the same
# permission as creating content rather than a read permission.
PublishContent = Annotated[CurrentUser, Depends(require_perm("publish_content"))]


# --------------------------------------------------------------------------- #
# The Experience questionnaire
# --------------------------------------------------------------------------- #
# The doctrine pipeline HALTS every page whose first-party facts nobody has
# supplied (Law 16, the owner's "hard halt, no exceptions"). The SME stage writes
# the questions into `sme_slots` and stops. Until these two routes existed there
# was nowhere to read those questions or send an answer, so a halted page stayed
# halted forever - the gate worked and the door had no handle.
#
# WHY NOT /content/jobs/{code}/experience, which is the shape you would expect:
# `content.py` registers a CATCH-ALL `/content/jobs/{code}/{column}` for the job's
# rich columns, and its router is included first - so that path resolved to the
# catch-all, which 404s any column it does not recognise. Measured, not guessed:
# the route registered fine and every request to it came back 404. A sibling
# router cannot safely add anything under `/content/jobs/{code}/`, so this lives
# in its own namespace where router order cannot reach it.


@router.get("/content/experience/{code}")
def get_experience(code: str, _user: ViewReports, repo: ContentPlanningRepoDep) -> dict[str, Any]:
    """The Experience questions for one content job, and what has been answered.

    A job with no engagement (it has not run yet) is NOT an error: it returns
    `status: "not_started"` with no slots, because the questions do not exist
    until the pipeline asks them.
    """
    found = repo.dossier_for_job(code)
    if found is None:
        return {"code": code, "status": "not_started", "dossierId": None, "slots": []}
    dossier, slots = found
    return {
        "code": code,
        "dossierId": str(dossier["id"]),
        "status": str(dossier.get("status") or "empty"),
        "clusterKey": dossier.get("cluster_key") or "",
        "slots": [
            {
                "slotKey": row["slot_key"],
                "question": row.get("question") or "",
                "answer": row.get("answer") or "",
                "artifactUrl": row.get("artifact_url") or "",
                # The rule the gate actually applies: an artifact alone counts,
                # because a dated photo or a licence document IS the answer.
                "answered": bool(
                    (row.get("answer") or "").strip() or (row.get("artifact_url") or "").strip()
                ),
            }
            for row in slots
        ],
    }


@router.put("/content/experience/{code}")
def put_experience(
    code: str,
    user: PublishContent,
    repo: ContentPlanningRepoDep,
    answers: Annotated[list[dict[str, Any]], Body(embed=True)],
) -> dict[str, Any]:
    """Record answers to the Experience questions and re-derive the status.

    Answers UPDATE existing slots only. The SME stage decides which proof
    categories a page type requires; accepting new keys from the wire would let a
    caller invent a slot and mark the dossier complete without answering what was
    actually asked - which is the one thing this gate exists to prevent.
    """
    found = repo.dossier_for_job(code)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this job has no Experience questions yet; it has not run",
        )
    dossier, slots = found
    known = {row["slot_key"] for row in slots}
    unknown = sorted({str(a.get("slot_key") or "") for a in answers} - known)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown Experience slots: {', '.join(unknown)}",
        )
    status_now = repo.answer_slots(str(dossier["id"]), answers)
    body = get_experience(code, user, repo)

    # A completed dossier RESUMES the page. Without this the questionnaire is a
    # dead end: the halt holds the job at `drafting`, and the worker's guard
    # refuses anything that is not `queued`, so the operator would answer every
    # question and watch nothing happen. Best-effort on purpose - a broker that is
    # down must not lose the answers, which are already committed, so the response
    # reports whether the page was actually re-queued rather than assuming it.
    body["resumed"] = False
    if status_now == "complete":
        try:
            from workers.tasks.content_pipeline import run_content_pipeline_job

            run_content_pipeline_job.delay(code, resume=True)
            body["resumed"] = True
        except Exception as exc:  # broker down / not configured
            logger.warning(
                "experience_resume_enqueue_failed", code=code, error=type(exc).__name__
            )
    return body
