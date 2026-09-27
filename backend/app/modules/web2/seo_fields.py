"""SEO fields for a Web 2.0 placement - and only the ones the platform actually has.

``M05`` REQ-W2-008: *SEO fields wherever the platform has them*. The qualifier is the
whole design. Before this, ``Web2Post`` carried a title, a slug and tags, and the
pipeline filled the slug and tags for every platform regardless of whether the adapter
sent them - so the work was done 54 times and used perhaps 20.

THE RULE HERE IS THE INVERSE: a field is derived only when ``PlatformSpec`` says the
adapter will transmit it. Deriving a meta description for Bluesky is not harmlessly
redundant - it is a metered model call producing a string nothing will ever read, on
every placement, forever.

WHAT IS DETERMINISTIC AND WHAT COSTS A CALL, deliberately split:

* ``slug`` - derived from the title. A model adds nothing to lowercasing and hyphenating.
* ``tags`` - taken from the brief's own terms, capped at the platform's measured limit
  (dev.to slices to 4; sending 10 wastes the other 6 silently).
* ``canonical_url`` - a FACT about where the original lives, never a guess.
* ``meta_description`` - the one genuinely generative field, and the only one that spends.
  It runs on the ``bulk`` tier because that is exactly what §3 reserves that tier for:
  "title/meta variants, description variants - high volume, low stakes".

Everything degrades: no router means a deterministic description built from the opening
sentence, which is worse prose than a model would write and materially better than an
empty tag. Nothing here can raise into the graph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.logging_setup import get_logger
from app.modules.web2.platform_spec import PlatformSpec
from app.platform.ai.prompts import get as get_prompt
from app.platform.ai.router import CostBlockedError, ModelRequest, ModelRouter
from app.platform.ai.tiers import TaskTier

logger = get_logger("modules.web2.seo_fields")

#: Where search engines truncate a description in practice. Not a rule anyone publishes -
#: it is a rendering limit that moves - so it is used as a WRITING target and enforced as
#: a hard cut, rather than presented as a standard.
META_DESCRIPTION_CHARS = 155

#: A slug long enough to read and short enough for a URL bar. Platforms that reject long
#: slugs do so silently by truncating, which produces two properties with colliding URLs.
MAX_SLUG_CHARS = 72

_NON_SLUG = re.compile(r"[^a-z0-9]+")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_MD_INLINE = re.compile(r"\[([^\]]+)\]\([^)]+\)|[*_`>]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class SeoFields:
    """The SEO metadata one placement carries. Empty means "this platform has no such
    field", never "we could not be bothered" - the distinction is what makes the report
    on these honest."""

    slug: str = ""
    meta_description: str = ""
    canonical_url: str = ""
    tags: tuple[str, ...] = ()
    spent_usd: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def as_row(self) -> dict[str, object]:
        """The columns to persist. Only non-empty values, so a platform without a field
        stores NULL rather than an empty string that reads as "we tried and got nothing"."""
        row: dict[str, object] = {}
        if self.slug:
            row["slug"] = self.slug
        if self.meta_description:
            row["meta_description"] = self.meta_description
        if self.canonical_url:
            row["canonical_url"] = self.canonical_url
        if self.tags:
            row["tags"] = list(self.tags)
        return row


def derive(
    *,
    spec: PlatformSpec,
    title: str,
    body_md: str,
    topic: str,
    client_name: str,
    candidate_tags: tuple[str, ...] = (),
    canonical_url: str = "",
    router: ModelRouter | None = None,
    module: str = "web2",
    feature_key: str = "content",
    client_id: str | None = None,
    job_id: str = "",
) -> SeoFields:
    """Derive the SEO fields ``spec`` says this platform will actually transmit."""
    notes: list[str] = []
    slug = _slugify(title or topic) if spec.supports_slug else ""
    tags = _tags(candidate_tags, spec) if spec.supports_tags else ()
    canonical = canonical_url if spec.supports_canonical else ""

    if not spec.supports_meta_description:
        # Named in the notes rather than silently skipped: "this platform has no meta
        # description" is a fact an operator looking at a thin report needs, and it is
        # indistinguishable from a bug unless someone writes it down.
        notes.append(f"{spec.platform} exposes no meta description field")
        return SeoFields(slug=slug, canonical_url=canonical, tags=tags, notes=notes)

    description, spent, why = _describe(
        title=title, body_md=body_md, topic=topic, client_name=client_name, router=router,
        module=module, feature_key=feature_key, client_id=client_id, job_id=job_id,
    )
    if why:
        notes.append(why)
    return SeoFields(
        slug=slug, meta_description=description, canonical_url=canonical, tags=tags,
        spent_usd=spent, notes=notes,
    )


def _describe(
    *, title: str, body_md: str, topic: str, client_name: str, router: ModelRouter | None,
    module: str, feature_key: str, client_id: str | None, job_id: str,
) -> tuple[str, float, str]:
    """The meta description, its cost, and a note when it degraded."""
    excerpt = _excerpt(body_md)
    if router is None or not router.configured:
        return _fallback_description(excerpt, title), 0.0, "meta description: no router, derived from the opening"
    prompt = get_prompt("web2/meta_description")
    try:
        result = router.complete(
            ModelRequest(
                task=TaskTier.BULK,
                prompt=prompt.render(
                    title=title, topic=topic, client_name=client_name,
                    excerpt=excerpt, max_chars=META_DESCRIPTION_CHARS,
                ),
                expected_output_tokens=80,
                module=module, client_id=client_id, client_name=client_name,
                job_id=job_id, job_type=module, feature_key=feature_key,
                prompt_id=prompt.id,
            )
        )
    except CostBlockedError as blocked:
        # A description is worth a fraction of a cent; refusing the whole placement over
        # one would spend the operator's budget ceiling on nothing.
        return (
            _fallback_description(excerpt, title), 0.0,
            f"meta description degraded: {blocked.outcome}",
        )
    text = _clean_description(result.text)
    return text or _fallback_description(excerpt, title), result.cost_usd, ""


def _clean_description(text: str) -> str:
    """Strip the wrapping a model habitually adds, then cut at a WORD boundary.

    A description cut mid-word is the failure this length limit exists to prevent, so
    enforcing the limit must not reintroduce it.
    """
    cleaned = _MD_INLINE.sub(r"\1", text.strip()).strip().strip('"').strip()
    cleaned = " ".join(cleaned.split())
    if len(cleaned) <= META_DESCRIPTION_CHARS:
        return cleaned
    clipped = cleaned[:META_DESCRIPTION_CHARS].rsplit(" ", 1)[0]
    return clipped.rstrip(",;:-— ")


def _fallback_description(excerpt: str, title: str) -> str:
    """A deterministic description from the page's own opening.

    Worse prose than a model would write, and materially better than an empty tag: the
    page still describes itself in the SERP rather than letting the engine invent a
    snippet from whatever it finds first.
    """
    source = excerpt.strip() or title.strip()
    if not source:
        return ""
    first = _SENTENCE.split(source)[0].strip()
    return _clean_description(first)


def _excerpt(body_md: str, *, sentences: int = 3) -> str:
    """The opening prose of the draft, with markdown scaffolding removed.

    Headings are dropped rather than included: a heading is a label, and feeding it to a
    description writer produces a description that restates the title - which rule 2 of
    the prompt exists to forbid.
    """
    body = _HEADING.sub("", body_md)
    body = _MD_INLINE.sub(r"\1", body)
    prose = [
        line.strip() for line in body.splitlines()
        if line.strip() and not line.lstrip().startswith(("-", "*", "|", ">"))
    ]
    joined = " ".join(prose)
    parts = _SENTENCE.split(joined)[:sentences]
    return " ".join(part.strip() for part in parts).strip()


def _slugify(text: str) -> str:
    """A URL-safe slug, cut at a WORD boundary so it stays readable."""
    slug = _NON_SLUG.sub("-", text.strip().lower()).strip("-")
    if len(slug) <= MAX_SLUG_CHARS:
        return slug
    return slug[:MAX_SLUG_CHARS].rsplit("-", 1)[0].strip("-")


def _tags(candidates: tuple[str, ...], spec: PlatformSpec) -> tuple[str, ...]:
    """The platform's own tag budget, applied here rather than discovered by the adapter.

    ``DevToClient`` slices to ``_MAX_TAGS=4``. Sending ten means six were chosen, carried
    and then dropped without anyone being told which - so the cap is applied where the
    choice is made, and the choice is the first N (the brief orders terms by relevance).
    """
    seen: list[str] = []
    for raw in candidates:
        tag = _NON_SLUG.sub("-", raw.strip().lower()).strip("-")
        if tag and tag not in seen:
            seen.append(tag)
    limit = spec.max_tags or len(seen)
    return tuple(seen[:limit])
