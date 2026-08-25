"""Checks over the Lighthouse ``audits[]`` array.

PageSpeed was fetched, three numbers were taken off it, and the rest was
discarded. The array names the exact resources costing the page its score -
which stylesheet blocks rendering, which script is unused, which element is the
Largest Contentful Paint - and none of it reached a finding.

Audit ids below are Lighthouse's own stable identifiers, so each check reads
one documented thing rather than pattern-matching English titles.

The distinction this module is careful about: an audit that is ABSENT from the
response and an audit that PASSED look identical if you only keep failures.
Reporting the first as the second is the exact failure this audit system exists
to avoid, so every check separates them.
"""

from __future__ import annotations

from typing import Any

from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.registry import check

# --- Lighthouse audit ids (stable, published) ------------------------------
#: Lighthouse 12 renamed several audits to an "-insight" form and REMOVED the
#: mobile-usability ones entirely, so a check pinned to one id silently stops
#: measuring after a Lighthouse upgrade. Each constant is the list of ids that
#: have carried this measurement.
RENDER_BLOCKING = ("render-blocking-resources", "render-blocking-insight")
UNUSED_CSS = ("unused-css-rules",)
UNUSED_JS = ("unused-javascript",)
LCP_ELEMENT = ("largest-contentful-paint-element", "lcp-discovery-insight")
LAYOUT_SHIFTS = ("layout-shift-elements", "layout-shifts", "cls-culprits-insight")
VIEWPORT = ("viewport", "meta-viewport", "viewport-insight")
FONT_SIZE = ("font-size",)
TAP_TARGETS = ("tap-targets",)
CONTENT_WIDTH = ("content-width",)
TBT = "total-blocking-time"
SPEED_INDEX = "speed-index"
INTERACTIVE = "interactive"

#: Lighthouse sets this when an audit does not apply to the page at all.
NOT_APPLICABLE = "notApplicable"

# web.dev thresholds, the same ones Google's own tooling reports against.
LCP_GOOD_MS, LCP_POOR_MS = 2500, 4000
CLS_GOOD, CLS_POOR = 0.1, 0.25
INP_GOOD_MS, INP_POOR_MS = 200, 500
TBT_GOOD_MS, TBT_POOR_MS = 200, 600

# JUDGEMENT: a saving worth telling a client about. Below ~150 ms the change is
# inside the noise of a single measurement, so reporting it invites work that
# cannot be shown to have helped.
SAVINGS_WORTH_REPORTING_MS = 150


def _audit(psi: Any, audit_ids: tuple[str, ...] | str) -> tuple[str, dict] | tuple[None, None]:
    """First id that the response actually carries, with its row."""
    audits = getattr(psi, "audits", {}) or {}
    for aid in ((audit_ids,) if isinstance(audit_ids, str) else audit_ids):
        if aid in audits:
            return aid, audits[aid]
    return None, None


def _metric(psi: Any, name: str) -> float | None:
    """Field percentile first, lab value second - the same order the CWV
    findings use, so the two never disagree about which number they mean.

    Matches on the CANONICAL key: PageSpeed names one metric three ways.
    """
    from audit_engine.integrations.pagespeed import canonical_metric

    want = canonical_metric(name)
    for m in getattr(psi, "field_metrics", []) or []:
        key = getattr(m, "key", "") or canonical_metric(m.name or "")
        if key == want and m.percentile is not None:
            return float(m.percentile)
    for m in getattr(psi, "lab_metrics", []) or []:
        key = getattr(m, "key", "") or canonical_metric(m.name or "")
        if key == want and m.value is not None:
            return float(m.value)
    return None


def _no_psi(psi: Any) -> Verdict | None:
    if psi is None or getattr(psi, "error", None):
        return Verdict("n_a", 0.0, "info", 0.0,
                       {"reason": f"PageSpeed did not return a result: "
                                  f"{getattr(psi, 'error', 'not run')}"})
    if not (getattr(psi, "audits", {}) or {}):
        return Verdict("n_a", 0.0, "info", 0.0,
                       {"reason": "PageSpeed returned no audits array"})
    return None


