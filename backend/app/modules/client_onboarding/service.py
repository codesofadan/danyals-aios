"""Client-onboarding orchestration: the template seed, the derived progress, the
credential seal, the completion hand-off, and the tool-workspace adapter.

The pure helpers (``run_progress`` / ``current_step``) are DB-free and mirror the
milestones module (``app/schemas/milestones.py`` ``project_progress`` /
``current_stage``) deliberately: onboarding is the FIRST stage of the very same
engagement lifecycle, so the two surfaces must read on one scale. Their weights live
in ``schemas.STEP_WEIGHT``, aligned with ``STAGE_WEIGHT``.

THREE THINGS IN HERE CARRY REAL WEIGHT:

* ``seal_step_credential`` - a collected credential goes to the KEY VAULT and only
  its reference comes back. The plaintext is never returned by this function, never
  stored on the step, and never logged. ``kind='client_access'`` (0041) marks it as a
  client login rather than an agency API key; ``provider`` names WHICH system it
  opens. Nothing here can read a secret back - there is no reveal path in this
  module, by construction.
* ``verified`` is never touched by the seal. Collecting a credential and PROVING it
  works are different facts, and only a human asserting the latter sets the flag
  (the "test every login" rule). This module's job is to make the honest state -
  "collected, untested" - representable and visible.
* ``complete_run`` hands off to the milestones lifecycle (``onboarding`` ->
  ``baseline``) BEST-EFFORT: the activation is finished the moment its own row says
  so, and a milestone hiccup must never undo that (mirrors ``record_activity``'s
  never-raise discipline). The alternative - failing the completion because a
  downstream timeline update failed - would leave the run in a state its own module
  knows is finished.

``build_workspace`` is the ``GET /client-onboarding/workspace`` adapter: it emits the
frontend ``lib/tools.ts`` ``client_onboarding`` EXTRA shape with table columns pinned
EXACTLY to ``["Client", "Step", "Owner", "Status"]`` (the tool-workspace contract
test asserts this byte-for-byte).
"""

from __future__ import annotations

from typing import Any, cast

from app.logging_setup import get_logger
from app.modules.client_onboarding.constants import (
    COLLECT_PREFIX,
    DEFAULT_TEMPLATE_KEY,
    template_for,
)
from app.modules.client_onboarding.repo import OnboardingRepo
from app.modules.client_onboarding.schemas import (
    STEP_WEIGHT,
    OnboardingStats,
    OnboardingStepResponse,
)
from app.schemas.tool_workspace import (
    ToolCell,
    ToolCellObj,
    ToolExtraResponse,
    ToolKpi,
    ToolPrimary,
    ToolTable,
)
from app.services.vault import add_key

logger = get_logger("app.client_onboarding")

# --- tool-workspace contract constants (pinned to lib/tools.ts client_onboarding) ---
WORKSPACE_TABLE_COLS: list[str] = ["Client", "Step", "Owner", "Status"]
_WORKSPACE_TABLE_TITLE = "Onboarding"
_WORKSPACE_TABLE_ICON = "person_add"
_WORKSPACE_PRIMARY = ToolPrimary(label="Start onboarding", icon="person_add")
_WORKSPACE_BULLETS = [
    "Run the onboarding wizard",
    "Collect access & assets",
    "Track onboarding progress",
]
_WORKSPACE_ROW_LIMIT = 8

# The step statuses that mean "not yet resolved" - what blocks an unforced complete.
_UNRESOLVED: frozenset[str] = frozenset({"pending", "in_progress", "blocked"})

# The display label + tone per step status (the tool-workspace status scale).
# 'pending' reads WARN, not mut: an uncollected access is the thing this board
# exists to nag about. 'blocked'/'skipped' fall through to mut.
_STATUS_LABEL: dict[str, str] = {
    "pending": "Pending",
    "in_progress": "In progress",
    "blocked": "Blocked",
    "completed": "Done",
    "skipped": "Skipped",
}
_STATUS_TONE: dict[str, str] = {
    "pending": "warn",
    "completed": "ok",
    "in_progress": "info",
}


# --------------------------------------------------------------------------- #
# Pure helpers (DB-free; mirrored on the milestones module).
# --------------------------------------------------------------------------- #
def run_progress(steps: list[OnboardingStepResponse]) -> int:
    """Derived % completion from the step weights, mirroring ``milestones``
    ``project_progress`` (sum of the per-status weights / step count, rounded).

    A run with no steps is 0%, NOT 100%: an empty checklist means the seed has not
    happened yet, and reporting that as complete would hide the failure."""
    if not steps:
        return 0
    total = sum(STEP_WEIGHT.get(s.status, 0.0) for s in steps)
    return round((total / len(steps)) * 100)


