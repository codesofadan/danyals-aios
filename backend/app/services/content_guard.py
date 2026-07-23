"""Wave 5: the AI / em-dash GUARD - a PURE, deterministic detector + de-AI rewriter
for generated content, with a HARD post-process guarantee of ZERO em/en dashes.

The client's single hardest rule for generated copy: it must NOT read as "AI
slop", and it must carry NO em dashes (U+2014) or en dashes (U+2013) - the single
most reliable machine-writing tell. This module is the enforcement point.

It is split into three layers, in strictly increasing trust cost:

1. **Detection (100% pure).** :func:`scan` reads a draft and returns a
   :class:`GuardReport`: the exact em/en-dash counts, the AI-cliche phrases it
   found, an ``ai_score`` (0-100, higher = more machine-like), and the ``flagged``
   verdict. No I/O, no writer, fully deterministic - so it is unit-tested
   exhaustively against hand-built strings.
2. **Section rewrite (writer-injected).** :func:`deai_draft` splits the markdown
   into blocks, and for each FLAGGED prose block (a block that carries a forbidden
   dash or crosses the AI-phrase trigger) it asks the injected ``Summarizer`` to
   rewrite that ONE block in plain, direct, client-friendly local-SEO copy - no
   em dashes, no AI cliches, and (critically) inventing NO new facts. Headings,
   list/table blocks, ``[NEEDS:]`` placeholders, and the protected answer block are
   never sent to the writer (they carry grounded facts or structure QA depends on);
   they are only dash-stripped. The writer is the ONLY external touch, so the worker
   injects a cost-gated one - the pure core never reaches a raw provider. Any writer
   failure (a spend block, a provider error) DEGRADES to a plain strip of that
   block; the guard never raises and never loses the draft.
3. **The hard guarantee (100% pure, unconditional).** :func:`strip_dashes` runs on
   EVERY block after any rewrite, so the returned draft is GUARANTEED dash-free even
   if the writer was unavailable or (perversely) emitted a dash of its own. This is
   the belt-and-braces contract the pipeline relies on: ``count_dashes`` of a
   :func:`deai_draft` / :func:`strip_dashes` result is always ``(0, 0)``.

Purity mirrors ``content_generator.py`` / ``content_qa.py``: given a deterministic
(or no) writer, every function here is deterministic and network-free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from integrations.llm import Summarizer

if TYPE_CHECKING:  # only for the GeneratedContent adapter's typing (no runtime cycle)
    from app.services.content_generator import GeneratedContent

# --------------------------------------------------------------------------- #
# The forbidden dash family (the load-bearing rule).
# --------------------------------------------------------------------------- #
# Declared as \u escapes (never literal glyphs) so this source file itself carries
# no em/en dash byte - the same rule it enforces on generated copy.
EM_DASH = chr(0x2014)  # em dash: the primary machine-writing tell
EN_DASH = chr(0x2013)  # en dash: ranges and parenthetical asides
HORIZONTAL_BAR = chr(0x2015)  # horizontal bar (quotation dash)
FIGURE_DASH = chr(0x2012)  # figure dash
_NB_HYPHEN = chr(0x2011)  # non-breaking hyphen, normalized to a plain hyphen

# The whole family we HARD-strip so no unicode dash can survive. Em + en are the
# tracked/target pair; the rest are stripped too so the guarantee is total.
_DASH_CLASS = f"{FIGURE_DASH}{EN_DASH}{EM_DASH}{HORIZONTAL_BAR}"

# A numeric range (5-10) collapses to a tight ASCII hyphen; every other dash
# becomes a spaced ASCII hyphen. ``[ \t]`` (not ``\s``) so a line break is never
# swallowed - markdown block structure is preserved.
_RANGE_DASH_RE = re.compile(rf"(?<=\d)[ \t]*[{_DASH_CLASS}]+[ \t]*(?=\d)")
_SPACED_DASH_RE = re.compile(rf"[ \t]*[{_DASH_CLASS}]+[ \t]*")

_EM_RE = re.compile(re.escape(EM_DASH))
_EN_RE = re.compile(re.escape(EN_DASH))


# --------------------------------------------------------------------------- #
# The AI-cliche phrase set (the "reads like a machine wrote it" tells).
# --------------------------------------------------------------------------- #
# Literal phrases (case-insensitive, word-boundary alternation). Curated for the
# over-AI SEO-copy register the client flagged; each is a well-known LLM tic.
_AI_PHRASES: tuple[str, ...] = (
    "in today's fast-paced world",
    "in today's digital age",
    "in today's world",
    "in the digital age",
    "ever-evolving",
    "ever-changing",
    "fast-paced world",
    "in the world of",
    "in the realm of",
    "when it comes to",
    "it's important to note",
    "it is important to note",
    "it's worth noting",
    "it is worth noting",
    "needless to say",
    "at the end of the day",
    "look no further",
    "rest assured",
    "that being said",
    "in conclusion",
    "in summary",
    "first and foremost",
    "furthermore",
    "moreover",
    "in essence",
    "delve into",
    "delving into",
    "dive into",
    "deep dive",
    "unlock the",
    "unleash",
    "elevate your",
    "embark on",
    "navigating the",
    "navigate the",
    "seamless",
    "seamlessly",
    "cutting-edge",
    "state-of-the-art",
    "game-changer",
    "game changer",
    "tapestry",
    "a testament to",
    "testament to",
    "harness the power",
    "the power of",
    "unparalleled",
    "unwavering",
    "world-class",
    "top-notch",
    "bustling",
    "nestled",
    "one-stop shop",
    "we've got you covered",
    "you've come to the right place",
    "look no further than",
    "when it comes down to it",
    "revolutionize",
    "revolutionizing",
    "supercharge",
    "take it to the next level",
)

# Templated tells that need a wildcard (kept separate from the literal alternation).
_AI_TEMPLATE_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("not only ... but also", re.compile(r"\bnot only\b[^.?!]{0,80}?\bbut also\b", re.IGNORECASE)),
    ("whether you're ... or", re.compile(r"\bwhether you(?:'re| are)\b[^.?!]{0,60}?\bor\b", re.IGNORECASE)),
    ("take your ... to the next level",
     re.compile(r"\btake your\b[^.?!]{0,60}?\bto the next level\b", re.IGNORECASE)),
    ("from ... to ...", re.compile(r"\bfrom\b[^.?!]{0,40}?\bto\b[^.?!]{0,40}?,", re.IGNORECASE)),
)


def _literal_alternation(phrases: tuple[str, ...]) -> re.Pattern[str]:
    # Longest-first so a longer phrase wins over a contained shorter one; each phrase
    # is bounded by a non-word edge so "seamless" does not match inside "seamlessly"
    # (that variant is a phrase in its own right).
    ordered = sorted(phrases, key=len, reverse=True)
    body = "|".join(re.escape(p) for p in ordered)
    return re.compile(rf"(?<![\w-])(?:{body})(?![\w])", re.IGNORECASE)


_AI_LITERAL_RE = _literal_alternation(_AI_PHRASES)


# --------------------------------------------------------------------------- #
# Tunable thresholds (defaults are the doctrine; a caller may override).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GuardThresholds:
    """Knobs for the flag / rewrite decisions.

    ``max_ai_score`` - a document scoring at or above this is ``flagged``.
    ``max_phrases`` - a document with this many AI phrases is ``flagged`` (a
    second, count-based trigger independent of the score).
    ``block_phrase_trigger`` - a single BLOCK with this many AI phrases is rewritten
    (a forbidden dash in a block ALWAYS triggers a rewrite regardless).
    ``rewrite_word_ceiling`` - a rewritten block is hard-bounded to this many words
    (a runaway provider can never inflate a block past its budget).
    """

    max_ai_score: int = 35
    max_phrases: int = 4
    block_phrase_trigger: int = 2
    rewrite_word_ceiling: int = 220


DEFAULT_THRESHOLDS = GuardThresholds()

# Per-tell weights for the ``ai_score`` roll-up (0-100, clamped). An em dash is the
# heaviest single tell; en dashes and AI phrases contribute less.
_EM_WEIGHT = 30
_EN_WEIGHT = 18
_PHRASE_WEIGHT = 9


# --------------------------------------------------------------------------- #
# Detection outputs
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GuardFinding:
    """One detected tell: its ``kind`` (``em_dash`` / ``en_dash`` / ``ai_phrase``),
    the matched ``text`` (the phrase label or the literal dash), and ``count``."""

    kind: str
    text: str
    count: int


@dataclass(frozen=True)
class GuardReport:
    """The verdict for one text.

    ``em_dashes`` / ``en_dashes`` are exact counts; ``findings`` lists every tell;
    ``ai_score`` is the 0-100 machine-likeness roll-up; ``flagged`` is the "needs
    de-AI-ing" decision. ``dash_free`` is the load-bearing property the hard
    guarantee asserts.
    """

    em_dashes: int
    en_dashes: int
    findings: list[GuardFinding]
    ai_score: int
    flagged: bool

    @property
    def dash_free(self) -> bool:
        """True iff there is NOT a single em or en dash (the hard guarantee)."""
        return self.em_dashes == 0 and self.en_dashes == 0

    @property
    def phrase_count(self) -> int:
        return sum(f.count for f in self.findings if f.kind == "ai_phrase")

    @property
    def clean(self) -> bool:
        """True iff dash-free AND not otherwise flagged as over-AI."""
        return self.dash_free and not self.flagged


# --------------------------------------------------------------------------- #
# Pure detection
# --------------------------------------------------------------------------- #
def count_dashes(text: str) -> tuple[int, int]:
    """Return ``(em_dash_count, en_dash_count)`` for ``text`` (pure, no allocation
    beyond the match lists)."""
    return len(_EM_RE.findall(text)), len(_EN_RE.findall(text))


def has_forbidden_dashes(text: str) -> bool:
    """True iff ``text`` contains at least one em or en dash."""
    return EM_DASH in text or EN_DASH in text


def find_ai_tells(text: str) -> list[GuardFinding]:
    """Every AI-cliche phrase in ``text`` as ``ai_phrase`` findings (deduped by
    phrase, counted). Deterministic and case-insensitive."""
    counts: dict[str, int] = {}
    for match in _AI_LITERAL_RE.findall(text):
        key = " ".join(match.lower().split())
        counts[key] = counts.get(key, 0) + 1
    for label, pattern in _AI_TEMPLATE_RES:
        found = len(pattern.findall(text))
        if found:
            counts[label] = counts.get(label, 0) + found
    return [GuardFinding("ai_phrase", label, n) for label, n in sorted(counts.items())]


def scan(text: str, thresholds: GuardThresholds = DEFAULT_THRESHOLDS) -> GuardReport:
    """Scan ``text`` and return its :class:`GuardReport` (pure, deterministic).

    ``flagged`` trips on ANY forbidden dash, or an ``ai_score`` at/above
    ``max_ai_score``, or an AI-phrase count at/above ``max_phrases``.
    """
    em, en = count_dashes(text)
    tells = find_ai_tells(text)
    phrase_total = sum(f.count for f in tells)

    findings: list[GuardFinding] = []
    if em:
        findings.append(GuardFinding("em_dash", EM_DASH, em))
    if en:
        findings.append(GuardFinding("en_dash", EN_DASH, en))
    findings.extend(tells)

    ai_score = min(100, em * _EM_WEIGHT + en * _EN_WEIGHT + phrase_total * _PHRASE_WEIGHT)
    flagged = (
        em > 0
        or en > 0
        or ai_score >= thresholds.max_ai_score
        or phrase_total >= thresholds.max_phrases
    )
    return GuardReport(em_dashes=em, en_dashes=en, findings=findings, ai_score=ai_score, flagged=flagged)


# --------------------------------------------------------------------------- #
# The HARD guarantee: strip every unicode dash to ASCII (pure, unconditional)
# --------------------------------------------------------------------------- #
def strip_dashes(text: str) -> str:
    """Replace EVERY unicode dash with an ASCII hyphen and return the result.

    A numeric range (``5<en>10``) collapses to a tight ``5-10``; every other dash
    becomes a spaced `` - ``. A non-breaking hyphen is normalized to a plain
    hyphen. The result is GUARANTEED to contain no em or en dash:
    ``count_dashes(strip_dashes(t)) == (0, 0)`` for any ``t``.
    """
    text = text.replace(_NB_HYPHEN, "-")
    text = _RANGE_DASH_RE.sub("-", text)
    text = _SPACED_DASH_RE.sub(" - ", text)
    return text


# --------------------------------------------------------------------------- #
# Block splitting (markdown-aware, structure-preserving)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Block:
    """One markdown block (paragraphs are separated by blank lines).

    ``kind`` is ``heading`` / ``list`` / ``needs`` / ``prose``; ``text`` is the
    block's raw text (blank-line separators are re-inserted on reassembly).
    """

    kind: str
    text: str


def _classify(block: str) -> str:
    stripped = block.strip()
    if not stripped:
        return "prose"
    if "[NEEDS:" in stripped:
        return "needs"
    first = stripped.splitlines()[0].lstrip()
    if first.startswith("#"):
        return "heading"
    if first.startswith(("- ", "* ", "|", "> ")) or first.startswith(("-\t", "*\t")):
        return "list"
    return "prose"


def split_blocks(draft_md: str) -> list[Block]:
    """Split a markdown draft into ordered, classified blocks on blank lines."""
    raw_blocks = re.split(r"\n[ \t]*\n", draft_md)
    return [Block(_classify(b), b) for b in raw_blocks if b.strip()]


# --------------------------------------------------------------------------- #
# De-AI rewrite (writer-injected; strip-guaranteed)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DeaiResult:
    """The verdict of one :func:`deai_draft` pass.

    ``draft_md`` is the final draft, GUARANTEED dash-free. ``rewritten`` is the
    number of prose blocks the writer rephrased; ``stripped`` is the number of
    blocks that were only dash-stripped (headings, lists, protected, or a rewrite
    that fell back). ``writer_calls`` is the number of real writer invocations (for
    cost accounting). ``before`` / ``after`` are the whole-doc reports.
    """

    draft_md: str
    rewritten: int
    stripped: int
    writer_calls: int
    before: GuardReport
    after: GuardReport


_REWRITE_SYSTEM = (
    "Rewrite the passage below as plain, direct, client-friendly local-SEO copy. "
    "STRICT RULES: keep every fact, name, number, price, and claim EXACTLY as given "
    "- add nothing, remove nothing, invent nothing. Never use an em dash or en dash; "
    "use short sentences, commas, or the word 'to' for ranges. Avoid AI-cliche "
    "phrases. Do not add headings or lists. Return ONLY the rewritten passage.\n\n"
)


def _bound_words(text: str, max_words: int) -> str:
    tokens = text.split()
    if len(tokens) <= max_words:
        return text.strip()
    return " ".join(tokens[:max_words]).strip()


def _rewrite_block(
    block: Block,
    writer: Summarizer,
    model: str,
    thresholds: GuardThresholds,
) -> tuple[str, bool]:
    """Ask the writer to rephrase ONE prose block; hard-strip the result. Returns
    ``(text, writer_called)``. Any writer failure falls back to a plain strip, so
    this never raises - the dash-free guarantee holds either way."""
    original_words = max(len(block.text.split()), 1)
    ceiling = min(thresholds.rewrite_word_ceiling, original_words * 2)
    try:
        result = writer.summarize(
            _REWRITE_SYSTEM + block.text.strip(),
            model=model,
            max_tokens=max(64, ceiling * 2),
        )
    except Exception:  # a spend block or a provider error -> plain strip fallback
        return strip_dashes(block.text), False
    rewritten = result.text.strip()
    if not rewritten:
        return strip_dashes(block.text), True
    # The writer only phrases; the hard strip is applied unconditionally so even a
    # dash the provider emitted cannot survive.
    return strip_dashes(_bound_words(rewritten, ceiling)), True


def _block_needs_rewrite(block: Block, thresholds: GuardThresholds) -> bool:
    """A prose block is rewritten if it carries a forbidden dash OR crosses the
    per-block AI-phrase trigger. Non-prose blocks are never sent to the writer."""
    if block.kind != "prose":
        return False
    if has_forbidden_dashes(block.text):
        return True
    return sum(f.count for f in find_ai_tells(block.text)) >= thresholds.block_phrase_trigger


def deai_draft(
    draft_md: str,
    *,
    writer: Summarizer | None = None,
    model: str = "content-writer",
    thresholds: GuardThresholds = DEFAULT_THRESHOLDS,
    protect: frozenset[str] = frozenset(),
    max_rewrites: int | None = None,
) -> DeaiResult:
    """De-AI a draft: rewrite each flagged prose block via the injected ``writer``
    (one block at a time), then GUARANTEE a dash-free result via the hard strip.

    ``writer=None`` (or a spend-blocked / erroring writer) is fully supported: no
    block is rephrased, but every block is still dash-stripped, so the returned
    ``draft_md`` is ALWAYS dash-free. ``protect`` is a set of exact block texts
    (e.g. the extractable answer block) that are stripped only, never rephrased -
    they carry grounded facts or structure the QA gate depends on. ``max_rewrites``
    caps the number of writer calls (cost control); once a writer call fails the
    remaining blocks fall back to a plain strip.
    """
    before = scan(draft_md, thresholds)
    blocks = split_blocks(draft_md)
    protect_norm = {" ".join(p.split()) for p in protect}

    out_parts: list[str] = []
    rewritten = 0
    stripped = 0
    writer_calls = 0
    writer_live = writer is not None

    for block in blocks:
        norm = " ".join(block.text.split())
        wants_rewrite = (
            writer_live
            and block.kind == "prose"
            and norm not in protect_norm
            and _block_needs_rewrite(block, thresholds)
            and (max_rewrites is None or writer_calls < max_rewrites)
        )
        if wants_rewrite and writer is not None:
            text, called = _rewrite_block(block, writer, model, thresholds)
            if called:
                writer_calls += 1
                rewritten += 1
            else:
                # The writer went away (spend block / error): stop calling it and
                # plain-strip the rest so we make no further doomed provider calls.
                writer_live = False
                stripped += 1
            out_parts.append(text)
        else:
            out_parts.append(strip_dashes(block.text))
            stripped += 1

    final = "\n\n".join(out_parts)
    if not final.endswith("\n"):
        final += "\n"
    after = scan(final, thresholds)
    return DeaiResult(
        draft_md=final,
        rewritten=rewritten,
        stripped=stripped,
        writer_calls=writer_calls,
        before=before,
        after=after,
    )


# --------------------------------------------------------------------------- #
# GeneratedContent adapter (the worker's one-call entry point)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GuardedContent:
    """A de-AI'd :class:`GeneratedContent` plus the :class:`DeaiResult` audit."""

    content: GeneratedContent
    result: DeaiResult


