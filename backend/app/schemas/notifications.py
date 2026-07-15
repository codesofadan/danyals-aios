"""Notifications + alerts request/response models (7F-1).

These surfaces are INTERNAL: the frontend ``lib/*.ts`` exports no ``Notification`` /
``Alert`` type (the delivery layer drives the in-app bell + the staff alert queue,
not a contract-locked dashboard grid), so there is NO ``tests/test_contract_lock.py``
entry for them - unlike every module whose response mirrors an exported TS type.

Python attributes are snake_case with a ``serialization_alias`` (ruff N815 forbids a
raw camelCase attribute), so the emitted JSON is camelCase for the client. ``from_row``
adapts a psycopg ``dict_row`` (uuid / datetime values) into the model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AlertType = Literal["rank_drop", "lost_link", "budget"]


class NotificationResponse(BaseModel):
    """One in-app notification (the caller's own inbox row)."""

    id: str
    kind: str
    title: str
    body: str
    read: bool
    created_at: datetime = Field(serialization_alias="createdAt")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> NotificationResponse:
        return cls(
            id=str(row["id"]),
            kind=str(row.get("kind", "")),
            title=str(row.get("title", "")),
            body=str(row.get("body", "")),
            read=bool(row.get("read", False)),
            created_at=row["created_at"],
        )


class AlertResponse(BaseModel):
    """One staff alert (rank-drop / lost-link / budget). Staff-only, so the internal
    ``client_id`` is surfaced here (a trusted staff audience), unlike the client-facing
    contract responses where it never leaks."""

    id: str
    client_id: str = Field(serialization_alias="clientId")
    type: AlertType
    severity: str
    detail: str
    acknowledged: bool
    created_at: datetime = Field(serialization_alias="createdAt")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> AlertResponse:
        return cls(
            id=str(row["id"]),
            client_id=str(row["client_id"]),
            type=row["type"],
            severity=str(row.get("severity", "warning")),
            detail=str(row.get("detail", "")),
            acknowledged=bool(row.get("acknowledged", False)),
            created_at=row["created_at"],
        )
