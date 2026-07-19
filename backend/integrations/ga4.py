"""Google Analytics 4 (GA4) read seam (7C): the ONLY door to a client's GA4 data.

Mirrors ``integrations.gsc`` exactly. ``GA4DataClient`` is real, backed by the
Analytics Data API (``analyticsdata.googleapis.com`` ``runReport``) over a
per-client OAuth2 bearer token (never read here). ``FakeGA4Client`` is the
deterministic offline stand-in.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from integrations.errors import ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

_INSTALL_HINT = "pass a per-client OAuth bearer token (from the vault) to read GA4"
_GA4_DATA_BASE = "https://analyticsdata.googleapis.com/v1beta"


@dataclass(frozen=True)
class GA4Summary:
    """A trailing-window GA4 snapshot for one property."""

    sessions: int
    users: int
    conversions: int


@runtime_checkable
class GA4Provider(Protocol):
    def fetch_summary(self, property_id: str, *, days: int = 28) -> GA4Summary: ...


class GA4DataClient(HttpProviderClient):
    """Real ``GA4Provider`` over the Analytics Data API's ``runReport``."""

    provider = "ga4_data"

    def __init__(self, *, access_token: str, timeout: float = 20.0) -> None:
        if not access_token:
            raise ProviderNotConfiguredError(f"GA4 unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url=_GA4_DATA_BASE,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        )

    def fetch_summary(self, property_id: str, *, days: int = 28) -> GA4Summary:
        data = self.request_json(
            "POST",
            f"/properties/{property_id}:runReport",
            json_body={
                "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
                "metrics": [
                    {"name": "sessions"}, {"name": "totalUsers"}, {"name": "conversions"},
                ],
            },
        )
        rows = data.get("rows") or []
        if not rows:
            return GA4Summary(sessions=0, users=0, conversions=0)
        values = rows[0].get("metricValues") or []

        def _metric(idx: int) -> int:
            try:
                return int(float(values[idx].get("value", 0)))
            except (IndexError, ValueError, TypeError, AttributeError):
                return 0

        return GA4Summary(sessions=_metric(0), users=_metric(1), conversions=_metric(2))


class FakeGA4Client:
    """Deterministic offline ``GA4Provider`` - sha256(property_id) -> stable
    sessions/users/conversions, so tests + degraded runs are reproducible with
    zero keys."""

    def fetch_summary(self, property_id: str, *, days: int = 28) -> GA4Summary:
        digest = hashlib.sha256(property_id.encode()).hexdigest()
        sessions = int(digest[:4], 16) % 10000
        users = int(sessions * 0.7)
        conversions = int(digest[4:6], 16) % 50
        return GA4Summary(sessions=sessions, users=users, conversions=conversions)


def ga4_client_from_token(access_token: str) -> GA4Provider:
    """The real client for a decrypted per-client access token (never settings-
    gated here - mirrors ``search_console_client_from_token``)."""
    return GA4DataClient(access_token=access_token)
