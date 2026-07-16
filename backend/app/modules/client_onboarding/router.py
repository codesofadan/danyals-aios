"""Client-onboarding endpoints (Part 8 Phase 2F): the staff-only ACTIVATION checklist.

No ``frontend/lib/*.ts`` type mirrors this module - the responses are
SERVER-AUTHORITATIVE (``schemas.py`` owns the shape + its own shape/enum tests). The
``GET /client-onboarding/workspace`` adapter emits the ``lib/tools.ts``
``client_onboarding`` EXTRA shape (KPIs + the run board + the CTA), with table
columns pinned to ``tests/test_tool_workspace_contract.py``.

Tables owned: ``onboarding_runs`` / ``onboarding_steps`` (migration
``0040_client_onboarding``); it also puts rows in ``vault_keys`` with
``kind='client_access'`` (migration ``0041_vault_kind``). Cost-gate dial: NONE - this
module makes no provider call and spends nothing.

Access: every route requires the ``client_onboarding`` FEATURE grant. Reads add
``view_reports``; every mutation adds ``manage_clients`` (owner/admin/manager) -
which lines up with the ``0040`` RLS insert/update policies byte-for-byte, so a
caller who passes the app gate is never rejected by Postgres with an opaque RLS
error instead of a clean 403.

The internal ``client_id`` never leaks (``client`` is the snapshotted name), and a
collected ``secret`` is WRITE-ONLY: it is sealed into the vault and the step keeps
only the reference, so no response on this router can carry it. Every mutation
offloads the blocking psycopg call with ``asyncio.to_thread`` and records an activity
entry (kind=client, entity=client) so the activation keeps each client's context
fresh.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_feature, require_perm
from app.core.pagination import PageDep
from app.modules.client_onboarding.constants import DEFAULT_TEMPLATE_KEY, is_collect_step
from app.modules.client_onboarding.repo import OnboardingRepoDep
from app.modules.client_onboarding.schemas import (
    OnboardingRunComplete,
    OnboardingRunCreate,
    OnboardingRunResponse,
    OnboardingStats,
    OnboardingStepResponse,
    OnboardingStepUpdate,
    RunStatus,
    StepStatus,
)
from app.modules.client_onboarding.service import (
    advance_onboarding_milestone,
    build_workspace,
    seal_step_credential,
    seed_run,
    unresolved_steps,
)
from app.schemas.tool_workspace import ToolExtraResponse
from app.services.activity import record_activity

router = APIRouter(tags=["client-onboarding"])

# Every tool route requires the fine-grained client_onboarding feature grant (owner
# is all-on). Reads additionally require view_reports; every mutation requires
# manage_clients - the same leads (owner/admin/manager) the 0040 RLS write policies
# name.
Feature = Annotated[CurrentUser, Depends(require_feature("client_onboarding"))]
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
ManageClients = Annotated[CurrentUser, Depends(require_perm("manage_clients"))]

_RUN_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
_STEP_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Step not found")
_CLIENT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
)
_OWNER_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Owner must be a staff user"
)
_NOTHING_TO_UPDATE = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update"
)
_ALREADY_ONBOARDING = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="Client already has an active onboarding run"
)
_NOT_A_COLLECT_STEP = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="Only a collect_* step may carry a credential",
)


def _incomplete(labels: list[str]) -> HTTPException:
    """422 naming what is still outstanding - a lead who meant it passes ``force``."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Onboarding still has unresolved steps: {', '.join(labels)}",
    )


# The two side-effecting seams, injected as dependencies (mirrors the keyword-research
# module's ``get_research_enqueuer``) so a test can observe them without reaching into
# the module - and, more to the point, so a unit test NEVER needs a real master key or
# a real vault to exercise the credential path.
def get_credential_sealer() -> Callable[..., str]:
    """Dependency: the vault seal for a collected credential (overridable in tests)."""
    return seal_step_credential


def get_milestone_advancer() -> Callable[[str, str], bool]:
    """Dependency: the milestone hand-off (overridable in tests). Already best-effort
    at the service layer - it swallows and logs its own failures."""
    return advance_onboarding_milestone


