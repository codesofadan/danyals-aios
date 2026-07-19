"""Citation SUBMISSION seam (7B-4): the ONLY door to actually CREATING a new
citation-directory listing.

This is the missing half of ``integrations.citations``, which only MONITORS whether
a listing already exists (a BrightLocal-style read). Every directory in the catalog
(``public.directories``, seeded 0046) is tagged with a ``tier`` that names which
engine handles it - this module defines the shared contract every engine implements,
so the worker dispatches on ``tier`` without caring which concrete engine runs:

* ``api``               - a direct, documented write API (``integrations.citation_apis``).
* ``aggregator``        - a push to a data aggregator that fans out downstream (same
  module - an aggregator push and a direct API write share this Protocol).
* ``bot_fillable`` / ``captcha_assisted`` - a Playwright form-fill
  (``integrations.citation_bot``), the latter routed through a CAPTCHA solver first.
* Apify (``integrations.citation_apify``) is an OCCASIONAL FALLBACK engine satisfying
  the SAME Protocol - not the default (the reference plan's own cost model has
  self-hosted beating Apify ~2.5x per unit); a directory only routes there when the
  self-hosted engine is explicitly configured to defer to it.
* ``manual_only`` directories have NO engine and are never dispatched to a worker -
  they exist in the catalog purely for completeness/reporting.

``FakeCitationSubmitter`` is the deterministic, offline engine every worker/pipeline
test runs against with zero external accounts, mirroring ``FakeWeb2Publisher``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# Submission outcomes. 'blocked' is distinct from 'failed': a cost-gate hold or an
# explicit "this directory requires manual review" case, vs. an engine actually
# erroring out mid-submit.
CitationSubmitStatus = str  # 'submitted' | 'verified' | 'failed' | 'blocked'


@dataclass(frozen=True)
class CitationJob:
    """One directory submission to run: which directory + the canonical NAP to fill
    the form/API call with. ``external_ref`` set => this is an UPDATE of an existing
    listing (a directory-side id from a prior submission), not a fresh create."""

    directory_name: str
    directory_url: str
    market: str
    submit_method: str  # e.g. 'api:bing_places', 'aggregator:data_axle', 'bot:playwright'
    business_name: str
    address_line1: str
    address_line2: str
    city: str
    region: str
    postal_code: str
    phone: str
    website_url: str
    categories: tuple[str, ...] = field(default_factory=tuple)
    external_ref: str | None = None


@dataclass(frozen=True)
class CitationSubmitResult:
    """The outcome of one submission attempt. ``proof_url`` is a screenshot/receipt
    artifact a human can spot-check before the ledger is trusted as ``verified``
    (an API/aggregator submit may have no visual proof - an empty string is fine,
    the API's own 2xx response IS the proof for that method)."""

    status: CitationSubmitStatus
    proof_url: str = ""
    external_ref: str | None = None
    error: str = ""


@runtime_checkable
class CitationSubmitter(Protocol):
    """Submit (or update, when ``job.external_ref`` is set) one directory listing."""

    def submit(self, job: CitationJob) -> CitationSubmitResult: ...


class FakeCitationSubmitter:
    """Deterministic, offline ``CitationSubmitter`` for the pipeline + worker suites -
    sha256(directory|business) -> a stable proof url + external ref, so tests and a
    keyless/proxyless degraded run are reproducible with zero external accounts."""

    def submit(self, job: CitationJob) -> CitationSubmitResult:
        digest = hashlib.sha256(f"{job.directory_name}|{job.business_name}".encode()).hexdigest()
        return CitationSubmitResult(
            status="submitted",
            proof_url=f"https://fake-proof.example/{digest[:16]}",
            external_ref=job.external_ref or digest[:12],
        )
