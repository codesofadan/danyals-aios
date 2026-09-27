"""Reading and answering the Experience questionnaire.

WHAT CHANGED, 2026-09-26 (the operator's decision). The questions are still the same
questions and the halt is still the same halt - what changed is that each one now arrives
with PICKABLE OPTIONS drawn from the client's own evidence, so a business owner confirms
facts instead of composing paragraphs. The options come from
``app.services.experience_options``, which is a pure extractor over what the client
already gave us: their prior attestations for other clusters, the proof points and data
supplied for this build, their stored business record, their own site copy. No option is
generated, none is inferred from what similar businesses usually do, and there is no
model call anywhere in this path.

That restraint is the whole safety argument. A dropdown of plausible-sounding answers
would be the fabrication the gate exists to stop, wearing a click; a dropdown of the
client's own facts is the gate being satisfied the way it was meant to be. Every stored
answer therefore records WHO attested it and ON WHAT EVIDENCE (migration 0155), because
an answer nobody can account for is indistinguishable from an invented one six months
later.

Two structural options are not extractions and are deliberate non-claims: "we do not have
this - do not reference it", which satisfies the gate while forbidding the claim, and
"I will attach the proof", which routes the answer to the artifact field. Free text is
always available and always first-class: a dropdown cannot carry the story of the job that
taught you something, and the moment it pretends to, the client picks the nearest lie.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_perm
from app.modules.content_planning.repo import ContentPlanningRepoDep
from app.services.experience_options import (
    Evidence,
    PriorAnswer,
    evidence_from,
    options_for_all,
)

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


def fmt_day(value: Any) -> str:
    """A date a client can recognise ("12 Sep 2026"), or "" when there is none."""
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y")
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    return ""


def build_evidence(
    repo: Any, job: dict[str, Any], *, dossier_id: str | None = None
) -> Evidence:
    """Gather what we legitimately know about this client, for the option list.

    Never raises on a missing piece: fewer inputs means fewer options, which is a
    smaller pick list and not a broken screen. A prior-answer lookup that fails is
    logged and skipped rather than taking the questionnaire down with it - the
    questions themselves do not depend on it.
    """
    prior: tuple[PriorAnswer, ...] = ()
    try:
        rows = repo.prior_answers_for_client(
            job.get("client_id"), exclude_dossier_id=dossier_id
        )
        prior = tuple(
            PriorAnswer(
                slot_key=str(row.get("slot_key") or ""),
                answer=str(row.get("answer") or ""),
                cluster_key=str(row.get("cluster_key") or ""),
                answered_on=fmt_day(row.get("answered_at")),
            )
            for row in rows
        )
    except Exception as exc:  # a view/permission/shape problem must not hide the questions
        logger.warning("experience_prior_lookup_failed", error=type(exc).__name__)

    client: dict[str, Any] = {}
    getter = getattr(repo, "client_facts", None)
    if callable(getter):
        try:
            client = getter(job.get("client_id")) or {}
        except Exception as exc:
            # LOGGED, because the silent version cost this feature half its options. The
            # lookup asked for two columns that do not exist, this except turned the
            # failure into `{}`, and the screen then read exactly like a client with no
            # business record on file - so nothing looked wrong and the record-derived
            # options were simply never offered. The catch is still right (a lookup
            # problem must not hide the questions); its silence was not.
            logger.warning("experience_client_facts_failed", error=type(exc).__name__)
            client = {}
    # The client's own blurb reads as site copy because that is what it is - the words the
    # client wrote about themselves. A founding year or a job count sitting in that text is
    # the client's own claim, which is exactly what may be offered back for confirmation.
    site_copy = tuple(
        str(client.get(field) or "")
        for field in ("description",)
        if str(client.get(field) or "").strip()
    )
    pack = job.get("source_pack") if isinstance(job.get("source_pack"), dict) else {}
    return evidence_from(
        client=client, source_pack=pack or {}, site_copy=site_copy, prior=prior
    )


def _slot_payload(row: dict[str, Any], options: list[Any]) -> dict[str, Any]:
    return {
        "slotKey": row["slot_key"],
        "question": row.get("question") or "",
        "answer": row.get("answer") or "",
        "artifactUrl": row.get("artifact_url") or "",
        # The rule the gate actually applies: an artifact alone counts,
        # because a dated photo or a licence document IS the answer.
        "answered": bool(
            (row.get("answer") or "").strip() or (row.get("artifact_url") or "").strip()
        ),
        # The attestation, surfaced so a reviewer can see it without a DB query.
        "source": str(row.get("source") or ""),
        "answerEvidence": row.get("answer_evidence") or "",
        "answeredOn": fmt_day(row.get("answered_at")),
        # The pick list. Empty is a legitimate answer: the client types instead.
        "options": [o.as_dict() for o in options],
    }


def _experience_body(
    code: str, repo: Any, *, job: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The questionnaire payload for one job - questions, answers, and the options."""
    found = repo.dossier_for_job(code)
    if found is None:
        return {"code": code, "status": "not_started", "dossierId": None, "slots": []}
    dossier, slots = found
    job = job or repo.job_for_experience(code) or {}
    evidence = build_evidence(repo, job, dossier_id=str(dossier["id"]))
    options = options_for_all(tuple(str(s["slot_key"]) for s in slots), evidence)
    return {
        "code": code,
        "dossierId": str(dossier["id"]),
        "status": str(dossier.get("status") or "empty"),
        "clusterKey": dossier.get("cluster_key") or "",
        "slots": [_slot_payload(row, options.get(str(row["slot_key"]), [])) for row in slots],
    }


