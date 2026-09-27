"""Named problems instead of a score: what a reviewer is actually shown.

THE DECISION THIS IMPLEMENTS (operator, 2026-09-26). The 14-dimension QA scorecard stays
exactly as it is - computed, stored, logged - but the weighted TOTAL is no longer put in
front of the person approving a draft. The reason is written into `content_qa` itself:
that threshold and its weight vector are provisional and uncalibrated against ranking
outcomes or a human SEO grade, so "61/100" reads as a judgement the number cannot support.
A reviewer who trusts it is misled, and a reviewer who learns to ignore it has a screen
full of noise.

What survives is the half that was always trustworthy: the deterministic detections. "A
claim with no source" is not a matter of calibration - either the draft asserts something
that traces to nothing supplied, or it does not. So this module turns the stored scorecard
into a short list of NAMED PROBLEMS in the reviewer's own language, and says nothing at all
when there is nothing to say.

    fact_grounding below its floor   ->  "A claim in this draft has no source"
    eeat_experience below its floor  ->  "No first-hand experience in this draft"

RULES THAT KEEP IT HONEST:

  * A flag is only raised for a dimension that was actually MEASURED. An unmeasured
    dimension (``UNMEASURED``) produces no flag, because "we did not look" and "we looked
    and it is wrong" are opposite claims (the same rule the audit rollups enforce).
  * The five hard-gate dimensions raise a `problem`; everything else below its floor
    raises a quieter `note`. That ranking is the doctrine's own, not a new invention.
  * No score, no threshold and no total appears in the output - not as a number, not in a
    string. A number that is not defensible must not leak back in through a label.
  * Degraded judging is disclosed. When the scorecard says its judged dimensions fell back
    to deterministic proxies, that is surfaced as a note, because a clean-looking review
    screen produced by a broken judge is the failure this whole change is guarding against.

Pure: no database, no network, no model, no clock. One stored scorecard in, one flag list
out, byte-identical every time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.content_qa import (
    HARD_GATE_DIMENSIONS,
    MIN_DIMENSION_SCORE,
    UNMEASURED,
)

#: Reviewer-facing wording per dimension: what is wrong, and what to do about it. Written
#: for the person deciding whether to publish, not for the engineer who wrote the scorer.
FLAG_COPY: dict[str, tuple[str, str]] = {
    "fact_grounding": (
        "A claim here has no source",
        "Something stated as fact does not trace to anything the client supplied. Check the "
        "numbers, dates and credentials before this goes out.",
    ),
    "eeat_experience": (
        "No first-hand experience",
        "Nothing in the draft could only have been written by someone who does this work. "
        "This is the signal a competitor cannot copy, so it is worth sending back for.",
    ),
    "originality": (
        "Reads like pages that already exist",
        "The draft overlaps heavily with what is already ranking, or with another page on "
        "this site. Ask for the angle that makes it different.",
    ),
    "intent_match": (
        "Does not answer what the searcher wants",
        "The page's shape does not match what this search actually returns - a comparison "
        "query answered with a service pitch, or the reverse.",
    ),
    "information_gain": (
        "Adds nothing new",
        "There is no differentiating point the competing pages do not already make.",
    ),
    "schema_validity": (
        "The structured data does not match the page",
        "The JSON-LD claims something the visible text does not say. Search engines treat "
        "that as a mismatch, so it is worth fixing before publish.",
    ),
    "entity_coverage": (
        "Misses topics the ranking pages all cover",
        "Several things every competing page discusses are absent here.",
    ),
    "keyword_handling": (
        "Keyword use looks forced",
        "The target term is repeated more than it reads naturally, or barely appears.",
    ),
    "structure_readability": (
        "Hard to read, or badly structured",
        "Heading hierarchy or sentence complexity is off - check for more than one H1 and "
        "for paragraphs nobody will finish.",
    ),
    "snippet_extractability": (
        "No direct answer to lift",
        "There is no short, self-contained answer near the top, which is what an AI "
        "overview or a featured snippet quotes.",
    ),
    "internal_linking": (
        "Not linked into the rest of the site",
        "The page neither links out to related pages nor gives anything to link back to.",
    ),
    "cta_ux": (
        "No clear next step",
        "A reader convinced by this page has nothing obvious to do next.",
    ),
    "local_relevance": (
        "Not specific to the place",
        "A location page that would read identically for any other town. Check the address, "
        "the service area and anything genuinely local.",
    ),
    "serp_format_fit": (
        "Wrong format for this search",
        "The results for this term are a different kind of page than this one.",
    ),
}


@dataclass(frozen=True, slots=True)
class ReviewFlag:
    """One named problem for the reviewer. ``kind`` is ``problem`` or ``note``."""

    key: str
    title: str
    detail: str
    kind: str

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "title": self.title, "detail": self.detail, "kind": self.kind}


def _dimensions(stored: dict[str, Any]) -> dict[str, float]:
    raw = stored.get("dimensions")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def flags_for(stored: dict[str, Any] | None) -> list[ReviewFlag]:
    """The named problems in one stored scorecard, most serious first.

    An empty list means the deterministic checks found nothing to raise - which is the
    common case for a good draft, and is exactly what the reviewer should see then. A
    scorecard that is absent entirely (the job has not reached review, or predates the
    scorer) also yields nothing: inventing a warning from missing data would be the same
    class of mistake as inventing a score.
    """
    stored = stored or {}
    dims = _dimensions(stored)
    problems: list[ReviewFlag] = []
    notes: list[ReviewFlag] = []
    for key, score in dims.items():
        # Unmeasured is not a failure. "We did not look" and "we looked and it is wrong"
        # are opposite claims and must never share a rendering.
        if score == UNMEASURED or score >= MIN_DIMENSION_SCORE:
            continue
        title, detail = FLAG_COPY.get(
            key,
            (key.replace("_", " ").capitalize(), "This check did not pass."),
        )
        if key in HARD_GATE_DIMENSIONS:
            problems.append(ReviewFlag(key, title, detail, "problem"))
        else:
            notes.append(ReviewFlag(key, title, detail, "note"))

    # A judge that could not run leaves five dimensions on conservative proxies. Saying so
    # is the difference between "nothing was found" and "nothing could be checked".
    for note in stored.get("notes") or []:
        text = str(note)
        if "proxy" in text.lower() or "judge" in text.lower():
            notes.append(ReviewFlag(
                "judge_degraded",
                "Some checks could not run",
                "The automated reader was unavailable, so the judgement-based checks fell "
                "back to rough approximations. Read this one closely.",
                "note",
            ))
            break

    # Problems before notes, and stable within each group so the panel does not reshuffle
    # between two reads of the same draft.
    problems.sort(key=lambda f: f.key)
    notes.sort(key=lambda f: f.key)
    return problems + notes


def flags_payload(stored: dict[str, Any] | None) -> dict[str, Any]:
    """The API shape: the flags, and a count the UI can badge without re-deriving it."""
    flags = flags_for(stored)
    return {
        "flags": [f.as_dict() for f in flags],
        "problems": sum(1 for f in flags if f.kind == "problem"),
        "notes": sum(1 for f in flags if f.kind == "note"),
    }
