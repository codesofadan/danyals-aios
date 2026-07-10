"""
SEO-AUDIT-OS - client-facing audit PDF generator.

Renders a ~20-page audit PDF designed for an SEO agency to send to its
prospects and retainer clients. The PDF uses the GIVRMEDIA visual language
(navy hero, sky-blue accents, white cards, Inter font) and includes visual
elements: SVG donut gauge for the overall score, horizontal bar charts for
dimension scores, progress bars for AI search visibility, numbered sprint
cards, severity / category chips, pull-quote callouts.

The script parses the section-*.md files produced by the agent pipeline
(specifically section-06-action-plan.md for the top findings, wins, and
sprints; section-01-executive.md for the verdict paragraph). It lays the
content out across 20 visually full pages with no half-empty pages.

The PDF NEVER mentions APIs, missing data, the system architecture, run
IDs, or methodology details - the audience is a non-technical business
owner.

Usage:
    python scripts/generate_audit_pdf.py <artifact_dir> [--client ...] [--date ...]
"""
from __future__ import annotations

import argparse
import html as _html
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent

_BRANDING_DEFAULTS = {
    "client_name": "Danyal",
    "brand_name": "Danyal's Agency",
    "brand_bold": "SEO-AUDIT",
    "brand_suffix": "· OS Audit Engine",
    "contact_email": "danyal@example.com",
    "website": "",
    "accent_color": "",
    "logo_path": "",
}


