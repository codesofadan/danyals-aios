# The job contract

*Spine item 1 of the AIOS v2 recovery plan (P0-3). Migration `0080_job_contract.sql`.*

Every background job in the platform runs inside one envelope: it is claimed exactly
once, retried a bounded number of times, capped per client, cancellable, and it ends
in one of five terminal states from a single vocabulary — with a dead letter if it
did not end well.

## Why

Before this, the job layer had 39 Celery tasks and:

| Missing | Consequence |
|---|---|
| No idempotency key | An at-least-once broker could run the same paid work twice |
| No retry accounting | A transient provider blip was a permanent failure |
| No dead-letter queue | A failure left no replayable record anywhere |
| No correlation id | A fan-out could not be reassembled after the fact |
| No per-client cap | One client's 300-page bulk run starved every other client |
| No shared vocabulary | `audit_status` says `done`, `site_job_status` says `completed`, `scheduled_job_status` says `ok` — and **none of them can say `degraded`** |

That last row is the expensive one. A WordPress publish that reached no website at all
recorded `done`, because `done` was the only terminal word available.

## The vocabulary — `app/jobs/status.py`

| State | Means |
|---|---|
| `queued` | Waiting. Either never started, or deferred by a retry or a concurrency cap. |
| `running` | In flight, heartbeating. |
| `completed` | **The promise was kept in full.** The only value that may render as success. |
| `degraded` | Ran to the end, and part of the promise was not kept. **Always carries a reason and a reason_code.** |
| `blocked` | Deliberately did not spend: a cost gate, a missing credential, an automation ceiling, a concurrency wait that ran out. **Always carries a reason and a reason_code.** |
| `failed` | Unrecoverable within the retry budget. Always has an `error_type` and a dead letter. |
| `cancelled` | A human stopped it. |

**The one rule:** `is_success()` returns `True` for `completed` and nothing else.
Anything that renders a green tick, increments a "jobs completed" count, or tells a
client their work is live must go through it.

The database enforces the same thing independently: `job_runs_reason_required_ck`
rejects a `degraded` or `blocked` row with no reason, `job_runs_error_required_ck`
rejects a `failed` row with no error type, and `job_runs_finished_ck` makes terminal
and `finished_at` a biconditional. A lie is not representable, not merely discouraged.

### A refusal is typed, not just described

`degraded` and `blocked` carry **two** fields, and both are required:

* `reason` — prose, for a person: *"published 2 of 10 pages; 8 rejected by the site's REST API"*.
* `reason_code` — a stable snake_case identifier, for everything else: `wp_rest_rejected`.

Prose alone is un-countable. Every call site phrases "no WordPress credentials"
differently, so with only a sentence the sole way to ask *how often* that block
happens is to grep free text — which is how a recurring, fixable refusal stays
invisible for months. `"47 publishes blocked on wp_credentials_missing this week"` is
a task; forty-seven differently-worded sentences are not.

The format (`^[a-z][a-z0-9_]{2,63}$`) is validated in Python at the call site *and* by
`job_runs_reason_code_format_ck`, so a sentence in that slot is a `ValueError` rather
than a constraint violation at the moment a job is recording why it refused to spend.

`reason_code` is deliberately **not** a Postgres enum. The closed vocabularies belong
to the modules — R3B specifies fourteen `blocked_reason` values for content publishing
alone — and pinning them here would force a migration on the contract every time a
module learns a new way to refuse. The runner's own two are named constants:
`BLOCKED_CONCURRENCY_CAP` and `FAILED_HEARTBEAT_LOST`; the DLQ additionally
distinguishes `retries_exhausted` from `permanent_error`, because those are different
problems with different fixes.

*Added after the Phase 1 research wave, whose cross-track index requires that "every
block is a typed refusal with a stable machine code" — while the contract was still
uncommitted and nothing depended on it. Later it would have been a data migration.*

`DOMAIN_TERMINAL_MAP` translates each module's own terminal words into this
vocabulary, so a rollup does not have to learn six of them. Modules keep their own
enums — `needs_review` is a real human-workflow state this vocabulary has no word for
and should not.

## Queues — by duration, not by module

