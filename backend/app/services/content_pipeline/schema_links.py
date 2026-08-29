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

AND THE LINKS THE TITLE PROMISED. Until now this stage built schema and nothing else:
`gate.py` passed `internal_links=[]`, no stage filled it, and the internal_linking
dimension scored 40 on every page the doctrine engine wrote. The pillar/cluster map to
build them from was already in the context - `brief.cluster` - so the links are planned
here, from data the page already paid for. A target only becomes a real `<a>` when a
real URL is known for it; the rest are recorded as anchor + keyword with no href, and
the notes say how many, because a guessed path is a 404 in a client's own body copy.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.services.content_generator import InternalLink
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

# How many internal links one page carries. Same cap as v1's MAX_INTERNAL_SPOKES (6):
# past that the "Related resources" block reads as a link farm, and content_qa scores
# anchor VARIETY, which a long list of near-identical spokes destroys.
MAX_INTERNAL_LINKS = 6

# The heading the resolved links live under. Also the IDEMPOTENCE key: schema_links is
# in EDIT_STAGES too, so a reviewer's edit re-runs this stage on a draft that already
# carries the block. Appending unconditionally would give a twice-edited page three
# copies of its own link list.
RELATED_HEADING = "Related resources"


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


def plan_internal_links(
    ctx: PipelineContext,
    *,
    internal_urls: Mapping[str, str] | None = None,
    limit: int = MAX_INTERNAL_LINKS,
) -> list[InternalLink]:
    """The pillar/cluster links this page should carry, from the research brief.

    THE DEFECT THIS CLOSES. `gate.py` passed `internal_links=[]` and no stage in this
    pipeline ever produced one, so `content_qa`'s internal_linking dimension scored the
    same 40 ("no internal links - pillar<->cluster map not applied") on every page the
    doctrine engine has ever written. The cluster map it needed was already in the
    context: `run_research` stores the brief, and `brief.cluster` is the pillar plus its
    supporting spokes - the same structure v1's `_links_block` builds from.

    URLS ARE NEVER INVENTED. v1 maps a spoke to `f"/{_slug(spoke)}"`, which is a guess
    at a path that may not exist; a 404 in a client's own body copy is worse than no
    link. Here a link gets a URL only from ``internal_urls`` - the operator's registry
    plus the client's own already-published sibling pages - and a target with no known
    URL is returned with `url=""`, i.e. an ANCHOR AND A TARGET KEYWORD and no href. The
    caller says so out loud rather than filling the gap.

    A page never links to itself: on a pillar page `cluster.pillar` IS the primary
    keyword, so the self-link has to be filtered or the page's most prominent internal
    link points at the page you are already on.
    """
    if ctx.page_type == "gbp_post":
        # A Business Profile update is a standalone post, never part of a pillar/cluster
        # scheme - the same early-return content_qa's own _score_internal_linking makes.
        return []

    brief = ctx.brief.get("research")
    cluster = getattr(brief, "cluster", None)
    targets: list[str] = []
    pillar = str(getattr(cluster, "pillar", "") or "")
    if pillar:
        targets.append(pillar)
    targets.extend(str(x) for x in (getattr(cluster, "supporting", None) or []))

    own = (ctx.primary_keyword or "").strip().lower()
    registry = {
        str(k).strip(): str(v).strip()
        for k, v in (internal_urls or {}).items()
        if str(k).strip() and str(v).strip()
    }

    links: list[InternalLink] = []
    seen: set[str] = set()
    # The registry first: a link with a real URL is worth more than a planned one, and
    # the cap must not spend its budget on unresolved targets while real pages wait.
    for keyword, url in registry.items():
        key = keyword.lower()
        if key == own or key in seen or len(links) >= limit:
            continue
        seen.add(key)
        links.append(InternalLink(anchor=keyword, url=url, keyword=keyword))
    for target in targets:
        key = target.strip().lower()
        if not key or key == own or key in seen or len(links) >= limit:
            continue
        seen.add(key)
        links.append(InternalLink(anchor=target.strip(), url="", keyword=target.strip()))
    return links


def render_related_block(draft_md: str, links: list[InternalLink]) -> str:
    """Append the RESOLVED links to the draft as a Related-resources list.

    Only links that have a URL are written, and that is the whole point: a planned link
    is not on the page, so it must not appear on the page and must not be counted as if
    it were. `- [anchor]()` is broken markup that renders as unclickable text, which is
    exactly the "looks done, is not" outcome the job contract exists to stop.
    """
    resolved = [x for x in links if x.url]
    if not resolved or RELATED_HEADING.lower() in draft_md.lower():
        return draft_md
    body = "\n".join(f"- [{x.anchor}]({x.url})" for x in resolved)
    return f"{draft_md.rstrip()}\n\n## {RELATED_HEADING}\n\n{body}\n"


def run_schema_links(
    ctx: PipelineContext,
    *,
    business: Business | None = None,
    url: str = "",
    internal_urls: Mapping[str, str] | None = None,
) -> StageResult:
    """Build the page's JSON-LD and its internal links from what the page actually says.

    Order matters: the links are planned and the RESOLVED ones written into the draft
    BEFORE the graph is built, because `validate_json_ld` matches every marked-up value
    against the visible text and the link block is part of that text.
    """
    if not ctx.draft_md.strip():
        return ctx.record(StageResult(
            STAGE, outcome="skipped", notes=("no draft to mark up",),
        ))

    planned = plan_internal_links(ctx, internal_urls=internal_urls)
    ctx.draft_md = render_related_block(ctx.draft_md, planned)
    resolved = [x for x in planned if x.url]
    unresolved = [x for x in planned if not x.url]
    # ONLY the resolved links reach the gate. content_qa's internal_linking dimension
    # asks whether the page carries the pillar/cluster links; handing it the plan would
    # score a page 100 for links a reader cannot click - the exact shape of "faking
    # success" this codebase keeps closing. The plan travels separately so the gate can
    # SAY why the dimension is low instead of leaving the 40 unexplained.
    ctx.brief["internal_links"] = resolved
    ctx.brief["internal_links_planned"] = planned

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
    if resolved:
        notes.append(f"{len(resolved)} internal links written into the page from the cluster map")
    if unresolved:
        notes.append(
            f"{len(unresolved)} cluster targets have NO url and are NOT on the page: "
            "the platform knows no published sibling page for them (nothing in the "
            "operator's registry, nothing pushed to WordPress yet). Their anchor and "
            "target keyword are recorded; a url would have to be invented."
        )
    if not planned:
        notes.append(
            "no internal links planned: the research brief carried no pillar/cluster map"
        )
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
        # The reviewer's link panel reads `links`; it is the FULL plan so the operator
        # can see what the page should point at, and `unresolved` is how many of those
        # have no href yet. Two numbers, so neither reads as the other.
        "internal_links": [
            {"anchor": x.anchor, "url": x.url, "keyword": x.keyword} for x in planned
        ],
        "internal_links_on_page": len(resolved),
        "internal_links_unresolved": len(unresolved),
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
