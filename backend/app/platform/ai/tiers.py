"""Task tiers: what KIND of work a model call is, and which model that buys.

``06-AI-STACK.md`` §3 fixes the mapping. The point of routing on a tier rather than a
model id is that a caller states its REQUIREMENT ("this is drafting", "this is a judge
call") and the model table answers it in one place. Every call site that names a model
directly is a place the table cannot be changed - and this repo already has ~15 of them,
which is exactly why a model swap in 2026-09 had to be done by grep.

TWO RULES THE TABLE ENCODES, NOT PREFERENCES:

* ``judge`` is never the same configuration as ``drafting``. A grader that shares the
  generator's model and effort agrees with it for reasons that have nothing to do with
  the output being good (§8, "judge independence").
* An unrecognised tier is a programming error, not a default. Falling back to a cheap
  tier silently downgrades work that asked for reasoning; falling back to an expensive
  one silently multiplies a bulk job's bill. Both are worse than a TypeError.

WHY EFFORT AND NOT ``budget_tokens``. ``output_config={"effort": ...}`` is the depth dial
on Opus 5 / Sonnet 5; passing ``thinking.budget_tokens`` alongside adaptive thinking is
rejected with a 400. The two fields here (``thinking``/``effort``) are carried as data so
the backend decides how to spell them - a backend that cannot honour one says so rather
than dropping it (see ``router.CapabilityMissingError``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class TaskTier(StrEnum):
    """What kind of work one model call is. The router maps this to a model."""

    REASONING = "reasoning"
    DRAFTING = "drafting"
    STRUCTURED = "structured"
    BULK = "bulk"
    JUDGE = "judge"


@dataclass(frozen=True)
class TierSpec:
    """The call configuration one tier buys.

    ``effort`` is ``None`` for tiers that do not think (``bulk``); ``adaptive_thinking``
    is True only where §3's call defaults say so (``reasoning`` and ``judge``).
    ``max_tokens`` is the DEFAULT ceiling for the tier - a caller may raise it, and the
    router streams when it is large enough to warrant it.
    """

    model: str
    effort: str | None = None
    adaptive_thinking: bool = False
    max_tokens: int = 16_000
    #: Why this tier exists, surfaced in traces so a span reads without the table.
    purpose: str = ""


# Model ids EXACTLY as `06-AI-STACK.md` §3 writes them - no date suffixes. A dated
# alias still prices correctly (`pricing.anthropic_tier` substring-matches), but the
# table is the contract and the contract is undated.
TIERS: Final[dict[TaskTier, TierSpec]] = {
    TaskTier.REASONING: TierSpec(
        model="claude-opus-5",
        effort="high",
        adaptive_thinking=True,
        max_tokens=32_000,
        purpose="design reconciliation, page-set planning, audit narrative, policy exposure",
    ),
    TaskTier.DRAFTING: TierSpec(
        model="claude-opus-5",
        effort="medium",
        adaptive_thinking=False,
        max_tokens=16_000,
        purpose="page drafting, Web 2.0 post bodies, GBP posts",
    ),
    TaskTier.STRUCTURED: TierSpec(
        model="claude-sonnet-5",
        effort="medium",
        adaptive_thinking=False,
        max_tokens=8_000,
        purpose="extraction to a fixed schema, classification, intent labelling",
    ),
    TaskTier.BULK: TierSpec(
        model="claude-haiku-4-5",
        effort=None,
        adaptive_thinking=False,
        max_tokens=4_000,
        purpose="alt text, title/meta variants, tag suggestions - high volume, low stakes",
    ),
    TaskTier.JUDGE: TierSpec(
        model="claude-opus-5",
        effort="high",
        adaptive_thinking=True,
        max_tokens=16_000,
        purpose="QA scorecard, grounding checks, eval graders - never the generator's config",
    ),
}


def spec_for(tier: TaskTier | str) -> TierSpec:
    """The :class:`TierSpec` for ``tier``.

    Raises ``KeyError`` on an unknown tier rather than defaulting. See the module
    header: every silent default here is either a quality downgrade or a bill.

    A bad string arrives as ``ValueError`` from the enum and is re-raised as ``KeyError``
    naming the valid tiers, so ONE exception type covers "not a tier" and "no spec for
    that tier" - a caller should not have to catch two types to handle one mistake.
    """
    if isinstance(tier, TaskTier):
        return TIERS[tier]
    try:
        key = TaskTier(tier)
    except ValueError as exc:
        raise KeyError(
            f"unknown task tier {tier!r}; valid tiers: {', '.join(t.value for t in TaskTier)}"
        ) from exc
    return TIERS[key]


def resolve_models(raw: str) -> dict[TaskTier, str]:
    """Parse a ``tier=model,tier=model`` override string into a model map.

    WHY OVERRIDES EXIST AT ALL. ``06-AI-STACK.md`` §3 fixes the tier -> model table and
    also states the thing that makes it insufficient on its own: *"Model IDs are
    gateway-specific: a router exposes its OWN catalog"*. This deployment proves it - it
    runs through an Anthropic-compatible gateway that answered a ``claude-haiku-4-5``
    request with::

        503 no available channel for model claude-haiku-4-5

    The TIER is the contract ("this is bulk work, cheap and high volume"); the model id
    that serves it is deployment configuration. Conflating them means a gateway change is
    a code change, which is exactly the coupling the router was built to remove.

    Unknown tier names and blank entries are REFUSED rather than ignored: a typo'd
    ``draffting=...`` that silently did nothing would leave that tier on a model the
    gateway cannot serve, and the failure would arrive as a 503 in a worker at 3am rather
    than as a startup error naming the typo.
    """
    resolved: dict[TaskTier, str] = {}
    for entry in raw.split(","):
        item = entry.strip()
        if not item:
            continue
        name, sep, model = item.partition("=")
        if not sep or not model.strip():
            raise ValueError(
                f"tier model override {item!r} must be 'tier=model'; "
                f"valid tiers: {', '.join(t.value for t in TaskTier)}"
            )
        try:
            tier = TaskTier(name.strip())
        except ValueError as exc:
            raise ValueError(
                f"unknown task tier {name.strip()!r} in the model overrides; "
                f"valid tiers: {', '.join(t.value for t in TaskTier)}"
            ) from exc
        resolved[tier] = model.strip()
    return resolved


def judge_is_independent(generator: TaskTier | str, judge: TaskTier | str) -> bool:
    """Whether ``judge`` grades ``generator`` from a genuinely different configuration.

    §8 requires the grader never share the generator's tier configuration. This is the
    machine-checkable half of that rule (the other half - a different PROMPT - lives in
    the prompt registry), and the eval suite asserts it rather than trusting a comment.
    """
    gen = spec_for(generator)
    jud = spec_for(judge)
    return (gen.model, gen.effort) != (jud.model, jud.effort)
