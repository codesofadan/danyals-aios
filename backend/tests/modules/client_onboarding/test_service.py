"""Client-onboarding orchestration: the template seed, the derived progress/current
step, the credential seal, and the completion hand-off.

No DB, no network: the repo is an in-memory fake and the vault seal / milestones repo
are monkeypatched. The properties pinned here are the ones that decide whether the
module is trustworthy rather than merely working:

* the template seeds ALL ELEVEN steps, in order, and a re-seed writes NOTHING;
* progress + current-step mirror the milestones module (one lifecycle, one scale);
* a sealed credential leaves ONLY a reference behind - no plaintext on the step,
  none in the logs - and NEVER sets ``verified``;
* the milestone hand-off is best-effort: a milestone failure cannot fail a
  completion that has already happened.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from app.modules.client_onboarding import service as svc
from app.modules.client_onboarding.constants import (
    DEFAULT_TEMPLATE_KEY,
    LOCAL_SEO_TEMPLATE,
    is_collect_step,
    template_for,
)
from app.modules.client_onboarding.schemas import OnboardingStats, OnboardingStepResponse
from app.modules.client_onboarding.service import (
    advance_onboarding_milestone,
    build_workspace,
    credential_provider,
    current_step,
    run_progress,
    seal_step_credential,
    seed_onboarding_for_client,
    seed_run,
    unresolved_steps,
)

pytestmark = pytest.mark.unit

_SECRET = "gbp-live-p@ssw0rd-9f2a"
_CALLER = "00000000-0000-0000-0000-0000000000a1"


class FakeRepo:
    """In-memory stand-in for the RLS-scoped OnboardingRepo."""

    def __init__(self) -> None:
        self.steps: dict[str, list[dict[str, Any]]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.seed_calls: list[dict[str, Any]] = []
        self.insert_calls: list[dict[str, Any]] = []
        self.active: dict[str, dict[str, Any]] = {}
        self.insert_returns: dict[str, Any] | None = {"id": "run-1"}

    def list_steps(self, run_id: str) -> list[dict[str, Any]]:
        return list(self.steps.get(run_id, []))

    def seed_steps(
        self, *, run_id: str, client_id: str, client_name: str, steps: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        self.seed_calls.append({
            "run_id": run_id, "client_id": client_id, "client_name": client_name,
            "steps": steps,
        })
        rows = [
            {"id": f"st-{i}", "run_id": run_id, "client_id": client_id,
             "client_name": client_name, "status": "pending", "verified": False,
             "vault_secret_id": None, **s}
            for i, s in enumerate(steps, start=1)
        ]
        self.steps.setdefault(run_id, []).extend(rows)
        return rows

    def active_run_for(self, client_id: str) -> dict[str, Any] | None:
        return self.active.get(client_id)

    def insert_run(self, **kwargs: Any) -> dict[str, Any] | None:
        self.insert_calls.append(kwargs)
        return self.insert_returns


def _step(status: str, label: str = "Step", sort_order: int = 1) -> OnboardingStepResponse:
    return OnboardingStepResponse.from_row({
        "id": f"st-{sort_order}", "label": label, "status": status,
        "sort_order": sort_order, "client_name": "Acme",
    })


# --------------------------------------------------------------------------- #
# 1. The versioned template.
# --------------------------------------------------------------------------- #
def test_the_template_is_exactly_the_eleven_researched_steps_in_order() -> None:
    assert [t.key for t in LOCAL_SEO_TEMPLATE] == [
        "kickoff", "collect_gbp", "collect_website_cms", "collect_analytics",
        "collect_search_console", "brand_assets", "competitor_list", "keyword_seeds",
        "baseline_audit", "content_plan", "reporting_setup",
    ]
    assert len(LOCAL_SEO_TEMPLATE) == 11


def test_the_template_sort_order_is_dense_and_starts_at_one() -> None:
    # sort_order IS the checklist order; a gap or a duplicate would render the board
    # in an order nobody chose.
    assert [t.sort_order for t in LOCAL_SEO_TEMPLATE] == list(range(1, 12))


def test_every_template_step_has_a_label_and_an_owner_role() -> None:
    for t in LOCAL_SEO_TEMPLATE:
        assert t.key and t.label and t.owner_role


def test_template_keys_are_unique() -> None:
    # The 0040 unique index is (run_id, step_key): a duplicate key in the template
    # would silently seed 10 steps instead of 11.
    keys = [t.key for t in LOCAL_SEO_TEMPLATE]
    assert len(set(keys)) == len(keys)


def test_the_five_collect_steps_are_exactly_the_credential_bearing_ones() -> None:
    """``is_collect_step`` keys off the prefix; this pins the convention against the
    actual template, so a future 'gather_gbp' step cannot quietly fall out of the
    credential path."""
    collect = [t.key for t in LOCAL_SEO_TEMPLATE if is_collect_step(t.key)]
    assert collect == [
        "collect_gbp", "collect_website_cms", "collect_analytics", "collect_search_console",
    ]
    assert not is_collect_step("kickoff")
    assert not is_collect_step("brand_assets")


def test_an_unknown_template_key_degrades_to_the_default_not_an_empty_checklist() -> None:
    """An empty checklist would read as 100% complete and skip the whole activation -
    the worst failure mode available here."""
    assert template_for("nope") == LOCAL_SEO_TEMPLATE
    assert template_for(DEFAULT_TEMPLATE_KEY) == LOCAL_SEO_TEMPLATE


# --------------------------------------------------------------------------- #
# 2. Seeding: all 11, in order, idempotently.
# --------------------------------------------------------------------------- #
def test_seed_run_writes_all_eleven_steps_in_template_order() -> None:
    repo = FakeRepo()
    steps = seed_run(repo, "run-1", "cl-1", "Acme Roofing")  # type: ignore[arg-type]
    assert len(steps) == 11
    assert [s["step_key"] for s in steps] == [t.key for t in LOCAL_SEO_TEMPLATE]
    assert [s["sort_order"] for s in steps] == list(range(1, 12))
    seeded = repo.seed_calls[0]
    assert seeded["client_id"] == "cl-1" and seeded["client_name"] == "Acme Roofing"


def test_seed_run_is_idempotent_and_writes_nothing_on_a_reseed() -> None:
    """A retried client-create hook must not duplicate the checklist."""
    repo = FakeRepo()
    seed_run(repo, "run-1", "cl-1", "Acme")  # type: ignore[arg-type]
    assert len(repo.seed_calls) == 1
    again = seed_run(repo, "run-1", "cl-1", "Acme")  # type: ignore[arg-type]
    assert len(repo.seed_calls) == 1  # no second write at all
    assert len(again) == 11  # ... and the caller still gets the checklist


def test_seed_run_snapshots_the_label_from_the_code_template() -> None:
    repo = FakeRepo()
    steps = seed_run(repo, "run-1", "cl-1", "Acme")  # type: ignore[arg-type]
    labels = {s["step_key"]: s["label"] for s in steps}
    assert labels["collect_gbp"] == "Collect GBP access"
    assert labels["kickoff"] == "Kickoff call & goals"


# --------------------------------------------------------------------------- #
# 3. Progress weighting + current-step precedence (mirrors milestones).
# --------------------------------------------------------------------------- #
def test_progress_is_the_weighted_average_of_the_step_statuses() -> None:
    steps = [
        _step("completed", sort_order=1),   # 1.0
        _step("in_progress", sort_order=2),  # 0.5
        _step("blocked", sort_order=3),      # 0.25
        _step("pending", sort_order=4),      # 0.0
    ]
    assert run_progress(steps) == 44  # 1.75 / 4 = 43.75 -> 44


def test_progress_of_an_all_completed_run_is_one_hundred() -> None:
    assert run_progress([_step("completed", sort_order=i) for i in range(1, 4)]) == 100


def test_progress_of_an_empty_checklist_is_zero_not_one_hundred() -> None:
    assert run_progress([]) == 0


def test_a_skipped_step_does_not_count_toward_progress() -> None:
    assert run_progress([_step("completed", sort_order=1), _step("skipped", sort_order=2)]) == 50


def test_progress_matches_the_milestones_helper_on_the_same_shape() -> None:
    """One lifecycle, one scale: the two helpers must agree given equivalent input."""
    from app.schemas.milestones import ClientProjectResponse, StageResponse, project_progress

    onboarding = [
        _step("completed", sort_order=1), _step("in_progress", sort_order=2),
        _step("blocked", sort_order=3), _step("pending", sort_order=4),
    ]
    project = ClientProjectResponse(
        id="p1", client="Acme", site="", init="AC", c="#000", health="on_track",
        stages=[
            StageResponse(key="onboarding", status="completed", auto_source="", updated_at=""),
            StageResponse(key="baseline", status="in_progress", auto_source="", updated_at=""),
            StageResponse(key="content", status="blocked", auto_source="", updated_at=""),
            StageResponse(key="authority", status="upcoming", auto_source="", updated_at=""),
        ],
    )
    assert run_progress(onboarding) == project_progress(project)


def test_current_step_prefers_work_in_flight_over_the_next_pending() -> None:
    steps = [
        _step("completed", "Kickoff", 1),
        _step("pending", "Collect GBP", 2),
        _step("in_progress", "Collect CMS", 3),
    ]
    # in_progress out-ranks an EARLIER pending: the board points at what a human is
    # actually holding, not at the top of the list.
    step = current_step(steps)
    assert step is not None and step.label == "Collect CMS"


def test_current_step_treats_blocked_as_in_flight() -> None:
    steps = [_step("pending", "Collect GBP", 1), _step("blocked", "Collect CMS", 2)]
    step = current_step(steps)
    assert step is not None and step.label == "Collect CMS"


def test_current_step_falls_back_to_the_first_pending() -> None:
    steps = [_step("completed", "Kickoff", 1), _step("pending", "Collect GBP", 2),
             _step("pending", "Collect CMS", 3)]
    step = current_step(steps)
    assert step is not None and step.label == "Collect GBP"


def test_current_step_of_a_finished_run_is_the_last_step() -> None:
    steps = [_step("completed", "Kickoff", 1), _step("completed", "Reporting", 2)]
    step = current_step(steps)
    assert step is not None and step.label == "Reporting"


def test_current_step_skips_over_skipped_steps_to_the_next_pending() -> None:
    steps = [_step("skipped", "Kickoff", 1), _step("pending", "Collect GBP", 2)]
    step = current_step(steps)
    assert step is not None and step.label == "Collect GBP"


def test_current_step_of_an_empty_checklist_is_none() -> None:
    assert current_step([]) is None


def test_current_step_precedence_matches_the_milestones_helper() -> None:
    from app.schemas.milestones import ClientProjectResponse, StageResponse, current_stage

    project = ClientProjectResponse(
        id="p1", client="Acme", site="", init="AC", c="#000", health="on_track",
        stages=[
            StageResponse(key="onboarding", status="completed", auto_source="", updated_at=""),
            StageResponse(key="baseline", status="upcoming", auto_source="", updated_at=""),
            StageResponse(key="content", status="in_progress", auto_source="", updated_at=""),
        ],
    )
    stage = current_stage(project)
    step = current_step([
        _step("completed", "onboarding", 1), _step("pending", "baseline", 2),
        _step("in_progress", "content", 3),
    ])
    # Both pick the in_progress item over the earlier not-started one.
    assert stage is not None and step is not None
    assert stage.key == "content" and step.label == "content"


# --------------------------------------------------------------------------- #
# 4. unresolved_steps - what blocks an unforced completion.
# --------------------------------------------------------------------------- #
def test_unresolved_counts_pending_in_progress_and_blocked() -> None:
    rows = [
        {"label": "A", "status": "pending"}, {"label": "B", "status": "in_progress"},
        {"label": "C", "status": "blocked"}, {"label": "D", "status": "completed"},
        {"label": "E", "status": "skipped"},
    ]
    assert unresolved_steps(rows) == ["A", "B", "C"]


def test_a_skipped_step_is_resolved_but_a_blocked_one_is_not() -> None:
    """A lead deciding a step does not apply IS a decision; 'blocked' is an
    unfinished step wearing a reason."""
    assert unresolved_steps([{"label": "X", "status": "skipped"}]) == []
    assert unresolved_steps([{"label": "X", "status": "blocked"}]) == ["X"]


def test_unresolved_falls_back_to_the_step_key_when_a_label_is_missing() -> None:
    assert unresolved_steps([{"step_key": "collect_gbp", "status": "pending"}]) == ["collect_gbp"]


# --------------------------------------------------------------------------- #
# 5. The credential seal: a reference comes back, never the secret.
# --------------------------------------------------------------------------- #
def test_seal_sends_the_secret_to_the_vault_with_client_access_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _add_key(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"id": "vk-1", "masked": "gbp-li••••••9f2a", "kind": "client_access"}

    monkeypatch.setattr(svc, "add_key", _add_key)
    ref = seal_step_credential(
        step_key="collect_gbp", credential_label="GBP manager login",
        secret=_SECRET, created_by=_CALLER,
    )
    assert ref == "vk-1"  # ONLY the reference comes back
    assert calls[0]["kind"] == "client_access"  # not an agency api_key
    assert calls[0]["provider"] == "gbp"  # what it opens
    assert calls[0]["secret"] == _SECRET  # the plaintext went to the vault, and only there
    assert calls[0]["created_by"] == _CALLER


def test_seal_returns_a_reference_and_nothing_resembling_the_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(svc, "add_key", lambda **_k: {"id": "vk-1"})
    ref = seal_step_credential(
        step_key="collect_analytics", credential_label="GA4", secret=_SECRET, created_by=None
    )
    assert _SECRET not in ref


def test_seal_never_logs_the_secret(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(svc, "add_key", lambda **_k: {"id": "vk-1"})
    with caplog.at_level(logging.DEBUG):
        seal_step_credential(
            step_key="collect_gbp", credential_label="GBP", secret=_SECRET, created_by=None
        )
    assert _SECRET not in caplog.text


@pytest.mark.parametrize(
    ("step_key", "expected"),
    [
        ("collect_gbp", "gbp"),
        ("collect_website_cms", "website_cms"),
        ("collect_analytics", "analytics"),
        ("collect_search_console", "search_console"),
    ],
)
def test_credential_provider_names_what_the_credential_opens(
    step_key: str, expected: str
) -> None:
    """``provider`` says WHAT IT OPENS while ``kind`` says WHAT SPECIES it is. That
    split is the whole reason 0041 added a dimension instead of overloading
    ``provider`` with pseudo-providers."""
    assert credential_provider(step_key) == expected


# --------------------------------------------------------------------------- #
# 6. The milestone hand-off - best-effort, by construction.
# --------------------------------------------------------------------------- #
class _FakeMilestones:
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self.advances: list[tuple[str, str, str, str | None]] = []
        self.project_id: str | None = "proj-1"

    def project_id_for_client(self, client_id: str) -> str | None:
        return self.project_id

    def advance_stage(
        self, project_id: str, stage_key: str, *, status: str, auto_source: str | None = None
    ) -> dict[str, Any] | None:
        self.advances.append((project_id, stage_key, status, auto_source))
        return {"id": "stage-1"}


@pytest.fixture
def milestones(monkeypatch: pytest.MonkeyPatch) -> list[_FakeMilestones]:
    """Capture the MilestonesRepo the service builds (it is imported lazily inside
    the function, so patch it at its source module)."""
    built: list[_FakeMilestones] = []

    def _factory(user_id: str) -> _FakeMilestones:
        repo = _FakeMilestones(user_id)
        built.append(repo)
        return repo

    monkeypatch.setattr("app.db.milestones_repo.MilestonesRepo", _factory)
    return built


def test_completion_advances_onboarding_to_baseline_with_the_auto_source(
    milestones: list[_FakeMilestones],
) -> None:
    assert advance_onboarding_milestone(_CALLER, "cl-1") is True
    assert milestones[0].advances == [
        ("proj-1", "onboarding", "completed", "onboarding_complete"),
        ("proj-1", "baseline", "in_progress", "onboarding_complete"),
    ]


def test_the_milestone_advance_runs_under_the_callers_identity(
    milestones: list[_FakeMilestones],
) -> None:
    # No BYPASSRLS anywhere in this module: the stage write is RLS-scoped to the lead
    # who completed the run (the 0021 update policy is leads-only, which they are).
    advance_onboarding_milestone(_CALLER, "cl-1")
    assert milestones[0].user_id == _CALLER


def test_a_client_with_no_project_timeline_is_a_clean_no_op(
    milestones: list[_FakeMilestones], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _factory(user_id: str) -> _FakeMilestones:
        repo = _FakeMilestones(user_id)
        repo.project_id = None
        milestones.append(repo)
        return repo

    monkeypatch.setattr("app.db.milestones_repo.MilestonesRepo", _factory)
    assert advance_onboarding_milestone(_CALLER, "cl-1") is False
    assert milestones[0].advances == []


def test_a_milestone_failure_is_swallowed_and_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """THE best-effort contract: the activation is finished the moment its own row
    says so. A milestone hiccup must never undo that."""

    def _boom(_user_id: str) -> Any:
        raise RuntimeError("milestones pool is down")

    monkeypatch.setattr("app.db.milestones_repo.MilestonesRepo", _boom)
    with caplog.at_level(logging.WARNING):
        assert advance_onboarding_milestone(_CALLER, "cl-1") is False  # no raise
    assert "onboarding_milestone_advance_failed" in caplog.text


def test_a_failure_midway_through_the_advance_is_also_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The second advance_stage blowing up must not propagate either - the first has
    # already been written, and the completion has already happened.
    class _HalfBroken(_FakeMilestones):
        def advance_stage(self, *a: Any, **k: Any) -> dict[str, Any] | None:
            super().advance_stage(*a, **k)
            raise RuntimeError("connection reset")

    monkeypatch.setattr("app.db.milestones_repo.MilestonesRepo", _HalfBroken)
    assert advance_onboarding_milestone(_CALLER, "cl-1") is False


# --------------------------------------------------------------------------- #
# 7. The client-create hook - best-effort, by construction.
# --------------------------------------------------------------------------- #
def test_the_client_create_hook_seeds_a_run_and_its_checklist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepo()
    monkeypatch.setattr(svc, "OnboardingRepo", lambda _uid: repo)
    run_id = seed_onboarding_for_client(_CALLER, "cl-1", "Acme Roofing", _CALLER, "Sara")
    assert run_id == "run-1"
    assert repo.insert_calls[0]["client_id"] == "cl-1"
    assert repo.insert_calls[0]["client_name"] == "Acme Roofing"
    assert repo.insert_calls[0]["template_key"] == DEFAULT_TEMPLATE_KEY
    assert repo.insert_calls[0]["owner_name"] == "Sara"
    assert len(repo.seed_calls[0]["steps"]) == 11


def test_the_hook_never_seeds_a_second_live_run(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepo()
    repo.active["cl-1"] = {"id": "run-existing"}
    monkeypatch.setattr(svc, "OnboardingRepo", lambda _uid: repo)
    assert seed_onboarding_for_client(_CALLER, "cl-1", "Acme", _CALLER, "Sara") is None
    assert repo.insert_calls == []  # nothing written next to the live run


def test_the_hook_returns_none_when_the_unique_index_wins_the_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepo()
    repo.insert_returns = None  # `on conflict do nothing` returned no row
    monkeypatch.setattr(svc, "OnboardingRepo", lambda _uid: repo)
    assert seed_onboarding_for_client(_CALLER, "cl-1", "Acme", _CALLER, "Sara") is None
    assert repo.seed_calls == []  # no orphan checklist without a run


def test_the_hook_swallows_any_failure_and_logs_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The client was already created and acknowledged: a seeding hiccup must never
    fail it (mirrors record_activity's never-raise discipline)."""

    def _boom(_uid: str) -> Any:
        raise RuntimeError("db pool is down")

    monkeypatch.setattr(svc, "OnboardingRepo", _boom)
    with caplog.at_level(logging.WARNING):
        assert seed_onboarding_for_client(_CALLER, "cl-1", "Acme", _CALLER, "Sara") is None
    assert "onboarding_seed_failed" in caplog.text


