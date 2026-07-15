"""P6B-5: the COMPACTION ENGINE - a PURE core that folds prior context + new
events into a bounded, non-stale living summary that PROVABLY supersedes stale
facts. This is the heart of "the AI layer is never stale".

The design is a **hybrid**:

* **Deterministic keyed facts (the supersession proof).** Each activity event
  maps, via a small explicit rule table (:func:`_keyed_facts`), to zero-or-more
  keyed facts. Events are folded **last-writer-wins per key, ordered by ``seq``**,
  starting from the prior facts - so a later event's value for a key OVERWRITES
  the earlier one and the superseded value is GONE (not appended). This step
  touches NO LLM: it is fully deterministic and unit-testable, and it is what
  makes ``tier: A`` become ``tier: B`` with no trace of ``A`` anywhere.
* **A bounded LLM narrative.** The summarizer writes ONLY the living-summary
  prose, from a prompt carrying the prior summary + the already-folded facts +
  the new events, instructed to drop anything the current facts contradict. The
  prose is HARD-BOUNDED to ``token_budget`` (truncated if the provider overshoots).

The core is pure: no DB, no network, no I/O. It receives a ``Summarizer`` (in the
worker P6B-7 that is a cost-gated ``GatedSummarizer``, so the compactor can never
reach a raw provider) and returns a ``CompactionResult`` the worker persists via
``ContextRepo`` and hands to the embed pipeline (P6B-6). Given a deterministic
summarizer (``FakeSummarizer``) the whole ``compact`` call is deterministic, so
re-running the SAME events yields an identical ``checksum`` - the worker uses that
to avoid bumping ``version`` when nothing changed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.schemas.context import ContextChunk
from integrations.llm import Summarizer

# Roughly one token per four characters - the same estimate the FakeSummarizer
# uses. Good enough to enforce a HARD upper bound (we always truncate to it).
_CHARS_PER_TOKEN = 4


# --------------------------------------------------------------------------- #
# Pure input / output types
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ContextEvent:
    """One activity event to fold (a projection of an ``activity_log`` row).

    ``seq`` is the monotonic ordering key - the fold is last-writer-wins by
    ``seq``, so ordering is total and independent of list order.
    """

    seq: int
    kind: str
    action: str
    target: str
    meta: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class PriorContext:
    """The entity's context BEFORE this fold (empty on first compaction)."""

    summary: str = ""
    facts: Mapping[str, Any] = field(default_factory=dict)
    event_watermark: int = 0
    version: int = 0


@dataclass(frozen=True)
class CompactionResult:
    """The folded context: the bounded prose, the superseding facts, the chunks
    to (re)embed, the enforced token count, an idempotency checksum, and the
    highest ``seq`` folded (the new watermark)."""

    new_summary: str
    new_facts: dict[str, Any]
    chunks: list[ContextChunk]
    token_count: int
    checksum: str
    high_watermark: int


# --------------------------------------------------------------------------- #
# The ActivityKind -> fact-key rule table (deterministic; NO LLM)
# --------------------------------------------------------------------------- #
# Each event yields zero-or-more (key, value) facts. Keys are STABLE so a later
# event overwrites an earlier one for the same slot (last-writer-wins by seq).
# Values are parsed conservatively from action/target/meta - never invented. We
# deliberately store only last-writer "current value" facts (e.g. ``last_task``,
# not a running "open_tasks" counter): a counter would break idempotence (re-
# applying the same events would double-count), whereas LWW re-application is a
# no-op. ``_fact_group`` maps each key to a chunk group for embedding.
#
#   kind     | condition                | fact key(s)                     | value
#   ---------+--------------------------+---------------------------------+---------------
#   audit    | always                   | last_audit                      | target (url)
#            | meta parses as a score   | last_audit_score                | int(meta)
#   client   | "tier" in action         | tier (+ delivery_tier if        | meta
#            |                          |   "delivery" in action)         |
#            | "budget"/"cap" in action | budget_cap                      | meta
#            | "portal" in action       | portal_login                    | meta|target
#            | "site" in action         | last_site                       | target (domain)
#            | otherwise                | last_client_event               | action+target
#   task     | always                   | last_task                       | action+target
#   content  | always                   | last_content                    | action+target
#   member   | always                   | last_member (+ last_member_role)| target (+meta)
#   access   | always                   | last_access                     | action+target
#   login    | always                   | last_login                      | target|action
_GROUP_BY_KEY: dict[str, str] = {
    "last_audit": "audit",
    "last_audit_score": "audit",
    "tier": "client",
    "delivery_tier": "client",
    "budget_cap": "client",
    "portal_login": "client",
    "last_site": "client",
    "last_client_event": "client",
    "last_task": "task",
    "last_content": "content",
    "last_member": "member",
    "last_member_role": "member",
    "last_access": "access",
    "last_login": "login",
}