def current_step(steps: list[OnboardingStepResponse]) -> OnboardingStepResponse | None:
    """The step a run is currently sitting on, mirroring ``milestones``
    ``current_stage``: the first ``in_progress``/``blocked`` step, else the first
    ``pending``, else the last. ``None`` only for a run with no steps.

    Precedence matters: work actually in flight (or stuck) out-ranks the next
    untouched item, so the board points at what needs a human NOW rather than at the
    top of the list."""
    if not steps:
        return None
    for s in steps:
        if s.status in ("in_progress", "blocked"):
            return s
    for s in steps:
        if s.status == "pending":
            return s
    return steps[-1]


# --------------------------------------------------------------------------- #
# Seeding.
# --------------------------------------------------------------------------- #
def seed_run(
    repo: OnboardingRepo,
    run_id: str,
    client_id: str,
    client_name: str,
    template_key: str = DEFAULT_TEMPLATE_KEY,
) -> list[dict[str, Any]]:
    """Seed a run's checklist from the versioned CODE template. IDEMPOTENT.

    Two layers of idempotency, on purpose: this checks for existing steps first (the
    cheap, obvious guard), and the insert itself is ``on conflict (run_id, step_key)
    do nothing`` (the guard that actually holds under a race). Re-seeding a seeded
    run returns its existing steps and writes nothing."""
    existing = repo.list_steps(run_id)
    if existing:
        return existing
    steps = [
        {"step_key": t.key, "label": t.label, "sort_order": t.sort_order}
        for t in template_for(template_key)
    ]
    repo.seed_steps(
        run_id=run_id, client_id=client_id, client_name=client_name, steps=steps
    )
    # Re-read so the caller always gets the run's FULL checklist in template order -
    # including on a partial/raced seed, where the insert returns only what it wrote.
    return repo.list_steps(run_id)


def seed_onboarding_for_client(
    user_id: str, client_id: str, client_name: str, owner_user_id: str, owner_name: str
) -> str | None:
    """BEST-EFFORT: give a freshly-created client its onboarding run. Never raises.

    Hooked onto client creation so a new client cannot silently exist without an
    activation - nobody forgets onboarding, and the client shows up in the KPI from
    minute one. Runs under the CREATING lead's identity, so the 0040 RLS insert
    policy applies exactly as it would to a manual start (no BYPASSRLS anywhere).

    Never raises, by the same reasoning as ``record_activity``: the client was
    already created and acknowledged: failing that write because a convenience
    side-effect failed would be a strictly worse outcome than a missing run a lead
    can start by hand. Returns the run id, or ``None`` if anything went wrong.
    """
    try:
        repo = OnboardingRepo(user_id)
        if repo.active_run_for(client_id) is not None:
            return None  # already activating - the partial unique index's rule
        run = repo.insert_run(
            client_id=client_id,
            client_name=client_name,
            template_key=DEFAULT_TEMPLATE_KEY,
            owner_user_id=owner_user_id,
            owner_name=owner_name,
        )
        if run is None:  # the index rejected it (a concurrent create won the race)
            return None
        run_id = str(run["id"])
        seed_run(repo, run_id, client_id, client_name, DEFAULT_TEMPLATE_KEY)
    except Exception:
        # A seeding hiccup must never fail the client creation it hangs off.
        logger.warning("onboarding_seed_failed", client_id=client_id)
        return None
    return run_id


# --------------------------------------------------------------------------- #
# Credentials.
# --------------------------------------------------------------------------- #
def credential_provider(step_key: str) -> str:
    """The vault ``provider`` for a ``collect_*`` step: WHICH system the credential
    opens (``collect_gbp`` -> ``gbp``).

    Note the division of labour with ``kind`` (0041): ``kind='client_access'`` says
    WHAT SPECIES of secret this is, ``provider`` says WHAT IT OPENS. Overloading
    ``provider`` alone would have made a client's GBP login indistinguishable from
    the agency's own Google API key."""
    return step_key.removeprefix(COLLECT_PREFIX)


def seal_step_credential(
    *, step_key: str, credential_label: str, secret: str, created_by: str | None
) -> str:
    """Seal a step's collected credential into the key vault; return ONLY its id.

    The plaintext goes straight into ``app/services/vault.py``'s AES-256-GCM seal and
    is never touched again here: this function returns a reference, and the caller
    stores that reference on the step. There is no path from an onboarding step back
    to the secret - reveal stays owner-only, in the vault router, where it always was.

    Deliberately does NOT set ``verified``: sealing proves a credential was TYPED,
    not that it WORKS."""
    row = add_key(
        provider=credential_provider(step_key),
        label=credential_label,
        secret=secret,
        created_by=created_by,
        kind="client_access",
    )
    return str(row["id"])


