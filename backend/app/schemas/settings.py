"""Settings module request/response models in the frontend shapes (``lib/data.ts``
``WorkspaceSettingsData`` / ``SecurityPolicy`` / ``NotifPref``).

Three net-new surfaces (the rest of the Settings screen reuses existing modules -
users / vault / rbac):

* ``WorkspaceSettingsResponse`` mirrors ``WorkspaceSettingsData`` (agency-global).
* ``SecurityPolicyResponse`` mirrors ``SecurityPolicy`` (agency-global).
* ``NotifPrefResponse`` mirrors ``NotifPref`` (per-user, per-event) - the static
  ``label``/``desc``/``icon`` come from the ``NOTIF_EVENTS`` server constant (like
  the rbac matrix), and the stored row supplies only the ``email``/``inApp`` toggles.

Python attributes are snake_case with a ``serialization_alias`` (ruff N815 forbids a
raw camelCase attribute); the emitted JSON keys therefore match the TS types
one-for-one (locked by ``tests/test_contract_lock.py``). Input models accept BOTH
the camelCase wire key (``alias``) and the snake name (``populate_by_name``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Unions verbatim from lib/data.ts. WeekStart is inline in WorkspaceSettingsData;
# SubTier is the exported union (reused from the clients/tiers surface).
WeekStart = Literal["Monday", "Sunday"]
SubTier = Literal["Starter", "Growth", "Scale"]

_WEEK_STARTS: frozenset[str] = frozenset({"Monday", "Sunday"})
_SUB_TIERS: frozenset[str] = frozenset({"Starter", "Growth", "Scale"})


# --------------------------------------------------------------------------- #
# Workspace settings (agency-global singleton)
# --------------------------------------------------------------------------- #
# The frontend defaults (data.ts workspaceDefaults) - one source of truth for the
# GET fallback + the danger-zone reset.
WORKSPACE_DEFAULTS: dict[str, Any] = {
    "agency_name": "Xegents AI",
    "support_email": "support@xegents.ai",
    "timezone": "Asia/Karachi (PKT)",
    "language": "English (US)",
    "week_start": "Monday",
    "default_tier": "Growth",
    "brand_color": "#7B69EE",
}


class WorkspaceSettingsResponse(BaseModel):
    """The agency workspace settings in the frontend ``WorkspaceSettingsData`` shape
    - and ONLY those 7 keys."""

    agency_name: str = Field(serialization_alias="agencyName")
    support_email: str = Field(serialization_alias="supportEmail")
    timezone: str
    language: str
    week_start: WeekStart = Field(serialization_alias="weekStart")
    default_tier: SubTier = Field(serialization_alias="defaultTier")
    brand_color: str = Field(serialization_alias="brandColor")

    @classmethod
    def from_row(cls, row: dict[str, Any] | None) -> WorkspaceSettingsResponse:
        row = row or {}
        week = row.get("week_start")
        tier = row.get("default_tier")
        return cls(
            agency_name=row.get("agency_name") or WORKSPACE_DEFAULTS["agency_name"],
            support_email=row.get("support_email") or WORKSPACE_DEFAULTS["support_email"],
            timezone=row.get("timezone") or WORKSPACE_DEFAULTS["timezone"],
            language=row.get("language") or WORKSPACE_DEFAULTS["language"],
            week_start=week if week in _WEEK_STARTS else "Monday",
            default_tier=tier if tier in _SUB_TIERS else "Growth",
            brand_color=row.get("brand_color") or WORKSPACE_DEFAULTS["brand_color"],
        )


class WorkspaceSettingsUpdate(BaseModel):
    """PUT /settings/workspace body: edit the workspace settings (owner/admin). Every
    field is optional; only those provided are changed. Accepts camelCase or snake."""

    model_config = ConfigDict(populate_by_name=True)

    agency_name: str | None = Field(default=None, alias="agencyName", min_length=1)
    support_email: str | None = Field(default=None, alias="supportEmail", min_length=1)
    timezone: str | None = None
    language: str | None = None
    week_start: WeekStart | None = Field(default=None, alias="weekStart")
    default_tier: SubTier | None = Field(default=None, alias="defaultTier")
    brand_color: str | None = Field(default=None, alias="brandColor")


# --------------------------------------------------------------------------- #
# Security policy (agency-global singleton)
# --------------------------------------------------------------------------- #
SECURITY_DEFAULTS: dict[str, Any] = {
    "enforce_2fa": True,
    "strong_passwords": True,
    "min_pass_length": 12,
    "rotation_days": 90,
    "session_timeout": 30,
    "single_session": False,
    "ip_allowlist": False,
    "audit_logging": True,
}


class SecurityPolicyResponse(BaseModel):
    """The agency security policy in the frontend ``SecurityPolicy`` shape - and ONLY
    those 8 keys."""

    enforce_2fa: bool = Field(serialization_alias="enforce2FA")
    strong_passwords: bool = Field(serialization_alias="strongPasswords")
    min_pass_length: int = Field(serialization_alias="minPassLength")
    rotation_days: int = Field(serialization_alias="rotationDays")
    session_timeout: int = Field(serialization_alias="sessionTimeout")
    single_session: bool = Field(serialization_alias="singleSession")
    ip_allowlist: bool = Field(serialization_alias="ipAllowlist")
    audit_logging: bool = Field(serialization_alias="auditLogging")

    @classmethod
    def from_row(cls, row: dict[str, Any] | None) -> SecurityPolicyResponse:
        row = row or {}

        def _b(key: str) -> bool:
            v = row.get(key)
            return bool(v) if v is not None else bool(SECURITY_DEFAULTS[key])

        def _i(key: str) -> int:
            v = row.get(key)
            return int(v) if v is not None else int(SECURITY_DEFAULTS[key])

        return cls(
            enforce_2fa=_b("enforce_2fa"),
            strong_passwords=_b("strong_passwords"),
            min_pass_length=_i("min_pass_length"),
            rotation_days=_i("rotation_days"),
            session_timeout=_i("session_timeout"),
            single_session=_b("single_session"),
            ip_allowlist=_b("ip_allowlist"),
            audit_logging=_b("audit_logging"),
        )


class SecurityPolicyUpdate(BaseModel):
    """PUT /settings/security body: edit the security policy (owner/admin). Every
    field is optional; only those provided are changed. Accepts camelCase or snake."""

    model_config = ConfigDict(populate_by_name=True)

    enforce_2fa: bool | None = Field(default=None, alias="enforce2FA")
    strong_passwords: bool | None = Field(default=None, alias="strongPasswords")
    min_pass_length: int | None = Field(default=None, alias="minPassLength", ge=8, le=64)
    rotation_days: int | None = Field(default=None, alias="rotationDays", ge=0)
    session_timeout: int | None = Field(default=None, alias="sessionTimeout", ge=1)
    single_session: bool | None = Field(default=None, alias="singleSession")
    ip_allowlist: bool | None = Field(default=None, alias="ipAllowlist")
    audit_logging: bool | None = Field(default=None, alias="auditLogging")


# --------------------------------------------------------------------------- #
# Notification preferences (per-user, per-event)
# --------------------------------------------------------------------------- #
# The 7 events + their static label/desc/icon and defaults (data.ts
# notificationDefaults). The table stores only the per-user email/in_app toggles;
# this constant supplies the immutable presentation + the default toggle state.
NOTIF_EVENTS: tuple[dict[str, Any], ...] = (
    {"key": "audit_done", "label": "Audit completed",
     "desc": "A free or paid audit finishes and the report is ready",
     "icon": "fact_check", "email": True, "in_app": True},
    {"key": "content_review", "label": "Content ready for review",
     "desc": "A draft hits the review gate awaiting approval",
     "icon": "rocket_launch", "email": True, "in_app": True},
    {"key": "new_ticket", "label": "New support ticket",
     "desc": "A client opens or escalates a support ticket",
     "icon": "confirmation_number", "email": True, "in_app": True},
    {"key": "past_due", "label": "Subscription past due",
     "desc": "A client's renewal payment fails or lapses",
     "icon": "payments", "email": True, "in_app": False},
    {"key": "member_login", "label": "New sign-in",
     "desc": "A team member signs in from a new device or location",
     "icon": "login", "email": False, "in_app": True},
    {"key": "access_change", "label": "Access changed",
     "desc": "Roles or permissions are granted or revoked",
     "icon": "admin_panel_settings", "email": True, "in_app": True},
    {"key": "task_assigned", "label": "Task assigned",
     "desc": "A task is assigned or reassigned to you",
     "icon": "assignment_ind", "email": True, "in_app": True},
    {"key": "member_welcome", "label": "Account created",
     "desc": "Your team account is created and ready to use",
     "icon": "person_add", "email": True, "in_app": True},
    {"key": "portal_ready", "label": "Portal access ready",
     "desc": "A client's portal login is created and shared",
     "icon": "vpn_key", "email": True, "in_app": True},
    {"key": "weekly_digest", "label": "Weekly digest",
     "desc": "Monday summary of audits, jobs and client health",
     "icon": "summarize", "email": True, "in_app": False},
)

_NOTIF_KEYS: frozenset[str] = frozenset(e["key"] for e in NOTIF_EVENTS)


def is_notif_key(key: str) -> bool:
    """Whether ``key`` is one of the 7 known notification events."""
    return key in _NOTIF_KEYS


class NotifPrefResponse(BaseModel):
    """One notification preference in the frontend ``NotifPref`` shape - and ONLY
    those 6 keys. ``label``/``desc``/``icon`` are static (from ``NOTIF_EVENTS``);
    ``email``/``inApp`` are the caller's stored toggles (else the event default)."""

    key: str
    label: str
    desc: str
    icon: str
    email: bool
    in_app: bool = Field(serialization_alias="inApp")

    @classmethod
    def merged(cls, overrides: dict[str, dict[str, Any]]) -> list[NotifPrefResponse]:
        """The full 7-event list, each merged with the caller's stored toggles.

        ``overrides`` maps ``event_key -> {email, in_app}`` (the user's rows). A
        missing event falls back to the ``NOTIF_EVENTS`` default; unknown stored
        keys are ignored (the event catalogue is authoritative)."""
        out: list[NotifPrefResponse] = []
        for event in NOTIF_EVENTS:
            row = overrides.get(str(event["key"]), {})
            email = row.get("email")
            in_app = row.get("in_app")
            out.append(
                cls(
                    key=str(event["key"]),
                    label=str(event["label"]),
                    desc=str(event["desc"]),
                    icon=str(event["icon"]),
                    email=bool(email) if email is not None else bool(event["email"]),
                    in_app=bool(in_app) if in_app is not None else bool(event["in_app"]),
                )
            )
        return out


class NotifPrefItem(BaseModel):
    """One toggle change in a PUT /settings/notifications body."""

    model_config = ConfigDict(populate_by_name=True)

    key: str = Field(min_length=1)
    email: bool
    in_app: bool = Field(alias="inApp")


class NotifPrefUpdate(BaseModel):
    """PUT /settings/notifications body: the caller's toggle changes (per-user).

    Each item upserts one ``(user, event)`` row; unknown event keys are ignored by
    the endpoint so a stale client can never write junk rows."""

    prefs: list[NotifPrefItem]
