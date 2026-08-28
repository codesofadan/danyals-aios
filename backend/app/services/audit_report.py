"""The client-facing audit report: a Python template, filled from measured rows.

WHY A TEMPLATE AND NOT A MODEL. Everything on these pages is arithmetic over rows
the audit already produced, so a model has nothing to add and two things to cost:
money per report, and the standing risk of a fabricated number in a document a
client acts on. The layout is code, the content is a query, and the same input
renders the same bytes every time. Regenerating a report a year from now produces
the report that was sent.

CHARTS ARE INLINE SVG, generated here. No chart library, no JavaScript, no
external asset, no font host - the document is self-contained, so it renders the
same in a browser, in an email client, and through a print-to-PDF pass, and it
keeps working with no network at all.

WHAT IT WILL NOT DO. It will not print a score without the number of checks
behind it, it will not render an unmeasured dimension as zero, and it will not
put a calendar date on a roadmap phase. Those are the same three rules the API
and the workbook hold, enforced in a third place because this is the artefact a
client actually reads.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db.database import privileged_connection
from app.services import report_pdf
from app.services.audit_artifacts import REPORT_PDF_NAME
from app.services.branding import Brand, brand

# --------------------------------------------------------------------------- #
# Palette - the platform's own tokens, inlined because the document is standalone
# --------------------------------------------------------------------------- #
INK = "#211B29"
BODY = "#4E4256"
MUTED = "#7A6B7F"
MUTED_2 = "#A497A8"
VIOLET = "#432B52"
VIOLET_2 = "#5B3A6E"
CREAM = "#FAF6EE"
CARD = "#FFFFFF"
LINE = "#E4DEE6"
OK = "#2F8A73"
WARN = "#A96913"
CRIT = "#B74355"

SEVERITY_COLOR = {"critical": CRIT, "major": WARN, "minor": "#6E7BA6", "info": MUTED_2}
SEVERITY_ORDER = ("critical", "major", "minor", "info")


def esc(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


#: Em dash, en dash, and their HTML entities. Banned from every client-facing
#: document by house style, and the ban has to be ENFORCED at the boundary rather
#: than remembered at each of the hundred places that write prose: most of the
#: text in this report is not written here at all - remediation strings and check
#: names come from the engine, and a dash typed into one of those would sail past
#: any amount of care taken in this file.
_DASHES = {
    "\u2014": "-", "\u2013": "-",
    "&mdash;": "-", "&ndash;": "-", "&#8212;": "-", "&#8211;": "-",
}


def no_dashes(doc: str) -> str:
    """Replace every em/en dash with a hyphen. Applied once, to the finished
    document, so no writer in this module or upstream of it has to remember."""
    for bad, good in _DASHES.items():
        doc = doc.replace(bad, good)
    return doc


def num(value: Any) -> float | None:
    """Coerce a stored score to a float.

    Postgres `numeric` arrives as `decimal.Decimal`, which does not mix with the
    float arithmetic every chart here does. Coercing at the boundary keeps the
    chart functions pure floats rather than sprinkling casts through them.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def tone(score: float | None) -> str:
    if score is None:
        return MUTED_2
    if score >= 80:
        return OK
    if score >= 65:
        return WARN
    return CRIT


# --------------------------------------------------------------------------- #
# Charts - pure SVG, no dependencies
# --------------------------------------------------------------------------- #

def donut(score: float | None, *, size: int = 132, label: str = "") -> str:
    """The headline score as a ring.

    An unmeasured score draws the track and no arc, with the words in the middle -
    a full grey ring would read as a complete measurement of zero.
    """
    score = num(score)
    r, cx = size / 2 - 12, size / 2
    circ = 2 * 3.141592653589793 * r
    colour = tone(score)
    if score is None:
        arc = f'<circle cx="{cx}" cy="{cx}" r="{r:.1f}" fill="none" stroke="{LINE}" stroke-width="12"/>'
        middle = f'<text x="{cx}" y="{cx + 2}" text-anchor="middle" font-size="13" font-weight="700" fill="{MUTED}">not</text>' \
                 f'<text x="{cx}" y="{cx + 18}" text-anchor="middle" font-size="13" font-weight="700" fill="{MUTED}">measured</text>'
    else:
        dash = circ * max(0.0, min(1.0, score / 100.0))
        arc = (
            f'<circle cx="{cx}" cy="{cx}" r="{r:.1f}" fill="none" stroke="{LINE}" stroke-width="12"/>'
            f'<circle cx="{cx}" cy="{cx}" r="{r:.1f}" fill="none" stroke="{colour}" stroke-width="12"'
            f' stroke-linecap="round" stroke-dasharray="{dash:.1f} {circ - dash:.1f}"'
            f' transform="rotate(-90 {cx} {cx})"/>'
        )
        middle = (
            f'<text x="{cx}" y="{cx + 9}" text-anchor="middle" font-size="30"'
            f' font-weight="800" fill="{colour}">{score:g}</text>'
        )
    # The caption sits BELOW the ring with real clearance. It used to be drawn at
    # `size - 1` inside a `size + 6` box - four pixels under a stroke that is
    # twelve wide - so "SITE SCORE" read as part of the ring rather than a label
    # for it, and the whole cover looked crowded at the one place a reader looks
    # first. Tracking it out is what makes a short all-caps caption legible at
    # 10px; the extra box height is what stops it touching anything.
    gap = 18 if label else 6
    cap = (
        f'<text x="{cx}" y="{size + 10}" text-anchor="middle" font-size="9.5"'
        f' font-weight="700" letter-spacing="1.1" fill="{MUTED}">{esc(label)}</text>'
        if label else ""
    )
    return (
        f'<svg width="{size}" height="{size + gap}" viewBox="0 0 {size} {size + gap}"'
        f' xmlns="http://www.w3.org/2000/svg" role="img">{arc}{middle}{cap}</svg>'
    )


