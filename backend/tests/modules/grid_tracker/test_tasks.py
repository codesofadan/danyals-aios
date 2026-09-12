"""The grid worker: what gets written when things go wrong.

NO DB, NO network, NO broker: the store is in-memory, the gate is a stub, and the
provider is a scripted double. The Celery entry points are invoked as plain functions -
``.delay`` is never called.

**THE MOST IMPORTANT TEST IN THIS FILE** is
``test_a_failed_probe_is_recorded_as_error_never_as_absent``.

``absent`` means "we looked and the business was not in the pack" - a real, chartable
observation. ``error`` means "we never looked". If a failed probe were written as
absent, a rate-limited afternoon would render on a client's heat map as their service
area collapsing, and because points are append-only the fabricated collapse becomes
permanent history. That is the same defect class as ``local_seo``'s null-rank contract,
restated for a shape that must keep its holes rather than drop them.

The others are the ones that cost money or leave a mess when they break:

* Refuse BEFORE claiming / opening a run when no coordinate-capable provider exists -
  the ``rank_tracker`` lesson (refusing after the claim burns the slot AND fills an
  evidence table with synthetic positions).
* A gate block mid-run KEEPS what was already bought and reports the rest as
  unmeasured, rather than discarding paid observations or completing a partial grid.
* Only a probe that actually answered is charged.
* Never re-raise (``task_acks_late`` would redeliver and re-probe up to 41 points).
* A redelivery ADOPTS the in-flight run row instead of opening a second one.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.grid_tracker.provider import GridProbeResult
from app.modules.grid_tracker.tasks import dispatch_due_grids, execute_grid_run

pytestmark = pytest.mark.unit


class FakeStore:
    """In-memory ``ServiceGridStore``. Records every write so the test can assert on
    what would have reached the database."""

    def __init__(self, definition: dict[str, Any] | None = None) -> None:
        self._definition = definition
        self.points: list[dict[str, Any]] = []
        self.finalized: dict[str, Any] | None = None
        self.opened: list[str] = []
        self.open_runs: list[str] = []
        self.claimed: list[dict[str, Any]] = []

    def definition(self, definition_id: str) -> dict[str, Any] | None:
        return self._definition

    def open_run(self, definition_id: str, *, job_run_id: str | None = None) -> str | None:
        run_id = f"run-{len(self.opened) + 1}"
        self.opened.append(run_id)
        return run_id

    def open_run_ids(self, definition_id: str) -> list[str]:
        return list(self.open_runs)

    def record_point(self, run_id: str, **kw: Any) -> None:
        self.points.append({"run_id": run_id, **kw})

    def finalize_run(self, run_id: str, **kw: Any) -> None:
        self.finalized = {"run_id": run_id, **kw}

    def close_run_without_probing(self, run_id: str, **kw: Any) -> None:
        self.finalized = {"run_id": run_id, **kw}

    def claim_due_definitions(self, limit: int) -> list[dict[str, Any]]:
        return self.claimed[:limit]


class ScriptedProvider:
    """Returns a scripted result per probe, in order; repeats the last one."""

    provider = "scripted"
    enabled = True

    def __init__(self, results: list[GridProbeResult], *, cost: float = 0.003) -> None:
        self._results = results
        self._cost = cost
        self.calls = 0

    def estimated_cost(self) -> float:
        return self._cost

    def probe(self, **kw: Any) -> GridProbeResult:
        index = min(self.calls, len(self._results) - 1)
        self.calls += 1
        return self._results[index]


class RaisingProvider:
    provider = "raising"
    enabled = True

    def estimated_cost(self) -> float:
        return 0.003

    def probe(self, **kw: Any) -> GridProbeResult:
        raise RuntimeError("connection reset")


class StubGate:
    """Allows ``allow_first`` evaluations, then blocks. Records commits."""

    def __init__(self, allow_first: int = 1_000) -> None:
        self._allow_first = allow_first
        self.evaluations = 0
        self.commits: list[float] = []

    def evaluate(self, ctx: Any) -> Any:
        self.evaluations += 1
        allowed = self.evaluations <= self._allow_first

        class _D:
            pass

        d = _D()
        d.allowed = allowed  # type: ignore[attr-defined]
        d.outcome = "ok" if allowed else "blocked_budget"  # type: ignore[attr-defined]
        return d

    def commit(self, ctx: Any, amount: float) -> None:
        self.commits.append(amount)


DEFINITION = {
    "id": "gd-1",
    "client_id": "cl-1",
    "client_name": "Acme Dental",
    "center_lat": 24.8607,
    "center_lng": 67.0011,
    # A 3x3 SQUARE - the shape 0143 made the default and what the market ships. Small
    # enough to assert on exhaustively, and the same 9 points the old 1-ring fixture
    # had, so every count below still reads the same.
    "shape": "square",
    "grid_size": 3,
    "rings": 1,
    "ring_spacing_km": 1.0,
    "keyword": "dentist karachi",
    "place_id": "ChIJ-test",
    "nap_name": "Acme Dental",
}


def run(store: FakeStore, provider: Any, gate: Any, **kw: Any) -> dict[str, Any]:
    return execute_grid_run(
        store, provider, gate, settings=None, definition_id="gd-1", **kw  # type: ignore[arg-type]
    )


class TestTheErrorAbsenceBoundary:
    def test_a_failed_probe_is_recorded_as_error_never_as_absent(self) -> None:
        """THE TEST THE MODULE'S HONESTY RESTS ON.

        Every probe fails. Not one point may be written as 'absent' - that would say
        the business was looked for and not found, which never happened.
        """
        store = FakeStore(DEFINITION)
        provider = ScriptedProvider([GridProbeResult(status="error", error="timeout")])
        run(store, provider, StubGate())

        assert len(store.points) == 9
        assert {p["status"] for p in store.points} == {"error"}
        assert not any(p["status"] == "absent" for p in store.points)
        # And no point carries a rank, so nothing downstream can read a position.
        assert all(p["rank"] is None for p in store.points)
        assert store.finalized is not None
        assert store.finalized["status"] == "failed"
        assert store.finalized["reason"], "0138 refuses a non-clean status with no reason"

    def test_a_provider_that_raises_is_still_an_error_not_an_absence(self) -> None:
        """A provider that throws instead of returning an error result must land in
        exactly the same place - otherwise the honest branch depends on the vendor
        client being well-behaved."""
        store = FakeStore(DEFINITION)
        run(store, RaisingProvider(), StubGate())

        assert {p["status"] for p in store.points} == {"error"}
        assert all(p["error"] for p in store.points), "an error point must say why"

    def test_a_genuine_absence_is_still_recorded_as_absent(self) -> None:
        """The contract cuts both ways: a real "not in the pack" must not be hidden as
        an error, or a business that genuinely lost visibility would look merely
        unmeasured."""
        store = FakeStore(DEFINITION)
        run(store, ScriptedProvider([GridProbeResult(status="absent")]), StubGate())

        assert {p["status"] for p in store.points} == {"absent"}
        assert store.finalized is not None
        assert store.finalized["status"] == "completed"
        assert store.finalized["points_absent"] == 9
        assert store.finalized["points_error"] == 0
        assert store.finalized["share_top3"] == pytest.approx(0.0), (
            "measured everywhere, in the pack nowhere - a real 0, not a null"
        )


class TestSpend:
    def test_only_a_probe_that_answered_is_charged(self) -> None:
        """A failed probe bought nothing. Charging for it would bill a client for a
        measurement they did not receive."""
        store = FakeStore(DEFINITION)
        gate = StubGate()
        provider = ScriptedProvider([
            GridProbeResult(status="ranked", rank=1),
            GridProbeResult(status="error", error="timeout"),
        ])
        run(store, provider, gate)

        # First probe ranked (charged); the rest errored (not charged).
        assert len(gate.commits) == 1
        assert store.finalized is not None
        assert store.finalized["cost_usd"] == pytest.approx(0.003)

    def test_a_gate_block_keeps_everything_already_measured(self) -> None:
        """The budget ran out after 4 probes. Those 4 were bought and are real; the
        remaining 5 were never looked at. Discarding the 4 would burn money for
        nothing, and completing all 9 would invent five observations."""
        store = FakeStore(DEFINITION)
        gate = StubGate(allow_first=4)
        run(store, ScriptedProvider([GridProbeResult(status="ranked", rank=2)]), gate)

        assert len(store.points) == 4, "only the probes that ran are recorded"
        assert store.finalized is not None
        assert store.finalized["status"] == "degraded"
        assert store.finalized["points_ranked"] == 4
        assert store.finalized["points_error"] == 5, "the unreached points are unmeasured"
        assert "spend gate" in store.finalized["reason"], (
            "the reason must name the BUDGET, not blame the provider - they send an "
            "operator to different places"
        )

    def test_the_gate_is_consulted_before_every_probe(self) -> None:
        """Once per run would mean a client with budget for 6 more probes either
        spends 41 or spends none."""
        store = FakeStore(DEFINITION)
        gate = StubGate()
        provider = ScriptedProvider([GridProbeResult(status="ranked", rank=1)])
        run(store, provider, gate)
        assert gate.evaluations == 9 == provider.calls


class TestRunLifecycle:
    def test_a_redelivery_adopts_the_open_run_instead_of_opening_a_second(self) -> None:
        """``task_acks_late`` redelivers. Opening a second run row would double-count
        the grid's history and leave an orphan for the reaper to sweep."""
        store = FakeStore(DEFINITION)
        run(store, ScriptedProvider([GridProbeResult(status="absent")]), StubGate(),
            run_id="run-existing")

        assert store.opened == [], "no new run row may be opened when one is adopted"
        assert {p["run_id"] for p in store.points} == {"run-existing"}

    def test_a_missing_definition_is_skipped_not_crashed(self) -> None:
        store = FakeStore(None)
        result = run(store, ScriptedProvider([GridProbeResult(status="absent")]), StubGate())
        assert result["state"] == "skipped"
        assert store.points == [] and store.finalized is None

    def test_every_point_of_the_grid_is_probed_and_recorded(self) -> None:
        """Nothing is silently lost: 1 ring is 9 points, and 9 rows are written."""
        store = FakeStore(DEFINITION)
        run(store, ScriptedProvider([GridProbeResult(status="ranked", rank=3)]), StubGate())
        labels = {p["label"] for p in store.points}
        assert len(labels) == 9
        # Spreadsheet labels, row-major from the north-west: B2 is the centre cell of a
        # 3x3 and sits exactly on the business.
        assert "A1" in labels and "B2" in labels and "C3" in labels

    def test_it_never_raises_whatever_the_provider_does(self) -> None:
        """With ``task_acks_late`` an escaping exception redelivers the job and
        re-probes every point that already succeeded - a second bill for the same
        heat map."""
        store = FakeStore(DEFINITION)
        result = run(store, RaisingProvider(), StubGate())
        assert result["state"] == "failed"


class TestDispatch:
    def test_one_grid_failing_to_enqueue_does_not_strand_the_batch(self) -> None:
        store = FakeStore(DEFINITION)
        store.claimed = [{"id": "gd-1"}, {"id": "gd-2"}, {"id": "gd-3"}]
        sent: list[str] = []

        def enqueue(definition_id: str) -> None:
            if definition_id == "gd-2":
                raise RuntimeError("broker down")
            sent.append(definition_id)

        out = dispatch_due_grids(store, batch=10, enqueue=enqueue)
        assert sent == ["gd-1", "gd-3"]
        assert out == ["gd-1", "gd-3"], "the failed one is not reported as dispatched"

    def test_the_batch_bounds_the_fan_out(self) -> None:
        store = FakeStore(DEFINITION)
        store.claimed = [{"id": f"gd-{i}"} for i in range(50)]
        out = dispatch_due_grids(store, batch=5, enqueue=lambda _: None)
        assert len(out) == 5
