"""What an automation is allowed to DO: a closed vocabulary of real capabilities.

WHY A REGISTRY AND NOT A FREE-TEXT TASK NAME. An automation row that named its own
Celery task would let anyone with the admin UI schedule any task in the process,
with any arguments - including the ones that spend money per client. It would also
rot silently: a task renamed or removed leaves a scheduled automation that fires into
nothing, and the only symptom is work that stops happening.

So a `kind` is chosen from this list, the task behind it is code, and
``tests/test_automations.py`` asserts every task named here is actually registered
with Celery. A typo fails the build rather than a schedule.

EVERY ENTRY IS A TASK THAT ALREADY EXISTS. This layer schedules the platform's
existing capabilities; it does not invent new ones. The set is drawn from the beat
schedule that was parked on 2026-08-19 (kept verbatim in
``workers/celery_app._BEAT_SCHEDULE_DISABLED``), minus the infrastructure entries
that belong to the platform rather than to an operator's decision.

WHAT IS DELIBERATELY NOT HERE:

* ``reap_stale_job_runs`` - it repairs the job ledger, costs nothing, and must not be
  pausable from the surface it protects. It stays a static beat entry.
* ``watch_policy_sources`` - superseded by the daily generator and no longer scheduled
  anywhere.

`paid` is the honest half of this file. An automation that spends money on a client's
behalf every night is a different decision from one that sends a reminder, and the UI
has to be able to say which is which BEFORE someone enables it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

#: Whether a capability runs once for the platform, or once per selected client.
Scope = Literal["platform", "client"]


@dataclass(frozen=True, slots=True)
class Capability:
    kind: str
    task: str
    label: str
    #: What it does, in the words an operator needs to decide whether to enable it.
    description: str
    scope: Scope
    #: True when a run can spend metered provider budget. Shown before enabling.
    paid: bool
    #: A sensible starting cadence in seconds. The operator can change it; this is
    #: only what the create form offers first.
    default_interval_seconds: int
    #: Provider keys/config a run needs. Surfaced as "waiting on" rather than letting
    #: someone enable an automation that will only ever degrade.
    needs: tuple[str, ...] = ()


_ALL: Final[tuple[Capability, ...]] = (
    Capability(
        kind="content.publish_due",
        task="dispatch_scheduled_content_publishes",
        label="Publish scheduled content",
        description=(
            "Publishes content a lead has already approved, once its scheduled time "
            "arrives. It never publishes anything that has not passed human review."
        ),
        scope="platform",
        paid=False,
        default_interval_seconds=300,
    ),
    Capability(
        kind="citations.liveness_recheck",
        task="citation_liveness_recheck",
        label="Re-check citation listings are still live",
        description=(
            "Fetches listings that are due a re-check and confirms the business is "
            "still on the page. Without it, 'live' decays from an observation into a "
            "claim. Plain HTTP requests, so it spends nothing."
        ),
        scope="platform",
        paid=False,
        default_interval_seconds=3600,
    ),
    Capability(
        kind="context.compact",
        task="dispatch_context",
        label="Keep client context up to date",
        description=(
            "Folds recent activity into each client's living context so the AI "
            "surfaces read current facts rather than stale ones."
        ),
        scope="platform",
        paid=True,
        default_interval_seconds=1800,
        needs=("ANTHROPIC_API_KEY",),
    ),
    Capability(
        kind="context.reconcile",
        task="reconcile_context_vectors",
        label="Repair the context index",
        description=(
            "Detects and heals drift between the stored context and its search index. "
            "A safety net, not a producer."
        ),
        scope="platform",
        paid=False,
        default_interval_seconds=3600,
    ),
    Capability(
        kind="billing.mark_past_due",
        task="mark_past_due",
        label="Mark overdue invoices past due",
        description="One idempotent pass over invoices whose due date has gone by.",
        scope="platform",
        paid=False,
        default_interval_seconds=86_400,
    ),
    Capability(
        kind="backups.nightly",
        task="run_nightly_backup",
        label="Nightly backup",
        description=(
            "Backs the database up to off-site storage. Costs nothing and is the "
            "difference between a bad day and a lost business."
        ),
        scope="platform",
        paid=False,
        default_interval_seconds=86_400,
        needs=("BACKUP_B2_KEY_ID",),
    ),
    Capability(
        kind="policy.daily_brief",
        task="generate_policy_daily",
        label="Daily policy brief",
        description=(
            "Researches the day's search-policy developments and files them as "
            "change events and recommendations. Spends one metered call per day."
        ),
        scope="platform",
        paid=True,
        default_interval_seconds=86_400,
        needs=("ANTHROPIC_API_KEY",),
    ),
    Capability(
        kind="reports.monthly",
        task="generate_monthly_reports",
        label="Generate monthly client reports",
        description=(
            "Builds each client's monthly report from data already held. The report "
            "enters review and reaches the client only when someone publishes it."
        ),
        scope="platform",
        paid=False,
        default_interval_seconds=86_400,
    ),
    Capability(
        kind="audits.refresh",
        task="refresh_client_audits",
        label="Re-run client audits",
        description=(
            "Runs a fresh audit for clients whose last one has aged out. A full "
            "engine run per client, so it is the heaviest thing on this list."
        ),
        scope="platform",
        paid=True,
        default_interval_seconds=604_800,
    ),
    Capability(
        kind="offpage.sweep",
        task="sweep_offpage_monitors",
        label="Sweep backlinks and citations for every client",
        description=(
            "Runs the off-page monitor across the roster. Needs a backlink or "
            "citation provider key; without one it degrades and records why."
        ),
        scope="platform",
        paid=True,
        default_interval_seconds=604_800,
        needs=("SERPER_API_KEY",),
    ),
    Capability(
        kind="offpage.monitor_client",
        task="monitor_offpage",
        label="Citation audit for chosen clients",
        description=(
            "Discovers which directories already list a client and which are "
            "missing. The same sweep the Run citation audit button starts."
        ),
        scope="client",
        paid=True,
        default_interval_seconds=604_800,
        needs=("SERPER_API_KEY",),
    ),
    Capability(
        kind="ranks.refresh_local",
        task="refresh_local_ranks",
        label="Refresh local map-pack ranks",
        description=(
            "Re-checks map-pack positions for tracked locations. Every check is paid, "
            "which is why the cadence is deliberately slow."
        ),
        scope="platform",
        paid=True,
        default_interval_seconds=86_400,
    ),
    Capability(
        kind="ranks.dispatch_checks",
        task="dispatch_rank_checks",
        label="Check tracked keyword rankings",
        description="Fans out a rank check per due keyword subscription. Paid per check.",
        scope="platform",
        paid=True,
        default_interval_seconds=86_400,
    ),
    Capability(
        kind="ranks.rollup_history",
        task="rollup_rank_history",
        label="Roll up ranking history",
        description=(
            "Compacts raw rank checks into history. Free, and pointless unless rank "
            "checking is enabled."
        ),
        scope="platform",
        paid=False,
        default_interval_seconds=604_800,
    ),
)

CAPABILITIES: Final[dict[str, Capability]] = {c.kind: c for c in _ALL}


def capability(kind: str) -> Capability | None:
    return CAPABILITIES.get(kind)


__all__ = ["CAPABILITIES", "Capability", "Scope", "capability"]
