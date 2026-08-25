"""Engagement planning endpoints - the scope layer above content jobs (P4).

READ-ONLY, DELIBERATELY. Every write path into these tables runs in the pipeline, where
the SME halt, the uniqueness gate and the engagement budget all live. An endpoint that
enqueued production would sit in front of those checks rather than behind them, and the
first thing anyone would do is call it directly.

So this exposes what an operator needs to DECIDE - what the engagement is, whether it
can start, what it will produce and in what order - and leaves starting it to the
existing content job path, which is already gated.

ACCESS mirrors the modules around it: reads need `view_reports`, and the work plan
needs `run_audits` because it reports budget and spend. Everything runs through
`ContentPlanningRepo`, which is RLS-scoped - NOT the pipeline's privileged store.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_perm
from app.modules.content_planning.repo import ContentPlanningRepoDep
from app.modules.content_planning.schemas import Engagement, MapNode
from app.modules.content_planning.service import build_work_plan, plan_for

router = APIRouter(tags=["content-planning"])

ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
RunAudits = Annotated[CurrentUser, Depends(require_perm("run_audits"))]


def _engagement_from_row(row: dict[str, Any]) -> Engagement:
    return Engagement(
        id=str(row["id"]), shape=row["shape"], status=row["status"],
        client_id=str(row["client_id"]) if row.get("client_id") else None,
        client_name=row.get("client_name") or "", name=row.get("name") or "",
        scope=row.get("scope") or {},
        budget_cap=float(row["budget_cap"]) if row.get("budget_cap") is not None else None,
        page_target=row.get("page_target") or 0,
        source_audit_id=str(row["source_audit_id"]) if row.get("source_audit_id") else None,
        owner_id=str(row["owner_id"]) if row.get("owner_id") else None,
        created_at=row.get("created_at"),
    )


def _node_from_row(row: dict[str, Any]) -> MapNode:
    return MapNode(
        id=str(row["id"]), map_id=str(row["map_id"]),
        primary_keyword=row.get("primary_keyword") or "",
        status=row.get("status") or "planned",
        parent_id=str(row["parent_id"]) if row.get("parent_id") else None,
        silo=row.get("silo") or "", page_type=row.get("page_type") or "service",
        secondary_keywords=tuple(row.get("secondary_keywords") or ()),
        intent=row.get("intent") or "", target_city=row.get("target_city") or "",
        priority=row.get("priority") or 0, target_words=row.get("target_words") or 0,
        cluster_key=row.get("cluster_key") or "", evidence=row.get("evidence") or "",
        info_gain_thesis=row.get("info_gain_thesis") or "",
        content_job_id=str(row["content_job_id"]) if row.get("content_job_id") else None,
        published_url=row.get("published_url") or "",
    )


@router.get("/content/engagements")
def list_engagements(
    _user: ViewReports,
    repo: ContentPlanningRepoDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[dict[str, Any]]:
    """Engagements this caller can see, newest first."""
    rows = repo.list_engagements(status=status_filter, limit=limit)
    return [
        {
            "id": str(r["id"]), "shape": r["shape"], "status": r["status"],
            "name": r.get("name") or "", "client_name": r.get("client_name") or "",
            "page_target": r.get("page_target") or 0,
            "budget_cap": float(r["budget_cap"]) if r.get("budget_cap") is not None else None,
            "created_at": r.get("created_at"),
        }
        for r in rows
    ]


@router.get("/content/engagements/{engagement_id}")
def get_engagement(
    engagement_id: str, _user: ViewReports, repo: ContentPlanningRepoDep
) -> dict[str, Any]:
    """One engagement, with the shape's own description of what it runs."""
    row = repo.get_engagement(engagement_id)
    if row is None:
        # 404 rather than 403 on an engagement RLS hid: distinguishing them would
        # confirm the row exists to a caller who is not allowed to know that.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "engagement not found")
    engagement = _engagement_from_row(row)
    shape = plan_for(engagement.shape)
    return {
        "id": engagement.id, "shape": engagement.shape, "status": engagement.status,
        "name": engagement.name, "client_name": engagement.client_name,
        "scope": engagement.scope, "budget_cap": engagement.budget_cap,
        "page_target": engagement.page_target,
        "blocks_drafting": engagement.blocks_drafting,
        "runs": {
            "engagement_stages": list(shape.engagement_stages),
            "page_stages": list(shape.page_stages),
            "requires": list(shape.requires),
            "recurring": shape.recurring,
            "description": shape.description,
        },
    }


@router.get("/content/engagements/{engagement_id}/plan")
def get_work_plan(
    engagement_id: str, _user: RunAudits, repo: ContentPlanningRepoDep
) -> dict[str, Any]:
    """The ordered plan of work: what will be produced, in what order, and why not."""
    row = repo.get_engagement(engagement_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "engagement not found")

    engagement = _engagement_from_row(row)
    nodes = [_node_from_row(n) for n in repo.map_nodes(engagement_id)]
    plan = build_work_plan(
        engagement, nodes,
        has_brand_kit=repo.has_brand_kit(engagement.client_id),
    )
    return {
        "engagement_id": plan.engagement_id,
        "shape": plan.shape,
        "can_start": plan.can_start,
        "page_count": plan.page_count,
        "engagement_stages": list(plan.engagement_stages),
        "page_stages": list(plan.page_stages),
        "recurring": plan.recurring,
        "readiness": {
            "ready": plan.readiness.ready,
            "missing": list(plan.readiness.missing),
            "reasons": list(plan.readiness.reasons),
        },
        "notes": list(plan.notes),
        "pages": [
            {
                "id": n.id, "primary_keyword": n.primary_keyword,
                "page_type": n.page_type, "silo": n.silo, "intent": n.intent,
                "target_city": n.target_city, "priority": n.priority,
                "target_words": n.target_words, "cluster_key": n.cluster_key,
                "status": n.status, "published_url": n.published_url,
            }
            for n in plan.nodes
        ],
    }


@router.get("/content/engagements/{engagement_id}/keywords")
def get_keywords(
    engagement_id: str,
    _user: ViewReports,
    repo: ContentPlanningRepoDep,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> dict[str, Any]:
    """The engagement's keyword plan, with every row's provenance attached.

    `estimated` is surfaced per row rather than aggregated away. A UI that shows volume
    without saying whether it was bought or derived reproduces v1's central lie in a
    nicer font.
    """
    if repo.get_engagement(engagement_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "engagement not found")

    rows = repo.keyword_terms(engagement_id, limit=limit)
    terms = [
        {
            "keyword": r.get("keyword") or "",
            "volume": r.get("volume"), "difficulty": r.get("difficulty"),
            "cpc": r.get("cpc"), "competition": r.get("competition"),
            "intent": r.get("intent") or "", "relevance": r.get("relevance"),
            "opportunity": r.get("opportunity"),
            "cluster_key": r.get("cluster_key") or "",
            "estimated": bool(r.get("estimated")),
        }
        for r in rows
    ]
    estimated = sum(1 for t in terms if t["estimated"])
    return {
        "engagement_id": engagement_id,
        "total": len(terms),
        "measured": len(terms) - estimated,
        "estimated": estimated,
        "terms": terms,
    }