CredentialSealerDep = Annotated[Callable[..., str], Depends(get_credential_sealer)]
MilestoneAdvancerDep = Annotated[Callable[[str, str], bool], Depends(get_milestone_advancer)]


# --- reads --------------------------------------------------------------------


@router.get("/client-onboarding/runs", response_model=list[OnboardingRunResponse])
async def list_runs(
    repo: OnboardingRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
    run_status: Annotated[RunStatus | None, Query(alias="status")] = None,
) -> list[OnboardingRunResponse]:
    """The activation board (newest first), optionally narrowed to one status.

    Each run carries its derived current step + progress. The checklists are fetched
    for the whole page in ONE round-trip (mirrors the milestones board: list, then
    ``steps_for_runs``) - a per-run fan-out would be an N+1. The full ``steps`` array
    is still left to the detail route: deriving the current step needs the checklist,
    but SHIPPING 11 steps x 50 runs to render a board does not."""
    rows = await asyncio.to_thread(
        repo.list_runs, status=run_status, limit=page.limit, offset=page.offset
    )
    step_rows = await asyncio.to_thread(repo.steps_for_runs, [str(r["id"]) for r in rows])
    by_run: dict[str, list[dict[str, Any]]] = {}
    for step in step_rows:
        by_run.setdefault(str(step.get("run_id", "")), []).append(step)
    return [
        OnboardingRunResponse.from_rows(r, by_run.get(str(r["id"]), [])) for r in rows
    ]


@router.get("/client-onboarding/stats", response_model=OnboardingStats)
async def onboarding_stats(
    repo: OnboardingRepoDep, _feat: Feature, _user: ViewReports
) -> OnboardingStats:
    """The summary tiles: clients mid-activation, outstanding steps, 30-day throughput."""
    row = await asyncio.to_thread(repo.onboarding_stats)
    return OnboardingStats.from_row(row)


@router.get("/client-onboarding/workspace", response_model=ToolExtraResponse)
async def onboarding_workspace(
    repo: OnboardingRepoDep, _feat: Feature, _user: ViewReports
) -> ToolExtraResponse:
    """The tool workspace (``lib/tools.ts`` ``client_onboarding`` shape): KPI tiles,
    the live-run board (cols ``Client|Step|Owner|Status``), and the CTA."""
    stats_row = await asyncio.to_thread(repo.onboarding_stats)
    live = await asyncio.to_thread(repo.live_run_steps)
    return build_workspace(OnboardingStats.from_row(stats_row), live)


@router.get("/client-onboarding/steps", response_model=list[OnboardingStepResponse])
async def list_steps(
    repo: OnboardingRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
    step_status: Annotated[StepStatus | None, Query(alias="status")] = None,
) -> list[OnboardingStepResponse]:
    """The cross-client STEP BOARD, optionally filtered by status (e.g. everything
    still ``pending``) - the "what is outstanding across every client" view."""
    rows = await asyncio.to_thread(
        repo.list_board, status=step_status, limit=page.limit, offset=page.offset
    )
    return [OnboardingStepResponse.from_row(r) for r in rows]


@router.get("/client-onboarding/runs/{run_id}", response_model=OnboardingRunResponse)
async def get_run(
    run_id: str, repo: OnboardingRepoDep, _feat: Feature, _user: ViewReports
) -> OnboardingRunResponse:
    """One run + its FULL checklist in template order."""
    run = await asyncio.to_thread(repo.get_run, run_id)
    if run is None:
        raise _RUN_NOT_FOUND
    steps = await asyncio.to_thread(repo.list_steps, run_id)
    return OnboardingRunResponse.from_rows(run, steps, include_steps=True)


# --- mutations ----------------------------------------------------------------


