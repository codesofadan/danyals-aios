"""Do the running Celery workers, between them, consume every queue jobs route to?

The defect this exists for (observed 2026-09-01): three workers were running, all
started with ``-Q celery``, so the ``long`` and ``browser`` queues had NO consumer —
three messages sat stranded in Redis (two of them the liveness re-check that writes
``live_url``), nothing errored, nothing dead-lettered, and the platform simply looked
idle. Coverage is a property of the SET of workers, which no single worker's config can
check; this module checks the set, from `ps` output, and `scripts/dev-doctor.sh` runs it.

The required set is DERIVED from :class:`app.jobs.status.JobQueue` plus Celery's legacy
default queue (kept deliberately — renaming it strands in-flight messages mid-deploy,
see ``workers/celery_app.py``). Hard-coding the list here would recreate the drift this
file guards against.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable

from app.jobs.status import JobQueue

#: Celery's default queue name. `task_default_queue` is intentionally unchanged.
LEGACY_DEFAULT_QUEUE = "celery"

_Q_FLAG = re.compile(r"(?:^|\s)(?:-Q|--queues)[=\s]+([\w,.-]+)")


def required_queues() -> frozenset[str]:
    """Every queue a job can be routed to."""
    return frozenset({q.value for q in JobQueue} | {LEGACY_DEFAULT_QUEUE})


def consumed_queues(worker_ps_lines: Iterable[str]) -> set[str]:
    """The union of queues the given worker command lines consume.

    A worker line with NO ``-Q`` consumes only the default queue — that is Celery's
    behavior, not an assumption.
    """
    consumed: set[str] = set()
    for line in worker_ps_lines:
        if "celery" not in line or "worker" not in line:
            continue
        match = _Q_FLAG.search(line)
        if match:
            consumed |= {q.strip() for q in match.group(1).split(",") if q.strip()}
        else:
            consumed.add(LEGACY_DEFAULT_QUEUE)
    return consumed


def starved_queues(worker_ps_lines: Iterable[str]) -> list[str]:
    """Required queues no running worker consumes. Empty list == healthy.

    With zero worker lines, EVERY queue is starved — an idle dev box gets told to
    start a worker rather than a clean bill of health.
    """
    return sorted(required_queues() - consumed_queues(worker_ps_lines))


def main() -> int:
    """Read `ps` lines on stdin; report; exit 1 when any queue is starved."""
    lines = [line.rstrip("\n") for line in sys.stdin if line.strip()]
    starved = starved_queues(lines)
    workers = [line for line in lines if "celery" in line and "worker" in line]
    if not workers:
        print("no celery workers are running - every queue is starved:", ", ".join(starved))
        return 1
    if starved:
        print(
            f"{len(workers)} worker(s) running but these queues have NO consumer: "
            + ", ".join(starved)
        )
        print("jobs routed there sit unread forever and the platform looks idle.")
        return 1
    print(f"{len(workers)} worker(s) cover all queues: {', '.join(sorted(required_queues()))}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via scripts/dev-doctor.sh
    raise SystemExit(main())
