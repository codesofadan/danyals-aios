"""The portal half of the Experience questionnaire: a client answering their own questions.

WHY THIS IS A SERVICE AND NOT A POLICY. A client reads their questions through the
`portal_sme_*` views (0156), which self-filter on ``current_client_id()``. Writing is
different in kind: giving the ``client`` role UPDATE on ``sme_slots`` would grant write
access to a table the content pipeline reads on every run, to close one capability. So the
write runs on the privileged path with the tenant PINNED SERVER-SIDE from the
authenticated session - the same trust shape ``client_audits.create_client_audit`` uses for
a portal-initiated audit, and for the same reason.

THE THREE RULES THAT MAKE IT SAFE, each enforced here rather than trusted from the caller:

  1. **The job must belong to the caller's client.** ``client_id`` comes from the verified
     session, never from the body, and a job that does not resolve under it is a 404 -
     indistinguishable from a job that does not exist, so the portal cannot be used to
     probe for other tenants' job codes.
  2. **Only the slots the pipeline asked for may be answered.** The SME stage owns which
     proof categories a page type requires; accepting an unknown key would let a caller
     invent a slot and mark the dossier complete without answering what was asked.
  3. **The attestation is recorded as the CLIENT's.** ``source = 'client'`` and
     ``answered_by`` is the portal user, because the whole value of a client-answered fact
     is that the client is the one who stands behind it.

A completed dossier resumes the held pages, exactly as it does when staff answer. The two
paths differ in who may write and in nothing else.
"""

from __future__ import annotations

from typing import Any

from app.db.database import privileged_connection
from app.logging_setup import get_logger
from app.modules.content_planning.repo import cluster_key_for

logger = get_logger("services.client_experience")

#: The client-safe slot columns. `answered_by` is a user id and stays server-side.
_SLOT_FIELDS = (
    "slot_key",
    "question",
    "answer",
    "artifact_url",
    "answer_evidence",
    "answered_at",
    "source",
)


def job_for_client(code: str, client_id: str) -> dict[str, Any] | None:
    """One content job, ONLY if it belongs to this client. Privileged read, pinned tenant.

    Returns the columns the questionnaire needs, including ``source_pack`` - which is the
    client's own supplied grounding and therefore legitimate evidence to offer them back,
    but is never returned to the browser as-is (it also carries the publish target).
    """
    with privileged_connection() as cur:
        cur.execute(
            "select id, code, client_id, engagement_id, topic, page_type, status, stage, "
            "  source_pack "
            "from public.content_jobs where code = %s and client_id = %s::uuid limit 1",
            (code, client_id),
        )
        return cur.fetchone()


