"""Draft - writing the page, in batches, from grounded facts only.

WHAT THIS REPLACES. `content_generator.generate()` is a deterministic template
assembler: a fixed heading table, then one ~133-word writer call per section, each
blind to the others. Two consequences follow from that shape and neither is fixable by
prompt tuning.

  1. THE PAGE HAS NO FLOW. A section written with no knowledge of the one before it
     cannot refer back, cannot vary its opening, and cannot avoid restating what was
     just said. It reads as a stack of paragraphs because that is exactly what it is.
  2. IT IS EXPENSIVE IN THE WRONG WAY. 15-21 calls per page, each re-sending the
     framing, to produce prose that then has to be stitched.

Here adjacent sections are written TOGETHER - the model sees the run it is writing and
the tail of what came before - so continuity is a property of the call rather than
something a later pass tries to repair.

GROUNDING IS ABSOLUTE. Only `ctx.facts` (from answered SME slots) may appear as fact.
The prompt says so, the doctrine's constitution says so, and the Experience gate
checks it afterwards. There is no path here that invents a figure, and the SME halt
upstream means a page with no facts never reaches this stage at all.

TOKEN HEADROOM. `max_tokens` is the word budget times `_MAX_TOKENS_PER_WORD` (3.0),
measured rather than guessed: local service copy runs 1.8-2.0 tokens per WORD because
licence codes, prices and counts tokenise heavily, and at the old 2.0 multiplier three
live calls out of three came back cut mid-sentence.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.content_generator import _MAX_TOKENS_PER_WORD, _bound_words
from app.services.content_pipeline.claims import build_atoms, render_atoms
from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_pipeline.writer import DoctrineWriter, WriteAccounting

STAGE = "draft"

# Sections per call. Enough for the model to carry a thread across a run; small enough
# that one weak batch does not spoil the page and can be re-requested alone.
BATCH_SIZE = 3

# How much of the previous batch the next one sees. The last paragraph is what a
# transition has to connect to; sending more would re-pay for context the cache
# already holds and crowd the instruction.
TAIL_CHARS = 400

# Headroom for extended THINKING, on top of the prose budget.
#
# The prose multiplier alone is not enough. This model reasons before it writes, and a
# 450-word batch at 3.0 tokens/word gives 1,350 - which it can spend entirely on
# thinking, returning no text at all. Measured on the outline stage: ~9,965 tokens of
# reasoning before the first output token.
#
# Budgeting them separately keeps the prose multiplier meaning what it says (tokens per
# WORD of output) instead of quietly absorbing a reasoning allowance.
THINKING_ALLOWANCE = 8_000

_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)


def _sections(outline: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in (outline.get("sections") or []) if isinstance(s, dict) and s.get("h2")]


def _batch_prompt(
    ctx: PipelineContext, batch: list[dict[str, Any]], tail: str, index: int, total: int
) -> str:
    lines = [
        f"Write sections {index + 1}-{index + len(batch)} of {total} for a "
        f"{ctx.page_type} page targeting '{ctx.primary_keyword}'"
        + (f" in {ctx.geo}" if ctx.geo else "") + ".",
        f"Client: {ctx.client_name or 'the client'}.",
    ]
    if ctx.facts:
        # NUMBERED, and citable. The old form was an unnumbered bullet list under the
        # instruction "the ONLY facts you may state" - a rule with no way to check
        # whether it was followed, and measured on six real pages, it was not: the
        # writer invented 44 claims the operator had explicitly said were false.
        # An id per fact makes compliance mechanical instead of hopeful.
        atoms = build_atoms(ctx.facts)
        lines += [
            "",
            "THE ONLY FACTS YOU MAY STATE. Each carries an id:",
            render_atoms(atoms),
            "",
            "CITE THEM. Any sentence that states a number, a credential, a customer or "
            "deployment, a named third-party system, a guarantee, or an absolute "
            "('never', 'zero', 'no data leaves') must end with the id of the fact it "
            "rests on, like [[a2]]. To cite two, write them together as [[a2]][[a5]] "
            "- exactly that shape, one bracket pair per id.",
            "If no fact supports the sentence you were about to write, DO NOT WRITE IT. "
            "Do not soften it, do not hedge it, do not write it without the id - a "
            "sentence with no id is deleted before the page is reviewed, so an "
            "uncited claim costs you the paragraph it was in.",
            "Saying less is correct here. A short page that is entirely true is the "
            "goal; a long one carrying an invented certification is a liability for "
            "the client whose name is on it.",
            "Never cite an id for a fact it does not contain, and never invent an id.",
        ]
    else:
        lines.append("State no figures, prices, dates, names or credentials at all.")

    if tail:
        lines += [
            "",
            "The previous section ended like this. Continue from it naturally; do not "
            "restate it and do not open with a summary of it:",
            f"  ...{tail}",
        ]

    lines += ["", "Sections to write:"]
    for section in batch:
        target = int(section.get("target_words") or 150)
        lines.append(f"\n## {section['h2']}   (~{target} words)")
        for sub in section.get("h3s") or []:
            lines.append(f"### {sub}")
        if section.get("intent_role"):
            lines.append(f"  role: {section['intent_role']}")
        if section.get("must_cover"):
            lines.append(f"  must cover: {', '.join(str(m) for m in section['must_cover'])}")
        block = section.get("passage_block")
        if isinstance(block, dict) and block.get("question"):
            lines.append(
                f"  open with a direct 40-55 word answer to: {block['question']}"
            )

    # These constraints are MEASURED, not stylistic preference. The first live draft
    # came back at reading grade 12.6 against a 6-9 target with 36% of sentences over
    # 25 words, and repeated the city to 3.4% density against a 2.5% stuffing ceiling.
    # The doctrine covers all of this, but a general instruction in a 74k-token system
    # block does not bind as tightly as a specific one in the user turn.
    lines += [
        "",
        "How the prose must read:",
        "  - Reading grade 6-9 - a BAND, not a floor to dive under. Aim for about 15 "
        "words per sentence on average. Keep most under 25, and let a few run to 20-25 "
        "where the thought needs the room; a page of nothing but short declaratives "
        "reads as a checklist and lands BELOW grade 6. Both misses are measured: a run "
        "of long sentences put the first draft at grade 12.6, and correcting it "
        "without a floor put the next one at 5.0.",
        f"  - Name '{ctx.geo or 'the city'}' AT MOST ONCE per section, and not at all "
        f"in a heading unless the heading is meaningless without it. Measured: the "
        f"first two drafts of this page put it in most headings and hit 3.4% density "
        f"against a 2.5% stuffing ceiling. Write 'the area', 'locally', or nothing.",
        "  - Do NOT open consecutive sections the same way. If one starts 'Yes,' the "
        "next must not.",
        "  - Do not put a figure or a licence number in every heading. A heading names "
        "the topic; the prose carries the proof.",
        "  - Where a claim is contestable, attribute it in the prose to the source it "
        "came from rather than asserting it flatly.",
        "",
        "Output markdown with the ## and ### headings exactly as given above, and the "
        "prose beneath each. No preamble, no closing summary, no invented headings.",
    ]
    return "\n".join(lines)


def _target_words(batch: list[dict[str, Any]]) -> int:
    return sum(int(s.get("target_words") or 150) for s in batch)


def run_draft(
    ctx: PipelineContext,
    *,
    writer: DoctrineWriter,
    model: str | None = None,
    batch_size: int = BATCH_SIZE,
) -> StageResult:
    """Write the page from the outline, in batches, and set ``ctx.draft_md``."""
    sections = _sections(ctx.outline)
    if not sections:
        return ctx.record(StageResult(
            STAGE, outcome="skipped", notes=("no outline sections to write",)))

    accounting = WriteAccounting()
    notes: list[str] = []
    batches = [sections[i : i + batch_size] for i in range(0, len(sections), batch_size)]
    parts: list[str] = []
    tail = ""

    for index, batch in enumerate(batches):
        budget = _target_words(batch)
        try:
            text = writer.write(
                STAGE,
                _batch_prompt(ctx, batch, tail, index * batch_size, len(sections)),
                page_type=ctx.page_type, vertical=ctx.vertical or None,
                framework=ctx.framework,
                max_tokens=THINKING_ALLOWANCE + max(1, round(budget * _MAX_TOKENS_PER_WORD)),
                expected_calls=len(batches), model=model, accounting=accounting,
            )
        except Exception as exc:
            # Hold what is written rather than losing it. A page that stops early is
            # reviewable and resumable; a page that vanishes on the last batch has
            # spent real money for nothing.
            notes.append(
                f"drafting stopped at section {index * batch_size + 1} "
                f"({type(exc).__name__}); {len(parts)} of {len(batches)} batches written"
            )
            break

        cleaned = text.strip()
        if not cleaned:
            notes.append(f"batch {index + 1} came back empty")
            continue
        if not _HEADING_RE.search(cleaned):
            # The model dropped the headings. Reinstating the first one keeps the
            # markdown parseable downstream rather than yielding a wall of prose the
            # schema and outline stages cannot read.
            cleaned = f"## {batch[0]['h2']}\n\n{cleaned}"
            notes.append(f"batch {index + 1} omitted its headings; the first was restored")

        # A whole-batch bound, not a per-section one: the model apportions between
        # sections better than a fixed split does, and `_bound_words` now cuts at a
        # sentence boundary rather than mid-thought.
        parts.append(_bound_words(cleaned, int(budget * 1.25)))
        tail = parts[-1][-TAIL_CHARS:]

    if not parts:
        return ctx.record(StageResult(
            STAGE, outcome="degraded", notes=(*notes, "nothing was written"),
            cost=accounting.cost, llm_calls=accounting.calls,
        ))

    ctx.draft_md = "\n\n".join(parts)
    partial = len(parts) < len(batches)
    return ctx.record(StageResult(
        STAGE, outcome="degraded" if partial else "ok", notes=tuple(notes),
        data={"sections": len(sections), "batches": len(parts),
              "words": len(ctx.draft_md.split())},
        cost=accounting.cost, llm_calls=accounting.calls,
        input_tokens=accounting.input_tokens, output_tokens=accounting.output_tokens,
        cache_write_tokens=accounting.cache_write_tokens,
        cache_read_tokens=accounting.cache_read_tokens,
        chunk_ids=tuple(accounting.chunk_ids),
    ))
