"""Observability: the Prometheus metrics endpoint + request instrumentation."""

from __future__ import annotations

import httpx
import pytest

from app.core.errors import ErrorCode


@pytest.mark.unit
async def test_metrics_endpoint_exposes_prometheus_text(client: httpx.AsyncClient) -> None:
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    # The metric families are declared even before any traffic.
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body
    assert "http_requests_in_flight" in body


@pytest.mark.unit
async def test_request_is_counted_by_route_template(client: httpx.AsyncClient) -> None:
    # Drive a request, then confirm it was recorded against the ROUTE label.
    await client.get("/health")
    body = (await client.get("/metrics")).text
    # A counter sample labelled by the matched template + status must be present.
    assert 'http_requests_total{' in body
    assert 'route="/health"' in body
    assert 'status="200"' in body


@pytest.mark.unit
async def test_unmatched_path_does_not_explode_cardinality(client: httpx.AsyncClient) -> None:
    # A path that never routes is collapsed to a single "unmatched" label, so a
    # path scan cannot spawn a metric series per URL.
    await client.get("/no-such-route-xyz")
    body = (await client.get("/metrics")).text
    assert 'route="unmatched"' in body


@pytest.mark.unit
def test_error_codes_are_a_stable_set() -> None:
    # The envelope `type` values are a versioned contract clients branch on.
    assert ErrorCode.INTERNAL == "internal_error"
    assert ErrorCode.SERVICE_UNAVAILABLE == "service_unavailable"
    assert ErrorCode.HTTP == "http_error"
    assert ErrorCode.VALIDATION == "validation_error"
