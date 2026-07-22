"""Key Vault request/response models (frontend ``VaultKey`` shape).

A list NEVER carries a real secret - ``secret`` is always empty there. Only the
super-admin reveal endpoint returns a decrypted value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr

from app.util.timefmt import relative_ago

ProviderId = Literal[
    "serper", "dataforseo", "google", "anthropic", "imagegen", "gsheets", "wordpress",
    "foursquare", "apify", "capmonster", "resend",
]
Scope = Literal["Agency-global", "Per-site"]
KeyStatus = Literal["active", "expiring", "rotate"]

# Age thresholds (days) that drive the rotate/expiring badges (see frontend seed).
_EXPIRING_DAYS = 60
_ROTATE_DAYS = 150


def compute_status(rotated_at: datetime | str | None) -> KeyStatus:
    """Derive a key's health from how long ago it was last rotated."""
    if rotated_at is None:
        return "active"
    if isinstance(rotated_at, datetime):
        dt = rotated_at
    else:
        try:
            dt = datetime.fromisoformat(str(rotated_at).replace("Z", "+00:00"))
        except ValueError:
            return "active"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    days = (datetime.now(UTC) - dt).days
    if days >= _ROTATE_DAYS:
        return "rotate"
    if days >= _EXPIRING_DAYS:
        return "expiring"
    return "active"


class VaultKeyResponse(BaseModel):
    """A vault entry in the frontend ``VaultKey`` shape; ``secret`` is masked-out."""

    id: str
    provider: str
    label: str
    masked: str
    secret: str = ""  # never populated in a list/read - reveal is a separate call
    scope: str
    site: str | None = None
    status: KeyStatus
    rotated: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> VaultKeyResponse:
        return cls(
            id=str(row["id"]),
            provider=row.get("provider", ""),
            label=row.get("label", ""),
            masked=row.get("masked", ""),
            scope=row.get("scope", "Agency-global"),
            site=row.get("site"),
            status=compute_status(row.get("rotated_at")),
            rotated=relative_ago(row.get("rotated_at")),
        )


class VaultKeyCreate(BaseModel):
    provider: ProviderId
    label: str = Field(min_length=1)
    secret: SecretStr = Field(min_length=1)
    scope: Scope = "Agency-global"
    site: str | None = None


class RotateRequest(BaseModel):
    secret: SecretStr = Field(min_length=1)


class RevealResponse(BaseModel):
    """The super-admin-only decrypted value."""

    id: str
    secret: str
