"""Client-onboarding wire shapes: the frozen key sets + the enum tuples.

These models are SERVER-AUTHORITATIVE (no ``lib/*.ts`` type mirrors them), so this
file IS their contract lock: it freezes the emitted key set of every response model
and the two status tuples against the 0040 enums.

The load-bearing assertion in here is the LAST section: ``secret`` is WRITE-ONLY. It
is asserted structurally - swept over EVERY response model in the module rather than
spot-checked on one - because a single new field on a single model is all it would
take to start handing client credentials back out over the wire.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from app.modules.client_onboarding.schemas import (
    RUN_STATUSES,
    STEP_STATUSES,
    STEP_WEIGHT,
    OnboardingRunComplete,
    OnboardingRunCreate,
    OnboardingRunResponse,
    OnboardingStats,
    OnboardingStepResponse,
    OnboardingStepUpdate,
    StepCredential,
)

pytestmark = pytest.mark.unit

_STEP_KEYS = {
    "id", "stepKey", "label", "client", "status", "owner", "ownerInit", "ownerColor",
    "due", "notes", "verified", "hasCredential", "sortOrder",
}
_RUN_KEYS = {
    "id", "client", "template", "status", "owner", "step", "stepStatus", "progress",
    "target", "steps",
}
_STATS_KEYS = {"inOnboarding", "stepsPending", "completed30d"}

# Every RESPONSE model this module can put on the wire. The write-only sweep below
# is parametrized over this list, so a new response model is covered the moment it
# is added here - and a new response model that is NOT added here is the one gap
# this file cannot close, which is why the sweep also walks nested models.
_RESPONSE_MODELS: list[type[BaseModel]] = [
    OnboardingStepResponse,
    OnboardingRunResponse,
    OnboardingStats,
]


def _step_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "st-1", "run_id": "run-1", "client_id": "cl-secret",
        "client_name": "Orchard Pediatrics", "step_key": "collect_gbp",
        "label": "Collect GBP access", "status": "pending", "owner_user_id": "u-1",
        "owner_name": "Sara Khan", "owner_init": "SK", "owner_color": "#7B69EE",
        "due_date": date(2026, 8, 14), "notes": "", "verified": False,
        "vault_secret_id": None, "sort_order": 2,
    }
    row.update(over)
    return row


def _run_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "run-1", "client_id": "cl-secret", "client_name": "Orchard Pediatrics",
        "template_key": "local_seo_default", "status": "in_progress",
        "owner_user_id": "u-1", "owner_name": "Sara Khan",
        "target_date": date(2026, 9, 1), "completed_at": None,
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# 1. Frozen key sets.
# --------------------------------------------------------------------------- #
def test_step_response_emits_exactly_the_frozen_key_set() -> None:
    body = OnboardingStepResponse.from_row(_step_row()).model_dump(by_alias=True)
    assert set(body) == _STEP_KEYS


def test_run_response_emits_exactly_the_frozen_key_set() -> None:
    body = OnboardingRunResponse.from_rows(_run_row(), [_step_row()]).model_dump(by_alias=True)
    assert set(body) == _RUN_KEYS


def test_stats_emits_exactly_the_frozen_key_set() -> None:
    body = OnboardingStats.from_row(
        {"in_onboarding": 3, "steps_pending": 7, "completed_30d": 12}
    ).model_dump(by_alias=True)
    assert set(body) == _STATS_KEYS
    assert body == {"inOnboarding": 3, "stepsPending": 7, "completed30d": 12}


# --------------------------------------------------------------------------- #
# 2. The enum tuples (pinned to the 0040 enums).
# --------------------------------------------------------------------------- #
def test_status_tuples_match_the_migration_enums() -> None:
    assert RUN_STATUSES == ("in_progress", "on_hold", "completed", "archived")
    assert STEP_STATUSES == ("pending", "in_progress", "blocked", "completed", "skipped")


def test_step_weight_covers_every_step_status() -> None:
    # A status with no weight would silently count as 0 and quietly deflate progress.
    assert set(STEP_WEIGHT) == set(STEP_STATUSES)


def test_skipped_weighs_zero_not_one() -> None:
    """A skipped step was never delivered, so it must not read as done. (It IS
    'resolved' for the purpose of completing a run - a different question, answered
    by ``unresolved_steps``.)"""
    assert STEP_WEIGHT["skipped"] == 0.0
    assert STEP_WEIGHT["completed"] == 1.0


def test_step_weights_mirror_the_milestones_stage_weights() -> None:
    """Onboarding is the FIRST stage of the very same engagement lifecycle, so the
    two progress bars must read on ONE scale. A drift here would mean 'in progress'
    meant something different on two screens of the same product."""
    from app.schemas.milestones import STAGE_WEIGHT

    for shared in ("completed", "in_progress", "blocked"):
        assert STEP_WEIGHT[shared] == STAGE_WEIGHT[shared]
    # The names differ where the domains genuinely differ (pending vs upcoming).
    assert STEP_WEIGHT["pending"] == STAGE_WEIGHT["upcoming"] == 0.0


@pytest.mark.parametrize("bogus", ["done", "", "Pending", "cancelled"])
def test_an_off_enum_row_status_degrades_to_pending_not_a_crash(bogus: str) -> None:
    # A row can only carry an off-enum status if the DB enum drifted; the response
    # must stay renderable rather than 500 the whole board.
    assert OnboardingStepResponse.from_row(_step_row(status=bogus)).status == "pending"


def test_an_off_enum_run_status_degrades_to_in_progress() -> None:
    assert OnboardingRunResponse.from_rows(_run_row(status="bogus"), []).status == "in_progress"


# --------------------------------------------------------------------------- #
# 3. The client_id never leaks; the snapshot replaces it.
# --------------------------------------------------------------------------- #
def test_no_response_model_carries_the_internal_client_id() -> None:
    step = OnboardingStepResponse.from_row(_step_row()).model_dump_json(by_alias=True)
    run = OnboardingRunResponse.from_rows(
        _run_row(), [_step_row()], include_steps=True
    ).model_dump_json(by_alias=True)
    for body in (step, run):
        assert "cl-secret" not in body  # not the value...
        assert "client_id" not in body and "clientId" not in body  # ...nor the key
    # The other half of the contract: hiding the id must not mean showing nothing.
    assert "Orchard Pediatrics" in step and "Orchard Pediatrics" in run


# --------------------------------------------------------------------------- #
# 4. The step's credential is a PRESENCE flag, never the reference.
# --------------------------------------------------------------------------- #
def test_has_credential_is_a_boolean_and_never_exposes_the_vault_reference() -> None:
    """A step that HAS a sealed credential says only that. Emitting the
    vault_secret_id would hand every staff reader the exact row id to go asking the
    vault about - a needless step toward the secret for zero product value."""
    row = _step_row(vault_secret_id="vk-9f2a4c7b")
    body = OnboardingStepResponse.from_row(row).model_dump(by_alias=True)
    assert body["hasCredential"] is True
    assert "vk-9f2a4c7b" not in OnboardingStepResponse.from_row(row).model_dump_json(
        by_alias=True
    )
    assert "vaultSecretId" not in body and "vault_secret_id" not in body


def test_has_credential_is_false_without_a_seal() -> None:
    assert OnboardingStepResponse.from_row(_step_row()).has_credential is False


def test_verified_defaults_false_on_a_row_that_does_not_carry_it() -> None:
    # The honest answer to "has anyone tested this login?" is no, by default.
    row = _step_row()
    row.pop("verified")
    assert OnboardingStepResponse.from_row(row).verified is False


# --------------------------------------------------------------------------- #
# 5. THE INVARIANT: ``secret`` is WRITE-ONLY.
# --------------------------------------------------------------------------- #
def _all_field_names(model: type[BaseModel], seen: set[type] | None = None) -> set[str]:
    """Every field name of ``model``, walking nested models too - a secret hidden one
    level down (``{"credential": {"secret": ...}}``) is just as leaked."""
    seen = seen if seen is not None else set()
    if model in seen:
        return set()
    seen.add(model)
    names: set[str] = set()
    for name, field in model.model_fields.items():
        names.add(name)
        annotation = field.annotation
        for candidate in (annotation, *getattr(annotation, "__args__", ())):
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                names |= _all_field_names(candidate, seen)
    return names


@pytest.mark.parametrize("model", _RESPONSE_MODELS, ids=lambda m: m.__name__)
def test_no_response_model_has_a_secret_field_anywhere(model: type[BaseModel]) -> None:
    """THE invariant of this module: a collected credential is sealed into the vault
    and can never come back out through onboarding. Not on the model, not nested."""
    assert "secret" not in _all_field_names(model)
    assert "credential" not in _all_field_names(model)


def test_the_only_secret_bearing_model_is_a_request_model() -> None:
    # StepCredential is the one place `secret` exists at all, and it is a REQUEST
    # body. Nothing in the module constructs a response from it.
    assert "secret" in StepCredential.model_fields
    assert "secret" in _all_field_names(OnboardingStepUpdate)  # via `credential`
    for response_model in _RESPONSE_MODELS:
        assert "secret" not in _all_field_names(response_model)


def test_secret_is_a_secretstr_so_a_stray_log_or_repr_cannot_spill_it() -> None:
    """Defense in depth behind "never log it": even if a traceback or a debug log
    renders the request body, SecretStr prints a mask rather than the credential."""
    body = OnboardingStepUpdate(
        credential=StepCredential(credential_label="GBP manager login", secret="hunter2-real")
    )
    assert "hunter2-real" not in repr(body)
    assert "hunter2-real" not in str(body)
    assert isinstance(body.credential is not None and body.credential.secret, SecretStr)
    # ... and it is still retrievable server-side, deliberately and explicitly.
    assert body.credential is not None
    assert body.credential.secret.get_secret_value() == "hunter2-real"


def test_a_dumped_step_update_does_not_render_the_secret() -> None:
    body = OnboardingStepUpdate(
        status="completed",
        credential=StepCredential(credential_label="CMS admin", secret="p@ssw0rd"),
    )
    assert "p@ssw0rd" not in body.model_dump_json()


# --------------------------------------------------------------------------- #
# 6. Request-model validation.
# --------------------------------------------------------------------------- #
def test_run_create_accepts_camel_case_aliases() -> None:
    body = OnboardingRunCreate.model_validate(
        {"clientId": "cl-1", "templateKey": "local_seo_default",
         "ownerUserId": "u-2", "targetDate": "2026-09-01"}
    )
    assert body.client_id == "cl-1"
    assert body.owner_user_id == "u-2"
    assert body.target_date == date(2026, 9, 1)


def test_run_create_requires_a_client() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OnboardingRunCreate.model_validate({})
    with pytest.raises(ValidationError):
        OnboardingRunCreate.model_validate({"clientId": ""})  # min_length=1


def test_credential_requires_both_a_label_and_a_secret() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StepCredential.model_validate({"credentialLabel": "GBP"})
    with pytest.raises(ValidationError):
        StepCredential.model_validate({"secret": "x"})
    with pytest.raises(ValidationError):
        StepCredential.model_validate({"credentialLabel": "", "secret": "x"})


def test_step_update_defaults_are_all_unset_so_a_patch_changes_nothing_by_accident() -> None:
    body = OnboardingStepUpdate()
    assert body.model_dump(exclude_unset=True) == {}


def test_complete_defaults_to_not_forcing() -> None:
    # The honest default: you cannot mark an activation done while access is missing.
    assert OnboardingRunComplete().force is False


# --------------------------------------------------------------------------- #
# 7. Run response derivations.
# --------------------------------------------------------------------------- #
def test_run_response_derives_the_current_step_and_progress() -> None:
    steps = [
        _step_row(id="s1", step_key="kickoff", label="Kickoff call & goals",
                  status="completed", sort_order=1),
        _step_row(id="s2", step_key="collect_gbp", label="Collect GBP access",
                  status="in_progress", sort_order=2),
    ]
    run = OnboardingRunResponse.from_rows(_run_row(), steps)
    assert run.step == "Collect GBP access"  # the derived current step's LABEL
    assert run.step_status == "in_progress"
    assert run.progress == 75  # (1.0 + 0.5) / 2


def test_run_response_omits_the_checklist_unless_asked() -> None:
    # A list response must not fan out a query per run; the detail route opts in.
    assert OnboardingRunResponse.from_rows(_run_row(), [_step_row()]).steps == []
    detailed = OnboardingRunResponse.from_rows(_run_row(), [_step_row()], include_steps=True)
    assert len(detailed.steps) == 1


def test_run_with_no_steps_is_zero_percent_not_complete() -> None:
    """An unseeded run is 0%, never 100%: reporting an empty checklist as complete
    would hide exactly the failure (a seed that never ran) worth surfacing."""
    run = OnboardingRunResponse.from_rows(_run_row(), [])
    assert run.progress == 0
    assert run.step == "" and run.step_status == "pending"


def test_dates_render_in_the_frontend_calendar_format() -> None:
    assert OnboardingStepResponse.from_row(_step_row()).due == "Aug 14, 2026"
    assert OnboardingRunResponse.from_rows(_run_row(), []).target == "Sep 01, 2026"


def test_an_unset_date_renders_the_em_dash() -> None:
    assert OnboardingStepResponse.from_row(_step_row(due_date=None)).due == "—"
    assert OnboardingRunResponse.from_rows(_run_row(target_date=None), []).target == "—"


def test_a_datetime_completed_at_does_not_break_the_run_shape() -> None:
    run = OnboardingRunResponse.from_rows(
        _run_row(status="completed", completed_at=datetime.now(UTC)), []
    )
    assert run.status == "completed"