_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_MD_SYNTAX_RE = re.compile(r"[#*`>\[\]()]|https?://\S+")


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(_MD_SYNTAX_RE.sub(" ", text)))


def guard_generated(
    content: GeneratedContent,
    *,
    writer: Summarizer | None,
    model: str = "content-writer",
    thresholds: GuardThresholds = DEFAULT_THRESHOLDS,
    max_rewrites: int | None = None,
) -> GuardedContent:
    """De-AI a whole :class:`GeneratedContent`: rewrite flagged prose blocks in the
    body, then dash-strip the body AND every text field (title, meta, answer block,
    headings) so the STORED + PUBLISHED draft is guaranteed em/en-dash-free.

    The extractable answer block is protected from rephrasing (it is already bounded,
    grounded, and primary-front-loaded by the generator - only its dashes are
    stripped). Word count is recomputed on the cleaned body; a de-AI note records
    what changed for the reviewer. Pure given a deterministic (or ``None``) writer.
    """
    result = deai_draft(
        content.draft_md,
        writer=writer,
        model=model,
        thresholds=thresholds,
        protect=frozenset({content.answer_block}) if content.answer_block else frozenset(),
        max_rewrites=max_rewrites,
    )
    clean_md = result.draft_md
    headings = [replace(h, text=strip_dashes(h.text)) for h in content.headings]
    notes = list(content.notes)
    if result.before.em_dashes or result.before.en_dashes or result.rewritten:
        notes.append(
            f"content guard: removed {result.before.em_dashes} em / {result.before.en_dashes} "
            f"en dashes, rewrote {result.rewritten} over-AI section(s)"
        )
    cleaned = replace(
        content,
        title=strip_dashes(content.title),
        meta_description=strip_dashes(content.meta_description),
        draft_md=clean_md,
        answer_block=strip_dashes(content.answer_block),
        headings=headings,
        word_count=_word_count(clean_md),
        notes=notes,
    )
    return GuardedContent(content=cleaned, result=result)
