"""The correcting loop - and the three things that keep it from burning publishes (P6.3).

`visual_diff` already re-captures a published page and returns typed diagnostics.
`site_builder` already has a `correcting` state. Nothing consumes either: a page that
renders wrong is measured, the measurement is stored, and then nothing happens.

THIS IS THE RISKIEST PIECE IN THE PHASE, and the risk is specific. Every round of this
loop RE-PUBLISHES TO A CLIENT'S LIVE SITE. A mapping that is confident where it should
not be does not fail safely - it edits a live page, measures it, edits it again, and
oscillates until the cap, having made the page worse in public each time.

So the design is defensive in three ways:

1. ONLY MAP WHAT IS A TOKEN. A diagnostic is fixable here when the correction is a
   single value substitution whose effect is knowable without re-deriving the page.
   Font size, container width and section background are that. Section COUNT is not -
   "expected 5 sections, rendered 3" is a rendering or template problem, and guessing
   at a token for it is how a loop starts thrashing. Those land `degraded` for a human.

   I could defend three mappings. The plan that scoped this phase guessed at "4-6", and
   padding to hit that number would mean shipping a mapping I could not argue for.

2. A RECURRENCE IS NOT A RETRY. If round 2 measures a diagnostic that round 1 already
   applied an override for, the override did not take - something downstream is winning,
   and sending it again cannot change that. That diagnostic becomes unfixable
   IMMEDIATELY rather than being re-attempted until the round cap. This is the check
   that actually stops oscillation; the cap alone only bounds how long it runs.

3. TRIVIAL DRIFT IS NOT WORTH A PUBLISH. `visual_diff` reports anything past a 12%
   tolerance. A 13% font drift is real and also not worth editing a live page for, so
   corrections need magnitude above a floor set well clear of the detection threshold.

Two rounds, then `degraded` with the diff attached. Not because two is magic, but
because a third attempt on something the first two could not move is evidence the
override is not the mechanism at fault.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.visual_diff import Diagnostic, DiffResult

# Round 1 corrects, round 2 corrects what round 1 missed, then a human looks.
MAX_ROUNDS = 2

# `visual_diff` flags drift past 12%. Correcting at 13% means re-publishing a live page
# over a difference nobody would notice, so the floor sits clear of the threshold.
MIN_MAGNITUDE = 0.20

# A background colour has no magnitude worth speaking of - it either matches or it does
# not - so `visual_diff` reports it at a flat 0.5. Judging it by the same floor as a
# size drift would silently drop every colour correction.
_FLAT_MAGNITUDE_KINDS = frozenset({"color"})


@dataclass(frozen=True)
class Override:
    """One token substitution, and the measurement that motivated it."""

    path: str
    value: str
    because: str


@dataclass(frozen=True)
class CorrectionPlan:
    """What to change this round, what a human has to look at, and whether to stop."""

    overrides: tuple[Override, ...] = ()
    unfixable: tuple[Diagnostic, ...] = ()
    stop: bool = False
    reason: str = ""
    notes: tuple[str, ...] = ()

    @property
    def should_republish(self) -> bool:
        """Only when there is something to change AND nothing said stop.

        Re-publishing with an empty override set would edit a client's live page to
        produce byte-identical output, which is a publish spent on nothing.
        """
        return bool(self.overrides) and not self.stop


@dataclass
class CorrectionHistory:
    """What has already been attempted, so a recurrence can be recognised."""

    rounds: int = 0
    attempted: set[tuple[str, str]] = field(default_factory=set)

    def key(self, diagnostic: Diagnostic) -> tuple[str, str]:
        return (diagnostic.kind, diagnostic.section)

    def record(self, overrides: tuple[Override, ...], diagnostics: list[Diagnostic]) -> None:
        self.rounds += 1
        applied = {o.because for o in overrides}
        for d in diagnostics:
            if d.detail in applied:
                self.attempted.add(self.key(d))


def _expected_px(detail: str) -> str:
    """The design-side value out of a diagnostic's own message.

    `visual_diff` writes "expected ~1180px, rendered 1440px". Reading it back is ugly,
    and the alternative is worse: re-deriving the expected value here means two places
    can disagree about what the design said, and the loop would then correct toward a
    number the diff never checked against.
    """
    import re

    m = re.search(r"expected ~?([\d.]+)px", detail)
    return f"{m.group(1).rstrip('.')}px" if m else ""


def _expected_colour(detail: str) -> str:
    import re

    m = re.search(r"expected (#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))", detail)
    return m.group(1) if m else ""


def _override_for(diagnostic: Diagnostic) -> Override | None:
    """The token substitution for one diagnostic, or None when it is not a token.

    Returning None is the common case and the safe one. A diagnostic with no mapping
    is a diagnostic a human reads.
    """
    kind, section, detail = diagnostic.kind, diagnostic.section, diagnostic.detail

    if kind == "typography" and section in ("heading", "body"):
        value = _expected_px(detail)
        if value:
            path = "typography.base_size" if section == "body" else "typography.heading_size"
            return Override(path=path, value=value, because=detail)
        return None

    if kind == "spacing" and section == "page":
        value = _expected_px(detail)
        if value:
            return Override(path="layout.container_width", value=value, because=detail)
        return None

    if kind == "color":
        value = _expected_colour(detail)
        if value:
            return Override(path=f"sections.{section}.bg_color", value=value, because=detail)
        return None

    # layout / size / image / alignment / responsive: NOT token substitutions. A
    # section-count mismatch is a rendering problem, and inventing a token for it is
    # how a correcting loop starts thrashing against a live site.
    return None


def _worth_correcting(diagnostic: Diagnostic) -> bool:
    if diagnostic.kind in _FLAT_MAGNITUDE_KINDS:
        return True
    return diagnostic.magnitude >= MIN_MAGNITUDE


def plan_corrections(
    diff: DiffResult, history: CorrectionHistory | None = None
) -> CorrectionPlan:
    """Decide what to change after one validation round.

    Total: never raises, never performs I/O. The caller owns rendering, publishing and
    re-capturing - this only decides, which is what makes the decision testable without
    a WordPress install.
    """
    history = history or CorrectionHistory()
    notes: list[str] = []

    if diff.status == "pass" or not diff.diagnostics:
        return CorrectionPlan(stop=True, reason="the rendered page matches the design")

    if history.rounds >= MAX_ROUNDS:
        return CorrectionPlan(
            unfixable=tuple(diff.diagnostics), stop=True,
            reason=(
                f"{MAX_ROUNDS} correction rounds did not resolve "
                f"{len(diff.diagnostics)} diagnostic(s); a human should look at the diff"
            ),
        )

    overrides: list[Override] = []
    unfixable: list[Diagnostic] = []

    for diagnostic in diff.diagnostics:
        if history.key(diagnostic) in history.attempted:
            # Point 2. An override was already sent for this and the page still
            # measures wrong, so something downstream is winning. Sending it again
            # cannot change that, and doing so is exactly how the loop oscillates.
            unfixable.append(diagnostic)
            notes.append(
                f"{diagnostic.kind}/{diagnostic.section}: an override was already "
                "applied and the page still renders this way - not retrying"
            )
            continue

        if not _worth_correcting(diagnostic):
            notes.append(
                f"{diagnostic.kind}/{diagnostic.section}: drift of "
                f"{diagnostic.magnitude:.0%} is under the {MIN_MAGNITUDE:.0%} floor; "
                "not worth re-publishing a live page for"
            )
            continue

        override = _override_for(diagnostic)
        if override is None:
            unfixable.append(diagnostic)
            notes.append(
                f"{diagnostic.kind}/{diagnostic.section} is not a token substitution; "
                "leaving it for a human"
            )
            continue
        overrides.append(override)

    if not overrides:
        return CorrectionPlan(
            unfixable=tuple(unfixable), stop=True, notes=tuple(notes),
            reason=(
                "nothing here is correctable by a token override; landing degraded "
                "with the diff attached"
            ),
        )

    return CorrectionPlan(
        overrides=tuple(overrides), unfixable=tuple(unfixable), notes=tuple(notes),
        reason=f"round {history.rounds + 1}: applying {len(overrides)} override(s)",
    )


def apply_overrides(design: dict[str, Any], overrides: tuple[Override, ...]) -> dict[str, Any]:
    """A COPY of ``design`` with each override's dotted path set.

    Copied rather than mutated: the original design is what the next round diffs
    against, and mutating it would make each round compare against the previous
    round's corrections instead of against the design.
    """
    import copy

    out = copy.deepcopy(design)
    for override in overrides:
        parts = override.path.split(".")
        cursor: Any = out
        for part in parts[:-1]:
            nxt = cursor.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[part] = nxt
            cursor = nxt
        cursor[parts[-1]] = override.value
    return out
