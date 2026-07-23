"""Wave 5: GMB (Google Business Profile) post request/response models.

Server-authoritative (no ``frontend/lib/*.ts`` mirror to lock against); the module's
own unit tests freeze the wire key set. Python attributes stay ``snake_case`` (ruff
N815); multi-word wire keys re-alias to camelCase via ``serialization_alias``.
``client_id`` is NEVER on the wire - ``client`` is the snapshotted display name.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.util.timefmt import relative_ago

PostType = Literal["update", "offer", "event", "product"]
CtaType = Literal["book", "order", "shop", "learn_more", "sign_up", "call", "none"]
PostStatus = Literal["draft", "needs_review", "approved", "posted", "rejected"]
ReviewAction = Literal["approve", "reject"]

# Human-readable stage labels per status (shown on the board / card).
STAGE_LABELS: dict[str, str] = {
    "draft": "Draft (generation pending)",
    "needs_review": "Awaiting review",
    "approved": "Approved (Google posting dormant)",
    "posted": "Posted to Google",
    "rejected": "Rejected",
}


class GmbPostCreate(BaseModel):
    """POST /gmb/posts body: generate a new GBP post for a client.

    ``client_id`` is validated + snapshotted (name/color) by the endpoint. ``ctaType``
    defaults to a learn-more button; ``ctaUrl`` is required by the policy gate for any
    button except a phone call.
    """

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    post_type: PostType = Field(default="update", alias="postType")
    cta_type: CtaType = Field(default="learn_more", alias="ctaType")
    cta_url: str = Field(default="", alias="ctaUrl")
    title: str = ""


class GmbReviewRequest(BaseModel):
    """POST /gmb/posts/{code}/review body: the lead's decision at the review gate."""

    action: ReviewAction


class GmbPostResponse(BaseModel):
    """One GBP post on the wire. ``id`` is the public ``GMB-####`` code; ``policy`` is
    the passthrough GBP policy report ({ok, charCount, violations, warnings})."""

    id: str
    client: str
    color: str
    topic: str
    post_type: PostType = Field(serialization_alias="postType")
    status: PostStatus
    title: str
    body: str
    cta_type: CtaType = Field(serialization_alias="ctaType")
    cta_url: str = Field(serialization_alias="ctaUrl")
    char_count: int = Field(serialization_alias="charCount")
    policy_ok: bool = Field(serialization_alias="policyOk")
    policy: dict[str, Any]
    cost: float
    stage: str
    ago: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> GmbPostResponse:
        raw_policy = row.get("policy")
        policy: dict[str, Any] = raw_policy if isinstance(raw_policy, dict) else {}
        post_type = row.get("post_type")
        cta_type = row.get("cta_type")
        status = row.get("status")
        return cls(
            id=str(row["code"]),
            client=row.get("client_name", ""),
            color=row.get("color", ""),
            topic=row.get("topic", ""),
            post_type=post_type if post_type in {"update", "offer", "event", "product"} else "update",
            status=status if status in {"draft", "needs_review", "approved", "posted", "rejected"} else "draft",
            title=row.get("title", ""),
            body=row.get("body", ""),
            cta_type=cta_type
            if cta_type in {"book", "order", "shop", "learn_more", "sign_up", "call", "none"}
            else "none",
            cta_url=row.get("cta_url", ""),
            char_count=int(row.get("char_count", 0) or 0),
            policy_ok=bool(policy.get("ok", False)),
            policy=policy,
            cost=float(row.get("cost", 0) or 0),
            stage=str(row.get("stage") or STAGE_LABELS.get(str(status), "")),
            ago=relative_ago(row.get("created_at"), empty="just now"),
        )


class GmbPublishResponse(BaseModel):
    """The result of a (dormant) publish-to-Google attempt. ``posted`` is always False
    until the GBP OAuth publish path is wired; ``message`` explains the dormant state."""

    code: str
    posted: bool
    url: str
    message: str


class GmbStatsResponse(BaseModel):
    """The GMB board KPIs."""

    total: int
    awaiting_review: int = Field(serialization_alias="awaitingReview")
    approved: int
    needs_fix: int = Field(serialization_alias="needsFix")


def compute_gmb_stats(rows: list[dict[str, Any]]) -> GmbStatsResponse:
    """Derive the GMB KPIs from the post rows (pure, unit-testable).

    ``awaitingReview`` = posts at the review gate; ``approved`` = approved/posted;
    ``needsFix`` = posts whose stored policy report failed (violations present).
    """
    total = len(rows)
    awaiting = 0
    approved = 0
    needs_fix = 0
    for r in rows:
        status = str(r.get("status") or "")
        if status == "needs_review":
            awaiting += 1
        if status in {"approved", "posted"}:
            approved += 1
        policy = r.get("policy") if isinstance(r.get("policy"), dict) else {}
        if policy and not policy.get("ok", True):
            needs_fix += 1
    return GmbStatsResponse(total=total, awaiting_review=awaiting, approved=approved, needs_fix=needs_fix)
