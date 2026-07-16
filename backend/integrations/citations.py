"""Citation-monitoring seam (7B): the ONLY door to a business's local directory /
NAP listings.

Local off-page monitoring checks a business's listings across the citation
directories (Google Business, Yelp, Apple Maps, data aggregators, ...) and reports,
per directory, whether the Name/Address/Phone is ``consistent``, has drifted
(``inconsistent``), or is ``missing`` entirely - which drives the Submit-vs-Update
action. Reachable through the ``CitationProvider`` Protocol so a later monitoring
chunk can wrap it in a cost-gated ingest; nothing else calls the provider directly.

Two impls satisfy the Protocol, mirroring the content/backlink seams exactly:

* ``BrightLocalCitations`` - real, backed by a BrightLocal / Whitespark-style
  citation-tracker API over the shared sync ``HttpProviderClient`` (retry/backoff;
  the key rides in an ``api-key`` header, never a URL or a log line). Key-gated on
  ``BRIGHTLOCAL_API_KEY``; an empty key -> ``ProviderNotConfiguredError`` naming the
  fix.
* ``FakeCitationProvider`` - deterministic, network-free: sha256(business) -> a
  stable spread of directories across all three NAP states, so tests + degraded runs
  are reproducible with zero keys.

``classify_citation`` is the shared verdict (not found -> ``missing``; found but NAP
mismatch -> ``inconsistent``; found + match -> ``consistent``) so the DB
``nap_status`` is derived one way from every source.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.config import Settings
from app.logging_setup import get_logger
from integrations.errors import ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

logger = get_logger("integrations.citations")

_INSTALL_HINT = "set BRIGHTLOCAL_API_KEY to enable live citation / NAP monitoring"
_BRIGHTLOCAL_BASE = "https://api.brightlocal.com"

# The directories a local citation audit walks (a representative core set).
_CORE_DIRECTORIES = (
    "Google Business",
    "Yelp",
    "Bing Places",
    "Apple Maps",
    "Yellow Pages",
    "Facebook",
)


@dataclass(frozen=True)
class CitationRecord:
    """One directory listing from any source. ``nap_status`` is DERIVED via
    ``classify_citation`` (never trusted raw); ``note`` records what drifted or a
    listing detail."""

    directory: str
    nap_status: str
    note: str = ""


def classify_citation(*, found: bool, nap_matches: bool) -> str:
    """The NAP verdict for a directory: no listing -> ``missing``; a listing whose
    NAP has drifted -> ``inconsistent``; a listing that matches -> ``consistent``."""
    if not found:
        return "missing"
    return "consistent" if nap_matches else "inconsistent"


@runtime_checkable
class CitationProvider(Protocol):
    """Fetch a business's directory listings as ``CitationRecord``s.

    ``business`` identifies the client (name or a business id the provider resolves).
    """

    def fetch_citations(self, business: str, *, limit: int = 50) -> list[CitationRecord]: ...


class BrightLocalCitations(HttpProviderClient):
    """Real ``CitationProvider`` over a BrightLocal-style citation-tracker API.

    The key rides in the ``api-key`` header (never a URL, never a log line). The
    caller (the factory / service layer) supplies it.
    """

    provider = "brightlocal_citations"

    def __init__(self, *, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"BrightLocal citations unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url=_BRIGHTLOCAL_BASE,
            headers={"api-key": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )

    def fetch_citations(self, business: str, *, limit: int = 50) -> list[CitationRecord]:
        data = self.request_json(
            "GET", "/v4/ct/results", params={"business": business, "limit": limit}
        )
        return [_record_from_brightlocal(item) for item in _brightlocal_items(data)]


def _brightlocal_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the listing rows out of a BrightLocal envelope defensively."""
    results = data.get("results")
    if isinstance(results, dict):
        results = results.get("citations")
    return [item for item in (results or []) if isinstance(item, dict)]


def _record_from_brightlocal(item: dict[str, Any]) -> CitationRecord:
    """Map one BrightLocal listing to a ``CitationRecord`` (NAP status derived)."""
    found = bool(item.get("found", item.get("listing_url")))
    nap_matches = bool(item.get("nap_match", item.get("is_consistent")))
    return CitationRecord(
        directory=str(item.get("directory") or item.get("source") or ""),
        nap_status=classify_citation(found=found, nap_matches=nap_matches),
        note=str(item.get("note") or item.get("issue") or ""),
    )


class FakeCitationProvider:
    """Deterministic, offline ``CitationProvider`` - sha256(business) -> a stable
    spread of directories across all three NAP states.

    Same business => identical records; different businesses differ. The set always
    contains at least one of each state so monitoring tests exercise every branch
    with zero keys.
    """

    def fetch_citations(self, business: str, *, limit: int = 50) -> list[CitationRecord]:
        digest = hashlib.sha256(business.encode()).hexdigest()
        states = ("consistent", "inconsistent", "missing")
        notes = {
            "consistent": "Verified",
            "inconsistent": "Suite # differs",
            "missing": "No listing yet",
        }
        records: list[CitationRecord] = []
        for i, directory in enumerate(_CORE_DIRECTORIES[:limit]):
            # First three directories are pinned one-per-state (guarantees coverage);
            # the rest are digest-assigned for stable variety.
            nap = (
                states[i]
                if i < len(states)
                else states[int(digest[i * 2 : i * 2 + 2] or "0", 16) % 3]
            )
            records.append(
                CitationRecord(directory=directory, nap_status=nap, note=notes[nap])
            )
        return records


def citation_provider_from_settings(settings: Settings) -> CitationProvider | None:
    """The real BrightLocal provider when its key is present, else ``None``
    (degraded - live citation monitoring is off until the key lands). Mirrors
    ``content_providers_from_settings``: no secret is ever logged, only the reason."""
    key = settings.brightlocal_api_key
    if not key:
        logger.info("citation_provider_degraded", reason="missing_brightlocal_key")
        return None
    return BrightLocalCitations(api_key=key.get_secret_value())
