"""Deterministic AI-search / GEO page-level analyzers.

These run on every page WITHOUT any LLM or paid API. They populate Section
04 (AI Search Visibility) even when the A5 specialist agent is skipped.

Check coverage map (matches checklists/on-page.yaml):

  ON-048  AI overview optimization        -> check_ai_overview_fitness
  ON-049  Direct answer optimization      -> check_direct_answer_paragraph
  ON-100  Structured content analysis     -> check_structured_content
  ON-101  Table optimization for snippets -> check_table_snippet_fitness
  ON-102  List optimization for snippets  -> check_list_snippet_fitness
  ON-103  Content extraction for AI       -> check_extraction_fitness
  ON-104  LLM readability                 -> check_llm_readability
  ON-105  Generative search optimization  -> check_generative_search_fitness
  ON-107  Semantic HTML structure         -> check_semantic_html_structure

Site-wide entry points are in `audit_engine.analyzers.geo_ai` (llms.txt,
AI-bot robots directives). Per-page checks live here.
"""

from __future__ import annotations

import re
from typing import Iterable

from audit_engine.analyzers.common import Verdict, status_from_score
from audit_engine.parsers.html import ParsedHTML


# ----- Shared helpers --------------------------------------------------------

_QUESTION_LEADERS = re.compile(
    r"^\s*(what|why|how|when|where|who|which|can|does|do|is|are|should|will|would|may|could)\b",
    re.IGNORECASE,
)
_SENT_RE = re.compile(r"[.!?]+\s")
_WORD_RE = re.compile(r"[A-Za-z]+")


def _schema_types(p: ParsedHTML) -> list[str]:
    types: list[str] = []
    for block in p.schema_blocks or []:
        if not isinstance(block, dict):
            continue
        t = block.get("@type")
        if isinstance(t, list):
            types.extend(str(x) for x in t)
        elif t:
            types.append(str(t))
    return types


def _has_schema(p: ParsedHTML, name: str) -> bool:
    return any(name.lower() == t.lower() for t in _schema_types(p))


def _first_paragraph_words(p: ParsedHTML) -> int:
    return (p.paragraph_word_counts or [0])[0] if p.paragraphs else 0


# ----- ON-049 Direct answer paragraph (40-60 words near top) ---------------

def check_direct_answer_paragraph(p: ParsedHTML) -> Verdict:
    """ON-049 - First paragraph should answer the page's central question in
    ~40-80 words. Too short = LLM has nothing to lift. Too long = answer is
    buried inside narrative.
    """
    if not p.paragraphs:
        return Verdict(
            "fail", 2.0, "major", 0.9,
            {"reason": "no <p> paragraphs found"},
            "Add a direct-answer paragraph at the top of the page (40-80 words) that answers the page's core question in plain English.",
        )
    first_words = p.paragraph_word_counts[0] if p.paragraph_word_counts else 0
    excerpt = (p.paragraphs[0] or "")[:240]
    if 40 <= first_words <= 80:
        return Verdict(
            "pass", 10.0, "info", 0.85,
            {"first_paragraph_words": first_words, "excerpt": excerpt},
        )
    if 25 <= first_words < 40 or 80 < first_words <= 110:
        return Verdict(
            "warn", 6.0, "minor", 0.85,
            {"first_paragraph_words": first_words, "excerpt": excerpt},
            f"First paragraph is {first_words} words. AI Overviews lift cleanest passages of 40-80 words. Tighten or expand it.",
        )
    if first_words < 25:
        return Verdict(
            "fail", 3.0, "major", 0.9,
            {"first_paragraph_words": first_words, "excerpt": excerpt},
            f"First paragraph is only {first_words} words. Rewrite the opening as a 40-80 word direct-answer paragraph that names the entity, the offer, and the location.",
        )
    return Verdict(
        "warn", 5.0, "minor", 0.85,
        {"first_paragraph_words": first_words, "excerpt": excerpt},
        f"First paragraph is {first_words} words - too long to be cited verbatim. Move supporting detail down; lead with a 40-80 word answer.",
    )