def _from_audit(
    psi: Any, audit_id: str, *, severity: str, remediation: str,
    minor_below_ms: int = SAVINGS_WORTH_REPORTING_MS,
) -> Verdict:
    """Shared body for the opportunity-shaped audits."""
    if (na := _no_psi(psi)) is not None:
        return na
    aid, a = _audit(psi, audit_id)
    if a is None:
        names = (audit_id,) if isinstance(audit_id, str) else audit_id
        return Verdict("n_a", 0.0, "info", 0.0,
                       {"reason": f"Lighthouse ran none of {list(names)}",
                        "audits_looked_for": list(names)})
    if a.get("scoreDisplayMode") == NOT_APPLICABLE:
        return Verdict("n_a", 0.0, "info", 1.0,
                       {"audit": aid, "reason": "Lighthouse marked this not applicable"})
    score = a.get("score")
    savings = a.get("overallSavingsMs") or 0
    ev = {"audit": aid, "score": score, "items": a.get("items"),
          "estimated_savings_ms": savings,
          "estimated_savings_bytes": a.get("overallSavingsBytes"),
          "display": a.get("displayValue")}
    if score is None:
        return Verdict("n_a", 0.0, "info", 0.5,
                       {**ev, "reason": "Lighthouse returned no score for this audit"})
    if score >= 0.9:
        return Verdict("pass", round(score * 10, 1), "info", 0.9, ev)
    if savings and savings < minor_below_ms:
        return Verdict("warn", 7.0, "minor", 0.9, ev,
                       f"{remediation} Estimated saving is only {int(savings)} ms, which is "
                       f"inside measurement noise - fix it opportunistically, not urgently.")
    return Verdict(
        "fail" if score < 0.5 else "warn",
        round(score * 10, 1),
        severity if score < 0.5 else "minor",
        0.9, ev,
        f"{remediation}"
        + (f" Lighthouse estimates {int(savings)} ms could be saved." if savings else ""),
    )


# --------------------------------------------------------------------------
# Render blocking
# --------------------------------------------------------------------------

@check("TECH-029", scope="psi")
def check_render_blocking(psi: Any) -> Verdict:
    """TECH-029 - resources that delay first paint."""
    return _from_audit(
        psi, RENDER_BLOCKING, severity="major",
        remediation="Stylesheets and scripts in the document head block the first paint. "
                    "Inline the CSS needed above the fold and defer the rest.",
    )


@check("TECH-045", scope="psi")
def check_render_blocking_css(psi: Any) -> Verdict:
    """TECH-045 - the CSS half of render blocking.

    Lighthouse reports one combined audit, so this and TECH-046 read the same
    row and say so in evidence rather than pretending to two measurements.
    """
    v = _from_audit(
        psi, RENDER_BLOCKING, severity="major",
        remediation="Render-blocking CSS delays the first paint. Inline critical CSS and "
                    "load the rest with media=print/onload or a preload swap.",
    )
    return Verdict(v.status, v.score, v.severity, v.confidence,
                   {**v.evidence, "note": "Lighthouse reports CSS and JS in one "
                                          "render-blocking audit; TECH-046 reads the same row"},
                   v.remediation, v.references)


@check("TECH-046", scope="psi")
def check_render_blocking_js(psi: Any) -> Verdict:
    """TECH-046 - the JS half of render blocking."""
    v = _from_audit(
        psi, RENDER_BLOCKING, severity="major",
        remediation="Render-blocking JavaScript delays the first paint. Add defer or async "
                    "to scripts that are not needed for the initial render.",
    )
    return Verdict(v.status, v.score, v.severity, v.confidence,
                   {**v.evidence, "note": "Lighthouse reports CSS and JS in one "
                                          "render-blocking audit; TECH-045 reads the same row"},
                   v.remediation, v.references)


@check("TECH-047", scope="psi")
def check_unused_css(psi: Any) -> Verdict:
    """TECH-047 - stylesheet bytes the page never uses."""
    return _from_audit(
        psi, UNUSED_CSS, severity="minor",
        remediation="Stylesheets ship rules this page never applies. Split CSS per template "
                    "or remove dead rules.",
    )


@check("TECH-048", scope="psi")
def check_unused_js(psi: Any) -> Verdict:
    """TECH-048 - script bytes the page never executes.

    Usually a whole library loaded for one widget, and on a marketing site
    usually a tag manager container nobody has pruned.
    """
    return _from_audit(
        psi, UNUSED_JS, severity="minor",
        remediation="Scripts ship code this page never runs. Code-split, drop unused "
                    "libraries, and audit the tag manager container.",
    )


