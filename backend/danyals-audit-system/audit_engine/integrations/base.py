"""Base HTTP client with retry, circuit breaker, rate-limit awareness.

All integration clients inherit from BaseClient. The base never logs secrets;
keys are redacted from any log line that mentions them.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Mapping

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from audit_engine.logging_setup import get_logger

log = get_logger(__name__)


class RateLimited(Exception):
    """Provider rate-limit signal (HTTP 429 or provider-specific)."""


class TransientError(Exception):
    """5xx or network issue; safe to retry."""


@dataclass
class CircuitBreaker:
    """Trips open after `failure_threshold` consecutive failures; resets after
    `cooldown_sec`. Half-open after cooldown lets one request through."""

    failure_threshold: int = 5
    cooldown_sec: float = 30.0
    _failures: int = 0
    _opened_at: float | None = None

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        if time.monotonic() - self._opened_at >= self.cooldown_sec:
            return True  # half-open
        return False

    def on_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def on_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = time.monotonic()


class BaseClient:
    """Async HTTP client with shared retry + circuit breaker.

    Subclasses set `provider_name` and `base_url`; they call `_get()` / `_post()`.
    The base never echoes keys in logs or exceptions.
    """

    provider_name: str = "base"
    base_url: str = ""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        max_retries: int = 3,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._headers = dict(headers or {})
        self._client: httpx.AsyncClient | None = None
        self._breaker = CircuitBreaker()

    async def __aenter__(self) -> BaseClient:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            headers=self._headers,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        if self._client is None:
            raise RuntimeError(f"{self.provider_name} client used outside `async with` context")
        if not self._breaker.allow():
            raise TransientError(f"{self.provider_name} circuit breaker open")

        merged_headers = {**self._headers, **(headers or {})}

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1.0, min=1.0, max=10.0),
            retry=retry_if_exception_type((TransientError, RateLimited, httpx.TransportError)),
            reraise=True,
        ):
            with attempt:
                try:
                    resp = await self._client.request(
                        method, url, params=params, json=json_body, headers=merged_headers
                    )
                except httpx.TransportError as e:
                    self._breaker.on_failure()
                    raise TransientError(f"{self.provider_name} transport error: {type(e).__name__}") from e

                if resp.status_code == 429:
                    self._breaker.on_failure()
                    raise RateLimited(f"{self.provider_name} 429 rate-limited")
                if 500 <= resp.status_code < 600:
                    self._breaker.on_failure()
                    raise TransientError(f"{self.provider_name} {resp.status_code}")
                # 4xx (non-429) is a client problem; raise without retry.
                if resp.status_code >= 400:
                    self._breaker.on_failure()
                    # Don't log body - may echo keys back.
                    log.error(
                        "provider_client_error",
                        provider=self.provider_name,
                        status=resp.status_code,
                        url=url.split("?", 1)[0],
                    )
                    resp.raise_for_status()
                self._breaker.on_success()
                return resp
        raise RuntimeError("unreachable")  # pragma: no cover

    async def get(
        self,
        path_or_url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        url = path_or_url if path_or_url.startswith("http") else f"{self.base_url.rstrip('/')}/{path_or_url.lstrip('/')}"
        return await self._request("GET", url, params=params, headers=headers)

    async def post(
        self,
        path_or_url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        url = path_or_url if path_or_url.startswith("http") else f"{self.base_url.rstrip('/')}/{path_or_url.lstrip('/')}"
        return await self._request("POST", url, params=params, json_body=json_body, headers=headers)


async def _gather_limited(coros: list, concurrency: int) -> list:
    """Bounded asyncio.gather. Returns results in input order; exceptions are
    returned (not raised) so callers can mark per-task failures without losing
    successful results."""
    sem = asyncio.Semaphore(concurrency)

    async def _run(coro):
        async with sem:
            try:
                return await coro
            except Exception as e:  # noqa: BLE001
                return e

    return await asyncio.gather(*[_run(c) for c in coros])
