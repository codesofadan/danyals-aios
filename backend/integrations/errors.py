"""Shared error for the context AI provider seams (P6B-3).

Lives in its own tiny module so the three seam modules (``llm``, ``embeddings``,
``vectorstore``) and the ``context_providers`` factory can all raise it without an
import cycle (the factory imports the seams; the seams must not import the factory).
"""

from __future__ import annotations


class ProviderNotConfiguredError(RuntimeError):
    """A real provider impl was constructed without its SDK or its key.

    Always raised with a message that names the fix - install the optional ``ai``
    extra and set the relevant key - so a misconfiguration is self-explaining. The
    key-gated factory avoids this by returning a degraded ``None`` when a key is
    absent; this fires only if a real impl is built directly without one.
    """