# --------------------------------------------------------------------------
# Core Web Vitals, in detail
# --------------------------------------------------------------------------

@check("TECH-039", scope="psi")
def check_core_web_vitals(psi: Any) -> Verdict:
    """TECH-039 - the three Core Web Vitals as one verdict.

    Google's own pass condition is ALL THREE in the good band, so this is not
    an average: one poor metric fails the assessment.
    """
    if (na := _no_psi(psi)) is not None:
        return na
    lcp = _metric(psi, "largest_contentful_paint")
    cls = _metric(psi, "cumulative_layout_shift")
    inp = _metric(psi, "interaction_to_next_paint") or _metric(
        psi, "experimental_interaction_to_next_paint")
    measured = {k: v for k, v in
                {"lcp_ms": lcp, "cls": cls, "inp_ms": inp}.items() if v is not None}
    ev = {**measured, "thresholds": {"lcp_ms": LCP_GOOD_MS, "cls": CLS_GOOD,
                                     "inp_ms": INP_GOOD_MS},
          "assessment_rule": "Google requires all three in the good band"}
    if not measured:
        return Verdict("n_a", 0.0, "info", 0.0,
                       {**ev, "reason": "no Core Web Vitals were returned for this URL"})
    bad = []
    if lcp is not None and lcp > LCP_GOOD_MS:
        bad.append(f"LCP {lcp:.0f} ms")
    if cls is not None and cls > CLS_GOOD:
        bad.append(f"CLS {cls:.3f}")
    if inp is not None and inp > INP_GOOD_MS:
        bad.append(f"INP {inp:.0f} ms")
    ev["failing"] = bad
    ev["metrics_available"] = len(measured)
    if not bad:
        # Confidence scales with how many of the three we actually have.
        return Verdict("pass", 10.0, "info", 0.6 + 0.13 * len(measured), ev)
    poor = (
        (lcp is not None and lcp > LCP_POOR_MS)
        or (cls is not None and cls > CLS_POOR)
        or (inp is not None and inp > INP_POOR_MS)
    )
    return Verdict("fail" if poor else "warn",
                   max(0.0, 10.0 - 3.5 * len(bad)),
                   "critical" if poor else "major",
                   0.6 + 0.13 * len(measured), ev,
                   f"Core Web Vitals assessment fails on {', '.join(bad)}. Google requires "
                   f"all three metrics in the good band, so one poor metric fails the whole "
                   f"assessment regardless of the others.")


@check("ON-084", scope="psi")
def check_cwv_seo_impact(psi: Any) -> Verdict:
    """ON-084 - what the CWV result means for ranking, specifically.

    Page experience is a tie-breaker, not a primary signal: Google has said it
    matters when other signals are comparable. Overstating it is the most
    common way an audit sells the wrong work.
    """
    if (na := _no_psi(psi)) is not None:
        return na
    perf = (getattr(psi, "lighthouse_scores", {}) or {}).get("performance")
    field = [m for m in (getattr(psi, "field_metrics", []) or []) if m.percentile is not None]
    ev = {"performance_score": perf, "field_metrics_available": len(field),
          "basis": "field data (CrUX)" if field else "lab data only",
          "ranking_context": "page experience is a tie-breaker between comparable "
                             "results, not a primary ranking signal"}
    if not field:
        return Verdict("n_a", 0.0, "info", 0.5,
                       {**ev, "reason": "no field data for this URL, so real-user "
                                        "experience cannot be assessed. Lab numbers do "
                                        "not feed the page-experience signal."})
    poor = [m.name for m in field if (m.rating or "").upper() == "POOR"]
    ni = [m.name for m in field if (m.rating or "").upper() == "NEEDS_IMPROVEMENT"]
    ev["poor"] = poor
    ev["needs_improvement"] = ni
    if not poor and not ni:
        return Verdict("pass", 10.0, "info", 0.85, ev)
    return Verdict("fail" if poor else "warn",
                   max(0.0, 10.0 - 3.0 * len(poor) - 1.5 * len(ni)),
                   "major" if poor else "minor", 0.85, ev,
                   f"Real users experience {', '.join(poor + ni)} outside the good band. "
                   f"Fix these where you already compete closely on content; page "
                   f"experience decides between comparable results rather than "
                   f"outranking better content.")