def bars(rows: Sequence[tuple[str, float | None, str]], *, width: int = 640,
         row_h: int = 30, label_w: int = 148) -> str:
    """Horizontal bars, one per pillar, each captioned with its own coverage.

    The caption is not decoration: a bar at 97 over a quarter of the checklist and
    a bar at 97 over all of them are different claims, and the chart has to carry
    the difference or it becomes the misleading half of the report.
    """
    if not rows:
        return ""
    h = row_h * len(rows) + 10
    track = width - label_w - 92
    out = [
        f'<svg width="{width}" height="{h}" viewBox="0 0 {width} {h}"'
        f' xmlns="http://www.w3.org/2000/svg" role="img">'
    ]
    for i, (name, raw_score, caption) in enumerate(rows):
        score = num(raw_score)
        y = i * row_h + 8
        out.append(
            f'<text x="0" y="{y + 12}" font-size="11.5" font-weight="700" fill="{INK}">{esc(name)}</text>'
        )
        out.append(
            f'<rect x="{label_w}" y="{y + 2}" width="{track}" height="13" rx="6.5" fill="{LINE}"/>'
        )
        if score is None:
            out.append(
                f'<text x="{label_w + 6}" y="{y + 12.5}" font-size="10" font-style="italic"'
                f' fill="{MUTED}">not measured</text>'
            )
        else:
            w = max(3.0, track * max(0.0, min(1.0, score / 100.0)))
            out.append(
                f'<rect x="{label_w}" y="{y + 2}" width="{w:.1f}" height="13" rx="6.5"'
                f' fill="{tone(score)}"/>'
            )
            out.append(
                f'<text x="{label_w + track + 8}" y="{y + 13}" font-size="12"'
                f' font-weight="800" fill="{tone(score)}">{score:g}</text>'
            )
        out.append(
            f'<text x="{label_w}" y="{y + 26}" font-size="9.5" fill="{MUTED}">{esc(caption)}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def severity_bar(counts: dict[str, int], *, width: int = 640, height: int = 34) -> str:
    """One stacked bar: how the issues divide by severity."""
    total = sum(counts.get(s, 0) for s in SEVERITY_ORDER)
    if total <= 0:
        return ""
    out = [
        f'<svg width="{width}" height="{height + 20}" viewBox="0 0 {width} {height + 20}"'
        f' xmlns="http://www.w3.org/2000/svg" role="img">'
    ]
    x = 0.0
    for sev in SEVERITY_ORDER:
        n = counts.get(sev, 0)
        if not n:
            continue
        w = width * (n / total)
        out.append(
            f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{height}" fill="{SEVERITY_COLOR[sev]}"/>'
        )
        if w > 54:
            out.append(
                f'<text x="{x + w / 2:.1f}" y="{height / 2 + 4}" text-anchor="middle"'
                f' font-size="11" font-weight="800" fill="#fff">{n:,}</text>'
            )
        x += w
    lx = 0
    for sev in SEVERITY_ORDER:
        n = counts.get(sev, 0)
        if not n:
            continue
        out.append(f'<rect x="{lx}" y="{height + 8}" width="9" height="9" rx="2" fill="{SEVERITY_COLOR[sev]}"/>')
        out.append(
            f'<text x="{lx + 13}" y="{height + 16}" font-size="10" fill="{BODY}">'
            f'{sev.capitalize()} {n:,}</text>'
        )
        lx += 34 + 7 * len(f"{sev} {n:,}")
    out.append("</svg>")
    return "".join(out)


def coverage_bar(rows: Sequence[tuple[str, int, int]], *, width: int = 640,
                 row_h: int = 26, label_w: int = 148) -> str:
    """Per pillar: how much of the checklist actually ran.

    The scores answer "how healthy"; this answers "how much do we know", and they
    are not the same question. A pillar at 92 over 11 of 80 checks and a pillar at
    92 over 80 of 80 look identical on a score chart and mean opposite things, so
    the denominator gets its own chart rather than living only in a caption.
    """
    rows = [r for r in rows if r[2]]
    if not rows:
        return ""
    h = row_h * len(rows) + 8
    track = width - label_w - 96
    out = [f'<svg width="{width}" height="{h}" viewBox="0 0 {width} {h}"'
           f' xmlns="http://www.w3.org/2000/svg" role="img">']
    for i, (name, ran, applicable) in enumerate(rows):
        y = i * row_h + 6
        frac = max(0.0, min(1.0, ran / applicable)) if applicable else 0.0
        out.append(f'<text x="0" y="{y + 12}" font-size="11" font-weight="700"'
                   f' fill="{INK}">{esc(name)}</text>')
        out.append(f'<rect x="{label_w}" y="{y + 2}" width="{track}" height="12" rx="6" fill="{LINE}"/>')
        if frac > 0:
            out.append(f'<rect x="{label_w}" y="{y + 2}" width="{max(3.0, track * frac):.1f}"'
                       f' height="12" rx="6" fill="{VIOLET_2}"/>')
        out.append(f'<text x="{label_w + track + 8}" y="{y + 12}" font-size="10.5"'
                   f' font-weight="700" fill="{BODY}">{ran} of {applicable}</text>')
    out.append("</svg>")
    return "".join(out)


def sev_split(rows: Sequence[tuple[str, dict[str, int]]], *, width: int = 640,
              row_h: int = 26, label_w: int = 148) -> str:
    """Per pillar: the severity mix, scaled against the busiest pillar.

    Bars are scaled to the LARGEST pillar rather than each to its own width, so
    the lengths compare. Normalising each row to 100% would draw a pillar with
    two issues the same size as one with two hundred.
    """
    rows = [(n, c) for n, c in rows if sum(c.values())]
    if not rows:
        return ""
    peak = max(sum(c.values()) for _, c in rows)
    h = row_h * len(rows) + 8
    track = width - label_w - 78
    out = [f'<svg width="{width}" height="{h}" viewBox="0 0 {width} {h}"'
           f' xmlns="http://www.w3.org/2000/svg" role="img">']
    for i, (name, counts) in enumerate(rows):
        y = i * row_h + 6
        total = sum(counts.values())
        full = track * (total / peak)
        out.append(f'<text x="0" y="{y + 12}" font-size="11" font-weight="700"'
                   f' fill="{INK}">{esc(name)}</text>')
        x = float(label_w)
        for sev in SEVERITY_ORDER:
            n = counts.get(sev, 0)
            if not n:
                continue
            w = full * (n / total)
            out.append(f'<rect x="{x:.1f}" y="{y + 2}" width="{max(1.0, w):.1f}" height="12"'
                       f' fill="{SEVERITY_COLOR[sev]}"/>')
            x += w
        out.append(f'<text x="{label_w + full + 8:.1f}" y="{y + 12}" font-size="10.5"'
                   f' font-weight="700" fill="{BODY}">{total:,}</text>')
    out.append("</svg>")
    return "".join(out)


def phase_bars(rows: Sequence[tuple[str, str, int]], *, width: int = 640,
               col_w: int = 128, height: int = 132) -> str:
    """The plan as columns: how much work sits in each window.

    Deliberately columns and not a timeline. A timeline implies dates, and these
    phases are relative windows of work - the same rule the roadmap table holds.
    """
    rows = [r for r in rows if r[2]]
    if not rows:
        return ""
    peak = max(n for _, _, n in rows)
    base, top = height - 30, 14
    out = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}"'
           f' xmlns="http://www.w3.org/2000/svg" role="img">']
    out.append(f'<line x1="0" y1="{base}" x2="{min(width, col_w * len(rows))}" y2="{base}"'
               f' stroke="{LINE}" stroke-width="1"/>')
    for i, (name, window, n) in enumerate(rows):
        cx = i * col_w + col_w / 2
        bh = max(4.0, (base - top) * (n / peak))
        out.append(f'<rect x="{cx - 26:.1f}" y="{base - bh:.1f}" width="52" height="{bh:.1f}"'
                   f' rx="5" fill="{VIOLET_2}"/>')
        out.append(f'<text x="{cx:.1f}" y="{base - bh - 5:.1f}" text-anchor="middle"'
                   f' font-size="12" font-weight="800" fill="{INK}">{n:,}</text>')
        out.append(f'<text x="{cx:.1f}" y="{base + 14}" text-anchor="middle" font-size="11"'
                   f' font-weight="700" fill="{INK}">{esc(name)}</text>')
        out.append(f'<text x="{cx:.1f}" y="{base + 26}" text-anchor="middle" font-size="9.5"'
                   f' fill="{MUTED}">{esc(window)}</text>')
    out.append("</svg>")
    return "".join(out)


