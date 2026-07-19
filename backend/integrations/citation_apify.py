"""Apify fallback engine (7B-4): an OCCASIONAL FALLBACK for a directory the
self-hosted Playwright bot cannot yet reach (no ``FormSpec``, or repeatedly
failing) - NOT the default engine. The reference plan's own cost model puts an
Apify Citation Builder actor run at ~$0.25/citation (its documented per-event
pricing: audited $0.05 + submitted $0.25 + aggregator push $0.50), roughly 2.5x the
self-hosted bot and far above a direct-API write; it earns its place only where
self-hosting genuinely cannot cover a directory yet, per the user's own call on
this build's engine strategy (self-hosted primary, Apify fallback).

Satisfies the SAME ``CitationSubmitter`` Protocol as the direct-API and Playwright
engines, so the worker's dispatch never special-cases it - a directory row simply
has ``submit_method="apify"`` instead of ``"bot:playwright"`` or ``"api:..."``.
"""

from __future__ import annotations

import time

from app.config import Settings
from app.logging_setup import get_logger
from integrations.citation_submitters import CitationJob, CitationSubmitResult
from integrations.errors import ProviderCallError, ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

logger = get_logger("integrations.citation_apify")

_INSTALL_HINT = "set APIFY_API_TOKEN + APIFY_CITATION_ACTOR_ID to enable the Apify fallback engine"


class ApifyCitationSubmitter(HttpProviderClient):
    """Real ``CitationSubmitter`` running an Apify actor synchronously (start the
    run, then poll) per submission."""

    provider = "apify"
    _POLL_INTERVAL_SECONDS = 3.0
    _POLL_TIMEOUT_SECONDS = 180.0

    def __init__(self, *, api_token: str, actor_id: str, timeout: float = 30.0) -> None:
        if not api_token or not actor_id:
            raise ProviderNotConfiguredError(f"Apify citation fallback unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://api.apify.com/v2",
            headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        self._actor_id = actor_id

    def submit(self, job: CitationJob) -> CitationSubmitResult:
        run_input = {
            "directory": job.directory_name,
            "directoryUrl": job.directory_url,
            "business": {
                "name": job.business_name,
                "address1": job.address_line1,
                "address2": job.address_line2,
                "city": job.city,
                "region": job.region,
                "postalCode": job.postal_code,
                "phone": job.phone,
                "website": job.website_url,
                "categories": list(job.categories),
            },
        }
        try:
            started = self.request_json("POST", f"/acts/{self._actor_id}/runs", json_body=run_input)
        except ProviderCallError as exc:
            return CitationSubmitResult(status="failed", error=str(exc))
        run = started.get("data") or {}
        run_id = run.get("id")
        if not run_id:
            return CitationSubmitResult(status="failed", error="Apify run response missing id")
        return self._poll(str(run_id))

    def _poll(self, run_id: str) -> CitationSubmitResult:
        deadline = time.monotonic() + self._POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                data = self.request_json("GET", f"/actor-runs/{run_id}")
            except ProviderCallError as exc:
                return CitationSubmitResult(status="failed", error=str(exc))
            run = data.get("data") or {}
            status = run.get("status")
            if status == "SUCCEEDED":
                output = run.get("output") or {}
                return CitationSubmitResult(
                    status="submitted",
                    proof_url=str(output.get("proofUrl") or ""),
                    external_ref=str(output.get("externalRef") or run_id),
                )
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                return CitationSubmitResult(status="failed", error=f"Apify run ended {status}")
            time.sleep(self._POLL_INTERVAL_SECONDS)
        return CitationSubmitResult(status="failed", error=f"Apify run {run_id} did not finish in time")


def apify_submitter_from_settings(settings: Settings) -> ApifyCitationSubmitter | None:
    """The fallback engine when both an API token and an actor id are configured,
    else ``None`` (degraded - a directory routed to ``apify`` HOLDS rather than
    crashing the worker)."""
    token = settings.apify_api_token
    actor_id = settings.apify_citation_actor_id
    if not token or not actor_id:
        logger.info("apify_submitter_degraded", reason="missing_token_or_actor_id")
        return None
    return ApifyCitationSubmitter(api_token=token.get_secret_value(), actor_id=actor_id)