def dossier_for_client_job(job: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """The dossier for a client's job, with its slots. None when the job has not run.

    Matches the job's own cluster the way ``ContentPlanningRepo.dossier_for_job`` does -
    one derivation (``cluster_key_for``) shared by both doors, so the client and the
    operator can never be shown different questions for the same page.
    """
    if not job.get("engagement_id"):
        return None
    with privileged_connection() as cur:
        cur.execute(
            "select id, cluster_key, status from public.sme_dossiers "
            "where engagement_id = %s and cluster_key = %s limit 1",
            (job["engagement_id"], cluster_key_for(job)),
        )
        dossier = cur.fetchone()
        if dossier is None:
            cur.execute(
                "select id, cluster_key, status from public.sme_dossiers "
                "where engagement_id = %s order by created_at limit 1",
                (job["engagement_id"],),
            )
            dossier = cur.fetchone()
        if dossier is None:
            return None
        cur.execute(
            "select " + ", ".join(_SLOT_FIELDS) + " from public.sme_slots "
            "where dossier_id = %s order by slot_key",
            (dossier["id"],),
        )
        return dossier, list(cur.fetchall())


def prior_answers_for_client(client_id: str, *, exclude_dossier_id: str | None) -> list[dict[str, Any]]:
    """The client's own prior attestations, for the option list. Privileged, tenant-pinned."""
    with privileged_connection() as cur:
        cur.execute(
            """select s.slot_key, s.answer, s.answered_at, d.cluster_key
               from public.sme_slots s
               join public.sme_dossiers d on d.id = s.dossier_id
               join public.content_engagements e on e.id = d.engagement_id
               where e.client_id = %s::uuid and s.answer <> ''
                 and (%s::uuid is null or s.dossier_id <> %s::uuid)
               order by s.answered_at desc nulls last, s.updated_at desc
               limit 200""",
            (client_id, exclude_dossier_id, exclude_dossier_id),
        )
        return list(cur.fetchall())


def client_facts(client_id: str) -> dict[str, Any] | None:
    """The client's own business record, as evidence. Privileged, tenant-pinned.

    Every column named here exists. The first version asked for ``p.tagline`` and
    ``p.year_founded``, which ``client_business_profiles`` does not have - on the staff
    route the caller catches that and carries on, so it read as "this client has no
    record"; on this route there is no catch and it 500'd the questionnaire on the first
    live request. The trading year lives on ``clients.since_year``.
    """
    with privileged_connection() as cur:
        cur.execute(
            """select c.name, c.industry, c.since_year, c.contact_name, c.contact_role,
                      p.city, p.region, p.market, p.description, p.website_url,
                      p.business_name, p.primary_category
               from public.clients c
               left join public.client_business_profiles p on p.client_id = c.id
               where c.id = %s::uuid limit 1""",
            (client_id,),
        )
        return cur.fetchone()


def answer_slots_as_client(
    dossier_id: str,
    answers: list[dict[str, Any]],
    *,
    actor_id: str,
) -> str:
    """Record the client's answers and recompute the dossier status, atomically.

    UPDATE-only and keyed on ``(dossier_id, slot_key)``, so an unknown key updates
    nothing rather than creating a slot. Status is recomputed in the SAME transaction
    because it is what the pipeline's halt reads; a status written a moment later is a
    window in which a complete dossier still blocks drafting.
    """
    with privileged_connection() as cur:
        for answer in answers:
            text = str(answer.get("answer") or "")
            artifact = str(answer.get("artifact_url") or "")
            present = bool(text.strip() or artifact.strip())
            cur.execute(
                "update public.sme_slots set answer = %s, artifact_url = %s, "
                "  source = 'client', answer_evidence = %s, "
                "  answered_by = case when %s then %s::uuid else null end, "
                "  answered_at = case when %s then now() else null end "
                "where dossier_id = %s::uuid and slot_key = %s",
                (
                    text,
                    artifact,
                    str(answer.get("answer_evidence") or "") if present else "",
                    present,
                    actor_id,
                    present,
                    dossier_id,
                    str(answer.get("slot_key") or ""),
                ),
            )
        cur.execute(
            "select count(*) as total, "
            "  count(*) filter (where answer <> '' or artifact_url <> '') as answered "
            "from public.sme_slots where dossier_id = %s::uuid",
            (dossier_id,),
        )
        row = cur.fetchone() or {"total": 0, "answered": 0}
        total, answered = int(row["total"]), int(row["answered"])
        status = (
            "complete" if total and answered == total
            else ("partial" if answered else "empty")
        )
        cur.execute(
            "update public.sme_dossiers set status = %s where id = %s::uuid",
            (status, dossier_id),
        )
    logger.info(
        "client_experience_answered", dossier=dossier_id, status=status, answers=len(answers)
    )
    return status


def open_questions_for_client(client_id: str) -> list[dict[str, Any]]:
    """Every page of this client's that is waiting on them, newest first.

    The portal's own to-do list. Without it a client would have to be told which page
    codes to open, which means being told by a person, which is the message this whole
    surface exists to stop.
    """
    with privileged_connection() as cur:
        cur.execute(
            """select j.code, j.topic, j.page_type, j.status, j.stage, d.cluster_key,
                      count(s.id) as slots,
                      count(s.id) filter (
                        where s.answer <> '' or s.artifact_url <> ''
                      ) as answered
               from public.content_jobs j
               join public.sme_dossiers d on d.engagement_id = j.engagement_id
               join public.sme_slots s on s.dossier_id = d.id
               where j.client_id = %s::uuid and d.status <> 'complete'
               -- j.created_at is GROUPED, not just ordered by: Postgres rejects an
               -- ORDER BY on a column that is neither aggregated nor grouped, and this
               -- 500'd on the first live request. Grouping it is right rather than
               -- merely legal - the grain here is one row per (page, dossier), and
               -- created_at is functionally dependent on the page.
               group by j.code, j.topic, j.page_type, j.status, j.stage, d.cluster_key,
                        j.created_at
               order by j.created_at desc
               limit 100""",
            (client_id,),
        )
        return list(cur.fetchall())