def blast_bars(rows: Sequence[tuple[str, str, int]], *, width: int = 640,
               row_h: int = 22, label_w: int = 300) -> str:
    """The widest-reaching issues by occurrence count.

    This is the chart that answers "where is the leverage" - one template edit
    that clears 121 pages outranks four one-page fixes, and no score chart shows
    that.
    """
    rows = [r for r in rows if r[2] > 0]
    if not rows:
        return ""
    peak = max(n for _, _, n in rows)
    h = row_h * len(rows) + 6
    track = width - label_w - 56
    out = [f'<svg width="{width}" height="{h}" viewBox="0 0 {width} {h}"'
           f' xmlns="http://www.w3.org/2000/svg" role="img">']
    for i, (name, sev, n) in enumerate(rows):
        y = i * row_h + 5
        w = max(3.0, track * (n / peak))
        out.append(f'<text x="0" y="{y + 11}" font-size="10.5" fill="{BODY}">{esc(name[:52])}</text>')
        out.append(f'<rect x="{label_w}" y="{y + 2}" width="{w:.1f}" height="11" rx="3"'
                   f' fill="{SEVERITY_COLOR.get(sev, MUTED_2)}"/>')
        out.append(f'<text x="{label_w + w + 6:.1f}" y="{y + 11}" font-size="10"'
                   f' font-weight="700" fill="{BODY}">{n:,}</text>')
    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# The document
# --------------------------------------------------------------------------- #

REPORT_NAME = "audit-report.html"
#: Re-exported: the printed document's name lives in `audit_artifacts`, which the
#: store reads without importing this builder. Rendered from the HTML by a headless
#: browser so the page a reviewer approved and the file a client receives cannot
#: diverge; absent when no browser is installed, and the HTML is written either way.
__all__ = ["REPORT_NAME", "REPORT_PDF_NAME", "ReportInput", "build", "render"]

#: URLs listed in the appendix. Beyond this the table stops being read and starts
#: being weight; the workbook carries the complete list either way.
_MAX_PAGES_LISTED = 150

