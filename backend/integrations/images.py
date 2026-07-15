"""Image-generation seam (P7A-2): the ONLY door to an image provider.

The content pipeline generates a hero/section image (with alt text for
accessibility + on-page SEO) for a draft. Reachable exclusively through the
``ImageGenerator`` Protocol so a later chunk can meter it on the cost path.

Anthropic has no image API, so - like the Voyage embedder - this is a SEPARATE
provider. The real impl targets an OpenAI-compatible images endpoint (the de-facto
generation API), returning a hosted URL that maps straight onto ``GeneratedImage``.

Two impls satisfy the Protocol, mirroring the context seams:

* ``OpenAIImageGenerator`` - real, over the shared sync ``HttpProviderClient``.
  Key-gated on ``IMAGE_GEN_API_KEY`` (Bearer header, never logged); absent key ->
  ``ProviderNotConfiguredError``. The provider carries the alt text through - the
  caller's alt is authoritative and always round-trips onto the result.
* ``FakeImageGenerator`` - deterministic, offline: a stable placeholder URL derived
  from sha256(prompt) + the caller's alt, so image tests + degraded runs are
  reproducible with no key.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from integrations.errors import ProviderCallError, ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

_INSTALL_HINT = "set IMAGE_GEN_API_KEY to enable live image generation"
_OPENAI_IMAGES_BASE = "https://api.openai.com"


@dataclass(frozen=True)
class GeneratedImage:
    """One generated image: its hosted ``url`` and the ``alt`` text (accessibility +
    on-page SEO). ``alt`` is the caller's authoritative alt, carried through."""

    url: str
    alt: str


@runtime_checkable
class ImageGenerator(Protocol):
    """Generate an image for ``prompt`` and return it tagged with ``alt`` text."""

    def generate(self, prompt: str, alt: str) -> GeneratedImage: ...


class OpenAIImageGenerator(HttpProviderClient):
    """Real ``ImageGenerator`` over an OpenAI-compatible images endpoint.

    The key rides in the ``Authorization: Bearer`` header (never logged). ``model``
    is configurable (defaults to a current image model); the response's first
    ``data[].url`` becomes the image URL, tagged with the caller's ``alt``.
    """

    provider = "image_gen"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-image-1",
        size: str = "1024x1024",
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"Image generator unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url=_OPENAI_IMAGES_BASE,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        self._model = model
        self._size = size

    def generate(self, prompt: str, alt: str) -> GeneratedImage:
        body = {"model": self._model, "prompt": prompt, "n": 1, "size": self._size}
        data = self.request_json("POST", "/v1/images/generations", json_body=body)
        items = data.get("data") or []
        url = items[0].get("url") if items and isinstance(items[0], dict) else None
        if not isinstance(url, str) or not url:
            raise ProviderCallError("image provider response missing an image url")
        # Alt is the caller's - the provider does not author it; carry it through.
        return GeneratedImage(url=url, alt=alt)


class FakeImageGenerator:
    """Deterministic, offline ``ImageGenerator`` - sha256(prompt) -> stable URL.

    Same prompt => same placeholder URL every run; the caller's ``alt`` round-trips
    unchanged. No network, so image tests + degraded runs are reproducible.
    """

    def __init__(self, *, base_url: str = "https://images.example.test") -> None:
        self._base_url = base_url.rstrip("/")

    def generate(self, prompt: str, alt: str) -> GeneratedImage:
        digest = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        return GeneratedImage(url=f"{self._base_url}/{digest}.png", alt=alt)