def test_the_hook_swallows_a_failure_during_the_step_seed_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SeedBoom(FakeRepo):
        def seed_steps(self, **_k: Any) -> list[dict[str, Any]]:
            raise RuntimeError("write failed")

    monkeypatch.setattr(svc, "OnboardingRepo", lambda _uid: _SeedBoom())
    assert seed_onboarding_for_client(_CALLER, "cl-1", "Acme", _CALLER, "Sara") is None


# --------------------------------------------------------------------------- #
# 8. The workspace adapter.
# --------------------------------------------------------------------------- #
def _live_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "st-1", "run_id": "run-1", "client_id": "cl-1", "client_name": "Acme",
        "step_key": "collect_gbp", "label": "Collect GBP access", "status": "pending",
        "owner_name": "Sara", "sort_order": 2,
    }
    row.update(over)
    return row


def _stats() -> OnboardingStats:
    return OnboardingStats.from_row(
        {"in_onboarding": 3, "steps_pending": 7, "completed_30d": 12}
    )


def test_workspace_emits_the_pinned_tools_ts_shape() -> None:
    extra = build_workspace(_stats(), [_live_row()])
    assert [k.label for k in extra.kpis] == ["In onboarding", "Steps pending", "Completed (30d)"]
    assert [k.value for k in extra.kpis] == ["3", "7", "12"]
    assert extra.table is not None
    assert extra.table.cols == ["Client", "Step", "Owner", "Status"]
    assert extra.table.title == "Onboarding" and extra.table.icon == "person_add"
    assert extra.primary is not None
    assert (extra.primary.label, extra.primary.icon) == ("Start onboarding", "person_add")
    assert extra.bullets == [
        "Run the onboarding wizard", "Collect access & assets", "Track onboarding progress",
    ]


