"""Never pay to write the same keyword twice for one client.

THE PROBLEM, and why it only shows up at volume. Each content job is created, researched
and drafted independently - correctly, since that is what lets thirty pages run in parallel
and one failure not take the rest down. The cost is that nothing has ever compared a new
page's target keyword against what this client already has published or in flight. Build
five pages a month by hand and you notice; fan out thirty from a research pass and you are
funding two pages that compete with each other, and the one that loses was paid for in
full.

WHAT THIS CHECKS, and deliberately nothing more:

  * the job's PRIMARY KEYWORD (``source_pack.primary_keyword``), normalised, and
  * the job's TOPIC, normalised - because a single-job create may carry no keyword at all,
    and the topic is then the only thing that says what the page is about.

An exact match after normalisation is a collision. That is a narrow test on purpose: a
fuzzy one ("emergency plumber" vs "emergency plumbing services") would fire on the pillar
and its own supporting pages, which are SUPPOSED to share a topic - a cluster is not
cannibalisation - and an operator who is warned about every legitimate page stops reading
the warnings. Better to catch the unambiguous case reliably than the ambiguous one
loudly.

REJECTED JOBS DO NOT COLLIDE. A rejected draft is a page the agency decided not to have, so
the keyword is free again. Everything else counts, including a job still drafting: two
pages racing for one keyword is the exact thing being prevented, and waiting until one
publishes would be waiting until the money is spent.

Pure: no database, no network, no clock. The caller supplies the existing rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: Statuses whose keyword is considered FREE again. Only a rejected page qualifies.
FREE_STATUSES: frozenset[str] = frozenset({"rejected"})

_PUNCT = re.compile(r"[^\w\s]+")
_SPACE = re.compile(r"\s+")
#: Words that carry no targeting signal, so their presence or absence must not make two
#: otherwise identical targets look different ("plumber in leeds" vs "plumber leeds").
_NOISE: frozenset[str] = frozenset({"a", "an", "the", "in", "of", "for", "to", "and", "near"})


def normalise(term: str) -> str:
    """The comparable form of a keyword or topic.

    Lowercase, punctuation stripped, whitespace collapsed, and the handful of connecting
    words removed that change nothing about what a page targets. Deterministic and
    reversible enough to explain: an operator shown a collision can see why the two
    matched.
    """
    text = _PUNCT.sub(" ", str(term or "").lower())
    words = [w for w in _SPACE.sub(" ", text).strip().split(" ") if w and w not in _NOISE]
    return " ".join(words)


@dataclass(frozen=True, slots=True)
class Collision:
    """One clash: what was asked for, and the page that already holds it."""

    term: str
    code: str
    topic: str
    status: str
    #: "keyword" when the target term matched, "topic" when only the subject matched.
    matched: str

    def as_dict(self) -> dict[str, str]:
        return {
            "term": self.term,
            "code": self.code,
            "topic": self.topic,
            "status": self.status,
            "matched": self.matched,
        }

    @property
    def message(self) -> str:
        """One sentence an operator can act on without opening anything else."""
        what = "target keyword" if self.matched == "keyword" else "topic"
        return (
            f'"{self.term}" is already the {what} of {self.code} '
            f"({self.topic or 'untitled'}, {self.status})."
        )


def index_existing(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build ``normalised term -> the job holding it`` from the client's existing jobs.

    A keyword and a topic both map into the same index, with the KEYWORD winning when both
    are present on one row: the keyword is what the page was actually optimised for, and
    reporting the topic instead would name the page correctly and the reason wrongly.

    Earliest job wins a tie, so the collision names the page that got there first rather
    than whichever row the database happened to return last.
    """
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        status = str(row.get("status") or "")
        if status in FREE_STATUSES:
            continue
        code = str(row.get("code") or "")
        topic = str(row.get("topic") or "")
        keyword = str(row.get("keyword") or "")
        for term, kind in ((keyword, "keyword"), (topic, "topic")):
            key = normalise(term)
            if not key:
                continue
            existing = index.get(key)
            if existing is not None and not (kind == "keyword" and existing["matched"] == "topic"):
                continue
            index[key] = {"code": code, "topic": topic, "status": status, "matched": kind}
    return index


def find_collisions(
    wanted: list[tuple[str, str]], existing: list[dict[str, Any]]
) -> list[Collision]:
    """Which of the requested pages clash with what this client already has.

    ``wanted`` is ``(keyword, topic)`` per requested page - the keyword may be empty, in
    which case only the topic is checked, which is exactly the single-job create's case.

    ALSO CATCHES CLASHES WITHIN THE REQUEST ITSELF. A research pass can return two items
    that normalise to the same target, and fanning both out would create the clash rather
    than inherit it - so each item's keys are claimed after it is checked, and a later item
    wanting the same target reports against it.

    AN ITEM NEVER COLLIDES WITH ITSELF, and the first version of this did. It checked and
    claimed one candidate at a time, so an item whose KEYWORD and TOPIC normalise alike -
    ("emergency plumber leeds", "Emergency plumber in Leeds"), which is the overwhelmingly
    common shape - claimed the key on its keyword and then reported its own topic as a
    clash against "(this request)". Measured on the first two tests written for it. So each
    item is CHECKED in full first, then CLAIMS in full.
    """
    index = index_existing(existing)
    out: list[Collision] = []
    for keyword, topic in wanted:
        term = keyword.strip() or topic.strip()
        # This item's distinct targets, keyword first so a hit reports the stronger reason.
        candidates = [
            (normalise(value), kind)
            for value, kind in ((keyword, "keyword"), (topic, "topic"))
            if normalise(value)
        ]
        hit = next(
            (index[key] for key, _ in candidates if key in index),
            None,
        )
        if hit is not None:
            out.append(Collision(
                term=term,
                code=str(hit["code"]),
                topic=str(hit["topic"]),
                status=str(hit["status"]),
                matched=str(hit["matched"]),
            ))
            continue
        for key, kind in candidates:
            index[key] = {
                "code": "(this request)",
                "topic": topic,
                "status": "requested",
                "matched": kind,
            }
    return out


def collision_detail(collisions: list[Collision]) -> str:
    """The refusal message: every clash, and how to proceed anyway."""
    lines = [c.message for c in collisions]
    return (
        "Already targeted for this client: "
        + " ".join(lines)
        + " Two pages chasing one keyword compete with each other, so this was not "
        "created. Change the target, or resend with allowDuplicates to build it anyway."
    )
