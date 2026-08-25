"""Discussion threads: the API shapes for threaded comments on work.

Two audiences read the same conversation and must NOT see the same thing, so there
are two response models rather than one with a nullable field:

* :class:`ThreadMessageResponse` - the STAFF shape. Carries ``visibility``, because a
  team member needs to see at a glance whether a note is internal or something the
  client can read.
* :class:`PortalMessageResponse` - the CLIENT shape. Has no ``visibility`` field at
  all, and no ``authorId``. It is fed exclusively from ``portal_thread_messages``,
  which never selects an internal row - so the field would be constant and the
  omission is a second, independent statement of the same boundary.

Times are ISO-8601 UTC strings; ``ago`` is the humanized form the UI renders, derived
here rather than stored (same convention as ``TicketResponse``). Wire names are
camelCase via ``serialization_alias``, matching every other response model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

EntityType = Literal["task", "ticket"]
Visibility = Literal["internal", "client_visible"]
AuthorKind = Literal["staff", "client"]

_MAX_BODY = 8000


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value or "")


def humanize_since(value: Any) -> str:
    """"2h ago" / "just now". Mirrors the ``ago`` convention used by tickets."""
    if not isinstance(value, datetime):
        return ""
    delta = datetime.now(UTC) - value.astimezone(UTC)
    secs = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


class MessageCreate(BaseModel):
    """Post one message. ``visibility`` is staff-only input.

    The CLIENT route ignores it entirely and pins ``client_visible`` server-side - a
    client cannot file an internal note, and the database refuses one anyway
    (``thread_messages_client_is_visible_ck``).
    """

    body: str = Field(min_length=1, max_length=_MAX_BODY)
    visibility: Visibility = "internal"

    @field_validator("body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        text = v.strip()
        if not text:
            raise ValueError("message body cannot be blank")
        return text


class ThreadMessageResponse(BaseModel):
    """One message, staff view - internal notes included."""

    id: str
    author: str
    author_kind: AuthorKind = Field(serialization_alias="authorKind")
    body: str
    visibility: Visibility
    created_at: str = Field(serialization_alias="createdAt")
    ago: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ThreadMessageResponse:
        return cls(
            id=str(row.get("id", "")),
            author=str(row.get("author_name") or "Unknown"),
            author_kind=cast_author_kind(row.get("author_kind")),
            body=str(row.get("body") or ""),
            visibility=cast_visibility(row.get("visibility")),
            created_at=_iso(row.get("created_at")),
            ago=humanize_since(row.get("created_at")),
        )


class PortalMessageResponse(BaseModel):
    """One message, CLIENT view.

    No ``visibility`` and no author id, by construction. See the module docstring.
    """

    id: str
    author: str
    author_kind: AuthorKind = Field(serialization_alias="authorKind")
    body: str
    created_at: str = Field(serialization_alias="createdAt")
    ago: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> PortalMessageResponse:
        return cls(
            id=str(row.get("id", "")),
            author=str(row.get("author_name") or "Unknown"),
            author_kind=cast_author_kind(row.get("author_kind")),
            body=str(row.get("body") or ""),
            created_at=_iso(row.get("created_at")),
            ago=humanize_since(row.get("created_at")),
        )


def cast_visibility(value: Any) -> Visibility:
    return "client_visible" if str(value) == "client_visible" else "internal"


def cast_author_kind(value: Any) -> AuthorKind:
    return "client" if str(value) == "client" else "staff"
