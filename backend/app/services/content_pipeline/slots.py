"""The typed contract for ONE section slot: what a writer must return to fill it.

WHY THIS EXISTS, and it is the fix for a defect an operator caught on a live client page.
The page templates (``page_blueprints``) have always described a real page - hero, then a
grid of what is included, then a numbered process, then proof, then a price, then a CTA.
But the template reached only the PUBLISH path, where it was applied as a WRAPPER over
prose the writer had already produced to its own plan. The writer never saw the wireframe.
So a service page with seven named slots met a draft with headings like "Where agency SEO
breaks", the wrapper found nothing that looked like pricing or testimonials, and the
published page was a hero, a wall of prose and a CTA. Measured on the real push: seven
slots specified, three rendered, five images scattered through the prose wherever an H2
happened to fall.

The repair is to stop treating the page as prose that gets shaped afterwards, and start
treating it as a FORM THE WRITER FILLS:

    a slot declares its FIELDS  ->  the writer returns exactly those fields, as JSON
                                ->  a renderer draws that shape, in the client's design

This module is the first arrow: the vocabulary of slot kinds, the exact JSON each one
must come back as, and the validation that decides whether a slot was actually filled.

THREE RULES THE SCHEMAS ENCODE, each of which was a real failure mode:

  1. EVERY FIELD IS BOUNDED. A grid that renders three cards and a writer that returns
     nine produces either a broken layout or six silently dropped paragraphs; a bounded
     schema makes the count part of the request.
  2. A SLOT IS EITHER FILLED OR DROPPED. There is no half-filled section: a testimonials
     block with one empty quote is worse than no testimonials block, because it looks
     like a rendering bug to the client and like a content bug to us.
  3. EVIDENCE-GATED SLOTS CANNOT BE WRITTEN FROM THE BRIEF. `pricing`, `testimonials`,
     `team`, `stats` and the local blocks name the client data they need. Without it the
     slot is dropped BEFORE the writer is asked, so the model is never put in the
     position of inventing a price - which is the one thing a fixed seven-section
     wireframe would otherwise guarantee it does.

Pure: no network, no DB, no provider, no clock. The writer call lives in ``compose``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# Field types the renderers know how to draw.
# --------------------------------------------------------------------------- #
#: A single line of text (heading, label, button).
TEXT = "text"
#: A paragraph or several.
PROSE = "prose"
#: A repeated item with its own sub-fields.
ITEMS = "items"


@dataclass(frozen=True)
class SlotField:
    """One field of a slot payload: its name, its shape, and its bounds.

    ``min_count`` / ``max_count`` bound a repeated field; ``max_chars`` bounds a text or
    prose field. The bounds are part of the PROMPT as well as the validation, so the
    writer is told the size of the box before it writes rather than after.
    """

    name: str
    kind: str
    max_chars: int = 0
    min_count: int = 0
    max_count: int = 0
    #: Sub-fields for an ``ITEMS`` field, e.g. ``("title", "text")``.
    item_fields: tuple[str, ...] = ()
    #: A field the renderer can draw without, e.g. a section's intro line.
    optional: bool = False
    #: Shown to the writer so it knows what belongs here. One short sentence.
    hint: str = ""


@dataclass(frozen=True)
class SlotSchema:
    """The full contract for one section kind."""

    kind: str
    #: What this section is FOR, in the writer's terms. Goes into the prompt verbatim.
    purpose: str
    fields: tuple[SlotField, ...]
    #: The client data this slot cannot exist without ("" = writable from the brief).
    evidence: str = ""
    #: True when the renderer supplies this section from live data (NAP, reviews, a map)
    #: and no copy is requested at all.
    chrome: bool = False

    def required_fields(self) -> tuple[SlotField, ...]:
        return tuple(f for f in self.fields if not f.optional)

    def example(self) -> dict[str, Any]:
        """A shape-only example for the prompt - types and counts, never sample copy.

        Sample copy in a prompt is the fastest way to get sample copy back: a model shown
        "Fast, friendly service" as an example of a benefit title will write variations of
        it for every client in every vertical.
        """
        out: dict[str, Any] = {}
        for f in self.fields:
            if f.kind in (TEXT, PROSE):
                out[f.name] = f"<{f.name}, max {f.max_chars} chars>"
            else:
                item = {sub: f"<{sub}>" for sub in f.item_fields}
                out[f.name] = [item, "... "
                               f"{f.min_count}-{f.max_count} items"]
        return out


def _f(
    name: str,
    kind: str,
    *,
    max_chars: int = 0,
    min_count: int = 0,
    max_count: int = 0,
    item_fields: tuple[str, ...] = (),
    optional: bool = False,
    hint: str = "",
) -> SlotField:
    return SlotField(
        name=name, kind=kind, max_chars=max_chars, min_count=min_count,
        max_count=max_count, item_fields=item_fields, optional=optional, hint=hint,
    )


# --------------------------------------------------------------------------- #
# The schemas, one per section kind the templates use.
# --------------------------------------------------------------------------- #
SLOT_SCHEMAS: dict[str, SlotSchema] = {
    "hero": SlotSchema(
        "hero",
        "The first screen. Say what this page is and who it is for, in the words the "
        "searcher used. No throat-clearing, no 'welcome to'.",
        (
            _f("heading", TEXT, max_chars=70, hint="the page's H1; contains the keyword"),
            _f("subheading", PROSE, max_chars=220, hint="one sentence, the promise"),
            _f("bullets", ITEMS, min_count=0, max_count=3, item_fields=("text",),
               optional=True, hint="up to three proof-flavoured one-liners"),
            _f("cta_label", TEXT, max_chars=28, hint="the button words, e.g. 'Get a quote'"),
        ),
    ),
    "intro": SlotSchema(
        "intro",
        "Why this matters to the reader, before any selling. Answer the question the "
        "search implied, directly, in the first two lines.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("paragraphs", ITEMS, min_count=2, max_count=3, item_fields=("text",),
               hint="60-90 words each"),
        ),
    ),
    "about": SlotSchema(
        "about",
        "Who the business is, in a way a stranger can verify. Specifics only.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("paragraphs", ITEMS, min_count=2, max_count=3, item_fields=("text",)),
        ),
    ),
    "conclusion": SlotSchema(
        "conclusion",
        "Close the argument the page made. No new claims, no summary of the summary.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("paragraphs", ITEMS, min_count=1, max_count=2, item_fields=("text",)),
        ),
    ),
    "features": SlotSchema(
        "features",
        "What the buyer actually receives. Each card is a deliverable, not an adjective.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("intro", PROSE, max_chars=200, optional=True),
            _f("items", ITEMS, min_count=3, max_count=6, item_fields=("title", "text"),
               hint="title = the deliverable, text = 20-35 words on what it includes"),
        ),
    ),
    "benefits": SlotSchema(
        "benefits",
        "The outcomes the buyer gets. Each one names a consequence, not a feature.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("intro", PROSE, max_chars=200, optional=True),
            _f("items", ITEMS, min_count=3, max_count=6, item_fields=("title", "text")),
        ),
    ),
    "services": SlotSchema(
        "services",
        "The services on offer, as a grid a buyer can scan and pick from.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("intro", PROSE, max_chars=200, optional=True),
            _f("items", ITEMS, min_count=3, max_count=6, item_fields=("title", "text")),
        ),
    ),
    "process": SlotSchema(
        "process",
        "How the work actually runs, step by step. Each step says what happens and who "
        "does it - this is the section that removes the buyer's fear of the unknown.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("intro", PROSE, max_chars=200, optional=True),
            _f("steps", ITEMS, min_count=3, max_count=5, item_fields=("title", "text"),
               hint="title = the step, text = 20-35 words on what happens in it"),
        ),
    ),
    "faq": SlotSchema(
        "faq",
        "The questions this buyer actually types before they buy. Answer each one in the "
        "first sentence, then add the detail - an answer that builds to its point cannot "
        "be lifted into a featured snippet.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("items", ITEMS, min_count=4, max_count=8,
               item_fields=("question", "answer"),
               hint="answer = 40-70 words, direct answer first"),
        ),
    ),
    "cta": SlotSchema(
        "cta",
        "One next step, stated plainly. What to do, and what happens when they do it.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("text", PROSE, max_chars=220),
            _f("button_label", TEXT, max_chars=28),
        ),
    ),
    "body": SlotSchema(
        "body",
        "The article itself, as markdown with ## subheadings. This is the only slot that "
        "carries long-form prose; everything around it is structured.",
        (
            _f("markdown", PROSE, max_chars=12000,
               hint="## subheadings, short paragraphs, lists where they earn their place"),
        ),
    ),
    # --- evidence-gated: these cannot be written from the brief ---------------- #
    "testimonials": SlotSchema(
        "testimonials",
        "Real client words, quoted. Never paraphrased into marketing copy.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("quotes", ITEMS, min_count=1, max_count=4,
               item_fields=("quote", "author", "role"),
               hint="quote the supplied testimonial; attribute only what was supplied"),
        ),
        evidence="testimonials",
    ),
    "pricing": SlotSchema(
        "pricing",
        "The prices the client actually charges, as cards a buyer can compare.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("intro", PROSE, max_chars=200, optional=True),
            _f("tiers", ITEMS, min_count=1, max_count=4,
               item_fields=("name", "price", "summary", "cta_label"),
               hint="price exactly as supplied - never rounded, never invented"),
        ),
        evidence="pricing",
    ),
    "stats": SlotSchema(
        "stats",
        "Numbers the client supplied, as tiles. Each tile is one figure and its label.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("stats", ITEMS, min_count=2, max_count=4, item_fields=("value", "label")),
        ),
        evidence="stats",
    ),
    "team": SlotSchema(
        "team",
        "The named people the client supplied, with their real roles.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("people", ITEMS, min_count=1, max_count=6,
               item_fields=("name", "role", "bio")),
        ),
        evidence="team",
    ),
    "proof": SlotSchema(
        "proof",
        "The evidence behind the page's claims, each tied to where it came from.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("points", ITEMS, min_count=2, max_count=5,
               item_fields=("claim", "source")),
        ),
        evidence="proof",
    ),
    "service_areas": SlotSchema(
        "service_areas",
        "The places the client actually covers, as a scannable list.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("intro", PROSE, max_chars=200, optional=True),
            _f("areas", ITEMS, min_count=3, max_count=24, item_fields=("name",)),
        ),
        evidence="areas",
    ),
    "reviews": SlotSchema(
        "reviews",
        "What clients have actually said, quoted. Never paraphrased into marketing copy.",
        (
            _f("heading", TEXT, max_chars=70),
            _f("quotes", ITEMS, min_count=1, max_count=4,
               item_fields=("quote", "author", "role"),
               hint="quote the supplied feedback; attribute only what was supplied"),
        ),
        evidence="reviews",
    ),
    # --- chrome: rendered from live data, no copy requested -------------------- #
    "contact": SlotSchema(
        "contact", "The business's real address, phone and hours.", (), evidence="nap",
        chrome=True,
    ),
    "related": SlotSchema(
        "related", "Links to the client's other pages.", (), evidence="links", chrome=True,
    ),
    "trust_bar": SlotSchema(
        "trust_bar", "Client logos or trust marks.", (), evidence="logos", chrome=True,
    ),
    "map": SlotSchema("map", "An embedded map.", (), evidence="nap", chrome=True),
    "hours": SlotSchema("hours", "Opening hours.", (), evidence="nap", chrome=True),
    "gallery": SlotSchema("gallery", "The client's own photographs.", (), evidence="photos",
                          chrome=True),
    "search": SlotSchema("search", "A search box.", (), chrome=True),
}


def schema_for(kind: str) -> SlotSchema | None:
    """The contract for a section kind, or None when the kind is not one we fill."""
    return SLOT_SCHEMAS.get(str(kind or "").strip().lower())


# --------------------------------------------------------------------------- #
# Validation: did the writer actually fill the slot?
# --------------------------------------------------------------------------- #
@dataclass
class SlotResult:
    """One validated slot payload, or the reason it could not be used."""

    kind: str
    data: dict[str, Any] = field(default_factory=dict)
    ok: bool = False
    reason: str = ""


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def parse_json_object(raw: str) -> dict[str, Any]:
    """Parse a model's JSON reply, tolerating the wrappers models actually emit.

    A fenced block, a leading sentence, a trailing apology - all of which have been seen
    from every provider - are stripped before parsing rather than treated as a failure,
    because re-asking costs a whole call to fix punctuation.
    """
    text = (raw or "").strip()
    if not text:
        return {}
    text = _FENCE_RE.sub("", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    # A model asked for a heading sometimes returns "## Heading" out of habit.
    text = re.sub(r"^#{1,6}\s*", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    if limit and len(text) > limit:
        # Cut at a word boundary: a heading ending mid-word looks like a bug to a reader
        # and is one to a search engine.
        cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:- ")
        text = cut or text[:limit]
    return text


def _clean_items(value: Any, field_spec: SlotField) -> list[dict[str, str]]:
    raw = value if isinstance(value, list) else []
    out: list[dict[str, str]] = []
    for entry in raw:
        if isinstance(entry, str):
            # A single-field item list may legitimately come back as plain strings.
            if field_spec.item_fields:
                item = {field_spec.item_fields[0]: _clean_text(entry, 400)}
            else:
                continue
        elif isinstance(entry, dict):
            item = {
                sub: _clean_text(entry.get(sub), 600) for sub in field_spec.item_fields
            }
        else:
            continue
        # An item whose FIRST field is empty is not an item - it is a hole the renderer
        # would draw as an empty card.
        if field_spec.item_fields and not item.get(field_spec.item_fields[0]):
            continue
        out.append(item)
        if field_spec.max_count and len(out) >= field_spec.max_count:
            break
    return out


def validate_slot(kind: str, payload: Any) -> SlotResult:
    """Coerce and bound one slot payload against its schema.

    Returns ``ok=False`` with a reason rather than raising: one bad slot must cost the
    page that slot, never the page.
    """
    schema = schema_for(kind)
    if schema is None:
        return SlotResult(kind=kind, reason="no schema for this section kind")
    if schema.chrome:
        return SlotResult(kind=kind, ok=True, data={})
    if not isinstance(payload, dict):
        return SlotResult(kind=kind, reason="payload was not an object")

    data: dict[str, Any] = {}
    for spec in schema.fields:
        value = payload.get(spec.name)
        if spec.kind in (TEXT, PROSE):
            text = _clean_text(value, spec.max_chars)
            if text:
                data[spec.name] = text
            elif not spec.optional:
                return SlotResult(kind=kind, reason=f"missing {spec.name}")
        else:
            items = _clean_items(value, spec)
            if len(items) < max(spec.min_count, 0) and not spec.optional:
                return SlotResult(
                    kind=kind,
                    reason=f"{spec.name}: {len(items)} of {spec.min_count} required items",
                )
            if items:
                data[spec.name] = items
    return SlotResult(kind=kind, ok=True, data=data)
