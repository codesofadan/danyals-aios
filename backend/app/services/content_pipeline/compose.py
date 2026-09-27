"""Compose - fill the page's SEVEN slots, as data, in one governed call.

THE STAGE THIS REPLACES. `draft` writes the page as prose: batches of sections, each a
run of markdown, stitched into one document that the publish path later tried to cut back
into sections by looking at its H2s. That round trip - structure to prose and back - is
where the page was lost. The writer chose its own headings (it had no reason not to), the
publish path could not recognise them as "pricing" or "what clients say", and a seven-slot
template rendered as three.

Here the wireframe IS the request. The writer is handed the slots, their field names, their
counts and their character budgets, and returns ONE JSON object keyed by slot id. Nothing
is parsed out of prose afterwards, because nothing was written as prose.

WHY ONE CALL AND NOT SEVEN. A slot written blind to the others repeats them: the benefits
grid and the features grid converge, the FAQ re-answers the intro, and every section opens
with the same clause. One call sees the whole page, which is also what lets it put the
deliverables in `features` and the objections in `faq` rather than both in both. The cost
is a larger single response; the alternative is seven responses that have to be de-duped
afterwards by a human.

WHAT IS NOT SENT TO THE WRITER AT ALL:

  * EVIDENCE-GATED SLOTS WITH NO EVIDENCE. `pricing` without prices is not in the prompt,
    so the model is never in the position of filling a pricing section from imagination.
    This is what makes a FIXED wireframe safe: the shape is fixed, the fabrication is not.
  * CHROME. NAP, reviews, maps, logos come from client data at render time; asking a writer
    for them would produce a plausible address.

DEGRADING IS PER SLOT. A slot that comes back malformed is dropped with its reason
recorded; the page renders the rest. The stage only fails when the page would have fewer
than `MIN_SECTIONS` real sections, because at that point it is not a page.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.services.content_pipeline.claims import (
    apply_deletions,
    audit_draft,
    build_atoms,
    split_units,
    vendor_pattern,
)
from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_pipeline.grounding import unsourced_figures
from app.services.content_pipeline.slots import (
    SlotResult,
    parse_json_object,
    schema_for,
    validate_slot,
)
from app.services.content_pipeline.writer import DoctrineWriter, WriteAccounting
from app.services.page_blueprints import SectionSpec

STAGE = "compose"

#: Below this many filled content sections the result is not a page, and publishing it
#: would put a hero and a CTA on a client's site. Three is a hero plus two real blocks.
MIN_SECTIONS = 3

#: Token headroom for the whole page's JSON. Seven slots of bounded fields runs ~1,200-
#: 1,800 output tokens; the ceiling is generous because a response cut mid-JSON is a
#: total loss (nothing parses), unlike prose where a cut costs one paragraph.
MAX_TOKENS = 8000


@dataclass
class ComposedSection:
    """One filled slot, ready for the page model."""

    kind: str
    layout: str = "stacked"
    heading: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "layout": self.layout, "heading": self.heading,
                "data": dict(self.data)}


@dataclass
class ComposeResult:
    """What the stage produced: the filled sections and what was dropped, with reasons."""

    sections: list[ComposedSection] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def kinds(self) -> list[str]:
        return [s.kind for s in self.sections]


def evidence_for(ctx: PipelineContext, source: str) -> tuple[str, ...]:
    """THE CLIENT'S OWN MATERIAL for an evidence-gated slot, verbatim.

    Both the gate and the prompt come from here, and returning the LINES rather than a
    yes/no is the point. A gate that only answers "yes, they supplied a team" puts a team
    section on the page and tells the writer nothing about who is on it - so the writer
    generalises, because generalising is the only honest thing left to do. MEASURED on a
    real run: three coaches supplied by name, role and background came back as "Age group
    squad coaches / Goalkeeping coach / Holiday camp staff", with a line added explaining
    that the academy names its coaches in person rather than publishing them.

    Read from the job's own pack and the answered Experience facts, never inferred from
    the brief, because the brief is about the SEARCH and not about this client. An unknown
    source returns empty, so a slot whose evidence cannot be confirmed is dropped: the page
    loses a section rather than gaining a fabrication.
    """
    # The job's own pack, seeded by the worker. `brief` is consulted as a fallback only
    # because an older caller put the pack under that key; it is not where the product
    # writes it, and reading ONLY there is why every gated slot was dropped from every
    # page - the gate was asking a dictionary that was always empty.
    pack = ctx.source_pack if isinstance(ctx.source_pack, dict) and ctx.source_pack else None
    if pack is None:
        brief_pack = ctx.brief.get("source_pack") if isinstance(ctx.brief, dict) else None
        pack = brief_pack if isinstance(brief_pack, dict) else {}

    def _lines(*keys: str) -> tuple[str, ...]:
        out: list[str] = []
        for key in keys:
            value = pack.get(key)
            if isinstance(value, str) and value.strip():
                out.append(value.strip())
            elif isinstance(value, (list, tuple)):
                out.extend(str(v).strip() for v in value if str(v).strip())
            elif isinstance(value, dict) and value:
                out.extend(f"{k}: {v}" for k, v in value.items() if str(v).strip())
        return tuple(out)

    if source == "testimonials":
        return _lines("testimonials")
    if source == "pricing":
        return _lines("pricing", "prices", "packages")
    if source == "stats":
        return _lines("unique_data", "stats")
    if source == "team":
        return _lines("team", "people")
    if source == "areas":
        return _lines("service_areas", "areas")
    if source == "reviews":
        # A "reviews" section and a "testimonials" section want the same thing: quotes the
        # client actually supplied. The operator has one place to put them, so reading only
        # a `reviews` key meant the reviews block on every location page was gated on a
        # field nothing writes, while the quotes sat in `testimonials` unused.
        return _lines("reviews", "testimonials")
    if source == "proof":
        # Proof is the one gate the ANSWERED experience can satisfy on its own: a page
        # whose SME slots carry a licence number or a job count has evidence to cite.
        return _lines("proof_points", "unique_data") or tuple(ctx.facts)
    if source == "nap":
        # The name/address/phone comes from the client's stored business profile, which
        # the assembly puts on the pack - not from anything typed into this request.
        return _lines("nap")
    if source in {"logos", "photos", "links"}:
        return _lines(source)
    return ()


def evidence_available(ctx: PipelineContext, source: str) -> bool:
    """Whether the client supplied what an evidence-gated slot needs - the gate itself."""
    return bool(evidence_for(ctx, source))


def plan_slots(
    specs: tuple[SectionSpec, ...] | list[SectionSpec], ctx: PipelineContext
) -> tuple[list[SectionSpec], list[tuple[str, str]]]:
    """Split the wireframe into slots to WRITE and slots dropped for missing evidence."""
    keep: list[SectionSpec] = []
    dropped: list[tuple[str, str]] = []
    for spec in specs:
        schema = schema_for(spec.kind)
        if schema is None:
            dropped.append((spec.kind, "no slot schema"))
            continue
        source = spec.evidence or schema.evidence
        if source and not evidence_available(ctx, source):
            dropped.append((spec.kind, f"no {source} supplied by the client"))
            continue
        if schema.chrome:
            # Chrome with its evidence present still renders, but it is drawn from data
            # rather than written - so it is kept OUT of the writer's request.
            keep.append(spec)
            continue
        keep.append(spec)
    return keep, dropped


def _slot_id(index: int, kind: str) -> str:
    return f"s{index + 1}_{kind}"


def build_prompt(specs: list[SectionSpec], ctx: PipelineContext) -> str:
    """The whole page as one instruction: the wireframe, the brief, the hard rules."""
    brief = ctx.brief if isinstance(ctx.brief, dict) else {}
    lines: list[str] = []
    lines.append(
        "Fill every slot of this page wireframe. Return ONE JSON object whose keys are "
        "the slot ids below and whose values are exactly the fields each slot declares. "
        "No markdown, no commentary, no extra keys."
    )
    lines.append("")
    lines.append(f"PAGE: {ctx.primary_keyword or ctx.title}")
    # THE SEARCH PHRASE, AND WHERE IT HAS TO LAND.
    #
    # Naming the subject is not the same as asking for the phrase, and the difference is
    # every red light in the client's editor: an SEO plugin checks the title, the opening
    # paragraph and the subheadings for the exact phrase, and a writer that was never
    # asked puts it in none of them. MEASURED on a shipped page - the phrase appeared
    # once in 819 words and in no heading, so every check failed and the client opened a
    # page covered in red badges.
    #
    # Asked for naturally and three times, not stuffed: a page that repeats a phrase
    # mechanically reads worse to a human AND scores worse, because over-optimisation is
    # itself one of the things being measured.
    phrase = (ctx.primary_keyword or "").strip()
    if phrase:
        lines.append("")
        lines.append(
            f'SEARCH PHRASE: "{phrase}". It must appear, worded naturally and never '
            "stuffed, in ALL THREE of: the hero heading, the first sentence of the first "
            "text below the hero, and at least one other section heading. Use it a "
            "handful of times across the page, not once and not in every paragraph. "
            "Ordinary variations of it count and read better than repeating it exactly."
        )
    lines.append(f"BUSINESS: {ctx.client_name or 'the client'}")
    if ctx.geo:
        lines.append(f"LOCATION: {ctx.geo}")
    lines.append(f"PAGE TYPE: {ctx.page_type}")
    intent = str(brief.get("intent") or "").strip()
    if intent:
        lines.append(f"SEARCH INTENT: {intent}")
    audience = str(brief.get("audience") or "").strip()
    if audience:
        lines.append(f"AUDIENCE: {audience}")
    gaps = [str(g).strip() for g in (brief.get("gaps") or []) if str(g).strip()][:6]
    if gaps:
        lines.append("WHAT COMPETING PAGES MISS (cover these): " + "; ".join(gaps))
    if ctx.facts:
        lines.append("")
        lines.append(
            "VERIFIED FACTS - the ONLY specifics you may state. Any number, date, "
            "credential or named person not in this list must not appear on the page:"
        )
        for fact in ctx.facts[:24]:
            lines.append(f"  - {fact}")
    else:
        lines.append("")
        lines.append(
            "NO VERIFIED FACTS were supplied. State no numbers, no dates, no "
            "credentials, no client names and no review counts anywhere on this page."
        )

    lines.append("")
    lines.append("SLOTS:")
    shape: dict[str, Any] = {}
    for i, spec in enumerate(specs):
        schema = schema_for(spec.kind)
        if schema is None or schema.chrome:
            continue
        sid = _slot_id(i, spec.kind)
        lines.append("")
        lines.append(f"{sid} ({spec.kind}, rendered as a {spec.layout})")
        lines.append(f"  purpose: {schema.purpose}")
        if spec.heading:
            lines.append(f"  suggested heading: {spec.heading}")
        for f in schema.fields:
            bound = (
                f"max {f.max_chars} chars"
                if f.max_chars
                else f"{f.min_count}-{f.max_count} items of "
                f"({', '.join(f.item_fields)})"
            )
            opt = " (optional)" if f.optional else ""
            hint = f" - {f.hint}" if f.hint else ""
            lines.append(f"  - {f.name}: {bound}{opt}{hint}")
        # THE MATERIAL THIS SLOT IS BUILT FROM, attached to the slot itself rather than
        # left in a list at the top of the prompt. A price table, a set of quotes, a team
        # or a list of areas is not background for the page - it IS the section, and a
        # writer shown a section's name but not its contents can only generalise.
        material = evidence_for(ctx, schema.evidence) if schema.evidence else ()
        if material:
            lines.append(
                "  USE EXACTLY THIS MATERIAL - one entry per item, in this order. Do not "
                "invent alternatives, do not add entries of your own, and do not "
                "generalise a named person or a stated price into a category:"
            )
            for item in material[:12]:
                lines.append(f"    * {item}")
        shape[sid] = schema.example()

    lines.append("")
    # READABILITY IS SCORED, AND IT IS SCORED ON SENTENCE LENGTH.
    #
    # The plugin in the client's editor turns the readability light red when more than a
    # quarter of the sentences run over twenty words. MEASURED on two shipped pages: 30%
    # and 43%. The writing was good - long, careful, subordinate-clause sentences - and
    # the badge said the page was hard to read, which is the first thing the client sees
    # when they open it.
    #
    # Asked as a RHYTHM rather than a cap, because a page of uniformly short sentences
    # reads like an instruction manual and is its own defect. The bound is on the SHARE
    # that run long, which is exactly what is measured.
    lines.append("")
    lines.append(
        "READABILITY: keep most sentences under twenty words - fewer than one in four "
        "may run longer, which is where a readability score turns red. Vary the length; "
        "a page of uniformly short sentences reads like a manual. Split a sentence "
        "carrying two ideas rather than joining them with a comma or a semicolon."
    )
    lines.append("")
    lines.append("RETURN EXACTLY THIS SHAPE:")
    lines.append(json.dumps(shape, indent=2))
    lines.append("")
    lines.append(
        "RULES: every slot filled; no slot repeats another slot's point; write for this "
        "business and this page only; no filler phrases ('in today's fast-paced world', "
        "'we pride ourselves'); no em dashes."
    )
    return "\n".join(lines)


def compose_page(
    writer: DoctrineWriter,
    ctx: PipelineContext,
    specs: tuple[SectionSpec, ...] | list[SectionSpec],
) -> tuple[ComposeResult, float, int]:
    """Ask for the whole page as data, validate each slot, return what survived.

    Returns ``(result, cost, calls)``. Never raises for a bad payload - a page that comes
    back unparseable is an empty result with the reason recorded, which the stage turns
    into a degrade rather than a crash.
    """
    keep, dropped = plan_slots(specs, ctx)
    writable = [s for s in keep if (sc := schema_for(s.kind)) and not sc.chrome]
    out = ComposeResult(dropped=list(dropped))
    if not writable:
        return out, 0.0, 0

    prompt = build_prompt(writable, ctx)
    # `write` returns the TEXT and folds cost/tokens into the accounting object, so the
    # accounting is what the stage reports - not a number re-derived here.
    acc = WriteAccounting()
    text = writer.write(
        STAGE,
        prompt,
        page_type=ctx.page_type,
        vertical=ctx.vertical,
        framework=ctx.framework,
        max_tokens=MAX_TOKENS,
        expected_calls=1,
        accounting=acc,
    )
    payload = parse_json_object(text)
    cost, calls = acc.cost, max(acc.calls, 1)

    index_by_kind = {id(spec): i for i, spec in enumerate(writable)}
    for spec in keep:
        schema = schema_for(spec.kind)
        if schema is None:
            continue
        if schema.chrome:
            out.sections.append(
                ComposedSection(kind=spec.kind, layout=spec.layout, heading=spec.heading)
            )
            continue
        sid = _slot_id(index_by_kind[id(spec)], spec.kind)
        # A model that renames the key (`hero` instead of `s1_hero`) has still done the
        # work; accepting both costs nothing and saves a whole repair call.
        raw = payload.get(sid, payload.get(spec.kind))
        result: SlotResult = validate_slot(spec.kind, raw)
        if not result.ok:
            out.dropped.append((spec.kind, result.reason))
            continue
        heading = str(result.data.get("heading") or spec.heading or "")
        out.sections.append(
            ComposedSection(
                kind=spec.kind, layout=spec.layout, heading=heading, data=result.data
            )
        )
    return out, cost, calls


def run_compose(
    ctx: PipelineContext,
    writer: DoctrineWriter,
    specs: Any,
    *,
    allowed_contacts: frozenset[str] = frozenset(),
    vendor_terms: tuple[str, ...] = (),
) -> StageResult:
    """The pipeline stage: fill the wireframe, scrub it, publish both representations."""
    result, cost, calls = compose_page(writer, ctx, specs or ())
    removed = scrub_sections(
        result.sections,
        facts=ctx.facts,
        allowed_contacts=allowed_contacts,
        vendor_terms=vendor_terms,
    )
    # Scrubbing can empty a slot completely (every sentence in it was an uncited claim).
    # An empty slot is dropped here rather than rendered as a headed blank.
    def _still_renders(section: ComposedSection) -> bool:
        if section.data:
            return True
        schema = schema_for(section.kind)
        # Chrome legitimately carries no copy - it is drawn from live client data - so an
        # empty payload there is not an empty section.
        return schema is not None and schema.chrome

    result.sections = [s for s in result.sections if _still_renders(s)]
    # THE TWO REPRESENTATIONS, written together so they can never describe different pages:
    # the structured slots are what renders, the markdown mirror is what the review screen,
    # the QA scorecard, the word count and the image planner read.
    ctx.sections = [s.as_dict() for s in result.sections]
    ctx.draft_md = sections_to_markdown(result.sections)
    filled = [s for s in result.sections if s.data]
    data: dict[str, Any] = {
        "claims_removed": removed,
        "sections": [s.as_dict() for s in result.sections],
        "kinds": result.kinds,
        "dropped": [{"kind": k, "why": why} for k, why in result.dropped],
        "filled": len(filled),
    }
    if len(filled) < MIN_SECTIONS:
        return ctx.record(
            StageResult(
                STAGE,
                outcome="degraded",
                data=data,
                cost=cost,
                llm_calls=calls,
                notes=(
                    f"only {len(filled)} section(s) could be filled; "
                    f"dropped: {', '.join(k for k, _ in result.dropped) or 'none'}",
                ),
            )
        )
    return ctx.record(
        StageResult(STAGE, outcome="ok", data=data, cost=cost, llm_calls=calls)
    )

# --------------------------------------------------------------------------- #
# The text-level guards, applied to STRUCTURED fields.
# --------------------------------------------------------------------------- #
#: Which fields of which slot carry sentences a reader will take as claims. Headings and
#: labels are excluded deliberately: a heading is not a claim, and auditing one produces a
#: section whose title has been deleted.
_SCRUBBED_FIELDS: dict[str, tuple[str, ...]] = {
    "hero": ("subheading",),
    "intro": ("paragraphs",),
    "about": ("paragraphs",),
    "conclusion": ("paragraphs",),
    "features": ("items", "intro"),
    "benefits": ("items", "intro"),
    "services": ("items", "intro"),
    "process": ("steps", "intro"),
    "faq": ("items",),
    "body": ("markdown",),
    "cta": ("text",),
}

#: Within a repeated item, the field that carries prose (the other is a label).
_ITEM_PROSE: dict[str, str] = {
    "items": "text", "steps": "text", "paragraphs": "text", "faq": "answer",
}


def _cut_unsourced_figures(text: str, facts: tuple[str, ...]) -> tuple[str, int]:
    """Drop any SENTENCE asserting a figure no supplied fact accounts for.

    THE GUARD THE TEMPLATED ORDER WOULD OTHERWISE HAVE LOST. In the prose sequence this is
    the `grounding` stage: it measures unsourced figures and asks the writer to re-source or
    cut them. A composed page has no document to rewrite, and re-running a repair prompt per
    field would cost a call per card - so the same measurement is applied deterministically
    and for free, by deleting the sentence.

    It runs WITH OR WITHOUT supplied facts, which is where it deliberately differs from the
    prose stage. That stage skips when nothing was supplied, because with no facts every
    figure is unsourced and a rewrite would gut the page. Here the compose prompt has
    already told the writer to state no numbers at all in that case, so a number that
    appears anyway is a violation of an explicit instruction - and cutting one sentence out
    of a card leaves a card, not a hole.
    """
    if not text.strip():
        return text, 0
    findings = unsourced_figures(text, facts)
    if not findings:
        return text, 0
    bad = {f.message.split("'")[1] for f in findings if "'" in f.message}
    if not bad:
        return text, 0
    kept: list[str] = []
    removed = 0
    for unit in split_units(text):
        if unit.lstrip().startswith("#"):
            kept.append(unit)
            continue
        if any(token in unit for token in bad):
            removed += 1
            continue
        kept.append(unit)
    return (" ".join(k.strip() for k in kept).strip(), removed)


def scrub_sections(
    sections: list[ComposedSection],
    *,
    facts: tuple[str, ...],
    allowed_contacts: frozenset[str] = frozenset(),
    vendor_terms: tuple[str, ...] = (),
) -> int:
    """Delete any sentence that states a specific nothing supplied supports. In place.

    THE SAME GUARANTEE THE PROSE PATH HAD, kept through the change of shape. `claims`
    audits a draft and deletes the sentences that assert a figure, a date, a credential or
    a contact with no citation behind them; that guard operated on markdown, and a page
    that is now structured data would have walked straight past it. So it is applied
    FIELD BY FIELD instead - the same pure audit, run on each prose field of each slot.

    An item whose prose is deleted entirely is dropped from its list, because a card with a
    title and no body is a rendering hole. Returns how many sentences were removed.
    """
    pattern = vendor_pattern(vendor_terms)
    # The atoms ARE the citable facts: a sentence is kept when it cites one of them. The
    # prose path builds them from the same answered Experience slots, so a page composed
    # from slots is held to exactly the same bar as a page written as prose.
    atoms = build_atoms(facts)
    removed = 0
    for section in sections:
        for field_name in _SCRUBBED_FIELDS.get(section.kind, ()):
            value = section.data.get(field_name)
            if isinstance(value, str):
                audit = audit_draft(
                    value, atoms, allowed_contacts=allowed_contacts, vendor=pattern,
                )
                cleaned, n = apply_deletions(value, audit)
                cleaned, m = _cut_unsourced_figures(cleaned, facts)
                removed += n + m
                section.data[field_name] = cleaned.strip()
            elif isinstance(value, list):
                prose_key = _ITEM_PROSE.get(field_name, "text")
                kept: list[Any] = []
                for entry in value:
                    if not isinstance(entry, dict):
                        kept.append(entry)
                        continue
                    text = str(entry.get(prose_key) or "")
                    if not text:
                        kept.append(entry)
                        continue
                    audit = audit_draft(
                        text, atoms, allowed_contacts=allowed_contacts, vendor=pattern,
                    )
                    cleaned, n = apply_deletions(text, audit)
                    cleaned, m = _cut_unsourced_figures(cleaned, facts)
                    removed += n + m
                    cleaned = cleaned.strip()
                    if cleaned:
                        entry[prose_key] = cleaned
                        kept.append(entry)
                section.data[field_name] = kept
    return removed


def sections_to_markdown(sections: list[ComposedSection]) -> str:
    """A readable markdown mirror of the filled page.

    NOT the page. The page is the structured data; this is what the review screen shows,
    what the QA scorecard reads and what the word count is measured from - all of which
    need running text. Generated from the slots so it can never describe a page other than
    the one that will publish.
    """
    out: list[str] = []
    for section in sections:
        data = section.data
        if section.kind == "hero":
            if section.heading:
                out.append(f"# {section.heading}")
            if data.get("subheading"):
                out.append(str(data["subheading"]))
            for bullet in data.get("bullets") or []:
                text = bullet.get("text") if isinstance(bullet, dict) else bullet
                if text:
                    out.append(f"- {text}")
            continue
        if section.heading:
            out.append(f"## {section.heading}")
        if data.get("intro"):
            out.append(str(data["intro"]))
        for para in data.get("paragraphs") or []:
            text = para.get("text") if isinstance(para, dict) else para
            if text:
                out.append(str(text))
        if data.get("markdown"):
            out.append(str(data["markdown"]))
        for item in data.get("items") or []:
            if not isinstance(item, dict):
                continue
            if "question" in item:
                out.append(f"### {item.get('question', '')}")
                out.append(str(item.get("answer", "")))
            else:
                out.append(f"**{item.get('title', '')}** - {item.get('text', '')}")
        for step in data.get("steps") or []:
            if isinstance(step, dict):
                out.append(f"**{step.get('title', '')}** - {step.get('text', '')}")
            else:
                out.append(str(step))
        for quote in data.get("quotes") or []:
            if isinstance(quote, dict):
                who = ", ".join(
                    x for x in (quote.get("author", ""), quote.get("role", "")) if x
                )
                out.append(f"> {quote.get('quote', '')}" + (f" - {who}" if who else ""))
        for tier in data.get("tiers") or []:
            if isinstance(tier, dict):
                out.append(
                    f"**{tier.get('name', '')}** {tier.get('price', '')} - "
                    f"{tier.get('summary', '')}"
                )
        for stat in data.get("stats") or []:
            if isinstance(stat, dict):
                out.append(f"**{stat.get('value', '')}** {stat.get('label', '')}")
        for person in data.get("people") or []:
            if isinstance(person, dict):
                out.append(
                    f"**{person.get('name', '')}**, {person.get('role', '')} - "
                    f"{person.get('bio', '')}"
                )
        for point in data.get("points") or []:
            if isinstance(point, dict):
                out.append(f"- {point.get('claim', '')} ({point.get('source', '')})")
        areas = [
            a.get("name") if isinstance(a, dict) else a for a in (data.get("areas") or [])
        ]
        if areas:
            out.append(", ".join(str(a) for a in areas if a))
        if data.get("text"):
            out.append(str(data["text"]))
    return "\n\n".join(x for x in out if str(x).strip())

