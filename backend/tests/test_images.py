"""Image-generation seam: ``OpenAIImageGenerator`` handles BOTH provider response
shapes (a hosted ``url`` AND base64 ``b64_json``), and ``LocalContentImageStore``
hosts the decoded bytes + serves them traversal-safe.

The bug this pins: ``gpt-image-1`` ALWAYS returns ``b64_json`` (base64), never a
hosted ``url`` (unlike dall-e-3). The old code read only ``data[0].url`` and raised
``ProviderCallError`` when absent, so every gpt-image-1 draft ended with 0 images
even though the image was generated + billed by OpenAI. These are offline (no
network): the HTTP call is stubbed with a canned provider payload.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.services.content_images import (
    CONTENT_IMAGE_ROUTE,
    LocalContentImageStore,
    content_image_dir,
    content_image_store_from_settings,
)
from integrations.errors import ProviderCallError, ProviderNotConfiguredError
from integrations.images import GeneratedImage, OpenAIImageGenerator

pytestmark = pytest.mark.unit

# A valid, tiny 1x1 transparent PNG in base64 (what gpt-image-1 returns in b64_json).
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
_TINY_PNG_BYTES = base64.b64decode(_TINY_PNG_B64)


class _StubImageAPI(OpenAIImageGenerator):
    """An ``OpenAIImageGenerator`` whose HTTP call is replaced by a canned payload, so
    ``generate`` runs its full response handling with zero network."""

    def __init__(self, payload: dict[str, Any], **kw: Any) -> None:
        super().__init__(api_key="test-key", **kw)
        self._payload = payload

    def request_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._payload


# --------------------------------------------------------------------------- #
# LocalContentImageStore: host + dedup + traversal-safe resolve.
# --------------------------------------------------------------------------- #
def test_store_hosts_bytes_and_dedups(tmp_path: Path) -> None:
    store = LocalContentImageStore(tmp_path, base_url="https://files.test/")
    url1 = store.host_png(b"the-image-bytes")
    url2 = store.host_png(b"the-image-bytes")  # identical bytes -> same content-hash file

    assert url1 == url2  # dedup: same URL
    assert url1.startswith(f"https://files.test{CONTENT_IMAGE_ROUTE}/")
    assert url1.endswith(".png")
    files = list(tmp_path.iterdir())
    assert len(files) == 1  # written exactly once

    # resolve() round-trips the served name back to the real file; traversal refused.
    name = url1.rsplit("/", 1)[-1]
    assert store.resolve(name) == files[0]
    assert store.resolve("../secret.png") is None
    assert store.resolve("") is None


def test_store_returns_relative_url_when_no_base(tmp_path: Path) -> None:
    store = LocalContentImageStore(tmp_path)
    url = store.host_png(b"xyz")
    assert url.startswith(f"{CONTENT_IMAGE_ROUTE}/")  # a same-origin-usable relative URL


def test_store_rejects_empty_bytes(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        LocalContentImageStore(tmp_path).host_png(b"")


# --------------------------------------------------------------------------- #
# content_image_dir fallback + factory.
# --------------------------------------------------------------------------- #
def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="dev", **over)  # type: ignore[arg-type]


def test_content_image_dir_prefers_explicit_then_falls_back() -> None:
    assert content_image_dir(_settings(content_image_dir="/x/imgs")) == "/x/imgs"
    # falls back UNDER content_artifact_dir, then audit_artifact_dir
    assert content_image_dir(_settings(content_artifact_dir="/c")) == str(Path("/c") / "content-images")
    assert content_image_dir(_settings(audit_artifact_dir="/a")) == str(Path("/a") / "content-images")
    # NO artifact root anywhere -> None (image hosting unavailable, degrade-safe)
    assert content_image_dir(_settings()) is None


def test_factory_none_when_no_root_configured() -> None:
    assert content_image_store_from_settings(_settings()) is None


def test_factory_builds_store_with_public_base_url(tmp_path: Path) -> None:
    store = content_image_store_from_settings(
        _settings(content_image_dir=str(tmp_path), public_file_base_url="https://app.qanry.com")
    )
    assert store is not None
    url = store.host_png(_TINY_PNG_BYTES)
    assert url == f"https://app.qanry.com{CONTENT_IMAGE_ROUTE}/{_sha_name(_TINY_PNG_BYTES)}"


def _sha_name(data: bytes) -> str:
    import hashlib

    return f"{hashlib.sha256(data).hexdigest()}.png"


# --------------------------------------------------------------------------- #
# OpenAIImageGenerator: BOTH response shapes.
# --------------------------------------------------------------------------- #
def test_generate_hosts_b64_json_and_returns_usable_url(tmp_path: Path) -> None:
    # THE regression: a gpt-image-1 response carries b64_json (no url). The generator
    # must decode + HOST it and return a real, non-empty https URL (not raise).
    store = LocalContentImageStore(tmp_path, base_url="https://files.test")
    gen = _StubImageAPI({"data": [{"b64_json": _TINY_PNG_B64}]}, image_host=store)

    img = gen.generate("a hero prompt", "a hero photo")

    assert isinstance(img, GeneratedImage)
    assert img.alt == "a hero photo"  # the caller's alt round-trips
    assert img.url  # non-empty, usable
    assert img.url.startswith(f"https://files.test{CONTENT_IMAGE_ROUTE}/")
    # The decoded bytes were actually written and resolve back to the exact image.
    name = img.url.rsplit("/", 1)[-1]
    path = store.resolve(name)
    assert path is not None
    assert path.read_bytes() == _TINY_PNG_BYTES


def test_generate_uses_a_hosted_url_directly(tmp_path: Path) -> None:
    # dall-e style: a hosted url comes straight back -> used as-is, nothing hosted.
    store = LocalContentImageStore(tmp_path, base_url="https://files.test")
    gen = _StubImageAPI({"data": [{"url": "https://cdn.example/hosted.png"}]}, image_host=store)

    img = gen.generate("p", "alt text")

    assert img.url == "https://cdn.example/hosted.png"
    assert img.alt == "alt text"
    assert not list(tmp_path.iterdir())  # the b64 host path was never taken


def test_generate_prefers_url_over_b64_when_both_present(tmp_path: Path) -> None:
    store = LocalContentImageStore(tmp_path, base_url="https://files.test")
    gen = _StubImageAPI(
        {"data": [{"url": "https://cdn.example/hosted.png", "b64_json": _TINY_PNG_B64}]},
        image_host=store,
    )
    img = gen.generate("p", "alt")
    assert img.url == "https://cdn.example/hosted.png"
    assert not list(tmp_path.iterdir())


def test_generate_b64_without_host_raises_caught_error() -> None:
    # b64 image but no host configured -> a TYPED error the pipeline catches + skips
    # (degrade, never crash); NOT an unhandled exception.
    gen = _StubImageAPI({"data": [{"b64_json": _TINY_PNG_B64}]}, image_host=None)
    with pytest.raises(ProviderCallError):
        gen.generate("p", "alt")


def test_generate_undecodable_b64_raises(tmp_path: Path) -> None:
    gen = _StubImageAPI(
        {"data": [{"b64_json": "!!! not valid base64 !!!"}]},
        image_host=LocalContentImageStore(tmp_path),
    )
    with pytest.raises(ProviderCallError):
        gen.generate("p", "alt")


def test_generate_missing_url_and_b64_raises() -> None:
    gen = _StubImageAPI({"data": [{}]})
    with pytest.raises(ProviderCallError):
        gen.generate("p", "alt")


def test_generate_empty_data_raises() -> None:
    gen = _StubImageAPI({"data": []})
    with pytest.raises(ProviderCallError):
        gen.generate("p", "alt")


def test_constructing_without_key_is_unconfigured() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        OpenAIImageGenerator(api_key="")


# --------------------------------------------------------------------------- #
# The doubled route prefix.
#
# MEASURED on a real deploy, 2026-08-30: every generated page embedded
# ``http://host:8000/api/v1/api/v1/public/content-images/<sha>.png``, which 404s,
# because PUBLIC_FILE_BASE_URL had been set to the API base *including* /api/v1
# while CONTENT_IMAGE_ROUTE already carries it.
#
# The reason this is worth a guard rather than a docs note is where it surfaces.
# The bytes host correctly (the single-slash URL returns 200), the stage reports
# success, the cost is real and the page passes QA - so nothing in the platform
# knows. It is discovered as a missing image on the client's live page.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("base", [
    "http://host:8000/api/v1",      # the exact value that shipped the 404
    "http://host:8000/api/v1/",     # ...with a trailing slash
    "http://host:8000/api",         # a partial overlap
    "http://host:8000",             # the documented, correct form
])
def test_a_base_url_that_repeats_the_route_still_mints_a_working_url(base: str) -> None:
    store = LocalContentImageStore("/tmp/unused", base_url=base)
    url = f"{store._base_url}{store._route}"
    assert url == "http://host:8000/api/v1/public/content-images"
    assert "/api/v1/api/v1/" not in url


def test_a_blank_base_url_stays_relative() -> None:
    # Same-origin dashboard preview depends on this; it is not an error case.
    store = LocalContentImageStore("/tmp/unused", base_url="")
    assert f"{store._base_url}{store._route}" == "/api/v1/public/content-images"


def test_an_unrelated_path_on_the_base_url_is_preserved() -> None:
    # Only an overlap with the ROUTE is trimmed. A host served under its own
    # sub-path keeps that sub-path, or every such deploy breaks instead.
    store = LocalContentImageStore("/tmp/unused", base_url="https://cdn.example.com/files")
    assert f"{store._base_url}{store._route}" == (
        "https://cdn.example.com/files/api/v1/public/content-images"
    )
