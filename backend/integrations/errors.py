"""Shared errors for the provider seams (P6B-3 context; P7A-2 content).

Lives in its own tiny module so every seam module (``llm``, ``embeddings``,
``vectorstore``, and the content seams ``content_research`` / ``wordpress`` /
``images`` + their ``http_client`` base) and the two factories can all raise these
without an import cycle (the factories import the seams; the seams must not import
the factories).
"""

from __future__ import annotations


class ProviderNotConfiguredError(RuntimeError):
    """A real provider impl was constructed without its SDK or its key.

    Always raised with a message that names the fix - install the optional extra
    and set the relevant key - so a misconfiguration is self-explaining. The
    key-gated factories avoid this by returning a degraded ``None`` / a fake when a
    key is absent; this fires only if a real impl is built directly without one.
    """


class ProviderCallError(RuntimeError):
    """A real provider HTTP call failed non-transiently (a 4xx after the retry
    budget, or a malformed response).

    Raised by the content seams' shared HTTP client so a caller can distinguish a
    genuine provider rejection from a missing-key misconfiguration. The message
    NEVER contains a secret or a response body - only the provider name, the status,
    and the path (query string stripped) - because auth rides in headers, not URLs.
    """
