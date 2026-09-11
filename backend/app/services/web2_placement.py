"""Extension-assisted Web 2.0 placement (0136, off-page redesign Phase 7).

WHAT THIS SERVICE HOLDS. The pure half of the placement lane: which draft values the
extension offers as copy-blocks, which selectors an EARNED spec licenses it to fill,
and the server-side verdict on an operator's pasted public URL. The router owns the
orchestration (SSRF guard, fetch, DB writes, session hook) exactly as the citation
complete route does; everything here is testable without a network or a database.

THE EVIDENCE RULE, same as everywhere else in the module: an operator saying "I
published it, here is the URL" is a claim. The server fetches that URL itself, checks
the page lives on the PLATFORM'S OWN HOST (a pasted URL on any other host is refused,
however plausible it looks), and looks for the client's target link on the page with
the same ``inspect_html`` the publish worker and the recheck sweep use. Only then does
the property become ``published`` - and a refusal advances nothing.

FAIL-CLOSED AUTOFILL. ``spec_selectors`` returns {} unless an ACTIVE placement spec
provides plain-selector fields; with no selectors the extension shows copy-blocks
only. It never fills contenteditable on a guess and never submits - the operator
publishes in their own logged-in session, and the human is the submit button.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.services.web2_linkcheck import LinkCheck, inspect_html

#: The same honest, non-masquerading UA the web2 link workers present.
PLACEMENT_PROBE_UA = "Mozilla/5.0 (compatible; AIOS-linkcheck/1.0)"

#: The draft values a placement can offer, in default order: (key, label, row column).
#: ``tags`` is deliberately absent - web2_properties stores no tags column, and a
#: fabricated tag list would be the panel inventing content. A spec's copy_blocks may
#: reorder/relabel these keys but can never conjure a value the draft does not hold.
_DEFAULT_COPY_BLOCKS: tuple[tuple[str, str, str], ...] = (
    ("title", "Title", "topic"),
    ("body", "Body (Markdown)", "body_md"),
    ("anchor", "Anchor text", "anchor"),
    ("target_url", "Link target", "target_url"),
)


def copy_blocks_for(
    row: dict[str, Any], spec: dict[str, Any] | None = None
) -> list[dict[str, str]]:
    """``[{key, label, value}]`` for one approved draft - the paste-ready payload.

    An ACTIVE spec's ``copy_blocks`` (``[{key, label}]``) controls order and labels;
    without one the default block set applies. Either way a block only exists when the
    draft actually holds a non-empty value for it - an empty copy button teaches an
    operator to ignore the panel."""
    values = {key: str(row.get(col) or "").strip() for key, _, col in _DEFAULT_COPY_BLOCKS}
    labels = {key: label for key, label, _ in _DEFAULT_COPY_BLOCKS}

    ordered: list[tuple[str, str]] = []
    declared = (spec or {}).get("copy_blocks")
    if isinstance(declared, list) and declared:
        for entry in declared:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or "")
            if key not in values:
                continue  # a spec cannot conjure a value the draft does not hold
            ordered.append((key, str(entry.get("label") or "") or labels[key]))
    if not ordered:
        ordered = [(key, labels[key]) for key, _, _ in _DEFAULT_COPY_BLOCKS]

    return [
        {"key": key, "label": label, "value": values[key]}
        for key, label in ordered
        if values[key]
    ]


def spec_selectors(spec: dict[str, Any] | None) -> dict[str, str]:
    """``{value_key: selector}`` from an ACTIVE placement spec's optional ``fields``.

    Empty is the fail-closed default: no spec, a spec without fields, or malformed
    entries all yield {} - and {} is what keeps the extension on copy-blocks."""
    if not spec:
        return {}
    fields = spec.get("fields")
    if not isinstance(fields, list):
        return {}
    out: dict[str, str] = {}
    for entry in fields:
        if not isinstance(entry, dict):
            continue
        selector = str(entry.get("selector") or "").strip()
        value_key = str(entry.get("value_key") or "").strip()
        if selector and value_key:
            out[value_key] = selector
    return out


def editor_url_for(spec: dict[str, Any] | None, platform_row: dict[str, Any] | None) -> str:
    """Where the extension's Open button points.

    An ACTIVE spec's host-pinned ``editor_url`` wins (it was verified against the live
    editor); otherwise the platform's own homepage - honest, the operator navigates to
    the editor themselves - and '' when even that is unknown."""
    if spec:
        url = str(spec.get("editor_url") or "").strip()
        if url:
            return url
    if platform_row:
        return str(platform_row.get("homepage_url") or "").strip()
    return ""


# --------------------------------------------------------------------------- #
# The completion verdict (pure).
# --------------------------------------------------------------------------- #
def host_of(url: str) -> str:
    """Lowercased host of ``url``: port and leading ``www.`` stripped, '' when the
    URL has no usable host. The Python-side mirror of the DB's ``_spec_host_of``
    normalisation, used to compare a fetched page's host against the platform's."""
    if not url:
        return ""
    try:
        host = urlsplit(url.strip()).hostname or ""
    except ValueError:
        return ""
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def host_belongs_to(page_host: str, platform_host: str) -> bool:
    """Equal, or a DOT-ANCHORED subdomain - ``blog.medium.com`` belongs to
    ``medium.com``; ``evil-medium.com`` does not."""
    if not page_host or not platform_host:
        return False
    return page_host == platform_host or page_host.endswith("." + platform_host)


@dataclass(frozen=True)
class PlacementVerdict:
    """The server's answer to "is this pasted URL really our placement?"."""

    accepted: bool
    reason: str = ""
    link: LinkCheck = field(default_factory=LinkCheck)


