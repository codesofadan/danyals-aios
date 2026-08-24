"""The canonical RBAC access model - reference data + enforcement helpers.

**This module is the single source of truth**, and the ONLY copy that any code
consults. Two things about the dashboard are true today and should not be overstated,
because overstating them is the exact defect this file was rewritten to remove:

* ``frontend/lib/data.ts`` **still declares its own copy.** It is held identical to
  this one by ``tests/test_rbac_single_source.py`` until the dashboard is moved onto
  ``GET /rbac/*``. That move is a separate piece of work.
* **No caller of ``GET /rbac/*`` exists yet.** All four endpoints are served,
  authorised and contract-tested with no product consumer: the single HTTP call site,
  ``useRbac()`` in ``frontend/lib/hooks/team.ts``, is never invoked, and
  ``AccessControl`` - the component it feeds - is never rendered.

It used to say it was "mirrored VERBATIM from ``frontend/lib/data.ts``". That was
false, and had been for some time: on 2026-08-24 a field-by-field comparison of the
two files found **14 differences** - nine colours (this file still carried the
pre-Avant-Garde palette), one feature icon (``client_setup``), and four descriptions
where an em dash had been transcribed as a hyphen. None of it reached enforcement,
because the drift landed entirely in presentation; the permission keys, the 8x6
grant matrix, the feature keys and the template grants all still agreed. That is the
warning, not the reassurance - the half that bites was one edit away.

The drift survived because nothing compared the two files. ``test_rbac_matrix.py``
claimed to "pin the reference data to ``frontend/lib/data.ts``" while re-typing the
expected values as Python literals, so it tested Python against Python;
``test_contract_lock.py`` reads the TS but compares field NAMES only, and listed
none of the RBAC models. Three hand-written copies, no comparison between any two.
``tests/test_rbac_single_source.py`` is the gate that now does the comparison.

Two authoritative datasets live here:

* **8 permissions x 6 governance roles** (``DEFAULT_ROLE_PERMS``) - the coarse
  matrix the Team screen renders and the vocabulary shared-base routes enforce
  with ``require_perm``. It covers all six roles, so it is the enforcement base.
* **11 features x 4 role templates** (``FEATURES`` / ``TEMPLATES``) - the
  fine-grained matrix the Add-Member screen renders. Templates seed a user's
  per-user feature grants; ``feature_allows`` enforces fine-grained access where
  a later module needs it. The doc's Full/View/Off is 3-state; the frontend
  template data only encodes on/off, so a template grant maps to ``"full"`` and
  everything else to ``"off"`` (per-user toggles can still store ``"view"``).

Owner (agency super-admin) is implicitly all-on and locked: every ``role_has_*``
and ``*_allows`` check short-circuits to allow for ``owner``.

**Colour is deliberately absent.** A role's and a template's accent colour is a theme
token owned by ``frontend/lib/data.ts`` (``SERIES``), and no Python here ever read one
- the only reader was ``routers/rbac.py`` copying it onto a response field the
dashboard discards. Nine of the fourteen drifts above were that field. It is not
reconciled; it is removed, so *this catalogue's* drift surface goes with it. What this
module owns is anything with product meaning - keys, groups, grants, labels,
descriptions, icons.

Note the narrow scope of that claim. The pre-Avant-Garde palette is **not** gone from
the backend: the same hex literals remain hardcoded in roughly a dozen places under
``app/`` (``schemas/identity.py``, ``schemas/clients.py``, ``schemas/tiers.py``,
``services/provisioning.py`` and others), several of which are served to the dashboard.
``#7B69EE`` - the value deleted from ``ROLE_META.owner`` here - is still the
``avatar_color`` default a newly provisioned member is written to the database with.
Removing colour from THIS catalogue does not make the backend palette-free, and the
guard in ``tests/test_rbac_single_source.py`` will report green over all of it.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel

# --- Type vocabularies (lowercase-canonical; DB enums match) ------------------

AppRole = Literal["owner", "admin", "manager", "specialist", "analyst", "viewer"]
# The client-portal login is a 7th role that sits OUTSIDE the governance matrix:
# it holds NONE of the staff permissions, is scoped to a single clients row, and
# reads only through the portal_* views. ``AppRole`` stays the 6 staff roles;
# ``UserRole`` is the full set a ``public.users`` row may carry.
#
# This is the CURRENT state, not a finished design. Phase 3.1 specifies client
# capability tiers - "See / Tell / Ask on, Decide-and-approve off by default" - and
# NONE of that is modelled anywhere yet: a client is binary (every check early-returns
# empty or ``off``), so "Decide-and-approve off" holds by accident rather than by
# design. When those tiers land they belong in THIS file, beside the staff vocabulary,
# not in a second access model somewhere else.
UserRole = Literal["owner", "admin", "manager", "specialist", "analyst", "viewer", "client"]
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
# Module (Part-8 tool) permissions: an ADDITIVE, backend-only vocabulary that sits
# ALONGSIDE the 8 frontend-mirrored governance perms above (which stay byte-for-byte
# in sync with ``data.ts``). A tool module that needs a finer paid-action gate than a
# governance role adds a key here + its holder roles in ``MODULE_PERM_ROLES``; it is
# NOT part of ``PermKey``/``PERMISSIONS`` (so the Team-screen matrix is unchanged).
# ``run_research`` gates the paid keyword research + all keyword-bank mutations.
ModulePermKey = Literal["run_research"]
FeatureGroup = Literal["Analytics", "Content", "Delivery", "Admin"]
AccessLevel = Literal["full", "view", "off"]

ROLE_ORDER: tuple[AppRole, ...] = get_args(AppRole)
PERM_KEYS: tuple[PermKey, ...] = get_args(PermKey)
ACCESS_LEVELS: tuple[AccessLevel, ...] = get_args(AccessLevel)

# The governance (staff) roles - everything a ``client`` is NOT.
STAFF_ROLES: frozenset[AppRole] = frozenset(get_args(AppRole))


def is_staff_role(role: str) -> bool:
    """Whether ``role`` is a staff (governance) role - i.e. anything but ``client``."""
    return role != "client"

# Most-privileged -> least; used to compare AccessLevel ("full" satisfies "view").
_LEVEL_RANK: dict[AccessLevel, int] = {"off": 0, "view": 1, "full": 2}


# --- Reference models --------------------------------------------------------
# Field names are the shapes the dashboard renders, because it renders THESE - the
# models are served directly as the ``/rbac/*`` response bodies. Colour is absent by
# design (see the module docstring).


class RoleMetaDef(BaseModel):
    """Governance-role metadata: served as part of ``GET /rbac/roles``."""

    role: AppRole
    desc: str


class PermissionDef(BaseModel):
    """A single toggleable permission: served by ``GET /rbac/permissions``."""

    key: PermKey
    label: str
    desc: str
    icon: str


class FeatureDef(BaseModel):
    """One of the 11 access features: served by ``GET /rbac/features``."""

    key: str
    label: str
    short: str
    icon: str
    group: FeatureGroup
    desc: str


class RoleTemplateDef(BaseModel):
    """A ready-made access template: served by ``GET /rbac/templates``."""

    key: str
    label: str
    tagline: str
    icon: str
    role: AppRole
    grants: tuple[str, ...]


# --- Governance roles ---------------------------------------------------------

ROLE_META: tuple[RoleMetaDef, ...] = (
    RoleMetaDef(role="owner", desc="Full control across the platform — billing, access & data."),
    RoleMetaDef(role="admin", desc="Manage team, clients & delivery. No access-control changes."),
    RoleMetaDef(role="manager", desc="Assign work, run audits & publish across a client book."),
    RoleMetaDef(role="specialist", desc="Deliver audits & content on assigned jobs."),
    RoleMetaDef(role="analyst", desc="Run audits and read reports — no publishing."),
    RoleMetaDef(role="viewer", desc="Read-only access to reports and dashboards."),
)

# --- The 8 permissions --------------------------------------------------------

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

# Default permission grants per role. Owner is stored all-on for display;
# enforcement additionally hard-locks owner to all-on.
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

# Holder roles per MODULE permission (see ``ModulePermKey``). Kept SEPARATE from
# ``DEFAULT_ROLE_PERMS`` so the 8x6 matrix the Team screen renders stays exactly the
# eight governance permissions - a backend-only gate must not silently appear as a
# ninth column in the operator's access grid. Owner is all-on and locked (enforced in
# ``role_has_module_perm``), so it need not be listed.
#
# ``run_research`` = the LEADS (owner/admin/manager). This MIRRORS the keyword-bank
# RLS insert/update policies in ``0035_keyword_research.sql``
# (``current_app_role() in ('owner', 'admin', 'manager')``) exactly: the app gate and
# the database must agree, or a caller who passes the app gate would be rejected by
# Postgres with an opaque RLS error instead of a clean 403.
MODULE_PERM_ROLES: dict[ModulePermKey, frozenset[AppRole]] = {
    "run_research": frozenset({"owner", "admin", "manager"}),
}

# --- The 11 features ----------------------------------------------------------

FEATURES: tuple[FeatureDef, ...] = (
    FeatureDef(key="technical_audit", label="Technical Audit", short="Tech Audit", icon="troubleshoot", group="Analytics", desc="Run site audits, review & mark issues fixed"),
    FeatureDef(key="content_pipeline", label="Content Pipeline", short="Content", icon="article", group="Content", desc="Briefs, AI drafting, edit & review"),
    FeatureDef(key="publishing", label="Publishing", short="Publishing", icon="rocket_launch", group="Content", desc="Send approved content live to the CMS"),
    FeatureDef(key="reporting", label="Reporting", short="Reporting", icon="summarize", group="Delivery", desc="Build, schedule & send client reports"),
    FeatureDef(key="task_board", label="Task / Workflow Board", short="Task Board", icon="checklist", group="Delivery", desc="Create, assign & track team tasks"),
    FeatureDef(key="client_onboarding", label="Client Onboarding", short="Onboarding", icon="person_add", group="Delivery", desc="Run the onboarding wizard & collect access"),
    FeatureDef(key="client_setup", label="Client & Website Setup", short="Client Setup", icon="add_business", group="Delivery", desc="Add & edit clients and their websites"),
    FeatureDef(key="data_import", label="Data Import", short="Imports", icon="upload_file", group="Delivery", desc="Upload & map CSV/Excel exports"),
    FeatureDef(key="key_vault", label="Integrations & Key Vault", short="Key Vault", icon="key", group="Admin", desc="API keys & integrations — Super Admin only"),
    FeatureDef(key="billing", label="Billing", short="Billing", icon="payments", group="Admin", desc="Plans, invoices & payment settings"),
    FeatureDef(key="team_access", label="Team & Access", short="Team & Access", icon="admin_panel_settings", group="Admin", desc="Manage members, roles & permissions"),
)

FEATURE_KEYS: tuple[str, ...] = tuple(f.key for f in FEATURES)

# All 11 feature keys, used by the Super Admin template.
_ALL_FEATURE_KEYS: tuple[str, ...] = FEATURE_KEYS

# --- The 4 role templates -----------------------------------------------------

TEMPLATES: tuple[RoleTemplateDef, ...] = (
    RoleTemplateDef(
        key="seo", label="SEO Specialist", tagline="Analytics & optimization", icon="query_stats",
        role="specialist",
        grants=("technical_audit", "content_pipeline", "reporting", "task_board", "client_onboarding", "client_setup", "data_import"),
    ),
    RoleTemplateDef(
        key="content", label="Content Creator", tagline="Copywriting & publishing", icon="edit_note",
        role="specialist",
        grants=("content_pipeline", "publishing", "reporting", "task_board", "client_setup"),
    ),
    RoleTemplateDef(
        key="va", label="Virtual Assistant", tagline="Coordination & admin", icon="support_agent",
        role="manager",
        grants=("content_pipeline", "reporting", "task_board", "client_onboarding", "client_setup", "data_import"),
    ),
    RoleTemplateDef(
        key="super", label="Super Admin", tagline="Full access — everything on", icon="shield_person",
        role="owner",
        grants=_ALL_FEATURE_KEYS,
    ),
)


# --- Enforcement helpers ------------------------------------------------------


def perms_for_role(role: UserRole) -> frozenset[PermKey]:
    """Default permission set for ``role`` (owner is all; client holds none).

    ``client`` returns early BEFORE indexing ``DEFAULT_ROLE_PERMS`` (which has no
    client key): a portal client is outside the governance matrix and holds no
    staff permission.
    """
    if role == "client":
        return frozenset()
    if role == "owner":
        return frozenset(PERM_KEYS)
    return DEFAULT_ROLE_PERMS[role]


def role_has_perm(role: UserRole, perm: PermKey) -> bool:
    """Whether ``role`` holds ``perm``. Owner is all-on; client holds none.

    ``client`` returns early BEFORE indexing ``DEFAULT_ROLE_PERMS``.
    """
    if role == "client":
        return False
    return role == "owner" or perm in DEFAULT_ROLE_PERMS[role]


def role_has_module_perm(role: UserRole, perm: ModulePermKey) -> bool:
    """Whether ``role`` holds the MODULE permission ``perm``. Owner is all-on;
    client holds none.

    Deliberately separate from :func:`role_has_perm`: a module perm is NOT in
    ``DEFAULT_ROLE_PERMS`` (that map is exactly the eight governance permissions), so
    routing a module perm through ``role_has_perm`` would resolve it to owner-only for
    every other role - silently locking out the leads the RLS policies do permit.
    """
    if role == "client":
        return False
    return role == "owner" or role in MODULE_PERM_ROLES[perm]


def level_satisfies(have: AccessLevel, required: AccessLevel) -> bool:
    """Whether an access level ``have`` meets ``required`` (full > view > off)."""
    return _LEVEL_RANK[have] >= _LEVEL_RANK[required]


def effective_feature_level(
    role: UserRole, overrides: dict[str, AccessLevel], feature_key: str
) -> AccessLevel:
    """Resolve a user's access to ``feature_key``.

    Owner is all-on (``full``). Otherwise a per-user override wins; with no
    override the feature is ``off`` (access is granted explicitly, never implied).
    A ``client`` has no grants, so it always resolves to ``off``.
    """
    if role == "owner":
        return "full"
    return overrides.get(feature_key, "off")


def feature_allows(
    role: UserRole,
    overrides: dict[str, AccessLevel],
    feature_key: str,
    required: AccessLevel = "full",
) -> bool:
    """Whether the user's effective access to ``feature_key`` meets ``required``."""
    return level_satisfies(effective_feature_level(role, overrides, feature_key), required)
