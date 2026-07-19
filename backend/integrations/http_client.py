"""Shared sync HTTP base for the content provider seams (P7A-2).

The content module's real providers - Serper (SERP research), WordPress (REST
publish), and the image generator - are all plain HTTP-over-``httpx``, unlike the
context seams which each wrap a vendor SDK (anthropic / voyageai / pinecone). So
they share ONE tiny synchronous client here instead of triplicating retry + secret
handling. It mirrors the audit engine's async ``BaseClient`` template that
``CLAUDE.md`` cites (retry/backoff on transient errors; NEVER log a secret or a
body), adapted to the backend's synchronous Celery-worker seams - exactly the shape
of ``PineconeVectorStore._run`` (build the transient tuple once, retry each op).

``httpx`` is lazy-imported inside ``__init__`` so importing this module stays free
at the base gate; a real client is only ever built behind a present credential, and
the auth material always rides in a HEADER (never a URL), so a stripped-path error
line can never echo it.
"""

from __future__ import annotations

from typing import Any

from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.logging_setup import get_logger
from integrations.errors import ProviderCallError, ProviderNotConfiguredError

logger = get_logger("integrations.http_client")

_INSTALL_HINT = "install httpx (a base dependency) - the content seams need it"


class _TransientHTTPError(RuntimeError):
    """Internal retry signal: a 429 or 5xx that is safe to retry with backoff.

    Never surfaces to callers - the retry loop either succeeds on a later attempt or
    re-raises the last one, which the seam translates into a ``ProviderCallError``.
    """


class HttpProviderClient:
    """A minimal sync HTTP client with shared retry + secret-safe error logging.

    Subclasses set ``provider`` and pass their auth ``headers`` (the caller has
    already resolved the key/credential); nothing here reads settings or a vault.
    Transient failures (network, 429, 5xx) retry with exponential backoff; a
    non-429 4xx is a caller problem and raises ``ProviderCallError`` at once with
    the path's query string stripped so a key in a query (there never is one) could
    not leak.
    """

    provider: str = "provider"

    def __init__(
        self,
        *,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
        max_attempts: int = 3,
    ) -> None:
        try:
            import httpx
        except ImportError as exc:  # httpx is a base dep; guard mirrors the SDK seams
            raise ProviderNotConfiguredError(
                f"{self.provider} client unavailable: {_INSTALL_HINT}"
            ) from exc
        self._client = httpx.Client(
            base_url=base_url,
            headers=dict(headers or {}),
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        )
        # Backoff only on transient failures; a 4xx surfaces immediately (below).
        self._transient: tuple[type[BaseException], ...] = (
            httpx.TransportError,
            _TransientHTTPError,
        )
        self._max_attempts = max_attempts

    def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        auth: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        """Issue one request under retry and return the parsed JSON object.

        ``auth`` is an optional ``(username, password)`` pair for HTTP Basic (used by
        WordPress application passwords); it is handed to ``httpx`` and NEVER logged.

        Every caller across this codebase catches ``ProviderCallError`` (never a raw
        transport error or the internal ``_TransientHTTPError``) - so a persistent
        5xx/429/network failure that survives every retry attempt is translated
        here, not left to escape as the internal/transport-level exception.
        """
        try:
            for attempt in Retrying(
                retry=retry_if_exception_type(self._transient),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
                stop=stop_after_attempt(self._max_attempts),
                reraise=True,
            ):
                with attempt:
                    return self._once(method, url, params=params, json_body=json_body, auth=auth)
        except self._transient as exc:
            raise ProviderCallError(f"{self.provider} failed after {self._max_attempts} attempts: {exc}") from exc
        raise AssertionError("unreachable: tenacity reraises or returns")  # pragma: no cover

    def _once(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None,
        json_body: Any,
        auth: tuple[str, str] | None,
    ) -> dict[str, Any]:
        # A transport error propagates straight to the retry loop (it is in the
        # transient tuple); everything else is classified by status below.
        response = self._client.request(method, url, params=params, json=json_body, auth=auth)
        status = response.status_code
        if status == 429 or 500 <= status < 600:
            raise _TransientHTTPError(f"{self.provider} {status}")
        if status >= 400:
            # A caller problem (bad request / auth): stop now. Log the STRIPPED path
            # only - never the body or headers, which could echo the credential.
            logger.error(
                "provider_client_error",
                provider=self.provider,
                status=status,
                path=str(response.request.url).split("?", 1)[0],
            )
            raise ProviderCallError(f"{self.provider} request failed with status {status}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderCallError(f"{self.provider} returned a non-JSON body") from exc
        if not isinstance(payload, dict):
            raise ProviderCallError(f"{self.provider} returned an unexpected JSON shape")
        return payload

    def close(self) -> None:
        """Close the underlying connection pool (best-effort)."""
        self._client.close()
