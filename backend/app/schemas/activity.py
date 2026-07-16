"""Activity feed response model (frontend ``Activity`` shape)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.util.timefmt import relative_ago

ActivityKind = Literal["task", "member", "audit", "content", "access", "login", "client"]


class ActivityResponse(BaseModel):
    """One feed entry in the frontend ``Activity`` shape."""

    id: str
    kind: str
    actor_init: str = Field(serialization_alias="actorInit")
    actor_name: str = Field(serialization_alias="actorName")
    actor_color: str = Field(serialization_alias="actorColor")
    action: str
    target: str
    meta: str | None = None
    ago: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ActivityResponse:
        return cls(
            id=str(row["id"]),
            kind=row.get("kind", "task"),
            actor_init=row.get("actor_init", ""),
            actor_name=row.get("actor_name", ""),
            actor_color=row.get("actor_color", "#7B69EE"),
            action=row.get("action", ""),
            target=row.get("target", ""),
            meta=row.get("meta"),
            ago=relative_ago(row.get("created_at"), empty="just now"),
        )