#: Print CSS lives with the document. `@page` gives the PDF pass real margins, and
#: `break-inside: avoid` keeps a finding card from splitting across a page - the
#: difference between a report and a printout.
def _css(accent: str = VIOLET) -> str:
    """The stylesheet, in the brand's accent.

    A function rather than a constant because the accent comes from the operator's
    `branding.json`, and a report that carries the platform's violet on a client's
    letterhead is the platform's report, not theirs.
    """
    return f"""
@page {{ size: A4; margin: 16mm 14mm 18mm; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: {CREAM}; color: {BODY};
  font: 13px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
.wrap {{ max-width: 900px; margin: 0 auto; padding: 28px 26px 60px; }}
h1, h2, h3 {{ color: {INK}; margin: 0; letter-spacing: -.02em; }}
h1 {{ font-size: 30px; font-weight: 800; }}
h2 {{ font-size: 19px; font-weight: 800; margin: 0 0 4px; }}
h3 {{ font-size: 14px; font-weight: 800; }}
p {{ margin: 6px 0; }}
.muted {{ color: {MUTED}; }}
.small {{ font-size: 11.5px; }}
section {{ margin: 26px 0; page-break-inside: avoid; }}
.sec-head {{ border-bottom: 2px solid {VIOLET}; padding-bottom: 7px; margin-bottom: 14px; }}
.sec-head .n {{ font-size: 10.5px; font-weight: 800; letter-spacing: .08em;
  text-transform: uppercase; color: {VIOLET_2}; }}
.cover {{ display: flex; gap: 26px; align-items: center; padding: 24px 26px;
  background: {CARD}; border: 1px solid {LINE}; border-radius: 16px; }}
.cover .meta {{ flex: 1; }}
.cover .site {{ font-size: 14px; color: {MUTED}; margin-top: 4px; word-break: break-all; }}
.kpis {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 14px; }}
.kpi {{ flex: 1; min-width: 150px; padding: 12px 14px; background: {CARD};
  border: 1px solid {LINE}; border-radius: 12px; }}
.kpi .l {{ font-size: 10px; font-weight: 800; letter-spacing: .04em;
  text-transform: uppercase; color: {MUTED}; }}
.kpi .v {{ font-size: 24px; font-weight: 800; color: {INK}; line-height: 1.1; margin-top: 3px; }}
.kpi .s {{ font-size: 10.5px; color: {MUTED}; }}
table {{ width: 100%; border-collapse: collapse; font-size: 11.5px; }}
th {{ text-align: left; font-size: 9.5px; font-weight: 800; letter-spacing: .04em;
  text-transform: uppercase; color: {MUTED}; padding: 7px 8px; border-bottom: 1.5px solid {LINE}; }}
td {{ padding: 7px 8px; border-bottom: 1px solid {LINE}; vertical-align: top; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
tr.dim td {{ color: {MUTED_2}; }}
.finding {{ border: 1px solid {LINE}; border-left: 3px solid {LINE}; border-radius: 10px;
  background: {CARD}; padding: 10px 12px; margin-bottom: 8px; page-break-inside: avoid; }}
.finding .top {{ display: flex; gap: 10px; align-items: baseline; }}
.finding .name {{ font-size: 13px; font-weight: 700; color: {INK}; flex: 1; }}
.finding .radius {{ font-size: 12px; font-weight: 800; color: {VIOLET}; white-space: nowrap; }}
.sev {{ font-size: 8.5px; font-weight: 800; letter-spacing: .05em; text-transform: uppercase;
  padding: 2px 7px; border-radius: 99px; color: #fff; }}
.finding .sub {{ font-size: 10.5px; color: {MUTED}; margin-top: 2px; }}
.finding .fix {{ font-size: 11.5px; margin-top: 7px; }}
.finding ul {{ margin: 6px 0 0; padding-left: 17px; font-size: 10.5px; color: {MUTED}; }}
.phase {{ margin-bottom: 14px; page-break-inside: avoid; }}
.phase h3 {{ display: flex; align-items: baseline; gap: 8px; }}
.phase h3 em {{ font-style: normal; font-size: 10.5px; font-weight: 600; color: {MUTED}; }}
.phase h3 b {{ margin-left: auto; font-size: 11px; color: {VIOLET}; }}
.note {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 10px;
  padding: 11px 13px; font-size: 11.5px; }}
.foot {{ margin-top: 34px; padding-top: 12px; border-top: 1px solid {LINE};
  font-size: 10px; color: {MUTED_2}; }}

/* ---- brand ---- */
.brandbar {{ display: flex; align-items: baseline; gap: 9px; padding-bottom: 12px;
  margin-bottom: 16px; border-bottom: 2px solid {accent}; }}
.brandbar .bn {{ font-size: 15px; font-weight: 800; color: {accent}; letter-spacing: -.01em; }}
.brandbar .bd {{ margin-left: auto; font-size: 10.5px; color: {MUTED}; }}
.sec-head {{ border-bottom-color: {accent}; }}
.sec-head .n {{ color: {accent}; }}
.finding .radius {{ color: {accent}; }}
.phase h3 b {{ color: {accent}; }}

/* ---- pillar deep-dive ---- */
.pillar {{ border: 1px solid {LINE}; border-radius: 13px; background: {CARD};
  padding: 14px 16px; margin-bottom: 12px; page-break-inside: avoid; }}
.pillar-h {{ display: flex; align-items: center; gap: 14px; }}
.pillar-h .t {{ flex: 1; }}
.pillar-h h3 {{ font-size: 15px; }}
.pillar-h .c {{ font-size: 11px; color: {MUTED}; margin-top: 2px; }}
.pillar-stats {{ display: flex; gap: 16px; margin-top: 2px; }}
.pillar-stats div {{ font-size: 10.5px; color: {MUTED}; }}
.pillar-stats b {{ display: block; font-size: 16px; font-weight: 800; color: {INK}; }}
.pillar table {{ margin-top: 10px; }}
.chartrow {{ display: flex; flex-wrap: wrap; gap: 22px; align-items: flex-start; }}
.chartrow > div {{ flex: 1; min-width: 280px; }}
.chartrow h3 {{ font-size: 12px; margin-bottom: 6px; }}

/* ---- print ---- */
/* Each numbered section starts a page. On screen the document reads as one
   scroll; on paper a section that begins two lines from the bottom of a sheet is
   the difference between a report and a printout. */
@media print {{
  body {{ background: {CARD}; }}
  .wrap {{ max-width: none; padding: 0; }}
  section.brk {{ page-break-before: always; }}
  .cover {{ page-break-after: always; }}
}}
"""


@dataclass(slots=True)
class ReportInput:
    """Everything the document needs. All of it already measured and stored."""
    meta: dict[str, Any]
    rollups: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    pages: list[dict[str, Any]]
    roadmap: dict[str, Any] | None = None
    roadmap_items: list[dict[str, Any]] | None = None
    coverage: dict[str, Any] | None = None
    #: How many issue cards the body carries IN FULL. Every issue beyond this is
    #: still printed, as a row in the per-pillar inventory table - so the document
    #: accounts for all of them and expands only the ones worth a card. The
    #: complaint this answers is a report that showed 25 of 365 problems the
    #: workbook listed, and read as a different audit.
    top_findings: int = 40
    #: The brand. Resolved from `branding.json` when absent.
    brand: Brand | None = None


def _sec(n: str, title: str, sub: str = "") -> str:
    return (
        f'<div class="sec-head"><div class="n">{esc(n)}</div><h2>{esc(title)}</h2>'
        + (f'<p class="muted small">{esc(sub)}</p>' if sub else "")
        + "</div>"
    )


def _score_text(r: dict[str, Any]) -> str:
    score = num(r.get("score"))
    if score is None or not r.get("checks_ran"):
        return "not measured"
    return f"{score:g}"


def _cov(r: dict[str, Any]) -> str:
    return f"ran {r.get('checks_ran', 0)} of {r.get('checks_applicable', 0)} checks"


#: Words `str.title()` and `str.capitalize()` get wrong. These reach a client
#: verbatim: "Seo Specialist" as an owner, "Ai assisted" as a reason a check did
#: not run. The same defect class as a `.capitalize()` that turned "H1" into "h1"
#: in a remediation line - a slug is not prose, and casing it as prose is a
#: rewrite, not a formatting choice.
_ACRONYMS = {
    "seo": "SEO", "ai": "AI", "dom": "DOM", "url": "URL", "urls": "URLs",
    "html": "HTML", "css": "CSS", "http": "HTTP", "https": "HTTPS", "api": "API",
    "cwv": "CWV", "lcp": "LCP", "cls": "CLS", "inp": "INP", "ttfb": "TTFB",
    "fcp": "FCP", "psi": "PSI", "gbp": "GBP", "nap": "NAP", "eeat": "E-E-A-T",
    "geo": "GEO", "faq": "FAQ", "cta": "CTA", "ctr": "CTR", "json": "JSON",
    "ld": "LD", "js": "JS", "id": "ID", "ids": "IDs", "n": "N", "a": "a",
}


