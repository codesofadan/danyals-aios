"""Static lint for local-SEO red flags - the over-optimisation and thin-content pre-gate.

Ported from ``seo-content-os/scripts/compliance_lint.py`` (P1B).

Surfaces the patterns that draw a manual action or a scaled-content demotion, so a
human writes something better. It never rewrites and never scores AI-detection
(Law 8).

The checks, grouped by what they are actually defending against:

  THIN / SCALED CONTENT
    * ``THIN_SECTION`` - an H2 block under 40 words. A page made of stubs is the
      scaled-low-value-content signature even when the total word count looks fine.

  OVER-OPTIMISATION (the doorway / keyword-stuffing family)
    * ``KEYWORD_STUFFING`` - phrase density over the 2.5% ceiling, measured as page
      COVERAGE by the ported density module rather than a raw tally.
    * ``OVER_EXACT_HEADING`` - the same exact-match phrase in more than two headings.
      Three headings all containing "roof repair austin" is a near-doorway signal
      regardless of how good the prose between them is.

  STRUCTURE
    * ``MISSING_H1`` / ``MULTIPLE_H1`` / ``DUPLICATE_HEADING``
    * ``MISSING_META_TITLE`` / ``MISSING_META_DESC``, plus length bands (G6).

  NAP CONSISTENCY (G11 / E2) - the sharpest check here
    * ``SCHEMA_NAP_MISMATCH`` - a NAP string in the schema that is not BYTE-IDENTICAL
      in the visible copy. Local ranking depends on the same name, address and phone
      appearing consistently, and schema that disagrees with the page is worse than
      absent schema: it asserts a second, competing identity for the business.
    * ``SCHEMA_NAP_FORMAT`` - a telephone whose DIGITS match but whose formatting
      differs. Deliberately a WARN, not an ERROR: "(555) 123-4567" versus
      "+1-555-123-4567" is a display choice, not a different business, and treating it
      as a hard failure would train operators to ignore the check.

PORT CHANGE worth naming: ``check_schema_nap`` originally opened a schema.json from
disk. This takes ALREADY-PARSED schema data, because the ports are pure and because in
this platform the JSON-LD is generated in-process by ``content_schema.build_json_ld``
and never round-trips through a file. Everything else is carried over verbatim.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.services.content_lint.keywords import MAX_DENSITY, analyse_density
from app.services.content_lint.schema import walk_nodes

EM_DASH = "—"

MIN_SECTION_WORDS = 40
META_TITLE_MIN, META_TITLE_MAX = 50, 60
META_DESC_MIN, META_DESC_MAX = 150, 160

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_NON_DIGIT_RE = re.compile(r"\D")

_NAP_ADDRESS_KEYS = ("streetAddress", "addressLocality", "addressRegion", "postalCode")


@dataclass(frozen=True)
class ComplianceIssue:
    severity: str  # "ERROR" | "WARN"
    code: str
    line: int      # 0 = whole document
    message: str


@dataclass(frozen=True)
class ComplianceReport:
    issues: tuple[ComplianceIssue, ...] = ()

    @property
    def errors(self) -> tuple[ComplianceIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "ERROR")

    @property
    def warnings(self) -> tuple[ComplianceIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "WARN")

    @property
    def passed(self) -> bool:
        """ERRORs fail the gate; WARNs are advisory."""
        return not self.errors


def find_headings(lines: Sequence[str]) -> list[tuple[int, str, int]]:
    """``(level, text, lineno)`` per ATX heading, skipping fenced code."""
    heads: list[tuple[int, str, int]] = []
    in_fence = False
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING_RE.match(line)
        if m:
            heads.append((len(m.group(1)), m.group(2).strip(), i))
    return heads


def _check_headings(lines: Sequence[str], out: list[ComplianceIssue]) -> list[tuple[int, str, int]]:
    heads = find_headings(lines)
    h1s = [h for h in heads if h[0] == 1]
    if not h1s:
        out.append(ComplianceIssue("ERROR", "MISSING_H1", 0, "no H1 (# ...) found"))
    elif len(h1s) > 1:
        for _lvl, text, line in h1s[1:]:
            out.append(ComplianceIssue("ERROR", "MULTIPLE_H1", line,
                                       f"extra H1: {text!r} (page should have exactly one)"))
    seen: dict[str, int] = {}
    for _lvl, text, line in heads:
        key = text.lower()
        if key in seen:
            out.append(ComplianceIssue("WARN", "DUPLICATE_HEADING", line,
                                       f"heading {text!r} repeats (first at line {seen[key]})"))
        else:
            seen[key] = line
    return heads


def extract_meta_values(text: str) -> tuple[str | None, str | None]:
    """Meta title and description from front-matter or inline lines. First match wins."""
    title: str | None = None
    desc: str | None = None
    for line in text.splitlines():
        if title is None:
            m = re.match(r"\s*(?:meta[\s_-]*)?title\s*[:=]\s*(.+?)\s*$", line, re.IGNORECASE)
            if m:
                title = m.group(1).strip().strip('"').strip("'")
        if desc is None:
            m = re.match(r"\s*(?:meta[\s_-]*)?desc(?:ription)?\s*[:=]\s*(.+?)\s*$", line, re.IGNORECASE)
            if m:
                desc = m.group(1).strip().strip('"').strip("'")
    return title, desc


def _check_meta(text: str, out: list[ComplianceIssue]) -> None:
    lower = text.lower()
    has_title = bool(re.search(r"meta[\s_-]*title\s*[:=]", lower)) or bool(
        re.search(r"^\s*title\s*:", lower, re.MULTILINE))
    has_desc = bool(re.search(r"meta[\s_-]*desc(ription)?\s*[:=]", lower)) or bool(
        re.search(r"^\s*description\s*:", lower, re.MULTILINE))
    if not has_title:
        out.append(ComplianceIssue("ERROR", "MISSING_META_TITLE", 0,
                                   "no meta title line/front-matter key found"))
    if not has_desc:
        out.append(ComplianceIssue("ERROR", "MISSING_META_DESC", 0,
                                   "no meta description line/front-matter key found"))


def _check_meta_length(text: str, out: list[ComplianceIssue]) -> None:
    """G6: length bands. Presence is handled separately; this only fires when present."""
    title, desc = extract_meta_values(text)
    if title:
        n = len(title)
        if n < META_TITLE_MIN or n > META_TITLE_MAX:
            out.append(ComplianceIssue("WARN", "META_TITLE_LENGTH", 0,
                                       f"meta title is {n} chars (target {META_TITLE_MIN}-{META_TITLE_MAX})"))
    if desc:
        n = len(desc)
        if n < META_DESC_MIN or n > META_DESC_MAX:
            out.append(ComplianceIssue("WARN", "META_DESC_LENGTH", 0,
                                       f"meta description is {n} chars (target {META_DESC_MIN}-{META_DESC_MAX})"))


def _check_thin_sections(
    lines: Sequence[str], heads: list[tuple[int, str, int]], out: list[ComplianceIssue],
    min_words: int,
) -> None:
    """An H2 block runs from its heading to the next H1/H2."""
    stops = sorted(line for lvl, _t, line in heads if lvl in (1, 2))
    for lvl, text, line in heads:
        if lvl != 2:
            continue
        next_stop = next((s for s in stops if s > line), len(lines) + 1)
        body = " ".join(lines[line:next_stop - 1])
        body = re.sub(r"^\s*[-*+#>0-9.]+\s*", " ", body)
        count = len(_WORD_RE.findall(body))
        if count < min_words:
            out.append(ComplianceIssue("WARN", "THIN_SECTION", line,
                                       f"H2 {text!r} has only {count} words (< {min_words})"))


def _check_em_dash(lines: Sequence[str], out: list[ComplianceIssue]) -> None:
    for i, line in enumerate(lines, 1):
        if EM_DASH in line:
            out.append(ComplianceIssue("ERROR", "EM_DASH", i,
                                       f"em dash (U+2014) at col {line.index(EM_DASH)} - use a hyphen"))


def _check_keyword_stuffing(
    text: str, keywords: Sequence[str], out: list[ComplianceIssue], max_density: float
) -> None:
    if not keywords:
        return
    for row in analyse_density(text, keywords, max_density=max_density).rows:
        if row.over:
            out.append(ComplianceIssue(
                "ERROR", "KEYWORD_STUFFING", 0,
                f"{row.keyword!r} density {100 * row.density:.2f}% > "
                f"{100 * max_density:.1f}% (over-optimization)",
            ))


def _check_over_exact_headings(
    heads: list[tuple[int, str, int]], keywords: Sequence[str], out: list[ComplianceIssue]
) -> None:
    if not keywords:
        return
    head_texts = [t.lower() for _lvl, t, _ln in heads]
    for keyword in keywords:
        n = sum(1 for h in head_texts if keyword.lower() in h)
        if n > 2:
            out.append(ComplianceIssue("WARN", "OVER_EXACT_HEADING", 0,
                                       f"{keyword!r} used in {n} headings (near-doorway signal)"))


def _check_target_present(text: str, keywords: Sequence[str], out: list[ComplianceIssue]) -> None:
    lower = text.lower()
    for keyword in keywords:
        if keyword.lower() not in lower:
            out.append(ComplianceIssue("WARN", "MISSING_TARGET", 0,
                                       f"target keyword {keyword!r} never appears in the draft"))


def extract_schema_nap(data: Any) -> dict[str, str]:
    """NAP strings from parsed JSON-LD: the first typed node with a name plus a
    telephone or address (that is the business node)."""
    for node in walk_nodes(data):
        name = str(node.get("name", "")).strip()
        phone = str(node.get("telephone", "")).strip()
        address = node.get("address")
        if not name or not (phone or address):
            continue
        nap: dict[str, str] = {"name": name}
        if phone:
            nap["telephone"] = phone
        if isinstance(address, list):
            address = address[0] if address else None
        if isinstance(address, dict):
            for key in _NAP_ADDRESS_KEYS:
                value = address.get(key)
                if value is not None and str(value).strip():
                    nap[key] = str(value).strip()
        return nap
    return {}


def _check_schema_nap(text: str, data: Any, out: list[ComplianceIssue]) -> None:
    """G11/E2: schema NAP must appear byte-identically in the visible copy.

    Schema that disagrees with the page is worse than absent schema - it asserts a
    second, competing identity for the same business.
    """
    nap = extract_schema_nap(data)
    if not nap:
        out.append(ComplianceIssue("WARN", "SCHEMA_NO_NAP", 0,
                                   "no LocalBusiness/Organization NAP node found in the schema"))
        return
    for label, value in nap.items():
        if not value or value in text:
            continue
        digits = _NON_DIGIT_RE.sub("", value)
        if label == "telephone" and digits and digits in _NON_DIGIT_RE.sub("", text):
            # A display-format difference, not a different business.
            out.append(ComplianceIssue(
                "WARN", "SCHEMA_NAP_FORMAT", 0,
                f"schema telephone {value!r} matches digits but is not byte-identical "
                "in the page copy",
            ))
        else:
            out.append(ComplianceIssue(
                "ERROR", "SCHEMA_NAP_MISMATCH", 0,
                f"schema {label} {value!r} is not byte-identical in the page copy (G11/E2)",
            ))


def lint_compliance(
    text: str,
    *,
    keywords: Sequence[str] = (),
    min_section_words: int = MIN_SECTION_WORDS,
    max_density: float = MAX_DENSITY,
    schema: Any | None = None,
) -> ComplianceReport:
    """Lint a draft. ``schema`` is PARSED JSON-LD, not a path.

    Total: never raises, never does I/O.
    """
    lines = text.splitlines()
    out: list[ComplianceIssue] = []
    heads = _check_headings(lines, out)
    _check_meta(text, out)
    _check_meta_length(text, out)
    _check_thin_sections(lines, heads, out, min_section_words)
    _check_em_dash(lines, out)
    _check_keyword_stuffing(text, keywords, out, max_density)
    _check_over_exact_headings(heads, keywords, out)
    _check_target_present(text, keywords, out)
    if schema is not None:
        _check_schema_nap(text, schema, out)
    return ComplianceReport(issues=tuple(out))