| Queue | Budget | For |
|---|---|---|
| `interactive` | 60s | A user is waiting |
| `standard` | 5m | The default: ordinary API-backed work |
| `long` | 30m | Audits, bulk content, imports |
| `browser` | 2h | Anything driving Chromium — its own worker image |

Splitting by module puts a 2-second webhook behind a 40-minute crawl; with
`worker_prefetch_multiplier=1` that webhook waits for the crawl. Splitting by duration
means a slow class can only starve itself.

**INVARIANT (#8, extended).** `broker_transport_options.visibility_timeout` must be
≥ the longest `task_time_limit`, or a job that outruns the window is redelivered to a
second worker and runs twice. It is now *derived* — `BROKER_VISIBILITY_TIMEOUT =
max(TIME_LIMITS) + 300` — and `tests/test_job_queues.py` asserts the two cannot drift.

**`task_default_queue` is deliberately left at Celery's own `celery`.** Renaming it
would strand every message already on the old name at deploy time. Legacy tasks keep
that queue until each is migrated; the deployed worker's `-Q` lists all five, and a
test reads `infra/systemd/aios-worker.service` to prove it.

## Writing a job

```python
from app.jobs import JobOutcome, JobQueue, JobTarget
from app.jobs.celery_task import aios_job

def _target(client_id: str, day: str) -> JobTarget:
    return JobTarget(
        idempotency_key=f"rank.sweep:{client_id}:{day}",
        client_id=client_id,
        scope_id=client_id,
    )

@aios_job(
    name="check_keyword_rank",       # the pinned Celery task name
    job_name="rank.check",           # the LOGICAL job an operator groups by
    queue=JobQueue.STANDARD,
    max_attempts=3,
    client_concurrency=4,
    scope_type="client",
    target=_target,
)
def check_keyword_rank(ctx, client_id: str, day: str) -> JobOutcome:
    for keyword in keywords:
        ctx.checkpoint()              # heartbeat + cancellation, both throttled
        ...
    if skipped:
        return JobOutcome.degraded(
            "serp_data_missing",                                  # machine-readable
            f"{len(skipped)} keywords had no SERP data",          # human-readable
            cost_usd=spend,
        )
    return JobOutcome.completed(f"checked {n} keywords", cost_usd=spend)
```

What the body no longer contains: no try/except that swallows the error, no manual
ledger write, no "never re-raise" boilerplate, no status string.

### What a job may raise

| Exception | Result |
|---|---|
| `JobBlocked(reason_code, reason)` | `blocked`. Never retried — retrying a refusal just refuses again. |
| `JobCancelled()` | `cancelled`. Raised by `ctx.check_cancelled()`. |
| `RetryableJobError(msg, retry_after=None)` | Retried with exponential backoff + jitter while the budget lasts, then `failed` + dead-lettered. |
| `PermanentJobError(msg)` | `failed` + dead-lettered immediately. |
| **anything else** | Treated as **permanent**. |

That last line is the conservative default and it is deliberate: an unclassified
exception is one nobody has reasoned about, and re-running unreasoned code against a
paid provider is how one bug becomes three invoices. Declare `retry_on=(...)` for
provider exceptions you would rather not translate.

### The idempotency key is the one thing to get right

It must be a deterministic function of the **work**, not of the call. Two enqueues of
the same unit produce the same key; two genuinely different units never collide.
Including a date or a period is usually what makes a recurring job safe to re-fire.

A `None` key opts out entirely — correct for a heartbeat sweep, **wrong for anything
that spends money**.

For a fan-out, use `enqueue_child(ctx, task, ..., key_suffix=...)`: it inherits the
correlation id and derives the child key from the parent's, so re-running the parent
produces the same children rather than a second fan-out beside the first.

### Cancellation is cooperative

A Celery task cannot be safely killed part-way through writing to a client's website.
`POST /jobs/runs/{id}/cancel` sets a flag: a queued run never starts, and a running
one stops at its next `ctx.checkpoint()`. **A job that never checkpoints can never be
stopped**, so anything that loops must.

### Heartbeats and the reaper

`ctx.checkpoint()` also stamps liveness. A worker killed by the OOM reaper or a host
reboot never writes a terminal state, and because `start()` counts `running` rows
against the per-client cap, a few such rows silently drop that client's throughput to
zero. `reap_stale_job_runs` fails any run whose heartbeat has been silent past its
queue's budget plus 300s of grace.

## The per-client concurrency cap

`start()` is a check-then-set — count this client's in-flight runs on this queue, then
transition — inside **one transaction under a `pg_advisory_xact_lock` keyed on
(client, queue)**. Without that serialisation, N workers picking up N of a client's
jobs at the same instant would all read a count below the cap and all start.

A capped run is *deferred*, not failed, and a deferral does not consume an attempt.
After `max_queue_seconds` of waiting it becomes `blocked` with a reason naming the
cap — because an hour of silent waiting is indistinguishable from a lost job.

Platform-wide jobs (`client_id IS NULL`) are never capped: a sweep that belongs to no
tenant must not consume a tenant's slots.

## The dead-letter queue

Every `failed` run writes a `job_dead_letters` row carrying the payload needed to
replay it, the sanitized error and traceback, and the facts copied from the run itself
so the two cannot disagree.

`POST /jobs/dead-letters/{id}/replay` re-runs it with a **fresh** key,
`replay:<dead_letter_id>`. Reusing the original would find the old terminal run and
skip the work silently — the replay would report success and do nothing. It also
refuses an already-replayed letter and does not enqueue if it loses the race, because
this is the one operator action that deliberately re-spends money.

`POST /jobs/dead-letters/{id}/resolve` requires a written decision (schema **and**
CHECK constraint). A queue closed with no reasons written is a graveyard: the next
person cannot tell "we fixed the bug" from "we gave up".

## The operator surface

| Endpoint | Auth | Answers |
|---|---|---|
| `GET /jobs/summary` | any staff | Runs and spend per terminal state, plus open DLQ depth |
| `GET /jobs/runs` | any staff | The board; `?needsAttention=true` is the daily view; `?correlationId=` reassembles a fan-out |
| `GET /jobs/runs/{id}` | any staff | One run |
| `GET /jobs/in-flight` | any staff | What the concurrency cap is acting on |
| `GET /jobs/dead-letters` | any staff | Lost work, **oldest first** |
| `POST /jobs/runs/{id}/cancel` | lead | Cooperative stop |
| `POST /jobs/dead-letters/{id}/replay` | lead | Re-run |
| `POST /jobs/dead-letters/{id}/resolve` | lead | Close with a decision |

A portal client holds no `view_reports` and has no select policy on either table, so
the tenant boundary is Postgres, not the router.

## Migrating an existing task

1. Extract the pure core if it is not already separate (the worker template here
   already does this).
2. Delete the manual ledger write, the swallow-everything `except`, and the status
   strings. Return a `JobOutcome`.
3. Write a `target()` that derives the idempotency key and the client from the call's
   own arguments.
4. Choose the duration class from the job's real p99, not its average.
5. Choose `max_attempts`: 1 for anything not safely repeatable, 3 for provider-backed
   work.
6. Add `ctx.checkpoint()` to every loop.
7. Set `client_concurrency` for anything a client can trigger in bulk.

Do them one at a time. The router falls through for unregistered tasks, so a
half-migrated system works.

## What this does NOT do yet

- **The beat schedule is still empty** (`beat_schedule = {}`, 9 tests red by design).
  Correct ordering, per the plan: the contract lands first, because restoring a
  schedule over a ledger that still mis-reports is how a double-spend happens.
- **No existing task has been migrated.** The contract is the envelope; moving the 39
  tasks into it is per-module work.
- **`content_status` still has no `degraded` label** (P0-4), so a credential-less
  publish still records `done` on the module table. Until that lands, a job records
  its degradation on the `job_runs` row — the rollup is honest even while the module
  table is not.
- **The browser queue is not yet its own image.** It is a separate queue precisely so
  it can be peeled onto its own worker; today one unit serves all four.
- **Cost is recorded, not gated, here.** `JobOutcome.cost_usd` writes the actual spend
  to the run; the cost gate itself (`app/services/cost_gate.py`) is spine item 8.
