"""Outline - and the uniqueness gate that kills the template.

THE FAILURE THIS EXISTS TO STOP IS ONE WE MANUFACTURE. `content_generator`'s
`_FRAMEWORK_MOVES` is a fixed heading table, so two competing plumbers in two cities
receive heading skeletons identical but for the city token. That is the textbook
scaled-content-abuse fingerprint, produced by us, on a client's live site.

`content_qa`'s originality dimension cannot see it: it compares a page only against
ITSELF. Only a cross-page comparison can, which is what this stage does.

THE MEASUREMENT THAT SHAPES THE WHOLE GATE. Shingling the headings RAW does not work.
Measured on real generator output, Austin vs Round Rock scored:

    w=3   raw 58.2%   entity-masked 100.0%
    w=5   raw 27.6%   entity-masked 100.0%

Both raw scores sit UNDER the 70% duplicate ceiling, so a raw gate would have passed
every templated page - and it gets WORSE as the window grows, which is the opposite of
the intuition. The cause is that the varying city token sits inside most shingles and
hides the very duplication being looked for.

So the entity is MASKED before shingling. Without that this gate ships, passes its own
tests, and silently approves exactly what it was built to stop.

A rejection NAMES the colliding headings, so the retry is informed rather than a
re-roll: "these five headings already exist on another page - use different ones".
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from app.services.content_lint import DUPLICATE_THRESHOLD, shingle_hashes
from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_pipeline.writer import DoctrineWriter, WriteAccounting

STAGE = "outline"

# Retries after a uniqueness rejection. Two, then accept-with-a-flag: a third attempt
# tends to produce contortions rather than a genuinely different structure, and an
# operator reviewing a flagged page beats an infinite re-roll at cost.
MAX_REPAIRS = 2

# Heading shingles are SHORT texts, so a 3-word window is right where a 5-word one
# would leave most headings unrepresented. This is not the body-text default.
HEADING_SHINGLE_SIZE = 3

# Token budget for a REASONING stage.
#
# MEASURED live 2026-08-25, not guessed. This model emits extended-THINKING blocks. On
# this stage's prompt it spent 4,000 tokens reasoning and produced ZERO text - the call
# returned an empty string that looked like "the model had nothing to say", and the
# stage degraded for a reason nobody could see. At 12,000 it finished thinking in
# ~9,965 tokens and wrote a full answer.
#
# So the budget has to cover THINKING PLUS THE ANSWER, not just the answer. That is
# also why `integrations.llm.EmptyCompletionError` exists: if this is ever set too low
# again, the failure is loud instead of a blank page.
REASONING_MAX_TOKENS = 12_000

_PLACEHOLDER = "<TARGET>"
_CITY_PLACEHOLDER = "<CITY>"


class ShingleStore(Protocol):
    def find_overlaps(self, **kwargs: Any) -> list[Any]: ...
    def record_shingles(self, **kwargs: Any) -> int: ...


def mask_entity(text: str, primary_keyword: str, geo: str = "") -> str:
    """Replace the target query and its place name with placeholders.

    The load-bearing step. Two pages built from one template differ ONLY in these
    tokens, so leaving them in is what let 58% look like "distinct enough".

    Longest-first so a city that is part of the query ("ac repair austin" then
    "austin") does not leave an orphaned fragment behind.
    """
    masked = text
    needles = sorted(
        {n.strip() for n in (primary_keyword, geo) if n and n.strip()},
        key=len, reverse=True,
    )
    for needle in needles:
        masked = re.sub(re.escape(needle), _PLACEHOLDER, masked, flags=re.IGNORECASE)
    # The place name often appears alone in headings even when the full query does not
    # ("Serving Austin since 2011"), so mask its tokens too.
    for token in {t for t in geo.split() if len(t) > 2}:
        masked = re.sub(rf"(?<!\w){re.escape(token)}(?!\w)", _CITY_PLACEHOLDER,
                        masked, flags=re.IGNORECASE)
    return masked


def heading_text(outline: dict[str, Any]) -> str:
    """The heading skeleton alone - the part a template fixes.

    Body prose differs between two templated pages because the facts differ; the
    HEADINGS are what stay identical, so they are what the gate compares.
    """
    lines: list[str] = []
    for section in outline.get("sections") or []:
        if not isinstance(section, dict):
            continue
        if section.get("h2"):
            lines.append(str(section["h2"]))
        lines.extend(str(h) for h in (section.get("h3s") or []) if h)
    return "\n".join(lines)


def _prompt(ctx: PipelineContext, forbidden: list[str]) -> str:
    lines = [
        f"Plan the outline for a {ctx.page_type} page targeting "
        f"'{ctx.primary_keyword}'" + (f" in {ctx.geo}" if ctx.geo else "") + ".",
        f"Client: {ctx.client_name or 'the client'}. Target length: about "
        f"{ctx.target_words} words.",
    ]
    if ctx.facts:
        lines += ["", "First-party facts you may use (and NOTHING else as fact):",
                  *(f"  - {f}" for f in ctx.facts)]
    # THE BLUEPRINT, when one resolved. Without this the writer plans an article and
    # the publish path then wraps that article in landing-page section divs - which is
    # how a "homepage" template produced long editorial H2s and read as a blog post in
    # a landing page's CSS. Asking for ONE section per slot, in order, is what makes
    # the copy the shape the layout is built for.
    if ctx.blueprint_sections:
        subs = {"{client}": ctx.client_name or "the business",
                "{primary}": ctx.primary_keyword or "the service"}
        slots = []
        for i, (kind, heading) in enumerate(ctx.blueprint_sections, 1):
            hint = heading
            for k, v in subs.items():
                hint = hint.replace(k, v)
            slots.append(f"  {i}. {kind}" + (f"  - suggested: {hint}" if hint else ""))
        lines += [
            "",
            "THIS IS A LANDING PAGE, NOT AN ARTICLE. It is built to a fixed layout, and",
            f"you must return EXACTLY {len(ctx.blueprint_sections)} sections, one per slot,",
            "IN THIS ORDER:",
            *slots,
            "",
            "Heading rules for this layout - they override the usual article guidance:",
            "  - SHORT. Two to six words. A landing-page section heading is a signpost,",
            "    not a sentence, and it sits in large type above a block of copy.",
            "  - No colons, no clauses, no rhetorical questions, no 'why X matters'.",
            "  - Say what the block IS ('What you get', 'How it works', 'Pricing'),",
            "    or the benefit it delivers. The suggested heading above is a fallback;",
            "    a better, more specific one for this business always wins.",
            "  - The hero heading is the page's single biggest promise, in plain words.",
            "",
            "Keep each section tight - a landing page is scanned, not read.",
        ]
    lines += [
        "",
        "For each section give:",
        "  h2                - the heading",
        "  h3s               - sub-headings, or []",
        "  intent_role       - what this section does for the reader",
        "  target_words      - roughly how long",
        "  must_cover        - entities or points it must address",
        "  passage_block     - {question, answer_40_55w} if it should be directly "
        "extractable, else null",
        "",
        "Write headings that could ONLY belong to this business and this place. A "
        "heading that would fit any competitor in any city is the scaled-content "
        "pattern search engines demote."
        + (
            " Within the short-heading rule above: specific beats generic, but never"
            " at the cost of length."
            if ctx.blueprint_sections
            else ""
        ),
    ]
    if forbidden:
        lines += [
            "",
            "REJECTED: the previous outline reused a heading structure that already "
            "exists on another page. Do not use these shapes again:",
            *(f"  - {h}" for h in forbidden[:8]),
            "Produce a genuinely different structure, not a reworded one.",
        ]
    lines += ["", 'Reply with ONLY a JSON object: {"sections": [...]}']
    return "\n".join(lines)


def _parse(raw: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except (ValueError, TypeError):
        return {}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("sections"), list):
        return {}
    return parsed


def run_outline(
    ctx: PipelineContext,
    *,
    writer: DoctrineWriter,
    store: ShingleStore | None = None,
    threshold: float = DUPLICATE_THRESHOLD,
    model: str | None = None,
) -> StageResult:
    """Produce an outline that is structurally distinct from its siblings."""
    accounting = WriteAccounting()
    notes: list[str] = []
    forbidden: list[str] = []
    outline: dict[str, Any] = {}
    hashes: frozenset[int] = frozenset()
    worst = 0.0

    for attempt in range(MAX_REPAIRS + 1):
        try:
            raw = writer.write(
                STAGE, _prompt(ctx, forbidden),
                page_type=ctx.page_type, vertical=ctx.vertical or None,
                framework=ctx.framework, max_tokens=REASONING_MAX_TOKENS,
                expected_calls=MAX_REPAIRS + 1, model=model, accounting=accounting,
            )
        except Exception as exc:
            return ctx.record(StageResult(
                STAGE, outcome="degraded",
                notes=(f"outline generation unavailable ({type(exc).__name__})",),
                cost=accounting.cost, llm_calls=accounting.calls,
            ))

        parsed = _parse(raw)
        if not parsed:
            forbidden = []
            notes.append(f"attempt {attempt + 1}: reply was not a JSON outline")
            continue
        outline = parsed

        headings = heading_text(outline)
        if not headings or store is None:
            break

        hashes = shingle_hashes(
            mask_entity(headings, ctx.primary_keyword, ctx.geo), size=HEADING_SHINGLE_SIZE
        )
        overlaps = store.find_overlaps(
            hashes=hashes, vertical=ctx.vertical, client_id=ctx.client_id,
            exclude_job_id=ctx.job_id,
        )
        worst = max((o.jaccard for o in overlaps), default=0.0)
        if worst < threshold:
            break

        forbidden = [h for h in headings.splitlines() if h.strip()]
        notes.append(
            f"attempt {attempt + 1} rejected: {worst:.0%} heading overlap with an "
            "existing page (scaled-content risk)"
        )

    if not outline:
        return ctx.record(StageResult(
            STAGE, outcome="degraded", notes=(*notes, "no usable outline after retries"),
            cost=accounting.cost, llm_calls=accounting.calls,
        ))

    duplicate = worst >= threshold
    if store is not None and hashes and not duplicate:
        # Recorded only on ACCEPT. Storing a rejected outline's shingles would make
        # the next page collide with a page that was never published.
        store.record_shingles(
            hashes=hashes, job_id=ctx.job_id, node_id=ctx.node_id,
            client_id=ctx.client_id, vertical=ctx.vertical,
        )
    if duplicate:
        notes.append(
            f"accepted at {worst:.0%} overlap after {MAX_REPAIRS} repairs; an operator "
            "should confirm this page is genuinely distinct before publishing"
        )

    ctx.outline = outline
    return ctx.record(StageResult(
        STAGE, outcome="degraded" if duplicate else "ok", notes=tuple(notes),
        data={"sections": len(outline.get("sections") or []),
              "max_overlap": round(worst, 4), "shingles": len(hashes)},
        cost=accounting.cost, llm_calls=accounting.calls,
        input_tokens=accounting.input_tokens, output_tokens=accounting.output_tokens,
        cache_write_tokens=accounting.cache_write_tokens,
        cache_read_tokens=accounting.cache_read_tokens,
        chunk_ids=tuple(accounting.chunk_ids),
    ))
