"""Direct-API citation submitters (7B-4): the handful of directories in the
reference plan's aggregator/global layer that genuinely expose a self-serve,
documented WRITE path - as opposed to a portal-only submission (Data Axle,
Neustar/Localeze: no public write API, catalogued ``manual_only``) or one where
automation is technically possible but community norms explicitly forbid it
(OpenStreetMap: catalogued ``manual_only`` despite having a real editing API - see
``db/migrations/0046_directories_seed.sql``'s own note).

Both real clients here are KEY-GATED and INTENTIONALLY conservative about the exact
endpoint shape: Bing Places for Business and Foursquare Places are lower-traffic,
less-uniformly-documented enterprise APIs than the Web 2.0 blogging APIs this pass
also adds, so - mirroring the reference doc's own "Unverified" discipline - each
docstring says exactly what is solid (the auth pattern) vs. what must be confirmed
against the LIVE current partner docs before a real key is dropped in and this goes
live. Nothing runs against a wrong endpoint by accident: both clients are key-gated,
so they simply do not fire until someone with real API access configures + verifies
them, at which point verifying the endpoint is a natural part of that setup step.
"""

from __future__ import annotations

from app.logging_setup import get_logger
from integrations.citation_submitters import CitationJob, CitationSubmitResult
from integrations.errors import ProviderCallError, ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

logger = get_logger("integrations.citation_apis")

_INSTALL_HINT = "set the matching *_API_KEY setting to enable a direct-API citation submit"


class BingPlacesSubmitter(HttpProviderClient):
    """Real ``CitationSubmitter`` over the Bing Places for Business bulk-upload API.

    CONFIRM BEFORE LIVE USE: Bing Places' bulk-location endpoint is a partner/API-key
    product whose exact current path Microsoft documents in the Bing Places for
    Business developer portal (not a single, stable public URL this codebase can
    hard-verify offline) - the auth pattern below (an API key in a header) is
    standard for the product family; re-confirm the path in the live docs at setup
    time, matching the reference doc's own "verify against the live source" rule.
    """

    provider = "bing_places"

    def __init__(self, *, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"Bing Places submitter unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://ssl.bing.com/webmaster/places/api/v1",
            headers={"Ocp-Apim-Subscription-Key": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )

    def submit(self, job: CitationJob) -> CitationSubmitResult:
        body: dict[str, object] = {
            "businessName": job.business_name,
            "address": {
                "line1": job.address_line1,
                "line2": job.address_line2,
                "city": job.city,
                "region": job.region,
                "postalCode": job.postal_code,
            },
            "phone": job.phone,
            "website": job.website_url,
            "categories": list(job.categories),
        }
        method, path = ("PUT", f"/locations/{job.external_ref}") if job.external_ref else ("POST", "/locations")
        try:
            data = self.request_json(method, path, json_body=body)
        except ProviderCallError as exc:
            return CitationSubmitResult(status="failed", error=str(exc))
        location_id = data.get("id") or data.get("locationId")
        # Bing's own docs note single-listing submits go through a phone/email
        # verification step before they go live - 'submitted' (not 'verified') is
        # the honest status here; a follow-up re-check confirms live/verified.
        return CitationSubmitResult(
            status="submitted", external_ref=str(location_id) if location_id else job.external_ref
        )


class FoursquareSubmitter(HttpProviderClient):
    """Real ``CitationSubmitter`` over the Foursquare Places API.

    CONFIRM BEFORE LIVE USE: Foursquare's public v3 Places API is primarily a READ
    product (search/details); creating/claiming a venue for a business you represent
    is Foursquare's partner-gated "Add a place" flow, whose exact write endpoint this
    codebase cannot hard-verify offline. The auth pattern (a bearer API key) and
    request shape below are Foursquare's documented convention for the product
    family - re-confirm the live write endpoint at setup time.
    """

    provider = "foursquare"

    def __init__(self, *, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"Foursquare submitter unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://api.foursquare.com/v3",
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )

    def submit(self, job: CitationJob) -> CitationSubmitResult:
        body: dict[str, object] = {
            "name": job.business_name,
            "address": job.address_line1,
            "locality": job.city,
            "region": job.region,
            "postcode": job.postal_code,
            "tel": job.phone,
            "website": job.website_url,
            "categories": list(job.categories),
        }
        method, path = ("PATCH", f"/places/{job.external_ref}") if job.external_ref else ("POST", "/places")
        try:
            data = self.request_json(method, path, json_body=body)
        except ProviderCallError as exc:
            return CitationSubmitResult(status="failed", error=str(exc))
        place_id = data.get("fsq_id") or data.get("id")
        ref = str(place_id) if place_id else job.external_ref
        # The public Foursquare venue page IS the live citation — surface it as the
        # proof link so the board shows WHERE the listing was built, not just "submitted".
        return CitationSubmitResult(
            status="submitted",
            external_ref=ref,
            proof_url=f"https://foursquare.com/v/{ref}" if ref else "",
        )