# --------------------------------------------------------------------------- #
# Completion + the milestone hand-off.
# --------------------------------------------------------------------------- #
def advance_onboarding_milestone(user_id: str, client_id: str) -> bool:
    """BEST-EFFORT: advance the client's lifecycle ``onboarding`` -> ``baseline``.

    Reuses the milestones module's own repo + table (``project_stages``) rather than
    reimplementing the write: onboarding is that lifecycle's first stage, so
    finishing the activation is precisely the event the stage was waiting on.
    ``auto_source='onboarding_complete'`` is what the auto-advance feed shows as the
    trigger.

    Never raises: a client with no project timeline yet (or a milestones hiccup) must
    not fail a completion that has already happened. Returns whether the stages moved.
    """
    try:
        # Imported lazily so this module's import graph does not drag the milestones
        # layer into every request that merely lists a checklist.
        from app.db.milestones_repo import MilestonesRepo

        milestones = MilestonesRepo(user_id)
        project_id = milestones.project_id_for_client(client_id)
        if project_id is None:
            return False  # no timeline for this client - nothing to advance
        milestones.advance_stage(
            project_id, "onboarding", status="completed", auto_source="onboarding_complete"
        )
        milestones.advance_stage(
            project_id, "baseline", status="in_progress", auto_source="onboarding_complete"
        )
    except Exception:
        logger.warning("onboarding_milestone_advance_failed", client_id=client_id)
        return False
    return True


def unresolved_steps(steps: list[dict[str, Any]]) -> list[str]:
    """The step labels still outstanding (pending / in_progress / blocked).

    'skipped' is resolved: a lead deciding a step does not apply to this client IS a
    decision. 'blocked' is not: it is an unfinished step wearing a reason."""
    return [
        str(s.get("label") or s.get("step_key") or "")
        for s in steps
        if str(s.get("status") or "") in _UNRESOLVED
    ]


# --------------------------------------------------------------------------- #
# The /workspace adapter (frontend lib/tools.ts client_onboarding EXTRA shape).
# --------------------------------------------------------------------------- #
def _status_cell(status: str) -> ToolCellObj:
    """One toned status cell: Pending->warn, Done->ok, In progress->info, else mut."""
    return ToolCellObj(
        v=_STATUS_LABEL.get(status, status or "—"),
        tone=cast("Any", _STATUS_TONE.get(status, "mut")),
    )


def _group_by_run(step_rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group the flat live-run step rows into one ordered list per run, preserving
    the SQL order (client_name, sort_order) so the board is stable."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in step_rows:
        grouped.setdefault(str(row.get("run_id", "")), []).append(row)
    return list(grouped.values())


def _run_row(steps: list[OnboardingStepResponse]) -> list[ToolCell]:
    """One workspace table row: [Client, Step, Owner, Status] for ONE run, described
    by its CURRENT step (what needs a human now), per lib/tools.ts."""
    step = current_step(steps)
    if step is None:  # an unseeded run - shown honestly rather than hidden
        return [steps[0].client if steps else "", "—", "", _status_cell("")]
    return [step.client, step.label, step.owner, _status_cell(step.status)]


def build_workspace(
    stats: OnboardingStats, live_step_rows: list[dict[str, Any]]
) -> ToolExtraResponse:
    """Assemble the client-onboarding tool workspace (KPIs + the run board + CTA).

    KPI labels + the primary + the table columns are pinned to ``lib/tools.ts``; the
    columns are EXACTLY ``["Client", "Step", "Owner", "Status"]`` (the tool-workspace
    contract test enforces byte-identity). Each ROW is one live run, shown at its
    derived current step."""
    kpis = [
        ToolKpi(label="In onboarding", value=str(stats.in_onboarding)),
        ToolKpi(label="Steps pending", value=str(stats.steps_pending)),
        ToolKpi(label="Completed (30d)", value=str(stats.completed_30d)),
    ]
    runs = _group_by_run(live_step_rows)[:_WORKSPACE_ROW_LIMIT]
    rows = [
        _run_row([OnboardingStepResponse.from_row(r) for r in steps]) for steps in runs
    ]
    table = ToolTable(
        title=_WORKSPACE_TABLE_TITLE,
        icon=_WORKSPACE_TABLE_ICON,
        cols=list(WORKSPACE_TABLE_COLS),
        rows=rows,
    )
    return ToolExtraResponse(
        kpis=kpis, table=table, primary=_WORKSPACE_PRIMARY, bullets=list(_WORKSPACE_BULLETS)
    )