# ----- ON-048 AI Overview fitness (question H2s + answer-bearing intro) ----

def check_ai_overview_fitness(p: ParsedHTML) -> Verdict:
    """ON-048 - AI Overview fitness rolls up: question-style H2/H3 ratio,
    first-paragraph length, presence of a named entity (title/H1 overlap).
    """
    headings = [h.text for h in p.headings if h.level in (2, 3)]
    questions = sum(
        1 for h in headings
        if h.endswith("?") or _QUESTION_LEADERS.match(h)
    )
    question_ratio = (questions / len(headings)) if headings else 0.0
    first_words = _first_paragraph_words(p)
    intro_ok = 40 <= first_words <= 80
    has_h1 = bool(p.h1s)
    has_title = bool(p.title)
    # Score components: heading ratio (0-4), intro ok (0-3), title+h1 (0-3)
    sub = 0.0
    sub += min(4.0, question_ratio * 12.0)
    sub += 3.0 if intro_ok else (1.5 if first_words >= 20 else 0.0)
    sub += (1.5 if has_h1 else 0.0) + (1.5 if has_title else 0.0)
    score = round(min(10.0, sub), 1)
    ev = {
        "heading_count": len(headings),
        "question_headings": questions,
        "question_ratio": round(question_ratio, 2),
        "first_paragraph_words": first_words,
        "intro_ok": intro_ok,
        "has_h1": has_h1,
        "has_title": has_title,
    }
    if score >= 8:
        return Verdict("pass", score, "info", 0.85, ev)
    rem = (
        "Reframe at least 2-3 H2/H3 as questions, then ensure the first paragraph (40-80 words) "
        "answers the page's central query in plain English. AI Overviews favour pages that pair "
        "explicit questions with self-contained answers."
    )
    if score >= 5:
        return Verdict("warn", score, "minor", 0.8, ev, rem)
    return Verdict("fail", score, "major", 0.85, ev, rem)


# ----- ON-100 Structured content analysis ----------------------------------

def check_structured_content(p: ParsedHTML) -> Verdict:
    """ON-100 - Pages cited by AI tend to mix paragraphs + lists + tables +
    semantic sections. Flat walls of <p> rarely get cited as passages.
    """
    list_count = (p.list_count or 0) + (p.ordered_list_count or 0)
    table_count = p.table_count or 0
    sem = p.semantic_tag_counts or {}
    has_article_or_section = (sem.get("article", 0) + sem.get("section", 0)) > 0
    has_figure = sem.get("figure", 0) > 0
    word_count = p.word_count or 0

    score = 0.0
    score += min(3.5, list_count * 1.0)
    score += min(2.5, table_count * 1.5)
    score += 2.5 if has_article_or_section else 0.0
    score += 1.5 if has_figure else 0.0
    score = min(10.0, score)
    ev = {
        "lists": list_count,
        "tables": table_count,
        "article_or_section": has_article_or_section,
        "figure_blocks": sem.get("figure", 0),
        "word_count": word_count,
    }
    if word_count < 200:
        return Verdict("n_a", 0.0, "info", 0.7, {**ev, "reason": "too thin to evaluate"})
    if score >= 7:
        return Verdict("pass", round(score, 1), "info", 0.8, ev)
    rem = (
        "Add at least one bullet list, one comparison table, and wrap key chunks in <article>/<section>. "
        "AI tools quote bounded, well-structured passages more often than wall-of-text paragraphs."
    )
    return Verdict(
        status_from_score(score), round(score, 1),
        "minor" if score >= 4 else "major", 0.8,
        ev, rem,
    )


# ----- ON-101 Table optimization for snippets ------------------------------

