"""Prometheus request metrics + the ``/metrics`` scrape endpoint.

Exposes request-rate, latency, in-flight, and error-rate signals so an operator
can alert on a 5xx spike (see ``infra/alerts/backend-alerts.yml``) - the exact
class of outage that hid the empty-JWT bug (34 routes 500ing would have driven
the 5xx ratio to ~0.67 and paged immediately).

The metric objects are module-level singletons on the DEFAULT registry: the app
factory is called many times in tests, and re-declaring a metric per app would
raise "Duplicated timeseries". The label set is deliberately low-cardinality -
the matched ROUTE TEMPLATE (``/api/v1/clients/{client_id}``), never the raw path,
so per-id URLs cannot explode the series count.

``/metrics`` carries no secrets but does reveal traffic shape; restrict it to the
scrape network at the edge (Caddy) rather than exposing it publicly.
"""

from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    labelnames=("method", "route", "status"),
)
_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency (seconds).",
    labelnames=("method", "route", "status"),
)
_IN_FLIGHT = Gauge(
    "http_requests_in_flight",
    "HTTP requests currently being served.",
)


def _route_template(request: Request) -> str:
    """The matched route's path template (low cardinality), or ``unmatched``.

    A 404 for an id that never routed has no ``route`` on the scope; collapsing
    those to a single label keeps a path scan from spawning a series per URL.
    """
    route = request.scope.get("route")
    path: str | None = getattr(route, "path", None)
    return path or "unmatched"


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record count + latency + in-flight for every request, labelled by template."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        _IN_FLIGHT.inc()
        start = time.perf_counter()
        status = 500  # if the inner app raises, it becomes a 500 downstream
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - start
            route = _route_template(request)
            labels = (request.method, route, str(status))
            _REQUESTS.labels(*labels).inc()
            _LATENCY.labels(*labels).observe(elapsed)
            _IN_FLIGHT.dec()


def metrics_response() -> Response:
    """Render the current metrics in Prometheus text exposition format."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
