"""citation_submit runs under the job contract — the invisible-campaign fix.

Before 2026-09-02 this task was a bare ``@celery_app.task``: no job_runs row, no
dead-letter, no reaper coverage, invisible in Operations. A 45-row campaign whose
queue nobody consumed was indistinguishable from an idle platform. These tests go
red the moment the decorator is reverted or the outcome mapping starts calling a
routing verdict a success.
"""

from __future__ import annotations

import pytest

from app.jobs import JobQueue
from app.jobs.celery_task import TASK_SPECS
from app.modules.citations.tasks import _submit_outcome, _submit_target

pytestmark = pytest.mark.unit


def test_the_task_is_registered_under_the_contract_on_the_browser_queue() -> None:
    assert "citation_submit" in TASK_SPECS, "reverted to a bare @celery_app.task?"
    spec, target = TASK_SPECS["citation_submit"]
    assert spec.queue is JobQueue.BROWSER
    assert spec.job_name == "citations.submit"
    assert spec.max_attempts == 1  # the body owns never-re-raise / never-double-spend
    assert target is _submit_target


def test_idempotency_is_row_times_campaign() -> None:
    """A double-POSTed campaign cannot run a row twice; a LATER campaign that
    legitimately requeues the same citation gets a fresh key."""
    a = _submit_target("c1", client_id="cl", campaign_id="camp-1")
    b = _submit_target("c1", client_id="cl", campaign_id="camp-1")
    c = _submit_target("c1", client_id="cl", campaign_id="camp-2")
    assert a.idempotency_key == b.idempotency_key
    assert a.idempotency_key != c.idempotency_key
    assert a.client_id == "cl"
    # No campaign (a manual requeue) still gets a stable key.
    assert _submit_target("c1").idempotency_key == "citations.submit:c1:manual"


def test_only_a_real_submission_is_a_success() -> None:
    """The succeeded doctrine: ready_for_human is a ROUTING verdict — rendering it
    as completed would put a green tick on 43 rows nobody has worked yet."""
    assert _submit_outcome({"state": "submitted", "reason": ""}).succeeded
    assert _submit_outcome({"state": "unchanged", "reason": "submit_status=live"}).succeeded

    routed = _submit_outcome({"state": "ready_for_human", "reason": "no_verified_spec"})
    assert not routed.succeeded
    assert routed.reason_code == "no_verified_spec"

    blocked = _submit_outcome({"state": "blocked", "reason": "price_unknown"})
    assert not blocked.succeeded
    assert blocked.reason_code == "price_unknown"

    failed = _submit_outcome({"state": "failed", "reason": "TimeoutError('x')"})
    assert not failed.succeeded
    assert failed.error_type == "failed"


def test_an_unknown_state_fails_loudly_not_greenly() -> None:
    out = _submit_outcome({"state": "???", "reason": ""})
    assert not out.succeeded
    assert out.error_type == "unexpected_state"
