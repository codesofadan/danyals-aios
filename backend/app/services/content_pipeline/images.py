"""IMAGES - the stage the doctrine engine never had (P3, stage 8c).

`settings.content_engine` defaults to `v2`, and `PAGE_STAGES` had no image step. So
from the moment the doctrine engine became the default, every page it produced was
text-only: no hero photo, no section photos, and `content_jobs.images` left at 0 on a
row whose v1-written siblings all carry pictures. v1 has generated images since P7A-2;
the replacement engine silently dropped the capability rather than deciding against it.

WHY THE PLAN IS DETERMINISTIC. v1 spends a writer call per page whose ONLY product is
a decision about what to photograph (`_photo_briefs`, workers/tasks/content.py's
generator). Nothing else reads it. Here the plan's STRUCTURE comes from the finished
draft itself - the H1 for the hero, the H2s for the section slots, in document order -
and only the scene WORDING costs a call: one per page, never one per image.

WHY THE PROMPT NEVER NAMES THE TOPIC. Proven at the provider and recorded at
content_generator's `Image planning (§9)` comment block: gpt-image ignores negative
prompts, and handed an ABSTRACT topic as its subject it renders that topic AS TITLE
TEXT - a flat-vector infographic with words in it, every time. The only reliable lever
is a CONCRETE, LITERAL scene.
Without a writer call there is no way to author a concrete scene that is also topical,
so this stage reuses v1's proven topic-free scene bank and SAYS SO in its notes. The
topical payload - the half that carries accessibility and on-page SEO - is the ALT
text, which is the section's own heading.

A KEYLESS RUN PRODUCES NOTHING AND IS BILLED NOTHING. This is v1's hard-won rule
(workers/tasks/content.py:_generate_images) and it is reproduced here deliberately:
`FakeImageGenerator` is what the provider factory substitutes when `IMAGE_GEN_API_KEY`
is absent, its URLs are sha256 placeholders, and charging for them wrote spend into the
cost ledger for provider calls that never happened. No provider call means no cost row,
no `images` count, and a note that names the missing key.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from typing import Any

from app.config import Settings
from app.services import pricing

# The camera/realism suffix and the concrete scene bank are PROVEN PROVIDER FACTS, not
# style choices - see the comment block above _CAMERA_SUFFIX in content_generator. They
# are imported rather than copied because two divergent copies means one engine quietly
# starts producing infographics again and nobody knows which.
from app.services.content_generator import (
    _CAMERA_SUFFIX,
    _FALLBACK_SCENES,
    ImagePlanItem,
)
from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.cost_gate import CostGate, GateContext
from integrations.images import FakeImageGenerator, GeneratedImage, ImageGenerator

STAGE = "images"

# The money dial, the ledger's provider label and the job type. These MUST read exactly
# as v1's `_CONTENT_FEATURE` / `_IMAGE_PROVIDER` / `_JOB_TYPE` in workers/tasks/content.py:
# the same dial governs both engines, and cost_log rows have to stay comparable across
# the engine flip. They are re-declared rather than imported because that module is a
# Celery task, and an `app.services` import of it drags Celery into every module that
# touches a stage - the same objection schema_links records for the FAQ parser.
FEATURE_KEY = "content"
IMAGE_PROVIDER = "images"
JOB_TYPE = "content"

#: The conservative default when nothing configures it: ONE hero image per page.
#: v1's cap is 5 (MAX_IMAGES), which is 5x the per-page image bill on an engine that
#: has never had a paid image run. One picture is the smallest change that stops a
#: page shipping with no featured image at all.
DEFAULT_MAX_IMAGES = 1

_H2_RE = re.compile(r"^##\s+(?!#)(.*)$")
_H1_RE = re.compile(r"^#\s+(?!#)(.*)$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def max_images_for(settings: Settings) -> int:
    """How many images this page is allowed to generate.

    Two knobs, and the OFF switch wins: `content_images_enabled` is the existing
    platform-wide photo dial that v1 already honours, so a deployment that turned
    photos off must not have the new engine turn them back on.
    """
    if not settings.content_images_enabled:
        return 0
    return max(0, int(settings.content_pipeline_max_images))


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", text.strip().lower()).strip("-")[:48]


def _scene_offset(seed: str) -> int:
    """Where in the scene bank this page starts.

    Starting every page at scene 0 would give every page on a client's site the same
    stock desk photo as its hero - the bank is topic-free by design, so position is the
    only thing distinguishing one page's images from the next one's. v1 avoids the
    collision by paying a writer call per page; this rotates the bank by a stable hash
    of the keyword instead, which is free and still deterministic (the same page
    re-drafted gets the same images).
    """
    if not seed:
        return 0
    digest = hashlib.sha256(seed.encode()).hexdigest()[:8]
    return int(digest, 16) % len(_FALLBACK_SCENES)


#: How many scene briefs one writer call may author. Bounded so a runaway max_images
#: cannot turn a cheap planning call into a long generation.
_MAX_AUTHORED_SCENES = 8


def _scene_prompt(ctx: PipelineContext, slots: Sequence[tuple[str, str]]) -> str:
    """Ask for ONE concrete, literal scene per slot, grounded in this page's subject."""
    sections = "\n".join(f"{i + 1}. {alt}" for i, (_slot, alt) in enumerate(slots))
    subject = ctx.title or ctx.primary_keyword
    where = f" in {ctx.geo}" if ctx.geo else ""
    who = f" for {ctx.client_name}" if ctx.client_name else ""
    return "\n".join([
        f'A page titled "{subject}" needs {len(slots)} photographs{who}{where}.',
        "",
        "Write ONE photographic scene description per section below. Each must be a",
        "CONCRETE, LITERAL, PHYSICAL scene a photographer could walk into and shoot:",
        "real objects, real people doing a real thing, a real place, real light.",
        "",
        "HARD RULES, each of which the image model will otherwise break:",
        "- Never name the topic, the industry or any abstract noun as the SUBJECT.",
        "  Handed an abstract subject the model renders it as TITLE TEXT and returns a",
        "  flat vector infographic. Describe only what is physically in frame.",
        "- No text, letters, words, numbers, signage, labels, logos, packaging copy,",
        "  screens showing text, charts, diagrams, icons or infographics.",
        "- No brand names and no recognisable real person.",
        "- One scene per entry, 20-40 words, no preamble and no numbering in the value.",
        "",
        "Sections:",
        sections,
        "",
        f"Reply with ONLY a JSON array of exactly {len(slots)} strings.",
    ])