def label_of(raw: Any, *, style: str = "sentence") -> str:
    """Turn a slug into a phrase without mangling the acronyms inside it.

    Two styles, because these read as different things. A REASON is a sentence
    fragment ("Needs rendered DOM"), and title-casing it - "Needs Rendered DOM" -
    reads as a proper noun it is not. A ROLE is a name ("SEO Specialist"), and
    sentence-casing it reads as a description. `lower` is for a fragment embedded
    mid-sentence, where even the first word should not be raised.
    """
    words = str(raw or "").replace("_", " ").replace("-", " ").split()
    if not words:
        return ""
    out: list[str] = []
    for i, w in enumerate(words):
        low = w.lower()
        if low in _ACRONYMS:
            out.append(_ACRONYMS[low])
            continue
        if style == "title" or (i == 0 and style == "sentence"):
            # First character only. `.capitalize()` lowercases the rest, which is
            # how a word that was already correctly cased gets destroyed.
            out.append(w[0].upper() + w[1:])
        else:
            out.append(low)
    return " ".join(out)


def _sev_of(r: dict[str, Any]) -> dict[str, int]:
    """A rollup's severity counts, coerced to plain ints.

    `severity_counts` arrives as jsonb, so its values may be strings and its keys
    may include severities this document does not render. Both are filtered here
    rather than in the chart, which has no business knowing about the database.
    """
    raw = r.get("severity_counts") or {}
    out: dict[str, int] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            key = str(k).lower()
            if key not in SEVERITY_COLOR:
                continue
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if n > 0:
                out[key] = n
    return out


def _blast(f: dict[str, Any]) -> str:
    if f.get("locus_kind") == "site":
        return "site-wide"
    n = int(f.get("instance_count") or 0)
    return "1 page" if n == 1 else f"{n:,} pages"


