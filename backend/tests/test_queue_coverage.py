"""The worker-set coverage check — the 2026-09-01 starved-queue outage, in test form.

Three workers all ran ``-Q celery``; ``long`` and ``browser`` had no consumer, and the
liveness re-check that writes ``live_url`` sat stranded in Redis. Each fixture below is
a real `ps` shape; the required-set test derives from ``JobQueue`` so adding a queue to
the enum automatically makes an uncovered dev box fail the doctor.
"""

from __future__ import annotations

import pytest

from app.jobs.queue_coverage import (
    LEGACY_DEFAULT_QUEUE,
    consumed_queues,
    required_queues,
    starved_queues,
)
from app.jobs.status import JobQueue

pytestmark = pytest.mark.unit

FULL = "python -m celery -A workers.celery_app worker -l info -Q celery,interactive,standard,long,browser -c 4"
ONLY_CELERY = "python -m celery -A workers.celery_app worker -l info -Q celery -c 8"


def test_required_set_is_derived_from_the_enum_not_hardcoded() -> None:
    assert required_queues() == frozenset({q.value for q in JobQueue} | {LEGACY_DEFAULT_QUEUE})
    # The enum currently carries the four duration classes; if one is added, coverage
    # of the old five must stop counting as healthy — which this equality guarantees.


def test_the_actual_outage_shape_fails() -> None:
    """Three workers, all -Q celery: exactly what `ps` showed that night."""
    lines = [ONLY_CELERY, ONLY_CELERY, ONLY_CELERY]
    assert starved_queues(lines) == sorted({"browser", "interactive", "long", "standard"})


def test_one_full_coverage_worker_passes() -> None:
    assert starved_queues([FULL]) == []


def test_coverage_is_a_property_of_the_set_not_any_single_worker() -> None:
    split = [
        "celery -A workers.celery_app worker -Q celery,interactive,standard -c 8",
        "celery -A workers.celery_app worker -Q long -c 2",
        "celery -A workers.celery_app worker -Q browser -c 1",
    ]
    assert starved_queues(split) == []


def test_a_worker_with_no_q_flag_consumes_only_the_default() -> None:
    assert consumed_queues(["celery -A workers.celery_app worker -l info"]) == {"celery"}


def test_non_worker_lines_are_ignored() -> None:
    lines = ["grep celery", "uvicorn app.main:app --port 8000", "celery -A x beat -l info"]
    assert consumed_queues(lines) == set()


def test_an_idle_box_is_not_a_healthy_box() -> None:
    assert starved_queues([]) == sorted(required_queues())


def test_the_equals_form_of_the_flag_parses() -> None:
    assert consumed_queues(["celery worker --queues=long,browser"]) == {"long", "browser"}
