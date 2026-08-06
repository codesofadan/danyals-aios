"""Celery tasks for Policy Radar: the DAILY Anthropic GENERATOR (the default feed) and
the legacy change-detection WATCHER (retained, now dormant).

DEFAULT (``generate_policy_daily``, beat ``generate-policy-daily``): once a day Claude
returns the current top Google-Search developments from its OWN expert knowledge (PURE
Cloud-API generation, no web search) and writes ``policy_daily_count`` items into
change_events + kb_entries + recommendations (``store_generated_items`` +
``app/services/policy_generate.py``). This REPLACED the Google-scrape watcher on the beat;
the manual ``POST /policy/generate`` forces a refresh.

LEGACY (``watch_policy_sources``): the source-diff watcher below is kept for reference /
re-enablement but is NO LONGER on the beat schedule (the user moved Policy Radar off
Google-feed scraping onto Anthropic generation). When it ran, once every
``policy_watch_seconds`` (6h) the beat fired ``watch_policy_sources``. It
CLAIMS the least-recently-checked sources (``FOR UPDATE SKIP LOCKED``, so overlapping
ticks never double-poll a source), and for each:

    fetch (SSRF-guarded) -> sha256 -> diff against the stored anchor

* no change  -> touch ``last_checked`` (``mark_unchanged``); nothing else.
* first poll (empty anchor) -> capture the baseline hash, no change_event.
* a real diff -> ``record_change`` (advance the anchor, flip status, append a
  change_event) and then the cost-gated Haiku analysis, which - when a key is present
  AND the gate allows - writes a versioned/deduped ``kb_entry`` + a 'new'
  ``recommendation`` and stamps the change_event's ``triggered_job``.

The pure cores (``watch_sources`` / ``analyze_and_store``) take an injected store +
fetcher + summarizer + gate, so they are unit-tested with fakes - NO DB, NO network,
NO Celery. The task NEVER re-raises (``task_acks_late`` would redeliver and re-spend);
every failure comes back as a small result dict. Degradation is total: no Anthropic
key OR a dial-off / cap / daily-stop block simply SKIPS the analysis - the
change_event still stands and the KB is unchanged, never a crash. Mirrors the context
worker (``workers/tasks/context.py``): the ``celery_app`` import lives AFTER the pure
cores, per the worker template.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.config import Settings, get_settings
from app.db.policy_watch_repo import service_policy_watch_repo
from app.logging_setup import get_logger
from app.services.cost_gate import CostGate
from app.services.cost_store import PostgresCostStore
from app.services.policy_ask import build_ask_summarizer
from app.services.policy_generate import GeneratedItem, run_policy_generation
from app.services.policy_watch import (
    PolicyFetcher,
    SsrfGuardedPolicyFetcher,
    analyze_change,
    detect_change,
    finding_hash,
    summarizer_from_settings,
)
from integrations.llm import Summarizer

logger = get_logger("workers.policy")

# How many sources one beat tick claims. Comfortably above the seeded set (8) so a
# single tick sweeps them all; the SKIP-LOCKED claim caps concurrency, not coverage.
_CLAIM_BATCH = 50
# The change_event's severity is recorded BEFORE the analysis runs, so it is a neutral
# default; the analysed severity rides on the KB entry the analysis produces.
_DEFAULT_CHANGE_SEVERITY = "info"


class _NullCostCache:
    """A no-op ``CostCache``: a policy-analysis Haiku call is a unique distillation of a
    fresh change, never a cache hit; the dial + budgets still gate it. Matches the
    content / on-page / audit workers."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _gate() -> CostGate:
    return CostGate(PostgresCostStore(), _NullCostCache())


# --------------------------------------------------------------------------- #
# The store seam the cores need (PolicyWatchRepo satisfies it)
# --------------------------------------------------------------------------- #
class PolicyWatchStore(Protocol):
    """The privileged write surface the watcher cores use (service_role, BYPASSRLS)."""

    def claim_due_sources(self, limit: int) -> list[dict[str, Any]]: ...
    def mark_unchanged(self, source_id: str) -> None: ...
    def capture_baseline(self, source_id: str, new_hash: str) -> None: ...
    def record_change(
        self, source_id: str, name: str, new_hash: str, summary: str, severity: str, diff_ref: str
    ) -> str: ...
    def insert_kb_entry(self, row: dict[str, Any]) -> dict[str, Any]: ...
    def insert_recommendation(self, row: dict[str, Any]) -> dict[str, Any]: ...
    def set_triggered_job(self, change_event_id: str, kb_job: str) -> None: ...
    # the daily Anthropic generator's extra surface:
    def insert_change_event(self, source_name: str, summary: str, severity: str) -> str: ...
    def count_generated_today(self) -> int: ...