def _parse_scenes(raw: str, wanted: int) -> list[str]:
    """Pull a list of scene strings out of the reply; [] when it is unusable."""
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    scenes = [str(x).strip() for x in parsed if isinstance(x, str) and str(x).strip()]
    # A reply that lost slots is still useful - the caller pads from the bank - but a
    # reply of the wrong SHAPE (objects, nested lists) is not.
    return scenes[:wanted]


def plan_images(
    ctx: PipelineContext,
    *,
    max_images: int,
    writer: Any | None = None,
    accounting: Any | None = None,
) -> tuple[ImagePlanItem, ...]:
    """A hero plus one image per H2, in document order, capped at ``max_images``.

    Read off the FINISHED draft rather than the outline: the draft is what the reader
    gets, and the voice and grounding stages both rewrite headings, so an outline-based
    plan would caption sections that no longer exist under those names.
    """
    if max_images <= 0:
        return ()
    h1 = ""
    h2s: list[str] = []
    for line in ctx.draft_md.splitlines():
        text = line.strip()
        h2 = _H2_RE.match(text)
        if h2:
            h2s.append(h2.group(1).strip())
            continue
        h1_match = _H1_RE.match(text)
        if h1_match and not h1:
            h1 = h1_match.group(1).strip()

    hero_alt = h1 or ctx.title or ctx.primary_keyword
    if not hero_alt:
        return ()

    slots: list[tuple[str, str]] = [("hero", hero_alt)]
    for heading in h2s:
        if len(slots) >= max_images:
            break
        if not heading:
            continue
        slots.append((f"section:{_slug(heading)}", heading))

    # TOPICAL SCENES, authored once per page.
    #
    # This stage used to draw every prompt from a topic-free bank, and said why: an
    # abstract topic handed to gpt-image comes back as title text, and "without a
    # writer call there is no way to author a concrete scene that is also topical".
    # The pipeline HAS a writer, so that is now one cheap call - and the reason it
    # matters is that a skincare page illustrated from the bank shipped a photograph
    # of a man in an office corridor. A generic picture is not a neutral default; it
    # actively contradicts the page.
    #
    # The bank remains the FALLBACK, per slot, so a missing writer, a spend block or
    # a malformed reply still yields a fully illustrated page.
    authored: list[str] = []
    if writer is not None:
        try:
            raw = writer.write(
                STAGE,
                _scene_prompt(ctx, slots[:_MAX_AUTHORED_SCENES]),
                page_type=ctx.page_type,
                vertical=ctx.vertical or None,
                max_tokens=2_000,
                expected_calls=1,
                accounting=accounting,
            )
            authored = _parse_scenes(raw, len(slots))
        except Exception:
            authored = []

    start = _scene_offset(ctx.primary_keyword or hero_alt)
    return tuple(
        ImagePlanItem(
            slot=slot,
            prompt=(
                f"{authored[i]} {_CAMERA_SUFFIX}"
                if i < len(authored)
                else f"{_FALLBACK_SCENES[(start + i) % len(_FALLBACK_SCENES)]} {_CAMERA_SUFFIX}"
            ),
            alt=alt,
        )
        for i, (slot, alt) in enumerate(slots)
    )


