"""Milestones module response models in the frontend shapes (``lib/milestones.ts``).

``ClientProjectResponse`` mirrors ``ClientProject`` EXACTLY - the 7 keys ``{id,
client, site, init, c, health, stages}`` and nothing else. ``id`` is the project
uuid (a string); ``client``/``init``/``c`` are display SNAPSHOTS so the internal
``client_id`` never leaks; ``stages`` is always the 5 lifecycle stages in order.
``StageResponse`` mirrors ``Stage`` (``{key, status, auto_source, updated_at}``);
``AutoAdvanceResponse`` mirrors the recently-auto-advanced feed entry ``AutoAdvance``.

§3 ENUM FIDELITY: ``Health`` (``on_track|at_risk|completed``) is SEPARATE from
``StageStatus`` (``completed|in_progress|upcoming|blocked``) - they share the label
``completed`` but are DISTINCT unions and are never merged.

``project_progress`` / ``current_stage`` mirror ``milestones.ts`` (``projectProgress``
/ ``currentStage``) as pure helpers - honest % completion from the stage weights and
the stage a project is currently sitting on.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.util.timefmt import relative_ago

# Unions verbatim from milestones.ts (StageKey / StageStatus / Health).
StageKey = Literal["onboarding", "baseline", "content", "authority", "reporting"]
StageStatus = Literal["completed", "in_progress", "upcoming", "blocked"]
Health = Literal["on_track", "at_risk", "completed"]

_STAGE_KEYS: frozenset[str] = frozenset(
    {"onboarding", "baseline", "content", "authority", "reporting"}
)
_STAGE_STATUSES: frozenset[str] = frozenset(
    {"completed", "in_progress", "upcoming", "blocked"}
)
_HEALTHS: frozenset[str] = frozenset({"on_track", "at_risk", "completed"})

# The fixed lifecycle order + display labels/icons (mirror milestones.ts LIFECYCLE).
STAGE_ORDER: tuple[StageKey, ...] = (
    "onboarding", "baseline", "content", "authority", "reporting"
)
STAGE_LABEL: dict[str, str] = {
    "onboarding": "Onboarding",
    "baseline": "Baseline Audit",
    "content": "Content Sprint",
    "authority": "Off-page / Authority",
    "reporting": "Reporting & Review",
}
STAGE_ICON: dict[str, str] = {
    "onboarding": "person_add",
    "baseline": "fact_check",
    "content": "article",
    "authority": "hub",
    "reporting": "summarize",
}
# Weight each stage carries toward the % progress bar (milestones.ts STAGE_WEIGHT).
STAGE_WEIGHT: dict[str, float] = {
    "completed": 1.0, "in_progress": 0.5, "blocked": 0.25, "upcoming": 0.0,
}


class StageResponse(BaseModel):
    """One lifecycle stage in the frontend ``Stage`` shape (``key`` / ``status`` /
    ``auto_source`` / ``updated_at``). ``updated_at`` is the RELATIVE time of the
    last auto-advance ("6d ago"); an un-advanced (``upcoming``) stage shows the
    em-dash, matching the mock."""

    key: StageKey
    status: StageStatus
    auto_source: str
    updated_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> StageResponse:
        key = row.get("stage_key")
        status = row.get("status")
        status_v: StageStatus = status if status in _STAGE_STATUSES else "upcoming"
        updated = "—" if status_v == "upcoming" else relative_ago(row.get("updated_at"), empty="—")
        return cls(
            key=key if key in _STAGE_KEYS else "onboarding",
            status=status_v,
            auto_source=row.get("auto_source", ""),
            updated_at=updated,
        )


class ClientProjectResponse(BaseModel):
    """One client project in the frontend ``ClientProject`` shape - and ONLY those
    7 keys. ``id`` is the project uuid; ``client``/``init``/``c`` are the snapshotted
    display fields; ``stages`` is always the 5 lifecycle stages in order. The
    internal ``client_id`` is never exposed."""

    id: str
    client: str
    site: str
    init: str
    c: str
    health: Health
    stages: list[StageResponse]

    @classmethod
    def from_rows(
        cls, project: dict[str, Any], stage_rows: list[dict[str, Any]]
    ) -> ClientProjectResponse:
        health = project.get("health")
        stages = sorted(
            (StageResponse.from_row(r) for r in stage_rows),
            key=lambda s: STAGE_ORDER.index(s.key),
        )
        return cls(
            id=str(project["id"]),
            client=project.get("client_name", ""),
            site=project.get("site", ""),
            init=project.get("init", ""),
            c=project.get("accent", ""),
            health=health if health in _HEALTHS else "on_track",
            stages=stages,
        )


class AutoAdvanceResponse(BaseModel):
    """One recently auto-advanced milestone in the frontend ``AutoAdvance`` shape.
    Derived from a recently-updated ``project_stages`` row joined to its project's
    display snapshot; ``flag`` marks a block/at-risk flag rather than a forward
    advance. No internal id/client_id leaks (``id`` is the stage row uuid)."""

    id: str
    client: str
    init: str
    c: str
    milestone: str
    trigger: str
    icon: str
    ago: str
    flag: bool

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> AutoAdvanceResponse:
        stage_key = str(row.get("stage_key") or "")
        blocked = str(row.get("status") or "") == "blocked"
        return cls(
            id=str(row["id"]),
            client=row.get("client_name", ""),
            init=row.get("init", ""),
            c=row.get("accent", ""),
            milestone=STAGE_LABEL.get(stage_key, stage_key),
            trigger=row.get("auto_source", ""),
            icon="block" if blocked else STAGE_ICON.get(stage_key, "flag"),
            ago=relative_ago(row.get("updated_at"), empty="just now"),
            flag=blocked,
        )


def project_progress(project: ClientProjectResponse) -> int:
    """Derived % completion from the stage weights, mirroring ``milestones.ts``
    ``projectProgress`` (sum of the per-status weights / stage count, rounded)."""
    if not project.stages:
        return 0
    total = sum(STAGE_WEIGHT.get(s.status, 0.0) for s in project.stages)
    return round((total / len(project.stages)) * 100)


def current_stage(project: ClientProjectResponse) -> StageResponse | None:
    """The stage a project is currently sitting on, mirroring ``milestones.ts``
    ``currentStage``: the first ``in_progress``/``blocked`` stage, else the first
    ``upcoming``, else the last. ``None`` only for a project with no stages."""
    if not project.stages:
        return None
    for s in project.stages:
        if s.status in ("in_progress", "blocked"):
            return s
    for s in project.stages:
        if s.status == "upcoming":
            return s
    return project.stages[-1]
