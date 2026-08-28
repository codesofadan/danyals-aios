"""Anchor safety: no exact-match commercial anchors, ever (R2-14).

THE PATTERN THIS REFUSES. The classic way a link profile gets actioned is not volume,
it is anchor text: N links whose clickable words are the exact commercial phrase the
page is trying to rank for. Natural editorial links are overwhelmingly brand names,
bare URLs, or ordinary sentence fragments. A run of "emergency drain unblocking leeds"
anchors pointing at /emergency-drain-unblocking-leeds is a pattern no human editor
produces, and it is trivially detectable.

WHY A HARD REFUSAL AND NOT A RATIO. There is no published safe percentage - every number
in circulation is somebody's correlation study, and encoding one would be inventing a
threshold and then defending it. What IS defensible is the shape: an anchor that is
exactly the money phrase has no editorial justification at all. So the rule is a floor,
not a quota - zero exact matches - and everything above the floor is left to the
operator's judgement rather than to a number we made up.

The money phrase is derived from the DESTINATION, not asked for separately: the slug of
the page being linked to is what the link is trying to rank, and an operator who has to
declare their own target keyword will simply declare a different one.

Pure: no DB, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

Verdict = Literal["ok", "exact_match", "empty", "too_long"]

#: Words that carry no commercial intent on their own; ignored when comparing an anchor
#: to a destination slug so "the drain unblocking service" is still recognised as the
#: money phrase wearing filler.
_STOPWORDS = frozenset({
    "a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or", "our",
    "the", "to", "with", "your",
})

#: An anchor longer than this is a sentence, not an anchor - and a sentence-long anchor
#: is its own footprint. Generous on purpose: natural anchors are sometimes long.
_MAX_WORDS = 12


@dataclass(frozen=True)
class AnchorVerdict:
    verdict: Verdict = "ok"
    reason: str = ""
    suggestion: str = ""

    @property
    def allowed(self) -> bool:
        return self.verdict == "ok"


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


def _significant(text: str) -> tuple[str, ...]:
    """Content words only, order preserved. Stopwords carry no commercial intent, so
    'the drain unblocking' and 'drain unblocking' must compare equal - otherwise the
    rule is defeated by adding 'the'."""
    return tuple(w for w in _words(text) if w not in _STOPWORDS)


def money_phrase(target_url: str, topic: str = "") -> tuple[str, ...]:
    """The commercial phrase a link is trying to rank, derived from the destination.

    The last meaningful path segment of the target URL: `/services/drain-unblocking`
    -> ('drain', 'unblocking'). Falls back to the topic when the URL has no path (a
    homepage link has no slug to read).
    """
    path = urlsplit(target_url.strip()).path if target_url else ""
    segments = [s for s in path.split("/") if s and "." not in s]
    if segments:
        return _significant(segments[-1])
    return _significant(topic)


def check_anchor(
    anchor: str, *, target_url: str, topic: str = "", client_name: str = ""
) -> AnchorVerdict:
    """Decide whether one anchor may be used.

    A BRAND anchor is always allowed even when it happens to contain the money words -
    a client called "Leeds Drain Unblocking" cannot be forbidden from using its own
    name, and refusing that would push the operator toward something less natural, not
    more.
    """
    cleaned = anchor.strip()
    if not cleaned:
        return AnchorVerdict("empty", "an anchor is required")
    if len(_words(cleaned)) > _MAX_WORDS:
        return AnchorVerdict(
            "too_long",
            f"{len(_words(cleaned))} words reads as a sentence, not an anchor",
            suggestion=client_name or "the brand name",
        )

    anchor_sig = _significant(cleaned)
    if not anchor_sig:
        return AnchorVerdict("empty", "the anchor is only filler words")

    # The brand exemption, applied first: a name is a name.
    brand = _significant(client_name)
    if brand and anchor_sig[: len(brand)] == brand:
        return AnchorVerdict("ok", "brand anchor")

    money = money_phrase(target_url, topic)
    if money and anchor_sig == money:
        return AnchorVerdict(
            "exact_match",
            f"'{cleaned}' is exactly the phrase {target_url} is trying to rank - the one "
            "anchor shape that has no editorial justification",
            suggestion=_suggest(client_name, cleaned),
        )
    return AnchorVerdict("ok", "")


def _suggest(client_name: str, anchor: str) -> str:
    """Offer the operator a usable alternative rather than only a refusal."""
    if client_name:
        return f"{client_name}  ·  {client_name}'s {anchor}  ·  a bare URL"
    return f"the brand name  ·  a natural phrase containing '{anchor}'  ·  a bare URL"


def first_allowed(
    anchors: list[str], *, target_url: str, topic: str = "", client_name: str = ""
) -> tuple[str, AnchorVerdict]:
    """The first usable anchor from an operator's list, and why the others were skipped.

    Returns the brand (or the first anchor) when every candidate is refused, so a
    campaign is never left with no anchor at all - a placement with no link text is a
    worse outcome than a slightly duller one.
    """
    last = AnchorVerdict("empty", "no anchors supplied")
    for candidate in anchors:
        verdict = check_anchor(
            candidate, target_url=target_url, topic=topic, client_name=client_name
        )
        if verdict.allowed:
            return candidate, verdict
        last = verdict
    fallback = client_name.strip() or (anchors[0].strip() if anchors else "")
    return fallback, last