@router.post(
    "/client-onboarding/runs",
    response_model=OnboardingRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_run(
    body: OnboardingRunCreate, repo: OnboardingRepoDep, _feat: Feature, actor: ManageClients
) -> OnboardingRunResponse:
    """Start an activation for a client and SEED the 11-step template (manage_clients).

    The client name (404 if unknown/invisible) and the owner (404 unless staff) are
    snapshotted server-side. One live run per client: a second attempt is a 409, not
    a duplicate checklist."""
    client_name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if client_name is None:
        raise _CLIENT_NOT_FOUND

    owner_id, owner_name = actor.id, actor.name
    if body.owner_user_id is not None:
        staff = await asyncio.to_thread(repo.staff_for, body.owner_user_id)
        if staff is None:
            raise _OWNER_NOT_FOUND
        owner_id, owner_name = body.owner_user_id, str(staff.get("name", ""))

    if await asyncio.to_thread(repo.active_run_for, body.client_id) is not None:
        raise _ALREADY_ONBOARDING

    template_key = body.template_key or DEFAULT_TEMPLATE_KEY
    run = await asyncio.to_thread(
        repo.insert_run,
        client_id=body.client_id,
        client_name=client_name,
        template_key=template_key,
        owner_user_id=owner_id,
        owner_name=owner_name,
        target_date=body.target_date,
    )
    if run is None:  # the 0040 partial unique index won a race the check above lost
        raise _ALREADY_ONBOARDING

    steps = await asyncio.to_thread(
        seed_run, repo, str(run["id"]), body.client_id, client_name, template_key
    )
    await record_activity(
        actor, kind="client", action="started onboarding", target=client_name,
        entity_type="client", entity_id=body.client_id,
    )
    return OnboardingRunResponse.from_rows(run, steps, include_steps=True)


async def _apply_step_update(
    run_id: str,
    step_id: str,
    body: OnboardingStepUpdate,
    repo: OnboardingRepoDep,
    actor: CurrentUser,
    seal: Callable[..., str],
) -> OnboardingStepResponse:
    """The shared write path behind PATCH and /advance (they differ in intent, not in
    mechanics - so the security-bearing logic exists exactly once).

    A credential is sealed into the VAULT and only its reference reaches the step
    row; ``verified`` moves only when the caller explicitly says so."""
    existing = await asyncio.to_thread(repo.get_step, run_id, step_id)
    if existing is None:
        raise _STEP_NOT_FOUND

    provided = body.model_dump(exclude_unset=True)
    if not provided:
        raise _NOTHING_TO_UPDATE

    changes: dict[str, Any] = {}
    if body.status is not None:
        changes["status"] = body.status
        # Stamp/clear the completion time with the status, so "when did this land?"
        # never has to be inferred from updated_at (which any later edit moves).
        changes["completed_at"] = datetime.now(UTC) if body.status == "completed" else None
    if "owner_user_id" in provided:
        if body.owner_user_id is None:  # explicit unassign
            changes.update(
                {"owner_user_id": None, "owner_name": "", "owner_init": "", "owner_color": ""}
            )
        else:
            staff = await asyncio.to_thread(repo.staff_for, body.owner_user_id)
            if staff is None:
                raise _OWNER_NOT_FOUND
            from app.util.text import initials

            name = str(staff.get("name", ""))
            changes.update({
                "owner_user_id": body.owner_user_id,
                "owner_name": name,
                "owner_init": initials(name),
                "owner_color": str(staff.get("avatar_color", "")),
            })
    if "due_date" in provided:
        changes["due_date"] = body.due_date
    if "notes" in provided:
        changes["notes"] = body.notes or ""
    if body.verified is not None:
        # ONLY an explicit confirmation moves this flag. Nothing else in this module
        # writes it - a collected credential stays unverified until a human signs in.
        changes["verified"] = body.verified
    if body.credential is not None:
        step_key = str(existing.get("step_key", ""))
        if not is_collect_step(step_key):
            raise _NOT_A_COLLECT_STEP
        # The plaintext ends its life inside the vault seal; only the id comes back.
        changes["vault_secret_id"] = await asyncio.to_thread(
            seal,
            step_key=step_key,
            credential_label=body.credential.credential_label,
            secret=body.credential.secret.get_secret_value(),
            created_by=actor.id,
        )

    if not changes:
        raise _NOTHING_TO_UPDATE

    row = await asyncio.to_thread(repo.update_step, run_id, step_id, changes)
    if row is None:
        raise _STEP_NOT_FOUND

    client_id = str(existing.get("client_id") or "") or None
    await record_activity(
        actor, kind="client", action=f"updated onboarding step '{existing.get('label', '')}'",
        target=str(existing.get("client_name", "")),
        entity_type="client" if client_id else None, entity_id=client_id,
    )
    return OnboardingStepResponse.from_row(row)


@router.post(
    "/client-onboarding/runs/{run_id}/steps/{step_id}/advance",
    response_model=OnboardingStepResponse,
)
async def advance_step(
    run_id: str,
    step_id: str,
    body: OnboardingStepUpdate,
    repo: OnboardingRepoDep,
    seal: CredentialSealerDep,
    _feat: Feature,
    actor: ManageClients,
) -> OnboardingStepResponse:
    """Advance ONE step (manage_clients), optionally SEALING a collected credential.

    A ``collect_*`` step advanced with ``credential`` seals it into the key vault
    (``kind='client_access'``) and stores only the returned reference - the secret is
    never echoed back and never lands on the step row. ``verified`` stays FALSE
    unless the body explicitly confirms an access test: collecting a login is not
    testing it."""
    return await _apply_step_update(run_id, step_id, body, repo, actor, seal)


@router.patch(
    "/client-onboarding/runs/{run_id}/steps/{step_id}",
    response_model=OnboardingStepResponse,
)
async def update_step(
    run_id: str,
    step_id: str,
    body: OnboardingStepUpdate,
    repo: OnboardingRepoDep,
    seal: CredentialSealerDep,
    _feat: Feature,
    actor: ManageClients,
) -> OnboardingStepResponse:
    """Edit ONE step (manage_clients): reassign the owner, set a due date, add notes,
    move the status, or confirm the access test. 404 for an unknown step (or one
    belonging to another run); 400 if nothing was provided."""
    return await _apply_step_update(run_id, step_id, body, repo, actor, seal)


@router.post("/client-onboarding/runs/{run_id}/complete", response_model=OnboardingRunResponse)
async def complete_run(
    run_id: str,
    body: OnboardingRunComplete,
    repo: OnboardingRepoDep,
    advance: MilestoneAdvancerDep,
    _feat: Feature,
    actor: ManageClients,
) -> OnboardingRunResponse:
    """Finish an activation (manage_clients) and hand off to the delivery lifecycle.

    Refuses (422) while steps are unresolved unless ``force`` - "onboarded" must mean
    the access is actually in hand. On success it stamps ``completed_at`` and
    BEST-EFFORT advances the client's milestone ``onboarding`` -> ``baseline``
    (``auto_source='onboarding_complete'``); a milestone hiccup is logged and
    swallowed - it can never undo a completion that already happened."""
    run = await asyncio.to_thread(repo.get_run, run_id)
    if run is None:
        raise _RUN_NOT_FOUND

    steps = await asyncio.to_thread(repo.list_steps, run_id)
    if not body.force:
        outstanding = unresolved_steps(steps)
        if outstanding:
            raise _incomplete(outstanding)

    updated = await asyncio.to_thread(
        repo.update_run, run_id, {"status": "completed", "completed_at": datetime.now(UTC)}
    )
    if updated is None:
        raise _RUN_NOT_FOUND

    client_id = str(run.get("client_id") or "") or None
    if client_id is not None:
        # Best-effort by construction (the service swallows + logs its own failures).
        await asyncio.to_thread(advance, actor.id, client_id)
    await record_activity(
        actor, kind="client", action="completed onboarding",
        target=str(run.get("client_name", "")),
        entity_type="client" if client_id else None, entity_id=client_id,
    )
    fresh = await asyncio.to_thread(repo.list_steps, run_id)
    return OnboardingRunResponse.from_rows(updated, fresh, include_steps=True)