def _phrase(action: str, target: str) -> str:
    """A compact "<action> <target>" value, whitespace-trimmed."""
    return f"{action} {target}".strip()


def _as_score(meta: str | None) -> int | None:
    """``meta`` as an int score, or ``None`` when it is not a plain number."""
    if meta is None:
        return None
    text = meta.strip().rstrip("%")
    try:
        return int(float(text))
    except ValueError:
        return None


def _keyed_facts(event: ContextEvent) -> list[tuple[str, Any]]:
    """Map one event to its keyed facts (see the rule table above)."""
    action = event.action.lower()
    target = event.target
    meta = event.meta
    out: list[tuple[str, Any]] = []
    if event.kind == "audit":
        out.append(("last_audit", target))
        score = _as_score(meta)
        if score is not None:
            out.append(("last_audit_score", score))
    elif event.kind == "client":
        if "tier" in action:
            out.append(("tier", meta or target))
            if "delivery" in action:
                out.append(("delivery_tier", meta or target))
        elif "budget" in action or "cap" in action:
            out.append(("budget_cap", meta or target))
        elif "portal" in action:
            out.append(("portal_login", meta or target))
        elif "site" in action:
            out.append(("last_site", target))
        else:
            out.append(("last_client_event", _phrase(event.action, target)))
    elif event.kind == "task":
        out.append(("last_task", _phrase(event.action, target)))
    elif event.kind == "content":
        out.append(("last_content", _phrase(event.action, target)))
    elif event.kind == "member":
        out.append(("last_member", _phrase(event.action, target)))
        if meta:
            out.append(("last_member_role", meta))
    elif event.kind == "access":
        out.append(("last_access", _phrase(event.action, target)))
    elif event.kind == "login":
        out.append(("last_login", target or event.action))
    return out


def _fact_group(key: str) -> str:
    """The chunk group a fact key embeds under (``misc`` for anything unmapped)."""
    return _GROUP_BY_KEY.get(key, "misc")


# --------------------------------------------------------------------------- #
# The deterministic fold: last-writer-wins by seq + recency cap
# --------------------------------------------------------------------------- #
def _fold_facts(
    prior_facts: Mapping[str, Any], events: list[ContextEvent], max_facts: int
) -> dict[str, Any]:
    """Fold ``events`` onto ``prior_facts`` last-writer-wins per key, ordered by
    ``seq``, then cap to ``max_facts`` keys keeping the most-recently-touched.

    Ordering by ``seq`` (not list order) means an out-of-order lower-seq event can
    never overwrite a higher-seq value. A carried-forward prior key that no event
    touches survives (its recency is oldest, so it is evicted first under the cap).
    """
    facts: dict[str, Any] = dict(prior_facts)
    touched: dict[str, int] = {}
    for event in sorted(events, key=lambda e: e.seq):
        for key, value in _keyed_facts(event):
            facts[key] = value
            touched[key] = event.seq

    if len(facts) <= max_facts:
        return facts

    # Recency eviction: keep the max_facts keys with the highest touch seq. Prior
    # keys no event touched rank oldest (-1); the sort is stable so ties keep
    # insertion order. Return in canonical (sorted-key) order for a stable result.
    ranked = sorted(facts.items(), key=lambda kv: touched.get(kv[0], -1), reverse=True)
    kept = dict(ranked[:max_facts])
    return {key: kept[key] for key in sorted(kept)}


