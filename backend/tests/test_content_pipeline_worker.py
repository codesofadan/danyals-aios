"""The doctrine engine's worker core: what it writes, and what it refuses to write.

Driven entirely through injected doubles - no database, no provider, no broker -
so these assertions are about the ENGINE's behaviour, not about infrastructure.

The three behaviours that matter most here are the ones a screen will be built
on: a halt is not a failure, a redelivery does not draft twice, and the row says
which stage is running while it is running rather than after it finished.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from app.config import get_settings
from app.services.content_pipeline.context import PipelineContext, StageResult
from workers.tasks.content_pipeline import (
    STAGE_LABEL,
    PipelineDeps,
    execute_pipeline_job,
)

pytestmark = pytest.mark.unit


class _Store:
    """A ContentStore double that remembers every write, in order."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = dict(row) if row else None
        self.writes: list[dict[str, Any]] = []

    def load(self, code: str) -> dict[str, Any] | None:
        return dict(self.row) if self.row is not None else None

    def update(self, code: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        self.writes.append(dict(fields))
        if self.row is not None:
            self.row.update(fields)
        return dict(self.row) if self.row is not None else None

    @property
    def stages(self) -> list[str]:
        return [w["stage"] for w in self.writes if "stage" in w]

    def final(self, key: str) -> Any:
        for write in reversed(self.writes):
            if key in write:
                return write[key]
        return None


class _Planning:
    """Planning-store double: records engagements it was asked to create."""

    def __init__(self, *, fails: bool = False) -> None:
        self.created: list[dict[str, Any]] = []
        self._fails = fails

    def create_engagement(self, **kwargs: Any) -> Any:
        if self._fails:
            raise RuntimeError("engagements table unreachable")
        self.created.append(dict(kwargs))
        return type("_E", (), {"id": "eng-new"})()


class _Gate:
    def evaluate(self, ctx: Any) -> Any:  # pragma: no cover - never consulted here
        raise AssertionError("the engine must not consult the gate directly")


def _row(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "code": "CJ-4200", "status": "queued", "client_id": "c-1",
        "client_name": "Dallas Plumbing", "page_type": "service",
        "topic": "Emergency plumbing in Dallas", "framework": "PAS",
        "engagement_id": "eng-1",
        "source_pack": {
            "primary_keyword": "emergency plumber dallas", "geo": "Dallas",
            "proof_points": ["412 callouts in 2025, from our dispatch log"],
        },
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _scripted_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let a test script the stage set, and ALWAYS put the real one back.

    Patching the module attribute directly would leak the double into every test
    that runs after this file - the kind of cross-file contamination that makes a
    suite green in one order and red in another.
    """
    monkeypatch.setattr(
        "workers.tasks.content_pipeline.build_page_stages",
        lambda **kwargs: _SCRIPT["stages"],
    )


_SCRIPT: dict[str, Any] = {"stages": {}}


def _stage(name: str, outcome: str = "ok", **data: Any) -> Any:
    def run(ctx: PipelineContext) -> StageResult:
        return ctx.record(StageResult(name, outcome=outcome, data=data))  # type: ignore[arg-type]
    return run


def _run(store: _Store, stages: dict[str, Any], planning: Any | None = None) -> Any:
    _SCRIPT["stages"] = stages
    deps = PipelineDeps(store=store, planning=planning or _Planning())
    return execute_pipeline_job(deps, "CJ-4200", settings=get_settings(), gate=_Gate())


class TestARedeliveryNeverDraftsTwice:
    """The broker is at-least-once and drafting spends real money."""

    @pytest.mark.parametrize("status", ["drafting", "needs_review", "done", "failed"])
    def test_a_job_that_is_not_queued_is_a_no_op(self, status: str) -> None:
        store = _Store(_row(status=status))
        outcome = _run(store, {"gate": _stage("gate")})
        assert outcome.state == "noop"
        assert store.writes == [], "a redelivery must not touch the row"

    def test_a_missing_job_is_a_no_op_not_a_crash(self) -> None:
        store = _Store(None)
        outcome = _run(store, {"gate": _stage("gate")})
        assert outcome.state == "noop" and outcome.status == "unknown"


class TestAHaltIsNotAFailure:
    """Law 16. The Experience gate refusing to draft is the system working, so the
    job must not be marked failed, must not be retried, and must say what is
    outstanding - that is the only thing an operator can act on."""

    def test_an_experience_halt_holds_the_job_instead_of_failing_it(self) -> None:
        store = _Store(_row())
        outcome = _run(store, {
            "sme": _stage("sme", "halted", missing=["proof_metric", "photo"],
                          questions={"proof_metric": "q1", "photo": "q2"}),
        })
        assert outcome.status == "drafting", "a halt must never be written as failed"
        assert outcome.state == "deferred"
        assert store.final("status") == "drafting"
        assert store.final("experience_slots_missing") == 2

    def test_the_held_row_says_how_many_answers_are_outstanding(self) -> None:
        store = _Store(_row())
        _run(store, {"sme": _stage("sme", "halted", missing=["a", "b", "c"])})
        assert "3 to go" in store.stages[-1]

    def test_a_halt_does_not_write_a_draft(self) -> None:
        store = _Store(_row())
        _run(store, {"sme": _stage("sme", "halted", missing=["a"])})
        assert store.final("draft_md") is None


class TestTheRowSaysWhatIsRunningWhileItRuns:
    def test_each_stage_is_streamed_before_it_executes(self) -> None:
        store = _Store(_row())
        order: list[str] = []

        def watcher(name: str) -> Any:
            def run(ctx: PipelineContext) -> StageResult:
                # Whatever the row says right now must already be THIS stage.
                order.append(store.stages[-1])
                return ctx.record(StageResult(name, outcome="ok"))
            return run

        _run(store, {"sme": watcher("sme"), "gate": watcher("gate")})
        assert order == [STAGE_LABEL["sme"], STAGE_LABEL["gate"]]

    def test_every_declared_label_belongs_to_a_real_stage(self) -> None:
        """There are two sequences now - a full page and a reviewer's edit - and
        every label must belong to one of them. A label with no stage is a step
        that can never light up, which is the exact defect v1's fourteen-key
        table has; a stage with no label streams a raw key at the operator."""
        from app.services.content_pipeline.runner import EDIT_STAGES, PAGE_STAGES

        real = set(PAGE_STAGES) | set(EDIT_STAGES)
        assert set(STAGE_LABEL) == real

    def test_the_edit_sequence_reuses_the_page_instead_of_redrafting(self) -> None:
        """An edit is not a redraft. Re-running research, outline and draft would
        throw away the page the lead just read and bill a full page to ignore
        what they asked for."""
        from app.services.content_pipeline.runner import EDIT_STAGES

        assert EDIT_STAGES[0] == "guided_edit"
        for skipped in ("sme", "research", "outline", "draft"):
            assert skipped not in EDIT_STAGES, f"{skipped} must not re-run on an edit"
        for kept in ("voice", "grounding", "title_meta", "schema_links", "gate"):
            assert kept in EDIT_STAGES, f"{kept} must see the edited text"


class TestAFinishedPageGoesToTheHumanGate:
    def test_a_clean_run_lands_on_needs_review_with_its_work_written(self) -> None:
        store = _Store(_row())

        def draft(ctx: PipelineContext) -> StageResult:
            ctx.draft_md = "# Emergency plumbing\n\nWe answered 412 calls last year."
            ctx.title = "Emergency Plumber Dallas"
            ctx.meta_description = "Same-day emergency plumbing in Dallas."
            return ctx.record(StageResult("draft", outcome="ok"))

        outcome = _run(store, {
            "draft": draft,
            "gate": _stage("gate", "ok", weighted_total=88.5, passed=True),
        })
        assert outcome.status == "needs_review" and outcome.state == "advanced"
        assert store.final("draft_md").startswith("# Emergency plumbing")
        assert store.final("words") == 9
        assert store.final("qa_weighted_total") == 88.5
        assert store.final("outline")["meta"]["title"] == "Emergency Plumber Dallas"
        assert outcome.passed is True

    def test_a_degraded_run_still_reaches_review_but_says_so(self) -> None:
        store = _Store(_row())

        def draft(ctx: PipelineContext) -> StageResult:
            ctx.draft_md = "body"
            return ctx.record(StageResult("draft", outcome="ok"))

        outcome = _run(store, {
            "research": _stage("research", "degraded"),
            "draft": draft,
            "gate": _stage("gate", "ok"),
        })
        assert outcome.status == "needs_review"
        assert outcome.state == "degraded"
        assert "degraded" in store.final("stage")

    def test_a_broken_stage_fails_the_job_honestly(self) -> None:
        store = _Store(_row())
        outcome = _run(store, {"draft": _stage("draft", "failed")})
        assert outcome.status == "failed" and store.final("status") == "failed"


class TestAJobWithoutAnEngagementGetsOne:
    """Nothing in the product writes `content_engagements`. Without this the SME
    gate halts every single page with "no engagement" - a reason the operator can
    do absolutely nothing about, forever."""

    def test_an_engagement_is_created_and_stamped_on_the_job(self) -> None:
        store = _Store(_row(engagement_id=None))
        planning = _Planning()
        _run(store, {"gate": _stage("gate")}, planning)
        assert planning.created, "a job with no engagement must get one"
        assert planning.created[0]["shape"] == "single_page"
        assert store.final("engagement_id") == "eng-new"

    def test_an_existing_engagement_is_reused_not_duplicated(self) -> None:
        store = _Store(_row(engagement_id="eng-1"))
        planning = _Planning()
        _run(store, {"gate": _stage("gate")}, planning)
        assert planning.created == [], "a second engagement would open a second dossier"

    def test_an_engagement_that_cannot_be_created_does_not_crash_the_job(self) -> None:
        store = _Store(_row(engagement_id=None))
        outcome = _run(store, {"gate": _stage("gate")}, _Planning(fails=True))
        # Any terminal verdict is fine; the point is that an unavailable
        # engagements table degrades the run instead of raising out of the task.
        assert outcome.state in ("advanced", "deferred", "degraded"), "must degrade, not raise"
        assert outcome.status != "failed"


class TestTheClientsOwnPhoneNumberReachesThePage:
    """Found by running the engine: the conversion stage requires a tappable
    `tel:` link, the draft stage may state nothing outside the supplied facts, and
    the client's phone number was in neither - so the writer had to invent a
    number or fail that check on every page, forever."""

    def test_the_stored_nap_becomes_first_party_facts(self) -> None:
        from workers.tasks.content_pipeline import nap_facts

        facts = nap_facts({
            "phone": "214-555-0142", "website_url": "https://ortizplumbing.com",
            "address_line1": "1820 Greenville Ave", "city": "Dallas",
            "postal_code": "75206",
        })
        assert "phone: 214-555-0142" in facts
        assert any(f.startswith("address: 1820 Greenville Ave, Dallas, 75206") for f in facts)

    def test_a_half_filled_profile_contributes_only_what_it_has(self) -> None:
        from workers.tasks.content_pipeline import nap_facts

        facts = nap_facts({"phone": "214-555-0142", "website_url": "", "city": ""})
        assert facts == ("phone: 214-555-0142",), "blank fields must not be asserted"

    def test_no_profile_adds_nothing_rather_than_blank_facts(self) -> None:
        from workers.tasks.content_pipeline import nap_facts

        assert nap_facts(None) == () and nap_facts({}) == ()

    def test_the_operators_brief_reaches_the_writer(self) -> None:
        """The flow asks for proof points, services and unique data and stores
        them on source_pack. This pipeline grounded a page solely on the
        Experience dossier, so everything typed on the brief screen was collected
        and silently ignored - and the QA gate then scored fact_grounding against
        facts the writer had never been given."""
        from workers.tasks.content_pipeline import brief_facts

        facts = brief_facts({
            "proof_points": ["412 callouts in 2025, from our dispatch log"],
            "services": ["Emergency leak repair"],
            "unique_data": ["Median on-site 47 minutes"],
            "testimonials": [""],
        })
        assert "proof: 412 callouts in 2025, from our dispatch log" in facts
        assert "service: Emergency leak repair" in facts
        assert "only we know: Median on-site 47 minutes" in facts
        assert not any(f.endswith(": ") for f in facts), "blank entries must not travel"

    def test_a_job_with_no_brief_adds_nothing(self) -> None:
        from workers.tasks.content_pipeline import brief_facts

        assert brief_facts(None) == () and brief_facts({}) == ()

    def test_the_facts_are_appended_to_what_the_experience_gate_collected(self) -> None:
        store = _Store(_row())
        seen: dict[str, Any] = {}

        def sme(ctx: PipelineContext) -> StageResult:
            ctx.facts = ("count_source: 412 callouts in 2025",)
            return ctx.record(StageResult("sme", outcome="ok"))

        def draft(ctx: PipelineContext) -> StageResult:
            seen["facts"] = ctx.facts       # what the WRITER would be given
            ctx.draft_md = "body"
            return ctx.record(StageResult("draft", outcome="ok"))

        _SCRIPT["stages"] = {"sme": sme, "draft": draft}
        deps = PipelineDeps(
            store=store, planning=_Planning(), nap={"phone": "214-555-0142"},
        )
        execute_pipeline_job(deps, "CJ-4200", settings=get_settings(), gate=_Gate())
        assert "count_source: 412 callouts in 2025" in seen["facts"]
        assert "phone: 214-555-0142" in seen["facts"]
        # _row() seeds a source_pack, so the operator's brief rides too.
        assert "proof: 412 callouts in 2025, from our dispatch log" in seen["facts"]

    def test_a_halted_experience_gate_does_not_get_nap_facts_appended(self) -> None:
        """Nothing is being written, so there is nothing to ground."""
        store = _Store(_row())
        captured: dict[str, Any] = {}

        def sme(ctx: PipelineContext) -> StageResult:
            result = ctx.record(StageResult("sme", outcome="halted", data={"missing": ["photo"]}))
            captured["facts"] = ctx.facts
            return result

        _SCRIPT["stages"] = {"sme": sme}
        deps = PipelineDeps(store=store, planning=_Planning(), nap={"phone": "214-555-0142"})
        execute_pipeline_job(deps, "CJ-4200", settings=get_settings(), gate=_Gate())
        assert captured["facts"] == ()


class TestAPageThatWasNeverWrittenDoesNotReachAHuman:
    """Found by running a real job: a degraded outline stops the pipeline before a
    word exists, and that used to persist as `needs_review` - putting an EMPTY
    draft in front of a lead and asking them to approve it onto a client's site.
    `needs_review` must mean a human has something to read."""

    def test_a_run_with_no_draft_holds_instead_of_queueing_for_review(self) -> None:
        store = _Store(_row())
        outcome = _run(store, {
            "outline": _stage("outline", "degraded"),
        })
        assert outcome.status == "drafting", "an empty page must not reach the review queue"
        assert store.final("status") != "needs_review"
        assert "Held" in store.final("stage")

    def test_the_hold_says_why_on_the_row(self) -> None:
        store = _Store(_row())
        _run(store, {"outline": _stage("outline", "degraded")})
        assert "outline" in store.final("stage").lower()

    def test_a_run_that_produced_a_page_still_reaches_review(self) -> None:
        store = _Store(_row())

        def draft(ctx: PipelineContext) -> StageResult:
            ctx.draft_md = "# A real page\n\nWith real words in it."
            return ctx.record(StageResult("draft", outcome="ok"))

        outcome = _run(store, {"draft": draft, "gate": _stage("gate", "ok")})
        assert outcome.status == "needs_review"


class TestWhatTheStagesProduceActuallyReachesTheRow:
    """The first paid run wrote an empty qa_score and no JSON-LD onto a job whose
    gate had scored it and whose schema stage had validated it. The work was done
    and dropped on the floor between the pipeline and the row, because this code
    read for keys the stages do not emit - a nested "qa", a "schema_type".

    Nothing failed. The run reported success. That is the failure mode these
    assertions exist to prevent: silent loss between two working halves."""

    def _run_with(self, store: _Store, gate_data: dict[str, Any], schema_data: dict[str, Any]) -> Any:
        def draft(ctx: PipelineContext) -> StageResult:
            ctx.draft_md = "# A page\n\nWith real words."
            return ctx.record(StageResult("draft", outcome="ok"))

        return _run(store, {
            "draft": draft,
            "schema_links": _stage("schema_links", "ok", **schema_data),
            "gate": _stage("gate", "ok", **gate_data),
        })

    def test_the_gate_verdict_lands_whole(self) -> None:
        store = _Store(_row())
        self._run_with(
            store,
            {"weighted_total": 91.5, "passed": True, "dimensions": {"voice": 9},
             "blocked_by": [], "provisional": True},
            {},
        )
        qa = store.final("qa_score")
        assert qa["weighted_total"] == 91.5
        assert qa["passed"] is True
        assert qa["dimensions"] == {"voice": 9}, "the per-dimension scores must survive"
        assert store.final("qa_weighted_total") == 91.5

    def test_the_schema_graph_and_its_settled_type_land(self) -> None:
        store = _Store(_row())
        self._run_with(
            store, {},
            {"json_ld": {"@type": "Service", "name": "Emergency plumbing"},
             "primary_type": "Service", "valid": True},
        )
        assert store.final("json_ld")["@type"] == "Service"
        assert store.final("schema_type") == "Service"

    def test_internal_links_are_not_invented_as_empty(self) -> None:
        """This pipeline does not produce internal links - no stage fills them.
        Writing {"links": []} would say "we looked and found none" where the truth
        is that nothing looked."""
        store = _Store(_row())
        self._run_with(store, {}, {"json_ld": {"@type": "Service"}, "primary_type": "Service"})
        assert store.final("internal_links") is None

    def test_a_gate_that_produced_nothing_writes_no_score_rather_than_a_zero(self) -> None:
        store = _Store(_row())
        self._run_with(store, {}, {})
        assert store.final("qa_weighted_total") is None, "absent is not zero"


class TestTheEngineFlagActuallyRoutes:
    """The flag was documented in two places and read by nothing for a day, so
    every job ran v1 whatever the config said. A setting that does not do what it
    says is worse than no setting: it makes the wrong engine look chosen."""

    def _enqueued(self, engine: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        import app.routers.content as router_mod
        import workers.tasks.content as v1
        import workers.tasks.content_pipeline as v2

        seen: list[str] = []

        class _T:
            def __init__(self, name: str) -> None:
                self.name = name

            def delay(self, code: str) -> None:
                seen.append(self.name)

        settings = get_settings().model_copy(update={"content_engine": engine})
        monkeypatch.setattr(router_mod, "get_settings", lambda: settings)
        monkeypatch.setattr(v1, "run_content_job", _T("v1"))
        monkeypatch.setattr(v2, "run_content_pipeline_job", _T("v2"))
        router_mod.get_content_enqueuer()("CJ-4200")
        return seen

    def test_v2_routes_to_the_doctrine_pipeline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._enqueued("v2", monkeypatch) == ["v2"]

    def test_v1_routes_to_the_original_generator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._enqueued("v1", monkeypatch) == ["v1"]

    def test_an_unknown_value_falls_back_rather_than_failing_the_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A typo in config must not stop an agency creating content."""
        assert self._enqueued("V2-beta-typo", monkeypatch) == ["v1"]

    def test_the_value_is_case_and_whitespace_tolerant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self._enqueued("  V2  ", monkeypatch) == ["v2"]


class TestTheDefaultEngineIsTheDoctrinePipeline:
    """Switched 2026-08-29 after six paid runs took fact_grounding from 40 to 100
    and cleared every hard block. This asserts the DEFAULT, not the mechanism -
    the routing itself is covered above - because a silent revert to v1 would
    look identical from the outside: jobs would still be created, still reach
    review, and quietly skip the Experience gate, the uniqueness gate and the
    grounding repair."""

    def test_a_fresh_settings_object_selects_v2(self) -> None:
        from app.config import Settings

        assert Settings(_env_file=None).content_engine == "v2"  # type: ignore[call-arg]

    def test_the_environment_can_still_pin_v1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The revert path has to keep working, or the switch is one-way."""
        from app.config import Settings

        monkeypatch.setenv("CONTENT_ENGINE", "v1")
        assert Settings(_env_file=None).content_engine == "v1"  # type: ignore[call-arg]


class TestAReviewersEditIsNotADeadEnd:
    """Reproduced through the real API before this worked: a lead clicked
    "Request edits", typed what they wanted, and the page sat at "Edit requested"
    forever. The row moved to `drafting`, the instruction was stored, the pipeline
    was re-enqueued, and the engine returned `noop - job is drafting, not queued`.
    The reviewer's only feedback channel was a dead end."""

    def _edit_row(self, **kw: Any) -> dict[str, Any]:
        return _row(
            status="drafting", stage="Edit requested",
            edit_instruction="Cut the second section and add pricing.",
            draft_md="# The page\n\nAs the reviewer read it.",
            **kw,
        )

    def test_an_edit_request_runs_instead_of_no_opping(self) -> None:
        store = _Store(self._edit_row())
        seen: dict[str, Any] = {}

        def edit(ctx: PipelineContext) -> StageResult:
            seen["instruction_seen"] = True
            seen["draft_in"] = ctx.draft_md
            ctx.draft_md = "# The page\n\nEdited as asked, with pricing."
            return ctx.record(StageResult("guided_edit", outcome="ok"))

        outcome = _run(store, {"guided_edit": edit, "gate": _stage("gate", "ok")})
        assert outcome.state != "noop", "an edit request must not be mistaken for a redelivery"
        assert seen.get("instruction_seen") is True

    def test_the_edit_works_on_the_page_the_lead_actually_read(self) -> None:
        store = _Store(self._edit_row())
        seen: dict[str, Any] = {}

        def edit(ctx: PipelineContext) -> StageResult:
            seen["draft_in"] = ctx.draft_md
            ctx.draft_md = "# Edited"
            return ctx.record(StageResult("guided_edit", outcome="ok"))

        _run(store, {"guided_edit": edit, "gate": _stage("gate", "ok")})
        assert "As the reviewer read it." in seen["draft_in"], (
            "the stored draft must be loaded, or the edit rewrites a blank page"
        )

    def test_the_instruction_is_cleared_once_applied(self) -> None:
        """Otherwise the next run re-applies an edit the lead already received,
        and the job can never be redelivered safely."""
        store = _Store(self._edit_row())

        def edit(ctx: PipelineContext) -> StageResult:
            ctx.draft_md = "# Edited page\n\nWith the change."
            return ctx.record(StageResult("guided_edit", outcome="ok"))

        _run(store, {"guided_edit": edit, "gate": _stage("gate", "ok")})
        assert store.final("edit_instruction") == ""

    def test_a_drafting_job_with_no_instruction_is_still_a_no_op(self) -> None:
        """The redelivery guard must not be weakened into nothing."""
        store = _Store(_row(status="drafting", edit_instruction=""))
        outcome = _run(store, {"gate": _stage("gate", "ok")})
        assert outcome.state == "noop"

    def test_the_row_says_it_is_applying_edits_while_it_does(self) -> None:
        store = _Store(self._edit_row())

        def edit(ctx: PipelineContext) -> StageResult:
            ctx.draft_md = "# Edited"
            return ctx.record(StageResult("guided_edit", outcome="ok"))

        _run(store, {"guided_edit": edit, "gate": _stage("gate", "ok")})
        assert any("edit" in s.lower() for s in store.stages)


class TestAnUnscoredPageDoesNotShowAnOldScore:
    """Measured on a real edit run: the gate degrades to NO verdict when it has no
    research brief - exactly the case on the edit path, where research does not
    re-run. The scorecard emptied while `qa_weighted_total` still read 84 from
    before the change, so the headline number described a draft that no longer
    existed."""

    def _run_editing(self, gate_data: dict[str, Any]) -> _Store:
        store = _Store(_row(
            status="drafting", stage="Edit requested",
            edit_instruction="Cut the second section.",
            draft_md="# Page\n\nOriginal text.",
            qa_weighted_total=84,
        ))

        def edit(ctx: PipelineContext) -> StageResult:
            ctx.draft_md = "# Page\n\nEdited text."
            return ctx.record(StageResult("guided_edit", outcome="ok"))

        _run(store, {"guided_edit": edit, "gate": _stage("gate", "degraded", **gate_data)})
        return store

    def test_a_gate_with_no_verdict_clears_the_previous_number(self) -> None:
        store = self._run_editing({})
        assert store.final("qa_weighted_total") is None, "a stale score is a false claim"

    def test_the_row_says_it_was_not_re_scored(self) -> None:
        store = self._run_editing({})
        assert "not re-scored" in store.final("stage")

    def test_a_gate_that_did_score_still_writes_its_number(self) -> None:
        store = self._run_editing({"weighted_total": 91.0, "passed": True})
        assert store.final("qa_weighted_total") == 91.0


class TestTheKeywordMapReachesTheRow:
    """The publish leg reads `keyword_map` for the WordPress focus keyword and the
    post's tags, and the reviewer's keyword panel is that same column. v1 wrote it
    and this engine did not - so from the moment it became the default, every page
    it drafted pushed with no focus keyword, no tags, and an empty keyword panel.

    The existing WordPress guard test seeds a v1-shaped row, so the suite stayed
    green with the defect live. These assert the WRITE."""

    class _Terms:
        primary = "emergency plumber dallas"
        secondary: ClassVar[list[str]] = ["24 hour plumber dallas"]
        semantic_entities: ClassVar[list[str]] = ["slab leak"]
        questions: ClassVar[list[str]] = ["who do I call at night?"]

    class _Brief:
        intent = "transactional"
        intent_confidence = 0.9
        fanout: ClassVar[list[str]] = []
        low_confidence = False
        degraded = False
        notes: ClassVar[list[str]] = []

        def __init__(self, terms: Any) -> None:
            self.terms = terms
            self.content_format = type("F", (), {"recommended": "service", "confidence": 0.8})()
            self.cluster = type("C", (), {"pillar": "emergency plumbing", "supporting": []})()
            self.winnability = type(
                "W", (), {"client_da": None, "neutral_da_assumed": 30.0, "targets": []},
            )()

    def _run_with_brief(self, brief: Any) -> _Store:
        store = _Store(_row())

        def research(ctx: PipelineContext) -> StageResult:
            if brief is not None:
                ctx.brief["research"] = brief
            return ctx.record(StageResult("research", outcome="ok"))

        def draft(ctx: PipelineContext) -> StageResult:
            ctx.draft_md = "# Page\n\nWords."
            return ctx.record(StageResult("draft", outcome="ok"))

        _run(store, {"research": research, "draft": draft, "gate": _stage("gate", "ok")})
        return store

    def test_the_operators_keyword_reaches_the_column_publish_reads(self) -> None:
        store = self._run_with_brief(self._Brief(self._Terms()))
        km = store.final("keyword_map")
        assert km["primary"] == "emergency plumber dallas"
        assert km["secondary"] == ["24 hour plumber dallas"]
        assert km["intent"] == "transactional"

    def test_a_run_without_research_does_not_wipe_the_stored_map(self) -> None:
        """The EDIT path deliberately skips research. Writing an empty map there
        would strip the SEO fields off a page for the crime of being edited."""
        store = self._run_with_brief(None)
        assert store.final("keyword_map") is None

    def test_a_malformed_brief_loses_the_map_not_the_page(self) -> None:
        store = self._run_with_brief(object())   # no .terms
        assert store.final("keyword_map") is None
        assert store.final("status") == "needs_review", "the page must still land"


class TestTheStoredDraftCarriesNoMachineDashes:
    """v1 GUARANTEED a stored draft had no em or en dash - the clearest
    machine-writing tell and the one a client notices. This engine dropped the
    guarantee, so its pages shipped with them. The strip is pure, deterministic
    and free, so it applies to everything the reader sees."""

    def _persisted(self, text: str, title: str = "", meta: str = "") -> _Store:
        store = _Store(_row())

        def draft(ctx: PipelineContext) -> StageResult:
            ctx.draft_md = text
            ctx.title = title
            ctx.meta_description = meta
            return ctx.record(StageResult("draft", outcome="ok"))

        _run(store, {"draft": draft, "gate": _stage("gate", "ok")})
        return store

    #: Written as code points, not literals: ruff flags an ambiguous dash in
    #: source, and a test about dashes should not smuggle one in invisibly.
    EM = "\u2014"
    EN = "\u2013"

    def test_the_body_is_stripped(self) -> None:
        store = self._persisted(f"We answer fast {self.EM} usually within the hour.")
        body = store.final("draft_md")
        assert self.EM not in body and self.EN not in body
        assert "-" in body, "the sentence must survive, not just the dash"

    def test_the_title_and_meta_are_stripped_too(self) -> None:
        """They are what shows in the SERP, so a dash there is the most visible
        place it could possibly appear."""
        store = self._persisted(
            "body",
            title=f"Plumber {self.EM} Dallas",
            meta=f"Fast help {self.EM} any hour",
        )
        assert self.EM not in store.final("outline")["meta"]["title"]
        assert self.EM not in store.final("outline")["meta"]["description"]

    def test_a_numeric_range_collapses_rather_than_becoming_spaced(self) -> None:
        store = self._persisted(f"Most repairs run 5{self.EN}10 hours.")
        assert "5-10" in store.final("draft_md")


class TestTheEntityPictureIsKept:
    """The gate computes entity coverage on its way to a score and used to throw
    it away with its local content object - so the `entities` column stayed empty
    for every page this engine wrote, and the reviewer's entity tab had nothing in
    it, while the numbers existed inside the stage that had just run."""

    def test_the_coverage_is_persisted(self) -> None:
        store = _Store(_row())

        def draft(ctx: PipelineContext) -> StageResult:
            ctx.draft_md = "# Page\n\nWords."
            return ctx.record(StageResult("draft", outcome="ok"))

        _run(store, {
            "draft": draft,
            "gate": _stage(
                "gate", "ok", weighted_total=80.0, passed=False,
                entity_coverage={
                    "table_stakes": ["licence"], "differentiators": ["night crew"],
                    "covered": ["licence"], "missing": ["night crew"],
                    "primary_density": 1.4, "local_uniqueness": {},
                },
            ),
        })
        ec = store.final("entity_coverage")
        assert ec["covered"] == ["licence"]
        assert ec["missing"] == ["night crew"]

    def test_it_does_not_pollute_the_qa_scorecard(self) -> None:
        """It travels on the gate's data to get here; it must not end up stored as
        a QA dimension, where it would read as an unscored criterion."""
        store = _Store(_row())

        def draft(ctx: PipelineContext) -> StageResult:
            ctx.draft_md = "words"
            return ctx.record(StageResult("draft", outcome="ok"))

        _run(store, {
            "draft": draft,
            "gate": _stage("gate", "ok", weighted_total=80.0, entity_coverage={"covered": []}),
        })
        assert "entity_coverage" not in store.final("qa_score")
