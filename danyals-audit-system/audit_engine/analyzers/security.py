"""Signs that a page has been injected with something it did not ask for.

WHAT THIS IS NOT. It is not an antivirus scan, and it does not consult Google
Safe Browsing or any reputation feed. It reads the HTML that was crawled and
looks for the patterns that compromised sites actually carry. So it can be wrong
in both directions: a heavily minified analytics bundle can look like obfuscation,
and a careful injection can look like ordinary code.

WHY THAT MATTERS MORE HERE THAN ANYWHERE ELSE. "Your site has malware" is the
single most alarming sentence this audit can produce. Told wrongly, it sends an
owner to an emergency clean-up they did not need and costs the agency its
credibility; told softly, it misses a live compromise. So the bar is deliberately
asymmetric:

* ``fail`` needs TWO INDEPENDENT signals. One is a coincidence; two together are
  the shape of an injection.
* one signal is a ``warn`` that says what was seen and asks for a check, never
  "you have malware".
* the evidence always names the pattern that fired, so a developer can look at
  the same line and disagree.

Every threshold below is JUDGEMENT. There is no published standard for "how much
obfuscation is too much", because legitimate minifiers produce some of the same
shapes.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.registry import check
from audit_engine.crawlers.basic import CrawledPage

#: Long unbroken base64-ish runs inside a script. Minifiers produce long tokens,
#: but rarely 200+ characters of continuous base64 alphabet with no operators.
#: JUDGEMENT: 200 chosen because inlined SVG/font data URIs (the main innocent
#: source) are almost always attribute values, which are excluded below.
_B64_RUN = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")

#: The decode-and-run idioms. `eval` of a decoded string is the classic shape;
#: `document.write(unescape(` is the older one; `String.fromCharCode` in bulk is
#: how a payload is smuggled past a naive string search.
_DECODE_EXEC = (
    ("eval_of_decoded_string", re.compile(r"eval\s*\(\s*(?:atob|unescape|decodeURIComponent)\s*\(", re.I)),
    ("document_write_unescape", re.compile(r"document\.write\s*\(\s*unescape\s*\(", re.I)),
    ("bulk_fromcharcode", re.compile(r"(?:String\.fromCharCode\s*\(\s*\d+\s*,\s*\d+\s*,\s*\d+[^)]{60,}\))", re.I)),
    ("function_constructor_on_decoded", re.compile(r"(?:new\s+Function|Function)\s*\(\s*(?:atob|unescape)\s*\(", re.I)),
)

#: An iframe that is invisible. A legitimate hidden iframe exists (payment
#: bridges, some analytics), which is why this alone is never a `fail`.
_HIDDEN_IFRAME = re.compile(
    r"<iframe\b[^>]*(?:"
    r"(?:width|height)\s*=\s*[\"']?0[\"']?"
    r"|display\s*:\s*none"
    r"|visibility\s*:\s*hidden"
    r"|(?:top|left)\s*:\s*-\d{3,}px"
    r")[^>]*>", re.I,
)

#: Text pushed off-screen. Long a spam technique, and a common payload wrapper.
_OFFSCREEN_BLOCK = re.compile(
    r"style\s*=\s*[\"'][^\"']*(?:text-indent\s*:\s*-\d{4,}|left\s*:\s*-\d{4,}px)[^\"']*[\"']", re.I,
)

#: Scripts are stripped of their attributes before the base64 test, so inline
#: data-URI images and fonts (the main innocent source of long base64) do not
#: count as obfuscation.
_SCRIPT_BODY = re.compile(r"<script\b[^>]*>(.*?)</script>", re.I | re.S)
_ATTR = re.compile(r'\w+\s*=\s*"[^"]*"|\w+\s*=\s*\'[^\']*\'')


def _script_bodies(html: str) -> str:
    return "\n".join(_ATTR.sub("", m.group(1)) for m in _SCRIPT_BODY.finditer(html))


def _external_script_hosts(html: str, page_host: str) -> list[str]:
    hosts: list[str] = []
    for m in re.finditer(r"<script\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"']", html, re.I):
        host = (urlparse(m.group(1)).netloc or "").lower()
        if host and host != page_host:
            hosts.append(host)
    return hosts


@check("TECH-082", scope="page_http")
def malware(page: CrawledPage) -> Verdict:
    """TECH-082 - does this page carry the shape of an injection?"""
    html = page.html or ""
    if not html.strip():
        return Verdict(
            status="n_a", score=0.0, severity="info", confidence=1.0,
            evidence={"reason": "no HTML was retrieved for this page, so nothing could be scanned"},
        )

    bodies = _script_bodies(html)
    signals: list[str] = []

    for name, pattern in _DECODE_EXEC:
        if pattern.search(bodies):
            signals.append(name)
    if _B64_RUN.search(bodies):
        signals.append("long_encoded_blob_in_script")
    if _HIDDEN_IFRAME.search(html):
        signals.append("hidden_iframe")
    if _OFFSCREEN_BLOCK.search(html):
        signals.append("offscreen_positioned_block")

    page_host = (urlparse(page.final_url or page.url or "").netloc or "").lower()
    ev = {
        "signals_found": ", ".join(signals) if signals else "none",
        "signal_count": len(signals),
        "external_script_hosts": len(set(_external_script_hosts(html, page_host))),
        "method": "static pattern scan of the crawled HTML, not an antivirus or reputation check",
    }

    # TWO signals to accuse, one to ask. See the module docstring: the cost of
    # being wrong is not symmetric, and neither is the bar.
    if len(signals) >= 2:
        return Verdict(
            status="fail", score=0.0, severity="critical", confidence=0.6, evidence=ev,
            remediation=(
                f"This page carries {len(signals)} independent signs of injected code "
                f"({', '.join(signals)}). Have a developer read the inline scripts on "
                "this URL, compare the files against a known-good deploy, and rotate "
                "any credentials the site uses. This is a pattern match, not a virus "
                "scan - confirm before acting on it."
            ),
        )
    if signals:
        return Verdict(
            status="warn", score=6.0, severity="major", confidence=0.5, evidence=ev,
            remediation=(
                f"One pattern associated with injected code was found on this page "
                f"({signals[0]}). Minifiers and analytics bundles can produce the same "
                "shape, so this is worth a look rather than an alarm: check that the "
                "script is one you added."
            ),
        )
    return Verdict(status="pass", score=10.0, severity="info", confidence=0.5, evidence=ev)
