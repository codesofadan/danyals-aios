"""Identity request/response models mirroring the frontend team shapes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, SecretStr

from app.rbac import AppRole


def to_team_role(role: str) -> str:
    """Map the lowercase DB ``app_role`` to the frontend's capitalized ``TeamRole``."""
    return role.capitalize()


def _initials(name: str) -> str:
    parts = name.split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _joined(created_at: Any) -> str:
    """Format a created_at timestamp as the frontend's "Mon YYYY" join label."""
    if not created_at:
        return ""
    if isinstance(created_at, datetime):
        return created_at.strftime("%b %Y")
    try:
        return datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).strftime("%b %Y")
    except ValueError:
        return ""


class ProvisionUserRequest(BaseModel):
    """Payload for the super-admin provisioning endpoint (no public signup)."""

    email: EmailStr
    name: str = Field(min_length=1)
    password: SecretStr = Field(min_length=8)
    role: AppRole = "viewer"
    title: str = ""
    avatar_color: str = "#7B69EE"
    template: str | None = None  # optional role template key to seed feature grants


class MemberResponse(BaseModel):
    """A team member in the frontend ``TeamMemberRecord`` shape.

    Performance metrics (activeTasks/completed/onTime/utilization/quality) are
    derived from job data (Google Sheets) in a later part; the identity service
    returns zeros so the shape is complete today.
    """

    id: str
    name: str
    init: str
    c: str  # avatar accent
    title: str
    email: str
    role: str  # capitalized TeamRole
    status: str
    # serialization_alias => output uses the frontend's camelCase keys, while the
    # snake_case field names keep their defaults (no alias required on input).
    active_tasks: int = Field(default=0, serialization_alias="activeTasks")
    completed: int = 0
    on_time: int = Field(default=0, serialization_alias="onTime")
    utilization: int = 0
    quality: int = 0
    joined: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> MemberResponse:
        name = row.get("name", "")
        return cls(
            id=str(row["id"]),
            name=name,
            init=_initials(name),
            c=row.get("avatar_color", "#7B69EE"),
            title=row.get("title", ""),
            email=row.get("email", ""),
            role=to_team_role(row.get("role", "viewer")),
            status=row.get("status", "invited"),
            joined=_joined(row.get("created_at")),
        )