def check_table_snippet_fitness(p: ParsedHTML) -> Verdict:
    """ON-101 - tables only earn snippet/AI citations when they use proper
    <table>/<th>. Tables faked from <div>s do not. Parser only counts real
    <table> tags, so any positive count is a win.
    """
    table_count = p.table_count or 0
    if table_count == 0:
        return Verdict(
            "n_a", 0.0, "info", 0.6,
            {"table_count": 0},
            "Comparison tables (pricing, feature matrix, service tiers) earn featured-snippet and AI Overview citations. Add one if the page topic supports it.",
        )
    # We have at least one. Heuristic: any real <table> with at least 2 rows
    # is good. Parser doesn't expose <th> counts directly, so we don't
    # penalize. A future enhancement can detect <th>.
    return Verdict(
        "pass", min(10.0, 6.0 + 1.5 * table_count), "info", 0.75,
        {"table_count": table_count},
    )


# ----- ON-102 List optimization for snippets -------------------------------

def check_list_snippet_fitness(p: ParsedHTML) -> Verdict:
    """ON-102 - bulleted / numbered lists are the most-cited passage type
    after direct-answer paragraphs. Pages with 2+ semantic lists are favored.
    """
    total = (p.list_count or 0) + (p.ordered_list_count or 0)
    word_count = p.word_count or 0
    if word_count < 200:
        return Verdict("n_a", 0.0, "info", 0.7, {"word_count": word_count, "lists": total})
    if total >= 3:
        return Verdict("pass", 10.0, "info", 0.8, {"lists": total})
    if total == 2:
        return Verdict("pass", 8.0, "info", 0.8, {"lists": total})
    if total == 1:
        return Verdict(
            "warn", 6.0, "minor", 0.8,
            {"lists": total},
            "Only one semantic list on this page. Add a second bulleted or numbered list with 4-7 items - lists are the most-quoted passage type in AI Overviews.",
        )
    return Verdict(
        "warn", 3.0, "major", 0.85,
        {"lists": 0},
        "Page contains zero semantic <ul>/<ol> lists. Reformat at least one paragraph as a bulleted list (steps, features, qualifications, FAQs).",
    )


# ----- ON-103 Content extraction fitness for AI ----------------------------

def check_extraction_fitness(p: ParsedHTML) -> Verdict:
    """ON-103 - Can a crawler extract clean, fact-bearing prose from this
    page? Penalize: tiny body, no schema, body-text-to-HTML ratio low.
    """
    word_count = p.word_count or 0
    if word_count < 100:
        return Verdict(
            "fail", 2.0, "major", 0.85,
            {"word_count": word_count},
            f"Only {word_count} words on the page. AI tools require enough extractable prose to construct a citation. Add at least 300 words of substantive content.",
        )
    html_bytes = max(p.raw_html_bytes or 1, 1)
    text_bytes = len((p.body_text or "").encode("utf-8"))
    text_ratio = min(1.0, text_bytes / html_bytes)
    has_schema = len(_schema_types(p)) > 0
    score = 0.0
    if word_count >= 600:
        score += 4.0
    elif word_count >= 300:
        score += 3.0
    else:
        score += 1.5
    score += 3.0 if text_ratio >= 0.15 else (1.5 if text_ratio >= 0.08 else 0.0)
    score += 3.0 if has_schema else 0.0
    score = min(10.0, score)
    ev = {
        "word_count": word_count,
        "text_to_html_ratio": round(text_ratio, 3),
        "has_schema": has_schema,
        "schema_types": _schema_types(p)[:8],
    }
    if score >= 8:
        return Verdict("pass", round(score, 1), "info", 0.8, ev)
    rem = (
        "Improve extraction fitness: ensure body copy renders in initial HTML (not JS-injected), "
        "raise text-to-HTML ratio above 15%, and add JSON-LD schema (WebPage + Article or LocalBusiness)."
    )
    return Verdict(
        status_from_score(score), round(score, 1),
        "major" if score < 5 else "minor", 0.8,
        ev, rem,
    )


