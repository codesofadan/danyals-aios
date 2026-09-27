"""Did we actually get to look at this site? The one question an audit must answer first.

THE FAILURE THIS CLOSES. A site behind Cloudflare, basic auth, a staging password or an
aggressive firewall answers our crawler with 403s and nothing else. The run completes
normally: the engine emits what it could, the ingest stores it, coverage is honestly low,
the score is honestly null - and the report reads like a THIN audit of a simple site
rather than a FAILED look at a locked one. Every individual number is defensible and the
document as a whole says something false.

It is the most likely way a client-facing report misleads, because nothing about it looks
broken. The scores are absent for the right reason, the page list is short for the right
reason, and there is no single place that says "we were refused".

WHAT THIS DECIDES, and the vocabulary is deliberately three words rather than a
percentage:

    ok        we crawled enough of the site to say something about it
    thin      we reached far fewer pages than we set out to - report it, do not explain it
    blocked   the site refused us; the findings describe our access, not their SEO

`blocked` is the one that changes what may be said to a client, so its test is the strict
one: a MAJORITY of the pages we touched came back refused (401/403/429/451) or unreachable,
or we could not fetch more than a single page of a site we planned to crawl properly.
Anything weaker stays `thin`, because "your site blocked us" is an accusation and it should
be made only when the evidence is unambiguous.

Pure: no database, no network, no clock. Pages in, verdict out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Statuses that mean "we were refused", as distinct from "it is not there" (404) or
#: "their server broke" (5xx). Only refusal supports a `blocked` verdict: a site full of
#: 404s is a real, reportable finding about the site, not a wall in front of us.
REFUSED_STATUSES: frozenset[int] = frozenset({401, 403, 429, 451})

#: Share of touched pages that must be refusals before we will say `blocked`.
BLOCKED_SHARE = 0.5

#: Below this share of the planned crawl we call the run `thin`. Not a failure and not an
#: accusation - a statement that the audit saw a fraction of what it aimed at.
THIN_SHARE = 0.25

#: A planned crawl smaller than this is not evidence of anything: a 3-page quote for a
#: 3-page site that returned 2 pages is a complete audit, not a thin one.
MIN_PLANNED_FOR_THIN = 8


@dataclass(frozen=True, slots=True)
class CrawlHealth:
    """What we were able to see, and the sentence to print when it was not enough."""

    verdict: str  # ok | thin | blocked
    note: str
    fetched: int = 0
    refused: int = 0
    planned: int = 0

    @property
    def is_clean(self) -> bool:
        return self.verdict == "ok"


def assess(pages: list[dict[str, Any]], *, planned: int = 0) -> CrawlHealth:
    """Judge one run's crawl from its own page rows.

    ``pages`` are the ingested page records (each with an ``http_status``, absent or None
    when the fetch never produced a response). ``planned`` is the page budget the run was
    created with, which is what makes "we got 3 pages" interpretable: 3 of 3 is complete
    and 3 of 300 is not.

    Returns ``ok`` with an empty note whenever there is nothing to report - the common
    case, and the one where a banner would be noise.
    """
    touched = len(pages)
    if touched == 0:
        # Nothing at all. This is the strongest possible evidence and the least
        # ambiguous: there is no audit here, whatever else the artifacts contain.
        return CrawlHealth(
            verdict="blocked",
            note=(
                "No page of this site could be fetched, so the findings below describe "
                "what we were able to reach - not the site itself. The usual causes are a "
                "firewall or bot protection refusing our crawler, a password-protected "
                "staging site, or a domain that no longer serves."
            ),
            fetched=0,
            refused=0,
            planned=planned,
        )

    refused = sum(
        1 for p in pages
        if _status(p) in REFUSED_STATUSES or _status(p) == 0
    )
    fetched = touched - refused
    share_refused = refused / touched

    # BLOCKED REQUIRES REFUSALS. A small site is not a blocked one, and the first version of
    # this rule also said `fetched <= 1 and planned >= 8` - which called a REAL one-page
    # audit of example.com "blocked" on its first live run, because the page budget was 15
    # and the site has one page. That is the accusation this module's own docstring warns
    # against making on weak evidence: a 200 response is not a wall. So the only two things
    # that support `blocked` are a majority of REFUSALS and a crawl that fetched nothing at
    # all (handled above); a small fetch against a large budget is `thin`.
    if share_refused >= BLOCKED_SHARE:
        return CrawlHealth(
            verdict="blocked",
            note=(
                f"{refused} of the {touched} pages we requested were refused or "
                "unreachable, so this audit describes the part of the site we could "
                "reach. Bot protection, an IP block or an access-restricted environment "
                "will produce this. Re-run once our crawler is allowed through, and treat "
                "the findings below as provisional until then."
            ),
            fetched=fetched,
            refused=refused,
            planned=planned,
        )

    if planned >= MIN_PLANNED_FOR_THIN and fetched < planned * THIN_SHARE:
        return CrawlHealth(
            verdict="thin",
            note=(
                f"This run reached {fetched} page{'' if fetched == 1 else 's'} of a "
                f"planned {planned}. That can simply "
                "mean the site is smaller than the budget allowed - or that a sitemap, a "
                "robots rule or an internal-linking gap kept the rest out of reach. The "
                "findings cover the pages listed; they do not cover what was not seen."
            ),
            fetched=fetched,
            refused=refused,
            planned=planned,
        )

    return CrawlHealth(verdict="ok", note="", fetched=fetched, refused=refused, planned=planned)


def _status(page: dict[str, Any]) -> int:
    """A page's HTTP status as an int, with 0 meaning "no response at all"."""
    raw = page.get("http_status")
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0
