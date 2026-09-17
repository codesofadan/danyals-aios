"""Run registered checks. One failure costs one check, never a run.

Today every per-page check for a site runs inside a single generator:

    def iter_per_page_checks(p):
        yield ("ON-034", "A3", check_title(p))
        yield ("ON-035", "A3", check_title_ctr(p))
        ...47 more

A generator that raises stops. An exception in the twelfth check silently
abandons the remaining thirty-five **for that page and for every page after
it**, and the audit still reports success with a quietly smaller check set. The
score then rises, because ``score = 100 x (1 - failed/ran)`` and the checks that
never ran leave the denominator.

The dispatcher calls each check separately and converts a failure into one
``n_a`` finding carrying ``analyzer_error``, with ``confidence`` 0.0 so it is
excluded from the weighted mean rather than counted as a pass.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.registry import Registration, for_scope

log = logging.getLogger(__name__)

#: Evidence key set on a finding whose analyzer raised.
ANALYZER_ERROR = "analyzer_error"
#: Evidence key set when a rollup did not have enough inputs to mean anything.
INPUTS_RAN = "inputs_ran"
INPUTS_MISSING = "inputs_missing"
PARTIAL_ROLLUP = "partial_rollup"


@dataclass
class DispatchResult:
    """What one dispatch pass produced."""

    #: (check_id, verdict) in registration order
    verdicts: list[tuple[str, Verdict]] = field(default_factory=list)
    #: check_ids whose analyzer raised
    errored: list[str] = field(default_factory=list)
    #: check_ids skipped before the call (rollups with too few inputs)
    gated: list[str] = field(default_factory=list)

    def ids(self) -> set[str]:
        return {c for c, _ in self.verdicts}


def _error_verdict(exc: BaseException) -> Verdict:
    """A check that raised did not measure anything. Say so, do not score it."""
    return Verdict(
        "n_a", 0.0, "info", 0.0,
        {ANALYZER_ERROR: f"{type(exc).__name__}: {exc}"[:300]},
        None,
    )


def _call(reg: Registration, payload: Any) -> Verdict:
    out = reg.func(payload)
    if not isinstance(out, Verdict):
        raise TypeError(
            f"{reg.dotted_path} returned {type(out).__name__}, expected Verdict"
        )
    return out


async def _call_async(reg: Registration, payload: Any) -> Verdict:
    out = await reg.func(payload)
    if not isinstance(out, Verdict):
        raise TypeError(
            f"{reg.dotted_path} returned {type(out).__name__}, expected Verdict"
        )
    return out


def run_scope(
    scope: str,
    payload: Any,
    *,
    only: Iterable[str] | None = None,
    registrations: Sequence[Registration] | None = None,
) -> DispatchResult:
    """Run every check registered for ``scope`` against ``payload``.

    ``only`` restricts to a set of check ids - used by the tier system so a
    free run never calls a billable analyzer.
    """
    result = DispatchResult()
    allowed = set(only) if only is not None else None
    regs = list(registrations) if registrations is not None else for_scope(scope)
    for reg in regs:
        if allowed is not None and reg.check_id not in allowed:
            continue
        if reg.is_async:
            raise RuntimeError(
                f"{reg.dotted_path} is async; use run_scope_async for scope {scope!r}"
            )
        try:
            result.verdicts.append((reg.check_id, _call(reg, payload)))
        except Exception as exc:
            log.warning("analyzer_failed check=%s at=%s err=%r",
                        reg.check_id, reg.dotted_path, exc)
            result.errored.append(reg.check_id)
            result.verdicts.append((reg.check_id, _error_verdict(exc)))
    return result


async def run_scope_async(
    scope: str,
    payload: Any,
    *,
    only: Iterable[str] | None = None,
    registrations: Sequence[Registration] | None = None,
) -> DispatchResult:
    """As :func:`run_scope`, awaiting any coroutine analyzers."""
    result = DispatchResult()
    allowed = set(only) if only is not None else None
    regs = list(registrations) if registrations is not None else for_scope(scope)
    for reg in regs:
        if allowed is not None and reg.check_id not in allowed:
            continue
        try:
            v = await _call_async(reg, payload) if reg.is_async else _call(reg, payload)
            result.verdicts.append((reg.check_id, v))
        except Exception as exc:
            log.warning("analyzer_failed check=%s at=%s err=%r",
                        reg.check_id, reg.dotted_path, exc)
            result.errored.append(reg.check_id)
            result.verdicts.append((reg.check_id, _error_verdict(exc)))
    return result


def run_rollups(
    ran_check_ids: set[str],
    payload: Any,
    *,
    registrations: Sequence[Registration] | None = None,
) -> DispatchResult:
    """Run rollups, gating on how many of their inputs actually ran.

    OFF-074 "Authority score" declares ``data_sources: [computed]``, which
    classes as zero-cost, so it ran on a free tier while all 33 Moz checks it
    aggregates were skipped - publishing an authority score computed over no
    link data. The gate is applied BEFORE the call so no rollup can forget it,
    and every rollup carries its provenance whether or not it was gated.
    """
    result = DispatchResult()
    regs = list(registrations) if registrations is not None else for_scope("rollup")
    for reg in regs:
        ran = sorted(set(reg.inputs) & ran_check_ids)
        missing = sorted(set(reg.inputs) - ran_check_ids)
        provenance = {
            INPUTS_RAN: ran,
            INPUTS_MISSING: missing,
            "inputs_declared": len(reg.inputs),
        }
        if len(ran) < reg.min_inputs_ran:
            # Not a score of zero. aggregator.py drops n_a from the weighted
            # mean, so this leaves the composite instead of dragging it down.
            result.gated.append(reg.check_id)
            result.verdicts.append((reg.check_id, Verdict(
                "n_a", 0.0, "info", 0.0,
                {**provenance, "reason":
                 f"{len(ran)} of {len(reg.inputs)} inputs ran; "
                 f"{reg.min_inputs_ran} required"},
                None,
            )))
            continue
        try:
            v = _call(reg, payload)
        except Exception as exc:
            log.warning("rollup_failed check=%s err=%r", reg.check_id, exc)
            result.errored.append(reg.check_id)
            result.verdicts.append((reg.check_id, _error_verdict(exc)))
            continue
        partial = bool(missing)
        coverage = len(ran) / len(reg.inputs) if reg.inputs else 1.0
        result.verdicts.append((reg.check_id, Verdict(
            v.status,
            v.score,
            v.severity,
            # A rollup is only as confident as the share of inputs behind it.
            round(v.confidence * coverage, 4),
            {**v.evidence, **provenance, PARTIAL_ROLLUP: partial},
            v.remediation,
            v.references,
        )))
    return result


def scope_is_async(scope: str) -> bool:
    return any(r.is_async for r in for_scope(scope))


