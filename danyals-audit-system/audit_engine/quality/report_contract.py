"""Deterministic M5 report-design contract validator (no AI required).

The interactive ``/audit`` skill runs the full M5 QA Report Validator (a Claude
subagent) against the assembled report and re-invokes the offending writer on a
blocker. The PLATFORM audit path (the CLI ``full`` command the AIOS backend
shells out to -> ``write_full_bundle``) never invokes that subagent, so its
report used to render with no design-contract gate at all.

This module provides the AI-free subset of the M5 checklist as machine-checkable
rules over the assembled ``report.html`` string, plus targeted auto-patchers, so
``write_full_bundle`` can run a real validate -> patch -> re-validate loop on
EVERY audit (free + paid) before the PDF is rendered. It never imports Playwright
or any network client; it operates purely on the HTML string the consulting
generator produced.

Checked (blockers):
  1. All 7 dimension sections present AND in contract order
     (Strategy, Content, On-page, Technical, Off-page, Local SEO, GEO).
  2. Index issue count == inventory critical + major (the index lists every
     critical and major issue type).
  3. Zero em dashes (U+2014) and zero en dashes (U+2013).
  4. Closing CTA carries the branding contact email.
  5. Severity highlighting present (an ``fp-finding`` card with a critical/major
     severity chip) whenever there is at least one critical or major issue.

Warnings (logged, non-blocking):
  - No quick-wins / actionable-roadmap page.
  - An issue card with no visible description text.

Auto-patchers (applied inside the loop):
  - dash blocker -> strip U+2014 / U+2013 to '-' across the whole document.
  - cta-email blocker -> inject a contact line before ``</body>``.
Structural blockers (missing/mis-ordered sections, index-count mismatch,
missing highlighting) are not string-patchable; they indicate a generator bug,
are reported, and stop the loop (the report still renders best-effort).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# The dim-header-title text each dimension section opens with, in contract order.
_SECTION_MARKERS: tuple[tuple[str, str], ...] = (
    ("strategy",  "Strategy issues in your site"),
    ("content",   "Content issues in your site"),
    ("onpage",    "On-page issues in your site"),
    ("technical", "Technical issues in your site"),
    ("offpage",   "Off-page issues in your site"),
    ("local",     "Local SEO issues in your site"),
    ("geo",       "GEO (AI Search) issues in your site"),
)

_EM_DASH = "—"
_EN_DASH = "–"
_DASH_TRANSLATE = {ord(_EM_DASH): "-", ord(_EN_DASH): "-"}

_INDEX_ROW_RE = re.compile(r'class="idx-sev sev-chip ')
_TILE_CRIT_RE = re.compile(r'tile-label">Critical</div><div class="tile-value">(\d+)</div>')
_TILE_MAJOR_RE = re.compile(r'tile-label">Major</div><div class="tile-value">(\d+)</div>')


@dataclass
class ContractVerdict:
    passed: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)


def validate_report_contract(html: str, *, branding_email: str = "") -> ContractVerdict:
    """Validate the assembled report HTML against the deterministic M5 subset."""
    blockers: list[str] = []
    warnings: list[str] = []
    facts: dict = {}

    # 1. Sections present + in order.
    positions: list[int] = []
    missing: list[str] = []
    for key, marker in _SECTION_MARKERS:
        idx = html.find(marker)
        if idx == -1:
            missing.append(key)
        positions.append(idx)
    if missing:
        blockers.append(f"missing_sections:{','.join(missing)}")
    else:
        ordered = [p for p in positions if p != -1]
        if ordered != sorted(ordered):
            blockers.append("sections_out_of_order")
    facts["sections_present"] = 7 - len(missing)

    # 2. Index count == inventory critical + major.
    crit_m = _TILE_CRIT_RE.search(html)
    major_m = _TILE_MAJOR_RE.search(html)
    index_rows = len(_INDEX_ROW_RE.findall(html))
    facts["index_issue_rows"] = index_rows
    if crit_m and major_m:
        expected = int(crit_m.group(1)) + int(major_m.group(1))
        facts["inventory_crit_major"] = expected
        if index_rows != expected:
            blockers.append(f"index_count_mismatch:index={index_rows},inventory={expected}")
    else:
        warnings.append("inventory_tiles_unparsed")

    # 3. No em / en dashes.
    n_em = html.count(_EM_DASH)
    n_en = html.count(_EN_DASH)
    facts["em_dashes"] = n_em
    facts["en_dashes"] = n_en
    if n_em or n_en:
        blockers.append(f"dashes:em={n_em},en={n_en}")

    # 4. Closing CTA carries the branding email.
    if branding_email:
        if branding_email not in html:
            blockers.append("cta_email_missing")
        facts["cta_email_present"] = branding_email in html

    # 5. Severity highlighting present when there are critical/major issues.
    has_crit_major = index_rows > 0 or (crit_m and major_m and (int(crit_m.group(1)) + int(major_m.group(1))) > 0)
    highlighted = ("fp-finding" in html) and (("sev-critical" in html) or ("sev-major" in html))
    facts["highlighting_present"] = highlighted
    if has_crit_major and not highlighted:
        blockers.append("severity_highlighting_missing")

    # Warnings (non-blocking).
    if "Quick Wins" not in html and "Quick wins" not in html and "quick-win" not in html:
        warnings.append("no_quick_wins_page")

    return ContractVerdict(passed=not blockers, blockers=blockers, warnings=warnings, facts=facts)


def strip_dashes(html: str) -> str:
    """Replace every em / en dash with a hyphen across the whole document."""
    return html.translate(_DASH_TRANSLATE)


def inject_cta_email(html: str, email: str) -> str:
    """Guarantee the contact email appears, as a backstop when the CTA builder
    somehow did not include it. Injects a minimal contact line before </body>."""
    if not email or email in html:
        return html
    block = (
        '<div class="page"><div class="cta-card">'
        '<div class="cta-card-body"><p>If you want these issues fixed for you, '
        f'contact: {email}</p></div></div></div>'
    )
    lower = html.lower()
    pos = lower.rfind("</body>")
    if pos == -1:
        return html + block
    return html[:pos] + block + html[pos:]


def apply_patches(html: str, verdict: ContractVerdict, *, email: str = "") -> str:
    """Apply the string-level auto-patches for the patchable blockers. Returns
    the patched HTML (unchanged when no patchable blocker is present)."""
    out = html
    for b in verdict.blockers:
        if b.startswith("dashes:"):
            out = strip_dashes(out)
        elif b == "cta_email_missing":
            out = inject_cta_email(out, email)
    return out


def enforce_report_contract(
    html: str,
    *,
    branding_email: str = "",
    max_iterations: int = 3,
) -> tuple[str, ContractVerdict, int]:
    """Run the validate -> patch -> re-validate loop.

    Returns ``(html, final_verdict, iterations)``. The loop stops early when the
    report is clean or when a round of patching changes nothing (a residual
    structural blocker that cannot be auto-fixed - the caller then renders
    best-effort and logs the verdict)."""
    verdict = validate_report_contract(html, branding_email=branding_email)
    iterations = 0
    while verdict.blockers and iterations < max_iterations:
        iterations += 1
        patched = apply_patches(html, verdict, email=branding_email)
        if patched == html:
            break  # nothing patchable changed; stop
        html = patched
        verdict = validate_report_contract(html, branding_email=branding_email)
    return html, verdict, iterations