def judge_placement(
    html: str | None,
    final_url: str,
    *,
    platform_host: str,
    target_url: str,
) -> PlacementVerdict:
    """Pure verdict over a fetched page. Refusals name the failing check.

    ``final_url`` is the post-redirect URL - the host that actually answered, so a
    redirector off the platform is caught even when the pasted URL looked right."""
    if not platform_host:
        return PlacementVerdict(
            False,
            "This platform has no recorded homepage host to verify against - record "
            "its homepage_url in the catalogue first.",
        )
    if html is None:
        return PlacementVerdict(
            False,
            "That page could not be fetched. If it was just published, wait for it to "
            "become publicly visible and try again.",
        )
    page_host = host_of(final_url)
    if not host_belongs_to(page_host, platform_host):
        return PlacementVerdict(
            False,
            f"That page lives on {page_host or 'an unknown host'}, not on the "
            f"platform's own host ({platform_host}).",
        )
    link = inspect_html(html, target_url)
    if link.state != "found":
        return PlacementVerdict(
            False,
            link.detail
            or "The client's target link was not found on that page.",
            link=link,
        )
    return PlacementVerdict(True, link=link)


def fetch_placement_page(url: str, *, max_redirects: int = 5) -> tuple[str | None, str]:
    """GET a pasted placement URL with the honest UA. Returns ``(html, final_url)``;
    ``(None, '')`` on any failure. NEVER raises - "could not look" must stay
    distinguishable from "looked and it is not there".

    REDIRECTS ARE FOLLOWED MANUALLY, EVERY HOP SSRF-RE-VALIDATED (the
    ``EvidenceFetcher`` pattern in ``workers/tasks/offpage.py``, per the plan §8
    contract). ``follow_redirects=True`` would issue the GET to a redirect target
    BEFORE any check ran - a public URL 302ing to the metadata service or an internal
    admin endpoint would be fetched server-side even though the body was later
    refused on ``final_url``. Refusing the hop *before* the request is the only
    ordering that prevents the blind SSRF. Callers still SSRF-validate ``url`` and
    the returned ``final_url`` - harmless defence in depth."""
    import httpx

    from app.core.security import is_public_url

    current = url
    for _hop in range(max_redirects + 1):
        # Re-validated EVERY hop: a redirect target is as attacker-controllable as
        # the pasted URL itself (TOCTOU / rebinding contract in app/core/security.py).
        if not is_public_url(current):
            return None, ""
        try:
            with httpx.Client(
                timeout=20.0,
                follow_redirects=False,
                headers={"User-Agent": PLACEMENT_PROBE_UA},
            ) as client:
                resp = client.get(current)
        except Exception:
            # No exception body in logs-or-messages: a URL can carry a token in a query.
            return None, ""
        location = resp.headers.get("location", "")
        if resp.status_code in (301, 302, 303, 307, 308) and location:
            current = str(httpx.URL(current).join(location))
            continue
        if resp.status_code >= 400:
            return None, current
        return resp.text[:1_500_000], current
    return None, ""
