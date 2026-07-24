"""Schemas for the multi-client WordPress Connections registry.

The response NEVER carries the sealed secret (or its plaintext) - only masked
metadata: the site URL, the auth method, the (non-secret) username, the last-test
status, and a ``configured`` flag telling the UI whether a credential is stored.
The upsert body carries the raw ``api_key`` / ``password`` inbound only; they are
sealed server-side (app/services/wp_connections.py) and never read back.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AuthMethod = Literal["plugin", "xmlrpc", "app_password"]


def _iso_or_none(value: Any) -> str | None:
    """Render a timestamptz to ISO-8601, or ``None`` (never tested)."""
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value)


class WpConnectionResponse(BaseModel):
    """One client's WordPress connection state (masked - no secret ever).

    ``configured`` is True when a sealed credential is stored (so the UI can show a
    "credential set" affordance without revealing it). ``status`` is the raw
    connectivity verdict (``unknown`` | ``connected`` | ``failed``, or
    ``unconfigured`` for a client with no connection row yet); the frontend maps it
    to a pill.
    """

    client_id: str = Field(serialization_alias="clientId")
    client_name: str = Field(serialization_alias="clientName")
    site_url: str = Field(default="", serialization_alias="siteUrl")
    auth_method: AuthMethod = Field(default="plugin", serialization_alias="authMethod")
    username: str = ""
    status: str = "unconfigured"
    configured: bool = False
    last_tested_at: str | None = Field(default=None, serialization_alias="lastTestedAt")

    model_config = {"populate_by_name": True}

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> WpConnectionResponse:
        """Build from a ``clients LEFT JOIN wp_connections`` row.

        A client without a connection row has ``auth_method``/``site_url`` NULL - so
        default them and report ``unconfigured``. The join exposes a ``configured``
        boolean (``secret_sealed is not null``) rather than the bytea itself, so the
        sealed secret can never reach this serializer.
        """
        has_row = row.get("site_url") is not None or row.get("auth_method") is not None
        method = str(row.get("auth_method") or "plugin")
        status = str(row.get("status") or "unknown") if has_row else "unconfigured"
        return cls(
            client_id=str(row["client_id"]),
            client_name=str(row.get("client_name") or ""),
            site_url=str(row.get("site_url") or ""),
            auth_method=method if method in ("plugin", "xmlrpc", "app_password") else "plugin",  # type: ignore[arg-type]
            username=str(row.get("username") or ""),
            status=status,
            configured=bool(row.get("configured")),
            last_tested_at=_iso_or_none(row.get("last_tested_at")),
        )


class WpConnectionUpsert(BaseModel):
    """PUT body: set/replace a client's WordPress connection.

    ``api_key`` is the plugin shared key (method ``plugin``); ``username`` +
    ``password`` are the login credential (methods ``xmlrpc`` / ``app_password``).
    The relevant secret is sealed server-side. All secret fields are OPTIONAL: a
    metadata-only edit (e.g. changing the site URL) omits them and the stored secret
    is left unchanged.
    """

    site_url: str = Field(default="", alias="siteUrl")
    auth_method: AuthMethod = Field(default="plugin", alias="authMethod")
    api_key: str | None = Field(default=None, alias="apiKey")
    username: str | None = None
    password: str | None = None

    model_config = {"populate_by_name": True}

    def secret(self) -> str | None:
        """The inbound secret to seal for this method (or None to keep the existing).

        ``plugin`` -> the api_key; ``xmlrpc`` / ``app_password`` -> the password. An
        empty/blank value is treated as "not provided" (keep the stored secret).
        """
        raw = self.api_key if self.auth_method == "plugin" else self.password
        value = (raw or "").strip()
        return value or None


class WpTestResponse(BaseModel):
    """The result of a POST .../test connectivity probe against the real site."""

    ok: bool
    detail: str = ""
    status: str = "unknown"
    last_tested_at: str | None = Field(default=None, serialization_alias="lastTestedAt")

    model_config = {"populate_by_name": True}