# --------------------------------------------------------------------------- #
# Outcomes (JSON-serializable; the task returns as_dict())
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class WatchOutcome:
    """The tally of one full sweep (JSON-serializable)."""

    claimed: int = 0
    unchanged: int = 0
    baselined: int = 0
    changed: int = 0
    analyzed: int = 0
    degraded: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "claimed": self.claimed,
            "unchanged": self.unchanged,
            "baselined": self.baselined,
            "changed": self.changed,
            "analyzed": self.analyzed,
            "degraded": self.degraded,
            "errors": self.errors,
        }


@dataclass(frozen=True)
class AnalysisOutcome:
    """The verdict of one change's analysis: ``analyzed`` (KB + rec written) or
    ``degraded`` (no key / gate blocked -> the change_event stands alone)."""

    state: str  # analyzed | degraded
    kb_ref: str = ""


# --------------------------------------------------------------------------- #
# Analysis -> DB (writes kb_entry + recommendation + triggered_job)
# --------------------------------------------------------------------------- #
def analyze_and_store(
    store: PolicyWatchStore,
    *,
    summarizer: Summarizer | None,
    gate: CostGate,
    settings: Settings,
    source_id: str,
    source_name: str,
    source_url: str,
    change_event_id: str,
    summary: str,
    text: str,
) -> AnalysisOutcome:
    """Run the cost-gated analysis of a recorded change and persist its KB entry +
    recommendation, or DEGRADE cleanly.

    ``analyze_change`` returns ``None`` (degrade) when the key is absent or the gate
    blocks the spend - then NOTHING is written and the change_event stands alone. On an
    allowed call it returns a ``PolicyAnalysis`` (real fields, or a minimal one on a
    parse failure), and we insert a versioned/deduped ``kb_entry``, a 'new'
    ``recommendation`` pointing at it, and stamp the change_event's ``triggered_job``.
    The live KB ref is ``kb-live-<sha8>`` - distinct from the ``kb-base-*`` baseline
    ids (``policy_baseline.py``) so it can never collide with the baseline dedupe."""
    analysis = analyze_change(
        summarizer,
        gate,
        settings=settings,
        source_id=source_id,
        source_name=source_name,
        source_url=source_url,
        text=text,
        fallback_summary=summary,
    )
    if analysis is None:
        logger.info("policy_analysis_degraded", source=source_name)
        return AnalysisOutcome("degraded")

    kb_hash = finding_hash(source_url, analysis.title, analysis.summary)
    kb_ref = f"kb-live-{kb_hash[:8]}"
    kb_row = store.insert_kb_entry(
        {
            "source_id": source_id,
            "title": analysis.title,
            "summary": analysis.summary,
            "severity": analysis.severity,
            "category": analysis.category,
            "region": analysis.region,
            "region_label": analysis.region_label,
            "source_name": source_name,
            "source_url": source_url,
            "hash": kb_hash,
        }
    )
    store.insert_recommendation(
        {
            "kb_entry_id": kb_row.get("id"),
            "kb_ref": kb_ref,
            "title": analysis.rec_title,
            "why": analysis.rec_why,
            "action": analysis.rec_action,
            "scope": "global",
            "target_module": analysis.target_module,
            "region": analysis.region,
            "region_label": analysis.region_label,
            "status": "new",
        }
    )
    store.set_triggered_job(change_event_id, kb_ref)
    logger.info(
        "policy_analysis_done", source=source_name, kb_ref=kb_ref, severity=analysis.severity
    )
    return AnalysisOutcome("analyzed", kb_ref=kb_ref)


# --------------------------------------------------------------------------- #
# Generated items -> DB (the daily Anthropic brief: change_event + kb + rec each)
# --------------------------------------------------------------------------- #
# The display source name for a generated change_event when the model did not cite one.
_GEN_SOURCE_LABEL = "AIOS Policy Brief"


