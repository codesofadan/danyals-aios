"""Identity request/response models mirroring the frontend team shapes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, SecretStr, field_validator

from app.rbac import FEATURE_KEYS, TEMPLATES, AccessLevel, AppRole

_FEATURE_KEY_SET = frozenset(FEATURE_KEYS)
_TEMPLATE_KEYS = frozenset(t.key for t in TEMPLATES)


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
    # The staff login key (case-insensitively unique). Required so the account can
    # actually sign in via POST /auth/login after the P6A-7 cutover.
    username: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=8)
    role: AppRole = "viewer"
    title: str = ""
    avatar_color: str = "#7B69EE"
    template: str | None = None  # optional role template key to seed feature grants


class PortalUserRequest(BaseModel):
    """Payload for provisioning a client PORTAL login (owner-only).

    Carries no role and no client_id: the role is fixed to ``client`` and the
    tenant comes from the path, so a caller can never provision a staff account
    or point a login at another client's tenant through this endpoint.
    """

    email: EmailStr
    name: str = Field(min_length=1)
    # The portal login key (case-insensitively unique) the client signs in with.
    username: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=8)


class MemberResponse(BaseModel):
    """A team member in the frontend ``TeamMemberRecord`` shape.

    The identity row supplies the profile fields; the performance metrics
    (activeTasks/completed/onTime/utilization/quality) default to 0 here and are
    overlaid by the routers from :mod:`app.services.team_metrics` (7F-3), computed
    from the tasks + activity ledgers.
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


# --- Feature-grant editing (7F-4) --------------------------------------------


class UpdateGrantsRequest(BaseModel):
    """PUT body: set a user's per-feature access levels (the 17-feature toggles).

    ``grants`` maps a feature key -> ``full`` | ``view`` | ``off``. Every key MUST
    be one of the 17 canonical ``accessFeatures`` keys (unknown keys are rejected
    before any write); levels are validated by the ``AccessLevel`` literal. The
    map may be partial (only the listed features are changed).
    """

    grants: dict[str, AccessLevel] = Field(default_factory=dict)

    @field_validator("grants")
    @classmethod
    def _known_feature_keys(cls, value: dict[str, AccessLevel]) -> dict[str, AccessLevel]:
        unknown = sorted(set(value) - _FEATURE_KEY_SET)
        if unknown:
            raise ValueError(f"unknown feature key(s): {', '.join(unknown)}")
        return value


class UserGrantsResponse(BaseModel):
    """A user's effective access level for every one of the 17 features.

    ``grants`` always carries ALL 17 keys (resolved via ``effective_feature_level``):
    an owner reads back all ``full`` (all-on and locked), otherwise a per-user
    override wins and any un-granted feature resolves to ``off``.
    """

    grants: dict[str, AccessLevel]


# --- Add-Member invite (generated credentials) (7F-4) ------------------------


class InviteMemberRequest(BaseModel):
    """Payload for the Add-Member wizard: pick access + identity, server mints creds.

    Mirrors the wizard's output (``NewMember``): a ``template`` role-template key
    seeds the feature grants, OR an explicit ``features`` list (custom toggles)
    overrides it; ``role`` is the governance role stamped on the roster row. No
    password is supplied - the server generates a one-time username + password.
    """

    email: EmailStr
    name: str = Field(min_length=1)
    role: AppRole = "specialist"
    title: str = ""
    avatar_color: str = "#7B69EE"
    template: str | None = None  # role-template key (seo|content|va|super)
    features: list[str] | None = None  # explicit granted feature keys (custom)

    @field_validator("template")
    @classmethod
    def _known_template(cls, value: str | None) -> str | None:
        if value is not None and value not in _TEMPLATE_KEYS:
            raise ValueError(f"unknown role template: {value}")
        return value

    @field_validator("features")
    @classmethod
    def _known_features(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            unknown = sorted(set(value) - _FEATURE_KEY_SET)
            if unknown:
                raise ValueError(f"unknown feature key(s): {', '.join(unknown)}")
        return value


class MemberInviteResponse(BaseModel):
    """The created member + the one-time credentials, returned to the admin ONCE.

    ``tempPassword`` is the plaintext generated password; it is shown here a single
    time and is NEVER persisted (only its argon2id hash lives in ``auth.users``).
    """

    member: MemberResponse
    username: str
    temp_password: str = Field(serialization_alias="tempPassword")
