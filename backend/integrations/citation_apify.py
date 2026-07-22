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

    def __init__(
        self,
        *,
        api_token: str,
        actor_id: str,
        timeout: float = 30.0,
        captcha_provider: str = "",
        captcha_api_key: str = "",
    ) -> None:
        if not api_token or not actor_id:
            raise ProviderNotConfiguredError(f"Apify citation fallback unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://api.apify.com/v2",
            headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        self._actor_id = actor_id
        self._captcha_provider = captcha_provider
        self._captcha_api_key = captcha_api_key

    def submit(self, job: CitationJob) -> CitationSubmitResult:
        # The Citation Builder actor's REAL input schema
        # (apify.com/alizarin_refrigerator-owner/citation-builder): flattened NAP
        # fields + mode. `demoMode` DEFAULTS TRUE on the actor, so it must be
        # explicitly disabled or every "submission" is a sample run that builds
        # nothing. mode="submit" = audit + auto-fill of fillable directories
        # ("full" additionally needs Data Axle/Yext/BrightLocal aggregator keys we
        # do not hold). `directories` pins the run to THIS row's directory - the
        # worker dispatches one row at a time.
        run_input: dict[str, object] = {
            "mode": "submit",
            "demoMode": False,
            "enableAiAnalysis": False,
            "verifyAfterSubmit": False,
            "businessName": job.business_name,
            "streetAddress": job.address_line1,
            "city": job.city,
            "state": job.region,
            "zipCode": job.postal_code,
            "phone": job.phone,
            "website": job.website_url,
            "categories": list(job.categories),
            "directories": [job.directory_name],
            "maxConcurrent": 1,
        }
        if self._captcha_provider and self._captcha_api_key:
            run_input["captchaSolverProvider"] = self._captcha_provider
            run_input["captchaSolverApiKey"] = self._captcha_api_key
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
                return self._result_from_dataset(run_id, str(run.get("defaultDatasetId") or ""))
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                return CitationSubmitResult(status="failed", error=f"Apify run ended {status}")
            time.sleep(self._POLL_INTERVAL_SECONDS)
        return CitationSubmitResult(status="failed", error=f"Apify run {run_id} did not finish in time")

    def _result_from_dataset(self, run_id: str, dataset_id: str) -> CitationSubmitResult:
        """Read the run's DATASET (where this actor writes results - actor runs have
        no `output` field) and extract the submission outcome + live listing URL.
        Tolerant of item-shape drift: any URL-ish field counts as the proof link, and
        an explicit failed/error status on the item is reported honestly."""
        if not dataset_id:
            return CitationSubmitResult(status="submitted", external_ref=run_id)
        try:
            # The items endpoint returns a JSON ARRAY, which the shared
            # ``request_json`` (dict-only contract) rejects — read it raw. A failed
            # read still reports the submission; it just carries no proof link.
            response = self._client.request(
                "GET", f"/datasets/{dataset_id}/items", params={"format": "json"}
            )
            items: object = response.json() if response.status_code < 400 else []
        except Exception:
            # The run succeeded; only the result read failed - still a submission.
            return CitationSubmitResult(status="submitted", external_ref=run_id)
        rows = items if isinstance(items, list) else (items.get("items") or []) if isinstance(items, dict) else []
        for item in rows:
            if not isinstance(item, dict):
                continue
            nested = item.get("results")
            candidates = nested if isinstance(nested, list) else [item]
            for c in candidates:
                if not isinstance(c, dict):
                    continue
                status = str(c.get("status") or c.get("submissionStatus") or "").lower()
                url = str(
                    c.get("liveUrl") or c.get("listingUrl") or c.get("proofUrl")
                    or c.get("submissionUrl") or c.get("url") or ""
                )
                if status in ("failed", "error", "skipped"):
                    reason = str(c.get("error") or c.get("message") or f"directory {status}")
                    return CitationSubmitResult(status="failed", error=reason)
                if status or url:
                    return CitationSubmitResult(
                        status="verified" if status == "verified" else "submitted",
                        proof_url=url,
                        external_ref=str(c.get("externalRef") or c.get("id") or run_id),
                    )
        return CitationSubmitResult(status="submitted", external_ref=run_id)


def apify_submitter_from_settings(settings: Settings) -> ApifyCitationSubmitter | None:
    """The fallback engine when both an API token and an actor id are configured,
    else ``None`` (degraded - a directory routed to ``apify`` HOLDS rather than
    crashing the worker). The CAPTCHA solver credentials ride along when present -
    the actor drives CAPTCHA-gated directories itself."""
    token = settings.apify_api_token
    actor_id = settings.apify_citation_actor_id
    if not token or not actor_id:
        logger.info("apify_submitter_degraded", reason="missing_token_or_actor_id")
        return None
    captcha_key = (
        settings.captcha_solver_api_key.get_secret_value() if settings.captcha_solver_api_key else ""
    )
    return ApifyCitationSubmitter(
        api_token=token.get_secret_value(),
        actor_id=actor_id,
        captcha_provider=settings.captcha_solver_provider if captcha_key else "",
        captcha_api_key=captcha_key,
    )
