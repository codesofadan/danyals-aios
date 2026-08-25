"""TITLE and META - written, not concatenated (P3, stage 9).

v1 built these with string arithmetic (`content_generator.py:976-987`): keyword, a
separator, the city, a separator, the client name, truncated to fit. Every page in an
engagement therefore had the same title SHAPE, differing only in the tokens - the same
scaled-content fingerprint the outline gate exists to stop, in the one field Google
shows the user before they click.

Cheap model, deliberately: this is a short constrained rewrite of facts already
established, not a reasoning task. It is the clearest case in the pipeline for Haiku.

The length bands are enforced HERE rather than left to the compliance linter to
complain about later, because a title that is eight characters too long is a defect
the model can simply fix if it is told the number - and cannot fix if nobody tells it.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.content_lint.compliance import (
    META_DESC_MAX,
    META_DESC_MIN,
    META_TITLE_MAX,
    META_TITLE_MIN,
)
from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_pipeline.writer import DoctrineWriter, WriteAccounting

STAGE = "title_meta"

# Short output, but the model still reasons first - see draft.THINKING_ALLOWANCE.
MAX_TOKENS = 4_000

# One retry. The failure mode here is a length miss, which is mechanical and worth
# re-asking once with the measured overshoot named; a second retry does not add much.
MAX_REPAIRS = 1


def _prompt(ctx: PipelineContext, problems: list[str]) -> str:
    lines = [
        f"Write the meta title and meta description for a {ctx.page_type} page "
        f"targeting '{ctx.primary_keyword}'"
        + (f" in {ctx.geo}" if ctx.geo else "")
        + ".",
        f"Business: {ctx.client_name}." if ctx.client_name else "",
        "",
        "Constraints:",
        f"  - Title: {META_TITLE_MIN}-{META_TITLE_MAX} characters INCLUDING spaces.",
        f"  - Description: {META_DESC_MIN}-{META_DESC_MAX} characters including spaces.",
        "  - The title must read like a person wrote it for this one business. Do not "
        "use a 'Keyword | City | Brand' template - that shape repeated across pages is "
        "what marks a site as machine-generated.",
        "  - The description must say something the title does not, and give a reason "
        "to click. It is not a summary of the title.",
        "  - State no fact that is not in the page. No prices, guarantees, ratings or "
        "superlatives unless the draft already carries them.",
    ]
    if ctx.draft_md.strip():
        opening = "\n".join(ctx.draft_md.strip().splitlines()[:12])
        lines += ["", "How the page opens, for tone and substance:", opening]
    if problems:
        lines += ["", "Your previous attempt was rejected:", *(f"  - {p}" for p in problems),
                  "Return corrected values. Count the characters this time."]
    lines += ["", 'Return ONLY JSON: {"title": "...", "description": "..."}']
    return "\n".join(x for x in lines if x != "")


def _parse(raw: str) -> tuple[str, str] | None:
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return None
    try:
        obj: Any = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    title, desc = obj.get("title"), obj.get("description")
    if not isinstance(title, str) or not isinstance(desc, str):
        return None
    return title.strip(), desc.strip()


def _length_problems(title: str, desc: str) -> list[str]:
    out: list[str] = []
    if not META_TITLE_MIN <= len(title) <= META_TITLE_MAX:
        out.append(
            f"title was {len(title)} characters, needs {META_TITLE_MIN}-{META_TITLE_MAX}"
        )
    if not META_DESC_MIN <= len(desc) <= META_DESC_MAX:
        out.append(
            f"description was {len(desc)} characters, needs {META_DESC_MIN}-{META_DESC_MAX}"
        )
    return out


def run_title_meta(
    ctx: PipelineContext, *, writer: DoctrineWriter, model: str | None = None
) -> StageResult:
    """Write a title and description that fit, and that do not share a template."""
    accounting = WriteAccounting()
    problems: list[str] = []
    title = desc = ""
    notes: list[str] = []

    for attempt in range(MAX_REPAIRS + 1):
        try:
            raw = writer.write(
                STAGE, _prompt(ctx, problems),
                page_type=ctx.page_type, vertical=ctx.vertical or None,
                framework=ctx.framework, max_tokens=MAX_TOKENS,
                expected_calls=MAX_REPAIRS + 1, model=model, accounting=accounting,
            )
        except Exception as exc:
            return ctx.record(StageResult(
                STAGE, outcome="degraded",
                notes=(f"title/meta unavailable ({type(exc).__name__})",),
                cost=accounting.cost, llm_calls=accounting.calls,
            ))

        parsed = _parse(raw)
        if parsed is None:
            problems = ["the reply was not the requested JSON object"]
            notes.append(f"attempt {attempt + 1}: reply was not JSON")
            continue

        title, desc = parsed
        problems = _length_problems(title, desc)
        if not problems:
            break
        notes.append(f"attempt {attempt + 1}: " + "; ".join(problems))

    if not title or not desc:
        return ctx.record(StageResult(
            STAGE, outcome="degraded", notes=(*notes, "no usable title/meta"),
            cost=accounting.cost, llm_calls=accounting.calls,
            input_tokens=accounting.input_tokens, output_tokens=accounting.output_tokens,
            cache_write_tokens=accounting.cache_write_tokens,
            cache_read_tokens=accounting.cache_read_tokens,
            chunk_ids=tuple(accounting.chunk_ids),
        ))

    # Kept even when out of band. A title eight characters long in the wrong direction
    # is a WARN in the compliance linter, not a blocker, and discarding a usable title
    # to hold a soft bound would leave the page with nothing at all.
    ctx.title, ctx.meta_description = title, desc
    if problems:
        notes.append("kept out-of-band values; the compliance linter will flag them")
    return ctx.record(StageResult(
        STAGE, outcome="degraded" if problems else "ok", notes=tuple(notes),
        data={"title_len": len(title), "desc_len": len(desc), "in_band": not problems},
        cost=accounting.cost, llm_calls=accounting.calls,
        input_tokens=accounting.input_tokens, output_tokens=accounting.output_tokens,
        cache_write_tokens=accounting.cache_write_tokens,
        cache_read_tokens=accounting.cache_read_tokens,
        chunk_ids=tuple(accounting.chunk_ids),
    ))
