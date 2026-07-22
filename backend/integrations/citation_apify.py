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
from typing import Any

from app.config import Settings
from app.logging_setup import get_logger
from integrations.citation_submitters import CitationJob, CitationSubmitResult
from integrations.errors import ProviderCallError, ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

logger = get_logger("integrations.citation_apify")

_INSTALL_HINT = "set APIFY_API_TOKEN + APIFY_CITATION_ACTOR_ID to enable the Apify fallback engine"

# The actor's directory network, discovered from a live audit run 2026-07-23
# (48 names, item shape {directory, domain, category, priority, status}). The
# run's `directories` filter matches THESE names — our catalog's own names
# ("Bing Places for Business") silently match nothing, which burned a paid run
# that touched zero directories. Names are mapped below before every run.
_ACTOR_NETWORK: tuple[str, ...] = (
    "Google Business Profile", "Facebook", "Bing Places", "Apple Maps", "BBB",
    "Yellow Pages", "MapQuest", "SuperPages", "Foursquare", "LinkedIn", "Angi",
    "Nextdoor", "Healthgrades", "Citysearch", "Alignable", "Hotfrog",
    "ShowMeLocal", "CitySquares", "EZLocal", "LocalStack", "Spoke",
    "ChamberOfCommerce", "Tupalo", "USCity", "WhereTo", "GoLocal", "Hub.biz",
    "Fyple", "Local.com", "eLocal", "2FindLocal", "iBegin", "YellowBot",
    "Instagram", "Yelp", "Manta", "TripAdvisor", "Merchant Circle", "n49",
    "Zocdoc", "Brownbook", "Trustpilot", "Cybo", "Cylex", "FindUsLocal",
    "Vitals", "Kompass", "DexKnows",
)


def _norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


# Catalog-name → actor-name for the spellings a plain normalization can't bridge.
_NETWORK_ALIASES: dict[str, str] = {
    "bingplacesforbusiness": "Bing Places",
    "facebookbusinesspage": "Facebook",
    "facebookbusiness": "Facebook",
    "applebusinessconnect": "Apple Maps",
    "applemapsconnect": "Apple Maps",
    "betterbusinessbureau": "BBB",
    "betterbusinessbureaubbb": "BBB",
    "bbb": "BBB",
    "googlebusinessprofilegbp": "Google Business Profile",
    "angieslist": "Angi",
    "yellowpagescom": "Yellow Pages",
    "merchantcirclecom": "Merchant Circle",
}

_NETWORK_BY_NORM: dict[str, str] = {_norm(n): n for n in _ACTOR_NETWORK}


def actor_network_name(directory_name: str) -> str | None:
    """Map one of OUR catalog names onto the actor's directory name, or ``None``
    when the actor's network simply does not include it (the caller reports that
    honestly instead of paying for a run that touches nothing)."""
    n = _norm(directory_name)
    if not n:
        return None
    if n in _NETWORK_ALIASES:
        return _NETWORK_ALIASES[n]
    if n in _NETWORK_BY_NORM:
        return _NETWORK_BY_NORM[n]
    # containment either way (e.g. "yelpforbusiness" ~ "yelp"), guarded against
    # tiny tokens so "n49" can't swallow unrelated names.
    for cand_norm, cand in _NETWORK_BY_NORM.items():
        if len(cand_norm) >= 4 and (cand_norm in n or n in cand_norm):
            return cand
    return None


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
        # Map our catalog name onto the actor's network FIRST - an unmapped
        # directory fails fast and free instead of paying for a run that
        # matches nothing.
        target = actor_network_name(job.directory_name)
        if target is None:
            return CitationSubmitResult(
                status="failed",
                error=f"{job.directory_name!r} is not in the Apify actor's 48-directory network",
            )
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
            "directories": [target],
            "maxConcurrent": 1,
        }
        # The actor's schema allows ONLY these solver enums — an off-list value
        # (e.g. capmonster) is a 400 invalid-input on the whole run, so pass the
        # solver through only when the actor can actually accept it.
        if (
            self._captcha_provider in ("capsolver", "2captcha", "anticaptcha")
            and self._captcha_api_key
        ):
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
        saw_candidate = False
        for item in rows:
            if not isinstance(item, dict):
                continue
            # THE REAL OUTPUT SHAPE (verified against live runs 2026-07-23):
            #   item.submissions = {summary: {...}, results: [{directory, status,
            #   manualLink?, listingUrl?, preformattedData?}, ...]}
            # Submission results are authoritative; audit.results is the CHECK
            # (missing/correct/incorrect vocabulary), used only as a fallback.
            sub_results: list[Any] = []
            subs = item.get("submissions")
            if isinstance(subs, dict) and isinstance(subs.get("results"), list):
                sub_results = subs["results"]
            elif isinstance(subs, list):
                sub_results = subs
            for c in sub_results:
                if not isinstance(c, dict):
                    continue
                saw_candidate = True
                status = str(c.get("status") or "").lower()
                url = str(
                    c.get("liveUrl") or c.get("listingUrl") or c.get("proofUrl")
                    or c.get("submissionUrl") or c.get("url") or ""
                )
                if status in ("requires_account", "requiresaccount"):
                    # The platform only accepts an authenticated business account
                    # (Google/Facebook/Bing/Apple class). Blocked - retryable once
                    # credentials exist - with the actor's manual link surfaced so
                    # the operator can finish it by hand from the board.
                    manual = str(c.get("manualLink") or "")
                    return CitationSubmitResult(
                        status="blocked",
                        proof_url=manual,
                        error="requires an authenticated business account"
                        + (f" - manual: {manual}" if manual else ""),
                    )
                if status in ("failed", "error", "skipped"):
                    reason = str(c.get("error") or c.get("message") or f"directory {status}")
                    return CitationSubmitResult(status="failed", error=reason)
                if status in (
                    "submitted", "success", "succeeded", "verified", "created",
                    "updated", "ok", "pending", "verification_pending", "verificationpending",
                ) or (not status and url):
                    return CitationSubmitResult(
                        status="verified" if status == "verified" else "submitted",
                        proof_url=url,
                        external_ref=str(c.get("externalRef") or c.get("id") or run_id),
                    )
                return CitationSubmitResult(
                    status="failed", error=f"Apify submission reported '{status}'"
                )
            # Fallback: audit-only output (no submissions block) - the directory
            # was checked, not built.
            audit = item.get("audit")
            audit_results = audit.get("results") if isinstance(audit, dict) else None
            for c in audit_results or []:
                if isinstance(c, dict) and (c.get("status") or c.get("directory")):
                    saw_candidate = True
                    return CitationSubmitResult(
                        status="failed",
                        error=f"Apify audited only (status '{c.get('status')}') - nothing was submitted",
                    )
        if not saw_candidate:
            # The run finished but processed NOTHING (e.g. the directory filter
            # matched none of the actor's network) — an honest failure, never a
            # claimed submission.
            return CitationSubmitResult(
                status="failed",
                error="Apify run completed without touching this directory (not in the actor's network?)",
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
