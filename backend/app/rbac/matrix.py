"""Canonical RBAC reference data + enforcement helpers.

Mirrored VERBATIM from ``frontend/lib/data.ts`` so the API and the dashboard
agree byte-for-byte. Two authoritative datasets are reconciled here:

* **8 permissions x 6 governance roles** (``DEFAULT_ROLE_PERMS``) - the coarse
  matrix the Team screen renders and the vocabulary shared-base routes enforce
  with ``require_perm``. It covers all six roles, so it is the enforcement base.
* **17 features x 4 role templates** (``FEATURES`` / ``TEMPLATES``) - the
  fine-grained matrix the Add-Member screen renders. Templates seed a user's
  per-user feature grants; ``feature_allows`` enforces fine-grained access where
  a later module needs it. The doc's Full/View/Off is 3-state; the frontend
  template data only encodes on/off, so a template grant maps to ``"full"`` and
  everything else to ``"off"`` (per-user toggles can still store ``"view"``).

Owner (agency super-admin) is implicitly all-on and locked: every ``role_has_*``
and ``*_allows`` check short-circuits to allow for ``owner``.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel

# --- Type vocabularies (lowercase-canonical; DB enums match) ------------------

AppRole = Literal["owner", "admin", "manager", "specialist", "analyst", "viewer"]
PermKey = Literal[
    "run_audits",
    "publish_content",
    "manage_clients",
    "assign_tasks",
    "manage_team",
    "access_control",
    "manage_vault",
    "view_reports",
]
FeatureGroup = Literal["Analytics", "Content", "Delivery", "Admin"]
AccessLevel = Literal["full", "view", "off"]

ROLE_ORDER: tuple[AppRole, ...] = get_args(AppRole)
PERM_KEYS: tuple[PermKey, ...] = get_args(PermKey)
ACCESS_LEVELS: tuple[AccessLevel, ...] = get_args(AccessLevel)

# Most-privileged -> least; used to compare AccessLevel ("full" satisfies "view").
_LEVEL_RANK: dict[AccessLevel, int] = {"off": 0, "view": 1, "full": 2}


# --- Reference models (field names mirror the frontend shapes) ----------------


class RoleMetaDef(BaseModel):
    """Governance-role metadata (mirrors ``ROLE_META``)."""

    role: AppRole
    desc: str
    color: str  # frontend ``c``


class PermissionDef(BaseModel):
    """A single toggleable permission (mirrors ``permissions[]``)."""

    key: PermKey
    label: str
    desc: str
    icon: str


class FeatureDef(BaseModel):
    """One of the 17 access features (mirrors ``accessFeatures[]``)."""

    key: str
    label: str
    short: str
    icon: str
    group: FeatureGroup
    desc: str


class RoleTemplateDef(BaseModel):
    """A ready-made access template (mirrors ``roleTemplates[]``)."""

    key: str
    label: str
    tagline: str
    icon: str
    role: AppRole
    color: str
    grants: tuple[str, ...]


# --- Governance roles ---------------------------------------------------------

ROLE_META: tuple[RoleMetaDef, ...] = (
    RoleMetaDef(role="owner", desc="Full control across the platform - billing, access & data.", color="#7B69EE"),
    RoleMetaDef(role="admin", desc="Manage team, clients & delivery. No access-control changes.", color="#4D8DF0"),
    RoleMetaDef(role="manager", desc="Assign work, run audits & publish across a client book.", color="#1FA890"),
    RoleMetaDef(role="specialist", desc="Deliver audits & content on assigned jobs.", color="#C77E14"),
    RoleMetaDef(role="analyst", desc="Run audits and read reports - no publishing.", color="#D4568A"),
    RoleMetaDef(role="viewer", desc="Read-only access to reports and dashboards.", color="var(--muted)"),
)

# --- The 8 permissions (verbatim from ``permissions``) ------------------------

PERMISSIONS: tuple[PermissionDef, ...] = (
    PermissionDef(key="run_audits", label="Run audits", desc="Trigger free & paid audits", icon="fact_check"),
    PermissionDef(key="publish_content", label="Publish content", desc="Push content live past the review gate", icon="rocket_launch"),
    PermissionDef(key="manage_clients", label="Manage clients", desc="Edit accounts, contacts & subscriptions", icon="diversity_3"),
    PermissionDef(key="assign_tasks", label="Assign tasks", desc="Create & route jobs to the team", icon="assignment_ind"),
    PermissionDef(key="manage_team", label="Manage team", desc="Add, edit & deactivate members", icon="group_add"),
    PermissionDef(key="access_control", label="Access control", desc="Edit roles & permissions", icon="admin_panel_settings"),
    PermissionDef(key="manage_vault", label="Key vault", desc="View & rotate API keys and creds", icon="key"),
    PermissionDef(key="view_reports", label="View reports", desc="Open audits, dashboards & metrics", icon="summarize"),
)

# Default permission grants per role (verbatim ``defaultRolePerms``). Owner is
# stored all-on for display; enforcement additionally hard-locks owner to all-on.
DEFAULT_ROLE_PERMS: dict[AppRole, frozenset[PermKey]] = {
    "owner": frozenset(PERM_KEYS),
    "admin": frozenset(
        {"run_audits", "publish_content", "manage_clients", "assign_tasks", "manage_team", "manage_vault", "view_reports"}
    ),
    "manager": frozenset({"run_audits", "publish_content", "manage_clients", "assign_tasks", "view_reports"}),
    "specialist": frozenset({"run_audits", "publish_content", "view_reports"}),
    "analyst": frozenset({"run_audits", "view_reports"}),
    "viewer": frozenset({"view_reports"}),
}

# --- The 17 features (verbatim from ``accessFeatures``) ------------------------

FEATURES: tuple[FeatureDef, ...] = (
    FeatureDef(key="rank_tracker", label="Rank Tracker", short="Rank Tracker", icon="trending_up", group="Analytics", desc="Track keyword positions & ranking history"),
    FeatureDef(key="technical_audit", label="Technical Audit", short="Tech Audit", icon="troubleshoot", group="Analytics", desc="Run site audits, review & mark issues fixed"),
    FeatureDef(key="on_page", label="On-Page Optimizer", short="On-Page", icon="tune", group="Analytics", desc="Review & apply on-page recommendations"),
    FeatureDef(key="keyword_research", label="Keyword Research", short="Keywords", icon="search", group="Analytics", desc="Find, group & assign keywords"),
    FeatureDef(key="backlink_manager", label="Backlink Manager", short="Backlinks", icon="hub", group="Analytics", desc="Monitor profile, flag lost or toxic links"),
    FeatureDef(key="competitor_intel", label="Competitor Intel", short="Competitors", icon="insights", group="Analytics", desc="Compare clients & read gap analysis"),
    FeatureDef(key="local_seo", label="Local SEO", short="Local SEO", icon="storefront", group="Analytics", desc="Track local & map-pack rankings"),
    FeatureDef(key="content_pipeline", label="Content Pipeline", short="Content", icon="article", group="Content", desc="Briefs, AI drafting, edit & review"),
    FeatureDef(key="publishing", label="Publishing", short="Publishing", icon="rocket_launch", group="Content", desc="Send approved content live to the CMS"),
    FeatureDef(key="reporting", label="Reporting", short="Reporting", icon="summarize", group="Delivery", desc="Build, schedule & send client reports"),
    FeatureDef(key="task_board", label="Task / Workflow Board", short="Task Board", icon="checklist", group="Delivery", desc="Create, assign & track team tasks"),
    FeatureDef(key="client_onboarding", label="Client Onboarding", short="Onboarding", icon="person_add", group="Delivery", desc="Run the onboarding wizard & collect access"),
    FeatureDef(key="client_setup", label="Client & Website Setup", short="Client Setup", icon="language", group="Delivery", desc="Add & edit clients and their websites"),
    FeatureDef(key="data_import", label="Data Import", short="Imports", icon="upload_file", group="Delivery", desc="Upload & map CSV/Excel exports"),
    FeatureDef(key="key_vault", label="Integrations & Key Vault", short="Key Vault", icon="key", group="Admin", desc="API keys & integrations - Super Admin only"),
    FeatureDef(key="billing", label="Billing", short="Billing", icon="payments", group="Admin", desc="Plans, invoices & payment settings"),
    FeatureDef(key="team_access", label="Team & Access", short="Team & Access", icon="admin_panel_settings", group="Admin", desc="Manage members, roles & permissions"),
)

FEATURE_KEYS: tuple[str, ...] = tuple(f.key for f in FEATURES)

# All 17 feature keys, used by the Super Admin template.
_ALL_FEATURE_KEYS: tuple[str, ...] = FEATURE_KEYS

# --- The 4 role templates (verbatim from ``roleTemplates``) -------------------

TEMPLATES: tuple[RoleTemplateDef, ...] = (
    RoleTemplateDef(
        key="seo", label="SEO Specialist", tagline="Analytics & optimization", icon="query_stats",
        role="specialist", color="#4D8DF0",
        grants=("rank_tracker", "technical_audit", "on_page", "keyword_research", "backlink_manager", "competitor_intel", "local_seo", "content_pipeline", "reporting", "task_board", "client_onboarding", "client_setup", "data_import"),
    ),
    RoleTemplateDef(
        key="content", label="Content Creator", tagline="Copywriting & publishing", icon="edit_note",
        role="specialist", color="#C77E14",
        grants=("rank_tracker", "on_page", "keyword_research", "competitor_intel", "content_pipeline", "publishing", "reporting", "task_board", "client_setup"),
    ),
    RoleTemplateDef(
        key="va", label="Virtual Assistant", tagline="Coordination & admin", icon="support_agent",
        role="manager", color="#7B69EE",
        grants=("rank_tracker", "content_pipeline", "local_seo", "reporting", "task_board", "client_onboarding", "client_setup", "data_import"),
    ),
    RoleTemplateDef(
        key="super", label="Super Admin", tagline="Full access - everything on", icon="shield_person",
        role="owner", color="#7B69EE",
        grants=_ALL_FEATURE_KEYS,
    ),
)


# --- Enforcement helpers ------------------------------------------------------


def perms_for_role(role: AppRole) -> frozenset[PermKey]:
    """Default permission set for ``role`` (owner is all permissions)."""
    if role == "owner":
        return frozenset(PERM_KEYS)
    return DEFAULT_ROLE_PERMS[role]


def role_has_perm(role: AppRole, perm: PermKey) -> bool:
    """Whether ``role`` holds ``perm``. Owner is hard-locked to all-on."""
    return role == "owner" or perm in DEFAULT_ROLE_PERMS[role]


def level_satisfies(have: AccessLevel, required: AccessLevel) -> bool:
    """Whether an access level ``have`` meets ``required`` (full > view > off)."""
    return _LEVEL_RANK[have] >= _LEVEL_RANK[required]


def effective_feature_level(
    role: AppRole, overrides: dict[str, AccessLevel], feature_key: str
) -> AccessLevel:
    """Resolve a user's access to ``feature_key``.

    Owner is all-on (``full``). Otherwise a per-user override wins; with no
    override the feature is ``off`` (access is granted explicitly, never implied).
    """
    if role == "owner":
        return "full"
    return overrides.get(feature_key, "off")


def feature_allows(
    role: AppRole,
    overrides: dict[str, AccessLevel],
    feature_key: str,
    required: AccessLevel = "full",
) -> bool:
    """Whether the user's effective access to ``feature_key`` meets ``required``."""
    return level_satisfies(effective_feature_level(role, overrides, feature_key), required)