def store_generated_items(store: PolicyWatchStore, items: list[GeneratedItem]) -> int:
    """Persist each generated policy item as a change_event + a versioned/deduped kb_entry
    + a 'new' recommendation, returning the number written.

    Mirrors ``analyze_and_store`` but for the GENERATOR: there is no diffed source, so the
    change_event has a NULL source_id (``insert_change_event``) and the citation snapshots
    come from the model. The KB ref is ``kb-gen-<sha8>`` - distinct from ``kb-live-*``
    (watcher) and ``kb-base-*`` (baseline) - so the once-per-day guard
    (``count_generated_today``) and the reset (``clear_policy_feed``) can target generated
    rows precisely. Pure over the injected store, so it unit-tests with a fake store."""
    written = 0
    for item in items:
        analysis = item.analysis
        source_name = item.source_name or _GEN_SOURCE_LABEL
        change_event_id = store.insert_change_event(
            source_name=source_name,
            summary=analysis.summary,
            severity=analysis.severity,
        )
        kb_hash = finding_hash(item.source_url or "aios-generated", analysis.title, analysis.summary)
        kb_ref = f"kb-gen-{kb_hash[:8]}"
        kb_row = store.insert_kb_entry(
            {
                "source_id": None,
                "title": analysis.title,
                "summary": analysis.summary,
                "severity": analysis.severity,
                "category": analysis.category,
                "region": analysis.region,
                "region_label": analysis.region_label,
                "source_name": source_name,
                "source_url": item.source_url,
                "hash": kb_hash,
            }
        )
        store.insert_recommendation(
            {
                "kb_entry_id": kb_row.get("id"),
                "kb_ref": kb_ref,
                "title": analysis.rec_title,
                "why": analysis.rec_why,
                "action": analysis.rec_action,
                "scope": "global",
                "target_module": analysis.target_module,
                "region": analysis.region,
                "region_label": analysis.region_label,
                "status": "new",
            }
        )
        store.set_triggered_job(change_event_id, kb_ref)
        written += 1
    return written


# --------------------------------------------------------------------------- #
# The sweep core (claim -> per-source fetch + detect + record + analyse)
# --------------------------------------------------------------------------- #
def _watch_one(
    store: PolicyWatchStore,
    src: dict[str, Any],
    *,
    fetcher: PolicyFetcher,
    settings: Settings,
    summarizer: Summarizer | None,
    gate: CostGate,
) -> tuple[str, str | None]:
    """Poll ONE claimed source. Returns ``(source_state, analysis_state)`` where
    ``source_state`` is unchanged | baselined | changed and ``analysis_state`` is the
    analysis verdict (analyzed | degraded) only when a change was recorded."""
    source_id = str(src["id"])
    name = str(src.get("name") or "")
    url = str(src.get("url") or "")
    last_hash = str(src.get("last_hash") or "")

    text = fetcher.fetch(url)
    if text is None:
        # Unreachable / non-200 this tick: touch last_checked and retry next tick.
        store.mark_unchanged(source_id)
        return "unchanged", None

    changed, new_hash = detect_change(text, last_hash)
    if not last_hash:
        # First observation of this source: capture the baseline anchor, no change.
        store.capture_baseline(source_id, new_hash)
        return "baselined", None
    if not changed:
        store.mark_unchanged(source_id)
        return "unchanged", None

    summary = f"Detected an update to {name}." if name else "Detected a policy source update."
    change_event_id = store.record_change(
        source_id, name, new_hash, summary, _DEFAULT_CHANGE_SEVERITY, new_hash
    )
    outcome = analyze_and_store(
        store,
        summarizer=summarizer,
        gate=gate,
        settings=settings,
        source_id=source_id,
        source_name=name,
        source_url=url,
        change_event_id=change_event_id,
        summary=summary,
        text=text,
    )
    return "changed", outcome.state


def watch_sources(
    store: PolicyWatchStore,
    *,
    fetcher: PolicyFetcher,
    settings: Settings,
    summarizer: Summarizer | None,
    gate: CostGate,
    limit: int = _CLAIM_BATCH,
) -> WatchOutcome:
    """Claim due sources and poll each. NEVER raises out of a single source: one
    unreachable / failing source must not stop the sweep, so each is guarded and the
    tallies roll up into the returned ``WatchOutcome``."""
    claimed = store.claim_due_sources(limit)
    counts: dict[str, int] = {
        "unchanged": 0,
        "baselined": 0,
        "changed": 0,
        "analyzed": 0,
        "degraded": 0,
        "errors": 0,
    }
    for src in claimed:
        try:
            source_state, analysis_state = _watch_one(
                store,
                src,
                fetcher=fetcher,
                settings=settings,
                summarizer=summarizer,
                gate=gate,
            )
            counts[source_state] += 1
            if analysis_state is not None:
                counts[analysis_state] += 1
        except Exception:  # a single bad source never stops the sweep
            logger.exception("policy_watch_source_failed", source=str(src.get("name", "")))
            counts["errors"] += 1
    return WatchOutcome(
        claimed=len(claimed),
        unchanged=counts["unchanged"],
        baselined=counts["baselined"],
        changed=counts["changed"],
        analyzed=counts["analyzed"],
        degraded=counts["degraded"],
        errors=counts["errors"],
    )


