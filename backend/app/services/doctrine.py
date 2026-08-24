"""The doctrine chunk index - making 2.6MB of corpus addressable at runtime.

`content_generator` and `content_qa` have always cited
``backend/seo-content-os/knowledge/`` as the source of their numeric constants. P1A put
the corpus there. This makes it USABLE: split into addressable chunks so a stage can
be handed the 15k tokens that govern it rather than the 2.6MB that governs everything.

WHY RULE-BASED RETRIEVAL, NOT EMBEDDINGS. This is 133 markdown files of curated
doctrine, not a million-document corpus. A hand-authored routing table (see
:mod:`app.services.doctrine_routes`) is deterministic, free, unit-testable and -
critically - AUDITABLE: six months from now you can say exactly which doctrine
governed page 37, because the chunk ids are recorded per call. Embeddings would add
Voyage plus Pinecone (both deliberately excluded from the default image), cost money
on every page, and make the answer LESS explainable. The corpus is small enough that
the expensive machinery would buy nothing.

CHUNK IDS ARE STABLE AND HUMAN-READABLE - ``relpath#slugified-heading``. That matters
more than it looks: an id is what gets written into the provenance ledger, so it has
to survive being read by a person a year later and grepped back to a file.

TOKEN COUNTS ARE ESTIMATES, and deliberately so. ``len(text) / 4`` is the standard
English heuristic. A real tokenizer would mean carrying `tiktoken` or the Anthropic
SDK's counter into a pure module, and the estimate is only ever used to keep an
assembled block inside a budget - being 10% out costs a slightly smaller pack, while
the dependency would cost a great deal more. Anywhere exactness matters, the API's own
usage numbers are authoritative and are what the cost gate meters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.services.content_lint.corpus import corpus_root

# Indexed areas. `research/` is provenance for WHY the doctrine says what it says and
# is deliberately excluded - it would double the index while never being routed to.
INDEXED_AREAS: tuple[str, ...] = ("knowledge", "agents", "commands", "skills")

# Files indexed whole, outside the areas above.
INDEXED_FILES: tuple[str, ...] = ("CLAUDE.md",)

_CHARS_PER_TOKEN = 4.0

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def estimate_tokens(text: str) -> int:
    """Heuristic token count (~4 chars/token). See the module docstring on why."""
    return max(1, round(len(text) / _CHARS_PER_TOKEN))


def slugify(heading: str) -> str:
    return _SLUG_STRIP_RE.sub("-", heading.lower()).strip("-")


@dataclass(frozen=True)
class DoctrineChunk:
    """One addressable section of doctrine."""

    id: str        # "knowledge/quality-gates/gates.md#run-order-at-a-glance"
    path: str      # corpus-relative file path
    heading: str   # the heading text, or "" for a file preamble
    level: int     # 0 preamble, 1 H1, 2 H2, 3 H3
    text: str
    tokens: int

    @property
    def area(self) -> str:
        return self.path.split("/", 1)[0]


def _split_file(path: Path, relpath: str) -> list[DoctrineChunk]:
    """Split one markdown file on H1-H3 boundaries.

    Content before the first heading becomes a level-0 PREAMBLE chunk rather than
    being dropped - in this corpus the preamble is frequently the thesis of the file,
    and losing it would silently remove the part a stage most needs.
    """
    text = path.read_text(encoding="utf-8")
    matches = list(_HEADING_RE.finditer(text))
    chunks: list[DoctrineChunk] = []

    def add(heading: str, level: int, body: str) -> None:
        body = body.strip()
        if not body:
            return
        slug = slugify(heading) if heading else "preamble"
        chunks.append(DoctrineChunk(
            id=f"{relpath}#{slug}", path=relpath, heading=heading,
            level=level, text=body, tokens=estimate_tokens(body),
        ))

    if not matches:
        add("", 0, text)
        return chunks

    if matches[0].start() > 0:
        add("", 0, text[: matches[0].start()])

    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        add(m.group(2), len(m.group(1)), text[m.start() : end])
    return chunks


@cache
def chunk_index() -> tuple[DoctrineChunk, ...]:
    """Every doctrine chunk, in stable path order. Parsed once per process.

    Cached because this reads ~130 files and nothing about it can change at runtime.
    A duplicate id (two identical headings in one file) is disambiguated with a
    numeric suffix rather than silently overwriting, because an id that maps to two
    different texts would make the provenance ledger lie.
    """
    root = corpus_root()
    out: list[DoctrineChunk] = []
    seen: dict[str, int] = {}

    paths: list[Path] = [root / name for name in INDEXED_FILES]
    for area in INDEXED_AREAS:
        paths.extend(sorted((root / area).rglob("*.md")))

    for path in paths:
        if not path.is_file():
            continue
        relpath = path.relative_to(root).as_posix()
        for chunk in _split_file(path, relpath):
            count = seen.get(chunk.id, 0)
            seen[chunk.id] = count + 1
            if count:
                chunk = DoctrineChunk(
                    id=f"{chunk.id}-{count + 1}", path=chunk.path, heading=chunk.heading,
                    level=chunk.level, text=chunk.text, tokens=chunk.tokens,
                )
            out.append(chunk)
    return tuple(out)


@cache
def chunks_by_id() -> dict[str, DoctrineChunk]:
    return {c.id: c for c in chunk_index()}


@cache
def chunks_by_path() -> dict[str, tuple[DoctrineChunk, ...]]:
    grouped: dict[str, list[DoctrineChunk]] = {}
    for chunk in chunk_index():
        grouped.setdefault(chunk.path, []).append(chunk)
    return {path: tuple(items) for path, items in grouped.items()}


def whole_file(relpath: str) -> tuple[DoctrineChunk, ...]:
    """Every chunk of one file, in document order. Raises if the file is not indexed."""
    chunks = chunks_by_path().get(relpath)
    if not chunks:
        raise KeyError(
            f"{relpath!r} is not in the doctrine index. Indexed areas: "
            f"{', '.join(INDEXED_AREAS)} plus {', '.join(INDEXED_FILES)}."
        )
    return chunks


def resolve(*refs: str) -> tuple[DoctrineChunk, ...]:
    """Resolve chunk ids and whole-file paths to chunks, de-duplicated, order preserved.

    A ref containing ``#`` is a chunk id; otherwise it is a file path meaning "all of
    it". Mixing the two is deliberate: some doctrine is only meaningful whole (the
    compliance spine), while for a long playbook a stage wants two sections.
    """
    index = chunks_by_id()
    out: list[DoctrineChunk] = []
    seen: set[str] = set()
    for ref in refs:
        found = (index[ref],) if "#" in ref and ref in index else whole_file(ref)
        for chunk in found:
            if chunk.id not in seen:
                seen.add(chunk.id)
                out.append(chunk)
    return tuple(out)


def fit(
    chunks: tuple[DoctrineChunk, ...], *, max_tokens: int | None = None
) -> tuple[tuple[DoctrineChunk, ...], tuple[DoctrineChunk, ...]]:
    """Split chunks into ``(kept, dropped)`` under a token ceiling.

    Truncation drops WHOLE CHUNKS from the tail rather than cutting mid-text: half a
    rule is worse than no rule, because a model will follow the half it was given.

    Returning what was DROPPED is the point. A block that silently loses 29% of its
    doctrine looks identical to one that fits, and the resulting pages would just be
    quietly worse. The caller records the dropped ids so the loss is visible in the
    provenance ledger rather than inferred later from disappointing output.
    """
    if max_tokens is None:
        return chunks, ()
    kept: list[DoctrineChunk] = []
    dropped: list[DoctrineChunk] = []
    used = 0
    for chunk in chunks:
        if used + chunk.tokens > max_tokens and kept:
            dropped.append(chunk)
            continue
        kept.append(chunk)
        used += chunk.tokens
    return tuple(kept), tuple(dropped)


def render(chunks: tuple[DoctrineChunk, ...], *, max_tokens: int | None = None) -> str:
    """Render chunks into one prompt block, bounded by ``max_tokens``."""
    kept, _dropped = fit(chunks, max_tokens=max_tokens)
    return "\n\n".join(c.text for c in kept)


def total_tokens(chunks: tuple[DoctrineChunk, ...]) -> int:
    return sum(c.tokens for c in chunks)
