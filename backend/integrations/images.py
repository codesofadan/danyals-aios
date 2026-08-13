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
  caller's alt is authoritative and always round-trips onto the result. It handles
  BOTH provider response shapes: a hosted ``url`` (dall-e style) is used directly;
  base64 (``b64_json`` - what ``gpt-image-1`` ALWAYS returns) is decoded and HOSTED
  through an injected ``ImageHost`` so the result is still a real ``https`` URL, not
  a multi-MB inline ``data:`` URI.
* ``FakeImageGenerator`` - deterministic, offline: a stable placeholder URL derived
  from sha256(prompt) + the caller's alt, so image tests + degraded runs are
  reproducible with no key.
"""

from __future__ import annotations

import base64
import binascii
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


@runtime_checkable
class ImageHost(Protocol):
    """Persist decoded PNG bytes and return a served ``https`` URL for them.

    The seam by which a base64 (``b64_json``) image is turned into a real, embeddable
    URL. Implemented by ``app.services.content_images.LocalContentImageStore`` (injected
    from the provider factory), so ``integrations`` stays free of an app-layer import.
    """

    def host_png(self, data: bytes) -> str: ...


class OpenAIImageGenerator(HttpProviderClient):
    """Real ``ImageGenerator`` over an OpenAI-compatible images endpoint.

    The key rides in the ``Authorization: Bearer`` header (never logged). ``model``
    is configurable (defaults to a current image model). The response is handled for
    BOTH provider shapes:

    * a hosted ``data[].url`` (dall-e-3 style) -> used directly;
    * ``data[].b64_json`` (what ``gpt-image-1`` ALWAYS returns - never a url) ->
      decoded and HOSTED via the injected ``image_host``, yielding a real ``https``
      URL (never a multi-MB inline ``data:`` URI in the draft).

    Either way the result is tagged with the caller's authoritative ``alt``. When a
    ``b64_json`` image arrives but no ``image_host`` is configured, a typed
    ``ProviderCallError`` is raised (the caller catches it and skips that image -
    degrade, never crash).
    """

    provider = "image_gen"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-image-1",
        size: str = "1024x1024",
        timeout: float = 60.0,
        image_host: ImageHost | None = None,
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
        self._host = image_host

    def generate(self, prompt: str, alt: str) -> GeneratedImage:
        body = {"model": self._model, "prompt": prompt, "n": 1, "size": self._size}
        data = self.request_json("POST", "/v1/images/generations", json_body=body)
        items = data.get("data") or []
        first = items[0] if items and isinstance(items[0], dict) else {}

        # (1) dall-e style: a hosted url comes straight back -> use it as-is.
        url = first.get("url")
        if isinstance(url, str) and url:
            # Alt is the caller's - the provider does not author it; carry it through.
            return GeneratedImage(url=url, alt=alt)

        # (2) gpt-image-1 style: base64 PNG (b64_json), never a hosted url. Decode it
        # and HOST the bytes so the draft embeds a real https URL, not a giant data: URI.
        b64 = first.get("b64_json")
        if isinstance(b64, str) and b64:
            if self._host is None:
                raise ProviderCallError(
                    "image provider returned base64 (b64_json) but no image host is "
                    "configured to serve it (set CONTENT_IMAGE_DIR / PUBLIC_FILE_BASE_URL)"
                )
            try:
                raw = base64.b64decode(b64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ProviderCallError("image provider returned undecodable base64") from exc
            hosted = self._host.host_png(raw)
            return GeneratedImage(url=hosted, alt=alt)

        raise ProviderCallError("image provider response missing an image url")


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
