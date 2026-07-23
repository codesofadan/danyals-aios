"""Wave 5 - the GMB (Google Business Profile) post module endpoints.

Operators prompt the AI to draft a GBP post that respects Google Business Profile
content policy + best-practices (concise, a proper CTA, length-capped, NO em dashes);
a lead reviews it; ACTUAL posting to Google is dormant (degrades honestly - the OAuth
publish path is not wired). Reads require any provisioned staff (``view_reports`` - a
portal client holds none, so clients are 403'd off the whole surface); generating,
reviewing, and the dormant publish are LEAD-only (owner/admin/manager), which mirrors
the ``gmb_posts`` RLS insert/update policies byte-for-byte.

Generation is SYNCHRONOUS + cost-gated on the ``gmb`` money-dial (the ai_assist
pattern): the backend calls Claude through the shared summarizer seam under the shared
gate; the client never holds a key. A keyless deploy or a dial/budget block DEGRADES
(the post is stored as a ``draft`` with an honest marker), never crashes. The generated
body is guaranteed em/en-dash-free (the content guard's hard strip) and policy-scored
before it is stored.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg.types.json import Jsonb

from app.core.auth import CurrentUser, require_perm, require_role
from app.core.deps import SettingsDep
from app.core.pagination import PageDep
from app.db.clients_repo import ClientsRepoDep
from app.modules.gmb.repo import GmbRepoDep
from app.modules.gmb.schemas import (
    STAGE_LABELS,
    GmbPostCreate,
    GmbPostResponse,
    GmbPublishResponse,
    GmbReviewRequest,
    GmbStatsResponse,
    compute_gmb_stats,
)
from app.modules.gmb.service import (
    build_gmb_gate,
    build_gmb_summarizer,
    run_gmb_generation,
)
from app.services.activity import record_activity
from app.services.cost_gate import CostGate
from integrations.llm import Summarizer

router = APIRouter(tags=["gmb"])

# All six staff roles hold view_reports; a portal client does NOT -> clients 403'd off
# the whole surface (mirrors content/reports/ai). Generation + review are LEAD-only.
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
LeadOnly = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

_POST_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GMB post not found")
_NOT_IN_REVIEW = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="GMB post is not awaiting review"
)


# --------------------------------------------------------------------------- #
# Injected seams (overridable in tests; the summarizer + gate mirror ai_assist).
# --------------------------------------------------------------------------- #
def get_gmb_summarizer(settings: SettingsDep) -> Summarizer | None:
    """Dependency: the key-gated GBP summarizer (or ``None`` degraded)."""
    return build_gmb_summarizer(settings)


def get_gmb_gate() -> CostGate:
    """Dependency: the real cost gate over the Postgres store."""
    return build_gmb_gate()


GmbSummarizerDep = Annotated[Summarizer | None, Depends(get_gmb_summarizer)]
GmbGateDep = Annotated[CostGate, Depends(get_gmb_gate)]


def _facts_from_client(client: dict[str, Any]) -> dict[str, str]:
    """Snapshot the client facts the generator may ground the post in."""
    facts: dict[str, str] = {}
    if client.get("industry"):
        facts["industry"] = str(client["industry"])
    if client.get("since_year"):
        facts["founded"] = str(client["since_year"])
    if client.get("contact_name"):
        facts["primary_contact"] = str(client["contact_name"])
    return facts


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
@router.get("/gmb/posts", response_model=list[GmbPostResponse])
async def list_gmb_posts(
    repo: GmbRepoDep,
    page: PageDep,
    _user: ViewReports,
    client: Annotated[str | None, Query()] = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
) -> list[GmbPostResponse]:
    """List GBP posts (created_at desc). Optional ``?client`` + ``?status`` filters."""
    rows = await asyncio.to_thread(
        repo.list_posts, client_id=client, status=status_, limit=page.limit, offset=page.offset
    )
    return [GmbPostResponse.from_row(r) for r in rows]


@router.get("/gmb/posts/stats", response_model=GmbStatsResponse)
async def gmb_stats(repo: GmbRepoDep, _user: ViewReports) -> GmbStatsResponse:
    """The GMB board KPIs (total, awaiting-review, approved, needs-fix)."""
    rows = await asyncio.to_thread(repo.list_posts)
    return compute_gmb_stats(rows)


@router.get("/gmb/posts/{code}", response_model=GmbPostResponse)
async def get_gmb_post(code: str, repo: GmbRepoDep, _user: ViewReports) -> GmbPostResponse:
    """One GBP post (with its policy report)."""
    row = await asyncio.to_thread(repo.get_post_by_code, code)
    if row is None:
        raise _POST_NOT_FOUND
    return GmbPostResponse.from_row(row)


# --------------------------------------------------------------------------- #
# Generate (LEAD-only; synchronous + cost-gated)
# --------------------------------------------------------------------------- #
@router.post("/gmb/posts", response_model=GmbPostResponse, status_code=status.HTTP_201_CREATED)
async def create_gmb_post(
    body: GmbPostCreate,
    repo: GmbRepoDep,
    clients: ClientsRepoDep,
    settings: SettingsDep,
    summarizer: GmbSummarizerDep,
    gate: GmbGateDep,
    actor: LeadOnly,
) -> GmbPostResponse:
    """Generate a GBP post and store it at the review gate (or as a degraded draft).

    Validates + snapshots the client, drafts via the cost-gated summarizer (the body
    is dash-stripped + capped + policy-scored inside the service), and inserts the row
    on the RLS path. A keyless/blocked generation degrades to a ``draft`` marker.
    """
    client = await asyncio.to_thread(clients.get_client, body.client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    def _generate() -> Any:
        return run_gmb_generation(
            body.topic,
            post_type=body.post_type,
            cta_type=body.cta_type,
            cta_url=body.cta_url,
            title=body.title,
            client_id=body.client_id,
            client_name=client.get("name", ""),
            facts=_facts_from_client(client),
            summarizer=summarizer,
            gate=gate,
            settings=settings,
        )

    result = await asyncio.to_thread(_generate)
    degraded = result.status == "degraded"
    post_status = "draft" if degraded else "needs_review"
    stage = (
        f"Generation degraded ({result.reason})" if degraded else STAGE_LABELS["needs_review"]
    )

    row = await asyncio.to_thread(
        repo.insert_post,
        {
            "client_id": body.client_id,
            "client_name": client.get("name", ""),
            "color": client.get("contact_color", "#7B69EE"),
            "topic": body.topic,
            "post_type": body.post_type,
            "cta_type": body.cta_type,
            "cta_url": body.cta_url,
            "title": body.title,
            "body": result.body,
            "char_count": result.policy.char_count,
            "status": post_status,
            "policy": Jsonb(result.policy.as_dict()),
            "cost": result.cost,
            "provider": "Anthropic",
            "stage": stage,
            "created_by": actor.id,
        },
    )
    await record_activity(
        actor, kind="client", action="generated a GMB post", target=client.get("name", ""),
        entity_type="client", entity_id=body.client_id,
    )
    return GmbPostResponse.from_row(row)


# --------------------------------------------------------------------------- #
# Review gate (LEAD-only) - approval re-checks the policy HARD gate.
# --------------------------------------------------------------------------- #
@router.post("/gmb/posts/{code}/review", response_model=GmbPostResponse)
async def review_gmb_post(
    code: str, body: GmbReviewRequest, repo: GmbRepoDep, actor: LeadOnly
) -> GmbPostResponse:
    """Approve or reject a GBP post at the review gate. ``approve`` re-checks the GBP
    policy HARD gate (a post with unresolved violations CANNOT be approved) and moves
    it to ``approved``; ``reject`` -> ``rejected``. 409 unless awaiting review."""
    post = await asyncio.to_thread(repo.get_post_by_code, code)
    if post is None:
        raise _POST_NOT_FOUND
    if post.get("status") != "needs_review":
        raise _NOT_IN_REVIEW

    if body.action == "approve":
        raw_policy = post.get("policy")
        policy: dict[str, Any] = raw_policy if isinstance(raw_policy, dict) else {}
        if not policy.get("ok", False):
            codes = [str(v.get("code")) for v in policy.get("violations", [])]
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"GBP policy violations block approval: {', '.join(codes) or 'unknown'}",
            )
        new_status, stage = "approved", STAGE_LABELS["approved"]
    else:
        new_status, stage = "rejected", STAGE_LABELS["rejected"]

    updated = await asyncio.to_thread(
        repo.update_post_by_code, code, {"status": new_status, "stage": stage}, "needs_review"
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="GMB post changed concurrently")
    action = "approved a GMB post" if body.action == "approve" else "rejected a GMB post"
    client_id = post.get("client_id")
    await record_activity(
        actor, kind="client", action=action, target=post.get("client_name", ""),
        entity_type="client" if client_id is not None else None,
        entity_id=str(client_id) if client_id is not None else None,
    )
    return GmbPostResponse.from_row(updated)


# --------------------------------------------------------------------------- #
# Publish to Google (LEAD-only) - DORMANT: degrades honestly (OAuth path unwired).
# --------------------------------------------------------------------------- #
@router.post("/gmb/posts/{code}/publish", response_model=GmbPublishResponse)
async def publish_gmb_post(code: str, repo: GmbRepoDep, actor: LeadOnly) -> GmbPublishResponse:
    """Attempt to post an APPROVED GBP post to Google. Posting is NOT connected yet, so
    this DEGRADES honestly: it never fakes a live post - it reports that the Google
    Business Profile publish path is dormant and leaves the post approved + queued."""
    post = await asyncio.to_thread(repo.get_post_by_code, code)
    if post is None:
        raise _POST_NOT_FOUND
    if post.get("status") != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="GMB post must be approved before publishing"
        )
    await asyncio.to_thread(
        repo.update_post_by_code, code,
        {"stage": "Approved (Google posting not connected - dormant)"}, "approved",
    )
    return GmbPublishResponse(
        code=code,
        posted=False,
        url="",
        message=(
            "Google Business Profile posting is not connected yet. The approved post is "
            "queued; connect a GBP account to publish it live."
        ),
    )