# --------------------------------------------------------------------------- #
# Celery entry point (thin; import the app AFTER the pure cores, per the template)
# --------------------------------------------------------------------------- #
from workers.celery_app import celery_app  # noqa: E402 - after the pure cores, per the worker template


@celery_app.task(name="watch_policy_sources")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def watch_policy_sources() -> dict[str, Any]:
    """BEAT entry point: sweep the policy sources once. Wires the privileged store, the
    SSRF-guarded fetcher, the (key-gated) Haiku summarizer and the cost gate, then runs
    the pure core - which never raises. The wiring is INSIDE the guard too, so a seam
    that fails to construct still degrades to a result dict rather than redelivering the
    job (the acks_late double-spend guard)."""
    try:
        settings = get_settings()
        outcome = watch_sources(
            service_policy_watch_repo(),
            fetcher=SsrfGuardedPolicyFetcher(),
            settings=settings,
            summarizer=summarizer_from_settings(settings),
            gate=_gate(),
            limit=_CLAIM_BATCH,
        )
        return outcome.as_dict()
    except Exception:  # never re-raise: acks_late would redeliver the beat task
        logger.exception("watch_policy_sources_task_failed")
        return {"claimed": 0, "state": "failed"}


@celery_app.task(name="generate_policy_daily")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def generate_policy_daily(force: bool = False) -> dict[str, Any]:
    """BEAT entry point (+ manual trigger): generate the day's policy brief via Anthropic.

    Wires the (key-gated) pure-generation summarizer, the cost gate, and the privileged
    store, then runs the pure core (``run_policy_generation``) and persists its items
    (``store_generated_items``). ONCE PER DAY: unless ``force`` is set (the manual
    ``POST /policy/generate`` refresh), a run is SKIPPED when generator items already exist
    for the current UTC day (``count_generated_today``), so a re-delivered beat tick never
    double-spends. Total degradation: a keyless deploy, a dial/budget block, or a research
    failure simply writes NOTHING (state='degraded'); the task NEVER re-raises (acks_late
    would otherwise redeliver + re-spend)."""
    try:
        settings = get_settings()
        store = service_policy_watch_repo()
        if not force and store.count_generated_today() > 0:
            return {"state": "skipped", "reason": "already_generated_today", "written": 0}
        result = run_policy_generation(
            summarizer=build_ask_summarizer(settings),
            gate=_gate(),
            settings=settings,
        )
        if result.status != "ok":
            return {"state": result.status, "reason": result.reason, "written": 0}
        written = store_generated_items(store, result.items)
        logger.info("generate_policy_daily_done", written=written, forced=force)
        return {"state": "ok", "written": written}
    except Exception:  # never re-raise: acks_late would redeliver the beat task
        logger.exception("generate_policy_daily_task_failed")
        return {"state": "failed", "written": 0}


@celery_app.task(name="reset_policy_feed")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def reset_policy_feed() -> dict[str, Any]:
    """One-off ops task: clear the RETIRED Google-scrape Policy-Radar feed.

    Deletes every change_event + kb_entry + NON-baseline recommendation via the privileged
    repo (``clear_policy_feed``; the evergreen baseline recs survive) so the dashboard drops
    the old generic scrape items and shows only the Cloud-API-generated brief. Runnable in
    the worker's own context (``celery call reset_policy_feed``) so it inherits the live
    config. Returns the per-table row counts; NEVER re-raises (acks_late would redeliver)."""
    try:
        counts = service_policy_watch_repo().clear_policy_feed()
        logger.info("reset_policy_feed_done", **counts)
        return {"state": "ok", **counts}
    except Exception:
        logger.exception("reset_policy_feed_task_failed")
        return {"state": "failed"}