def image_md(image: GeneratedImage) -> str:
    """The Markdown tag every downstream consumer already understands."""
    return f"![{image.alt}]({image.url})"


def inject_images(draft_md: str, resolved: Sequence[tuple[str, GeneratedImage]]) -> str:
    """Place each generated image at the top of the section it introduces.

    Same placement rule as v1's `_inject_images`, and re-implemented here for the same
    reason schema_links re-implements the FAQ parser: the original lives in a Celery
    task module. Hero goes under the H1; section images follow the H2s IN ORDER, which
    does not depend on an image's alt still matching its heading - so a heading the
    voice stage rephrased never collapses every image into one spot.

    Only images with a real URL are ever passed in, so this cannot write broken markup.
    """
    if not resolved:
        return draft_md
    lines = draft_md.splitlines()
    h1_idx: int | None = None
    h2_idxs: list[int] = []
    for i, line in enumerate(lines):
        text = line.strip()
        if _H2_RE.match(text):
            h2_idxs.append(i)
        elif h1_idx is None and _H1_RE.match(text):
            h1_idx = i

    top = h1_idx if h1_idx is not None else -1  # -1 = before the first line
    after: dict[int, list[str]] = {}
    section = 0
    for slot, image in resolved:
        if slot == "hero":
            after.setdefault(top, []).append(image_md(image))
            continue
        # Past the last H2 an image folds under it rather than being dropped: the
        # plan is capped at the H2 count, so this only fires on a draft the voice
        # stage restructured between planning and injection.
        idx = (h2_idxs[section] if section < len(h2_idxs) else h2_idxs[-1]) if h2_idxs else top
        section += 1
        after.setdefault(idx, []).append(image_md(image))

    out: list[str] = []
    for md in after.get(-1, []):
        out.extend((md, ""))
    for i, line in enumerate(lines):
        out.append(line)
        for md in after.get(i, []):
            out.extend(("", md))
    return "\n".join(out)


def _skipped(ctx: PipelineContext, note: str) -> StageResult:
    """A stage that produced no image, said why, and charged nothing."""
    return ctx.record(StageResult(
        STAGE, outcome="skipped", data={"images": 0, "planned": 0}, notes=(note,),
    ))