# --------------------------------------------------------------------------- #
# Prompt, bounding, chunking, checksum
# --------------------------------------------------------------------------- #
def _build_prompt(prior_summary: str, facts: Mapping[str, Any], events: list[ContextEvent]) -> str:
    """Assemble the summarize prompt from the prior prose + the FOLDED facts +
    the new events. Only folded facts (never raw superseded metas) carry values,
    so a superseded value never enters the prompt - hence never the prose."""
    lines: list[str] = []
    if prior_summary:
        lines.append(f"Current summary: {prior_summary}")
    if facts:
        rendered = "; ".join(f"{key}={facts[key]}" for key in sorted(facts))
        lines.append(f"Current facts: {rendered}")
    if events:
        rendered_events = "; ".join(
            _phrase(f"[{event.seq}] {event.kind} {event.action}", event.target)
            for event in sorted(events, key=lambda e: e.seq)
        )
        lines.append(f"Recent events: {rendered_events}")
    lines.append(
        "Write a concise living summary. Drop any statement the current facts contradict."
    )
    return "\n".join(lines)


def _enforce_budget(text: str, token_budget: int) -> tuple[str, int]:
    """Hard-bound ``text`` to ``token_budget`` tokens; return (text, token_count).

    We truncate to ``token_budget * _CHARS_PER_TOKEN`` characters, so the estimated
    token count (``len // _CHARS_PER_TOKEN``) is ALWAYS ``<= token_budget`` - the
    budget is a guarantee, not a hint, regardless of what the provider returns.
    """
    char_budget = max(token_budget, 0) * _CHARS_PER_TOKEN
    bounded = text[:char_budget]
    return bounded, len(bounded) // _CHARS_PER_TOKEN


def _sha256(text: str) -> str:
    """sha256 hex digest of ``text``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_chunks(summary: str, facts: Mapping[str, Any]) -> list[ContextChunk]:
    """One ``summary`` chunk (the prose) + one ``facts:<group>`` chunk per fact
    group, each with its content checksum (what P6B-6 embeds/upserts)."""
    chunks: list[ContextChunk] = [
        ContextChunk(chunk_key="summary", content=summary, content_checksum=_sha256(summary))
    ]
    groups: dict[str, dict[str, Any]] = {}
    for key in sorted(facts):
        groups.setdefault(_fact_group(key), {})[key] = facts[key]
    for group in sorted(groups):
        content = "\n".join(f"{key}: {groups[group][key]}" for key in sorted(groups[group]))
        chunks.append(
            ContextChunk(
                chunk_key=f"facts:{group}", content=content, content_checksum=_sha256(content)
            )
        )
    return chunks


def _checksum(summary: str, facts: Mapping[str, Any]) -> str:
    """A stable digest over (summary + sorted facts). Identical inputs -> identical
    checksum, so an idempotent re-run is detectable and the worker skips a version
    bump when nothing changed."""
    payload = summary + "\n" + json.dumps(facts, sort_keys=True, separators=(",", ":"), default=str)
    return _sha256(payload)


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #
def compact(
    prior: PriorContext,
    events: list[ContextEvent],
    summarizer: Summarizer,
    *,
    token_budget: int,
    max_facts: int,
    model: str,
) -> CompactionResult:
    """Fold ``prior`` + ``events`` into a bounded, non-stale living context.

    Deterministic given a deterministic ``summarizer``. With no events the prior
    is returned unchanged (no summarizer call, so no cost and a stable checksum) -
    once the watermark has caught up, a re-fire of the debounce is a true no-op.
    """
    folded = _fold_facts(prior.facts, events, max_facts)

    if not events:
        # Nothing new to narrate: carry the prior prose forward verbatim, bounded.
        summary, token_count = _enforce_budget(prior.summary, token_budget)
        return CompactionResult(
            new_summary=summary,
            new_facts=folded,
            chunks=_build_chunks(summary, folded),
            token_count=token_count,
            checksum=_checksum(summary, folded),
            high_watermark=prior.event_watermark,
        )

    prompt = _build_prompt(prior.summary, folded, events)
    result = summarizer.summarize(prompt, model=model, max_tokens=token_budget)
    summary, token_count = _enforce_budget(result.text, token_budget)

    return CompactionResult(
        new_summary=summary,
        new_facts=folded,
        chunks=_build_chunks(summary, folded),
        token_count=token_count,
        checksum=_checksum(summary, folded),
        high_watermark=max(event.seq for event in events),
    )
