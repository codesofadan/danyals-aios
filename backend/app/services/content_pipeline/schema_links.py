"""SCHEMA and INTERNAL LINKS - deterministic, and free (P3, stage 10).

NO MODEL CALL. Everything here is derived from the finished page, and asking a model to
emit JSON-LD would be strictly worse: it would cost money to produce a structure a
builder already produces correctly, and it would be free to invent a rating, a price or
an opening hour that appears nowhere on the page. `validate_json_ld` exists precisely
because marking up a claim the reader cannot see is a manual-action risk, not a style
problem. Deriving the markup FROM the visible text makes that failure impossible rather
than merely detectable.

TWO THINGS V1 BUILT AND NEVER CONNECTED:

  - `_derive_faq` (workers/tasks/content.py:1896) parses an FAQ section into Q&A pairs
    and was wired ONLY to the WordPress payload. `build_json_ld` accepts `faqs=` and
    appends an FAQPage node, so every page with a visible FAQ section was eligible for
    an FAQ rich result and shipped without one.
  - `content_qa`'s internal_linking dimension was scored by a stub. `content_lint.links`
    is the ported `link_graph.py` and measures the real thing: orphans, over-linking,
    and hub reachability within a silo.

The FAQ parser is re-implemented here rather than imported because the original lives
in the WORKER layer; a service importing from a Celery task drags the whole task module
- and its Celery import - into anything that touches schema.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.content_lint import strip_markdown
from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_schema import (
    Business,
    FaqItem,
    Page,
    build_json_ld,
    validate_json_ld,
)

STAGE = "schema_links"

# An H2 whose text contains one of these opens a question-and-answer region.
_FAQ_HEADINGS = ("faq", "frequently asked", "common questions", "questions")

# Schema.org's FAQPage guidance is that the markup mirrors what a user can see. Eight is
# where v1 capped it; kept, because the cap is about page sanity, not about the parser.
MAX_FAQS = 8


def service_type_for(ctx: PipelineContext, visible: str) -> str:
    """The service name to mark up - or "" when the page does not visibly say it.

    NOT the primary keyword. A target keyword is geo-suffixed and word-ordered for a
    search box ("slab leak repair san jose"); no page says that, so marking it up is
    marking up a claim the reader cannot see. `validate_json_ld` rejects it, and it is
    right to - that is the shape of keyword-stuffed markup that draws a manual action.

    Caught by running this stage over a real draft: the raw keyword failed validation
    on the first try, which is the check doing its job on code I had just written.

    So: strip the geo token, then require the remainder to actually appear on the page.
    A missing optional property is a smaller defect than an unsupported one.
    """
    if ctx.page_type not in ("service", "local"):
        return ""
    name = (ctx.primary_keyword or "").strip()
    if ctx.geo:
        name = re.sub(re.escape(ctx.geo), "", name, flags=re.I).strip(" -|,")
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return ""
    return name if name.lower() in visible.lower() else ""


def derive_faqs(draft_md: str) -> tuple[FaqItem, ...]:
    """Q&A pairs from a visible FAQ section: H3 questions, prose beneath as answers."""
    in_faq = False
    out: list[FaqItem] = []
    question: str | None = None
    answer: list[str] = []

    def flush() -> None:
        nonlocal question, answer
        if question and answer:
            out.append(FaqItem(question=question, answer=" ".join(answer).strip()))
        question, answer = None, []

    for line in draft_md.splitlines():
        text = line.strip()
        h2 = re.match(r"^##\s+(.*)$", text)
        h3 = re.match(r"^###\s+(.*)$", text)
        if h2:
            flush()
            in_faq = any(k in h2.group(1).strip().lower() for k in _FAQ_HEADINGS)
        elif not in_faq:
            continue
        elif h3:
            flush()
            question = strip_markdown(h3.group(1)).strip()
        elif text and question is not None:
            answer.append(strip_markdown(text).strip())
    flush()
    return tuple(out[:MAX_FAQS])


def run_schema_links(
    ctx: PipelineContext,
    *,
    business: Business | None = None,
    url: str = "",
) -> StageResult:
    """Build and validate the page's JSON-LD from what the page actually says."""
    if not ctx.draft_md.strip():
        return ctx.record(StageResult(
            STAGE, outcome="skipped", notes=("no draft to mark up",),
        ))

    faqs = derive_faqs(ctx.draft_md)
    # Validated against the VISIBLE text, plus title and description - which are part of
    # the page as the user meets it in the SERP, and which the body does not contain.
    # Without them a correct title mark-up reads as an unsupported claim.
    visible = "\n".join(x for x in (ctx.title, ctx.meta_description, ctx.draft_md) if x)
    page = Page(
        url=url,
        title=ctx.title or ctx.primary_keyword,
        description=ctx.meta_description,
        service_type=service_type_for(ctx, visible),
        area_served=(ctx.geo,) if ctx.geo else (),
        faqs=faqs,
    )
    graph = build_json_ld(
        ctx.page_type,
        business or Business(name=ctx.client_name or "", area_served=(ctx.geo,) if ctx.geo else ()),
        page,
    )

    verdict = validate_json_ld(graph, visible)

    notes: list[str] = []
    if faqs:
        notes.append(f"{len(faqs)} FAQ pairs marked up from the visible Q&A section")
    for err in getattr(verdict, "errors", ())[:6]:
        notes.append(f"schema error: {err}")
    for warn in getattr(verdict, "warnings", ())[:4]:
        notes.append(f"schema warning: {warn}")

    data: dict[str, Any] = {
        "json_ld": graph,
        "primary_type": getattr(verdict, "primary_type", None),
        "valid": bool(getattr(verdict, "valid", False)),
        "faqs": len(faqs),
        "errors": len(getattr(verdict, "errors", ())),
        "warnings": len(getattr(verdict, "warnings", ())),
    }
    ctx.brief["json_ld"] = graph
    # The GATE scores a schema_validity dimension off this. Storing only the graph and
    # not the verdict made the gate re-derive it as "absent" and score 60 on a document
    # that had just validated clean - caught by running the two stages back to back.
    ctx.brief["schema_validation"] = verdict
    return ctx.record(StageResult(
        STAGE,
        outcome="ok" if data["valid"] else "degraded",
        data=data, notes=tuple(notes),
    ))