def run_images(
    ctx: PipelineContext,
    *,
    generator: ImageGenerator,
    gate: CostGate,
    settings: Settings,
    max_images: int | None = None,
    writer: Any | None = None,
) -> StageResult:
    """Generate the planned images, one gate decision per image, and weave them in."""
    if not ctx.draft_md.strip():
        return _skipped(ctx, "no draft to illustrate")

    limit = max_images if max_images is not None else max_images_for(settings)
    if limit <= 0:
        return _skipped(
            ctx,
            "images are switched off (content_images_enabled / "
            f"content_pipeline_max_images = {limit}); the page carries no photos",
        )

    if isinstance(generator, FakeImageGenerator):
        # THE KEYLESS RULE. The provider factory substitutes this generator when
        # IMAGE_GEN_API_KEY is absent; its URLs are sha256 placeholders of the prompt.
        # Generating them would inject fake pictures into a client's page, and billing
        # for them wrote ledger rows for calls that never happened. Say it out loud - a
        # silent zero is indistinguishable from "the plan asked for none".
        return _skipped(
            ctx,
            "no image provider configured (IMAGE_GEN_API_KEY unset): no image was "
            "generated and nothing was billed",
        )

    plan = plan_images(ctx, max_images=limit, writer=writer)
    if not plan:
        return _skipped(ctx, "the draft carries no heading to hang an image on")

    per_image = settings.price_image_per_image
    resolved: list[tuple[str, GeneratedImage]] = []
    notes: list[str] = []
    cost = 0.0

    for item in plan:
        gate_ctx = GateContext(
            feature_key=FEATURE_KEY,
            client_id=ctx.client_id,
            provider=IMAGE_PROVIDER,
            estimated_cost=per_image,  # the pre-check is one image's price, as in v1
            job_id=ctx.job_code,
            job_type=JOB_TYPE,
            client_name=ctx.client_name,
            cache_key=None,
        )
        decision = gate.evaluate(gate_ctx)
        if not decision.allowed:
            # A dial block stops IMAGES, never the page: the draft is already written
            # and paid for. The count that lands on the row is what was produced.
            notes.append(
                f"image spend stopped after {len(resolved)} of {len(plan)} "
                f"({decision.outcome}"
                + (f": {decision.reason}" if decision.reason else "")
                + ")"
            )
            break
        try:
            image = generator.generate(item.prompt, item.alt)
        except Exception as exc:  # one bad image never loses a written page
            notes.append(
                f"the image for '{item.alt}' failed ({type(exc).__name__}); that "
                "section has no photo, and nothing was billed for it"
            )
            continue
        if not image.url:
            # The provider answered without giving us a picture. Nothing is injected,
            # so nothing is counted and nothing is charged - the ledger records what
            # happened, not what was attempted.
            notes.append(
                f"the provider returned no url for '{item.alt}'; nothing injected, "
                "nothing billed"
            )
            continue
        actual = pricing.image_cost(settings, images=1)
        gate.commit(gate_ctx, actual)
        cost += actual
        resolved.append((item.slot, image))

    if resolved:
        ctx.draft_md = inject_images(ctx.draft_md, resolved)
        # Said on every run that produced a picture, because it is a real limitation a
        # reviewer would otherwise have to discover by looking at the page: the scene is
        # generic on purpose (a topical prompt renders an infographic), and the page's
        # subject is carried by the alt text alone.
        notes.append(
            f"{len(resolved)} image(s) from the topic-free concrete scene bank - no "
            "writer call was made to author a topical scene, so the page's subject "
            "lives in the alt text, not in the photograph"
        )

    data: dict[str, Any] = {
        "images": len(resolved),
        "planned": len(plan),
        "slots": [slot for slot, _img in resolved],
        "alts": [img.alt for _slot, img in resolved],
        "urls": [img.url for _slot, img in resolved],
    }
    ctx.brief["images"] = data
    return ctx.record(StageResult(
        STAGE,
        # Fewer pictures than planned is a VISIBLE degrade with its cause in the notes,
        # not a failure: the page exists and a human can still read it.
        outcome="ok" if len(resolved) == len(plan) else "degraded",
        data=data,
        notes=tuple(notes),
        cost=round(cost, 6),
        # llm_calls stays 0 on purpose: an image generation is not an LLM call, and the
        # run's llm_calls feeds the token/cache reporting, which has no tokens here.
    ))