@check("ON-085", scope="psi")
def check_lcp_element(psi: Any) -> Verdict:
    """ON-085 - WHICH element is the Largest Contentful Paint.

    Knowing LCP is 4 seconds is not actionable. Knowing it is the hero image
    is: preload it, size it, stop lazy-loading it.
    """
    if (na := _no_psi(psi)) is not None:
        return na
    aid, a = _audit(psi, LCP_ELEMENT)
    lcp = _metric(psi, "largest_contentful_paint")
    ev = {"lcp_ms": lcp, "element_identified": bool(a and a.get("items")),
          "audit": aid, "display": (a or {}).get("displayValue")}
    if a is None:
        return Verdict("n_a", 0.0, "info", 0.0,
                       {**ev, "reason": "Lighthouse did not report an LCP element"})
    if lcp is None:
        return Verdict("n_a", 0.0, "info", 0.4,
                       {**ev, "reason": "no LCP measurement to attribute"})
    if lcp <= LCP_GOOD_MS:
        return Verdict("pass", 10.0, "info", 0.85, ev)
    return Verdict("fail" if lcp > LCP_POOR_MS else "warn",
                   max(0.0, 10.0 - (lcp - LCP_GOOD_MS) / 400.0),
                   "major", 0.85, ev,
                   f"LCP is {lcp:.0f} ms against a {LCP_GOOD_MS} ms target. Lighthouse "
                   f"identifies the element responsible - preload it, give it explicit "
                   f"width and height, and make sure it is not lazy-loaded.")


@check("ON-086", scope="psi")
def check_cls_issues(psi: Any) -> Verdict:
    """ON-086 - layout shift, and which elements cause it."""
    if (na := _no_psi(psi)) is not None:
        return na
    cls = _metric(psi, "cumulative_layout_shift")
    _aid, a = _audit(psi, LAYOUT_SHIFTS)
    ev = {"cls": cls, "shifting_elements": (a or {}).get("items"),
          "good_threshold": CLS_GOOD, "poor_threshold": CLS_POOR}
    if cls is None:
        return Verdict("n_a", 0.0, "info", 0.0,
                       {**ev, "reason": "no CLS measurement returned"})
    if cls <= CLS_GOOD:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    return Verdict("fail" if cls > CLS_POOR else "warn",
                   max(0.0, 10.0 - cls * 20.0),
                   "major" if cls > CLS_POOR else "minor", 0.9, ev,
                   f"Cumulative Layout Shift is {cls:.3f} against a {CLS_GOOD} target. "
                   f"Reserve space for images, ads and embeds with explicit dimensions, "
                   f"and load webfonts with font-display: optional or swap.")


@check("ON-087", scope="psi")
def check_inp(psi: Any) -> Verdict:
    """ON-087 - Interaction to Next Paint, with the blocking time behind it."""
    if (na := _no_psi(psi)) is not None:
        return na
    inp = _metric(psi, "interaction_to_next_paint") or _metric(
        psi, "experimental_interaction_to_next_paint")
    tbt = _metric(psi, "total_blocking_time")
    ev = {"inp_ms": inp, "total_blocking_time_ms": tbt,
          "good_threshold_ms": INP_GOOD_MS, "poor_threshold_ms": INP_POOR_MS}
    if inp is None:
        if tbt is None:
            return Verdict("n_a", 0.0, "info", 0.0,
                           {**ev, "reason": "neither INP nor Total Blocking Time returned"})
        # TBT is the lab proxy for INP; report it as a proxy, and say so.
        ev["basis"] = "Total Blocking Time, a lab proxy for INP"
        if tbt <= TBT_GOOD_MS:
            return Verdict("pass", 9.0, "info", 0.6, ev)
        return Verdict("fail" if tbt > TBT_POOR_MS else "warn", 5.0,
                       "major" if tbt > TBT_POOR_MS else "minor", 0.6, ev,
                       f"No field INP for this URL. Total Blocking Time is {tbt:.0f} ms, "
                       f"which is the lab proxy: long tasks on the main thread will make "
                       f"real interactions feel slow.")
    if inp <= INP_GOOD_MS:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    return Verdict("fail" if inp > INP_POOR_MS else "warn",
                   max(0.0, 10.0 - (inp - INP_GOOD_MS) / 60.0),
                   "major" if inp > INP_POOR_MS else "minor", 0.9, ev,
                   f"Interaction to Next Paint is {inp:.0f} ms against a {INP_GOOD_MS} ms "
                   f"target. Break up long JavaScript tasks and defer non-essential work "
                   f"so the main thread can respond to taps.")


