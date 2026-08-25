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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from app.db.database import privileged_connection

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
    cap = (
        f'<text x="{cx}" y="{size - 1}" text-anchor="middle" font-size="10"'
        f' font-weight="700" fill="{MUTED}">{esc(label)}</text>' if label else ""
    )
    return (
        f'<svg width="{size}" height="{size + 6}" viewBox="0 0 {size} {size + 6}"'
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


# --------------------------------------------------------------------------- #
# The document
# --------------------------------------------------------------------------- #

REPORT_NAME = "audit-report.html"

#: Print CSS lives with the document. `@page` gives the PDF pass real margins, and
#: `break-inside: avoid` keeps a finding card from splitting across a page - the
#: difference between a report and a printout.
_CSS = f"""
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
    #: How many issue cards the body carries. The rest stay in the workbook; a
    #: report that prints all 461 is the 833-page PDF this replaces.
    top_findings: int = 25


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
    issues = [f for f in data.findings]
    sev_counts: dict[str, int] = {}
    for f in issues:
        k = (f.get("severity") or "info").lower()
        sev_counts[k] = sev_counts.get(k, 0) + 1

    o: list[str] = []
    o.append(f'<!doctype html><html lang="en"><head><meta charset="utf-8">')
    o.append(f'<title>SEO audit - {esc(m.get("client_name") or m.get("url", ""))}</title>')
    o.append(f"<style>{_CSS}</style></head><body><div class=\"wrap\">")

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
        ("Pages without a critical issue",
         "-" if site.get("url_health_pct") is None else f"{num(site['url_health_pct']):g}%",
         "comparable across runs"),
    ):
        o.append(f'<div class="kpi"><div class="l">{esc(label)}</div>'
                 f'<div class="v">{esc(value)}</div><div class="s">{esc(sub)}</div></div>')
    o.append("</div>")
    if sev_counts:
        o.append('<div style="margin-top:16px">' + severity_bar(sev_counts) + "</div>")
    o.append("</section>")

    # ---- 02 where the site stands ------------------------------------------
    o.append("<section>")
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
    o.append("</section>")

    # ---- 03 by subpoint -----------------------------------------------------
    scored = [r for r in subs if r.get("checks_ran") and r.get("findings_open")]
    scored.sort(key=lambda r: (num(r["score"]) if r["score"] is not None else 999))
    if scored:
        o.append("<section>")
        o.append(_sec("03", "Weakest areas",
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
        o.append("<section>")
        o.append(_sec("04", "The plan",
                      "Ordered by impact over effort. Phases are relative windows of work, "
                      "not calendar dates."))
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
                    f"<td class='small'>{esc((it.get('owner_role') or '').replace('_', ' ').title())}</td>"
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
    o.append("<section>")
    o.append(_sec("05", "The issues",
                  f"The {min(len(issues), data.top_findings)} highest-priority problems. "
                  "Each is ONE fix, however many pages it touches; every occurrence is "
                  "listed in the workbook."))
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
            "listed in the workbook, with every affected URL.</div>"
        )
    o.append("</section>")

    # ---- 06 what we could and could not check -------------------------------
    o.append("<section>")
    o.append(_sec("06", "What we checked",
                  "A check that did not run is reported as such. It is not counted as a pass."))
    o.append("<table><thead><tr><th>Dimension</th><th class='num'>Ran</th>"
             "<th class='num'>Of</th><th>Not run because</th></tr></thead><tbody>")
    for r in dims:
        reasons = r.get("skip_reasons") or {}
        why = ", ".join(f"{k.replace('_', ' ')} ({v})" for k, v in sorted(reasons.items())) or "-"
        o.append(
            f"<tr{' class=dim' if not r.get('checks_ran') else ''}>"
            f"<td><b>{esc(r.get('label') or r['key'])}</b></td>"
            f"<td class='num'>{r.get('checks_ran', 0)}</td>"
            f"<td class='num'>{r.get('checks_applicable', 0)}</td>"
            f"<td class='small muted'>{esc(why)}</td></tr>"
        )
    o.append("</tbody></table></section>")

    # ---- 07 methodology -----------------------------------------------------
    o.append("<section>")
    o.append(_sec("07", "How to read this", "The arithmetic, stated."))
    o.append(
        '<div class="note">'
        "<p><b>Scores.</b> Each score is computed only over the checks that actually ran at "
        "that level, weighted by severity. A dimension where nothing ran has no score and is "
        "reported as <i>not measured</i> &mdash; that is not the same as scoring zero.</p>"
        "<p><b>Issues and occurrences.</b> An issue is one problem with one fix. A template "
        "problem affecting 121 pages is one issue with 121 occurrences, because it is one "
        "edit. Occurrence counts are the blast radius, not the amount of work.</p>"
        "<p><b>Comparability.</b> Two scores may only be compared when the same checks ran "
        "behind them. A run with more data will not necessarily score higher.</p>"
        "</div></section>"
    )

    o.append(
        f'<div class="foot">Generated by AIOS from measured data. '
        f'{site.get("checks_ran", 0)} of {site.get("checks_applicable", 0)} checks ran across '
        f'{site.get("pages_crawled", 0):,} crawled pages. No figure in this document is estimated.</div>'
    )
    o.append("</div></body></html>")
    return "".join(o)


# --------------------------------------------------------------------------- #
# Build from stored rows
# --------------------------------------------------------------------------- #

def build(
    *,
    audit_id: str,
    out_dir: str | Path,
    meta: dict[str, Any] | None = None,
    top_findings: int = 25,
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
    return path