def render(data: ReportInput) -> str:
    """Build the whole document. Pure: same input, same bytes."""
    m = data.meta
    site = next((r for r in data.rollups if r["level"] == "site"), {})
    dims = [r for r in data.rollups if r["level"] == "dimension"]
    subs = [r for r in data.rollups if r["level"] == "subpoint"]
    issues = list(data.findings)
    sev_counts: dict[str, int] = {}
    for f in issues:
        k = (f.get("severity") or "info").lower()
        sev_counts[k] = sev_counts.get(k, 0) + 1

    o: list[str] = []
    o.append('<!doctype html><html lang="en"><head><meta charset="utf-8">')
    o.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    o.append(f'<title>SEO audit - {esc(m.get("client_name") or m.get("url", ""))}</title>')
    b = data.brand or brand()
    o.append(f"<style>{_css(b.accent)}</style></head><body><div class=\"wrap\">")

    # ---- brand bar ---------------------------------------------------------
    o.append('<div class="brandbar">')
    o.append(f'<span class="bn">{esc(b.name)}</span>')
    o.append('<span class="muted small">SEO audit</span>')
    o.append(f'<span class="bd">{esc(m.get("generated_at", ""))}</span>')
    o.append("</div>")

    # ---- cover -------------------------------------------------------------
    o.append('<div class="cover">')
    o.append(donut(num(site.get("score")) if site.get("checks_ran") else None, size=140, label="SITE SCORE"))
    o.append('<div class="meta">')
    o.append(f'<h1>{esc(m.get("client_name") or "SEO audit")}</h1>')
    o.append(f'<div class="site">{esc(m.get("url", ""))}</div>')
    o.append(
        f'<p class="muted small">{esc(m.get("tier", ""))} audit'
        f' &middot; {esc(m.get("generated_at", ""))}'
        f' &middot; {_cov(site)}</p>'
    )
    o.append("</div></div>")

    # ---- 01 executive summary ---------------------------------------------
    o.append("<section>")
    o.append(_sec("01", "Executive summary",
                  "What we measured, and what it found. Every score states the number of "
                  "checks behind it."))
    o.append('<div class="kpis">')
    for label, value, sub in (
        ("Issues to fix", f"{len(issues):,}", "distinct problems"),
        ("Occurrences", f"{sum(int(f.get('instance_count') or 0) for f in issues):,}", "across all pages"),
        ("Pages crawled", f"{site.get('pages_crawled', 0):,}", "in this run"),
        # Short enough to sit on one line beside the other three. The long form
        # wrapped, which dropped this tile's number half a line below its
        # neighbours and made the row read as broken.
        ("Critical-free pages",
         "-" if site.get("url_health_pct") is None else f"{num(site['url_health_pct']):g}%",
         "no critical issue on the page"),
    ):
        o.append(f'<div class="kpi"><div class="l">{esc(label)}</div>'
                 f'<div class="v">{esc(value)}</div><div class="s">{esc(sub)}</div></div>')
    o.append("</div>")
    if sev_counts:
        o.append('<div style="margin-top:16px">' + severity_bar(sev_counts) + "</div>")
    o.append("</section>")

    # ---- 02 where the site stands ------------------------------------------
    #
    # Three charts, deliberately, because they answer three different questions
    # and a reader who sees only the first will draw the wrong conclusion from it:
    # how healthy (score), how much we know (coverage), and what kind of problem
    # (severity mix). The score chart alone is the misleading half of a report.
    o.append('<section class="brk">')
    o.append(_sec("02", "Where this site stands",
                  "A dimension we could not measure says so. It is never shown as zero."))
    o.append(bars([
        (r.get("label") or r["key"],
         num(r["score"]) if r.get("checks_ran") else None,
         # A literal character, not `&middot;`: this string goes through esc() into
         # an SVG <text> node, which does not decode HTML entities - the entity
         # would print as "&middot;" on the page.
         _cov(r) + (f" \u00b7 {r['findings_open']:,} issues" if r.get("findings_open") else ""))
        for r in dims
    ]))
    o.append('<div class="chartrow" style="margin-top:18px">')
    o.append('<div><h3>How much of the checklist ran</h3>'
             + coverage_bar([(r.get("label") or r["key"], int(r.get("checks_ran") or 0),
                              int(r.get("checks_applicable") or 0)) for r in dims], width=400)
             + '<p class="muted small">A score is only comparable to another score '
               'computed over the same checks.</p></div>')
    o.append('<div><h3>What kind of problem, by dimension</h3>'
             + sev_split([(r.get("label") or r["key"], _sev_of(r)) for r in dims], width=400)
             + '<p class="muted small">Bars are scaled against the busiest dimension, '
               'so their lengths compare.</p></div>')
    o.append("</div></section>")

    # ---- 03 every dimension, in full ---------------------------------------
    #
    # THE SECTION THAT MAKES THIS DOCUMENT AND THE WORKBOOK THE SAME AUDIT. The
    # report used to print the top 25 issues and stop, while the workbook listed
    # several hundred - so the two artefacts read as different runs of different
    # depth. Every issue the workbook holds is now accounted for here: the worst
    # get a card in section 05, and the rest are listed by name, severity and
    # blast radius under their own dimension. Nothing is silently dropped.
    # Keyed on DIMENSION, not pillar. These are two different taxonomies and only one
    # of them matches `audit_rollups.key`: findings carry pillars like "on-page" and
    # "local-seo", while the dimension rollups this section iterates are keyed "onpage",
    # "local", "geo". Grouping by pillar meant `by_dimension.get("onpage")` missed all
    # 370 of its findings and the card printed "No open issues in this dimension" - while
    # section 02, which reads the rollup, printed 370 for the same dimension on the page
    # before. Only "technical" agreed, because it is spelled the same in both.
    # `pillar` remains the fallback for a legacy row written before `dimension` existed.
    by_dimension: dict[str, list[dict[str, Any]]] = {}
    for f in issues:
        key_for = f.get("dimension") or f.get("pillar") or "other"
        by_dimension.setdefault(key_for, []).append(f)
    if dims:
        o.append('<section class="brk">')
        o.append(_sec("03", "Every dimension, in full",
                      "Each dimension with its score, its coverage, its sub-areas and "
                      "every issue found in it."))
        for r in dims:
            key = r["key"]
            label = r.get("label") or key
            mine = by_dimension.get(key, [])
            sub_rows = [x for x in subs if (x["key"] or "").split("/")[0] == key]
            o.append('<div class="pillar">')
            o.append('<div class="pillar-h">')
            o.append(donut(num(r["score"]) if r.get("checks_ran") else None, size=104))
            o.append(f'<div class="t"><h3>{esc(label)}</h3>'
                     f'<div class="c">{esc(_cov(r))}</div></div>')
            o.append('<div class="pillar-stats">')
            for lab, val in (("Issues", f"{len(mine):,}"),
                             ("Occurrences", f"{sum(int(x.get('instance_count') or 0) for x in mine):,}"),
                             ("Pages hit", f"{int(r.get('pages_affected') or 0):,}")):
                o.append(f"<div><b>{esc(val)}</b>{esc(lab)}</div>")
            o.append("</div></div>")

            if sub_rows:
                o.append("<table><thead><tr><th>Sub-area</th><th class='num'>Score</th>"
                         "<th>Coverage</th><th class='num'>Issues</th>"
                         "<th class='num'>Occurrences</th></tr></thead><tbody>")
                for x in sorted(sub_rows, key=lambda v: (v["score"] is None,
                                                         float(num(v["score"]) or 0))):
                    sc = num(x["score"])
                    cell = ("<span class='muted'>not measured</span>" if sc is None
                            or not x.get("checks_ran")
                            else f"<b style='color:{tone(sc)}'>{sc:g}</b>")
                    o.append(f"<tr><td>{esc(x.get('label') or x['key'])}</td>"
                             f"<td class='num'>{cell}</td>"
                             f"<td class='small muted'>{esc(_cov(x))}</td>"
                             f"<td class='num'>{int(x.get('findings_open') or 0):,}</td>"
                             f"<td class='num'>{int(x.get('instances_open') or 0):,}</td></tr>")
                o.append("</tbody></table>")

            if mine:
                o.append("<table><thead><tr><th>Issue</th><th>Severity</th>"
                         "<th>Check</th><th class='num'>Reach</th></tr></thead><tbody>")
                for f in mine:
                    sev = (f.get("severity") or "info").lower()
                    o.append(
                        f"<tr><td>{esc(f.get('check_name') or f.get('check_id'))}</td>"
                        f"<td><span class='sev' style='background:"
                        f"{SEVERITY_COLOR.get(sev, MUTED_2)}'>{esc(sev)}</span></td>"
                        f"<td class='small muted'>{esc(f.get('check_id'))}</td>"
                        f"<td class='num'>{esc(_blast(f))}</td></tr>")
                o.append("</tbody></table>")
            else:
                o.append('<p class="muted small">No open issues in this dimension.</p>')
            o.append("</div>")
        o.append("</section>")

    # ---- 03 by subpoint -----------------------------------------------------
    scored = [r for r in subs if r.get("checks_ran") and r.get("findings_open")]
    # 999 sorts an unscored subpoint last WITHOUT pretending it scored 999.
    scored.sort(key=lambda r: float(num(r["score"]) or 0) if r["score"] is not None else 999.0)
    if scored:
        o.append('<section class="brk">')
        o.append(_sec("04", "Weakest areas",
                      f"The {min(len(scored), 20)} lowest-scoring subpoints that returned findings."))
        o.append("<table><thead><tr><th>Area</th><th>Pillar</th><th class='num'>Score</th>"
                 "<th>Coverage</th><th class='num'>Issues</th><th class='num'>Occurrences</th>"
                 "</tr></thead><tbody>")
        for r in scored[:20]:
            pillar = (r["key"] or "").split("/")[0]
            o.append(
                f"<tr><td><b>{esc(r.get('label') or r['key'])}</b></td><td>{esc(pillar)}</td>"
                f"<td class='num' style='color:{tone(num(r['score']))};font-weight:800'>{num(r['score']):g}</td>"
                f"<td class='small muted'>{esc(_cov(r))}</td>"
                f"<td class='num'>{r['findings_open']:,}</td>"
                f"<td class='num'>{r['instances_open']:,}</td></tr>"
            )
        o.append("</tbody></table></section>")

    # ---- 04 the plan --------------------------------------------------------
    if data.roadmap_items:
        by_phase: dict[str, list[dict[str, Any]]] = {}
        for it in data.roadmap_items:
            by_phase.setdefault(it["phase"], []).append(it)
        labels = {
            "p0_30d": ("Now", "first 30 days"), "p1_90d": ("Next", "through 90 days"),
            "p2_180d": ("Then", "through 6 months"), "p3_365d": ("Later", "through 12 months"),
        }
        cap = (data.roadmap or {}).get("capacity_points_per_month")
        o.append('<section class="brk">')
        o.append(_sec("05", "The plan",
                      "Ordered by impact over effort. Phases are relative windows of work, "
                      "not calendar dates."))
        o.append(phase_bars([(name, window, len(by_phase.get(key, [])))
                             for key, (name, window) in labels.items()]))
        for key, (name, window) in labels.items():
            items = sorted(by_phase.get(key, []), key=lambda x: x["sequence"])
            if not items:
                continue
            o.append('<div class="phase">')
            o.append(f"<h3>{esc(name)} <em>{esc(window)}</em> <b>{len(items)} items</b></h3>")
            o.append("<table><thead><tr><th>#</th><th>Do this</th><th>Owner</th>"
                     "<th>Proven by</th></tr></thead><tbody>")
            for it in items[:10]:
                o.append(
                    f"<tr><td class='num'>{it['sequence']}</td>"
                    f"<td><b>{esc(it['title'])}</b></td>"
                    f"<td class='small'>{esc(label_of(it.get('owner_role'), style='title'))}</td>"
                    f"<td class='small muted'>{esc(it.get('exit_criterion') or '')}</td></tr>"
                )
            if len(items) > 10:
                o.append(f"<tr><td></td><td class='small muted' colspan='3'>"
                         f"+{len(items) - 10} more in this window - see the workbook</td></tr>")
            o.append("</tbody></table></div>")
        backlog = by_phase.get("backlog") or []
        if backlog:
            o.append(
                f'<div class="note">{len(backlog):,} further items fall beyond the planned '
                f'horizon at the stated throughput'
                + (f" of {cap} points per month" if cap else "")
                + ". They are listed in full in the workbook, not dropped.</div>"
            )
        o.append("</section>")

    # ---- 05 the issues ------------------------------------------------------
    o.append('<section class="brk">')
    o.append(_sec("06", "The issues",
                  f"The {min(len(issues), data.top_findings)} highest-priority problems in "
                  "full. Each is ONE fix, however many pages it touches; the remaining "
                  f"{max(0, len(issues) - data.top_findings):,} are listed under their "
                  "dimension in section 03, and every occurrence of every one of them is "
                  "in the workbook."))
    widest = sorted(issues, key=lambda f: -int(f.get("instance_count") or 0))[:12]
    reach = [int(f.get("instance_count") or 0) for f in widest]
    # A chart of twelve identical bars is decoration. It earns its space only when
    # the issues actually differ in reach - which on a small crawl they do not.
    if reach and max(reach) > 1 and max(reach) != min(reach):
        o.append('<h3 style="margin-bottom:6px">Where one fix goes furthest</h3>')
        o.append(blast_bars([(f.get("check_name") or f.get("check_id") or "",
                              (f.get("severity") or "info").lower(),
                              int(f.get("instance_count") or 0)) for f in widest]))
        o.append('<p class="muted small" style="margin-bottom:14px">Occurrences, not '
                 'effort. A template problem on 121 pages is still one edit.</p>')
    for f in issues[: data.top_findings]:
        sev = (f.get("severity") or "info").lower()
        colour = SEVERITY_COLOR.get(sev, MUTED_2)
        o.append(f'<div class="finding" style="border-left-color:{colour}">')
        o.append('<div class="top">')
        o.append(f'<span class="sev" style="background:{colour}">{esc(sev)}</span>')
        o.append(f'<span class="name">{esc(f.get("check_name") or f.get("check_id"))}</span>')
        o.append(f'<span class="radius">{esc(_blast(f))}</span>')
        o.append("</div>")
        locus = f.get("locus_value") or ""
        o.append(
            f'<div class="sub">{esc(f.get("check_id"))} &middot; '
            f'{esc(f.get("pillar"))} / {esc(f.get("subcategory"))}'
            + (f" &middot; one template: {esc(locus)}" if f.get("locus_kind") == "template" and locus else "")
            + "</div>"
        )
        if f.get("remediation"):
            o.append(f'<div class="fix">{esc(f["remediation"])}</div>')
        samples = f.get("sample_urls") or []
        if samples:
            o.append("<ul>" + "".join(f"<li>{esc(u)}</li>" for u in samples[:3]) + "</ul>")
        o.append("</div>")
    if len(issues) > data.top_findings:
        o.append(
            f'<div class="note">{len(issues) - data.top_findings:,} further issues are '
            "listed by name under their own dimension in section 03, and in the workbook "
            "with every affected URL.</div>"
        )
    o.append("</section>")

    # ---- 06 what we could and could not check -------------------------------
    o.append('<section class="brk">')
    o.append(_sec("07", "What we checked",
                  "A check that did not run is reported as such. It is not counted as a pass."))
    o.append("<table><thead><tr><th>Dimension</th><th class='num'>Ran</th>"
             "<th class='num'>Of</th><th>Not run because</th></tr></thead><tbody>")
    for r in dims:
        reasons = r.get("skip_reasons") or {}
        why = ", ".join(f"{label_of(k, style='lower')} ({v})"
                        for k, v in sorted(reasons.items())) or "-"
        o.append(
            f"<tr{' class=dim' if not r.get('checks_ran') else ''}>"
            f"<td><b>{esc(r.get('label') or r['key'])}</b></td>"
            f"<td class='num'>{r.get('checks_ran', 0)}</td>"
            f"<td class='num'>{r.get('checks_applicable', 0)}</td>"
            f"<td class='small muted'>{esc(why)}</td></tr>"
        )
    o.append(
        f"<tr><td><b>All dimensions</b></td>"
        f"<td class='num'><b>{site.get('checks_ran', 0)}</b></td>"
        f"<td class='num'><b>{site.get('checks_applicable', 0)}</b></td><td></td></tr>"
    )
    o.append("</tbody></table>")

    # A count of skipped checks is not an explanation. The engine records a typed
    # reason for every check it did not run, and this is where a client gets to
    # read it - "33 checks need backlink data you have not purchased" is an
    # answerable statement; "33 checks skipped" is not.
    totals: dict[str, int] = {}
    for r in dims:
        for k, v in (r.get("skip_reasons") or {}).items():
            try:
                totals[str(k)] = totals.get(str(k), 0) + int(v)
            except (TypeError, ValueError):
                continue
    if totals:
        o.append('<h3 style="margin-top:16px">Why a check did not run</h3>')
        o.append("<table><thead><tr><th>Reason</th><th class='num'>Checks</th>"
                 "</tr></thead><tbody>")
        for k, v in sorted(totals.items(), key=lambda kv: -kv[1]):
            o.append(f"<tr><td>{esc(label_of(k))}</td>"
                     f"<td class='num'>{v:,}</td></tr>")
        o.append("</tbody></table>")
        o.append('<p class="muted small">Every one of these is listed by check in the '
                 "workbook's coverage sheet, with what it is waiting on.</p>")
    o.append("</section>")

    # ---- 08 the pages we crawled -------------------------------------------
    if data.pages:
        o.append('<section class="brk">')
        o.append(_sec("08", "The pages we crawled",
                      f"All {len(data.pages):,} URLs this run reached. A finding can only "
                      "name a page on this list."))
        o.append("<table><thead><tr><th>URL</th><th class='num'>Status</th>"
                 "<th class='num'>Words</th><th>Indexable</th></tr></thead><tbody>")
        for pg in data.pages[:_MAX_PAGES_LISTED]:
            idx = pg.get("indexable")
            # `http_status` is the column (0094_audit_altitudes.sql); `status_code` was
            # never a key on this row, so every URL in every report printed "-" here -
            # a Status column that has never once shown a status.
            code = pg.get("http_status")
            words = pg.get("word_count")
            o.append(
                f"<tr><td class='small'>{esc(pg.get('url') or '')}</td>"
                f"<td class='num'>{esc(code if code is not None else '-')}</td>"
                f"<td class='num'>{esc(words if words is not None else '-')}</td>"
                f"<td class='small'>{'yes' if idx else ('no' if idx is not None else '-')}</td></tr>"
            )
        o.append("</tbody></table>")
        if len(data.pages) > _MAX_PAGES_LISTED:
            o.append(f'<div class="note">{len(data.pages) - _MAX_PAGES_LISTED:,} further '
                     "URLs are in the workbook's pages sheet.</div>")
        o.append("</section>")

    # ---- 09 methodology -----------------------------------------------------
    o.append('<section class="brk">')
    o.append(_sec("09", "How to read this", "The arithmetic, stated."))
    o.append(
        '<div class="note">'
        "<p><b>Scores.</b> Each score is computed only over the checks that actually ran at "
        "that level, weighted by severity. A dimension where nothing ran has no score and is "
        "reported as <i>not measured</i>, which is not the same as scoring zero.</p>"
        "<p><b>Issues and occurrences.</b> An issue is one problem with one fix. A template "
        "problem affecting 121 pages is one issue with 121 occurrences, because it is one "
        "edit. Occurrence counts are the blast radius, not the amount of work.</p>"
        "<p><b>Comparability.</b> Two scores may only be compared when the same checks ran "
        "behind them. A run with more data will not necessarily score higher.</p>"
        "</div></section>"
    )

    o.append(
        f'<div class="foot">Prepared by {esc(b.name)} from measured data. '
        f'{site.get("checks_ran", 0)} of {site.get("checks_applicable", 0)} checks ran across '
        f'{site.get("pages_crawled", 0):,} crawled pages. No figure in this document is estimated.'
        # Only a real address. A placeholder under "reply to" is worse than silence.
        + (f' Questions: {esc(b.contact_email)}.' if b.has_contact else "")
        + (f' {esc(b.website)}' if b.website else "")
        + "</div>"
    )
    o.append("</div></body></html>")
    return no_dashes("".join(o))