# ----- ON-104 LLM readability ---------------------------------------------

def check_llm_readability(p: ParsedHTML) -> Verdict:
    """ON-104 - Short sentences (12-22 words avg) read cleanly in AI
    summaries. Walls of 35+ word sentences truncate badly.
    """
    text = (p.body_text or "")[:25000]
    if not text or len(text) < 200:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "too little text"})
    sentences = [s for s in _SENT_RE.split(text) if s.strip()]
    if len(sentences) < 5:
        return Verdict("n_a", 0.0, "info", 0.7, {"sentence_count": len(sentences)})
    word_counts = [len(_WORD_RE.findall(s)) for s in sentences]
    avg = sum(word_counts) / len(word_counts)
    long_share = sum(1 for w in word_counts if w >= 35) / len(word_counts)
    ev = {
        "avg_sentence_words": round(avg, 1),
        "long_sentence_share": round(long_share, 2),
        "sentence_count": len(sentences),
    }
    if 12 <= avg <= 22 and long_share < 0.1:
        return Verdict("pass", 10.0, "info", 0.85, ev)
    if avg < 12:
        return Verdict(
            "warn", 7.0, "minor", 0.8, ev,
            f"Avg sentence is {avg:.1f} words - sentences may be too choppy for AI summary lifting. Aim for 12-22.",
        )
    if avg <= 28 and long_share < 0.2:
        return Verdict(
            "warn", 6.0, "minor", 0.8, ev,
            f"Avg sentence is {avg:.1f} words ({long_share:.0%} above 35 words). Break long sentences to improve LLM citation quality.",
        )
    return Verdict(
        "fail", 3.0, "major", 0.85, ev,
        f"Sentences are too long (avg {avg:.1f} words; {long_share:.0%} above 35). LLMs truncate or paraphrase poorly. Rewrite to 12-22 word average.",
    )


# ----- ON-105 Generative search fitness (passage citability) ---------------

def check_generative_search_fitness(p: ParsedHTML) -> Verdict:
    """ON-105 - Self-contained passages: each H2 section should make sense
    lifted out of context. Heuristic: H2 count, avg words per section, lists
    or tables inside the section, FAQ schema, and FAQ-style Q-headings.
    """
    h2 = [h.text for h in p.headings if h.level == 2]
    word_count = p.word_count or 0
    has_faq_schema = _has_schema(p, "FAQPage") or _has_schema(p, "Question")
    has_howto_schema = _has_schema(p, "HowTo")
    has_speakable = _has_schema(p, "SpeakableSpecification")
    question_h2s = sum(
        1 for h in h2
        if h.endswith("?") or _QUESTION_LEADERS.match(h)
    )
    score = 0.0
    if h2:
        avg_words_per_section = word_count / max(len(h2), 1)
        if 80 <= avg_words_per_section <= 250:
            score += 3.5
        elif 40 <= avg_words_per_section < 80 or 250 < avg_words_per_section <= 400:
            score += 2.0
    score += min(2.5, question_h2s * 1.0)
    score += 2.5 if has_faq_schema else 0.0
    score += 1.0 if has_howto_schema else 0.0
    score += 1.0 if has_speakable else 0.0
    score = min(10.0, score)
    ev = {
        "h2_count": len(h2),
        "question_h2s": question_h2s,
        "word_count": word_count,
        "faq_schema": has_faq_schema,
        "howto_schema": has_howto_schema,
        "speakable_schema": has_speakable,
    }
    if word_count < 200:
        return Verdict("n_a", 0.0, "info", 0.7, {**ev, "reason": "too thin"})
    if score >= 7:
        return Verdict("pass", round(score, 1), "info", 0.8, ev)
    rem = (
        "Boost passage citability: add 1-2 question-style H2s, add FAQ schema with 4-6 Q&A pairs, "
        "and keep each section 80-250 words so it stands alone when an AI tool quotes it."
    )
    return Verdict(
        status_from_score(score), round(score, 1),
        "major" if score < 4 else "minor", 0.8,
        ev, rem,
    )