@router.get("/content/experience/{code}")
def get_experience(code: str, _user: ViewReports, repo: ContentPlanningRepoDep) -> dict[str, Any]:
    """The Experience questions for one content job, what has been answered, and the
    options the client can pick from.

    A job with no engagement (it has not run yet) is NOT an error: it returns
    `status: "not_started"` with no slots, because the questions do not exist
    until the pipeline asks them.
    """
    return _experience_body(code, repo)


@router.get("/content/experience-library/{client_id}")
def experience_library(
    client_id: str, _user: ViewReports, repo: ContentPlanningRepoDep
) -> list[dict[str, Any]]:
    """Every cluster this client has an Experience dossier for, and how covered it is.

    WHY IT EXISTS. The dossier is per cluster and reused by every page in it, so the
    question an operator has before starting a batch is "what has this client already
    told us?". The only way to answer it was to open each held job in turn, which meant
    nobody did, which meant clients were asked the same questions twice.
    """
    rows = repo.dossiers_for_client(client_id)
    return [
        {
            "dossierId": str(row["id"]),
            "clusterKey": row.get("cluster_key") or "",
            "status": str(row.get("status") or "empty"),
            "slots": int(row.get("slots") or 0),
            "answered": int(row.get("answered") or 0),
            "lastAnsweredOn": fmt_day(row.get("last_answered_at")),
        }
        for row in rows
    ]


@router.put("/content/experience/{code}")
def put_experience(
    code: str,
    user: PublishContent,
    repo: ContentPlanningRepoDep,
    answers: Annotated[list[dict[str, Any]], Body(embed=True)],
    source: Annotated[str, Query()] = "operator",
) -> dict[str, Any]:
    """Record answers to the Experience questions and re-derive the status.

    Answers UPDATE existing slots only. The SME stage decides which proof
    categories a page type requires; accepting new keys from the wire would let a
    caller invent a slot and mark the dossier complete without answering what was
    actually asked - which is the one thing this gate exists to prevent.

    Each answer may carry ``answer_evidence`` - the provenance string from the option
    that was picked. It is stored as supplied rather than re-derived, because the
    evidence describes what the answerer was looking at when they attested, which the
    server cannot reconstruct afterwards. It is never treated as a claim in itself: the
    draft grounds on the ANSWER, and the evidence is there for the human who audits it.
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
    status_now = repo.answer_slots(
        str(dossier["id"]), answers, source=source, actor_id=user.id
    )
    body = _experience_body(code, repo)

    # A completed dossier RESUMES the page. Without this the questionnaire is a
    # dead end: the halt holds the job at `drafting`, and the worker's guard
    # refuses anything that is not `queued`, so the operator would answer every
    # question and watch nothing happen. Best-effort on purpose - a broker that is
    # down must not lose the answers, which are already committed, so the response
    # reports whether the page was actually re-queued rather than assuming it.
    body["resumed"] = False
    if status_now == "complete":
        body["resumed"] = resume_held_pages(code)
    return body


def resume_held_pages(code: str) -> bool:
    """Re-queue the page whose Experience answers just completed. Never raises.

    Shared with the portal route so a client answering in their own portal resumes the
    same work an operator answering in the dashboard would - the two paths differ in who
    may write, never in what a completed dossier does next.
    """
    try:
        from workers.tasks.content_pipeline import run_content_pipeline_job

        run_content_pipeline_job.delay(code, resume=True)
        return True
    except Exception as exc:  # broker down / not configured
        logger.warning("experience_resume_enqueue_failed", code=code, error=type(exc).__name__)
        return False