# --------------------------------------------------------------------------- #
# Build from stored rows
# --------------------------------------------------------------------------- #

def build(
    *,
    audit_id: str,
    out_dir: str | Path,
    meta: dict[str, Any] | None = None,
    top_findings: int = 40,
    pdf: bool = True,
) -> Path:
    """Fetch this audit's rows and write `audit-report.html`.

    Findings come through the audit's OWN instances, not `audit_findings.audit_id`
    - that column is last-writer-wins, so a report keyed on it silently loses
    findings once a newer audit of the same site upserts them.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with privileged_connection() as cur:
        cur.execute(
            "select * from public.audit_rollups where audit_id = %s order by level, key",
            (audit_id,),
        )
        rollups = [dict(r) for r in cur.fetchall()]
        cur.execute(
            """select f.* from public.audit_findings f
               where exists (select 1 from public.audit_finding_instances i
                             where i.finding_id = f.id and i.audit_id = %s)
               order by case f.severity when 'critical' then 0 when 'major' then 1
                                        when 'minor' then 2 else 3 end,
                        f.instance_count desc, f.check_id""",
            (audit_id,),
        )
        findings = [dict(r) for r in cur.fetchall()]
        cur.execute("select * from public.audit_pages where audit_id = %s", (audit_id,))
        pages = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "select * from public.audit_roadmaps where audit_id = %s and status = 'active'",
            (audit_id,),
        )
        rm = cur.fetchone()
        cur.execute(
            """select i.* from public.audit_roadmap_items i
               join public.audit_roadmaps m on m.id = i.roadmap_id
               where m.audit_id = %s and m.status = 'active'
               order by i.sequence""",
            (audit_id,),
        )
        items = [dict(r) for r in cur.fetchall()]
        # Up to three example URLs per printed finding. Only for the ones that
        # actually appear in the body - fetching them for all 461 would be 461
        # round trips for evidence nobody prints.
        for f in findings[:top_findings]:
            cur.execute(
                "select url from public.audit_finding_instances"
                " where finding_id = %s and audit_id = %s and url <> '' limit 3",
                (f["id"], audit_id),
            )
            f["sample_urls"] = [r["url"] for r in cur.fetchall()]

    doc = render(ReportInput(
        meta=meta or {}, rollups=rollups, findings=findings, pages=pages,
        roadmap=dict(rm) if rm else None, roadmap_items=items,
        top_findings=top_findings,
    ))
    path = out / REPORT_NAME
    path.write_text(doc, encoding="utf-8")
    if pdf:
        # Best effort by design: a missing browser must cost this run its PDF, not
        # its workbook, its CSVs, or the HTML that was just written.
        report_pdf.render(path, out / REPORT_PDF_NAME)
    return path