# ----- ON-107 Semantic HTML structure --------------------------------------

def check_semantic_html_structure(p: ParsedHTML) -> Verdict:
    """ON-107 - Modern AI crawlers prefer pages that use semantic landmarks
    (<main>, <article>, <section>, <nav>, <header>, <footer>). Pages built
    from <div>s confuse passage extraction.
    """
    sem = p.semantic_tag_counts or {}
    required = ("main", "header", "footer", "nav")
    boosters = ("article", "section", "figure", "aside")
    has_required = [name for name in required if sem.get(name, 0) > 0]
    has_boosters = [name for name in boosters if sem.get(name, 0) > 0]
    score = (len(has_required) * 1.7) + (len(has_boosters) * 0.7)
    score = min(10.0, score)
    ev = {
        "semantic_landmarks_present": has_required,
        "semantic_boosters_present": has_boosters,
        "tag_counts": sem,
    }
    if score >= 8:
        return Verdict("pass", round(score, 1), "info", 0.85, ev)
    missing = sorted(set(required) - set(has_required))
    rem = (
        f"Add semantic landmarks: {missing or 'none'} are absent. Wrap content in <main>, "
        f"<article>, and <section> so AI tools can identify primary content vs. boilerplate."
    )
    return Verdict(
        status_from_score(score), round(score, 1),
        "minor" if score >= 5 else "major", 0.8,
        ev, rem,
    )


# ----- Aliases that match the analyzer paths declared in checklists/*.yaml -

# checklists/on-page.yaml references:
#   audit_engine.analyzers.ai_search.overview         (ON-048)
#   audit_engine.analyzers.ai_search.direct_answer    (ON-049)
#   audit_engine.analyzers.ai_search.extraction       (ON-103)
#   audit_engine.analyzers.ai_search.llm_readability  (ON-104)
#   audit_engine.analyzers.ai_search.generative       (ON-105)
#   audit_engine.analyzers.ai_search.crawl_readiness  (ON-106) - in geo_ai
#   audit_engine.analyzers.ai_search.semantic_html    (ON-107)
overview = check_ai_overview_fitness
direct_answer = check_direct_answer_paragraph
extraction = check_extraction_fitness
llm_readability = check_llm_readability
generative = check_generative_search_fitness
semantic_html = check_semantic_html_structure

# Re-export the site-wide crawl-readiness analyzer that lives in geo_ai so
# the YAML analyzer path resolves correctly.
try:
    from audit_engine.analyzers.geo_ai import (
        check_ai_crawler_directives as crawl_readiness,
    )
except ImportError:  # pragma: no cover - circular import safety
    crawl_readiness = None  # type: ignore[assignment]


# ----- Aggregator ----------------------------------------------------------

def iter_per_page_ai_search(p: ParsedHTML) -> Iterable[tuple[str, str, Verdict]]:
    """Yield (check_id, owner, verdict) for every AI-search per-page check.

    Owner is always A5 (GEO/AI Search analyst). These run for EVERY parsed
    page so the AI-search section of the report is never empty.
    """
    yield ("ON-049", "A5", check_direct_answer_paragraph(p))
    yield ("ON-048", "A5", check_ai_overview_fitness(p))
    yield ("ON-100", "A5", check_structured_content(p))
    yield ("ON-101", "A5", check_table_snippet_fitness(p))
    yield ("ON-102", "A5", check_list_snippet_fitness(p))
    yield ("ON-103", "A5", check_extraction_fitness(p))
    yield ("ON-104", "A5", check_llm_readability(p))
    yield ("ON-105", "A5", check_generative_search_fitness(p))
    yield ("ON-107", "A5", check_semantic_html_structure(p))