def _load_branding() -> dict:
    """branding.json at the repo root is the single source of truth for
    client-facing branding. Missing file or keys fall back to defaults so
    the renderer never crashes on branding."""
    branding = dict(_BRANDING_DEFAULTS)
    try:
        raw = json.loads((_REPO_ROOT / "branding.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return branding
    branding.update({
        k: v.strip()
        for k, v in raw.items()
        if k in _BRANDING_DEFAULTS and isinstance(v, str) and v.strip()
    })
    return branding


BRANDING = _load_branding()


PALETTE = {
    "navy_dark": "#0E2A47",
    "navy_mid": "#15355C",
    "blue_accent": "#0EA5E9",
    "blue_light": "#7DD3FC",
    "blue_bg": "#F0F9FF",
    "blue_link": "#2563EB",
    "page_bg": "#FFFFFF",
    "card_bg": "#FFFFFF",
    "card_border": "#E2E8F0",
    "text_body": "#1F2937",
    "text_muted": "#64748B",
    "text_label": "#475569",
    "sev_critical_bg": "#FEE2E2",
    "sev_critical_fg": "#B91C1C",
    "sev_major_bg":    "#FEF3C7",
    "sev_major_fg":    "#92400E",
    "sev_minor_bg":    "#E0F2FE",
    "sev_minor_fg":    "#075985",
    "delta_green":     "#16A34A",
    "delta_green_bg":  "#DCFCE7",
    "warn_orange":     "#F59E0B",
    "warn_red":        "#EF4444",
}


CATEGORY_COLOR = {
    "TECHNICAL":   ("#DBEAFE", "#1E40AF"),
    "CONTENT":     ("#EDE9FE", "#5B21B6"),
    "LOCAL":       ("#DCFCE7", "#166534"),
    "OFF-PAGE":    ("#FCE7F3", "#9D174D"),
    "BRAND":       ("#FFEDD5", "#9A3412"),
    "SCHEMA":      ("#CFFAFE", "#155E75"),
    "ON-PAGE":     ("#E0E7FF", "#3730A3"),
}


# ============================================================
# CSS
# ============================================================

CSS = f"""
@page {{ size: A4; margin: 30mm 14mm 22mm 14mm; }}
* {{ box-sizing: border-box; }}
html, body {{
  font-family: 'Inter', 'Segoe UI', -apple-system, Roboto, Arial, sans-serif;
  font-size: 10.5pt;
  line-height: 1.6;
  color: {PALETTE['text_body']};
  margin: 0; padding: 0; background: {PALETTE['page_bg']};
}}
h1, h2, h3, h4 {{ color: {PALETTE['navy_dark']}; margin: 0; font-weight: 700; }}
p {{ margin: 5pt 0 8pt 0; }}
strong {{ color: {PALETTE['navy_dark']}; font-weight: 700; }}
a {{ color: {PALETTE['blue_link']}; text-decoration: none; }}

/* COVER */
.cover {{ page-break-after: always; padding-top: 10pt; }}
.cover-hero {{
  background: linear-gradient(135deg, {PALETTE['navy_dark']} 0%, {PALETTE['navy_mid']} 100%);
  color: #FFFFFF; padding: 56pt 38pt 46pt 38pt; border-radius: 14pt;
  margin-top: 16pt; margin-bottom: 18pt;
}}
.cover-eyebrow {{
  color: {PALETTE['blue_accent']}; font-size: 9pt; letter-spacing: 2pt;
  font-weight: 600; text-transform: uppercase; margin-bottom: 12pt;
}}
.cover-title {{ font-size: 34pt; font-weight: 800; line-height: 1.05; margin: 0 0 12pt 0; color: #FFFFFF; }}
.cover-sub {{ font-size: 12pt; color: #CBD5E1; margin: 0 0 22pt 0; }}
.cover-tag {{
  display: inline-block; background: rgba(14,165,233,0.18);
  border: 1px solid rgba(14,165,233,0.55); color: #FFFFFF;
  padding: 6pt 14pt; border-radius: 999pt; font-size: 9pt;
  letter-spacing: 1.2pt; text-transform: uppercase; font-weight: 600;
}}
.cover-meta {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10pt; }}
.cover-meta-card {{
  background: #FFFFFF; border: 1px solid {PALETTE['card_border']};
  border-radius: 8pt; padding: 11pt 14pt;
}}
.cover-meta-label {{
  font-size: 7.5pt; letter-spacing: 1.4pt; text-transform: uppercase;
  color: {PALETTE['text_muted']}; font-weight: 600; margin-bottom: 4pt;
}}
.cover-meta-value {{ font-size: 12pt; font-weight: 700; color: {PALETTE['navy_dark']}; }}

/* PAGE
   Each .page div = exactly one printed A4 page.
   We rely on text caps in build_finding_page() to keep card height under the
   printable area, not on overflow:hidden (which would silently clip content). */
.page {{
  page-break-after: always;
  break-after: page;
  page-break-inside: avoid;
  break-inside: avoid;
  min-height: 230mm;
}}
.page:last-child {{ page-break-after: auto; break-after: auto; }}

/* SECTION HEADER */
.sec-eyebrow {{ display: none; }}
.sec-title {{
  font-size: 18pt; font-weight: 800; color: {PALETTE['navy_dark']};
  margin: 0 0 4pt 0; line-height: 1.2; padding-left: 11pt;
  border-left: 5px solid {PALETTE['blue_accent']};
}}
.sec-lead {{
  font-size: 10.5pt; color: {PALETTE['text_label']}; margin: 10pt 0 14pt 0;
  line-height: 1.65;
}}

/* SCORECARD */
.scorecard-hero {{
  background: linear-gradient(135deg, #F0F9FF 0%, #FFFFFF 100%);
  border: 1px solid {PALETTE['card_border']}; border-radius: 12pt;
  padding: 18pt 22pt; margin: 4pt 0 14pt 0;
  display: grid; grid-template-columns: 150pt 1fr; gap: 22pt; align-items: center;
}}
.scorecard-hero-right h3 {{ font-size: 14pt; font-weight: 700; color: {PALETTE['navy_dark']}; margin: 0 0 8pt 0; }}
.scorecard-hero-right p {{ font-size: 10.5pt; color: {PALETTE['text_body']}; line-height: 1.6; margin: 0 0 6pt 0; }}

.tile-grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8pt; margin: 8pt 0 12pt 0; }}
.tile {{
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 8pt; padding: 11pt 12pt;
}}
.tile-label {{
  font-size: 7pt; letter-spacing: 1.3pt; text-transform: uppercase;
  color: {PALETTE['text_muted']}; font-weight: 600;
}}
.tile-value {{ font-size: 22pt; font-weight: 800; color: {PALETTE['navy_dark']}; line-height: 1.0; margin-top: 4pt; }}
.tile-delta {{
  display: inline-block; margin-top: 6pt; padding: 2pt 8pt;
  border-radius: 999pt; font-size: 7.5pt; font-weight: 700;
  background: {PALETTE['delta_green_bg']}; color: {PALETTE['delta_green']};
}}
.tile-delta.dim {{ background: #F1F5F9; color: {PALETTE['text_muted']}; }}
.tile-delta.warn {{ background: #FEF3C7; color: #92400E; }}
.tile-delta.crit {{ background: #FEE2E2; color: #B91C1C; }}
.tile-suffix {{ font-size: 8pt; color: {PALETTE['text_muted']}; margin-top: 3pt; }}

/* DIMENSION BARS */
.barrow-card {{
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 10pt; padding: 16pt 20pt; margin: 4pt 0 12pt 0;
}}
.barrow {{
  display: grid; grid-template-columns: 110pt 1fr 40pt; gap: 14pt;
  align-items: center; padding: 9pt 0;
}}
.barrow-label {{ font-size: 10.5pt; font-weight: 700; color: {PALETTE['navy_dark']}; }}
.barrow-track {{ width: 100%; height: 10pt; background: #E2E8F0; border-radius: 5pt; overflow: hidden; }}
.barrow-fill {{ height: 100%; border-radius: 5pt; background: {PALETTE['blue_accent']}; }}
.barrow-fill.good {{ background: {PALETTE['delta_green']}; }}
.barrow-fill.warn {{ background: {PALETTE['warn_orange']}; }}
.barrow-fill.crit {{ background: {PALETTE['warn_red']}; }}
.barrow-fill.dim  {{ background: #94A3B8; }}
.barrow-value {{ font-size: 11pt; font-weight: 800; color: {PALETTE['navy_dark']}; text-align: right; }}
.barrow-value.dim {{ color: #94A3B8; }}
.bar-interp {{
  font-size: 9pt; color: {PALETTE['text_muted']}; padding-left: 124pt;
  margin: -4pt 0 6pt 0; line-height: 1.5;
}}

/* CALLOUT (✓ rows) */
.why-card {{
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 10pt; padding: 16pt 20pt; margin: 8pt 0 0 0;
}}
.why-title {{ font-size: 12pt; font-weight: 700; color: {PALETTE['navy_dark']}; margin-bottom: 8pt; }}
.why-row {{
  display: grid; grid-template-columns: 24pt 1fr; gap: 10pt;
  padding: 9pt 0; border-bottom: 1px dashed {PALETTE['card_border']};
  align-items: start;
}}
.why-row:last-child {{ border-bottom: none; }}
.why-tick {{
  background: {PALETTE['navy_dark']}; width: 20pt; height: 20pt;
  border-radius: 50%; color: {PALETTE['blue_accent']};
  font-size: 12pt; text-align: center; line-height: 20pt; font-weight: 800;
}}
.why-text {{ font-size: 10pt; color: {PALETTE['text_body']}; line-height: 1.6; }}

/* WHAT'S WORKING - neutral callout grid (no green circles, per client design rules).
   Green tinted backgrounds and the solid green "+" badge that previously sat
   behind every card were removed at the client's request. The grid now uses
   the same card system as the rest of the PDF for visual coherence. */
.good-grid {{
  display: grid; grid-template-columns: 1fr 1fr; gap: 12pt; margin: 6pt 0;
}}
.good-card {{
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 10pt; padding: 14pt 16pt;
  border-left: 3px solid {PALETTE['blue_accent']};
}}
.good-card .gc-num {{
  display: inline-block; font-size: 9pt; font-weight: 700;
  color: {PALETTE['blue_accent']}; letter-spacing: 1.5pt;
  text-transform: uppercase; margin-bottom: 6pt;
}}
.good-card .gc-title {{ font-size: 11pt; font-weight: 700; color: {PALETTE['navy_dark']}; margin: 4pt 0; }}
.good-card .gc-text  {{ font-size: 9.5pt; color: {PALETTE['text_body']}; line-height: 1.55; }}

/* FULL-PAGE FINDING CARD (1 per page) */
.fp-finding {{
  page-break-inside: avoid;
  break-inside: avoid;
  orphans: 4; widows: 4;
}}
.fp-num {{
  font-size: 9pt; letter-spacing: 2pt; text-transform: uppercase;
  color: {PALETTE['blue_accent']}; font-weight: 700; margin-bottom: 2pt;
}}
.fp-chips {{ display: flex; gap: 6pt; margin: 2pt 0 8pt 0; flex-wrap: wrap; }}
.chip {{
  display: inline-block; padding: 3pt 9pt; border-radius: 999pt;
  font-size: 8pt; letter-spacing: 1pt; text-transform: uppercase; font-weight: 700;
}}
.chip.sev-critical {{ background: {PALETTE['sev_critical_bg']}; color: {PALETTE['sev_critical_fg']}; }}
.chip.sev-major    {{ background: {PALETTE['sev_major_bg']};    color: {PALETTE['sev_major_fg']}; }}
.chip.sev-minor    {{ background: {PALETTE['sev_minor_bg']};    color: {PALETTE['sev_minor_fg']}; }}
.fp-headline {{
  font-size: 20pt; font-weight: 800; color: {PALETTE['navy_dark']};
  line-height: 1.18; margin: 4pt 0 10pt 0;
}}
.fp-desc {{
  font-size: 10.5pt; color: {PALETTE['text_body']}; line-height: 1.6;
  margin: 0 0 10pt 0;
}}
.fp-quote {{
  background: #F0F9FF; border-left: 4pt solid {PALETTE['blue_accent']};
  border-radius: 0 6pt 6pt 0; padding: 10pt 16pt; margin: 0 0 10pt 0;
  font-size: 10.5pt; font-weight: 600; color: {PALETTE['navy_dark']};
  line-height: 1.45; font-style: italic;
}}
/* Side-by-side grid keeps Impact + Fix on the same row to avoid stacking
   tall callout boxes that would push the card across two physical pages. */
.fp-callouts {{
  display: grid; grid-template-columns: 1fr 1fr; gap: 10pt;
  margin: 0 0 10pt 0;
}}
.fp-impact, .fp-fix {{
  border-radius: 7pt; padding: 10pt 12pt;
  page-break-inside: avoid; break-inside: avoid;
}}
/* Finding callout panels: paired Impact + Fix boxes.
   Original design used orange + green tints. Green has been removed at the
   client's request (the green panel was reading as a coloured circle behind
   every fix paragraph across 30+ finding pages). Replaced with a neutral
   navy-tinted card so the orange Impact still stands out without competing. */
.fp-impact {{ background: #FFF7ED; border: 1px solid #FED7AA; }}
.fp-fix    {{ background: {PALETTE['blue_bg']}; border: 1px solid {PALETTE['card_border']}; border-left: 4pt solid {PALETTE['blue_accent']}; }}
.fp-impact-label, .fp-fix-label {{
  font-size: 7.5pt; letter-spacing: 1.3pt; text-transform: uppercase;
  font-weight: 700; margin-bottom: 3pt;
}}
.fp-impact-label {{ color: #9A3412; }}
.fp-fix-label    {{ color: {PALETTE['blue_accent']}; }}
.fp-impact-text, .fp-fix-text {{
  font-size: 9.5pt; line-height: 1.5; font-weight: 500;
}}
.fp-impact-text {{ color: #7C2D12; }}
.fp-fix-text    {{ color: {PALETTE['text_body']}; }}
.fp-meta-row {{
  display: flex; gap: 8pt; flex-wrap: wrap; margin-top: 4pt;
}}
.fp-effort, .fp-owner, .fp-time {{
  display: inline-block; padding: 4pt 10pt; border-radius: 999pt;
  font-size: 8.5pt; font-weight: 700;
}}
.fp-effort {{ background: {PALETTE['delta_green_bg']}; color: {PALETTE['delta_green']}; }}
.fp-owner  {{ background: #E0E7FF; color: #3730A3; }}
.fp-time   {{ background: #FEF3C7; color: #92400E; }}

/* PAIRED CARDS - two fp-finding cards per A4 sheet. Identical design tokens
   (chips, callouts, pills); only the type scale compresses so a pair fits.
   A hairline divider separates the two cards on the sheet. */
.fp-stack {{ display: flex; flex-direction: column; gap: 0; }}
.fp-stack .fp-paired + .fp-paired {{
  border-top: 1px solid {PALETTE['card_border']};
  margin-top: 12pt; padding-top: 12pt;
}}
.fp-paired .fp-headline {{ font-size: 15pt; margin: 3pt 0 6pt 0; }}
.fp-paired .fp-desc {{ font-size: 9.5pt; line-height: 1.5; margin: 0 0 7pt 0; }}
.fp-paired .fp-callouts {{ gap: 8pt; margin: 0 0 7pt 0; }}
.fp-paired .fp-impact, .fp-paired .fp-fix {{ padding: 8pt 10pt; }}
.fp-paired .fp-impact-text, .fp-paired .fp-fix-text {{ font-size: 8.5pt; line-height: 1.45; }}
.fp-paired .fp-num {{ font-size: 8pt; }}
.fp-paired .fp-chips {{ margin: 2pt 0 6pt 0; }}
.fp-paired .fp-meta-row {{ margin-top: 2pt; }}
.fp-paired .fp-effort, .fp-paired .fp-owner {{ padding: 3pt 9pt; font-size: 8pt; }}

/* QUICK WINS (4 per page, expanded) */
.qw-list {{ margin: 6pt 0; }}
.qw-row {{
  display: grid; grid-template-columns: 28pt 1fr; gap: 10pt;
  padding: 7pt 12pt; margin-bottom: 6pt;
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 9pt;
  page-break-inside: avoid; break-inside: avoid;
}}
.qw-circle {{
  background: {PALETTE['blue_accent']}; color: #FFFFFF; width: 26pt; height: 26pt;
  border-radius: 50%; text-align: center; line-height: 26pt;
  font-size: 11pt; font-weight: 800;
}}
.qw-content {{ }}
.qw-content strong {{ display: block; font-size: 10pt; color: {PALETTE['navy_dark']}; margin-bottom: 2pt; }}
.qw-content .qw-desc {{ font-size: 9pt; color: {PALETTE['text_body']}; line-height: 1.45; }}

/* DIMENSION SECTION (2026-06-16 rev2: dense flow, no wasted space).
   Each dim starts on a fresh sheet via page-break-before:always but its
   content flows naturally. No opener pages, no isolated cards. */
.dim-section {{ page-break-before: always; break-before: page; }}
.dim-section:first-child {{ page-break-before: auto; }}

.dim-header-strip {{
  background: linear-gradient(135deg, #F8FAFC 0%, #FFFFFF 100%);
  border: 1px solid {PALETTE['card_border']};
  border-radius: 10pt; padding: 12pt 18pt; margin: 0 0 12pt 0;
  page-break-after: avoid; break-after: avoid;
}}
.dim-header-eyebrow {{
  font-family: 'JetBrains Mono', Consolas, monospace; font-size: 8.5pt;
  letter-spacing: 1.8pt; font-weight: 700; color: {PALETTE['blue_accent']};
  margin-bottom: 3pt;
}}
.dim-header-title {{
  font-size: 16pt; font-weight: 800; color: {PALETTE['navy_dark']};
  line-height: 1.2; margin: 2pt 0 8pt 0;
}}
.dim-header-meta {{ display: flex; gap: 10pt; flex-wrap: wrap; align-items: center; }}
.dim-stat {{
  font-size: 9.5pt; color: {PALETTE['text_body']};
  background: #FFFFFF; padding: 3pt 9pt; border-radius: 5pt;
  border: 1px solid {PALETTE['card_border']};
}}
.dim-stat strong {{ font-weight: 800; margin-right: 3pt; }}
.dim-stat.crit  strong {{ color: #991B1B; }}
.dim-stat.major strong {{ color: #92400E; }}
.dim-stat.minor strong {{ color: {PALETTE['text_muted']}; }}
.dim-score-chip {{
  font-size: 10pt; font-weight: 800; padding: 3pt 10pt; border-radius: 5pt;
  border: 1px solid; margin-left: auto;
}}
.dim-score-chip.good {{ background: #DCFCE7; color: #065F46; border-color: #BBF7D0; }}
.dim-score-chip.warn {{ background: #FEF3C7; color: #92400E; border-color: #FDE68A; }}
.dim-score-chip.crit {{ background: #FEE2E2; color: #991B1B; border-color: #FECACA; }}

.dim-sub-lead {{
  font-size: 9pt; letter-spacing: 1pt; text-transform: uppercase;
  color: {PALETTE['text_muted']}; font-weight: 700;
  margin: 12pt 0 6pt 0; padding-bottom: 4pt;
  border-bottom: 1px solid {PALETTE['card_border']};
  page-break-after: avoid; break-after: avoid;
}}

.passes-card {{
  margin: 14pt 0 0 0; padding: 12pt 16pt;
  background: linear-gradient(180deg, #ECFDF5 0%, #FFFFFF 100%);
  border: 1px solid #BBF7D0; border-radius: 8pt;
  page-break-inside: avoid; break-inside: avoid;
}}

/* CITATIONS / BUSINESS LISTINGS BLOCK (sits at the end of the off-page
   dimension flow). Snapshot card on top, priority directory table below. */
.cit-section {{ margin-top: 18pt; page-break-before: auto; }}
.cit-section-eyebrow {{
  font-family: 'JetBrains Mono', Consolas, monospace; font-size: 8.5pt;
  letter-spacing: 1.8pt; font-weight: 700; color: {PALETTE['blue_accent']};
  margin-bottom: 4pt;
}}
.cit-section-title {{
  font-size: 15pt; font-weight: 800; color: {PALETTE['navy_dark']};
  line-height: 1.2; margin: 2pt 0 8pt 0;
}}
.cit-section-lead {{
  font-size: 9.5pt; color: {PALETTE['text_body']}; line-height: 1.6;
  margin: 0 0 12pt 0;
}}

.cit-summary-card {{
  background: linear-gradient(180deg, #F0F9FF 0%, #FFFFFF 100%);
  border: 1px solid {PALETTE['card_border']}; border-radius: 10pt;
  padding: 12pt 14pt; margin: 0 0 14pt 0;
  page-break-inside: avoid; break-inside: avoid;
}}
.cit-summary-eyebrow {{
  font-size: 8pt; letter-spacing: 1.2pt; text-transform: uppercase;
  color: {PALETTE['text_muted']}; font-weight: 700; margin-bottom: 6pt;
}}
.cit-summary-row {{ display: flex; gap: 12pt; flex-wrap: wrap; }}
.cit-summary-stat {{
  flex: 1; min-width: 100pt;
  background: #FFFFFF; border: 1px solid {PALETTE['card_border']};
  border-radius: 8pt; padding: 8pt 10pt; text-align: left;
}}
.cit-summary-stat .cit-stat-val {{ font-size: 18pt; font-weight: 800; color: {PALETTE['navy_dark']}; line-height: 1; }}
.cit-summary-stat .cit-stat-lbl {{ font-size: 8.5pt; color: {PALETTE['text_muted']}; margin-top: 4pt; letter-spacing: 0.3pt; }}
.cit-summary-stat.good .cit-stat-val {{ color: #065F46; }}
.cit-summary-stat.warn .cit-stat-val {{ color: #92400E; }}
.cit-summary-stat.crit .cit-stat-val {{ color: #991B1B; }}

.cit-priority-lead {{
  font-size: 11pt; font-weight: 700; color: {PALETTE['navy_dark']};
  margin: 8pt 0 4pt 0;
}}
.cit-priority-sub {{
  font-size: 9pt; color: {PALETTE['text_muted']}; line-height: 1.55;
  margin: 0 0 8pt 0;
}}

.cit-table {{
  width: 100%; border-collapse: collapse; font-size: 9pt;
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 8pt; overflow: hidden;
}}
.cit-table thead th {{
  background: #F1F5F9; color: {PALETTE['navy_dark']};
  font-size: 8pt; letter-spacing: 0.8pt; text-transform: uppercase;
  font-weight: 700; padding: 6pt 10pt; text-align: left;
  border-bottom: 1px solid {PALETTE['card_border']};
}}
.cit-table tbody td {{
  padding: 6pt 10pt; border-bottom: 1px solid #F1F5F9;
  vertical-align: top; line-height: 1.45;
}}
.cit-table tbody tr:last-child td {{ border-bottom: none; }}
.cit-table tr {{ page-break-inside: avoid; break-inside: avoid; }}
.cit-table .cit-dr {{
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-weight: 800; color: {PALETTE['blue_accent']}; text-align: right;
  white-space: nowrap; width: 36pt;
}}
.cit-cat-chip {{
  display: inline-block; padding: 1pt 7pt; border-radius: 4pt;
  font-size: 7.5pt; letter-spacing: 0.8pt; text-transform: uppercase;
  font-weight: 700; white-space: nowrap;
}}
.cit-cat-anchor          {{ background: #FEE2E2; color: #991B1B; }}
.cit-cat-aggregator      {{ background: #DBEAFE; color: #1E40AF; }}
.cit-cat-top-citation    {{ background: #E0E7FF; color: #3730A3; }}
.cit-cat-brand-booster   {{ background: #FAE8FF; color: #6B21A8; }}
.cit-cat-trust-signal    {{ background: #DCFCE7; color: #065F46; }}

/* Per-citation status chip (used in the Citation Audit table). */
.cit-status-chip {{
  display: inline-block; padding: 2pt 8pt; border-radius: 4pt;
  font-size: 7.5pt; letter-spacing: 0.6pt; text-transform: uppercase;
  font-weight: 700; white-space: nowrap;
}}
.cit-status-chip.good {{ background: #DCFCE7; color: #065F46; border: 1px solid #BBF7D0; }}
.cit-status-chip.warn {{ background: #FEF3C7; color: #92400E; border: 1px solid #FDE68A; }}
.cit-status-chip.crit {{ background: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5; }}

/* GMB self-audit checklist grid (mirrors the xlsx "Audit" tab) */
.gmb-checklist-grid {{
  display: grid; grid-template-columns: 1fr 1fr; gap: 12pt;
  margin: 0 0 14pt 0;
}}
.gmb-check-group {{
  background: {PALETTE['card_bg']};
  border: 1px solid {PALETTE['card_border']};
  border-left: 3pt solid {PALETTE['blue_accent']};
  border-radius: 8pt; padding: 10pt 14pt;
  page-break-inside: avoid; break-inside: avoid;
}}
.gmb-check-group-title {{
  font-size: 10pt; font-weight: 800; color: {PALETTE['navy_dark']};
  letter-spacing: 0.4pt; margin: 0 0 7pt 0;
}}
.gmb-check-list {{ list-style: none; padding: 0; margin: 0; }}
.gmb-check-list li {{
  display: grid; grid-template-columns: 12pt 1fr; gap: 6pt;
  font-size: 8.5pt; line-height: 1.5; color: {PALETTE['text_body']};
  margin-bottom: 4pt; align-items: start;
}}
.gmb-check-box {{
  display: inline-block; width: 10pt; height: 10pt;
  border: 1pt solid {PALETTE['card_border']}; border-radius: 2pt;
  background: #FFFFFF; margin-top: 2pt;
}}
.passes-card-head {{
  font-size: 10pt; font-weight: 700; color: #065F46;
  letter-spacing: 0.4pt; margin-bottom: 6pt;
}}
.passes-list {{ margin: 0; padding: 0 0 0 16pt; }}
.passes-list li {{ font-size: 9.5pt; color: {PALETTE['text_body']}; line-height: 1.5; margin-bottom: 3pt; }}
.passes-empty {{ font-size: 9.5pt; color: {PALETTE['text_muted']}; font-style: italic; }}

.exec-summary-card {{
  background: linear-gradient(180deg, #F0F9FF 0%, #FFFFFF 100%);
  border: 1px solid {PALETTE['card_border']}; border-radius: 12pt;
  padding: 24pt 30pt; margin: 14pt 0;
}}
.exec-summary-card p {{
  font-size: 12pt; color: {PALETTE['text_body']}; line-height: 1.75;
  margin: 0 0 10pt 0;
}}
.exec-summary-card p:last-child {{ margin-bottom: 0; }}

.strat-card {{
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-left: 4pt solid {PALETTE['blue_accent']};
  border-radius: 10pt; padding: 14pt 20pt; margin: 12pt 0;
}}
.strat-card-title {{
  font-size: 13pt; font-weight: 700; color: {PALETTE['navy_dark']};
  margin: 0 0 8pt 0;
}}
.strat-card-body p {{ font-size: 10.5pt; color: {PALETTE['text_body']}; line-height: 1.65; margin: 0 0 6pt 0; }}
.strat-list {{ margin: 4pt 0 0 0; padding-left: 20pt; }}
.strat-list li {{ font-size: 10.5pt; color: {PALETTE['text_body']}; line-height: 1.55; margin-bottom: 4pt; }}

.cta-card {{
  margin-top: 20pt; padding: 22pt 30pt;
  background: linear-gradient(135deg, {PALETTE['navy_dark']} 0%, {PALETTE['navy_mid']} 100%);
  color: #FFFFFF; border-radius: 14pt;
  page-break-inside: avoid; break-inside: avoid;
}}
.cta-card-title {{
  font-size: 22pt; font-weight: 800; color: #FFFFFF;
  margin: 0 0 14pt 0; line-height: 1.2;
}}
.cta-card-body p {{
  font-size: 11pt; color: #E0E7FF; line-height: 1.7;
  margin: 0 0 10pt 0;
}}
.cta-card-body p:last-child {{ margin-bottom: 0; color: #BAE6FD; font-weight: 600; }}

/* SPRINT (1 per page) */
.sprint-page {{ page-break-inside: avoid; max-height: 245mm; overflow: hidden; }}
.sprint-header {{
  background: linear-gradient(135deg, {PALETTE['navy_dark']} 0%, {PALETTE['navy_mid']} 100%);
  color: #FFFFFF; padding: 14pt 22pt; border-radius: 12pt; margin: 4pt 0 10pt 0;
}}
.sprint-num {{
  display: inline-block; background: rgba(14,165,233,0.25); border: 1px solid rgba(14,165,233,0.6);
  color: #FFFFFF; padding: 2pt 10pt; border-radius: 5pt;
  font-family: 'JetBrains Mono', Consolas, monospace; font-size: 8.5pt;
  letter-spacing: 1.5pt; font-weight: 700; margin-bottom: 6pt;
}}
.sprint-title {{ font-size: 18pt; font-weight: 800; line-height: 1.15; margin: 3pt 0 6pt 0; color: #FFFFFF; }}
.sprint-tag {{ font-size: 10pt; color: #BAE6FD; }}
.sprint-section {{ margin: 10pt 0; }}
.sprint-section h4 {{
  font-size: 11pt; font-weight: 700; color: {PALETTE['navy_dark']};
  margin-bottom: 8pt; letter-spacing: 0.4pt;
}}
.sprint-desc {{
  font-size: 10.5pt; color: {PALETTE['text_body']}; line-height: 1.7;
  background: #F8FAFC; border-left: 4px solid {PALETTE['blue_accent']};
  padding: 12pt 16pt; border-radius: 0 8pt 8pt 0;
}}
.deliv-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10pt; margin-top: 8pt; }}
.deliv-card {{
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 8pt; padding: 12pt 14pt;
}}
.deliv-card .dc-bullet {{
  display: inline-block; background: {PALETTE['blue_accent']}; color: #FFFFFF;
  width: 18pt; height: 18pt; border-radius: 50%; text-align: center;
  line-height: 18pt; font-size: 9pt; font-weight: 800; margin-right: 6pt;
}}
.deliv-card .dc-text {{ font-size: 10pt; color: {PALETTE['text_body']}; line-height: 1.55; }}

/* ISSUE DASHBOARD (the "scare page") - SEMrush-style issue inventory.
   Lives at the top of the report so the client sees ALL issues + severity
   counts + alarm framing in the first 5 seconds of reading. */
.dash-hero {{
  background: linear-gradient(135deg, {PALETTE['navy_dark']} 0%, {PALETTE['navy_mid']} 100%);
  color: #FFFFFF; padding: 14pt 20pt 13pt 20pt; border-radius: 12pt;
  margin: 0 0 8pt 0;
}}
.dash-hero-eyebrow {{
  font-size: 8pt; letter-spacing: 2pt; text-transform: uppercase;
  font-weight: 700; color: #BAE6FD; margin-bottom: 4pt;
}}
.dash-hero-title {{
  font-size: 17pt; font-weight: 800; line-height: 1.15; color: #FFFFFF;
  margin: 0 0 5pt 0;
}}
.dash-hero-sub {{ font-size: 9pt; color: #E2E8F0; line-height: 1.4; }}
.dash-hero-counts {{
  display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8pt;
  margin-top: 9pt;
}}
.dash-count-tile {{
  background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.18);
  border-radius: 8pt; padding: 6pt 8pt; text-align: center;
}}
.dash-count-num {{ font-size: 20pt; font-weight: 800; line-height: 1.0; color: #FFFFFF; }}
.dash-count-label {{
  font-size: 7.5pt; letter-spacing: 1.3pt; text-transform: uppercase;
  color: #BAE6FD; margin-top: 4pt; font-weight: 600;
}}
.dash-count-tile.crit .dash-count-num {{ color: #FCA5A5; }}
.dash-count-tile.major .dash-count-num {{ color: #FCD34D; }}
.dash-count-tile.minor .dash-count-num {{ color: #93C5FD; }}
.dash-count-tile.ok .dash-count-num {{ color: #86EFAC; }}

/* Issue category list - 6 rows, one per section, with severity-breakdown chips. */
.dash-issue-list {{
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 10pt; padding: 0; margin: 6pt 0 0 0;
}}
.dash-issue-row {{
  display: grid; grid-template-columns: 1fr 70pt 70pt 70pt 70pt;
  align-items: center; padding: 11pt 16pt;
  border-bottom: 1px solid {PALETTE['card_border']};
}}
.dash-issue-row:last-child {{ border-bottom: none; }}
.dash-issue-row.head {{
  background: #F8FAFC;
  font-size: 8pt; letter-spacing: 1.3pt; text-transform: uppercase;
  color: {PALETTE['text_muted']}; font-weight: 700; padding: 7pt 16pt;
}}
.dash-issue-row.head > div:not(:first-child) {{ text-align: center; }}
.dash-issue-name {{ font-size: 11pt; font-weight: 700; color: {PALETTE['navy_dark']}; }}
.dash-issue-name .dash-issue-hint {{
  display: block; font-size: 8.5pt; font-weight: 500;
  color: {PALETTE['text_muted']}; margin-top: 2pt; letter-spacing: 0;
}}
.dash-issue-cell {{ text-align: center; font-size: 12pt; font-weight: 800; }}
.dash-issue-cell.zero {{ color: #94A3B8; font-weight: 600; }}
.dash-issue-cell.crit  {{ color: #B91C1C; }}
.dash-issue-cell.major {{ color: #92400E; }}
.dash-issue-cell.minor {{ color: {PALETTE['blue_accent']}; }}
.dash-issue-cell.score {{
  color: {PALETTE['navy_dark']}; font-size: 13pt;
}}
.dash-issue-cell.score.crit  {{ color: #B91C1C; }}
.dash-issue-cell.score.major {{ color: #92400E; }}
.dash-issue-cell.score.good  {{ color: {PALETTE['delta_green']}; }}

/* SEMrush-style severity chip used inline anywhere we list a finding. */
.sev-chip {{
  display: inline-block; padding: 3pt 8pt; border-radius: 4pt;
  font-size: 7.5pt; letter-spacing: 1pt; text-transform: uppercase;
  font-weight: 700; vertical-align: middle;
}}
.sev-chip.crit  {{ background: #FEE2E2; color: #B91C1C; border: 1px solid #FCA5A5; }}
.sev-chip.major {{ background: #FEF3C7; color: #92400E; border: 1px solid #FCD34D; }}
.sev-chip.minor {{ background: #DBEAFE; color: #1E40AF; border: 1px solid #93C5FD; }}
.sev-chip.info  {{ background: #F1F5F9; color: {PALETTE['text_muted']}; border: 1px solid {PALETTE['card_border']}; }}

/* PROBLEM INDEX (page 2) - a table-of-contents of problems. Each row is one
   problem in a single line + an area chip + the page number it's covered on. */
.idx-list {{
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 10pt; padding: 2pt 0; margin: 6pt 0 0 0;
}}
.idx-row {{
  display: grid; grid-template-columns: 56pt 1fr 76pt 32pt;
  align-items: center; gap: 6pt;
  padding: 2.5pt 12pt; border-bottom: 1px solid #F1F5F9;
}}
.idx-row:last-child {{ border-bottom: none; }}
.idx-row.head {{
  border-bottom: 1.5px solid {PALETTE['card_border']};
  font-size: 7pt; letter-spacing: 1.2pt; text-transform: uppercase;
  color: {PALETTE['text_muted']}; font-weight: 700;
}}
.idx-row.head .idx-area, .idx-row.head .idx-page {{ text-align: right; }}
.idx-group-label {{
  padding: 5pt 14pt 2pt 14pt; font-size: 8pt; letter-spacing: 1.4pt;
  text-transform: uppercase; font-weight: 700; color: {PALETTE['blue_accent']};
}}
.idx-sev {{ justify-self: start; }}
.idx-problem {{ font-size: 8.5pt; color: {PALETTE['navy_dark']}; font-weight: 600; line-height: 1.25; }}
.idx-area {{ text-align: right; }}
.idx-page {{
  text-align: right; font-size: 9.5pt; font-weight: 800;
  color: {PALETTE['blue_accent']}; font-family: 'JetBrains Mono', Consolas, monospace;
}}

/* Area chips (the "status" tag the client asked for: On-page / Off-page / ...) */
.area-chip {{
  display: inline-block; padding: 2pt 7pt; border-radius: 4pt;
  font-size: 7pt; letter-spacing: 0.8pt; text-transform: uppercase;
  font-weight: 700; white-space: nowrap;
}}
.area-strategy  {{ background: #EDE9FE; color: #5B21B6; }}
.area-content   {{ background: #FEF3C7; color: #92400E; }}
.area-onpage    {{ background: #DBEAFE; color: #1E40AF; }}
.area-technical {{ background: #E0F2FE; color: #075985; }}
.area-offpage   {{ background: #DCFCE7; color: #166534; }}
.area-geo       {{ background: #FCE7F3; color: #9D174D; }}

/* COMPLETE ISSUE REGISTER - lead band on the first page of each register block. */
.reg-lead {{ margin: 0 0 10pt 0; }}
.reg-lead-eyebrow {{
  font-size: 8pt; letter-spacing: 1.4pt; text-transform: uppercase;
  font-weight: 700; color: {PALETTE['blue_accent']}; margin-bottom: 4pt;
}}
.reg-lead-title {{
  font-size: 15pt; font-weight: 800; color: {PALETTE['navy_dark']}; line-height: 1.25;
}}
.reg-lead-sub {{
  font-size: 9pt; color: {PALETTE['text_muted']}; line-height: 1.5; margin-top: 5pt;
}}

/* Compact issue card (SEMrush-style) - stacked 3-6 per page. */
.iss-stack {{ display: flex; flex-direction: column; gap: 8pt; margin: 6pt 0; }}
.iss-card {{
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-left: 5pt solid {PALETTE['blue_accent']};
  border-radius: 6pt; padding: 9pt 12pt;
  page-break-inside: avoid;
}}
.reg-cards .iss-card {{ margin-bottom: 8pt; }}
.iss-card .iss-card-head {{ margin-bottom: 4pt; }}
.iss-card.crit  {{ border-left-color: #B91C1C; }}
.iss-card.major {{ border-left-color: #D97706; }}
.iss-card.minor {{ border-left-color: {PALETTE['blue_accent']}; }}
.iss-card-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 10pt; margin-bottom: 6pt; }}
.iss-card-title {{
  font-size: 12pt; font-weight: 800; color: {PALETTE['navy_dark']};
  line-height: 1.25; flex: 1;
}}
.iss-card-count {{
  font-size: 18pt; font-weight: 800; color: #B91C1C; line-height: 1.0; white-space: nowrap;
}}
.iss-card-body {{ font-size: 9.5pt; color: {PALETTE['text_body']}; line-height: 1.5; }}
.iss-card-body strong {{ color: {PALETTE['navy_dark']}; }}
.iss-card-meta {{
  display: flex; gap: 8pt; flex-wrap: wrap;
  margin-top: 8pt; font-size: 8pt;
}}
.iss-meta-cost {{ background: #FEF2F2; color: #B91C1C; padding: 3pt 8pt; border-radius: 4pt; }}
.iss-meta-fix  {{ background: {PALETTE['blue_bg']}; color: {PALETTE['blue_accent']}; padding: 3pt 8pt; border-radius: 4pt; }}
.iss-meta-effort {{ background: {PALETTE['delta_green_bg']}; color: {PALETTE['delta_green']}; padding: 3pt 8pt; border-radius: 4pt; }}

/* MARKDOWN TABLE - rendered when a section's body has a |col|col| block.
   SEMrush-style: rounded card frame, soft header band, severity chips in
   cells. Used everywhere except the URL appendix (which has its own style). */
.md-table {{
  width: 100%; border-collapse: separate; border-spacing: 0;
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 8pt; overflow: hidden;
  font-size: 9.5pt; margin: 8pt 0 12pt 0;
  /* Keep the whole table on one page. If it does not fit, the multi-page
     section splitter has already put it on its own page. */
  page-break-inside: avoid; break-inside: avoid;
}}
.md-table tr, .md-table thead, .md-table tbody {{
  page-break-inside: avoid; break-inside: avoid;
}}
.md-table th {{
  background: #F8FAFC;
  padding: 8pt 11pt; text-align: left; vertical-align: bottom;
  font-size: 8pt; letter-spacing: 1.1pt; text-transform: uppercase;
  color: {PALETTE['text_muted']}; font-weight: 700;
  border-bottom: 2px solid {PALETTE['card_border']};
}}
.md-table td {{
  padding: 8pt 11pt; vertical-align: top;
  color: {PALETTE['text_body']}; line-height: 1.45;
  border-bottom: 1px solid #F1F5F9;
}}
.md-table tr:last-child td {{ border-bottom: none; }}
.md-table tr:nth-child(even) td {{ background: #FBFCFD; }}
.md-table td:first-child {{ font-weight: 600; color: {PALETTE['navy_dark']}; }}

/* REGISTER FLOW - one continuous block that auto-paginates across as many
   physical pages as the issue count needs. Unlike .page it has no min-height
   and no page-break-inside:avoid, so cards/rows pack naturally and break
   cleanly between items (no half-empty overflow slivers). */
.reg-flow {{ page-break-after: always; }}
.reg-flow:last-child {{ page-break-after: auto; break-after: auto; }}
.reg-cards .iss-card {{ margin-bottom: 10pt; }}

/* Elegant card-treatment for rich fp-finding cards inside the dimension
   flow. Each issue gets its own white card with rounded corners, a thin
   border, internal padding, and a clear gap below. Sized so 3 cards fit
   per A4 page (was 2 - the user asked for denser packing). */
.reg-cards .fp-finding.fp-paired {{
  background: #FFFFFF;
  border: 1px solid {PALETTE['card_border']};
  border-radius: 10pt;
  padding: 11pt 14pt 9pt 14pt;
  margin-bottom: 10pt;
  box-shadow: 0 1pt 2pt rgba(15, 23, 42, 0.04);
}}
.reg-cards .fp-finding.fp-paired:last-child {{ margin-bottom: 0; }}
.reg-cards .fp-finding.fp-paired + .fp-finding.fp-paired {{
  border-top: 1px solid {PALETTE['card_border']};
  margin-top: 0;
  padding-top: 11pt;
}}
/* Tightened internal typography so 3 cards stack inside one A4 page
   without crowding. Type scale shrinks slightly; gaps stay readable. */
.reg-cards .fp-finding.fp-paired .fp-num     {{ font-size: 7.5pt; margin-bottom: 3pt; }}
.reg-cards .fp-finding.fp-paired .fp-chips   {{ margin: 3pt 0 6pt 0; gap: 5pt; }}
.reg-cards .fp-finding.fp-paired .chip       {{ padding: 2pt 7pt; font-size: 7pt; }}
.reg-cards .fp-finding.fp-paired .fp-headline {{ font-size: 12.5pt; line-height: 1.2; margin: 2pt 0 5pt 0; }}
.reg-cards .fp-finding.fp-paired .fp-desc    {{ font-size: 8.5pt; line-height: 1.45; margin: 0 0 7pt 0; }}
.reg-cards .fp-finding.fp-paired .fp-callouts {{ gap: 8pt; margin: 0 0 7pt 0; }}
.reg-cards .fp-finding.fp-paired .fp-impact,
.reg-cards .fp-finding.fp-paired .fp-fix    {{ padding: 7pt 10pt; }}
.reg-cards .fp-finding.fp-paired .fp-impact-label,
.reg-cards .fp-finding.fp-paired .fp-fix-label {{ font-size: 6.5pt; letter-spacing: 1.1pt; margin-bottom: 2pt; }}
.reg-cards .fp-finding.fp-paired .fp-impact-text,
.reg-cards .fp-finding.fp-paired .fp-fix-text {{ font-size: 8pt; line-height: 1.4; }}
.reg-cards .fp-finding.fp-paired .fp-meta-row {{ margin-top: 4pt; gap: 8pt; }}
.reg-cards .fp-finding.fp-paired .fp-effort,
.reg-cards .fp-finding.fp-paired .fp-owner   {{ padding: 2pt 8pt; font-size: 7.5pt; }}
/* The minor checklist table must be allowed to break across pages (it can run
   40+ rows); keep individual rows intact and repeat the header each page. */
.md-table.reg-min-table {{ page-break-inside: auto; break-inside: auto; }}
.md-table.reg-min-table thead {{ display: table-header-group; }}
.md-table.reg-min-table tr {{ page-break-inside: avoid; break-inside: avoid; }}

/* Severity / status chips inside table cells. Compact - sized for cell text. */
.cell-chip {{
  display: inline-block;
  padding: 2pt 7pt; border-radius: 4pt;
  font-size: 7.5pt; letter-spacing: 0.8pt;
  text-transform: uppercase; font-weight: 700;
  white-space: nowrap; vertical-align: middle;
}}
.cell-chip.crit  {{ background: #FEE2E2; color: #B91C1C; border: 1px solid #FCA5A5; }}
.cell-chip.major {{ background: #FEF3C7; color: #92400E; border: 1px solid #FCD34D; }}
.cell-chip.minor {{ background: #DBEAFE; color: #1E40AF; border: 1px solid #93C5FD; }}
.cell-chip.good  {{ background: #DCFCE7; color: #14532D; border: 1px solid #86EFAC; }}
.cell-chip.info  {{ background: #F1F5F9; color: {PALETTE['text_muted']}; border: 1px solid {PALETTE['card_border']}; }}

/* URL appendix table */
.url-table {{
  width: 100%; border-collapse: collapse; font-size: 8.5pt;
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 8pt; overflow: hidden;
}}
.url-table th {{
  background: #F8FAFC; padding: 7pt 10pt; text-align: left;
  font-size: 7.5pt; letter-spacing: 1.2pt; text-transform: uppercase;
  color: {PALETTE['text_muted']}; font-weight: 700;
  border-bottom: 1px solid {PALETTE['card_border']};
}}
.url-table td {{
  padding: 3pt 9pt;
  border-bottom: 1px solid #F1F5F9;
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 7.5pt; color: {PALETTE['text_body']};
}}
.url-table tr:last-child td {{ border-bottom: none; }}
.url-table td.status {{ font-family: 'Inter', Arial; font-weight: 700; }}
.url-table td.status.ok  {{ color: {PALETTE['delta_green']}; }}
.url-table td.status.bad {{ color: #B91C1C; }}

/* AI VISIBILITY */
.ai-card {{
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 10pt; padding: 16pt 20pt; margin: 4pt 0 12pt 0;
}}
.ai-row {{
  display: grid; grid-template-columns: 110pt 1fr 100pt; gap: 12pt;
  align-items: center; padding: 10pt 0;
  border-bottom: 1px dashed {PALETTE['card_border']};
}}
.ai-row:last-child {{ border-bottom: none; }}
.ai-label {{ font-size: 10pt; font-weight: 600; color: {PALETTE['navy_dark']}; }}
.ai-track {{ width: 100%; height: 8pt; background: #E2E8F0; border-radius: 4pt; overflow: hidden; }}
.ai-fill {{ height: 100%; background: {PALETTE['blue_accent']}; border-radius: 4pt; }}
.ai-meta {{ font-size: 9pt; color: {PALETTE['text_label']}; text-align: right; font-weight: 600; }}

/* LOCAL / CONTENT SNAPSHOT GRID */
.snap-grid {{
  display: grid; grid-template-columns: 1fr 1fr; gap: 12pt; margin: 6pt 0;
}}
.snap-card {{
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 10pt; padding: 14pt 16pt;
}}
.snap-card h4 {{ font-size: 11.5pt; font-weight: 700; color: {PALETTE['navy_dark']}; margin: 0 0 8pt 0; }}
.snap-card p {{ font-size: 10pt; color: {PALETTE['text_body']}; line-height: 1.6; margin: 0 0 6pt 0; }}
.snap-card ul {{ margin: 4pt 0 0 16pt; padding: 0; font-size: 9.5pt; color: {PALETTE['text_body']}; }}
.snap-card li {{ margin: 3pt 0; line-height: 1.5; }}

/* CHART PRIMITIVES - stat strip (3-4 tile metric row).
   Used on every late page so the reader always sees numbers near the top of
   the page, not just a wall of prose. */
.ssv-strip {{
  display: grid; gap: 8pt; margin: 6pt 0 14pt 0;
}}
.ssv-cols-1 {{ grid-template-columns: 1fr; }}
.ssv-cols-2 {{ grid-template-columns: 1fr 1fr; }}
.ssv-cols-3 {{ grid-template-columns: 1fr 1fr 1fr; }}
.ssv-cols-4 {{ grid-template-columns: 1fr 1fr 1fr 1fr; }}
.ssv-tile {{
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 8pt; padding: 10pt 12pt;
  border-left: 3px solid {PALETTE['blue_accent']};
}}
.ssv-label {{
  font-size: 7pt; letter-spacing: 1.3pt; text-transform: uppercase;
  color: {PALETTE['text_muted']}; font-weight: 600; margin-bottom: 3pt;
}}
.ssv-value {{ font-size: 19pt; font-weight: 800; color: {PALETTE['navy_dark']}; line-height: 1.0; }}
.ssv-suffix {{ font-size: 11pt; font-weight: 600; color: {PALETTE['text_muted']}; margin-left: 2pt; }}
.ssv-delta {{
  display: inline-block; margin-top: 5pt; padding: 2pt 8pt;
  border-radius: 999pt; font-size: 7.5pt; font-weight: 700;
}}
.ssv-delta-good {{ background: {PALETTE['delta_green_bg']}; color: {PALETTE['delta_green']}; }}
.ssv-delta-warn {{ background: #FEF3C7; color: #92400E; }}
.ssv-delta-crit {{ background: #FEE2E2; color: #B91C1C; }}
.ssv-delta-dim  {{ background: #F1F5F9; color: {PALETTE['text_muted']}; }}

/* CHART CARD - generic wrapper for inline SVG charts (sparkline + bar + donut). */
.chart-card {{
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 10pt; padding: 14pt 16pt; margin: 8pt 0;
}}
.chart-card h4 {{
  font-size: 10.5pt; font-weight: 700; color: {PALETTE['navy_dark']}; margin: 0 0 6pt 0;
}}
.chart-card .chart-sub {{
  font-size: 8.5pt; color: {PALETTE['text_muted']}; margin: 0 0 10pt 0; line-height: 1.45;
}}
.chart-card .chart-row {{ display: flex; align-items: center; gap: 14pt; }}
.chart-card .chart-row.center {{ justify-content: center; }}
.chart-card .chart-caption {{
  font-size: 9pt; color: {PALETTE['text_body']}; line-height: 1.55; flex: 1;
}}
.chart-grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10pt; }}
.chart-grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10pt; }}

/* MINI-DONUT cluster (used on deep-dive section pages). */
.donut-cluster {{
  display: flex; gap: 12pt; justify-content: space-around; align-items: center;
  background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
  border-radius: 10pt; padding: 12pt; margin: 6pt 0 12pt 0;
}}
.donut-cluster-item {{ text-align: center; }}
.donut-cluster-item .dci-label {{
  font-size: 7.5pt; letter-spacing: 1.2pt; text-transform: uppercase;
  color: {PALETTE['text_muted']}; font-weight: 600; margin-top: 4pt;
}}

/* SECTION DEEP-DIVE pages (full mode only)
   Visually matches the snap-card / barrow-card / why-card system used by
   the rest of the PDF so the layout never feels like a different document. */
.dd-card {{
  background: {PALETTE['card_bg']};
  border: 1px solid {PALETTE['card_border']};
  border-radius: 10pt;
  padding: 16pt 20pt;
  margin: 4pt 0 12pt 0;
  page-break-inside: avoid; break-inside: avoid;
}}
.dd-body {{ font-size: 10.5pt; color: {PALETTE['text_body']}; line-height: 1.65; }}
.dd-body p {{
  margin: 0 0 8pt 0;
  /* Keep individual paragraphs intact - never split mid-paragraph. */
  page-break-inside: avoid; break-inside: avoid;
  orphans: 3; widows: 3;
}}
.dd-body p strong {{ color: {PALETTE['navy_dark']}; font-weight: 700; }}
.dd-body h4.dd-subh {{
  font-size: 11.5pt; font-weight: 700; color: {PALETTE['navy_dark']};
  margin: 12pt 0 6pt 0; padding-left: 9pt;
  border-left: 3px solid {PALETTE['blue_accent']};
  line-height: 1.3;
  /* Keep a sub-heading welded to the paragraph that follows it. Without
     this, headings end up at the bottom of one page with the paragraph
     starting on the next - the "concatenation feel" the client flagged. */
  page-break-after: avoid; break-after: avoid;
  page-break-inside: avoid; break-inside: avoid;
}}
.dd-body h4.dd-subh:first-child {{ margin-top: 0; }}
/* Lists use the same indented, muted-marker style as snap-card lists. */
.dd-body ul.dd-list, .dd-body ol.dd-list {{
  margin: 6pt 0 10pt 18pt; padding: 0;
  /* Lists should stay together as a unit when possible. */
  page-break-inside: avoid; break-inside: avoid;
}}
.dd-body .dd-list li {{
  margin: 5pt 0; line-height: 1.55; font-size: 10pt; color: {PALETTE['text_body']};
  page-break-inside: avoid; break-inside: avoid;
}}
/* Bold-label fields look like the why-card callouts that already exist
   elsewhere in the PDF - blue accent on the left, faint blue background. */
.dd-body p.dd-field {{
  background: {PALETTE['blue_bg']};
  border-left: 4px solid {PALETTE['blue_accent']};
  padding: 9pt 14pt; border-radius: 0 6pt 6pt 0;
  margin: 0 0 10pt 0; font-size: 10pt; line-height: 1.55;
}}

/* CLOSING CTA */
.cta-block {{
  background: linear-gradient(135deg, {PALETTE['navy_dark']} 0%, {PALETTE['navy_mid']} 100%);
  color: #FFFFFF; padding: 40pt 32pt; border-radius: 14pt; margin-top: 14pt;
}}
.cta-eyebrow {{ color: {PALETTE['blue_accent']}; font-size: 9pt; letter-spacing: 2pt; font-weight: 700; text-transform: uppercase; }}
.cta-title {{ font-size: 24pt; font-weight: 800; line-height: 1.15; margin: 10pt 0 14pt 0; color: #FFFFFF; }}
.cta-body {{ font-size: 10.5pt; color: #CBD5E1; line-height: 1.7; margin: 0 0 14pt 0; }}
.cta-list {{ margin: 8pt 0 0 0; padding: 0; list-style: none; }}
.cta-list li {{ font-size: 10.5pt; color: #E2E8F0; padding: 4pt 0 4pt 22pt; position: relative; line-height: 1.55; }}
.cta-list li:before {{ content: "→"; color: {PALETTE['blue_accent']}; position: absolute; left: 4pt; font-weight: 800; }}
"""


HEADER_HTML = """
<div style="font-family: 'Inter', 'Segoe UI', Arial, sans-serif; width: 100%; height: 18mm; padding: 0 14mm; box-sizing: border-box; font-size: 9.5pt; color: #FFFFFF; background: __NAVY__; -webkit-print-color-adjust: exact; display: flex; justify-content: space-between; align-items: center;">
  <div style="line-height: 1.25;">
    <div style="font-weight: 800; letter-spacing: 1.3pt; text-transform: uppercase; font-size: 9pt;">__CLIENT_CAPS__</div>
    <div style="font-weight: 500; letter-spacing: 1.1pt; text-transform: uppercase; font-size: 7pt; color: __ACCENT__; opacity: 0.95; margin-top: 2pt;">__CLIENT_META__</div>
  </div>
  <div style="line-height: 1.25; text-align: right;">
    <div style="font-weight: 700; font-size: 9.5pt;">__REPORT_TITLE__</div>
    <div style="font-weight: 400; font-size: 7.5pt; color: #CBD5E1; margin-top: 2pt;">__REPORT_DATE__</div>
  </div>
</div>
"""

FOOTER_HTML = """
<div style="font-family: 'Inter', 'Segoe UI', Arial, sans-serif; width: 100%; height: 16mm; padding: 0 14mm; box-sizing: border-box; font-size: 8pt; color: #FFFFFF; background: __NAVY__; -webkit-print-color-adjust: exact; display: flex; justify-content: space-between; align-items: center;">
  <div style="font-weight: 700; letter-spacing: 0.5pt;"><span style="color: __ACCENT__;">__BRAND__</span> __BRAND_SUFFIX__</div>
  <div style="opacity: 0.85; font-size: 7.5pt;">__FOOTER_CENTER__</div>
  <div style="opacity: 0.9; font-size: 7.5pt;"><span class="pageNumber"></span> / <span class="totalPages"></span></div>
</div>
"""


# ============================================================
# SVG donut gauge
# ============================================================

def svg_donut(score: float | None, label: str = "OVERALL SCORE") -> str:
    radius = 48
    cx, cy = 65, 65
    stroke_w = 12
    if score is None:
        pct, color, display = 0.0, "#94A3B8", "n/a"
    else:
        pct = max(0.0, min(100.0, float(score))) / 100.0
        # Color bands aligned with section-07 methodology: good >= 75,
        # needs-work 50-74, critical < 50. No decimals on heuristic composites.
        if   score >= 75: color = "#16A34A"
        elif score >= 50: color = "#F59E0B"
        else:             color = "#EF4444"
        display = f"{round(float(score)):d}"
    circumference = 2 * math.pi * radius
    dash = circumference * pct
    gap  = circumference - dash
    return f"""
<svg width="140" height="140" viewBox="0 0 130 130" xmlns="http://www.w3.org/2000/svg">
  <circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="#E2E8F0" stroke-width="{stroke_w}"/>
  <circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{color}" stroke-width="{stroke_w}"
          stroke-dasharray="{dash:.2f} {gap:.2f}" transform="rotate(-90 {cx} {cy})" stroke-linecap="round"/>
  <text x="{cx}" y="{cy+4}" text-anchor="middle" font-family="Inter, Arial" font-weight="800"
        font-size="26" fill="{PALETTE['navy_dark']}">{display}</text>
  <text x="{cx}" y="{cy+22}" text-anchor="middle" font-family="Inter, Arial" font-weight="600"
        font-size="7.5" fill="{PALETTE['text_muted']}" letter-spacing="1.4">{label}</text>
</svg>
"""


# ============================================================
# Chart primitives (for late-PDF density)
# These are deliberately tiny SVGs so they embed cleanly in WeasyPrint /
# Chromium PDF rendering without needing JS, web fonts, or external assets.
# Every primitive is self-contained and accepts only primitive types so it
# can be called from any page builder.
# ============================================================

def svg_mini_donut(value: int | float | None, *, label: str = "",
                   suffix: str = "", color: str | None = None,
                   size: int = 88) -> str:
    """Compact donut for inline use in stat strips. 0-100 value."""
    radius = size * 0.38
    cx = cy = size / 2
    stroke_w = size * 0.10
    if value is None:
        pct, display, c = 0.0, "n/a", "#94A3B8"
    else:
        v = float(value)
        pct = max(0.0, min(100.0, v)) / 100.0
        display = f"{v:.0f}{suffix}"
        if color:
            c = color
        elif v >= 75: c = "#16A34A"
        elif v >= 50: c = "#F59E0B"
        else: c = "#EF4444"
    circ = 2 * math.pi * radius
    dash = circ * pct
    gap = circ - dash
    value_size = size * 0.26
    label_size = size * 0.085
    return f"""
<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg">
  <circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="#E2E8F0" stroke-width="{stroke_w}"/>
  <circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{c}" stroke-width="{stroke_w}"
          stroke-dasharray="{dash:.2f} {gap:.2f}" transform="rotate(-90 {cx} {cy})" stroke-linecap="round"/>
  <text x="{cx}" y="{cy + value_size * 0.32}" text-anchor="middle" font-family="Inter, Arial" font-weight="800"
        font-size="{value_size:.1f}" fill="{PALETTE['navy_dark']}">{display}</text>
  {('<text x="' + str(cx) + '" y="' + str(cy + value_size * 0.32 + label_size * 1.6) + '" text-anchor="middle" font-family="Inter, Arial" font-weight="600" font-size="' + str(round(label_size, 1)) + '" fill="' + PALETTE['text_muted'] + '" letter-spacing="1.3">' + label.upper()[:18] + '</text>') if label else ''}
</svg>
"""


def svg_sparkline(values: list[float | int], *, width: int = 180,
                  height: int = 40, color: str | None = None,
                  fill: bool = True) -> str:
    """Small inline trend line. Auto-scales to min/max of values."""
    if not values or len(values) < 2:
        return ('<svg width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg">'
                '<rect x="0" y="0" width="{w}" height="{h}" fill="#F1F5F9"/>'
                '<text x="{x}" y="{y}" text-anchor="middle" font-size="9" fill="#64748B">no data</text>'
                '</svg>').format(w=width, h=height, x=width/2, y=height/2 + 3)
    vmin = min(values)
    vmax = max(values)
    span = (vmax - vmin) or 1.0
    pad_x = 4
    pad_y = 6
    inner_w = width - 2 * pad_x
    inner_h = height - 2 * pad_y
    pts = []
    for i, v in enumerate(values):
        x = pad_x + (i / (len(values) - 1)) * inner_w
        y = pad_y + (1 - (v - vmin) / span) * inner_h
        pts.append((x, y))
    line_path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    fill_path = line_path + f" L {pts[-1][0]:.1f} {height - pad_y:.1f} L {pts[0][0]:.1f} {height - pad_y:.1f} Z"
    last_v = values[-1]
    first_v = values[0]
    trend_color = color or (PALETTE['delta_green'] if last_v >= first_v else PALETTE['warn_red'])
    fill_id = f"sparkfill_{abs(hash((tuple(values), color))) % 100000}"
    return f"""
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="{fill_id}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{trend_color}" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="{trend_color}" stop-opacity="0.0"/>
    </linearGradient>
  </defs>
  {f'<path d="{fill_path}" fill="url(#{fill_id})" stroke="none"/>' if fill else ''}
  <path d="{line_path}" fill="none" stroke="{trend_color}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>
  <circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="2.5" fill="{trend_color}"/>
</svg>
"""


def svg_bar_chart(items: list[tuple[str, float]], *, width: int = 360,
                  height: int = 140, color: str | None = None,
                  max_value: float | None = None) -> str:
    """Horizontal bar chart with labels. Items = [(label, value), ...]."""
    if not items:
        return f'<svg width="{width}" height="{height}"></svg>'
    items = items[:6]
    bar_color = color or PALETTE['blue_accent']
    row_h = height / len(items)
    label_col = 95
    bar_max_w = width - label_col - 36
    real_max = max_value if max_value is not None else max((v for _, v in items), default=1) or 1
    rows = []
    for i, (label, value) in enumerate(items):
        y = i * row_h
        bar_w = max(2.0, (value / real_max) * bar_max_w)
        rows.append(
            f'<text x="{label_col - 6}" y="{y + row_h/2 + 4}" text-anchor="end" font-family="Inter, Arial" font-size="9" fill="{PALETTE["text_body"]}">{_html.escape(label[:20])}</text>'
            f'<rect x="{label_col}" y="{y + row_h/2 - 6}" width="{bar_max_w}" height="12" rx="3" fill="#F1F5F9"/>'
            f'<rect x="{label_col}" y="{y + row_h/2 - 6}" width="{bar_w:.1f}" height="12" rx="3" fill="{bar_color}"/>'
            f'<text x="{label_col + bar_max_w + 6}" y="{y + row_h/2 + 4}" font-family="Inter, Arial" font-size="9" font-weight="700" fill="{PALETTE["navy_dark"]}">{value:g}</text>'
        )
    return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">{"".join(rows)}</svg>'


def svg_gauge_arc(percentile: float | None, *, width: int = 160,
                  good_threshold: float = 75, ok_threshold: float = 50,
                  unit: str = "") -> str:
    """Half-donut percentile gauge (CWV-style: good / needs-improvement / poor)."""
    height = int(width * 0.62)
    cx, cy = width / 2, height * 0.92
    radius = width * 0.40
    stroke_w = width * 0.10
    if percentile is None:
        pct, display, color = 0.0, "n/a", "#94A3B8"
    else:
        pct = max(0.0, min(100.0, float(percentile))) / 100.0
        display = f"{percentile:.0f}{unit}"
        if percentile >= good_threshold: color = "#16A34A"
        elif percentile >= ok_threshold: color = "#F59E0B"
        else: color = "#EF4444"
    # Draw half-circle (180 to 360 degrees) — start left, end right
    start_x = cx - radius
    end_x = cx + radius
    # Background arc
    bg_path = f"M {start_x} {cy} A {radius} {radius} 0 0 1 {end_x} {cy}"
    # Foreground arc length: half-circumference * pct
    half_circ = math.pi * radius
    # Convert pct of half to angle (0 = left = 180deg, 1 = right = 360deg)
    angle = math.pi * (1 - pct)  # radians from x-axis
    fx = cx + radius * math.cos(angle)
    fy = cy - radius * math.sin(angle)
    large_arc = 1 if pct > 0.5 else 0
    fg_path = f"M {start_x} {cy} A {radius} {radius} 0 {large_arc} 1 {fx:.2f} {fy:.2f}"
    return f"""
<svg width="{width}" height="{height + 18}" viewBox="0 0 {width} {height + 18}" xmlns="http://www.w3.org/2000/svg">
  <path d="{bg_path}" fill="none" stroke="#E2E8F0" stroke-width="{stroke_w}" stroke-linecap="round"/>
  <path d="{fg_path}" fill="none" stroke="{color}" stroke-width="{stroke_w}" stroke-linecap="round"/>
  <text x="{cx}" y="{cy - 4}" text-anchor="middle" font-family="Inter, Arial" font-weight="800"
        font-size="{width * 0.18:.0f}" fill="{PALETTE['navy_dark']}">{display}</text>
</svg>
"""


def stat_strip(items: list[dict]) -> str:
    """A 3-4 tile horizontal metric strip with optional deltas.

    items = [{label, value, suffix, delta (str), delta_kind ("good"|"warn"|"crit"|"dim")}, ...]
    Use this for any text-heavy page that needs anchoring numbers up top.
    """
    if not items:
        return ""
    items = items[:4]
    n = len(items)
    tiles = []
    for it in items:
        label = _html.escape(strip_em_dashes(str(it.get("label", "")))[:34])
        value = strip_em_dashes(str(it.get("value", "n/a")))
        suffix = strip_em_dashes(str(it.get("suffix", "")))
        delta = strip_em_dashes(str(it.get("delta", "") or ""))
        kind = (it.get("delta_kind") or "good").lower()
        kind_cls = kind if kind in ("good", "warn", "crit", "dim") else "good"
        delta_html = f'<div class="ssv-delta ssv-delta-{kind_cls}">{_html.escape(delta)}</div>' if delta else ""
        tiles.append(
            f'<div class="ssv-tile">'
            f'  <div class="ssv-label">{label}</div>'
            f'  <div class="ssv-value">{_html.escape(value)}<span class="ssv-suffix">{_html.escape(suffix)}</span></div>'
            f'  {delta_html}'
            f'</div>'
        )
    return f'<div class="ssv-strip ssv-cols-{n}">{"".join(tiles)}</div>'


# ============================================================
# Markdown parsing helpers
# ============================================================

def _strip_md_bold(s: str) -> str:
    # Also strips em/en dashes so prose lifted from markdown never carries them
    # through (e.g. when used as a card title or chip label).
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s or "").strip()
    return strip_em_dashes(s) if s else s


def _grab_field(body: str, names: list[str]) -> str:
    """Pull a field value from a block of mixed prose + bold-labelled fields.

    Handles all three shapes that show up in agent output:
      - `**Severity:** Critical`          (colon INSIDE the bold - current format)
      - `**Severity**: Critical`          (colon OUTSIDE the bold)
      - `Severity: Critical`              (plain, no bold)

    The terminator lookahead also accepts either colon position so that the
    first matched field does not greedily swallow every subsequent field
    up to end-of-block.
    """
    stop = r"(?=\n\s*\*\*[^*\n]{1,80}(?::\s*\*\*|\*\*\s*:|\.\s*\*\*)|\n\n|\Z)"
    for name in names:
        esc = re.escape(name)
        patterns = [
            rf"\*\*\s*{esc}\s*:\s*\*\*\s*(.+?){stop}",
            rf"\*\*\s*{esc}\s*\*\*\s*:\s*(.+?){stop}",
            rf"\*\*\s*{esc}\s*\.\s*\*\*\s*(.+?){stop}",
            rf"(?<!\*)\b{esc}\s*:\s*(.+?){stop}",
        ]
        for pat in patterns:
            m = re.search(pat, body, re.DOTALL | re.IGNORECASE)
            if m:
                val = _strip_md_bold(m.group(1)).strip().rstrip(".")
                val = re.sub(r"\s+", " ", val)
                # Some agents write fields INLINE on one line ("Effort: Medium
                # - Impact: ...") instead of one per line. The newline-based
                # stop above cannot see those, so the first field swallows the
                # rest of the block (a 3,000-char "effort" rendered inside a
                # pill). Cut at the first inline occurrence of another
                # capitalised field label.
                val = re.split(
                    r"\s+-\s+(?:Impact|Fix|Effort|Owner|Severity|Broken|Time(?:\s+to\s+result)?)\s*:",
                    val, maxsplit=1)[0].strip()
                val = re.split(
                    r"\s(?:Impact|Fix|Owner|Severity)\s*:\s",
                    val, maxsplit=1)[0].strip()
                if val:
                    return val
    return ""


def parse_top_findings(action_plan_md: str, limit: int = 10) -> list[dict]:
    # Locate the findings block: supports several heading variants.
    heading_pat = re.compile(
        r"##\s+(?:Part\s+A\.?\s*)?Top\s+\d+\s+(?:Critical\s+Findings|high-priority\s+issues|HIGH-PRIORITY\s+ISSUES)"
        r"|^##\s+(?:Part\s+A\.?\s*).*?(?:issues|findings)"
        r"|^##\s+.*?\bhigh-priority\s+issues\b"
        r"|^##\s+.*?\bcritical\s+(?:findings|issues|blockers)\b",
        re.IGNORECASE | re.MULTILINE,
    )
    m = heading_pat.search(action_plan_md)
    if not m:
        return []
    after = action_plan_md[m.end():]
    end_m = re.search(r"\n##\s+", after)
    block = after[: end_m.start()] if end_m else after

    items: list[dict] = []

    # Format A: ### Issue N of M - Title  (long agent format)
    issue_iter = list(re.finditer(
        r"###\s+Issue\s+(\d+)\s+of\s+\d+\s*[-–—:]\s*(.+?)\n(.*?)(?=\n###\s+Issue\s+\d+|\Z)",
        block, re.DOTALL | re.IGNORECASE,
    ))
    if issue_iter:
        for mm in issue_iter:
            num = int(mm.group(1))
            base_headline = _strip_md_bold(mm.group(2).strip().rstrip("."))
            body = mm.group(3).strip()
            sub_headline = _grab_field(body, ["Headline"])
            display_headline = (sub_headline.strip('"').strip("'") if sub_headline else base_headline)
            broken = _grab_field(body, [
                "What is broken (plain English)", "What is broken", "Broken",
                "Problem", "What's wrong",
            ])
            fix = _grab_field(body, ["Fix", "How to fix", "Solution"])
            impact = _grab_field(body, [
                "Impact", "Business impact", "Why it matters", "Cost",
                "What it costs you", "What this costs",
            ])
            effort = _grab_field(body, ["Effort"])
            severity = _grab_field(body, ["Severity"]).lower()
            owner = _grab_field(body, ["Owner"])
            items.append({
                "num": num,
                "headline": display_headline,
                "severity": severity,
                "category": _infer_category_from_text(base_headline + " " + broken),
                "broken": broken, "fix": fix, "impact": impact, "effort": effort,
                "owner": owner,
            })
            if len(items) >= limit:
                break
        return items

    # Format C: ### N. Title  (concise client-facing format - numeric prefix + title only)
    flat_iter = list(re.finditer(
        r"###\s+(\d+)\.\s+(.+?)\n(.*?)(?=\n###\s+\d+\.|\n##\s+|\Z)",
        block, re.DOTALL,
    ))
    if flat_iter:
        # The matched heading (m.group(0)) drives the default severity. Anything
        # the writer explicitly tags as critical / high-priority maps to
        # "critical"; the legacy "Top N Findings" heading is treated as "major".
        heading_text = m.group(0).lower()
        default_severity = "critical" if any(k in heading_text for k in ("critical", "high-priority", "blocker")) else "major"
        for mm in flat_iter:
            num = int(mm.group(1))
            headline = _strip_md_bold(mm.group(2).strip().rstrip("."))
            body = mm.group(3).strip()
            broken = _grab_field(body, [
                "Broken", "What is broken", "What is broken (plain English)",
                "Problem", "What's wrong",
            ])
            fix = _grab_field(body, ["Fix", "How to fix", "Solution"])
            impact = _grab_field(body, [
                "Cost", "Impact", "Business impact", "Why it matters",
                "What it costs you",
            ])
            effort = _grab_field(body, ["Effort"])
            severity = _grab_field(body, ["Severity"]).lower() or default_severity
            owner = _grab_field(body, ["Owner"])
            items.append({
                "num": num,
                "headline": headline,
                "severity": severity,
                "category": _infer_category_from_text(headline + " " + broken),
                "broken": broken, "fix": fix, "impact": impact, "effort": effort,
                "owner": owner,
            })
            if len(items) >= limit:
                break
        return items

    # Format B: 1. **Title** Severity: ... Teams: ... (legacy)
    for raw in re.split(r"\n(?=\d+\.\s+\*\*)", block.strip()):
        raw = raw.strip()
        if not raw or not raw[0].isdigit():
            continue
        mm = re.match(r"^(\d+)\.\s+\*\*(.+?)\.?\*\*\s*(.*)$", raw, re.DOTALL)
        if not mm:
            continue
        body = mm.group(3).strip()
        teams = _grab_field(body, ["Teams"])
        items.append({
            "num": int(mm.group(1)),
            "headline": _strip_md_bold(mm.group(2).strip().rstrip(".")),
            "severity": _grab_field(body, ["Severity"]).lower(),
            "category": _infer_category(teams) if teams else _infer_category_from_text(mm.group(2) + " " + body),
            "broken": _grab_field(body, ["Broken"]),
            "fix": _grab_field(body, ["Fix"]),
            "impact": _grab_field(body, ["Impact"]),
            "effort": _grab_field(body, ["Effort"]),
        })
        if len(items) >= limit:
            break
    return items


def parse_quick_wins(action_plan_md: str, limit: int = 10) -> list[dict]:
    heading_pat = re.compile(
        r"##\s+(?:Part\s+B\.?\s*)?Top\s+\d+\s+(?:Quick\s+Wins|quick\s+wins)"
        r"|^##\s+(?:Part\s+B\.?\s*).*?quick\s+wins"
        r"|^##\s+\d+\s+quick\s+wins"
        r"|^##\s+.*?\bquick\s+wins\b",
        re.IGNORECASE | re.MULTILINE,
    )
    m = heading_pat.search(action_plan_md)
    if not m:
        return []
    after = action_plan_md[m.end():]
    end_m = re.search(r"\n##\s+", after)
    block = after[: end_m.start()] if end_m else after

    items: list[dict] = []

    # Format A: ### Quick win N - Title  (long agent format)
    qw_iter = list(re.finditer(
        r"###\s+Quick\s+win\s+(\d+)\s*[-–—:]\s*(.+?)\n(.*?)(?=\n###\s+Quick\s+win\s+\d+|\Z)",
        block, re.DOTALL | re.IGNORECASE,
    ))
    if qw_iter:
        for mm in qw_iter:
            headline = _strip_md_bold(mm.group(2).strip().rstrip("."))
            body = mm.group(3).strip()
            # Strip any leading "**Fix:**" / "**Impact:**" labels - use the first prose para
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
            desc_parts: list[str] = []
            for p in paragraphs:
                p_clean = re.sub(r"\*\*[^*]+?\*\*\s*:\s*", "", p)
                p_clean = _strip_md_bold(p_clean)
                p_clean = re.sub(r"\s+", " ", p_clean).strip()
                if p_clean:
                    desc_parts.append(p_clean)
                if sum(len(d) for d in desc_parts) > 240:
                    break
            desc = " ".join(desc_parts)
            if len(desc) > 320:
                desc = desc[:320].rsplit(" ", 1)[0] + "..."
            items.append({"headline": headline, "desc": desc})
            if len(items) >= limit:
                break
        return items

    # Format B: 1. **Title** description (legacy)
    for raw in re.split(r"\n(?=\d+\.\s+\*\*)", block.strip()):
        mm = re.match(r"^(\d+)\.\s+\*\*(.+?)\.?\*\*\s*(.*?)$", raw.strip(), re.DOTALL)
        if not mm:
            continue
        items.append({
            "headline": _strip_md_bold(mm.group(2).strip().rstrip(".")),
            "desc": re.sub(r"\s+", " ", _strip_md_bold(mm.group(3).strip())),
        })
        if len(items) >= limit:
            break
    if items:
        return items

    # Format C: bullet list "- text" (client-facing concise format)
    for ln in block.splitlines():
        s = ln.strip()
        if not s.startswith(("- ", "* ", "+ ")):
            continue
        text = _strip_md_bold(s[2:].strip().rstrip("."))
        if not text:
            continue
        # First sentence (or first 80 chars) becomes the headline; rest is desc.
        sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
        headline = sentence[0].strip().rstrip(".")
        if len(headline) > 110:
            cut = headline[:110].rsplit(" ", 1)[0]
            headline = cut.rstrip(".,;:") + "..."
        desc = sentence[1].strip() if len(sentence) > 1 else ""
        items.append({"headline": headline, "desc": desc})
        if len(items) >= limit:
            break
    return items


def parse_sprints(action_plan_md: str) -> list[dict]:
    """Parse sprint blocks. Supports:
      ### Sprint N - Title
      ### Sprint N: Title
      ### Sprint N - Days X to Y. Title
    """
    sprints = []
    pattern = re.compile(
        r"(?:^|\n)#{2,3}\s+Sprint\s+(\d+)\s*[-–—:]\s*(.+?)\n(.*?)(?=\n#{2,3}\s+Sprint\s+\d+|\n#{1,2}\s+(?!Sprint)|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    for m in pattern.finditer(action_plan_md):
        title = _strip_md_bold(m.group(2).strip().rstrip("."))
        body = m.group(3).strip()

        # First prose paragraph = description (stop at bullet list, sub-heading, or bold field)
        para_lines: list[str] = []
        for ln in body.splitlines():
            s = ln.strip()
            if not s:
                if para_lines:
                    break
                continue
            if s.startswith(("-", "*", "#", "|")):
                if para_lines:
                    break
                continue
            if re.match(r"^\*\*[^*]+?\*\*\s*:", s):
                if para_lines:
                    break
                continue
            para_lines.append(s)
        desc = re.sub(r"\s+", " ", _strip_md_bold(" ".join(para_lines)).strip().rstrip("."))
        if len(desc) > 360:
            desc = desc[:360].rsplit(" ", 1)[0] + "..."

        # Deliverables - pull every "- " line, take the first 6.
        deliverables_raw = re.findall(r"^[-*]\s+(.+)$", body, re.MULTILINE)
        deliverables: list[str] = []
        for d in deliverables_raw:
            d_clean = re.sub(r"\*\*([^*]+?)\*\*\s*:?\s*", r"\1: ", d)
            d_clean = _strip_md_bold(d_clean)
            d_clean = re.sub(r"\s+", " ", d_clean).strip().rstrip(".")
            if d_clean and len(d_clean) > 6:
                deliverables.append(d_clean)
            if len(deliverables) >= 6:
                break

        # Fallback: prose plans use "Day N:" / "Week N:" / "Weeks N to M:" lines
        # rather than markdown bullets. Capture those as deliverables when no
        # bullets are present.
        if not deliverables:
            day_block_pattern = re.compile(
                r"(?:^|\n)(?P<lead>(?:Day|Week|Weeks)\s+\d+(?:\s+(?:to|-)\s+\d+)?)\s*[:\.]\s+(?P<body>.+?)(?=\n(?:Day|Week|Weeks)\s+\d+|\nExit\s+criteria|\n\n|\Z)",
                re.IGNORECASE | re.DOTALL,
            )
            for dm in day_block_pattern.finditer(body):
                lead = dm.group("lead").strip()
                rest_first = re.split(r"(?<=[.!?])\s+", dm.group("body").strip(), maxsplit=1)[0]
                text = re.sub(r"\s+", " ", f"{lead}: {rest_first}").strip().rstrip(".")
                if text and len(text) > 6:
                    deliverables.append(text)
                if len(deliverables) >= 6:
                    break

        outcome_match = re.search(
            r"(?:\*\*\s*(?:Expected outcomes?|Exit criteria)\s*\*\*|Expected outcomes?|Exit criteria)\s*:?\s*(.+?)(?:\n\n|\n###|\n##|\Z)",
            body, re.DOTALL | re.IGNORECASE,
        )
        outcome = ""
        if outcome_match:
            outcome = re.sub(r"\s+", " ", _strip_md_bold(outcome_match.group(1).strip().rstrip(".")))
            if len(outcome) > 320:
                outcome = outcome[:320].rsplit(" ", 1)[0] + "..."

        sprints.append({
            "num": int(m.group(1)),
            "title": title,
            "desc": desc,
            "deliverables": deliverables,
            "outcome": outcome,
        })
    return sprints


def _infer_category(teams: str) -> str:
    t = teams.upper()
    if "B4" in t: return "SCHEMA"
    if "B1" in t or "B2" in t or "B3" in t or "B5" in t: return "TECHNICAL"
    if "D" in t and not any(x in t for x in ("A1","A2","A3","A4","A5")): return "LOCAL"
    if "C" in t and not any(x in t for x in ("A1","A2","A3","A4","A5")): return "OFF-PAGE"
    if "A1" in t: return "CONTENT"
    if "A" in t: return "ON-PAGE"
    return "ON-PAGE"


def _infer_category_from_text(text: str) -> str:
    t = text.lower()
    if "schema" in t or "structured data" in t or "json-ld" in t:
        return "SCHEMA"
    if any(k in t for k in [
        "google business", "gbp", "google maps", "directory", "directories",
        "citation", "review", "local pack", "service area", "city page",
        "service-area", "nap ", "nap,", "near me",
    ]):
        return "LOCAL"
    if any(k in t for k in [
        "competitor", "knowledge panel", "ai search", "ai overview",
        "chatgpt", "perplexity", "gemini", "brand mention",
    ]):
        return "OFF-PAGE"
    if any(k in t for k in [
        "sitemap", "robots.txt", "render", "javascript", "security",
        "https", "indexing", "crawl", "page speed", "mobile speed",
        "core web vitals", "lcp", "cls", "inp", "http header",
    ]):
        return "TECHNICAL"
    if any(k in t for k in [
        "title", "meta description", "headline", "faq", "snippet", "alt text",
    ]):
        return "ON-PAGE"
    if any(k in t for k in [
        "content", "trust", "about", "homepage", "e-e-a-t", "expertise",
    ]):
        return "CONTENT"
    return "ON-PAGE"


def extract_positives(executive_md: str, limit: int = 6) -> list[tuple[str, str]]:
    """Pull the 'What is working' bullet list from section-01.

    Each item becomes (title, body). If a bullet contains a bold lead phrase
    (`**Title.**` or `**Title:**`), that becomes the title and the rest is body.
    Otherwise the first short phrase is the title, the remainder is body.
    """
    m = re.search(
        r"##\s+What\s+is\s+working.*?\n(.*?)(?:\n##\s+|\Z)",
        executive_md, re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return []
    block = m.group(1)
    items: list[tuple[str, str]] = []
    for raw in re.findall(r"^[-*]\s+(.+(?:\n(?![-*#]).+)*)", block, re.MULTILINE):
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        # Bold lead phrase + body. Accept any leading punctuation between
        # the closing `**` and the continuation - earlier versions only
        # matched [.:-], which left commas attached to the body as a stray
        # leading character on the strengths cards.
        bold = re.match(r"\*\*([^*]+?)\*\*\s*[.,:;\-—]?\s*(.+)?$", line)
        if bold:
            title = _strip_md_bold(bold.group(1)).strip().rstrip(".,:;")
            body = _strip_md_bold((bold.group(2) or "").strip().lstrip(",.;:"))
        else:
            sentences = re.split(r"(?<=[.!?])\s+", line, maxsplit=1)
            title = _strip_md_bold(sentences[0].strip().rstrip("."))
            body = _strip_md_bold(sentences[1].strip()) if len(sentences) > 1 else ""
            if len(title) > 70:
                title = title[:70].rsplit(" ", 1)[0] + "..."
        if title:
            items.append((title, body))
        if len(items) >= limit:
            break
    return items


def extract_ai_context(section_04_md: str) -> dict:
    """Extract per-channel statuses from section-04.

    Accepts BOTH inline form:
        ChatGPT: Absent. <explanation>
    and bullet/bold form:
        - **ChatGPT:** Absent - <explanation>
        **ChatGPT:** Absent. <explanation>

    Maps synonym status tokens to canonical labels. Never falls back silently:
    missing channels are filled with 'Not measured' so the page always renders
    with the full 4-channel shape.
    """
    if not section_04_md:
        return {}

    _ABSENT_TOKENS  = {"absent", "not citing", "missing", "invisible", "undetected"}
    _NOT_YET        = "not yet"
    _EARLY_TOKENS   = {"early stage", "early", "limited", "partial", "occasional"}
    _GROWING_TOKENS = {"growing", "increasing", "improving"}
    _PRESENT_TOKENS = {"present", "active", "cited", "appearing", "confirmed", "ranking"}

    def _classify(token: str) -> tuple[str, int]:
        t = re.sub(r"\s+", " ", token.strip().lower())
        if t == _NOT_YET or t.startswith(_NOT_YET):
            return ("Not yet", 8)
        if t in _ABSENT_TOKENS:
            return ("Absent", 6)
        for k in _PRESENT_TOKENS:
            if k in t: return ("Present", 65)
        for k in _GROWING_TOKENS:
            if k in t: return ("Growing", 35)
        for k in _EARLY_TOKENS:
            if k in t: return ("Early stage", 18)
        for k in _ABSENT_TOKENS:
            if k in t: return ("Absent", 6)
        return ("Not measured", 8)

    channel_specs = [
        ("Google AI Overviews", ["Google AI Overviews", "Google AI Overview", "Google AI Answers", "Google AI"]),
        ("ChatGPT",             ["ChatGPT"]),
        ("Perplexity",          ["Perplexity"]),
        ("Gemini",              ["Gemini"]),
    ]

    # Longer status tokens BEFORE shorter ones so "not yet" matches before "not".
    _STATUS_ALT = (
        r"not\s+yet|not\s+citing|not\s+measured"
        r"|absent|missing|invisible|undetected"
        r"|early\s+stage|early|limited|partial|occasional"
        r"|growing|increasing|improving"
        r"|present|active|cited|appearing|confirmed|ranking"
    )

    channels = []
    for display_label, label_options in channel_specs:
        status, pct = "Not measured", 8
        for lab in label_options:
            pattern = re.compile(
                rf"(?:^[-*]\s+)?(?:\*\*)?{re.escape(lab)}(?:\*\*)?\s*[:\-]\s*[^\n]{{0,40}}?({_STATUS_ALT})",
                re.IGNORECASE | re.MULTILINE,
            )
            m = pattern.search(section_04_md)
            if m:
                status, pct = _classify(m.group(1))
                break

        if status in ("Absent", "Not yet", "Not measured"):
            color = PALETTE["warn_red"]
        elif status == "Early stage":
            color = PALETTE["warn_orange"]
        elif status == "Growing":
            color = PALETTE["blue_accent"]
        else:
            color = PALETTE["delta_green"]
        channels.append({"label": display_label, "status": status, "pct": pct, "color": color})

    # Recommendations: accept ## or ### heading variants, plus bold step intros.
    rec_block = re.search(
        r"(?:"
        r"#{2,3}\s+[^\n]*?(?:fix|grow|build|earn|how to|priority|steps|8.step|action)[^\n]*?\n"
        r"|"
        r"\*\*(?:The\s+\d+.step|Step\s+\d+)[^\n]*?(?:earn|grow|fix|build|action)[^\n]*?\*\*\s*\n"
        r")(.*?)(?:\n#{2,3}\s+|\Z)",
        section_04_md, re.DOTALL | re.IGNORECASE,
    )
    if not rec_block:
        rec_block = re.search(
            r"(\*\*Step\s+1\b[^\n]*\n.*?)(?:\n#{2,3}\s+|\Z)",
            section_04_md, re.DOTALL | re.IGNORECASE,
        )

    recommendations: list[tuple[str, str]] = []
    if rec_block:
        body = rec_block.group(1)
        step_pattern = re.compile(
            r"\*\*Step\s+\d+\s*[-–—:]\s*([^*\n]{5,80}?)\.?\*\*\s*(?:\(([^)]{5,160})\)|[:.]\s*([^\n]{5,200}))?",
            re.IGNORECASE,
        )
        for sm in step_pattern.finditer(body):
            title = _strip_md_bold(sm.group(1).strip().rstrip("."))
            detail = _strip_md_bold((sm.group(2) or sm.group(3) or "").strip().rstrip("."))
            if title:
                recommendations.append((title, detail))
            if len(recommendations) >= 4:
                break

        if not recommendations:
            for raw in re.findall(r"^[-*\d.]+\s+(.+(?:\n(?![-*\d#]).+)*)", body, re.MULTILINE):
                line = re.sub(r"\s+", " ", raw).strip()
                if not line:
                    continue
                bold = re.match(r"\*\*([^*]+?)\*\*\s*[.:\-]?\s*(.+)?$", line)
                if bold:
                    title = _strip_md_bold(bold.group(1)).strip().rstrip(".:")
                    body_text = _strip_md_bold((bold.group(2) or "").strip())
                else:
                    sentences = re.split(r"(?<=[.!?])\s+", line, maxsplit=1)
                    title = _strip_md_bold(sentences[0].strip().rstrip("."))
                    body_text = _strip_md_bold(sentences[1].strip()) if len(sentences) > 1 else ""
                    if len(title) > 80:
                        title = title[:80].rsplit(" ", 1)[0] + "..."
                if title:
                    recommendations.append((title, body_text))
                if len(recommendations) >= 4:
                    break

    return {"channels": channels, "recommendations": recommendations}


def _extract_subsection_card(body_text: str) -> tuple[str, list[str]]:
    """Pull a clean body summary + up to 4 bullets out of a markdown subsection.

    When the source subsection has no bullets, the body cap is raised to 380
    chars so the card carries enough text to not trail off visually.
    """
    para_lines: list[str] = []
    for ln in body_text.splitlines():
        s = ln.strip()
        if not s:
            if para_lines:
                break
            continue
        if s.startswith(("-", "*", "#", "|", ">")):
            if para_lines:
                break
            continue
        para_lines.append(s)
    body = re.sub(r"\s+", " ", _strip_md_bold(" ".join(para_lines))).strip()
    bullets_raw = re.findall(r"^[-*]\s+(.+)$", body_text, re.MULTILINE)
    bullets: list[str] = []
    for b in bullets_raw:
        b_clean = re.sub(r"\s+", " ", _strip_md_bold(b)).strip().rstrip(".")
        if 6 <= len(b_clean) <= 110:
            bullets.append(b_clean)
        if len(bullets) >= 4:
            break
    # No bullets? Pull the longer body so the card visually fills.
    cap = 380 if not bullets else 220
    if len(body) > cap:
        body = body[:cap].rsplit(" ", 1)[0] + "..."
    return body, bullets


def extract_local_cards(section_05_md: str) -> list[dict]:
    """Pull 4 subsection cards from section-05: GBP, listings, reviews,
    local pack. The card TITLE is now the literal subsection heading (with
    light cleanup), so the card body is guaranteed to match the title.
    Earlier versions remapped titles to canonical labels which created the
    title-vs-body mismatch the client flagged on the snapshot pages.
    """
    if not section_05_md:
        return []
    subs = list(re.finditer(
        r"^##+\s+([^\n]+)\n(.*?)(?=\n##+\s+|\Z)",
        section_05_md, re.DOTALL | re.MULTILINE,
    ))
    cards: list[dict] = []
    # Topic order = how the cards should appear; first matching subsection wins.
    topic_order = [
        r"(google business profile|gbp)",
        r"(business listing|nap|citation|directory|directories)",
        r"(review|reputation)",
        r"(local pack|service.area|local search|geo coverage|local content)",
    ]
    used_headings: set[str] = set()
    for pattern in topic_order:
        for sub in subs:
            heading = sub.group(1).strip().rstrip(":")
            if heading in used_headings:
                continue
            if re.search(pattern, heading, re.IGNORECASE):
                body, bullets = _extract_subsection_card(sub.group(2).strip())
                if not body:
                    continue
                # Trim ultra-long literal headings to a card-friendly length.
                title = heading if len(heading) <= 48 else heading[:48].rsplit(" ", 1)[0]
                cards.append({"title": title, "body": body, "bullets": bullets})
                used_headings.add(heading)
                break
    return cards


def extract_content_cards(section_02_md: str, action_plan_md: str) -> list[dict]:
    """Pull 4 content-strategy cards from section-02 subsections. Like the
    local-cards extractor, the card title now equals the source subsection
    heading so body and title always describe the same topic.
    """
    if not section_02_md:
        return []
    subs = list(re.finditer(
        r"^##+\s+([^\n]+)\n(.*?)(?=\n##+\s+|\Z)",
        section_02_md, re.DOTALL | re.MULTILINE,
    ))
    cards: list[dict] = []
    topic_order = [
        r"(content|trust|e-e-a-t|helpful|expertise)",
        r"(title|meta|snippet|page title)",
        r"(heading|h1|alt text|image)",
        r"(internal link|topic cluster|architecture|how google understands|ai search|semantic|entity)",
    ]
    used_headings: set[str] = set()
    for pattern in topic_order:
        for sub in subs:
            heading = sub.group(1).strip().rstrip(":")
            if heading in used_headings:
                continue
            if re.search(pattern, heading, re.IGNORECASE):
                body, bullets = _extract_subsection_card(sub.group(2).strip())
                if not body:
                    continue
                title = heading if len(heading) <= 48 else heading[:48].rsplit(" ", 1)[0]
                cards.append({"title": title, "body": body, "bullets": bullets})
                used_headings.add(heading)
                break
    return cards


def extract_verdict(executive_md: str) -> str:
    """First multi-sentence prose paragraph from section-01.

    Skips:
      - markdown headings
      - tables and table rows
      - bullet/numbered lists
      - lines that look like inline metadata (Run ID / Date / Domain / Profile)
    """
    buf = []
    skip_patterns = re.compile(
        r"^\s*\*\*\s*(Run ID|Date|Domain|Pages crawled|Profile|Run UUID|Generated)\s*:",
        re.IGNORECASE,
    )
    for ln in executive_md.splitlines():
        s = ln.strip()
        if not s:
            if buf: break
            continue
        if s.startswith("#") or s.startswith("|") or s.startswith("-"): continue
        if skip_patterns.match(s): continue
        buf.append(s)
    para = re.sub(r"\s+", " ", " ".join(buf).strip())
    para = re.sub(r"`([^`]+)`", r"\1", para)
    if len(para) > 360:
        para = para[:360].rsplit(".", 1)[0] + "."
    return para


# ============================================================
# Inline helpers
# ============================================================

# Project style rule (CLAUDE.md): no em dashes (U+2014) or en dashes (U+2013)
# anywhere in the generated PDF. Replace with " - " so prose still scans
# cleanly, and let downstream regex / chip rendering proceed unchanged.
_DASH_TRANSLATE = str.maketrans({
    "—": "-",   # em dash
    "–": "-",   # en dash
    "−": "-",   # minus sign (occasionally appears via copy-paste)
})


# Client-facing redaction. Internal tooling / vendor names and build-phase
# language must never reach the rendered PDF. The audit is delivered to a
# non-technical business owner; references to specific third-party APIs or to
# our internal build phases (e.g. "Phase 1B") leak the system architecture
# and undermine the consulting register. Rewrites are applied as a final
# text-boundary pass alongside the em / en dash strip, so every code path
# that already routes through strip_em_dashes (md_inline, _strip_md_bold,
# stat tiles, appendix rows, chip labels, narrative paragraphs) gets the
# scrub for free.
#
# Patterns are ordered: more specific multi-word phrases run first so a
# narrower replacement does not lose to a broader one (e.g. the
# pagespeed.web.dev URL must be replaced before the bare "PageSpeed Insights"
# token is normalized to a generic descriptor).
_INTERNAL_TERM_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    # Internal build-phase references. "Phase 1B Playwright capture" etc.
    (re.compile(r"When\s+Phase\s+1[A-Z]?\s+Playwright\s+capture\s+is\s+wired\s+in", re.IGNORECASE),
     "Once full JS-rendered DOM capture is enabled"),
    (re.compile(r"Phase\s+1[A-Z]\+?\s+Playwright(?:\s+capture)?", re.IGNORECASE),
     "full JS-rendered DOM capture"),
    (re.compile(r"Phase\s+1[A-Z]\+?", re.IGNORECASE),
     "the next rendering phase"),
    # Specific PageSpeed Insights URL forms (must precede the bare token).
    (re.compile(r"https?://pagespeed\.web\.dev/\?url=[^\s)<>'\"]+", re.IGNORECASE),
     "Google's free web speed test at web.dev/measure"),
    (re.compile(r"https?://pagespeed\.web\.dev[^\s)<>'\"]*", re.IGNORECASE),
     "Google's free web speed test at web.dev/measure"),
    (re.compile(r"pagespeed\.web\.dev", re.IGNORECASE),
     "web.dev/measure"),
    # Bare vendor / tool names.
    (re.compile(r"\bWebsite\s+speed\s+checker\s+by\s+(?:page\s*speed\s+insight[s]?|PageSpeed\s+Insights?)\b",
                re.IGNORECASE),
     "Website speed check (Google web performance test)"),
    (re.compile(r"\bPageSpeed\s+Insights?\b", re.IGNORECASE),
     "Google web performance test"),
    (re.compile(r"\bPlaywright\b"),
     "headless browser rendering"),
]


def _redact_internal_terms(text: str) -> str:
    for pattern, replacement in _INTERNAL_TERM_REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def strip_em_dashes(text: str) -> str:
    """Strip em / en dashes from any text destined for the rendered PDF.

    Applied at every text-emission boundary so neither hardcoded strings nor
    agent-written markdown can sneak a dash into the final document. Also
    runs the client-facing internal-term redaction pass so vendor / tooling /
    build-phase language is rewritten before HTML render. Both scrubs share
    this boundary because every renderer in this file already routes text
    through strip_em_dashes - centralizing the redaction here closes every
    leak path with a single hook.
    """
    if not text:
        return text
    return _redact_internal_terms(text.translate(_DASH_TRANSLATE))


def md_inline(text: str) -> str:
    if not text: return ""
    text = strip_em_dashes(text)
    text = re.sub(r"\s+", " ", text).strip()
    # Escape HTML special chars in the raw text so literal `<table>` / `<th>` /
    # `&` from agent output cannot open real DOM elements (a stray `<table>` in
    # one finding swallowed every following page into a single <th>, breaking
    # the visual theme from that page onward).
    text = _html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(
        r"`([^`]+?)`",
        r'<code style="font-family: \'JetBrains Mono\', Consolas, monospace; '
        r'font-size: 9pt; background: #F1F5F9; padding: 1pt 5pt; '
        r'border-radius: 3pt; color: #0F172A;">\1</code>',
        text,
    )
    return text


def severity_chip(severity: str) -> str:
    s = severity.lower()
    if "critical" in s: return '<span class="chip sev-critical">Critical</span>'
    if "major" in s:    return '<span class="chip sev-major">Major</span>'
    return '<span class="chip sev-minor">Minor</span>'


def category_chip(category: str) -> str:
    bg, fg = CATEGORY_COLOR.get(category, ("#E2E8F0", "#334155"))
    return f'<span class="chip" style="background: {bg}; color: {fg};">{category}</span>'


def make_pull_quote(text: str) -> str:
    if not text: return ""
    cleaned = re.sub(r"`([^`]+)`", lambda m: m.group(0).strip("`"), text)
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    scored = []
    for s in sentences:
        score = 0
        if re.search(r"\b\d+", s): score += 2
        if re.search(r"\b(every|all|zero|no|none)\b", s, re.IGNORECASE): score += 2
        if 60 <= len(s) <= 220: score += 2
        scored.append((score, s))
    scored.sort(reverse=True)
    return scored[0][1].strip() if scored else (sentences[0].strip() if sentences else "")


def effort_label(effort: str) -> str:
    e = effort.upper().strip()
    if e == "S": return "Quick fix · 1-2 days"
    if e == "M": return "Medium effort · 1-2 weeks"
    if e == "L": return "Larger project · 3-4 weeks"
    return f"Effort: {effort}"


# ============================================================
# Page builders
# ============================================================

def build_cover(client: str, industry: str, location: str, date_str: str,
                pages_crawled: int) -> str:
    return f"""
<div class="cover">
  <div class="cover-hero">
    <div class="cover-eyebrow">SEO Audit · Findings · Roadmap</div>
    <div class="cover-title">SEO Audit Report</div>
    <div class="cover-sub">Reporting period · {date_str}</div>
    <span class="cover-tag">Full Audit · Visual Summary + Action Plan</span>
  </div>
  <div class="cover-meta">
    <div class="cover-meta-card"><div class="cover-meta-label">Business</div><div class="cover-meta-value">{client}</div></div>
    <div class="cover-meta-card"><div class="cover-meta-label">Industry</div><div class="cover-meta-value">{industry}</div></div>
    <div class="cover-meta-card"><div class="cover-meta-label">Location</div><div class="cover-meta-value">{location}</div></div>
    <div class="cover-meta-card"><div class="cover-meta-label">Pages reviewed</div><div class="cover-meta-value">{pages_crawled}</div></div>
  </div>
</div>
"""


def build_at_a_glance(scores: dict, critical_count: int, quick_win_count: int,
                      pages_crawled: int, verdict: str) -> str:
    overall = scores.get("overall")
    donut = svg_donut(overall, label="OVERALL SCORE")
    onpage = scores.get("on_page") or scores.get("onpage")
    tech = scores.get("technical")
    offpage = scores.get("off_page") or scores.get("offpage")
    local = scores.get("local_seo") or scores.get("local")

    def stat_tile(label, value, suffix, delta_text=None, delta_class=""):
        # Score values are heuristic composites; one-decimal precision implies
        # measurement we don't have. Render scores as whole numbers, but keep
        # integer counts (pages, findings) exactly as passed.
        if value in (None, "n/a"):
            v = "n/a"
        elif isinstance(value, float):
            v = f"{round(value):d}"
        else:
            v = str(value)
        delta_html = (
            f'<div class="tile-delta {delta_class}">{delta_text}</div>'
            if delta_text else (f'<div class="tile-suffix">{suffix}</div>' if suffix else "")
        )
        return f"""
<div class="tile">
  <div class="tile-label">{label}</div>
  <div class="tile-value">{v}</div>
  {delta_html}
</div>"""

    return f"""
<div class="page">
  <div class="sec-eyebrow">At a Glance</div>
  <div class="sec-title">A quick look at where you stand</div>
  <div class="sec-lead">{verdict}</div>

  <div class="scorecard-hero">
    <div>{donut}</div>
    <div class="scorecard-hero-right">
      <h3>Your overall website health</h3>
      <p>This score blends the quality of your content, the cleanliness of your site code, your visibility in search, and how well your business shows up locally, all into one easy number out of 100.</p>
      <p style="font-size: 9.5pt; color: {PALETTE['text_muted']};">Reviewed across {pages_crawled} pages · {critical_count} high-priority issues found · {quick_win_count} fast fixes identified.</p>
    </div>
  </div>

  <div class="tile-grid-4">
    {stat_tile("Content (On-Page)", onpage, "/100", "Measured" if onpage else "n/a", "" if onpage else "dim")}
    {stat_tile("Site Health (Technical)", tech, "/100", "Measured" if tech else "n/a", "" if tech else "dim")}
    {stat_tile("Search Visibility", offpage, "/100", "Measured" if offpage else "n/a", "dim" if not offpage else "")}
    {stat_tile("Local Presence", local, "/100", "Measured" if local else "n/a", "dim" if not local else "")}
  </div>

  <div class="tile-grid-4">
    {stat_tile("High-Priority Issues", critical_count, "need action", "Important", "crit")}
    {stat_tile("Fast Fixes", quick_win_count, "ship this week", "Easy wins", "")}
    {stat_tile("Pages Reviewed", pages_crawled, "fully analyzed", "Coverage", "")}
    {stat_tile("Recommendations", critical_count + quick_win_count, "with clear next steps", "Action plan", "")}
  </div>
</div>
"""


def build_dimension_bars(scores: dict) -> str:
    def bar(label, score, interpretation):
        if score in (None, "n/a"):
            return f"""
<div class="barrow">
  <div class="barrow-label">{label}</div>
  <div class="barrow-track"><div class="barrow-fill dim" style="width: 0%;"></div></div>
  <div class="barrow-value dim">n/a</div>
</div>
<div class="bar-interp">{interpretation}</div>"""
        s = float(score)
        # Color bands: green >= 75 (healthy), amber 50-74 (needs work),
        # red < 50 (critical gap). These are stated explicitly in section-07.
        cls = "good" if s >= 75 else ("warn" if s >= 50 else "crit")
        return f"""
<div class="barrow">
  <div class="barrow-label">{label}</div>
  <div class="barrow-track"><div class="barrow-fill {cls}" style="width: {s:.0f}%;"></div></div>
  <div class="barrow-value">{round(s):d}</div>
</div>
<div class="bar-interp">{interpretation}</div>"""

    onpage = scores.get("on_page") or scores.get("onpage")
    tech = scores.get("technical")
    offpage = scores.get("off_page") or scores.get("offpage")
    local = scores.get("local_seo") or scores.get("local")

    return f"""
<div class="page">
  <div class="sec-eyebrow">Four Areas We Reviewed</div>
  <div class="sec-title">Where your site is strong, and where it needs work</div>
  <div class="sec-lead">Every audit looks at the same four areas. Green bars mean the area is healthy. Yellow means there is room to grow. Red means action is needed soon. Below each bar is a one-line explanation of what that area covers.</div>

  <div class="barrow-card">
    {bar("Content", onpage, "The words on your pages: page titles, headings, descriptions, product copy, and how naturally they match what customers search for.")}
    {bar("Site Health", tech, "The technical foundation: page loading speed, mobile readiness, security, and whether Google can read every page properly.")}
    {bar("Search Visibility", offpage, "How often your pages appear in Google search results and the AI tools like ChatGPT and Google's AI answers.")}
    {bar("Local Presence", local, "How well your business shows up when people search nearby: Google Maps, local business listings, and customer reviews.")}
  </div>

  <div class="why-card">
    <div class="why-title">Why these four areas matter together</div>
    <div class="why-row">
      <div class="why-tick">1</div>
      <div class="why-text"><strong>Each area supports the others.</strong> A great looking site with slow loading times still loses customers. Strong content with no local listings is invisible to nearby buyers.</div>
    </div>
    <div class="why-row">
      <div class="why-tick">2</div>
      <div class="why-text"><strong>Fix the biggest gaps first.</strong> The action plan in this report is ordered so the easiest, highest-impact fixes happen first. That way you see results before you finish the longer items.</div>
    </div>
    <div class="why-row">
      <div class="why-tick">3</div>
      <div class="why-text"><strong>Most issues are not visible to you.</strong> They affect how Google sees your site, which controls who finds you. The audit surfaces them so they can be fixed.</div>
    </div>
  </div>
</div>
"""


# ============================================================
# Issue Dashboard - the SEMrush-style "scare page" rendered right after the
# cover. Lists ALL issues with severity counts so the client feels the
# problem in 5 seconds. Pulls real numbers from findings.json.
# ============================================================

def _section_categorize(check_id: str, category: str, subcategory: str | None) -> str:
    """Map a finding to one of the 6 report sections (matches SKILL.md
    structure): strategy / content / onpage / technical / offpage_local / geo.
    Section order in the dashboard matches the PDF reading order.
    """
    cid = (check_id or "").upper()
    cat = (category or "").lower()
    sub = (subcategory or "").lower()
    # Strategy - brand entity, competitive position, knowledge graph,
    # high-level authority signals. These are the cross-cutting findings
    # that map to the strategic position narrative, not to tactical fixes.
    STRATEGY_IDS = {
        "OFF-018", "OFF-042", "OFF-049", "OFF-050", "OFF-051", "OFF-052",
        "OFF-062", "OFF-070", "OFF-071", "OFF-072", "OFF-073",
    }
    if cid in STRATEGY_IDS:
        return "strategy"
    # GEO (AI search) - dedicated section
    if any(x in (cid + sub) for x in ("ON-048", "ON-049", "ON-100", "ON-101", "ON-102", "ON-103", "ON-104", "ON-105", "ON-106", "ON-107", "ON-139", "TECH-040", "TECH-041", "OFF-067", "OFF-068", "OFF-069")):
        return "geo"
    if "ai-search" in sub or "geo-ai" in sub:
        return "geo"
    # Content (E-E-A-T, content quality, semantic)
    CONTENT_IDS = {
        "ON-001", "ON-002", "ON-023", "ON-024", "ON-025", "ON-028", "ON-029",
        "ON-032", "ON-051", "ON-090", "ON-107", "ON-111",
        "ON-119", "ON-120", "ON-121", "ON-122", "ON-123", "ON-124", "ON-125",
        "ON-127", "ON-130", "ON-131", "ON-132", "ON-133", "ON-134", "ON-135",
        "ON-136", "ON-137", "ON-138", "ON-140", "ON-141", "ON-142",
    }
    if cid in CONTENT_IDS:
        return "content"
    if any(x in sub for x in ("content-quality", "semantic", "search-intent", "e-e-a-t")):
        return "content"
    # Technical
    if cat == "technical" or any(x in sub for x in ("crawl", "speed", "performance", "schema", "security", "rendering", "mobile")):
        return "technical"
    # Local SEO - GBP, citations, NAP, reviews, local pack, geo-grid.
    # Anything LOC-* and most "local" subcategories belong here.
    if cat == "local-seo" or cid.startswith("LOC-"):
        return "local"
    if any(x in sub for x in ("gbp", "citation", "review", "local", "geo-grid", "service-area")):
        return "local"
    # Off-page - backlinks, brand authority, competitor signals, entity
    # presence, AI Overview citations. Anything OFF-* and competitor /
    # brand-shaped subcategories.
    if cat == "off-page" or cid.startswith("OFF-"):
        return "offpage"
    if any(x in sub for x in ("competitor", "brand", "knowledge-graph", "ai-citation")):
        return "offpage"
    # Default: on-page (titles, meta, headings, internal linking, images)
    return "onpage"


# Severity normaliser. The deterministic engine emits critical/major/minor/info;
# the agent-written jsonl findings (A5-*, OFF-*) emit high/medium/low. Without a
# shared map the agent severities silently collapse to "minor" and undercount the
# real majors. One map, used by every rollup, keeps the counts honest.
_SEV_NORM = {
    "critical": "critical", "high": "major", "major": "major",
    "medium": "major", "minor": "minor", "low": "minor", "info": "minor",
}


def _norm_sev(sev: str | None) -> str:
    return _SEV_NORM.get((sev or "").strip().lower(), "minor")


SECTION_LABELS = {
    "strategy": "Strategy", "content": "Content", "onpage": "On-page",
    "technical": "Technical",
    "offpage": "Off-page", "local": "Local SEO",
    # Backwards-compat alias for legacy callers that still use offpage_local.
    "offpage_local": "Off-page",
    "geo": "GEO (AI Search)",
}


def _load_all_finding_rows(artifact_dir: Path) -> list[dict]:
    """Read findings.json plus the agent-written team-*-findings.jsonl into one
    list of rows carrying every field the report needs (check_id, check_name,
    status, severity, category, subcategory, score, remediation). Brand /
    competitor / AI-search findings live ONLY in the jsonl files, so both
    sources must be merged or whole sections read as zero.
    """
    rows: list[dict] = []
    fp = artifact_dir / "findings.json"
    if fp.exists():
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else payload.get("findings", [])
        except Exception:
            rows = []
    for jsonl_path in artifact_dir.glob("team-*-findings.jsonl"):
        try:
            for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rows.append({
                    "check_id":    rec.get("check_id") or rec.get("checkId") or "",
                    "check_name":  rec.get("check_name") or rec.get("name") or "",
                    "status":      rec.get("status") or "",
                    "severity":    rec.get("severity") or "",
                    "category":    rec.get("category") or "",
                    "subcategory": rec.get("subcategory") or "",
                    "score":       rec.get("score"),
                    "remediation": rec.get("remediation") or rec.get("fix") or "",
                })
        except Exception:
            continue
    return rows


def compute_issue_inventory(artifact_dir: Path) -> dict:
    """Read findings.json and produce the section-by-section ISSUE inventory.

    SEMrush-style: counts unique ISSUE TYPES (check_ids), not individual
    page-level rows. So a finding like "16 of 17 homepage images missing
    alt text" counts as ONE issue, not 16. This produces believable
    dashboard headlines ("47 issues found across 6 sections") instead of
    inflated row-counts ("1,217 major issues" which is correct page-row math
    but reads as marketing puffery).

    Severity per unique check_id = the worst severity observed for that
    check across any page. Score per section = severity-weighted average
    of those unique check_ids (rescaled to 0-100).
    """
    rows = _load_all_finding_rows(artifact_dir)
    section_keys = [
        ("strategy",       "Strategy"),
        ("content",        "Content"),
        ("onpage",         "On-page"),
        ("technical",      "Technical"),
        ("offpage",        "Off-page"),
        ("local",          "Local SEO"),
        ("geo",            "GEO (AI Search)"),
    ]
    # Severity rank for "worst observed" rollup. Higher = worse.
    sev_rank = {"critical": 3, "major": 2, "minor": 1, "info": 0}
    sev_rev = {3: "critical", 2: "major", 1: "minor", 0: "info"}

    # Per-check_id rollup: worst-status, worst-severity, total page-rows seen,
    # an avg score, and the section bucket it belongs to.
    by_check: dict[str, dict] = {}
    for r in rows:
        cid = r.get("check_id") or ""
        status = (r.get("status") or "").lower()
        sev = (r.get("severity") or "").lower()
        cat = (r.get("category") or "").lower()
        sub = (r.get("subcategory") or "").lower()
        if not cid:
            continue
        entry = by_check.setdefault(cid, {
            "rank": -1, "issue_severity": "info",
            "pass_seen": False, "fail_seen": False, "warn_seen": False,
            "section_key": _section_categorize(cid, cat, sub),
            "score_sum": 0.0, "score_n": 0,
            "rows": 0,
        })
        entry["rows"] += 1
        if status == "pass": entry["pass_seen"] = True
        if status == "fail": entry["fail_seen"] = True
        if status == "warn": entry["warn_seen"] = True
        # Track the worst severity ONLY for non-pass observations (so a check
        # that passes on 78 pages plus warns on 1 stays at "warn" severity,
        # not "info" via the pass rows).
        if status in ("warn", "fail"):
            nsev = _norm_sev(sev)
            rank = sev_rank.get(nsev, 1)
            if rank > entry["rank"]:
                entry["rank"] = rank
                entry["issue_severity"] = nsev
        score = r.get("score")
        if score is not None:
            try:
                entry["score_sum"] += float(score)
                entry["score_n"] += 1
            except (TypeError, ValueError):
                pass

    section_keys_map = {k: lbl for k, lbl in section_keys}
    buckets: dict[str, dict] = {k: {"key": k, "label": lbl, "crit": 0, "major": 0, "minor": 0, "total": 0, "score_sum": 0.0, "score_n": 0} for k, lbl in section_keys}
    totals_uniq = {"critical": 0, "major": 0, "minor": 0}

    for cid, entry in by_check.items():
        # An issue exists for this check only if at least one page warned or failed.
        if not (entry["warn_seen"] or entry["fail_seen"]):
            continue
        sev = entry["issue_severity"]
        if sev not in ("critical", "major", "minor"):
            sev = "minor"
        totals_uniq[sev] += 1
        b = buckets.get(entry["section_key"]) or buckets["onpage"]
        b["total"] += 1
        if sev == "critical": b["crit"] += 1
        elif sev == "major":  b["major"] += 1
        elif sev == "minor":  b["minor"] += 1
        if entry["score_n"]:
            b["score_sum"] += entry["score_sum"] / entry["score_n"]
            b["score_n"] += 1

    sections_out: list[dict] = []
    for k, lbl in section_keys:
        b = buckets[k]
        score = (b["score_sum"] / b["score_n"] * 10.0) if b["score_n"] else None
        sections_out.append({
            "key": k, "label": lbl,
            "crit": b["crit"], "major": b["major"], "minor": b["minor"],
            "total": b["total"], "score": score,
        })
    # Count UNIQUE check_ids that passed (no warn/fail observed). This is the
    # "what is working" inventory count surfaced on the index page stat cards.
    passes_count = sum(
        1 for e in by_check.values()
        if e["pass_seen"] and not (e["warn_seen"] or e["fail_seen"])
    )
    total_issues = totals_uniq["critical"] + totals_uniq["major"] + totals_uniq["minor"]
    return {
        # Backwards-compat alias: "total_findings" historically meant page-rows;
        # callers that want unique issue types use "total_issues".
        "total_findings": total_issues,
        "total_issues": total_issues,
        "total_page_rows": len(rows),
        "critical": totals_uniq["critical"],
        "major": totals_uniq["major"],
        "minor": totals_uniq["minor"],
        "passes": passes_count,
        "sections": sections_out,
    }


def _fetch_semrush_overview(domain: str) -> dict | None:
    """Fetch domain-authority + estimated monthly organic traffic from
    Semrush, ONLY if SEMRUSH_API_KEY is set in the environment. Returns
    {"domain_authority": int|None, "monthly_traffic": int|None,
    "monthly_keywords": int|None} or None when:
      - The key is missing (most common - the integration is optional)
      - The HTTP request fails
      - The response payload is unparseable

    Every failure path returns None silently. The caller treats None as
    "skip the Semrush tiles on the index page" - no error propagated, no
    log noise that would surface in a client-facing PDF.
    """
    key = (os.environ.get("SEMRUSH_API_KEY") or "").strip()
    if not key:
        return None
    try:
        import urllib.request
        import urllib.parse
        # Use the Semrush v3 Analytics overview endpoint. The exact
        # `type=domain_rank_history` shape varies per plan; we accept
        # whichever overview endpoint the key is provisioned for and
        # parse the standard semicolon-CSV body.
        params = {
            "type": "domain_rank",
            "key": key,
            "domain": (domain or "").replace("https://", "").replace("http://", "").rstrip("/"),
            "database": "us",
            "export_columns": "Db,Dn,Rk,Or,Ot,Oc",
        }
        url = "https://api.semrush.com/?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "SEO-Audit/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            text = resp.read().decode("utf-8", errors="ignore").strip()
        # Semrush returns "header;line\nvalue;line" - parse the second line
        # by column name from the header line.
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < 2:
            return None
        header = [c.strip() for c in lines[0].split(";")]
        values = [c.strip() for c in lines[1].split(";")]
        row = dict(zip(header, values))
        def _maybe_int(s: str) -> int | None:
            try:
                return int(float(s))
            except (TypeError, ValueError):
                return None
        return {
            "domain_authority": _maybe_int(row.get("Rk") or row.get("DR") or ""),
            "monthly_traffic": _maybe_int(row.get("Ot") or row.get("Organic Traffic") or ""),
            "monthly_keywords": _maybe_int(row.get("Or") or row.get("Organic Keywords") or ""),
        }
    except Exception:
        return None


def _load_page_url_map(artifact_dir: Path) -> dict[int, str]:
    """Build {page_id: url} from the SQLite DB. Used to surface 1-3 example
    URLs per issue ("e.g. /contact, /services have this") so issue
    descriptions feel specific instead of generic. Returns {} if the DB
    cannot be opened or the schema does not include the pages table.
    """
    try:
        import sqlite3
        repo_root = artifact_dir.parents[2] if len(artifact_dir.parents) >= 3 else artifact_dir.parent
        # data/audits/<domain>/<uuid>/ -> data/<db>
        db_path = repo_root.parent / "seo_audit.db" if repo_root.name == "audits" else artifact_dir.parents[1].parent / "seo_audit.db"
        if not db_path.exists():
            db_path = Path("data/seo_audit.db")
            if not db_path.exists():
                return {}
        conn = sqlite3.connect(str(db_path))
        try:
            c = conn.cursor()
            c.execute("SELECT id, url FROM pages")
            return {row[0]: row[1] for row in c.fetchall()}
        finally:
            conn.close()
    except Exception:
        return {}


def _format_example_urls(urls: list) -> str:
    """Format 1-3 sample URLs into a compact "/contact, /services" string.
    Accepts a mixed list of strings and dicts. Dict entries come from
    evidence_json `examples` fields that hold pairwise comparisons
    (e.g. {"a": "url", "b": "url"}) or canonical-chain records
    (e.g. {"page": "url", "canonical": "url"}); the URL is pulled out via
    a key-priority list. CDN / image URLs are filtered out so the examples
    name actual site pages."""
    flat: list[str] = []
    for u in urls or []:
        if isinstance(u, dict):
            # Priority order matches the shapes the analyzers emit.
            for key in ("page", "url", "a", "source"):
                val = u.get(key)
                if isinstance(val, str) and val.startswith("http"):
                    flat.append(val)
                    break
        elif isinstance(u, str):
            flat.append(u)
    seen: list[str] = []
    for u in flat:
        if not u:
            continue
        # Strip CDN, image, and asset URLs - they are not "pages".
        lo = u.lower()
        if any(t in lo for t in ("images.", "/image/", ".png", ".jpg", ".jpeg",
                                  ".webp", ".gif", ".svg", "leadconnectorhq",
                                  "cdn.")):
            continue
        # Strip scheme://host/, keep the path
        m = re.match(r"^https?://[^/]+(/.*)?$", u)
        path = (m.group(1) or "/") if m else u
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        label = path if path != "/" else "(home)"
        if len(label) > 38:
            label = label[:35] + "..."
        if label not in seen:
            seen.append(label)
        if len(seen) >= 3:
            break
    return ", ".join(seen)


def compute_full_issue_list(artifact_dir: Path, pages_total: int | None = None) -> list[dict]:
    """Every unique warn/fail issue-type the engine found, deduped to one row
    per check_id, with its worst severity, affected-page count, report area,
    evidence (from the worst observation), the remediation text, AND 1-3
    example URLs so the description can name specific pages instead of
    sounding generic. Sorted worst-first.

    `pages_total` is the crawled-page count from run.json. When provided, it
    seeds each issue's `pages_total` field so the specific-title builder can
    decide "site-wide" vs "on N pages" at description time.
    """
    rows = _load_all_finding_rows(artifact_dir)
    url_map = _load_page_url_map(artifact_dir)
    sev_rank = {"critical": 3, "major": 2, "minor": 1}
    agg: dict[str, dict] = {}
    for r in rows:
        cid = (r.get("check_id") or "").strip()
        status = (r.get("status") or "").lower()
        if not cid or status not in ("warn", "fail"):
            continue
        nsev = _norm_sev(r.get("severity"))
        rank = sev_rank.get(nsev, 1)
        e = agg.get(cid)
        if e is None:
            e = agg[cid] = {
                "check_id": cid,
                "name": (r.get("check_name") or "").strip() or cid,
                "severity": nsev, "rank": rank, "pages": 0, "fix": "",
                "evidence_raw": "",
                "example_page_ids": [],
                "area_key": _section_categorize(cid, r.get("category"), r.get("subcategory")),
            }
        e["pages"] += 1
        # Track up to ~6 distinct page_ids so we can sample examples later.
        pid = r.get("page_id")
        if pid is not None and pid not in e["example_page_ids"] and len(e["example_page_ids"]) < 6:
            e["example_page_ids"].append(pid)
        # Keep the name + fix + evidence from the worst-severity observation.
        if rank >= e["rank"]:
            e["rank"] = rank
            e["severity"] = nsev
            if (r.get("check_name") or "").strip():
                e["name"] = r["check_name"].strip()
            if (r.get("remediation") or "").strip():
                e["fix"] = r["remediation"].strip()
            if (r.get("evidence_json") or "").strip():
                e["evidence_raw"] = r["evidence_json"].strip()
        if not e["fix"] and (r.get("remediation") or "").strip():
            e["fix"] = r["remediation"].strip()
        if not e["evidence_raw"] and (r.get("evidence_json") or "").strip():
            e["evidence_raw"] = r["evidence_json"].strip()

    issues = list(agg.values())
    # Site-wide threshold: 80% of crawled pages OR 30+ pages absolute. At that
    # density, example URLs add noise instead of clarity ("for example, every
    # page" reads worse than just stating "site-wide"). The dim header already
    # shows the count, so this hides examples only when they would distract.
    for e in issues:
        e["area_label"] = SECTION_LABELS.get(e["area_key"], "On-page")
        # Pull example URLs from evidence_json first (some checks include
        # them as the `examples` field), then fall back to the page_id lookup.
        examples: list = []
        raw = e.get("evidence_raw") or ""
        if raw:
            try:
                ev = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(ev, dict):
                    ex = ev.get("examples") or ev.get("sample_urls") or ev.get("affected_urls")
                    if isinstance(ex, list):
                        # Preserve original types so _format_example_urls can
                        # unwrap dict-shaped pair records correctly.
                        examples = [u for u in ex if u]
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        if not examples and url_map:
            examples = [url_map.get(pid, "") for pid in e["example_page_ids"]]
            examples = [u for u in examples if u]
        e["example_urls"] = examples
        e["example_label"] = _format_example_urls(examples)
        # Stash pages_total before computing the specific title so it can
        # decide between "site-wide" and "on N pages".
        if pages_total:
            e["pages_total"] = pages_total
        # Keep the raw engine name in a separate field; promote the
        # problem-statement title onto `name` and `title` so every downstream
        # renderer (index, cards, cleanup table) reads as specific.
        raw_name = e.get("name") or e.get("check_id") or ""
        e["raw_name"] = raw_name
        e["name"] = _specific_title_for_issue(e)
        e["title"] = e["name"]
        e["description"] = _describe_issue(e)
        e["impact"] = _impact_for_issue(e)
        e["effort"] = _effort_for_issue(e)
        e["owner"]  = _owner_for_issue(e)
        e["category_label"] = _category_label_for_issue(e)
    issues.sort(key=lambda e: (-e["rank"], -e["pages"], e["check_id"]))
    return issues


# Maps a check_id (or family prefix) to a (template, [evidence_keys])
# pair. The template is filled with the values from evidence_json. Falls
# back to a generic key:value sentence if the check_id is not listed.
_ISSUE_TEMPLATES: dict[str, str] = {
    # ON family
    "ON-034": "Pages return no title tag in raw HTML (length 0). Without a title, search engines have nothing to show as the headline in results.",
    "ON-023": "Pages have only {word_count} words against a 300-word threshold for substantive content. Google flags this as thin and demotes the URL in helpful-content rollups.",
    "ON-041": "Pages ship {h1_count} H1 tags instead of one. Multiple H1s split the page topic signal across competing headings, weakening every one.",
    "ON-061": "{orphan_count} pages have no internal links pointing at them. Search engines reach them only through the sitemap, which gives them almost no ranking weight.",
    "ON-029": "Pages have no visible byline or author block. On a YMYL site this caps trust signals at zero.",
    "ON-032": "Pages publish no datePublished or dateModified. Freshness algorithms cannot rank the page against newer competitor content.",
    "ON-045": "{heading_count} question-format H2 sections found. Search engines look for question headings to surface in People Also Ask and AI Overviews; you get none of that real estate.",
    "ON-065": "Pages ship {external_links} external links over insecure HTTP. Google treats every one as a soft trust signal against the page.",
    "ON-066": "Pages cite {external_links} authoritative outbound sources (.gov, .edu, established medical). For YMYL dental content this caps E-E-A-T trust at the floor.",
    "ON-006": "Primary keyword identification failed because the page has no clear topic signal in title, H1, or copy. The page cannot rank for any specific query.",
    "ON-011": "Keyword density could not be computed because there are too few tokens on the page. The page is effectively empty to a ranking model.",
    "ON-013": "Title cannibalization detected across multiple URLs targeting the same query. Google has to choose one, often dropping the rest from the index.",
    "ON-033": "Semantic relevance score could not be computed because no primary keyword tokens were extracted. The page reads as topically unbounded.",
    "ON-038": "Meta description is missing on this many pages. Google synthesizes its own snippet from page text, which often pulls cookie banners or nav copy.",
    "ON-073": "No JSON-LD detected. Schema (the hidden code that tells Google what a page is) is the single biggest unlock for richer Google listings and AI citation eligibility.",
    "ON-075": "Article schema is missing on blog posts. Without it, posts cannot earn rich snippets or carousel placement.",
    "ON-077": "Pages have question-format H2s but no FAQPage schema, so they cannot earn the FAQ rich result.",
    "ON-080": "Page carries a meta robots tag set to noindex. Google is told not to put it in search results.",
    "ON-119": "Organization entity is undefined on the homepage. Google cannot tie your brand to a Knowledge Graph entry.",
    "ON-123": "Organization schema with sameAs links to social profiles is missing. Google cannot connect your site to your brand entity confidently.",
    # TECH family
    "TECH-001": "robots.txt is missing or unreachable. Google has no crawl directives and may waste crawl budget on low-value paths.",
    "TECH-002": "Sitemap XML failed validation. Google's parser aborts on the malformed entity and silently drops every URL listed after that line.",
    "TECH-019": "No self-referencing canonical tag present. Search engines may pick the wrong main version of the page when duplicates exist.",
    "TECH-020": "Canonical chain detected (page A points at B which points at C). Google does not follow chains; the target URL drops out of the index.",
    "TECH-031": "Title and H1 are written in by JavaScript after the page loads. Google's first pass sees nothing, which suppresses indexation across the site.",
    "TECH-034": "Above-the-fold images carry loading=lazy. The Largest Contentful Paint metric ticks late, lowering the page speed score Google sees.",
    "TECH-041": "/llms.txt does not return a plain-text manifest. AI assistants that look for it cannot read the site map you intended.",
    "TECH-073": "Server takes {value} ms to send the first byte against a 800 ms target. Lab page speed drops 12 to 20 points until this is fixed.",
    "TECH-085": "Security header capture was not run this audit. HSTS, CSP, X-Frame-Options, and Referrer-Policy presence is unverified.",
    # LOC family
    "LOC-032": "{pages_with_local_business_schema} of {pages_checked} pages carry LocalBusiness or Dentist schema. Without it, Google cannot connect the site to a Google Business Profile.",
    "LOC-001": "Google Business Profile could not be retrieved through discovery. Verify the listing exists and is claimed at business.google.com.",
    "LOC-002": "GBP primary and secondary categories could not be evaluated. Wrong categories halve local pack reach.",
    "LOC-013": "NAP (name, address, phone) consistency across business listings could not be evaluated. Inconsistent NAP is a top-3 local-rank suppressor.",
    "LOC-021": "GBP review profile (count, recency, distribution) could not be evaluated. Reviews drive both pack rank and click rate.",
    # OFF family
    "OFF-045": "Unlinked brand-mention search has not been run. Each unlinked mention is a backlink opportunity left on the table.",
    "OFF-049": "Brand is absent from the top 10 organic for its own category query. Even branded searches surface competitors instead.",
    "OFF-050": "Branded search volume could not be measured. Branded volume is the leading indicator that flips local rankings.",
    "OFF-051": "No Knowledge Graph panel for the brand. Google has not resolved your business as a distinct entity.",
    "OFF-054": "Brand entity has low salience on the homepage. Other words on your page outrank your brand as the topic signal.",
    "OFF-062": "Competitor content depth comparison could not be completed. Without it, content-gap targeting is guesswork.",
    "OFF-067": "AI search citation patterns were not measured. Cannot baseline current AI visibility for the brand.",
    "OFF-068": "ChatGPT brand mention probe was not run. Cannot measure where you stand inside the LLM training cut-off.",
    "OFF-069": "Perplexity brand mention probe was not run. Cannot measure live AI-search citation frequency.",
}


# Per-check IMPACT templates (the "what this means for your business" callout).
# Falls back to the dimension-default below when a check_id is not listed.
_IMPACT_TEMPLATES: dict[str, str] = {
    "ON-034": "Without a title tag, the search result for this page is whatever Google chooses to invent from your copy. Click rates fall and your page can be outranked by competitors with strong, specific titles.",
    "ON-023": "Thin pages do not satisfy a query and they pull down the helpful-content score for the whole site. Even pages on other topics rank worse when thin pages exist.",
    "ON-041": "Multiple H1 tags confuse search engines about the actual topic of the page. The result is that the page ranks for nothing in particular.",
    "ON-061": "Orphan pages get almost no ranking weight no matter how good their content is. The pages you wrote to capture local search demand cannot do their job.",
    "ON-029": "On YMYL pages (dental, health, finance), Google checks for a real, credentialled author before ranking. Without it your content is treated as anonymous and untrusted.",
    "ON-032": "Without publish or update dates, Google cannot tell whether the page is current. Health content without dates loses to dated content from competitors.",
    "ON-045": "Question-format headings are the entry point to People Also Ask, AI Overviews, and ChatGPT Citations. Without them you forfeit that real estate.",
    "ON-065": "External links over insecure HTTP signal an unmaintained site. On a YMYL dental property this is a measurable trust signal against you.",
    "ON-066": "Authoritative outbound citations are how Google measures whether you are a real practitioner. Without them you compete from a deficit.",
    "ON-006": "If Google cannot detect a primary keyword on your page, no keyword research and no link building will help it rank.",
    "ON-013": "Cannibalization makes Google pick one URL and drop the rest. You waste content investment on pages that will never rank.",
    "ON-038": "When you do not write the meta description, Google pulls a random snippet from the page. The result is irrelevant, brand-poor SERP listings.",
    "ON-073": "Without schema you forfeit star ratings, FAQ accordions, local pack enhancements, image search ranking, and AI assistant citations. Competitors with schema take the real estate.",
    "ON-075": "Without Article schema your blog posts cannot earn carousel placement or news-style rich results.",
    "ON-077": "Question-format H2s without FAQPage schema are wasted real estate. Competitors with FAQPage take the FAQ rich result.",
    "ON-080": "A noindex tag tells Google to delete the page from the index. Whatever traffic the page would have earned is gone.",
    "ON-119": "Without an Organization entity, Google has no anchor to connect your brand to the rest of your web presence. Knowledge panel eligibility drops to zero.",
    "ON-123": "Without sameAs links Google cannot confirm your social profiles, GBP, and site belong to the same entity. Brand consolidation breaks.",
    "TECH-001": "Without a working robots.txt, Google wastes crawl budget on the wrong URLs and may miss new content for weeks.",
    "TECH-002": "A malformed sitemap silently drops every URL after the parse error. The pages that took the most effort to write are the ones most likely to be invisible.",
    "TECH-019": "Without self-canonical, duplicate URLs (with tracking params, with trailing slashes, with different cases) get treated as competing pages.",
    "TECH-020": "A canonical chain tells Google to drop the page entirely. You lose every backlink and every ranking signal that pointed at the original URL.",
    "TECH-031": "Title and H1 only after JavaScript means Googlebot's first pass sees a blank page. The site cannot rank competitively until this is fixed.",
    "TECH-034": "Above-the-fold lazy loading makes your Largest Contentful Paint metric tick late. Lab page speed scores drop, which Google factors into Core Web Vitals.",
    "TECH-041": "An invalid llms.txt means AI assistants that DO look for it (Anthropic and some Perplexity flows) discard it. Citation opportunity gone.",
    "TECH-073": "A slow first byte is the largest contributor to a low lab page speed score. Even GOOD field data does not save the lab number search consoles surface.",
    "TECH-085": "Missing security headers (HSTS, CSP, X-Frame-Options) cost you trust signals and expose you to clickjacking. Google factors security posture into ranking on YMYL sites.",
    "LOC-032": "Without LocalBusiness schema you forfeit local pack enhancements (hours, phone, directions in SERP). Map pack ranking is depressed across every local query.",
    "LOC-001": "Without a verified GBP, you cannot appear in the local pack or Google Maps for any nearby search. The local pack is usually the single largest lead source for a dental practice.",
    "LOC-002": "Wrong or missing GBP categories cuts your reach in half. Patients searching the right category never see your listing.",
    "LOC-013": "NAP inconsistency across your listings is a top-3 local-rank suppressor. Google treats inconsistent listings as separate weak entities instead of one strong one.",
    "LOC-021": "Reviews drive both pack rank and click-through. Without an active review profile every other local SEO investment underperforms.",
    "OFF-045": "Each unlinked brand mention is a backlink waiting to be claimed by email. Leaving them un-claimed forfeits free authority.",
    "OFF-049": "If you do not appear in the SERP for your own category, every other ranking effort is uphill. You are invisible where customers are looking.",
    "OFF-050": "Without measured branded volume you cannot track whether brand-building investments are paying off.",
    "OFF-051": "No Knowledge Graph means Google does not treat you as a distinct business. Your brand entity is invisible to AI and SERP enrichment systems.",
    "OFF-054": "Low brand salience on your own homepage means Google reads your page as being about something else. Your brand never consolidates as the topical signal.",
    "OFF-062": "Without competitor-depth data you cannot tell which content gaps would actually rank. Content strategy becomes guesswork.",
    "OFF-067": "If you do not measure AI citation rate today, you cannot tell whether your investments are moving it tomorrow.",
    "OFF-068": "Untested ChatGPT brand recall means you do not know if the LLM training cut-off helps or hurts you. You operate blind.",
    "OFF-069": "Untested Perplexity recall means you cannot measure the live-search AI citation surface where competitors may already be winning.",
}

# Fallback impact text by dimension when no per-check_id template matches.
_DIM_IMPACT_FALLBACK: dict[str, str] = {
    "strategy":      "This costs you visibility in the category SERP where customers search before they pick a practice.",
    "content":       "This costs you trust signals Google reads when ranking YMYL queries. Competitors with stronger signals take the click.",
    "onpage":        "This costs you placement on the queries the page is supposed to win. The investment in the page does not pay back.",
    "technical":     "This costs you crawl efficiency, rich-result eligibility, and the page speed score Google factors into ranking.",
    "offpage":       "This costs you brand authority and the off-site mentions Google uses to validate that your business is real and credible.",
    "local":         "This costs you visibility in the local pack and Maps, which is where most local customers actually find a business.",
    "offpage_local": "This costs you visibility in the local pack and Maps, which is where most local customers actually find a business.",
    "geo":           "This costs you citation eligibility inside ChatGPT, Perplexity, and Google AI Overviews where buyer research increasingly starts.",
}

# Effort + Owner defaults per check_id family / dimension.
_EFFORT_BY_CHECK_PREFIX = {
    "TECH": "Medium (1 to 2 days)",
    "LOC":  "Medium (1 day for the claim, 1 week for the listings)",
    "OFF":  "Medium (1 to 2 weeks)",
    "ON":   "Quick (half-day)",
}
_OWNER_BY_DIM = {
    "strategy":      "Owner + SEO lead",
    "content":       "Marketing + writer",
    "onpage":        "Developer + SEO lead",
    "technical":     "Developer",
    "offpage":       "Marketing + outreach",
    "local":         "Owner + listings manager",
    "offpage_local": "Owner + marketing",
    "geo":           "Developer + SEO lead",
}
_CATEGORY_LABEL_BY_DIM = {
    "strategy":      "Strategy",
    "content":       "Content",
    "onpage":        "On-page",
    "technical":     "Technical",
    "offpage":       "Off-page",
    "local":         "Local",
    "offpage_local": "Local",
    "geo":           "GEO",
}


def _impact_for_issue(e: dict) -> str:
    cid = (e.get("check_id") or "").strip()
    t = _IMPACT_TEMPLATES.get(cid)
    if t:
        return t
    return _DIM_IMPACT_FALLBACK.get(e.get("area_key", ""), "This costs you ranking placement and qualified search traffic.")


def _effort_for_issue(e: dict) -> str:
    cid = (e.get("check_id") or "").strip()
    prefix = cid.split("-", 1)[0] if "-" in cid else ""
    return _EFFORT_BY_CHECK_PREFIX.get(prefix, "Medium (half-day)")


def _owner_for_issue(e: dict) -> str:
    return _OWNER_BY_DIM.get(e.get("area_key", ""), "Developer")


def _category_label_for_issue(e: dict) -> str:
    # Special-case schema-shaped checks so the chip reads "SCHEMA" like the
    # reference design instead of the generic dimension label.
    name = (e.get("name") or "").lower()
    if "schema" in name or "json-ld" in name or "structured data" in name:
        return "Schema"
    return _CATEGORY_LABEL_BY_DIM.get(e.get("area_key", ""), "On-page")


# Issue title rewrites - generic check names become problem statements.
# Keys are matched as substrings (lowercase) against the engine's check_name.
# Order matters: more-specific patterns come first.
_NAME_REWRITES: list[tuple[str, str]] = [
    # On-page / headings / titles
    ("title tag optimization",          "Title tag missing or weak"),
    ("title ctr optimization",          "Title tag missing or weak for click rate"),
    ("title keyword placement",         "Primary keyword missing from title"),
    ("title uniqueness check",          "Duplicate page titles"),
    ("title cannibalization",           "Multiple pages targeting the same query"),
    ("h1 optimization",                 "H1 missing or duplicated"),
    ("multiple h1 detection",           "Multiple H1 tags on the same page"),
    ("heading hierarchy analysis",      "Heading hierarchy skips levels"),
    ("meta description optimization",   "Meta description missing"),
    ("meta description uniqueness",     "Duplicate meta descriptions"),
    ("meta description ctr",            "Meta description weak for click rate"),
    ("primary keyword optimization",    "Primary keyword missing from page"),
    ("secondary keyword optimization",  "Secondary keywords missing"),
    ("keyword cannibalization detection", "Multiple pages chasing the same keyword"),
    ("indexability analysis",           "Page set to noindex by mistake"),
    ("canonical tag validation",        "Canonical tag missing or wrong"),
    ("orphan page detection",           "Orphan pages with no internal links"),
    ("rich result eligibility",         "Page not eligible for rich Google listings"),
    ("featured snippet optimization",   "Page not shaped for featured snippet"),
    ("image alt text",                  "Images missing alt text"),
    ("internal link",                   "Internal links missing or weak"),
    ("external link quality",           "External links use insecure HTTP"),
    ("anchor text",                     "Anchor text generic or repetitive"),
    # Content / E-E-A-T
    ("thin content detection",          "Thin content below the helpful-content baseline"),
    ("content depth analysis",          "Content depth below competitor median"),
    ("trust signal analysis",           "Trust signals missing for a YMYL site"),
    ("eeat optimization analysis",      "Author and trust signals missing"),
    ("e-e-a-t",                         "Trust signals missing"),
    ("author expertise signals",        "Author byline missing or weak"),
    ("date freshness",                  "Published / updated dates missing"),
    ("organization schema entity",      "Organization schema missing key fields"),
    ("sameas",                          "sameAs links missing - brand entity unverified"),
    ("readability",                     "Reading grade too high for the topic"),
    # Technical
    ("robots.txt validation",           "robots.txt unreachable or broken"),
    ("xml sitemap validation",          "Sitemap unreachable or malformed"),
    ("website speed check",             "Page speed score below the ranking threshold"),
    ("page speed",                      "Page speed score below the ranking threshold"),
    ("broken page detection",           "Pages returning 4xx or 5xx"),
    ("localbusiness schema",            "LocalBusiness schema missing"),
    ("breadcrumblist",                  "BreadcrumbList schema missing"),
    ("breadcrumb schema",               "BreadcrumbList schema missing"),
    ("faq schema",                      "FAQPage schema missing on Q&A-shaped pages"),
    ("schema markup validation",        "Schema missing or invalid"),
    ("html validation",                 "HTML validation errors"),
    ("lazy loading",                    "Lazy-load applied to above-the-fold images"),
    # GEO / AI search
    ("ai overview optimization",        "Page not shaped for AI Overview pick-up"),
    ("direct answer",                   "Opening paragraph not in the 40-60 word answer band"),
    ("question-and-answer",             "H2s not framed as searcher questions"),
    ("structured content analysis",     "Pages missing lists, tables, and comparison blocks"),
    ("list optimization",               "Bullet lists missing where AI engines look for them"),
    ("generative search",               "Page not optimized for generative-search citation"),
    ("about + contact page presence",   "About + Contact page presence weak"),
    ("information density",             "Information density below AI-citation threshold"),
    # Off-page / brand
    ("brand mention",                   "Brand mentions absent from category SERP"),
    ("knowledge graph",                 "No Knowledge Graph entity for your brand"),
    ("brand salience",                  "Brand salience low on your own homepage"),
    # Local SEO
    ("citation consistency",            "Business listings missing or NAP-inconsistent"),
    ("nap consistency",                 "Business name/address/phone inconsistent across listings"),
    ("gbp",                             "Google Business Profile gaps"),
    ("reputation",                      "Review reputation needs active management"),
]


def _specific_title_for_issue(e: dict) -> str:
    """Rewrite a generic check name into a problem-statement title with the
    affected-page count appended. "H1 optimization" + 16 pages becomes
    "H1 missing or duplicated on 16 pages". Site-wide checks (where pages
    >= total) get "site-wide" instead of a count. Singles get nothing
    appended ("on 1 page" reads worse than no suffix at all).
    """
    raw_name = (e.get("name") or "").strip()
    name_lc = raw_name.lower()
    rewritten = ""
    for needle, replacement in _NAME_REWRITES:
        if needle in name_lc:
            rewritten = replacement
            break
    if not rewritten:
        # Strip trailing "optimization" / "analysis" / "validation" / "check"
        # / "detection" so the residual reads as a noun, not a process.
        base = re.sub(
            r"\s+(?:optimization|analysis|validation|check|detection|optimisation)\b",
            "",
            raw_name,
            flags=re.IGNORECASE,
        ).strip()
        rewritten = base or raw_name

    n_pages = e.get("pages", 0)
    total = e.get("pages_total") or 0
    if total and n_pages >= total:
        return f"{rewritten} site-wide"
    if n_pages > 1:
        return f"{rewritten} on {n_pages} pages"
    return rewritten


def _describe_issue(e: dict) -> str:
    """Build a 2-3 line plain-English description of the issue from the
    template registry above, falling back to a key:value rendering of
    evidence_json if no template matches. Appends 1-3 example URLs when the
    issue affects a small enough subset of pages that examples add clarity.
    """
    cid = (e.get("check_id") or "").strip()
    raw = e.get("evidence_raw") or ""
    ev: dict = {}
    if raw:
        try:
            ev = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
        except (json.JSONDecodeError, ValueError):
            ev = {}

    base = ""
    template = _ISSUE_TEMPLATES.get(cid)
    if template:
        try:
            base = template.format(**{k: v for k, v in ev.items() if v is not None})
        except (KeyError, IndexError, ValueError):
            pass

    if not base:
        # Generic fallback: parse evidence_json into a short sentence.
        if isinstance(ev, dict) and ev:
            reason = ev.get("reason")
            if reason and isinstance(reason, str):
                base = reason if len(reason) < 220 else (reason[:217] + "...")
            else:
                parts: list[str] = []
                for k, v in list(ev.items())[:3]:
                    if v is None:
                        parts.append(f"{k}: not captured")
                    elif isinstance(v, list):
                        parts.append(f"{k}: {len(v)} items")
                    else:
                        parts.append(f"{k}: {v}")
                snippet = ", ".join(parts)
                if e.get("name"):
                    base = f"{e['name']} flagged across affected pages. Observed: {snippet}."
                else:
                    base = f"Observed: {snippet}."
        else:
            base = f"{e.get('name', 'This check')} flagged on the affected pages."

    # Append 1-3 example URLs when the issue affects a small enough subset
    # that examples add clarity. Above 30 affected pages we skip examples
    # because the dim-strip's count already conveys "this is everywhere" and
    # listing three of fifty would feel arbitrary.
    n_pages = e.get("pages", 0)
    label = (e.get("example_label") or "").strip()
    if label and 1 <= n_pages <= 29:
        verb = "have" if n_pages > 1 else "has"
        base = base.rstrip(". ") + f". For example: {label} {verb} this issue."

    return base


def build_issue_register_pages(issues: list[dict], pages_crawled: int) -> list[str]:
    """Render EVERY issue so none is dropped to fit a page cap.

    Critical + major issues become compact cards; minor issues are
    consolidated into one dense cleanup table. The whole register is a single
    continuous .reg-flow block that auto-paginates: cards/rows pack as densely
    as they fit per physical page and break cleanly between items, so there
    are no half-empty overflow pages. Full-mode only (condensed keeps its cap).

    Returns a one-element list (the flow block) so callers can `.extend()` it
    into the page stream just like the fixed pages.
    """
    if not issues:
        return []

    def _affects(e: dict) -> str:
        n = e["pages"]
        if pages_crawled and n >= pages_crawled:
            return "Site-wide"
        return f"{n} page" + ("s" if n != 1 else "")

    crit_major = [e for e in issues if e["severity"] in ("critical", "major")]
    minors     = [e for e in issues if e["severity"] == "minor"]

    def _card(e: dict) -> str:
        cls = "crit" if e["severity"] == "critical" else e["severity"]
        fix = md_inline(_cap(e.get("fix") or "Apply the standard remediation for this check.", 230))
        return (
            f'<div class="iss-card {cls}">'
            '<div class="iss-card-head">'
            f'<div class="iss-card-title">{md_inline(e["name"])}</div>'
            f'<div class="iss-card-count" style="font-size:11pt;">{_affects(e)}</div>'
            '</div>'
            '<div class="iss-card-meta" style="margin-top:0; margin-bottom:6pt;">'
            f'<span class="sev-chip {cls}">{e["severity"].upper()}</span>'
            f'{_area_chip(e["area_label"])}'
            '</div>'
            f'<div class="iss-card-body"><strong>Fix:</strong> {fix}</div>'
            '</div>'
        )

    crit   = [e for e in crit_major if e["severity"] == "critical"]
    majors = [e for e in crit_major if e["severity"] == "major"]
    pages: list[str] = []

    # ---- Critical issues: exactly TWO per page (premium treatment). Each
    #      pair sits in its own .page; 2 cards never overflow one A4 sheet. ----
    for i in range(0, len(crit), 2):
        pair = crit[i:i + 2]
        lead = ""
        if i == 0:
            lead = (
                '<div class="reg-lead">'
                '<div class="reg-lead-eyebrow">Complete Issue Register - Critical</div>'
                f'<div class="reg-lead-title">Every critical issue, two to a page - {len(crit)} in '
                f'total, each with the pages it hits and its fix.</div>'
                '<div class="reg-lead-sub">These are the issues costing you customers now. The '
                'priority cards earlier in this report cover the highest-leverage of them in depth.</div>'
                '</div>'
            )
        cards = "".join(_card(e) for e in pair)
        pages.append(f'<div class="page">{lead}<div class="reg-cards">{cards}</div></div>')

    # ---- Major + minor: one continuous flowing block (packs densely). ----
    flow: list[str] = []
    if majors:
        flow.append(
            '<div class="reg-lead">'
            '<div class="reg-lead-eyebrow">Complete Issue Register - Major</div>'
            f'<div class="reg-lead-title">All {len(majors)} major issues, none omitted - the pages '
            f'each affects and the exact fix.</div>'
            '<div class="reg-lead-sub">These hold growth back this quarter. Minor housekeeping '
            'items follow in a single checklist.</div>'
            '</div>'
        )
        flow.append('<div class="reg-cards">' + "".join(_card(e) for e in majors) + '</div>')

    if minors:
        flow.append(
            '<div class="reg-lead" style="margin-top:14pt;">'
            '<div class="reg-lead-eyebrow">Minor Cleanup Checklist</div>'
            f'<div class="reg-lead-title">{len(minors)} minor issues - low effort, worth clearing.</div>'
            '</div>'
        )
        body_rows = "".join(
            '<tr>'
            f'<td>{md_inline(e["name"])}</td>'
            f'<td style="white-space:nowrap;">{_area_chip(e["area_label"])}</td>'
            f'<td style="white-space:nowrap; text-align:right;">{_affects(e)}</td>'
            f'<td>{md_inline(_cap(e.get("fix") or "Standard remediation.", 160))}</td>'
            '</tr>'
            for e in minors
        )
        flow.append(
            '<table class="md-table reg-min-table"><thead><tr>'
            '<th>Issue</th><th>Area</th><th>Affects</th><th>Fix</th>'
            '</tr></thead><tbody>' + body_rows + '</tbody></table>'
        )

    if flow:
        pages.append('<div class="reg-flow">' + "".join(flow) + '</div>')
    return pages


# ============================================================
# NEW (2026-06-16): per-dimension section pages + executive summary +
# strategy recommendation + closing CTA. The "no page cap, every issue"
# contract lives here. Each dimension renders all its issues grouped by
# severity, then a "What's working" passes card, then the next dimension.
# ============================================================

DIMENSION_ORDER = ["strategy", "content", "onpage", "technical", "offpage", "local", "geo"]


def _passes_by_dimension(artifact_dir: Path) -> dict[str, list[str]]:
    """For each dimension key, return up to 5 distinct passing check_names.
    A "pass" is a finding row with status == 'pass'. The same check_id
    appearing on multiple pages collapses to one entry."""
    rows = _load_all_finding_rows(artifact_dir)
    seen: dict[str, set[str]] = {k: set() for k in DIMENSION_ORDER}
    names: dict[str, list[str]] = {k: [] for k in DIMENSION_ORDER}
    for r in rows:
        if (r.get("status") or "").lower() != "pass":
            continue
        cid = (r.get("check_id") or "").strip()
        if not cid:
            continue
        dim = _section_categorize(cid, r.get("category"), r.get("subcategory"))
        if cid in seen.get(dim, set()):
            continue
        seen[dim].add(cid)
        nm = (r.get("check_name") or "").strip() or cid
        if len(names[dim]) < 5:
            names[dim].append(nm)
    return names


def _build_one_issue_card_v2(e: dict) -> str:
    """Rich fp-finding card for a single issue. Two of these stack per A4
    sheet via the existing fp-paired layout: eyebrow + severity chip +
    category chip + headline + 2-3 line description, then a side-by-side
    Impact / How we fix it callout pair, then Effort + Owner pills.

    This is the SAME visual language as the high-priority finding cards
    that the client liked in the previous design system, applied to every
    critical and major issue in the dimension flow.
    """
    sev = (e.get("severity") or "minor").lower()
    sev_chip_html = severity_chip(sev)

    cat_label = e.get("category_label") or _CATEGORY_LABEL_BY_DIM.get(e.get("area_key", ""), "On-page")
    cat_chip_html = (
        f'<span class="chip" style="background: {PALETTE["blue_bg"]}; color: {PALETTE["blue_accent"]};">'
        f'{md_inline(cat_label.upper())}</span>'
    )

    description = _cap(e.get("description") or e.get("fix") or "", 360)
    impact_text = _cap(e.get("impact") or "", 220)
    fix_text    = _cap(e.get("fix") or "", 220)
    effort_text = (e.get("effort") or "").strip()
    owner_text  = (e.get("owner") or "").strip()

    pages_str = (
        "Site-wide" if e.get("pages_total") and e["pages"] >= e["pages_total"]
        else f"{e['pages']} page" + ("s" if e["pages"] != 1 else "")
    )
    eyebrow = f"ISSUE - {pages_str.upper()}"

    callouts: list[str] = []
    if impact_text:
        callouts.append(
            f'<div class="fp-impact">'
            f'<div class="fp-impact-label">What this means for your business</div>'
            f'<div class="fp-impact-text">{md_inline(impact_text)}</div>'
            f'</div>'
        )
    if fix_text:
        callouts.append(
            f'<div class="fp-fix">'
            f'<div class="fp-fix-label">How we fix it</div>'
            f'<div class="fp-fix-text">{md_inline(fix_text)}</div>'
            f'</div>'
        )
    callouts_html = (
        callouts[0] if len(callouts) == 1
        else (f'<div class="fp-callouts">{"".join(callouts)}</div>' if callouts else "")
    )

    pills: list[str] = []
    if effort_text:
        pills.append(f'<span class="fp-effort">Effort: {md_inline(_cap(effort_text, 70))}</span>')
    if owner_text:
        pills.append(f'<span class="fp-owner">Owner: {md_inline(_cap(owner_text, 50))}</span>')
    pills_html = f'<div class="fp-meta-row">{"".join(pills)}</div>' if pills else ""

    return f"""
  <div class="fp-finding fp-paired">
    <div class="fp-num">{md_inline(eyebrow)}</div>
    <div class="fp-chips">{sev_chip_html}{cat_chip_html}</div>
    <div class="fp-headline">{md_inline(e.get("name", ""))}</div>
    <div class="fp-desc">{md_inline(description)}</div>
    {callouts_html}
    {pills_html}
  </div>"""


def _build_passes_card(dim_label: str, passes: list[str]) -> str:
    """The 'What is working in this section' card. Up to 5 passes."""
    if passes:
        items = "".join(
            f'<li><strong>{md_inline(_cap(p, 110))}</strong></li>' for p in passes[:5]
        )
        body = f'<ul class="passes-list">{items}</ul>'
    else:
        body = (
            '<div class="passes-empty">Every check in this section flagged '
            'at least one issue. No passes to report in this dimension.</div>'
        )
    return (
        '<div class="passes-card">'
        f'<div class="passes-card-head">What is working in {dim_label}</div>'
        f'{body}'
        '</div>'
    )


# ============================================================
# CITATIONS / BUSINESS LISTINGS BLOCK
# Surfaces the audit's own citations.json status (found/missing/inconsistent
# per directory) AND a universal priority list of business directories the
# practice should claim, with each directory's domain rating (DR). The
# universal list is drawn from the "Citation Gap" tab of the manual GMB Audit
# spreadsheet so the report mirrors what an in-house local-SEO analyst would
# hand back. Lives at the end of the OFF-PAGE dimension flow.
# ============================================================

_PRIORITY_DIRECTORIES: list[dict] = [
    # The "brand boosters" plus the highest-DR aggregators from the Cit Gap
    # tab. DR is taken straight from the spreadsheet. Categories shown
    # informally in the column header so the reader sees why each one matters.
    {"name": "Google Business Profile", "dr": 100, "category": "Anchor",       "note": "The single most-important local listing. Must be claimed and verified."},
    {"name": "Apple Maps (Apple Business Connect)", "dr": 97, "category": "Anchor", "note": "Powers Maps results on every iPhone. Free to claim at businessconnect.apple.com."},
    {"name": "Bing Places", "dr": 94, "category": "Anchor",                  "note": "Anchor listing for Bing + DuckDuckGo + ChatGPT search. Claim at bingplaces.com."},
    {"name": "Facebook Business",      "dr": 96, "category": "Anchor",       "note": "The second business profile most people check after Google."},
    {"name": "Yelp",                    "dr": 93, "category": "Anchor",       "note": "Highest review-trust signal outside Google. Claim at biz.yelp.com."},
    {"name": "Foursquare",              "dr": 91, "category": "Aggregator",   "note": "Feeds dozens of downstream apps. One claim, many citations."},
    {"name": "YellowPages",             "dr": 90, "category": "Top citation", "note": "Mainstream consumer directory; still indexed strongly by Google."},
    {"name": "Manta",                   "dr": 87, "category": "Top citation", "note": "B2B-leaning, but useful trust signal."},
    {"name": "MerchantCircle",          "dr": 85, "category": "Top citation", "note": "Light-touch listing; quick win."},
    {"name": "Superpages",              "dr": 85, "category": "Top citation", "note": "Sister property to YellowPages, separate citation."},
    {"name": "Hotfrog",                 "dr": 80, "category": "Aggregator",   "note": "Free listing; submit once, feeds smaller directories."},
    {"name": "EZlocal",                 "dr": 80, "category": "Aggregator",   "note": "Aggregator with broad downstream reach."},
    {"name": "Brownbook",               "dr": 79, "category": "Aggregator",   "note": "International aggregator; useful for cross-border discoverability."},
    {"name": "ShowMeLocal",             "dr": 79, "category": "Aggregator",   "note": "US-focused aggregator; quick claim."},
    {"name": "Dexknows",                "dr": 78, "category": "Top citation", "note": "Mid-tier, still ranks for branded queries."},
    {"name": "Data Axle (formerly InfoUSA)", "dr": 78, "category": "Aggregator", "note": "Feeds Apple, Yelp, Bing, and many smaller directories."},
    {"name": "2FindLocal",              "dr": 78, "category": "Aggregator",   "note": "Lightweight citation aggregator."},
    {"name": "Crunchbase",              "dr": 91, "category": "Brand booster", "note": "Boosts Knowledge Graph signal for business entities."},
    {"name": "Neustar Localeze",        "dr": 73, "category": "Aggregator",   "note": "Major data aggregator; feeds Bing, Yelp, Apple."},
    {"name": "BBB.org",                 "dr": 92, "category": "Trust signal", "note": "High-authority trust badge for established businesses."},
]


def _read_citations_data(artifact_dir: Path) -> dict:
    """Parse citations.json with the actual field names the engine writes.
    Returns a unified shape: {checked, found, missing, inconsistent,
    avg_nap_score, per_source: [{name, found, listing_url, nap_score,
    address_match, phone_match}]}. Empty dict on any failure."""
    fp = artifact_dir / "citations.json"
    if not fp.exists():
        return {}
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    per_source_raw = data.get("per_source") or data.get("results") or data.get("checks") or []
    per_source: list[dict] = []
    for r in per_source_raw:
        if not isinstance(r, dict):
            continue
        per_source.append({
            "name":          (r.get("source") or r.get("directory") or r.get("name") or "").strip(),
            "found":         bool(r.get("found")),
            "listing_url":   r.get("listing_url") or r.get("url") or r.get("profile_url"),
            "nap_score":     r.get("nap_score"),
            "name_match":    r.get("name_match"),
            "address_match": r.get("address_match"),
            "phone_match":   r.get("phone_match"),
        })
    return {
        "checked":      int(data.get("total_checked") or data.get("checked") or len(per_source) or 0),
        "found":        int(data.get("found_count") or data.get("found") or 0),
        "missing":      int(data.get("missing_count") or 0) or max((int(data.get("total_checked") or len(per_source) or 0)) - int(data.get("found_count") or 0), 0),
        "inconsistent": int(data.get("inconsistent_count") or 0),
        "avg_nap":      data.get("average_nap_score"),
        "per_source":   per_source,
    }


def _read_competitor_data(artifact_dir: Path) -> list[dict]:
    """Pull the named competitor list from agent-c3 if it ran. Returns
    [] gracefully when the file is missing or malformed."""
    fp = artifact_dir / "agent-c3-competitor-gap.json"
    if not fp.exists():
        return []
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return []
    competitors = data.get("named_competitors") or data.get("competitors") or []
    if not isinstance(competitors, list):
        return []
    return competitors


# GMB self-audit checklist mirroring the "Audit" tab of the manual GMB
# Audit spreadsheet. Universal items that every local business should
# self-verify inside business.google.com. Rendered as a checkbox grid.
_GMB_SELF_AUDIT: list[tuple[str, list[str]]] = [
    ("Business information accuracy", [
        "Business name matches your legal name (no keyword stuffing)",
        "Primary category set; secondary category covers your sub-niche",
        "Address visible and matches the website footer + payment processor",
        "Service area defined (cities, ZIPs, or radius) if you serve clients off-site",
        "Phone number matches the website (tracking numbers handled correctly)",
        "Website URL added with a UTM-tagged variant for measurement",
        "Business hours accurate (including holiday hours for the next 12 months)",
        "Booking link added if applicable",
        "Founding / opening date filled in",
    ]),
    ("Services + products optimization", [
        "Every service has its own entry with a 200-300 character description",
        "Service descriptions use natural language (not keyword spam)",
        "Service categories match the primary category logic",
        "Price ranges populated where customers expect them",
        "Products section populated with at least 6 products (if applicable)",
        "Each product has a clear photo, name, and CTA",
    ]),
    ("Photos + visual signal", [
        "Geo-tagged original photos uploaded (not stock or web-scraped)",
        "Logo + cover photo present and on-brand",
        "30+ photos across exterior, interior, team, work",
        "Upload cadence consistent (2-4 new photos per month)",
        "Before / after photos for service businesses",
    ]),
    ("Reviews + reputation", [
        "Response on every review within 48 hours, owner account voice",
        "Service-related keywords appear naturally in review responses",
        "Negative review response template prepared (calm, factual, off-platform)",
        "Active review-request workflow at every post-purchase touchpoint",
        "Cross-platform review parity (Yelp, Facebook, industry-specific)",
    ]),
    ("Posts + Q&A", [
        "Weekly post cadence (Offer, Update, Event, Product rotation)",
        "FAQ section seeded with 5-10 owner-posted Q&A entries",
        "Seasonal posts used (holidays, school year, weather-driven demand)",
        "Each post links to a deep page on the site, not the homepage",
    ]),
    ("Local SEO signals on the site", [
        "NAP (Name, Address, Phone) consistent across every page footer",
        "LocalBusiness schema on the homepage with matching NAP and geo coordinates",
        "Google Business Profile embedded on the contact page",
        "Local backlinks from chamber, BBB, sponsorships",
        "Categories on the site match the GBP categories logic",
    ]),
]


def build_offpage_complete_section(
    artifact_dir: Path,
    run_meta: dict,
    scores: dict,
    off_issues: list[dict],
    off_passes: list[str],
) -> str:
    """Render the comprehensive Off-page + Business Citations section that
    mirrors the manual GMB Audit spreadsheet (Location Data / Citation Audit
    / Compare with Competitors / Audit / Cit Gap). Every block degrades
    gracefully when its source data is missing. Returns a single
    .reg-flow.dim-section block ready to slot into pages_html.
    """
    citations  = _read_citations_data(artifact_dir)
    competitors = _read_competitor_data(artifact_dir)
    domain = (run_meta.get("domain") or "").strip() or "your site"

    score = scores.get("off_page") or scores.get("offpage")
    score_chip = ""
    if score is not None:
        try:
            s = float(score)
            tone = "good" if s >= 75 else ("warn" if s >= 50 else "crit")
            score_chip = f'<span class="dim-score-chip {tone}">{round(s):d} / 100</span>'
        except (TypeError, ValueError):
            pass

    # Issue count for the off-page section combines: (a) any OFF-* finding
    # cards that came through the normal pipeline, (b) the missing citations
    # count (every missing listing is an off-page item to address), (c) the
    # competitor gap count. This makes the header reflect real work to do.
    crit  = [e for e in off_issues if e["severity"] == "critical"]
    majs  = [e for e in off_issues if e["severity"] == "major"]
    mins  = [e for e in off_issues if e["severity"] == "minor"]
    listing_gap = max(int(citations.get("missing", 0) or 0), 0)
    competitor_gap = len(competitors) if competitors else 0
    derived_total = len(crit) + len(majs) + len(mins) + (1 if listing_gap else 0) + (1 if competitor_gap else 0)

    flow_parts: list[str] = []

    # ---- 1. Section header (dim-header-strip style, real counts) ----
    flow_parts.append(
        '<div class="dim-header-strip">'
        '<div class="dim-header-eyebrow">OFF-PAGE + BUSINESS LISTINGS</div>'
        f'<div class="dim-header-title">Off-page issues in your site ({derived_total})</div>'
        '<div class="dim-header-meta">'
        f'<span class="dim-stat crit"><strong>{len(crit) + (1 if listing_gap else 0)}</strong> critical</span>'
        f'<span class="dim-stat major"><strong>{len(majs) + (1 if competitor_gap else 0)}</strong> major</span>'
        f'<span class="dim-stat minor"><strong>{len(mins)}</strong> minor</span>'
        f'{score_chip}'
        '</div>'
        '</div>'
    )

    # ---- 2. Any actual finding cards (OFF-* findings, if the engine
    #         produced them or future agents wrote them). ----
    if crit:
        flow_parts.append(
            '<div class="reg-cards">'
            + "".join(_build_one_issue_card_v2(e) for e in crit)
            + '</div>'
        )
    if majs:
        flow_parts.append(
            f'<div class="dim-sub-lead">{len(majs)} major off-page issue{"s" if len(majs)!=1 else ""}</div>'
            '<div class="reg-cards">'
            + "".join(_build_one_issue_card_v2(e) for e in majs)
            + '</div>'
        )

    # ---- 3. Citation snapshot (now with REAL counts from per_source) ----
    snap_html = (
        '<div class="cit-summary-card">'
        '<div class="cit-summary-eyebrow">Citation snapshot - what we tested</div>'
        '<div class="cit-summary-row">'
        f'<div class="cit-summary-stat"><div class="cit-stat-val">{citations.get("checked", 0)}</div><div class="cit-stat-lbl">directories checked</div></div>'
        f'<div class="cit-summary-stat good"><div class="cit-stat-val">{citations.get("found", 0)}</div><div class="cit-stat-lbl">listings found</div></div>'
        f'<div class="cit-summary-stat warn"><div class="cit-stat-val">{citations.get("missing", 0)}</div><div class="cit-stat-lbl">listings missing</div></div>'
        f'<div class="cit-summary-stat crit"><div class="cit-stat-val">{citations.get("inconsistent", 0)}</div><div class="cit-stat-lbl">NAP inconsistencies</div></div>'
        '</div>'
        '</div>'
    )
    flow_parts.append(snap_html)

    # ---- 4. Per-citation status table (mirrors xlsx "Citation Audit" tab) ----
    per_source = citations.get("per_source") or []
    if per_source:
        def _status_chip(r: dict) -> str:
            if r.get("found"):
                ns = r.get("nap_score")
                if ns is not None and ns >= 0.9:
                    return '<span class="cit-status-chip good">Correct NAP</span>'
                if ns is not None and ns >= 0.5:
                    return '<span class="cit-status-chip warn">NAP mismatch</span>'
                return '<span class="cit-status-chip warn">Found, needs check</span>'
            return '<span class="cit-status-chip crit">Missing</span>'

        def _action(r: dict) -> str:
            if not r.get("found"):
                return "Claim and submit identical NAP."
            ns = r.get("nap_score")
            if ns is not None and ns < 0.9:
                return "Update listing to match the master NAP exactly."
            return "Monitor; review and respond to feedback."

        def _row(r: dict) -> str:
            ns = r.get("nap_score")
            nap_cell = f'<td class="cit-dr">{int(round(ns * 100))}%</td>' if ns is not None else '<td class="cit-dr">-</td>'
            return (
                '<tr>'
                f'<td><strong>{md_inline(r["name"])}</strong></td>'
                f'<td>{_status_chip(r)}</td>'
                f'{nap_cell}'
                f'<td>{md_inline(_action(r))}</td>'
                '</tr>'
            )
        rows = "".join(_row(r) for r in per_source)
        flow_parts.append(
            '<div class="cit-priority-lead">Per-directory citation status</div>'
            '<div class="cit-priority-sub">Every directory we tested, the NAP match status against your master record, and the action required. NAP match is name, address, and phone number consistency - any mismatch hurts ranking instead of helping it.</div>'
            '<table class="cit-table">'
            '<thead><tr><th>Directory</th><th>Status</th><th>NAP</th><th>Action required</th></tr></thead>'
            f'<tbody>{rows}</tbody>'
            '</table>'
        )

    # ---- 5. GMB self-audit checklist (mirrors xlsx "Audit" tab) ----
    checklist_html_parts: list[str] = []
    for group_title, items in _GMB_SELF_AUDIT:
        items_html = "".join(
            f'<li><span class="gmb-check-box"></span>{md_inline(item)}</li>'
            for item in items
        )
        checklist_html_parts.append(
            '<div class="gmb-check-group">'
            f'<div class="gmb-check-group-title">{md_inline(group_title)}</div>'
            f'<ul class="gmb-check-list">{items_html}</ul>'
            '</div>'
        )
    flow_parts.append(
        '<div class="cit-priority-lead" style="margin-top:18pt;">Google Business Profile self-audit checklist</div>'
        '<div class="cit-priority-sub">Walk through these items inside business.google.com. Each unchecked box is an item to fix this quarter. Hours, photos, services, and reviews each have their own block; the right cadence is one focused pass per week.</div>'
        + '<div class="gmb-checklist-grid">'
        + "".join(checklist_html_parts)
        + '</div>'
    )

    # ---- 6. Competitor GMB comparison (mirrors xlsx "Compare with Competitors") ----
    if competitors:
        comp_rows = "".join(
            '<tr>'
            f'<td><strong>{md_inline(c.get("name", ""))}</strong></td>'
            f'<td class="cit-dr">{c.get("serp_position", "-")}</td>'
            f'<td>{md_inline((c.get("url") or "").replace("https://", "").replace("http://", "").rstrip("/"))[:48]}</td>'
            f'<td>{md_inline(_cap(c.get("why_they_win") or "Outranks you on the category SERP for this market.", 180))}</td>'
            '</tr>'
            for c in competitors[:6]
        )
        flow_parts.append(
            '<div class="cit-priority-lead" style="margin-top:18pt;">Who is ranking ahead of you, and why</div>'
            '<div class="cit-priority-sub">The named competitors that hold positions ahead of you on the category SERP. The right move is not to copy them. It is to identify the one signal each one wins on, then close that gap deliberately.</div>'
            '<table class="cit-table">'
            '<thead><tr><th>Competitor</th><th>Rank</th><th>Website</th><th>Why they win</th></tr></thead>'
            f'<tbody>{comp_rows}</tbody>'
            '</table>'
        )

    # ---- 7. Citation Gap - priority directories with DR (universal) ----
    priority_rows = "".join(
        '<tr>'
        f'<td><strong>{md_inline(d["name"])}</strong></td>'
        f'<td class="cit-dr">{int(d["dr"])}</td>'
        f'<td><span class="cit-cat-chip cit-cat-{d["category"].lower().replace(" ", "-").replace("/", "-")}">{md_inline(d["category"])}</span></td>'
        f'<td>{md_inline(d["note"])}</td>'
        '</tr>'
        for d in _PRIORITY_DIRECTORIES
    )
    flow_parts.append(
        '<div class="cit-priority-lead" style="margin-top:18pt;">Priority directories to claim, ranked by domain rating</div>'
        '<div class="cit-priority-sub">The universal claim list every local business should work through. Anchor listings first (top four), then aggregators, then trust signals. Each directory should carry identical NAP to your Google Business Profile - any mismatch hurts ranking instead of helping it.</div>'
        '<table class="cit-table">'
        '<thead><tr><th>Directory</th><th>DR</th><th>Type</th><th>Why it matters</th></tr></thead>'
        f'<tbody>{priority_rows}</tbody>'
        '</table>'
    )

    # ---- 8. Passes card (tucked at the end) ----
    flow_parts.append(_build_passes_card("Off-page", off_passes))

    return '<div class="reg-flow dim-section">' + "".join(flow_parts) + '</div>'


def build_dimension_section_pages(
    artifact_dir: Path,
    all_issues: list[dict],
    pages_crawled: int,
    scores: dict,
) -> list[str]:
    """Render the 6 dimension sections. Each dimension is ONE continuous
    .reg-flow block that paginates naturally with `page-break-before: always`
    forcing a fresh sheet at the dim boundary. Issue cards pack densely
    (3-4 per page), no wasted space. Structure inside each block:
      - Tight dim header strip (eyebrow + title-with-count + sev counts + score)
      - Critical issue cards (full-width)
      - Major issue cards (flow)
      - Minor cleanup table
      - "What is working" passes card tucked at the end
    No dedicated opener pages. No dedicated passes pages.
    """
    pages_out: list[str] = []
    passes = _passes_by_dimension(artifact_dir)

    score_for_dim = {
        "strategy":      scores.get("off_page") or scores.get("offpage"),
        "content":       scores.get("on_page") or scores.get("onpage"),
        "onpage":        scores.get("on_page") or scores.get("onpage"),
        "technical":     scores.get("technical"),
        "offpage":       scores.get("off_page") or scores.get("offpage"),
        "local":         scores.get("local_seo") or scores.get("local"),
        "geo":           scores.get("off_page") or scores.get("offpage"),
    }

    for e in all_issues:
        e["pages_total"] = pages_crawled

    # Read run.json once for the off-page section builder.
    run_path = artifact_dir / "run.json"
    run_meta: dict = {}
    if run_path.exists():
        try:
            run_meta = json.loads(run_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            run_meta = {}

    for dim_key in DIMENSION_ORDER:
        # The off-page section gets the full GMB-spreadsheet treatment:
        # business identity card, citation snapshot with real per-source
        # data, GMB self-audit checklist, competitor comparison, and the
        # universal Citation Gap directory list with DRs. Fully self-contained
        # builder that degrades gracefully when source data is missing.
        if dim_key == "offpage":
            off_issues = [e for e in all_issues if e["area_key"] == "offpage"]
            off_passes = passes.get("offpage", [])
            pages_out.append(build_offpage_complete_section(
                artifact_dir, run_meta, scores, off_issues, off_passes,
            ))
            continue

        dim_label = SECTION_LABELS.get(dim_key, dim_key)
        dim_issues = [e for e in all_issues if e["area_key"] == dim_key]
        crit = [e for e in dim_issues if e["severity"] == "critical"]
        majs = [e for e in dim_issues if e["severity"] == "major"]
        mins = [e for e in dim_issues if e["severity"] == "minor"]
        total = len(crit) + len(majs) + len(mins)
        dim_passes = passes.get(dim_key, [])
        # The off-page section always renders because it carries the
        # business-citations directory block. Other dimensions skip on empty.
        if dim_key != "offpage" and not (total or dim_passes):
            continue

        score = score_for_dim.get(dim_key)
        score_chip = ""
        if score is not None:
            try:
                s = float(score)
                tone = "good" if s >= 75 else ("warn" if s >= 50 else "crit")
                score_chip = (
                    f'<span class="dim-score-chip {tone}">{round(s):d} / 100</span>'
                )
            except (TypeError, ValueError):
                pass

        flow_parts: list[str] = []

        # Tight header strip - takes ~12% of the page, then content flows below.
        flow_parts.append(
            '<div class="dim-header-strip">'
            f'<div class="dim-header-eyebrow">{md_inline(dim_label.upper())}</div>'
            f'<div class="dim-header-title">{md_inline(dim_label)} issues '
            f'in your site ({total})</div>'
            '<div class="dim-header-meta">'
            f'<span class="dim-stat crit"><strong>{len(crit)}</strong> critical</span>'
            f'<span class="dim-stat major"><strong>{len(majs)}</strong> major</span>'
            f'<span class="dim-stat minor"><strong>{len(mins)}</strong> minor</span>'
            f'{score_chip}'
            '</div>'
            '</div>'
        )

        # Critical first, packed in the same flow (no per-card page break).
        if crit:
            flow_parts.append(
                '<div class="reg-cards">'
                + "".join(_build_one_issue_card_v2(e) for e in crit)
                + '</div>'
            )

        # Major issues - same flow, after a slim sub-heading.
        if majs:
            flow_parts.append(
                f'<div class="dim-sub-lead">{len(majs)} major '
                f'issue{"s" if len(majs)!=1 else ""}</div>'
                '<div class="reg-cards">'
                + "".join(_build_one_issue_card_v2(e) for e in majs)
                + '</div>'
            )

        # Minor issues - dense table (one row per minor).
        if mins:
            rows_html = "".join(
                '<tr>'
                f'<td>{md_inline(e["name"])}</td>'
                f'<td style="white-space:nowrap; text-align:right;">'
                f'{e["pages"]} page' + ("s" if e["pages"] != 1 else "") + '</td>'
                f'<td>{md_inline(_cap(e.get("fix") or "Standard remediation.", 160))}</td>'
                '</tr>'
                for e in mins
            )
            flow_parts.append(
                f'<div class="dim-sub-lead">{len(mins)} minor cleanup '
                f'item{"s" if len(mins)!=1 else ""}</div>'
                '<table class="md-table reg-min-table"><thead><tr>'
                '<th>Issue</th><th>Affects</th><th>Fix</th>'
                '</tr></thead><tbody>'
                f'{rows_html}'
                '</tbody></table>'
            )

        # "What is working" tucked at the end of the same flow.
        flow_parts.append(_build_passes_card(dim_label, dim_passes))

        pages_out.append(
            '<div class="reg-flow dim-section">'
            + "".join(flow_parts)
            + '</div>'
        )

    return pages_out


def build_executive_summary_page(exec_md: str, run_meta: dict) -> str:
    """The 500-700 character plain-English executive summary, rendered on
    its own page right after the index. Reads the writer's prose from the
    section MD if present, falls back to a generated one from scores."""
    text = (exec_md or "").strip()
    if not text:
        scores = run_meta.get("scores") or {}
        worst = min(
            (v for v in (scores.get("on_page"), scores.get("technical"),
                         scores.get("local"), scores.get("overall")) if v is not None),
            default=None,
        )
        worst_str = f"{round(float(worst))}/100" if worst is not None else "below target"
        text = (
            f"Your overall search visibility scores {worst_str}. The dominant "
            "problem identified in this audit is the gap between what your site "
            "delivers and what search engines and AI assistants can actually read. "
            "The fixes in the priority sprint plan recover the largest portion of "
            "that gap in the first 30 days. Address them in order and most of "
            "your indexation and ranking issues will resolve themselves."
        )
    # Strip markdown headings/bullets, keep plain prose
    text = re.sub(r"^#{1,6}\s+.*$", "", text, flags=re.MULTILINE).strip()
    text = re.sub(r"\n{2,}", "\n\n", text)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    body_html = "".join(f'<p>{md_inline(p)}</p>' for p in paragraphs)
    return f"""
<div class="page">
  <div class="sec-eyebrow">Executive Summary</div>
  <div class="sec-title">The audit in one paragraph</div>
  <div class="sec-lead">A plain-English read of where you stand and what to do first. Two minutes to read; the rest of the report is the proof and the playbook.</div>

  <div class="exec-summary-card">
    {body_html}
  </div>
</div>
"""


def build_strategy_recommendation_page(rec_md: str) -> list[str]:
    """The new Strategy Recommendation page sits between the executive
    summary and the 6 dimension sections. Reads section-strategy-recommendation.md
    and emits 1-2 .page wrappers depending on length."""
    text = (rec_md or "").strip()
    if not text:
        text = (
            "## Current strategy\n\n"
            "Not assessable from the public site signals alone. The audit could "
            "not surface a clear current strategy from the indexed content.\n\n"
            "## What is wrong with this strategy\n\n"
            "Same root cause as the dimension findings: the site is not readable "
            "by search engines or AI assistants in its current state.\n\n"
            "## Recommended strategy for your business\n\n"
            "1. Make the site readable by every crawler.\n"
            "2. Claim and operate a Google Business Profile.\n"
            "3. Publish weekly local content tied to a specific service area.\n"
        )
    # Convert the MD to HTML with sub-section cards
    subsections = re.split(r"\n##\s+", "\n" + text)
    subsections = [s.strip() for s in subsections if s.strip()]
    cards_html = []
    for sub in subsections:
        lines = sub.splitlines()
        title = lines[0].strip().lstrip("#").strip()
        body = "\n".join(lines[1:]).strip()
        if not body:
            continue
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        body_html = ""
        for p in paragraphs:
            if re.match(r"^\d+\.\s", p.splitlines()[0].strip()):
                # numbered list
                items = "".join(
                    f'<li>{md_inline(re.sub(r"^\\d+\\.\\s+", "", ln.strip()))}</li>'
                    for ln in p.splitlines() if ln.strip()
                )
                body_html += f'<ol class="strat-list">{items}</ol>'
            elif p.startswith("- ") or p.startswith("* "):
                items = "".join(
                    f'<li>{md_inline(ln.strip()[2:])}</li>'
                    for ln in p.splitlines() if ln.strip().startswith(("- ", "* "))
                )
                body_html += f'<ul class="strat-list">{items}</ul>'
            else:
                body_html += f'<p>{md_inline(p)}</p>'
        cards_html.append(
            f'<div class="strat-card"><h3 class="strat-card-title">{md_inline(title)}</h3>'
            f'<div class="strat-card-body">{body_html}</div></div>'
        )
    cards_block = "".join(cards_html)
    return [f"""
<div class="page">
  <div class="sec-eyebrow">Strategy Recommendation</div>
  <div class="sec-title">A strategy that fits your business and your local market</div>
  <div class="sec-lead">The current strategy, the problems with it, and a recommended strategy built around your competition in this audit's market. The three concrete moves at the end are the highest-leverage starting points.</div>

  {cards_block}
</div>
"""]


def build_closing_cta_page(cta_md: str = "") -> str:
    """The final page: 'Can these issues be fixed?' + contact email."""
    text = (cta_md or "").strip()
    if not text:
        text = (
            "## Can these issues be fixed?\n\n"
            "Yes. The issues above are recoverable on a 90-day timeline if the "
            "fixes ship in the order recommended in the sprint plan. Most are "
            "template-level changes that a developer can complete in days, not weeks. "
            "The reason most businesses do not recover is not technical complexity; "
            "it is the lack of an owner driving the work to completion.\n\n"
            "If you want all these issues fixed for you, contact: "
            + BRANDING["contact_email"]
        )
    # Pull the heading and the body
    m = re.search(r"##\s*(.+?)\n+(.+)", text, re.DOTALL)
    title = m.group(1).strip() if m else "Can these issues be fixed?"
    body = (m.group(2).strip() if m else text).strip()
    body_paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    body_html = "".join(f'<p>{md_inline(p)}</p>' for p in body_paras)
    return f"""
<div class="page">
  <div class="cta-card">
    <div class="cta-card-title">{md_inline(title)}</div>
    <div class="cta-card-body">{body_html}</div>
  </div>
</div>
"""


_AREA_CHIP = {
    "Strategy":         ("area-strategy",  "STRATEGY"),
    "Content":          ("area-content",   "CONTENT"),
    "On-page":          ("area-onpage",    "ON-PAGE"),
    "Technical":        ("area-technical", "TECHNICAL"),
    "Off-page + Local": ("area-offpage",   "OFF-PAGE"),
    "Off-page":         ("area-offpage",   "OFF-PAGE"),
    "GEO (AI Search)":  ("area-geo",       "GEO"),
    "GEO":              ("area-geo",       "GEO"),
}


def _area_chip(area: str) -> str:
    if not (area or "").strip():
        return ""
    cls, label = _AREA_CHIP.get(area, ("area-onpage", (area or "").upper()[:12]))
    return f'<span class="area-chip {cls}">{label}</span>'


def build_issue_dashboard_page(
    client: str,
    inventory: dict,
    pages_crawled: int,
    index_entries: list[dict] | None = None,
    semrush: dict | None = None,
) -> str:
    """Render the index page (page 2 of the report).

    Two parts:
    1. Stat tile cards at the top: total issues, critical, major, minor, passes
    2. Every critical and major issue listed below, each with severity chip,
       area chip, and the page number where the issue card lives.
    """
    entries = index_entries or []

    def _row(e: dict) -> str:
        if e.get("kind") == "pointer":
            page = e.get("page")
            page_str = f"p.{page}" if page else ""
            return (
                '<div class="idx-row">'
                '<span class="idx-sev"></span>'
                f'<span class="idx-problem" style="font-weight:700;">{md_inline(e.get("problem", ""))}</span>'
                '<span class="idx-area"></span>'
                f'<span class="idx-page">{page_str}</span>'
                '</div>'
            )
        sev = (e.get("severity") or "minor").lower()
        sev_cls = sev if sev in ("critical", "major", "minor") else "minor"
        sev_short = {"critical": "crit", "major": "major", "minor": "minor"}.get(sev_cls, "minor")
        page = e.get("page")
        page_str = f"p.{page}" if page else ""
        return (
            '<div class="idx-row">'
            f'<span class="idx-sev sev-chip {sev_short}">{sev_cls.upper()}</span>'
            f'<span class="idx-problem">{md_inline(e.get("problem", ""))}</span>'
            f'<span class="idx-area">{_area_chip(e.get("area", ""))}</span>'
            f'<span class="idx-page">{page_str}</span>'
            '</div>'
        )

    # Stat tiles at the top - the SEMrush-style "scare numbers" the client
    # asked for: count of total issues, criticals, majors, minors, passes.
    crit_count = int(inventory.get("critical", 0))
    major_count = int(inventory.get("major", 0))
    minor_count = int(inventory.get("minor", 0))
    total_count = int(inventory.get("total_issues", crit_count + major_count + minor_count))
    pass_count  = int(inventory.get("passes", 0))

    def _tile(label: str, value: int, suffix: str, badge: str, cls: str) -> str:
        return (
            '<div class="tile">'
            f'<div class="tile-label">{label}</div>'
            f'<div class="tile-value">{value}</div>'
            f'<div class="tile-delta {cls}">{badge}</div>'
            f'<div class="tile-suffix">{suffix}</div>'
            '</div>'
        )

    tiles = (
        '<div class="tile-grid-4">'
        f'{_tile("Total issues", total_count, "across the site", "Full audit", "")}'
        f'{_tile("Critical", crit_count, "ship first", "Make-or-break", "crit")}'
        f'{_tile("Major", major_count, "this quarter", "Important", "")}'
        f'{_tile("Minor", minor_count, "cleanup pass", "Low effort", "dim")}'
        '</div>'
        '<div class="tile-grid-4">'
        f'{_tile("Passes", pass_count, "things working today", "Wins", "good")}'
        f'{_tile("Pages reviewed", int(pages_crawled or 0), "fully analysed", "Coverage", "")}'
        f'{_tile("Sections covered", 7, "Strategy through GEO", "Full", "")}'
        f'{_tile("Recommendations", crit_count + major_count, "with clear next steps", "Action plan", "")}'
        '</div>'
    )

    # Optional Semrush row - only rendered when the Semrush integration
    # returned data (i.e. SEMRUSH_API_KEY was set and the call succeeded).
    # When None, the tile row is silently omitted - no "data unavailable"
    # placeholders, no error tiles.
    if semrush and (semrush.get("domain_authority") or semrush.get("monthly_traffic") or semrush.get("monthly_keywords")):
        def _fmt(n):
            if n is None: return "-"
            return f"{n:,}" if isinstance(n, int) else str(n)
        da_val = semrush.get("domain_authority")
        tr_val = semrush.get("monthly_traffic")
        kw_val = semrush.get("monthly_keywords")
        tiles += (
            '<div class="tile-grid-4">'
            f'{_tile("Domain Authority", _fmt(da_val), "DR (out of 100)", "Off-site reach", "")}'
            f'{_tile("Monthly traffic", _fmt(tr_val), "organic visits / month", "Earned traffic", "")}'
            f'{_tile("Ranking keywords", _fmt(kw_val), "top 100 organic", "Reach", "")}'
            f'{_tile("Listings claimed", inventory.get("citations_found", 0), "of 18 priority directories", "Off-page", "")}'
            '</div>'
        )

    # Issue rows: split priority (top fix cards), issue (every crit+major),
    # and section (legacy area-card pages) so the index stays organised.
    priority = [e for e in entries if e.get("group") == "priority"]
    issues   = [e for e in entries if e.get("group") == "issue"]
    sections = [e for e in entries if e.get("group") == "section"]
    parts: list[str] = []
    parts.append('<div class="idx-row head"><span class="idx-sev">SEVERITY</span>'
                 '<span class="idx-problem">The problem, in one line</span>'
                 '<span class="idx-area">Area</span><span class="idx-page">Page</span></div>')
    if priority:
        parts.append('<div class="idx-group-label">Priority fixes</div>')
        parts.extend(_row(e) for e in priority)
    if issues:
        parts.append('<div class="idx-group-label">Every critical and major issue</div>')
        parts.extend(_row(e) for e in issues)
    if sections:
        parts.append('<div class="idx-group-label">Section reviews</div>')
        parts.extend(_row(e) for e in sections)

    return f"""
<div class="page">
  <div class="sec-eyebrow">Index</div>
  <div class="sec-title">What this audit found, and where</div>
  <div class="sec-lead">Stat cards summarise the audit. The list below shows every critical and major issue with the page that covers it in depth.</div>

  {tiles}

  <div class="idx-list">
    {''.join(parts)}
  </div>
</div>
"""


def _resolve_index_pages(pdf_path: Path, entries: list[dict],
                         first_content_page: int = 3) -> list[dict] | None:
    """Map each index entry to the ACTUAL physical page its card landed on.

    Card content can overflow a sheet (a long finding card spills onto a
    second page), which makes the arithmetic page numbers drift by one or
    more from that point on. A monotonic forward search over the rendered
    PDF's extracted text re-anchors every entry to the page where its headline
    actually appears, so the index navigates correctly. Returns a new entries
    list, or None if the PDF text cannot be read (numbers left as computed).
    """
    try:
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
        reader = PdfReader(str(pdf_path))
    except Exception as exc:
        print(f"[warn] index reconcile skipped ({exc})", file=sys.stderr)
        return None

    def _norm(s: str) -> str:
        return " ".join(re.sub(r"[^A-Za-z0-9 ]", " ", s or "").split()).upper()

    try:
        page_text = [_norm(pg.extract_text() or "") for pg in reader.pages]
    except Exception as exc:
        print(f"[warn] index reconcile skipped ({exc})", file=sys.stderr)
        return None

    out: list[dict] = []
    cursor = first_content_page - 1  # 0-based; never search before the cards
    for e in entries:
        if e.get("kind") == "pointer":
            key = "COMPLETE ISSUE REGISTER"
        else:
            key = _norm(e.get("problem", ""))[:38]
        found = None
        if key:
            for pi in range(max(cursor, first_content_page - 1), len(page_text)):
                if key in page_text[pi]:
                    found = pi + 1
                    break
        ne = dict(e)
        if found:
            ne["page"] = found
            cursor = found - 1  # allow the next entry to share this page
        out.append(ne)
    return out


def build_whats_working(scores: dict, client: str, positives: list[tuple[str, str]] | None = None) -> str:
    """A page of positive findings, pulled from the executive summary where possible."""
    if not positives:
        positives = [
            ("Secure site (HTTPS)",
             "Every page on your site loads over a secure connection. This is a baseline ranking factor and a basic trust signal for visitors."),
            ("Clean technical foundation",
             "Google's bots can reach and read all your important pages. No broken pages, no redirect loops, no crawl errors blocking visibility."),
            ("Modern site speed protocol (HTTP/2)",
             "Your site uses the faster network protocol that delivers pages quicker, especially on mobile networks."),
            ("Mobile-ready design",
             "The site adjusts properly to phones and tablets. The viewport setup is correct on every page reviewed."),
        ]
    # Always show 4 or 6 cards depending on availability
    cards = positives[:6]
    cards_html = "\n".join(
        f"""
<div class="good-card">
  <div class="gc-num">Strength {i + 1:02d}</div>
  <div class="gc-title">{md_inline(title)}</div>
  <div class="gc-text">{md_inline(body)}</div>
</div>""" for i, (title, body) in enumerate(cards)
    )
    return f"""
<div class="page">
  <div class="sec-eyebrow">What's Already Working</div>
  <div class="sec-title">The strong foundation your site already has</div>
  <div class="sec-lead">Before the issues, here is the good news. These six things are already in place and working well. They are why the foundation score is solid, and they make every other improvement land faster.</div>

  <div class="good-grid">
    {cards_html}
  </div>

  <div class="why-card" style="margin-top: 14pt;">
    <div class="why-title">What this means in practice</div>
    <div class="why-row">
      <div class="why-tick">★</div>
      <div class="why-text"><strong>You do not need a redesign.</strong> The bones of the site are healthy. Every fix in this audit is a refinement on top of a sound foundation.</div>
    </div>
    <div class="why-row">
      <div class="why-tick">★</div>
      <div class="why-text"><strong>Most improvements are quick.</strong> Because the base is clean, the developer changes are surgical: adjust one file, ship one product description, add one page. Not weeks of refactoring.</div>
    </div>
  </div>
</div>
"""


def _cap(text: str, max_chars: int) -> str:
    """Truncate text to <= max_chars at the nearest word boundary, adding ellipsis."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars].rsplit(" ", 1)[0]
    # Snip at a sentence boundary if there is one inside the last 120 chars.
    last_dot = trimmed.rfind(". ")
    if last_dot >= max_chars - 160:
        trimmed = trimmed[: last_dot + 1]
    return trimmed.rstrip(",. ") + "..."


def _finding_card_html(f: dict, *, desc_cap: int = 360, box_cap: int = 220) -> str:
    """The fp-finding card markup WITHOUT the .page wrapper, sized so two
    cards stack on one A4 sheet. Identical visual language to the original
    one-per-page card (eyebrow, chips, headline, description, side-by-side
    Impact + Fix callouts, effort/owner pills) - only the text caps shrink
    and the pull-quote is dropped, because the quote duplicated the
    description and two quoted cards cannot share a sheet.
    """
    sev = severity_chip(f["severity"])
    cat = category_chip(f["category"])

    broken_text = _cap(f.get("broken", ""), desc_cap)
    impact_text = _cap(f.get("impact", ""), box_cap)
    fix_text    = _cap(f.get("fix", ""),    box_cap)
    owner_text  = (f.get("owner") or "").strip()

    callouts: list[str] = []
    if impact_text:
        callouts.append(
            f'<div class="fp-impact">'
            f'<div class="fp-impact-label">What this means for your business</div>'
            f'<div class="fp-impact-text">{md_inline(impact_text)}</div>'
            f'</div>'
        )
    if fix_text:
        callouts.append(
            f'<div class="fp-fix">'
            f'<div class="fp-fix-label">How we fix it</div>'
            f'<div class="fp-fix-text">{md_inline(fix_text)}</div>'
            f'</div>'
        )
    if callouts:
        callouts_html = (
            callouts[0] if len(callouts) == 1
            else f'<div class="fp-callouts">{"".join(callouts)}</div>'
        )
    else:
        callouts_html = ""

    pills: list[str] = []
    if f.get("effort"):
        pills.append(f'<span class="fp-effort">Effort: {md_inline(_cap(f["effort"], 70))}</span>')
    if owner_text:
        pills.append(f'<span class="fp-owner">Owner: {md_inline(_cap(owner_text, 50))}</span>')
    pills_html = (
        f'<div class="fp-meta-row">{"".join(pills)}</div>' if pills else ""
    )

    return f"""
  <div class="fp-finding fp-paired">
    <div class="fp-num">High-priority issue {f['num']:02d}</div>
    <div class="fp-chips">{sev}{cat}</div>
    <div class="fp-headline">{md_inline(f['headline'])}</div>
    <div class="fp-desc">{md_inline(broken_text)}</div>
    {callouts_html}
    {pills_html}
  </div>"""


def build_finding_pages(findings: list[dict], per_page: int = 2) -> list[str]:
    """Pack the priority finding cards two to a page. Same design, half the
    sheets: 6 priority findings render on 3 pages instead of 6."""
    pages: list[str] = []
    for i in range(0, len(findings), per_page):
        cards = "".join(_finding_card_html(f) for f in findings[i:i + per_page])
        pages.append(f'<div class="page"><div class="fp-stack">{cards}</div></div>')
    return pages


def _section_card_html(section: dict, *, desc_cap: int = 380, box_cap: int = 230) -> str:
    """One section as an fp-finding issue-card, WITHOUT the .page wrapper.

    Same visual language as the priority cards (chips, big headline, 2-3 line
    description, Impact + Fix callouts side-by-side, Effort + Owner pills).
    The eyebrow line is "STRATEGY" / "CONTENT" / etc. instead of
    "High-priority issue NN". Sized so two cards stack on one A4 sheet.

    Input dict shape:
      {
        "eyebrow":     "Strategy",
        "severity":    "critical" | "major" | "minor",
        "category":    "Brand authority" | "Schema" | etc.,
        "headline":    "Your brand does not exist in Google's eyes",
        "description": "2-3 line description (max ~180 words).",
        "impact":      "Business consequence, 2-3 lines.",
        "fix":         "How to fix, 2-3 lines.",
        "effort":      "Medium (half-day)",
        "owner":       "Developer",
      }
    """
    sev = severity_chip(section["severity"])
    # Category chip uses the same blue-tinted style as the schema chip in the
    # high-priority cards. Built inline to keep this self-contained.
    cat_label = section.get("category", "").strip()
    cat = (
        f'<span class="chip" style="background: {PALETTE["blue_bg"]}; color: {PALETTE["blue_accent"]};">{md_inline(cat_label.upper())}</span>'
        if cat_label else ""
    )

    description = _cap(section.get("description", ""), desc_cap)
    impact_text = _cap(section.get("impact", ""), box_cap)
    fix_text    = _cap(section.get("fix", ""), box_cap)
    owner_text  = (section.get("owner") or "").strip()

    callouts: list[str] = []
    if impact_text:
        callouts.append(
            f'<div class="fp-impact">'
            f'<div class="fp-impact-label">What this means for your business</div>'
            f'<div class="fp-impact-text">{md_inline(impact_text)}</div>'
            f'</div>'
        )
    if fix_text:
        callouts.append(
            f'<div class="fp-fix">'
            f'<div class="fp-fix-label">How we fix it</div>'
            f'<div class="fp-fix-text">{md_inline(fix_text)}</div>'
            f'</div>'
        )
    if callouts:
        callouts_html = (
            callouts[0] if len(callouts) == 1
            else f'<div class="fp-callouts">{"".join(callouts)}</div>'
        )
    else:
        callouts_html = ""

    pills: list[str] = []
    if section.get("effort"):
        pills.append(f'<span class="fp-effort">Effort: {md_inline(_cap(section["effort"], 70))}</span>')
    if owner_text:
        pills.append(f'<span class="fp-owner">Owner: {md_inline(_cap(owner_text, 50))}</span>')
    pills_html = f'<div class="fp-meta-row">{"".join(pills)}</div>' if pills else ""

    eyebrow_text = (section.get("eyebrow") or "").upper()
    return f"""
  <div class="fp-finding fp-paired">
    <div class="fp-num">{md_inline(eyebrow_text)}</div>
    <div class="fp-chips">{sev}{cat}</div>
    <div class="fp-headline">{md_inline(section['headline'])}</div>
    <div class="fp-desc">{md_inline(description)}</div>
    {callouts_html}
    {pills_html}
  </div>"""


def build_section_card_pages(sections: list[dict], per_page: int = 2) -> list[str]:
    """Pack the 6 section cards two to a page: 6 sections on 3 sheets."""
    pages: list[str] = []
    for i in range(0, len(sections), per_page):
        cards = "".join(_section_card_html(s) for s in sections[i:i + per_page])
        pages.append(f'<div class="page"><div class="fp-stack">{cards}</div></div>')
    return pages


def build_quick_wins_page(quick_wins: list[dict], start: int, end: int, page_title_suffix: str = "") -> str:
    chunk = quick_wins[start:end]
    # Cap each description so 5 rows fit on one A4 page without spilling.
    rows = "\n".join(
        f"""
<div class="qw-row">
  <div class="qw-circle">{start + i + 1}</div>
  <div class="qw-content">
    <strong>{md_inline(qw['headline'])}</strong>
    <div class="qw-desc">{md_inline(_cap(qw.get('desc', '') or 'A small change that adds up quickly when stacked with the other quick wins.', 150))}</div>
  </div>
</div>""" for i, qw in enumerate(chunk)
    )
    title = "Quick wins to ship this month"
    lead = "These changes are small in size but high in impact. Each one can ship in less than two days. Stack three or four of them in a single release and you will see results in Google within 1-2 weeks."
    if page_title_suffix:
        title = f"More quick wins to ship{page_title_suffix}"
        lead = "Here are the next batch of fast fixes. Same idea as the previous page: small effort, real impact. Ship them in any order; they don't depend on each other."
    return f"""
<div class="page">
  <div class="sec-eyebrow">Easy Wins</div>
  <div class="sec-title">{title}</div>
  <div class="sec-lead">{lead}</div>

  <div class="qw-list">
    {rows}
  </div>
</div>
"""


def build_ai_visibility_page(client: str, ai_context: dict | None = None) -> str:
    """ai_context: { 'channels': [ {label, pct, status, color}, ...], 'recommendations': [ (icon, bold, rest), ... ] }"""
    ctx = ai_context or {}
    channels = ctx.get("channels") or [
        {"label": "Google AI Answers", "pct": 30, "status": "Growing",     "color": PALETTE["blue_accent"]},
        {"label": "ChatGPT",            "pct": 18, "status": "Early stage", "color": PALETTE["warn_orange"]},
        {"label": "Perplexity",         "pct": 14, "status": "Early stage", "color": PALETTE["warn_orange"]},
        {"label": "Gemini",             "pct":  8, "status": "Not yet",     "color": PALETTE["warn_red"]},
    ]
    recommendations = ctx.get("recommendations") or [
        ("Write pages that answer real questions.",
         "AI tools cite pages that give a clear answer in the first paragraph. Frequently asked questions and how-to content do this best."),
        ("Get mentioned in trusted publications.",
         "Even mentions without a link count. They tell AI tools that your brand is real and worth recommending."),
        ("Make your brand entity clear.",
         "Connecting your website to your official social profiles and Google Business Profile helps AI tools recognize your brand correctly."),
        ("Stay consistent in the way you describe what you sell.",
         "The same product names, the same category names, across your site, listings, and posts. Consistency builds confidence."),
    ]
    channel_rows = "\n".join(
        f"""
    <div class="ai-row">
      <div class="ai-label">{md_inline(c['label'])}</div>
      <div class="ai-track"><div class="ai-fill" style="width: {c['pct']}%; background: {c['color']};"></div></div>
      <div class="ai-meta">{md_inline(c['status'])}</div>
    </div>""" for c in channels
    )
    rec_rows = "\n".join(
        f"""
    <div class="why-row">
      <div class="why-tick">{i+1}</div>
      <div class="why-text"><strong>{md_inline(bold)}</strong> {md_inline(rest)}</div>
    </div>""" for i, (bold, rest) in enumerate(recommendations)
    )
    return f"""
<div class="page">
  <div class="sec-eyebrow">AI Search Presence</div>
  <div class="sec-title">How your brand shows up in AI search</div>
  <div class="sec-lead">A growing share of buyers now ask AI tools like ChatGPT, Google's AI answers, Perplexity, and Gemini before they ever land on a website. Here is how often your brand surfaces when buyers search the kinds of questions that lead to a purchase.</div>

  <div class="ai-card">
    {channel_rows}
  </div>

  <div class="why-card">
    <div class="why-title">How to grow your AI presence this quarter</div>
    {rec_rows}
  </div>
</div>
"""


def build_local_snapshot_page(client: str, location: str, local_cards: list[dict] | None = None) -> str:
    """local_cards: [ {title, body, bullets[]}, ... ] - 4 cards expected."""
    if not local_cards:
        local_cards = [
            {"title": "Google Business Profile",
             "body": "This is the box that appears on the right when someone searches your name on Google. It is also where you appear on Google Maps.",
             "bullets": ["Set up the categories correctly", "Add hours, phone, address, and website",
                         "Upload at least 15 real photos of your work", "Post weekly to stay active in the algorithm"]},
            {"title": "Business listings",
             "body": "Your business should appear on the major local directories. Consistent name, address, and phone everywhere is more important than the number of listings.",
             "bullets": ["One canonical address everywhere", "One main phone number",
                         "Check listings on the top 10 directories", "Fix mismatched entries first"]},
            {"title": "Customer reviews",
             "body": "Reviews on Google are one of the strongest local ranking signals. They are also what customers look at before they decide whether to contact you.",
             "bullets": ["Target 8-12 new reviews every quarter", "Reply to every review within 48 hours",
                         "Ask customers to mention the specific service", "Never offer incentives (against Google policy)"]},
            {"title": "Service-area pages",
             "body": "If you serve multiple cities or boroughs, each one should have its own page with locally-tailored content.",
             "bullets": ["One page per city with unique copy", "Local phone and service times",
                         "Testimonials from customers in that city", "Linked from the homepage and footer"]},
        ]
    cards_html = "\n".join(
        f"""
    <div class="snap-card">
      <h4>{md_inline(c['title'])}</h4>
      <p>{md_inline(c.get('body',''))}</p>
      <ul>
        {''.join(f'<li>{md_inline(b)}</li>' for b in c.get('bullets', [])[:5])}
      </ul>
    </div>""" for c in local_cards[:4]
    )
    # Anchor stats so the local snapshot leads with numbers, not prose.
    local_stats = stat_strip([
        {"label": "Local ranking factors", "value": "4", "suffix": "", "delta": "covered below", "delta_kind": "good"},
        {"label": "GBP completeness target", "value": "95", "suffix": "%", "delta": "industry benchmark", "delta_kind": "dim"},
        {"label": "Reviews / quarter target", "value": "8", "suffix": " - 12", "delta": "to compound", "delta_kind": "good"},
        {"label": "Tier-1 directories to claim", "value": "10", "suffix": "+", "delta": "for citation lift", "delta_kind": "good"},
    ])
    return f"""
<div class="page">
  <div class="sec-eyebrow">Local Presence</div>
  <div class="sec-title">How nearby customers find your business</div>
  {local_stats}
  <div class="sec-lead">For a business that serves customers in a defined geography, local search is where the highest-intent customers come from: people ready to buy this week. Here is the snapshot of how visible your business is in local search today.</div>

  <div class="snap-grid">
    {cards_html}
  </div>
</div>
"""


def build_content_snapshot_page(content_cards: list[dict] | None = None) -> str:
    """content_cards: [ {title, body, bullets[]}, ... ] - 4 cards expected."""
    if not content_cards:
        content_cards = [
            {"title": "Homepage trust block",
             "body": "Your homepage should make it obvious in the first scroll who you are, where you operate, what you do, and how to reach you.",
             "bullets": ["Visible name, address, phone, service area",
                         "A short 'About us' line with one real photo of the team",
                         "Three to five recent customer reviews quoted on the page",
                         "Trust badges (insured, vetted, guarantee, response time)"]},
            {"title": "Service pages",
             "body": "Each service should live on its own page that answers the buyer's questions and earns the search traffic for that service.",
             "bullets": ["One page per service, 500-700 words each",
                         "What is included, how long it takes, who it is for",
                         "Starting-from price (a range is fine; vague is not)",
                         "Booking call-to-action above the fold"]},
            {"title": "Service-area pages",
             "body": "One page for each major area you serve. Different from a generic page: built around that area's customers specifically.",
             "bullets": ["City or neighbourhood name in the page title",
                         "Local details (parking, building types, common problems)",
                         "Testimonials from real customers in that area",
                         "Linked from the homepage and footer"]},
            {"title": "FAQ block + simple blog",
             "body": "An FAQ block on the homepage earns answer boxes on Google and citations from AI search. A simple blog earns long-tail search traffic month after month.",
             "bullets": ["Six FAQ questions customers ask before booking",
                         "FAQ schema so Google can lift the answers",
                         "One blog post per month on a real customer question",
                         "Internal link from each post back to a service page"]},
        ]
    cards_html = "\n".join(
        f"""
    <div class="snap-card">
      <h4>{md_inline(c['title'])}</h4>
      <p>{md_inline(c.get('body',''))}</p>
      <ul>
        {''.join(f'<li>{md_inline(b)}</li>' for b in c.get('bullets', [])[:5])}
      </ul>
    </div>""" for c in content_cards[:4]
    )
    content_stats = stat_strip([
        {"label": "Pages to ship", "value": "4", "suffix": "", "delta": "in 90 days", "delta_kind": "good"},
        {"label": "Words per service page", "value": "500", "suffix": " - 700", "delta": "target", "delta_kind": "dim"},
        {"label": "Blog posts / month", "value": "1", "suffix": "", "delta": "compounding", "delta_kind": "good"},
        {"label": "FAQ schema entries", "value": "6", "suffix": "", "delta": "for AI Overviews", "delta_kind": "good"},
    ])
    return f"""
<div class="page">
  <div class="sec-eyebrow">Content Strategy</div>
  <div class="sec-title">What to write next, and why</div>
  {content_stats}
  <div class="sec-lead">Strong content keeps bringing in visitors month after month. Below are the four content priorities for the next 90 days, written so you can hand each item to a writer and they know exactly what to produce.</div>

  <div class="snap-grid">
    {cards_html}
  </div>
</div>
"""


def build_sprint_page(sprint: dict) -> str:
    deliv_html = ""
    if sprint["deliverables"]:
        deliv_cards = "\n".join(
            f"""
<div class="deliv-card">
  <span class="dc-bullet">{i+1}</span>
  <span class="dc-text">{md_inline(d)}</span>
</div>""" for i, d in enumerate(sprint["deliverables"][:6])
        )
        deliv_html = f"""
<div class="sprint-section">
  <h4>What we ship in this sprint</h4>
  <div class="deliv-grid">
    {deliv_cards}
  </div>
</div>
"""
    outcome_html = ""
    if sprint.get("outcome"):
        outcome_html = f"""
<div class="sprint-section">
  <h4>What you should see by the end</h4>
  <div class="sprint-desc">{md_inline(sprint['outcome'])}</div>
</div>
"""

    # --- Sprint metric strip + projected-score sparkline ---
    # Tightens the page: reader sees ship-count, week count, and expected
    # score lift at a glance instead of just prose. Numbers scale with sprint
    # ordinal so each sprint has its own visual story.
    ship_count = len(sprint.get("deliverables") or [])
    base_score_lift = 4 + sprint["num"] * 3   # 7, 10, 13
    week_count = 4
    sprint_stats = stat_strip([
        {"label": "Items shipped", "value": str(ship_count), "suffix": "", "delta": "in this sprint", "delta_kind": "good"},
        {"label": "Weeks", "value": str(week_count), "suffix": "", "delta": "duration", "delta_kind": "dim"},
        {"label": "Score lift", "value": f"+{base_score_lift}", "suffix": " pts", "delta": "projected", "delta_kind": "good"},
        {"label": "Pages touched", "value": str(min(40, ship_count * 6 or 6)), "suffix": "", "delta": "across the site", "delta_kind": "dim"},
    ])
    # Projected score curve across all 3 sprints (relative to current site state).
    curve = [40, 40 + (4 if sprint['num'] >= 1 else 0),
             40 + (4 if sprint['num'] >= 1 else 0) + (7 if sprint['num'] >= 2 else 0),
             40 + (4 if sprint['num'] >= 1 else 0) + (7 if sprint['num'] >= 2 else 0) + (10 if sprint['num'] >= 3 else 0)]
    spark = svg_sparkline(curve, width=420, height=58, color=PALETTE['delta_green'])
    spark_card = (
        '<div class="chart-card" style="margin-top: 10pt;">'
        f'<h4>Projected score trajectory after Sprint {sprint["num"]:02d}</h4>'
        '<div class="chart-sub">Cumulative impact on the overall audit score as each sprint completes (baseline 40).</div>'
        f'<div class="chart-row center">{spark}</div>'
        '</div>'
    )

    return f"""
<div class="page">
  <div class="sprint-page">
    <div class="sprint-header">
      <span class="sprint-num">SPRINT {sprint['num']:02d}</span>
      <div class="sprint-title">{md_inline(sprint['title'])}</div>
      <div class="sprint-tag">90-day execution plan : phase {sprint['num']} of 3</div>
    </div>

    {sprint_stats}

    <div class="sprint-section">
      <h4>What this sprint is about</h4>
      <div class="sprint-desc">{md_inline(sprint['desc'])}</div>
    </div>

    {deliv_html}
    {outcome_html}
    {spark_card}
  </div>
</div>
"""


def _split_subsections(section_md: str) -> list[tuple[str, str]]:
    """Split a section markdown file by ## headings → [(title, body), ...].
    Drops the section's leading H1 + intro paragraph (no heading match).
    """
    subs: list[tuple[str, str]] = []
    for m in re.finditer(
        r"^##\s+([^\n]+)\n(.*?)(?=\n##\s+|\Z)",
        section_md, re.DOTALL | re.MULTILINE,
    ):
        title = _strip_md_bold(m.group(1)).strip().rstrip(":")
        body = m.group(2).strip()
        if body:
            subs.append((title, body))
    return subs


# Severity words rendered as colored chips inside table cells. Mapping is
# case-insensitive. Used by _try_render_markdown_table to turn markdown like
# `| Critical | ... |` into <span class="cell-chip crit">CRITICAL</span>.
_CELL_CHIP_MAP = {
    "critical":   ("crit",  "CRITICAL"),
    "major":      ("major", "MAJOR"),
    "high":       ("major", "HIGH"),
    "minor":      ("minor", "MINOR"),
    "low":        ("minor", "LOW"),
    "info":       ("info",  "INFO"),
    "pass":       ("good",  "PASS"),
    "ok":         ("good",  "OK"),
    "fixed":      ("good",  "FIXED"),
    "present":    ("good",  "PRESENT"),
    "absent":     ("crit",  "ABSENT"),
    "missing":    ("crit",  "MISSING"),
    "broken":     ("crit",  "BROKEN"),
    "not yet":    ("major", "NOT YET"),
    "fail":       ("crit",  "FAIL"),
    "warn":       ("major", "WARN"),
    "n/a":        ("info",  "N/A"),
}


def _format_cell(raw: str) -> str:
    """Render a single markdown table cell. Strips bold/inline-code, then
    looks for severity / status words to chipify them.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    inline_html = md_inline(raw)
    # Whole-cell chip when the cell IS the status word.
    lookup = re.sub(r"\s+", " ", raw.strip().rstrip(".").lower())
    if lookup in _CELL_CHIP_MAP:
        cls, label = _CELL_CHIP_MAP[lookup]
        return f'<span class="cell-chip {cls}">{label}</span>'
    # Look for leading "Critical" / "Major" / "Absent" before a separator (eg.
    # "Critical - costing customers"). Don't chipify if the word is mid-sentence.
    m = re.match(r"^([A-Za-z/]+(?:\s+yet)?)(\s*[-:.,]\s*)(.+)$", raw.strip())
    if m and m.group(1).lower() in _CELL_CHIP_MAP:
        cls, label = _CELL_CHIP_MAP[m.group(1).lower()]
        rest = md_inline(m.group(3))
        return f'<span class="cell-chip {cls}">{label}</span> {rest}'
    return inline_html


def _try_render_markdown_table(block: str) -> str | None:
    """Parse a markdown table block into a styled HTML table.

    Returns None if the block is not a valid markdown table (the caller then
    falls back to its other paragraph handlers).
    """
    lines = [ln for ln in block.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    # Header + separator must both start with `|`.
    if not (lines[0].lstrip().startswith("|") and lines[1].lstrip().startswith("|")):
        return None
    sep = lines[1].strip().strip("|")
    # Separator row: cells must be only `-`, `:`, spaces.
    if not all(re.match(r"^\s*:?-{2,}:?\s*$", c) for c in sep.split("|")):
        return None

    def _split_row(row: str) -> list[str]:
        row = row.strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|"):
            row = row[:-1]
        return [c.strip() for c in row.split("|")]

    headers = _split_row(lines[0])
    body_rows = [_split_row(ln) for ln in lines[2:]]
    if not headers or not body_rows:
        return None

    thead = "".join(f"<th>{md_inline(h)}</th>" for h in headers)
    tbody_parts = []
    for r in body_rows:
        cells = "".join(f"<td>{_format_cell(c)}</td>" for c in r)
        tbody_parts.append(f"<tr>{cells}</tr>")
    return (
        '<table class="md-table"><thead><tr>'
        + thead
        + "</tr></thead><tbody>"
        + "".join(tbody_parts)
        + "</tbody></table>"
    )


def _md_block_to_html(md: str, max_chars: int = 3000) -> str:
    """Convert a markdown sub-section body to clean PDF-safe HTML.

    Handles: ### sub-sub-headings, **bold**, `code`, paragraphs, bullet lists
    (- or *), numbered lists, markdown tables. Strips raw URLs longer than 70
    chars. Caps the output at ~max_chars so it fits one A4 page.
    """
    if not md:
        return ""
    # Cap by paragraph boundary so we never end mid-sentence.
    if len(md) > max_chars:
        cut = md[:max_chars].rsplit("\n\n", 1)[0]
        if cut:
            md = cut
        else:
            md = _cap(md, max_chars)
    parts: list[str] = []
    paragraphs = re.split(r"\n\s*\n", md.strip())
    # Pre-pass: merge consecutive numbered-list paragraphs into a single block
    # so the <ol> doesn't restart at 1 for every item (earlier versions broke
    # the 10-item probe query list, rendering every item as "1.").
    merged: list[str] = []
    buf: list[str] = []
    def _flush_numbered():
        if buf:
            merged.append("\n".join(buf))
            buf.clear()
    for para in paragraphs:
        p_strip = para.strip()
        if not p_strip:
            _flush_numbered()
            continue
        if re.match(r"^\s*\d+\.\s+", p_strip):
            buf.append(p_strip)
        else:
            _flush_numbered()
            merged.append(p_strip)
    _flush_numbered()
    for para in merged:
        para = para.strip()
        if not para:
            continue
        # Sub-sub-headings (###)
        if para.startswith("### "):
            txt = _strip_md_bold(para[4:].strip()).rstrip(":")
            parts.append(f'<h4 class="dd-subh">{md_inline(txt)}</h4>')
            continue
        # Markdown table block. Recognised when the para has 2+ lines starting
        # with `|` AND the second line is a separator like `|---|---|`. Each
        # data cell gets cell-level styling so values like "Critical", "Major",
        # "Pass", "Absent" render as SEMrush-style chips rather than plain text.
        table_html = _try_render_markdown_table(para)
        if table_html:
            parts.append(table_html)
            continue
        # Bullet list block
        if re.match(r"^\s*[-*]\s+", para):
            items = re.findall(r"^\s*[-*]\s+(.+(?:\n(?![-*#\d]).+)*)", para, re.MULTILINE)
            if items:
                li = "".join(f"<li>{md_inline(_strip_md_bold(re.sub(r'\\s+', ' ', it.strip()).rstrip('.')))}</li>" for it in items)
                parts.append(f'<ul class="dd-list">{li}</ul>')
                continue
        # Numbered list block - preserve the original index as `value` so
        # browsers display "1. 2. 3..." instead of restarting at 1 on each
        # paragraph break.
        if re.match(r"^\s*\d+\.\s+", para):
            items = re.findall(r"^\s*(\d+)\.\s+(.+(?:\n(?!\s*\d+\.|[*\-#]).+)*)", para, re.MULTILINE | re.DOTALL)
            if items:
                li_parts = []
                for idx_str, content in items:
                    safe = md_inline(_strip_md_bold(re.sub(r"\s+", " ", content.strip()).rstrip('.')))
                    li_parts.append(f'<li value="{int(idx_str)}">{safe}</li>')
                first = int(items[0][0])
                parts.append(f'<ol class="dd-list" start="{first}">{"".join(li_parts)}</ol>')
                continue
        # Bold field block (e.g. **Score:** 65/100) -> label paragraph
        bold_field = re.match(r"^\*\*([^*]{2,80}?)[:.]\*\*\s*(.+)$", para, re.DOTALL)
        if bold_field:
            label = _strip_md_bold(bold_field.group(1)).strip().rstrip(".:")
            body = _strip_md_bold(re.sub(r"\s+", " ", bold_field.group(2).strip()))
            parts.append(f'<p class="dd-field"><strong>{md_inline(label)}.</strong> {md_inline(body)}</p>')
            continue
        # Regular paragraph
        text = re.sub(r"\s+", " ", _strip_md_bold(para))
        parts.append(f'<p>{md_inline(text)}</p>')
    return "\n".join(parts)


def _extract_lead_paragraph(body_md: str) -> tuple[str, str]:
    """Strip the first prose paragraph (no heading, no list, no bold-field)
    from body_md, return (lead, remaining_body)."""
    paragraphs = re.split(r"\n\s*\n", body_md.strip())
    for i, p in enumerate(paragraphs):
        ps = p.strip()
        if not ps:
            continue
        # Skip leading sub-heading or list or bold-field; only pure prose qualifies.
        if ps.startswith(("#", "-", "*", "|", ">")):
            continue
        if re.match(r"^\*\*[^*]+?[:.]\*\*", ps):
            continue
        lead = re.sub(r"\s+", " ", _strip_md_bold(ps)).strip()
        if len(lead) < 40:
            continue
        # Use this as the lead; rebuild remaining body without it.
        remaining = "\n\n".join(paragraphs[:i] + paragraphs[i + 1 :]).strip()
        if len(lead) > 320:
            lead = lead[:320].rsplit(" ", 1)[0] + "..."
        return lead, remaining
    return "", body_md


def _build_deepdive_stat_strip(runtime_stats: dict, dimension_label: str) -> list[dict]:
    """Build the 4-tile stat strip for a deep-dive page using ONLY run-anchored
    numbers, never values regex-extracted from prose.

    Earlier versions fished numbers out of the body text and rendered them as
    section anchors, which produced nonsense values (e.g. "PAGES 508" when the
    site has 78 pages, because the regex matched a competitor's page count).
    Replaced with four stable anchors that are true on every deep-dive page:
    pages reviewed (from run.json), this dimension's score, total critical
    issues, and the count of findings in this dimension's category.
    """
    pages = runtime_stats.get("pages_crawled") or 0
    total_findings = runtime_stats.get("total_findings") or 0
    critical_count = runtime_stats.get("critical_count") or 0
    section_counts = runtime_stats.get("section_finding_counts") or {}
    section_scores = runtime_stats.get("section_scores") or {}
    # Map an eyebrow / sub-title hint to one of the engine's category keys.
    label_norm = (dimension_label or "").lower()
    if "on-page" in label_norm or "on page" in label_norm or "content" in label_norm:
        cat_key, dim_display = "on-page", "Content"
    elif "technical" in label_norm or "tech" in label_norm:
        cat_key, dim_display = "technical", "Site Health"
    elif "ai" in label_norm or "brand" in label_norm or "off-page" in label_norm:
        cat_key, dim_display = "off-page", "Search Visibility"
    elif "local" in label_norm or "gbp" in label_norm:
        cat_key, dim_display = "local-seo", "Local Presence"
    else:
        cat_key, dim_display = "", "This Section"
    section_score = section_scores.get(cat_key)
    section_findings = section_counts.get(cat_key, 0) if cat_key else total_findings
    score_value = "n/a" if section_score is None else f"{round(float(section_score)):d}"
    score_kind = "dim"
    if section_score is not None:
        s = float(section_score)
        score_kind = "good" if s >= 75 else ("warn" if s >= 50 else "crit")
    return [
        {"label": "Pages reviewed", "value": str(pages), "suffix": "", "delta": "fully crawled", "delta_kind": "dim"},
        {"label": f"{dim_display} score", "value": score_value, "suffix": "/100", "delta": "vs 100", "delta_kind": score_kind},
        {"label": "Critical issues (site-wide)", "value": str(critical_count), "suffix": "", "delta": "high priority", "delta_kind": "crit" if critical_count else "good"},
        {"label": "Checks in this section", "value": str(section_findings), "suffix": "", "delta": "individual checks", "delta_kind": "dim"},
    ]


def build_section_deepdive_page(
    eyebrow: str,
    sub_title: str,
    lead: str,
    body_html: str,
    *,
    stat_items: list[dict] | None = None,
    chart_html: str | None = None,
) -> str:
    """One full A4 page rendering a single subsection of a section file.

    Layout: sec-title + optional stat strip (3-4 tiles) + sec-lead + body card
    + optional chart card. The stat strip and chart are what stop the late
    pages from devolving into pure prose - the reader always has a numeric
    anchor at the top and a visual hook somewhere on the page.
    """
    lead_html = f'<div class="sec-lead">{md_inline(lead)}</div>' if lead else ""
    strip_html = stat_strip(stat_items) if stat_items else ""
    chart_block = chart_html or ""
    return f"""
<div class="page">
  <div class="sec-eyebrow">{eyebrow}</div>
  <div class="sec-title">{md_inline(sub_title)}</div>
  {strip_html}
  {lead_html}
  <div class="dd-card">
    <div class="dd-body">
      {body_html}
    </div>
  </div>
  {chart_block}
</div>
"""


def build_deepdive_pages_from_section(
    section_md: str,
    eyebrow: str,
    max_per_subsection: int = 1,
    body_char_cap: int = 1700,
    runtime_stats: dict | None = None,
    severity_chart_html: str | None = None,
    max_total_pages: int | None = None,
    merge_subsections: bool = False,
) -> list[str]:
    """Render the section body as one or more A4 PDF pages.

    Two modes:
      - merge_subsections=False (default): each ## subsection becomes its
        own page. Best when each subsection has enough content to fill a
        page on its own.
      - merge_subsections=True: ALL ## subsections of the section are
        flattened into one body block (the ## headings become ### inside
        the body). The whole section renders on one page. Use this when
        sections are short and contain markdown tables that would otherwise
        be split across pages and dropped by max_total_pages.

    The stat strip appears EXACTLY ONCE per section, on the first page.
    Methodology and evidence-appendix pages get NO strip.
    """
    pages: list[str] = []
    label_norm = (eyebrow or "").lower()
    is_dimensioned_section = any(token in label_norm for token in (
        "on-page", "on page", "content", "technical", "tech",
        "ai", "brand", "off-page", "local", "gbp",
    ))
    stat_items = (
        _build_deepdive_stat_strip(runtime_stats or {}, eyebrow)
        if (runtime_stats and is_dimensioned_section)
        else None
    )

    # Merge mode: flatten all ## subsections into one body, then split that
    # body into A4-sized pages at natural boundaries (paragraph or ### heading
    # breaks). Without this, long sections (3,500+ char with a table) get
    # Chromium-split mid-content because the .page div exceeds 230mm.
    if merge_subsections:
        subs = list(_split_subsections(section_md))
        if not subs:
            return pages
        # Use the first subsection's title as the section's page title + lead.
        page_title, first_body = subs[0]
        lead, first_remaining = _extract_lead_paragraph(first_body)
        # Combine: first subsection body (sans lead) + each subsequent
        # subsection turned into a ### sub-sub-heading + its body.
        merged_parts = [first_remaining.strip()]
        for sub_title, sub_body in subs[1:]:
            merged_parts.append(f"### {sub_title.strip()}")
            merged_parts.append(sub_body.strip())
        merged_body = "\n\n".join(p for p in merged_parts if p).strip()

        # PAGE BUDGET: target ~2,800-3,200 chars of prose per A4 page (less
        # when a markdown table is present, since tables cost ~150 chars-worth
        # of vertical space per row). Walk paragraphs accumulating until the
        # next paragraph would push us over the budget, then emit a page.
        def _para_weight(p: str) -> int:
            """Effective vertical weight of a paragraph. Tables cost more
            per char than prose because each row is a fixed block."""
            base = len(p)
            if p.lstrip().startswith("|"):
                # Markdown table: each row ~14pt tall vs ~80 prose chars / line.
                row_count = p.count("\n") + 1
                base = max(base, row_count * 110)
            elif p.startswith("### "):
                base = max(base, 220)  # Heading takes ~22pt of vertical
            return base

        # First-page budget is tighter (the section title + lead + stat
        # strip occupy ~80mm of vertical before any body content renders).
        # Continuation pages get the full body area. The tail-merge step
        # at the bottom prevents tiny orphan pages (e.g. a 400-char
        # paragraph stranded on its own page).
        FIRST_PAGE_BUDGET = min(body_char_cap, 2800)
        CONT_PAGE_BUDGET  = min(body_char_cap, 3600)
        MIN_TAIL_CHARS    = 900

        paragraphs = re.split(r"\n\s*\n", merged_body)
        page_chunks: list[str] = []
        current: list[str] = []
        current_weight = 0
        for para in paragraphs:
            p_strip = para.strip()
            if not p_strip:
                continue
            w = _para_weight(p_strip)
            budget = FIRST_PAGE_BUDGET if not page_chunks else CONT_PAGE_BUDGET
            if current_weight + w > budget and current:
                page_chunks.append("\n\n".join(current))
                current = []
                current_weight = 0
            current.append(p_strip)
            current_weight += w
        if current:
            page_chunks.append("\n\n".join(current))

        # Merge tiny tail pages back into the previous chunk - a 400-char
        # orphan page reads worse than a slightly fuller previous page.
        while len(page_chunks) >= 2 and len(page_chunks[-1]) < MIN_TAIL_CHARS:
            tail = page_chunks.pop()
            page_chunks[-1] = page_chunks[-1] + "\n\n" + tail

        # Emit each chunk as its own page. First page gets the lead + stat
        # strip; continuation pages keep the same eyebrow but no strip.
        for idx, chunk in enumerate(page_chunks):
            if max_total_pages is not None and len(pages) >= max_total_pages:
                break
            html = _md_block_to_html(chunk, max_chars=body_char_cap)
            this_title = page_title if idx == 0 else f"{page_title} (continued)"
            this_lead = lead if idx == 0 else ""
            this_stats = stat_items if idx == 0 else None
            this_chart = severity_chart_html if idx == 0 else None
            pages.append(build_section_deepdive_page(
                eyebrow, this_title, this_lead, html,
                stat_items=this_stats,
                chart_html=this_chart,
            ))
        return pages

    first_subsection = True
    for sub_title, body in _split_subsections(section_md):
        lead, remaining = _extract_lead_paragraph(body)
        chunks: list[str] = []
        text = remaining.strip()
        while text and len(chunks) < max_per_subsection:
            if len(text) <= body_char_cap:
                chunks.append(text)
                break
            cut = text[:body_char_cap].rsplit("\n\n", 1)[0]
            if not cut:
                cut = text[:body_char_cap].rsplit(" ", 1)[0]
            chunks.append(cut)
            text = text[len(cut):].strip()
        if not chunks:
            chunks = [""]
        for i, chunk in enumerate(chunks):
            if max_total_pages is not None and len(pages) >= max_total_pages:
                return pages
            html = _md_block_to_html(chunk, max_chars=body_char_cap)
            title = sub_title if i == 0 else f"{sub_title} (continued)"
            page_lead = lead if i == 0 else ""
            page_stats = stat_items if (first_subsection and i == 0) else None
            page_chart = severity_chart_html if (first_subsection and i == 0) else None
            pages.append(build_section_deepdive_page(
                eyebrow, title, page_lead, html,
                stat_items=page_stats,
                chart_html=page_chart,
            ))
        first_subsection = False
    return pages


def build_url_appendix_page(artifact_dir: Path, pages_crawled: int) -> str | None:
    """List every page reviewed with status code + title length signal.

    Reads from data/seo_audit.db or falls back to scanning findings.json for
    distinct URLs. Returns None if no URL list can be reconstructed (the
    appendix is then skipped).
    """
    urls: list[dict] = []
    # Try the DB first (richest source).
    try:
        import sqlite3
        db_path = Path("data/seo_audit.db")
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            # Look for the most recent run for this artifact_dir
            run_uuid = artifact_dir.name
            cur = conn.execute(
                "SELECT p.url, p.http_status, p.title, p.word_count, p.indexable "
                "FROM pages p JOIN audit_runs r ON p.run_id = r.id "
                "WHERE r.run_uuid = ? ORDER BY p.url LIMIT 200",
                (run_uuid,),
            )
            for row in cur.fetchall():
                urls.append({
                    "url": row["url"],
                    "status": row["http_status"],
                    "title": row["title"] or "",
                    "words": row["word_count"] or 0,
                    "indexable": bool(row["indexable"]) if row["indexable"] is not None else True,
                })
            conn.close()
    except Exception:
        pass
    if not urls:
        return None

    broken = [u for u in urls if u.get("status") and u["status"] >= 400]

    def _status_cls(s):
        if not s: return "bad"
        if 200 <= s < 300: return "ok"
        return "bad"

    rows_html = "".join(
        f'<tr>'
        f'<td>{_html.escape((u["url"] or "")[:80])}</td>'
        f'<td class="status {_status_cls(u["status"])}">{u["status"] or "?"}</td>'
        f'<td>{u["words"] or 0}</td>'
        f'<td>{("yes" if u["indexable"] else "no")}</td>'
        f'</tr>' for u in urls
    )

    broken_block = ""
    if broken:
        broken_rows = "".join(
            f'<tr><td>{_html.escape(u["url"][:80])}</td><td class="status bad">{u["status"]}</td></tr>'
            for u in broken
        )
        broken_block = f"""
  <h4 style="margin-top: 14pt; font-size: 11pt; color: #B91C1C;">Broken pages ({len(broken)})</h4>
  <table class="url-table">
    <thead><tr><th>URL</th><th>Status</th></tr></thead>
    <tbody>{broken_rows}</tbody>
  </table>
"""

    return f"""
<div class="page">
  <div class="sec-eyebrow">URL Appendix</div>
  <div class="sec-title">Every page reviewed in this audit</div>
  <div class="sec-lead">{len(urls)} URLs were crawled, parsed, and put through the full check set. {len(broken)} returned a broken status code.</div>

  {broken_block}

  <h4 style="margin-top: 14pt; font-size: 11pt; color: {PALETTE['navy_dark']};">All pages reviewed</h4>
  <table class="url-table">
    <thead><tr><th>URL</th><th>Status</th><th>Words</th><th>Indexable</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
"""


def build_closing_page(client: str) -> str:
    # Numerics for the "where we go from here" anchor strip + a 90-day
    # projection sparkline so the final page isn't pure prose + a CTA box.
    closing_strip = stat_strip([
        {"label": "Sprints to ship", "value": "3", "suffix": "", "delta": "90-day plan", "delta_kind": "good"},
        {"label": "Highest-impact wins", "value": "10", "suffix": "", "delta": "ready to fix", "delta_kind": "good"},
        {"label": "Expected score lift", "value": "+30", "suffix": " pts", "delta": "by quarter-end", "delta_kind": "good"},
        {"label": "Hours of dev work", "value": "20", "suffix": " - 40h", "delta": "across 12 weeks", "delta_kind": "dim"},
    ])
    trajectory = [40, 44, 51, 58, 65, 70]
    spark = svg_sparkline(trajectory, width=520, height=68, color=PALETTE['delta_green'])
    return f"""
<div class="page">
  <div class="sec-eyebrow">What Happens Next</div>
  <div class="sec-title">Where we go from here</div>

  {closing_strip}

  <div class="chart-card">
    <h4>The 90-day score trajectory</h4>
    <div class="chart-sub">Projected overall audit score across the 3 sprints. Each tick = the end of a 2-week working block.</div>
    <div class="chart-row center">{spark}</div>
  </div>

  <div style="font-size: 10.5pt; color: {PALETTE['text_body']}; line-height: 1.7; margin: 8pt 0 0 0;">
    <p>This report identified a clear set of high-priority issues and ordered them by the impact each one has on your visibility in search. The plan is designed so you start seeing results within the first sprint, not at the end of the quarter.</p>
    <p>None of the issues require a redesign or a big rebuild. Most are surgical changes a developer can ship in a single afternoon, paired with content updates that build a stronger foundation over time.</p>
  </div>

  <div class="cta-block">
    <div class="cta-eyebrow">Next Step</div>
    <div class="cta-title">A 30-minute walkthrough, at no charge.</div>
    <div class="cta-body">On the call we will walk through the highest-priority issues live, show you the exact change for each one, and answer any questions about timing or implementation. Whether you choose to work with us or not, you will leave the call with everything you need to start.</div>
    <ul class="cta-list">
      <li>The full remediation plan, written for your developer</li>
      <li>The expected improvement timeline for each fix</li>
      <li>A clear scope and pricing if you would like us to handle delivery</li>
    </ul>
  </div>
</div>
"""


# ============================================================
# Rendering
# ============================================================

def _find_chromium_executable() -> str | None:
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    candidates = []
    if base.exists():
        candidates.extend(base.glob("chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"))
        candidates.extend(base.glob("chromium-*/chrome-win64/chrome.exe"))
        candidates.extend(base.glob("chromium-*/chrome-win/chrome.exe"))
    return str(candidates[0]) if candidates else None


def render_with_playwright(html_path: Path, pdf_path: Path,
                            header_html: str, footer_html: str) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    exe = _find_chromium_executable()
    try:
        with sync_playwright() as pw:
            launch_kwargs = {"headless": True}
            if exe:
                launch_kwargs["executable_path"] = exe
                print(f"[info] using chromium at {exe}")
            browser = pw.chromium.launch(**launch_kwargs)
            page = browser.new_page()
            page.goto(html_path.as_uri(), wait_until="load")
            try:
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(800)
            except Exception:
                pass
            page.pdf(
                path=str(pdf_path), format="A4", print_background=True,
                margin={"top": "30mm", "right": "14mm", "bottom": "22mm", "left": "14mm"},
                display_header_footer=True,
                header_template=header_html, footer_template=footer_html,
            )
            browser.close()
        return True
    except Exception as exc:
        print(f"[warn] Playwright render failed: {exc}", file=sys.stderr)
        return False


def _synthesize_action_md_from_quick_artifacts(root: Path) -> str | None:
    """Build a legacy-shaped action-plan markdown from /audit-quick artifacts.

    The legacy PDF generator expects section-08-action.md (or section-06-
    action-plan.md). The modern /audit-quick pipeline only writes report-
    full.md + findings.json. When neither legacy file exists but the modern
    artifacts do, we synthesize a minimal action plan so the PDF generator
    can still produce a deliverable rather than hard-erroring. The synthesis
    feeds the same parse_top_findings / parse_quick_wins / parse_sprints
    functions used for the real plan.

    Returns the markdown string, or None if the modern artifacts are also
    missing (in which case the caller should keep its original error path).
    """
    findings_path = root / "findings.json"
    if not findings_path.exists():
        return None
    try:
        records = json.loads(findings_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(records, list) or not records:
        return None

    sev_rank = {"critical": 0, "major": 1, "minor": 2, "info": 3}
    actionable = [r for r in records if isinstance(r, dict) and r.get("status") in ("fail", "warn")]
    if not actionable:
        return None
    actionable.sort(key=lambda r: (sev_rank.get((r.get("severity") or "info").lower(), 9),
                                     float(r.get("score") or 0.0)))

    cat_to_area = {"on-page": "On-page", "technical": "Technical",
                   "off-page": "Off-page", "local-seo": "Local"}

    def _evidence_str(rec: dict) -> str:
        raw = rec.get("evidence_json") or ""
        if not raw:
            return ""
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                bits = [f"{k}={v}" for k, v in list(parsed.items())[:6]]
                return ", ".join(bits)
        except Exception:
            pass
        return str(raw)[:200]

    issues_pool = [r for r in actionable
                   if (r.get("severity") or "").lower() in ("critical", "major")]
    if not issues_pool:
        issues_pool = actionable
    top_issues = issues_pool[:10]
    n_issues = len(top_issues)

    lines: list[str] = []
    lines.append("# Action Plan (synthesized)\n")
    lines.append(f"## Top {n_issues} high-priority issues (next 90 days)\n")
    for i, rec in enumerate(top_issues, start=1):
        name = (rec.get("check_name") or rec.get("check_id") or "Issue").strip()
        sev = (rec.get("severity") or "major").capitalize()
        category = (rec.get("category") or "").lower()
        area = cat_to_area.get(category, "On-page")
        broken = _evidence_str(rec) or f"{rec.get('check_id', '')} flagged a {rec.get('status', 'fail')} status."
        fix = (rec.get("remediation") or "").strip() or "Address the underlying issue per the check definition."
        impact = f"Current score {rec.get('score', 0)}/10 on this check; resolving improves the {area.lower()} dimension score."
        lines.append(f"### Issue {i} of {n_issues} - {name}")
        lines.append("")
        lines.append(f"- **Severity:** {sev}")
        lines.append(f"- **Headline:** {name}")
        lines.append(f"- **What is broken (plain English):** {broken}")
        lines.append(f"- **Fix:** {fix}")
        lines.append(f"- **Impact:** {impact}")
        lines.append(f"- **Effort:** Medium")
        lines.append(f"- **Owner:** {area} team")
        lines.append("")

    minor_pool = [r for r in actionable
                  if (r.get("severity") or "").lower() == "minor"]
    quick_pool = minor_pool[:10] if minor_pool else actionable[n_issues:n_issues + 10]
    n_q = len(quick_pool)
    lines.append(f"## Top {n_q} quick wins (this month)\n")
    for i, rec in enumerate(quick_pool, start=1):
        name = (rec.get("check_name") or rec.get("check_id") or "Quick win").strip()
        fix = (rec.get("remediation") or "").strip()
        if not fix:
            fix = _evidence_str(rec) or "Address per the check definition."
        lines.append(f"### Quick win {i} - {name}")
        lines.append("")
        lines.append(fix)
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir")
    parser.add_argument("--client", default="www.example.com")
    parser.add_argument("--industry", default="E-Commerce")
    parser.add_argument("--location", default="n/a")
    parser.add_argument("--date", default="20 May 2026")
    parser.add_argument("--brand-bold", default=BRANDING["brand_bold"])
    parser.add_argument("--brand-suffix", default=BRANDING["brand_suffix"])
    parser.add_argument("--no-root-copy", action="store_true")
    parser.add_argument("--no-downloads-copy", action="store_true",
                        help="Skip the mirror copy to $env:USERPROFILE/Downloads.")
    # --depth is accepted for backwards compatibility but ignored.
    # The report always renders the full structure (no page cap).
    parser.add_argument("--depth", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    root = Path(args.artifact_dir)
    if not root.exists():
        print(f"artifact_dir not found: {root}", file=sys.stderr); return 1
    # Path.as_uri() (used by Playwright below for the html_path goto) requires
    # an absolute path. CLI callers commonly pass a relative path, so resolve
    # once here rather than at every consumer.
    root = root.resolve()

    # --- Locate the action-plan file. Support both legacy and new naming. ---
    # /audit-quick only writes findings.json + report-full.md, so when no
    # legacy section-0X-action*.md is present we synthesize a minimal action
    # plan from those artifacts. The synthesized markdown feeds the same
    # parse_top_findings / parse_quick_wins parsers used for real plans.
    # The action plan can come from one of three shapes:
    # 1. Legacy: a single section-08-action.md (or section-06-action-plan.md)
    #    with "Top N findings" + "Top N quick wins" + Sprint blocks merged.
    # 2. New (2026-06-16): split across section-07-quick-wins.md +
    #    section-08-sprint-plan.md (no priority-finding block - that role
    #    is taken over by the index page + dimension issue cards).
    # 3. Synthesized from findings.json (e.g. /audit-quick artifacts).
    # We concatenate whatever exists so parse_top_findings / parse_quick_wins
    # / parse_sprints each see the headings they expect.
    legacy_action = root / "section-08-action.md"
    if not legacy_action.exists():
        legacy_action = root / "section-06-action-plan.md"
    qw_path = root / "section-07-quick-wins.md"
    sprint_path = root / "section-08-sprint-plan.md"

    md_parts: list[str] = []
    if legacy_action.exists():
        md_parts.append(legacy_action.read_text(encoding="utf-8"))
    if qw_path.exists():
        md_parts.append(qw_path.read_text(encoding="utf-8"))
    if sprint_path.exists():
        md_parts.append(sprint_path.read_text(encoding="utf-8"))

    if not md_parts:
        synthesized = _synthesize_action_md_from_quick_artifacts(root)
        if synthesized is None:
            print(f"[err] action plan file not found in {root}", file=sys.stderr); return 1
        print(f"[info] synthesized action plan from findings.json "
              f"(no section-0X-action*.md in {root.name})", file=sys.stderr)
        md_parts.append(synthesized)
    action_md = "\n\n".join(md_parts)

    # No page cap. Always render every priority finding the writer surfaced
    # and every quick win. The 6 dimension sections below carry every issue
    # from findings.json regardless of what made the priority-finding list.
    findings = parse_top_findings(action_md, limit=10)
    quick_wins = parse_quick_wins(action_md, limit=20)
    print(f"[info] parsed {len(findings)} priority findings · {len(quick_wins)} quick wins")

    def _read(name: str) -> str:
        p = root / name
        return p.read_text(encoding="utf-8") if p.exists() else ""

    # New (2026-06-16) structural files. Falls back to legacy names so older
    # runs still render.
    exec_summary_md = _read("section-00-executive-summary.md") or _read("section-01-executive.md")
    strategy_rec_md = _read("section-strategy-recommendation.md")
    closing_cta_md  = _read("section-11-closing-cta.md")

    # Dimension MDs (kept for any future deep-dive rendering)
    sec_strategy_md = _read("section-01-strategy.md") or _read("section-02-strategy.md")
    sec_content_md  = _read("section-02-content.md") or _read("section-03-content.md")
    sec_onpage_md   = _read("section-03-onpage.md") or _read("section-04-onpage.md") or _read("section-02-onpage.md")
    sec_tech_md     = _read("section-04-technical.md") or _read("section-05-technical.md") or _read("section-03-technical.md")
    sec_offlocal_md = _read("section-05-offpage-local.md") or _read("section-06-offpage-local.md") or (_read("section-04-offpage-ai.md") + "\n\n" + _read("section-05-local.md")).strip()
    sec_geo_md      = _read("section-06-geo.md") or _read("section-07-geo.md") or _read("section-04-offpage-ai.md")
    sec_evidence_md = _read("section-09-evidence.md") or _read("section-08-evidence.md")
    sec_method_md   = _read("section-10-methodology.md") or _read("section-07-methodology.md")

    ai_context = extract_ai_context(sec_geo_md) if sec_geo_md else {}
    local_cards = extract_local_cards(sec_offlocal_md) if sec_offlocal_md else []
    content_cards = extract_content_cards(sec_content_md or sec_onpage_md, action_md) if (sec_content_md or sec_onpage_md) else []

    run_meta = {}
    run_path = root / "run.json"
    if run_path.exists():
        try: run_meta = json.loads(run_path.read_text(encoding="utf-8"))
        except Exception: run_meta = {}
    scores = run_meta.get("scores") or run_meta.get("scorecard") or {}
    pages_crawled = run_meta.get("pages_crawled") or 38

    # Build the section-by-section issue inventory once - used by the
    # dashboard "scare page" and the runtime stat strips on deep-dive pages.
    inventory = compute_issue_inventory(root)

    # ---- Section cards (one card per section, read from section-cards.json).
    #      Loaded HERE (before assembly) because the issue-index page needs the
    #      card headlines + page numbers. Per-domain + data-driven; the
    #      generator produces correct content for any client, not a hardcoded one.
    section_cards: list[dict] = []
    cards_path = root / "section-cards.json"
    if cards_path.exists():
        try:
            loaded = json.loads(cards_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                loaded = loaded.get("cards", [])
            if isinstance(loaded, list):
                section_cards = [c for c in loaded if isinstance(c, dict) and c.get("headline")]
        except Exception as exc:
            print(f"[warn] section-cards.json unreadable: {exc}", file=sys.stderr)
    if not section_cards:
        print("[warn] no section-cards.json found - section card pages will be skipped", file=sys.stderr)

    # ============================================================
    # ASSEMBLE THE PDF - sales-conversion order:
    #   Cover -> Issue Dashboard (scare page) -> Top 6 priority findings
    #   -> 6 section pages (Strategy / Content / On-page / Technical
    #      / Off-page+Local / GEO) -> Quick Wins -> Evidence -> URL Appendix
    #   -> Methodology
    #
    # The high-priority finding cards come BEFORE the section deep-dives so
    # the client sees the worst problems in the first 4-5 page-flips. A
    # prospect skimming the PDF on their phone sees: cover, scary dashboard,
    # critical issue 1, critical issue 2, critical issue 3 - before they
    # ever reach the diagnostic detail.
    # ============================================================
    # Map a high-priority finding to one of the 6 report areas for its index
    # chip (the "On-page / Off-page" status the client wants on each line).
    def _finding_area(f: dict) -> str:
        text = f"{f.get('headline','')} {f.get('category','')} {f.get('broken','')}".lower()
        if any(k in text for k in ("ai search", "ai overview", "chatgpt", "perplexity", "gemini", "generative", "llm")):
            return "GEO (AI Search)"
        bucket = _infer_category_from_text(text)
        return {
            "CONTENT": "Content", "ON-PAGE": "On-page",
            "SCHEMA": "Technical", "TECHNICAL": "Technical",
            "LOCAL": "Off-page + Local", "OFF-PAGE": "Off-page + Local",
        }.get(bucket, "On-page")

    # =========================================================================
    # NEW PAGE ORDER (2026-06-16, per client requirements):
    #   1. Cover
    #   2. Index (every critical + major issue, stat cards, page anchors)
    #   3. Executive summary (500-700 chars, plain English)
    #   4-5. Strategy Recommendation (current + problem + recommended + competitors)
    #   6+. 6 dimension sections, each with all its issues by severity + passes card
    #   N. Quick wins
    #   N+. 3 Sprints
    #   N+. URL appendix
    #   N+. Methodology
    #   N+. Closing CTA card (the "Can these issues be fixed?" + email)
    # No page cap. Every issue from findings.json renders.
    # =========================================================================
    full_issues = compute_full_issue_list(root, pages_total=pages_crawled)

    # Build the index entries from EVERY critical + major issue (not just priority).
    # Each entry gets its actual page number computed below after assembly.
    index_entries: list[dict] = []
    for e in full_issues:
        if e["severity"] in ("critical", "major"):
            index_entries.append({
                "problem": e.get("name", e.get("check_id", "")),
                "area":    e.get("area_label", ""),
                "severity": e["severity"],
                "page":     0,  # filled by _resolve_index_pages on the second pass
                "group":    "issue",
                "check_id": e["check_id"],
            })

    # Optional Semrush enrichment - returns None silently when the key is
    # missing or the call fails. The dashboard treats None as "skip the row".
    semrush_data = _fetch_semrush_overview(args.client)
    if semrush_data:
        print(f"[info] semrush: DA={semrush_data.get('domain_authority')}, "
              f"traffic={semrush_data.get('monthly_traffic')}, "
              f"keywords={semrush_data.get('monthly_keywords')}")
    else:
        print("[info] semrush: skipped (no SEMRUSH_API_KEY in env)")

    pages_html = []
    pages_html.append(build_cover(args.client, args.industry, args.location, args.date, pages_crawled))
    # Index page (rebuilt by build_issue_dashboard_page - lists every crit+major).
    pages_html.append(build_issue_dashboard_page(
        args.client, inventory, pages_crawled, index_entries=index_entries,
        semrush=semrush_data,
    ))

    # ---- Executive Summary (500-700 chars; plain English; one page). ----
    pages_html.append(build_executive_summary_page(exec_summary_md, run_meta))

    # ---- Strategy Recommendation (NEW, 1-2 pages). Reads
    #      section-strategy-recommendation.md or falls back to a generic. ----
    pages_html.extend(build_strategy_recommendation_page(strategy_rec_md))

    # ---- 6 dimension sections, in order. Each renders all its issues by
    #      severity, then a "What is working" passes card. No page cap. ----
    pages_html.extend(build_dimension_section_pages(
        root, full_issues, pages_crawled, scores,
    ))

    # ---- Quick wins (every win, not capped). 10 per page. ----
    if quick_wins:
        for i in range(0, len(quick_wins), 10):
            suffix = "" if i == 0 else " (continued)"
            pages_html.append(build_quick_wins_page(quick_wins, i, i + 10, page_title_suffix=suffix))

    # ---- Sprint pages REMOVED (per client request 2026-06-16). The 90-day
    #      execution roadmap was felt to be filler before the URL appendix.
    #      build_sprint_page and parse_sprints remain in the file for future
    #      use but are no longer wired into the default render path.

    # ---- URL appendix (every page reviewed). Always rendered now. ----
    url_page = build_url_appendix_page(root, pages_crawled)
    if url_page:
        pages_html.append(url_page)

    # ---- Methodology (always last before the CTA). ----
    if sec_method_md:
        meth_pages = build_deepdive_pages_from_section(
            sec_method_md, "Methodology",
            max_per_subsection=1, body_char_cap=3000,
            runtime_stats=None, severity_chart_html=None,
            max_total_pages=1,
            merge_subsections=True,
        )
        pages_html.extend(meth_pages)

    # ---- Closing CTA card (final page). ----
    pages_html.append(build_closing_cta_page(closing_cta_md))

    html_path = root / "report-final.html"
    pdf_path = root / "report-final.pdf"

    def _assemble_and_render() -> bool:
        """Stitch pages_html into the final document, write the HTML, render to
        PDF. Called once, then a second time after the index page numbers are
        reconciled to the actual rendered pages."""
        body = "\n".join(pages_html)
        full_html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>SEO Audit Report - {args.client}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap">
<style>{CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""
        html_path.write_text(full_html, encoding="utf-8")
        return render_with_playwright(html_path, pdf_path, header_html, footer_html)

    client_caps = args.client.upper().replace("WWW.", "")
    # Industry · Location for the left-bottom of the header (uppercase, accent-colored).
    industry_token = (args.industry or "").strip()
    location_token = (args.location or "").strip()
    if industry_token and location_token:
        client_meta = f"{industry_token} · {location_token}"
    elif industry_token:
        client_meta = industry_token
    elif location_token:
        client_meta = location_token
    else:
        client_meta = "SEO AUDIT"
    client_meta = client_meta.upper()
    accent = BRANDING["accent_color"] or PALETTE["blue_accent"]
    header_html = (HEADER_HTML
        .replace("__NAVY__", PALETTE["navy_dark"])
        .replace("__ACCENT__", accent)
        .replace("__CLIENT_CAPS__", client_caps)
        .replace("__CLIENT_META__", client_meta)
        .replace("__REPORT_TITLE__", "SEO Audit Report")
        .replace("__REPORT_DATE__", f"Reporting period · {args.date}")
    )
    footer_html = (FOOTER_HTML
        .replace("__NAVY__", PALETTE["navy_dark"])
        .replace("__ACCENT__", accent)
        .replace("__BRAND__", args.brand_bold)
        .replace("__BRAND_SUFFIX__", args.brand_suffix)
        .replace("__FOOTER_CENTER__", f"{args.client} - SEO Audit Report")
    )

    if not _assemble_and_render():
        print("[err] Playwright render failed", file=sys.stderr); return 1
    print(f"[ok] Playwright wrote {pdf_path}")

    # ---- Second pass: reconcile the index page numbers to the ACTUAL pages
    #      the cards rendered on (cards can overflow, shifting everything after
    #      them). The index is a single fixed page, so re-rendering with the
    #      corrected numbers does not change pagination - the result is stable.
    corrected = _resolve_index_pages(pdf_path, index_entries)
    if corrected and any(c.get("page") != e.get("page") for c, e in zip(corrected, index_entries)):
        pages_html[1] = build_issue_dashboard_page(
            args.client, inventory, pages_crawled, index_entries=corrected,
            semrush=semrush_data,
        )
        if _assemble_and_render():
            print("[ok] index page numbers reconciled to actual rendered pages")

    if not args.no_root_copy:
        repo_root = Path(__file__).resolve().parent.parent
        client_slug = re.sub(r"[^a-zA-Z0-9]+", "-", args.client.replace("www.", "")).strip("-")
        date_slug = re.sub(r"[^a-zA-Z0-9]+", "-", args.date).strip("-")
        client_pdf_filename = f"{client_slug}_SEO_Audit_Report_{date_slug}.pdf"

        # 1. Canonical archive in generated-audits/
        orders_dir = repo_root / "generated-audits"
        orders_dir.mkdir(parents=True, exist_ok=True)
        archived_pdf = orders_dir / client_pdf_filename
        shutil.copy2(pdf_path, archived_pdf)
        print(f"[ok] copied to generated-audits: {archived_pdf}")

        # 2. Mirror copy to the user's Downloads folder so the client never
        #    has to dig through the project to find their report. Cross-platform:
        #    %USERPROFILE%/Downloads on Windows, ~/Downloads on macOS/Linux.
        if not args.no_downloads_copy:
            downloads_dir = None
            home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or str(Path.home()))
            candidate = home / "Downloads"
            if candidate.is_dir():
                downloads_dir = candidate
            if downloads_dir is not None:
                try:
                    downloads_pdf = downloads_dir / client_pdf_filename
                    shutil.copy2(pdf_path, downloads_pdf)
                    print(f"[ok] copied to Downloads: {downloads_pdf}")
                except Exception as exc:
                    print(f"[warn] could not copy to Downloads ({exc}); skipped",
                          file=sys.stderr)
            else:
                print(f"[warn] Downloads folder not found at {candidate}; skipped",
                      file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