@check("ON-088", scope="psi")
def check_page_speed_impact(psi: Any) -> Verdict:
    """ON-088 - the headline performance score, with what is behind it."""
    if (na := _no_psi(psi)) is not None:
        return na
    perf = (getattr(psi, "lighthouse_scores", {}) or {}).get("performance")
    opps = list(getattr(psi, "opportunities", []) or [])
    top = sorted(opps, key=lambda o: -(o.get("numericValue") or 0))[:3]
    ev = {"performance_score": perf,
          "opportunity_count": len(opps),
          "top_opportunities": [
              {"id": o.get("id"), "title": o.get("title"),
               "savings_ms": o.get("numericValue")} for o in top]}
    if perf is None:
        return Verdict("n_a", 0.0, "info", 0.0,
                       {**ev, "reason": "no performance score returned"})
    if perf >= 90:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    names = ", ".join(o.get("title") or o.get("id") or "?" for o in top) or "several audits"
    return Verdict("fail" if perf < 50 else "warn",
                   round(perf / 10.0, 1),
                   "major" if perf < 50 else "minor", 0.9, ev,
                   f"Lighthouse performance is {perf:.0f}/100. The largest wins available "
                   f"are: {names}.")


@check("TECH-044", scope="psi")
def check_page_speed_optimization(psi: Any) -> Verdict:
    """TECH-044 - how much time the listed opportunities would actually save.

    Distinct from ON-088: that reports the score, this reports the work.
    """
    if (na := _no_psi(psi)) is not None:
        return na
    opps = list(getattr(psi, "opportunities", []) or [])
    total = sum((o.get("numericValue") or 0) for o in opps)
    worth = [o for o in opps if (o.get("numericValue") or 0) >= SAVINGS_WORTH_REPORTING_MS]
    ev = {"opportunity_count": len(opps),
          "total_estimated_savings_ms": round(total),
          "opportunities_worth_acting_on": len(worth),
          "reporting_floor_ms": SAVINGS_WORTH_REPORTING_MS,
          "items": [{"id": o.get("id"), "savings_ms": o.get("numericValue")}
                    for o in sorted(worth, key=lambda o: -(o.get("numericValue") or 0))[:5]]}
    if not opps:
        return Verdict("pass", 10.0, "info", 0.9,
                       {**ev, "note": "Lighthouse lists no performance opportunities"})
    if not worth:
        return Verdict("pass", 9.0, "info", 0.9,
                       {**ev, "note": f"all opportunities are below the {SAVINGS_WORTH_REPORTING_MS} ms "
                                      f"reporting floor and sit inside measurement noise"})
    return Verdict("fail" if total > 3000 else "warn",
                   max(0.0, 10.0 - total / 500.0),
                   "major" if total > 3000 else "minor", 0.9, ev,
                   f"{len(worth)} performance opportunities together estimate "
                   f"{round(total / 1000, 1)}s of savings. Start with "
                   f"{ev['items'][0]['id']}.")


# --------------------------------------------------------------------------
# Mobile
# --------------------------------------------------------------------------