def test_workspace_emits_one_row_per_run_at_its_current_step() -> None:
    """Each row is a RUN, described by the step that needs a human - not one row per
    step (which would bury the board under 11 rows per client)."""
    rows = [
        _live_row(id="s1", run_id="run-1", label="Kickoff", status="completed", sort_order=1),
        _live_row(id="s2", run_id="run-1", label="Collect GBP access", status="in_progress",
                  sort_order=2),
        _live_row(id="s3", run_id="run-2", client_name="Coastline Fit", label="Kickoff",
                  status="pending", owner_name="Ayesha", sort_order=1),
    ]
    table = build_workspace(_stats(), rows).table
    assert table is not None and len(table.rows) == 2
    assert table.rows[0][:3] == ["Acme", "Collect GBP access", "Sara"]
    assert table.rows[1][:3] == ["Coastline Fit", "Kickoff", "Ayesha"]


@pytest.mark.parametrize(
    ("status", "label", "tone"),
    [
        ("pending", "Pending", "warn"),
        ("completed", "Done", "ok"),
        ("in_progress", "In progress", "info"),
        ("blocked", "Blocked", "mut"),
        ("skipped", "Skipped", "mut"),
    ],
)
def test_workspace_status_tones(status: str, label: str, tone: str) -> None:
    table = build_workspace(_stats(), [_live_row(status=status)]).table
    assert table is not None
    cell = table.rows[0][3]
    assert not isinstance(cell, str)
    assert cell.v == label and cell.tone == tone


def test_workspace_caps_the_board_at_eight_runs() -> None:
    rows = [
        _live_row(id=f"s{i}", run_id=f"run-{i}", client_name=f"Client {i:02d}")
        for i in range(1, 15)
    ]
    table = build_workspace(_stats(), rows).table
    assert table is not None and len(table.rows) == 8


def test_workspace_row_is_exactly_as_wide_as_the_cols() -> None:
    table = build_workspace(_stats(), [_live_row()]).table
    assert table is not None
    assert all(len(r) == len(table.cols) for r in table.rows)


def test_an_empty_board_still_emits_the_pinned_envelope() -> None:
    extra = build_workspace(OnboardingStats.from_row({}), [])
    assert extra.table is not None and extra.table.rows == []
    assert [k.value for k in extra.kpis] == ["0", "0", "0"]
    assert extra.table.cols == ["Client", "Step", "Owner", "Status"]


def test_the_workspace_never_renders_the_client_id() -> None:
    extra = build_workspace(_stats(), [_live_row(client_id="cl-secret")])
    assert "cl-secret" not in extra.model_dump_json()
