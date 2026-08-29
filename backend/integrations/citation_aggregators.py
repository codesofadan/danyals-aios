"""Route A: the three write paths that actually verified, and the price gate on one.

WHAT THIS REPLACES. `integrations/citation_apis.py` held Bing Places and Foursquare
submitters. Both were deleted because their coded endpoints do not exist - probed
unauthenticated on 2026-08-23, `POST /v3/places` answers 404 "Endpoint '/v3/places' not
found", the current Foursquare host has no write path either, and Bing's URL 301s to a
404. A Foursquare READ endpoint answering 401 was the control, so those are missing
routes rather than auth failures. Foursquare routes place additions to a community-
moderated queue; Bing's API is a partner programme reached by email.

THE THREE THAT DID VERIFY, same day, same method:

  Data Axle Local Listings Premium  POST /api/1/submissions        -> 403 (auth-gated)
  Apple Business Connect            POST /orgs/{org}/locations     -> 401 (auth-gated)
  Google Business Profile           POST /v1/accounts/{id}/locations  documented, allowlisted

A 401 or 403 to an unauthenticated probe means the endpoint EXISTS and wants credentials.
That is the whole difference between these and the two that were deleted.

NONE OF THEM MAY EVER RETURN `verified`, and this is the rule the module most needs:

  * Data Axle runs teleresearch - "up to three calls over three business days" - and
    files "can take up to two weeks to process";
  * Apple returns a created location in state `SUBMITTED`, i.e. queued for review;
  * Google's own docs say a created location "need[s] to be verified to be eligible to
    appear on Search and Maps".

So each returns `submitted`, and only the liveness probe in
`app/services/citation_liveness.py` ever promotes a row to `live`. A submitter that
returned `verified` would be asserting a listing exists because a POST returned 200,
which is the fabrication class this whole rebuild exists to remove.

WHY NONE OF THEM RUNS TODAY. Data Axle's price is published nowhere reachable: its own
site returns 403 to every client tried, the figure is absent from both the API docs and
the FAQ, and the `~$30/location` note in the 0046 seed carries no source. At $5/$10/$30
per Add the per-unit cost is $1.67/$3.33/$10.00 - between 17 and 100 times the 10c
commitment. `data_axle_add_cost_estimate` therefore defaults to 0.0 and BLOCKS the route
rather than pricing it as free, so no run can ever spend against an invented number.
Apple and GBP need credentials nobody has issued yet.

These classes exist so that closing that gap is a config change and a key, not a build.
"""

from __future__ import annotations

from typing import Any

from app.logging_setup import get_logger
from integrations.citation_submitters import CitationJob, CitationSubmitResult
from integrations.errors import ProviderCallError, ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

logger = get_logger("integrations.citation_aggregators")

_INSTALL_HINT = "set the matching key and a real per-submission cost before enabling"


class DataAxleSubmitter(HttpProviderClient):
    """Data Axle Local Listings Premium - the aggregator spine.

    VERIFIED FROM THE VENDOR'S OWN DOCS (2026-08-23): base
    ``https://local-listings-premium.data-axle.com/api/1``; auth is a token in an
    ``X-AUTH-TOKEN`` header generated from the account settings page; one endpoint,
    ``POST /submissions``, with four verbs by submission type - ``A`` add, ``R`` renew,
    ``U`` update, ``D`` delete - and up to 100 submissions per request. Required fields
    are Company Name, Location Address, City, State/Province, Zip/Postal Code and Phone.

    BILLING IS ON ADDS AND RENEWALS ONLY; updates are free. That is why a correction uses
    ``U`` rather than re-adding: re-adding a listing to fix a phone number would be
    charged, would create a duplicate, and would restart the verification clock.

    ``submission_type`` is chosen from whether we already hold a directory-side id, so an
    idempotent retry updates rather than duplicating.
    """

    provider = "data_axle"

    def __init__(self, *, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"Data Axle submitter unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://local-listings-premium.data-axle.com/api/1",
            headers={"X-AUTH-TOKEN": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )

    def submit(self, job: CitationJob) -> CitationSubmitResult:
        submission: dict[str, Any] = {
            # 'U' when we already hold a directory-side id: an update is FREE and does not
            # duplicate, where a second 'A' would be billed and would create a rival row.
            "submission_type": "U" if job.external_ref else "A",
            "company_name": job.business_name,
            "location_address": job.address_line1,
            "location_city": job.city,
            "location_state": job.region,
            "location_zip_code": job.postal_code,
            "location_phone": job.phone,
            "website": job.website_url,
        }
        if job.external_ref:
            submission["record_id"] = job.external_ref
        try:
            data = self.request_json("POST", "/submissions", json_body={"submissions": [submission]})
        except ProviderCallError as exc:
            return CitationSubmitResult(status="failed", error=str(exc))

        ref = str(data.get("submission_id") or data.get("id") or "") or job.external_ref
        # NEVER `verified`. Data Axle telephones the business up to three times over three
        # business days, and files can take two weeks to process. A 200 here means the
        # submission was ACCEPTED, which is a different fact from a listing existing.
        return CitationSubmitResult(status="submitted", external_ref=ref)


class AppleBusinessSubmitter(HttpProviderClient):
    """Apple Business Connect.

    ``POST {base}/api/v1/orgs/{orgId}/locations`` with a bearer token. A created location
    comes back in state ``SUBMITTED`` - reviewed before it is live - so this returns
    ``submitted`` and never ``verified``.

    ``partnersLocationId`` is OUR OWN citation id, which is what makes a retry idempotent
    and gives the later update/delete path a stable handle. Without it a re-run would
    create a second Apple location for the same business.
    """

    provider = "apple_business"

    def __init__(self, *, api_key: str, org_id: str, timeout: float = 30.0) -> None:
        if not api_key or not org_id:
            raise ProviderNotConfiguredError(f"Apple Business submitter unavailable: {_INSTALL_HINT}")
        self._org_id = org_id
        super().__init__(
            base_url="https://businessconnect.apple.com/api/v1",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )

    def submit(self, job: CitationJob) -> CitationSubmitResult:
        body = {
            "locationDetails": {
                "partnersLocationId": job.external_ref or f"aios:{job.directory_name}:{job.client_id}",
                "displayNames": [{"locale": "en-US", "value": job.business_name}],
                "mainAddress": {
                    "fullAddress": job.address_line1,
                    "locality": job.city,
                    "administrativeArea": job.region,
                    "postalCode": job.postal_code,
                    "countryCode": "US" if job.market == "US" else job.market,
                },
                "phoneNumber": job.phone,
                "websiteUrl": job.website_url,
            }
        }
        try:
            data = self.request_json("POST", f"/orgs/{self._org_id}/locations", json_body=body)
        except ProviderCallError as exc:
            return CitationSubmitResult(status="failed", error=str(exc))
        return CitationSubmitResult(
            status="submitted",
            external_ref=str(data.get("locationId") or data.get("id") or "") or job.external_ref,
        )