def _mobile_verdict(psi: Any, *, technical: bool) -> Verdict:
    """Shared body: viewport, legible text, tap targets, content width.

    Google retired the standalone Mobile-Friendly Test in 2023 because the
    index is mobile-only - every page is judged on its mobile rendering, so
    these are not optional extras.
    """
    if (na := _no_psi(psi)) is not None:
        return na
    if getattr(psi, "strategy", "mobile") != "mobile":
        return Verdict("n_a", 0.0, "info", 0.5,
                       {"reason": f"PageSpeed was run with strategy "
                                  f"{getattr(psi, 'strategy', '?')!r}; mobile friendliness "
                                  f"needs the mobile strategy"})
    checks = {}
    unavailable = []
    for group in (VIEWPORT, FONT_SIZE, TAP_TARGETS, CONTENT_WIDTH):
        aid, a = _audit(psi, group)
        if a is None:
            unavailable.append(group[0])
            continue
        if a.get("scoreDisplayMode") == NOT_APPLICABLE:
            checks[aid] = None
            continue
        checks[aid] = a.get("score")
    ev = {"audits": checks, "strategy": getattr(psi, "strategy", None),
          "audits_not_in_this_lighthouse": unavailable,
          "context": "Google's index is mobile-only since 2023; the standalone "
                     "Mobile-Friendly Test was retired because of it. Lighthouse 12 "
                     "removed font-size, tap-targets and content-width, so what can "
                     "be measured here depends on the Lighthouse version PSI ran."}
    graded = {k: v for k, v in checks.items() if isinstance(v, (int, float))}
    if not graded:
        return Verdict("n_a", 0.0, "info", 0.0,
                       {**ev, "reason": "Lighthouse returned no mobile usability audits"})
    failing = [k for k, v in graded.items() if v < 0.9]
    if not failing:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    # `failing` holds RESOLVED audit ids, while the constants are tuples of the
    # ids that have carried each measurement across Lighthouse versions.
    detail = {
        VIEWPORT: "no usable viewport meta tag, so the page renders at desktop width",
        FONT_SIZE: "text too small to read without zooming",
        TAP_TARGETS: "tap targets too small or too close together",
        CONTENT_WIDTH: "content wider than the viewport, forcing horizontal scrolling",
    }
    critical = any(f in VIEWPORT for f in failing)
    problems = "; ".join(
        text for group, text in detail.items() if any(f in group for f in failing)
    )
    return Verdict("fail" if critical else "warn",
                   max(0.0, 10.0 - 3.0 * len(failing)),
                   "critical" if critical else "major", 0.9, ev,
                   f"Mobile usability problems: {problems}. Google indexes the mobile "
                   f"rendering of this page, so these affect every ranking, not just "
                   f"mobile ones.")


@check("TECH-063", scope="psi")
def check_mobile_friendliness_technical(psi: Any) -> Verdict:
    """TECH-063 - mobile friendliness, technical pillar."""
    return _mobile_verdict(psi, technical=True)


@check("ON-082", scope="psi")
def check_mobile_friendliness_on_page(psi: Any) -> Verdict:
    """ON-082 - the same measurement seen from the on-page pillar."""
    v = _mobile_verdict(psi, technical=False)
    return Verdict(v.status, v.score, v.severity, v.confidence,
                   {**v.evidence, "note": "same Lighthouse audits as TECH-063, reported "
                                          "under the on-page pillar"},
                   v.remediation, v.references)


@check("TECH-064", scope="psi")
def check_mobile_usability_issues(psi: Any) -> Verdict:
    """TECH-064 - the individual usability audits, itemised.

    TECH-063 answers "is it mobile friendly". This answers "what exactly is
    wrong", which is the difference between a score and a work order.
    """
    if (na := _no_psi(psi)) is not None:
        return na
    rows = []
    graded = 0
    for group in (VIEWPORT, FONT_SIZE, TAP_TARGETS, CONTENT_WIDTH):
        aid, a = _audit(psi, group)
        if a is None or a.get("scoreDisplayMode") == NOT_APPLICABLE:
            continue
        score = a.get("score")
        if not isinstance(score, (int, float)):
            continue
        graded += 1
        if score < 0.9:
            rows.append({"audit": aid, "score": score,
                         "display": a.get("displayValue"), "items": a.get("items")})
    ev = {"failing_audits": rows, "failing_count": len(rows),
          "audits_graded": graded}
    if not (getattr(psi, "audits", {}) or {}):
        return Verdict("n_a", 0.0, "info", 0.0, {**ev, "reason": "no audits array"})
    if graded == 0:
        # "No failures found" and "nothing was measured" are different things.
        return Verdict("n_a", 0.0, "info", 0.0,
                       {**ev, "reason": "this Lighthouse version returned none of the "
                                        "mobile usability audits, so nothing was measured"})
    if not rows:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    return Verdict("fail" if len(rows) > 1 else "warn",
                   max(0.0, 10.0 - 3.0 * len(rows)),
                   "major", 0.9, ev,
                   f"{len(rows)} mobile usability audits fail: "
                   f"{', '.join(r['audit'] for r in rows)}.")
