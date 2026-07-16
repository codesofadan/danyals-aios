"""Client-onboarding request/response models - SERVER-AUTHORITATIVE.

No ``frontend/lib/*.ts`` type mirrors this module, so these shapes are owned here
(unlike the contract-locked Part-2/7 responses). The module's own unit tests freeze
the emitted key set + the status enum tuples, so a drift is still caught - this is
the server-authoritative equivalent of the contract lock.

Python attributes stay snake_case; a multi-word wire key re-aliases to camelCase via
``serialization_alias`` (ruff N815 forbids a raw camelCase attribute). The internal
``client_id`` NEVER leaks: ``client`` is the snapshotted display name.

THE ONE INVARIANT WORTH STATING TWICE: ``StepCredential.secret`` is WRITE-ONLY. It
appears on exactly one REQUEST model and on NO response model anywhere in this file.
A collected credential is sealed into the key vault and the step keeps only the
opaque ``vault_secret_id``; there is no field, on any model here, that could carry
it back out. Reveal remains owner-only, through the vault router, exactly as before
this module existed. ``secret`` is typed ``SecretStr`` so that even an accidental
log/repr/traceback of the request body renders ``**********`` rather than the
credential (matching ``VaultKeyCreate``).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.util.timefmt import format_date

# The run + step status labels - verbatim from the 0040 enums.
RunStatus = Literal["in_progress", "on_hold", "completed", "archived"]
StepStatus = Literal["pending", "in_progress", "blocked", "completed", "skipped"]

RUN_STATUSES: tuple[RunStatus, ...] = ("in_progress", "on_hold", "completed", "archived")
STEP_STATUSES: tuple[StepStatus, ...] = (
    "pending", "in_progress", "blocked", "completed", "skipped",
)

_RUN_STATUSES: frozenset[str] = frozenset(RUN_STATUSES)
_STEP_STATUSES: frozenset[str] = frozenset(STEP_STATUSES)

# Weight each step status carries toward a run's % progress. Mirrors the milestones
# module's STAGE_WEIGHT (``app/schemas/milestones.py``) so the two progress bars in
# the product read on the same scale. A 'skipped' step weighs 0 like 'pending': it
# is deliberately NOT counted as done, because a skipped step was never delivered.
STEP_WEIGHT: dict[str, float] = {
    "completed": 1.0, "in_progress": 0.5, "blocked": 0.25, "pending": 0.0, "skipped": 0.0,
}


class OnboardingStepResponse(BaseModel):
    """One checklist step. ``client`` is the snapshotted display name (the internal
    ``client_id`` never leaks); ``owner`` is the ``owner_name`` snapshot.

    ``verified`` is the access-test flag: ``true`` ONLY once a human confirmed the
    collected login actually works. ``has_credential`` reports merely that a sealed
    credential EXISTS for this step (derived from ``vault_secret_id``) - it is a
    boolean, never the reference and never the secret, so the response cannot even
    name the vault row, let alone open it."""

    id: str
    step_key: str = Field(serialization_alias="stepKey")
    label: str
    client: str
    status: StepStatus
    owner: str
    owner_init: str = Field(serialization_alias="ownerInit")
    owner_color: str = Field(serialization_alias="ownerColor")
    due: str
    notes: str
    verified: bool
    has_credential: bool = Field(serialization_alias="hasCredential")
    sort_order: int = Field(serialization_alias="sortOrder")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> OnboardingStepResponse:
        status = row.get("status")
        return cls(
            id=str(row.get("id", "")),
            step_key=str(row.get("step_key", "") or ""),
            label=str(row.get("label", "") or ""),
            client=str(row.get("client_name", "") or ""),
            status=status if status in _STEP_STATUSES else "pending",
            owner=str(row.get("owner_name", "") or ""),
            owner_init=str(row.get("owner_init", "") or ""),
            owner_color=str(row.get("owner_color", "") or ""),
            due=format_date(row.get("due_date")),
            notes=str(row.get("notes", "") or ""),
            verified=bool(row.get("verified")),
            # Presence only - never the id itself.
            has_credential=row.get("vault_secret_id") is not None,
            sort_order=int(row.get("sort_order", 0) or 0),
        )


class OnboardingRunResponse(BaseModel):
    """One activation run. ``client`` is the snapshot display name (the internal
    ``client_id`` never leaks); ``step`` is the DERIVED current step's label (see
    ``service.current_step``); ``progress`` is the weighted % completion.

    ``steps`` is the full ordered checklist and is populated only by the detail
    route - a list response leaves it empty rather than fanning out a query per run."""

    id: str
    client: str
    template: str
    status: RunStatus
    owner: str
    step: str
    step_status: StepStatus = Field(serialization_alias="stepStatus")
    progress: int
    target: str
    steps: list[OnboardingStepResponse] = Field(default_factory=list)

    @classmethod
    def from_rows(
        cls,
        run: dict[str, Any],
        step_rows: list[dict[str, Any]],
        *,
        include_steps: bool = False,
    ) -> OnboardingRunResponse:
        # Imported here (not at module import) purely to keep the schema layer free
        # of a hard dependency on the service layer's import graph.
        from app.modules.client_onboarding.service import current_step, run_progress

        steps = [OnboardingStepResponse.from_row(r) for r in step_rows]
        status = run.get("status")
        current = current_step(steps)
        return cls(
            id=str(run.get("id", "")),
            client=str(run.get("client_name", "") or ""),
            template=str(run.get("template_key", "") or ""),
            status=status if status in _RUN_STATUSES else "in_progress",
            owner=str(run.get("owner_name", "") or ""),
            step=current.label if current is not None else "",
            step_status=current.status if current is not None else "pending",
            progress=run_progress(steps),
            target=format_date(run.get("target_date")),
            steps=steps if include_steps else [],
        )


class OnboardingStats(BaseModel):
    """The onboarding summary tiles: how many clients are mid-activation, how many
    checklist steps are still outstanding, and how many runs finished in the last 30
    days (the throughput signal - a big ``in_onboarding`` next to a small
    ``completed_30d`` is a stalled pipeline, which is exactly the thing this module
    exists to surface)."""

    in_onboarding: int = Field(serialization_alias="inOnboarding")
    steps_pending: int = Field(serialization_alias="stepsPending")
    completed_30d: int = Field(serialization_alias="completed30d")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> OnboardingStats:
        return cls(
            in_onboarding=int(row.get("in_onboarding", 0) or 0),
            steps_pending=int(row.get("steps_pending", 0) or 0),
            completed_30d=int(row.get("completed_30d", 0) or 0),
        )


# --- Request models -----------------------------------------------------------


class OnboardingRunCreate(BaseModel):
    """POST /client-onboarding/runs body: start an activation for a client.

    The run is seeded from the versioned CODE template (``constants.py``) - the body
    picks WHICH template, never the steps themselves, so a caller cannot invent a
    checklist that skips the access collection. ``client_id`` is server-resolved to a
    display snapshot (404 if unknown/invisible); ``owner_user_id`` likewise resolves
    to an ``owner_name`` snapshot. One LIVE run per client (the 0040 partial unique
    index); a second attempt is a clean 409."""

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(alias="clientId", min_length=1)
    template_key: str | None = Field(default=None, alias="templateKey")
    owner_user_id: str | None = Field(default=None, alias="ownerUserId")
    target_date: date | None = Field(default=None, alias="targetDate")


class StepCredential(BaseModel):
    """The credential a ``collect_*`` step may carry when it is advanced.

    WRITE-ONLY, and structurally so: this model appears on request bodies only, and
    nothing in this module ever constructs a response from it. ``secret`` is sealed
    into the key vault (``kind='client_access'``) and the step keeps ONLY the
    returned reference - the plaintext is never persisted on the step, never
    returned, and never logged.

    ``label`` is what a human will see in the vault list (e.g. "GBP manager login"),
    so it must never itself contain the secret; that is a human contract this model
    cannot enforce, which is precisely why the vault stores a MASKED preview of the
    secret separately rather than trusting the label."""

    model_config = ConfigDict(populate_by_name=True)

    credential_label: str = Field(alias="credentialLabel", min_length=1, max_length=120)
    secret: SecretStr = Field(min_length=1)


class OnboardingStepUpdate(BaseModel):
    """PATCH/advance body for ONE step: only the provided fields change.

    ``status`` moves the step; ``owner_user_id`` (re)assigns it (the display fields
    are re-snapshotted server-side); ``due_date``/``notes`` are the working fields.

    ``credential`` seals a ``collect_*`` step's login into the vault - it is accepted
    ONLY for a ``collect_*`` step (else 400).

    ``verified`` is the access-test confirmation and is deliberately SEPARATE from
    ``credential``: passing a credential collects it, passing ``verified: true``
    asserts a human has actually signed into it. Collecting can never imply
    verifying - "test every login" is the rule this separation encodes."""

    model_config = ConfigDict(populate_by_name=True)

    status: StepStatus | None = None
    owner_user_id: str | None = Field(default=None, alias="ownerUserId")
    due_date: date | None = Field(default=None, alias="dueDate")
    notes: str | None = None
    verified: bool | None = None
    credential: StepCredential | None = None


class OnboardingRunComplete(BaseModel):
    """POST /client-onboarding/runs/{id}/complete body: finish an activation.

    ``force`` completes a run whose checklist is not fully resolved. It defaults to
    False so the honest default is "you cannot mark an activation done while access
    is still outstanding" - the whole point of the module - while leaving a lead an
    explicit, deliberate override for the real case where a step will never land."""

    model_config = ConfigDict(populate_by_name=True)

    force: bool = False
