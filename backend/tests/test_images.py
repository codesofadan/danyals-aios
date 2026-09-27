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


# --------------------------------------------------------------------------- #
# The quality rung. Left unsent, the provider bills `auto`, which is ADAPTIVE:
# measured against the pipeline's own scene prompt it settled at 343 output tokens
# ($0.0103), while `high` on the same model is 5,488 ($0.1656). A page makes five
# images, so an unchosen rung is a 16x tail on a bill nobody set.
# --------------------------------------------------------------------------- #
class _BodyCapturingAPI(OpenAIImageGenerator):
    """Captures the request body so the wire format can be asserted, not assumed."""

    sent: dict[str, Any]

    def __init__(self, **kw: Any) -> None:
        super().__init__(api_key="test-key", **kw)
        self.sent = {}

    def request_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.sent = dict(kwargs.get("json_body") or {})
        return {"data": [{"url": "https://cdn.test/a.png"}]}


class TestTheQualityRungIsChosenNotInherited:
    def test_a_configured_rung_rides_on_the_request(self) -> None:
        api = _BodyCapturingAPI(quality="medium")
        api.generate("a desk", "alt")
        assert api.sent["quality"] == "medium"

    def test_an_empty_rung_sends_no_field_at_all(self) -> None:
        """A provider whose vocabulary differs (dall-e-3 takes standard|hd) must not be
        handed a value from ours - it 400s. Omitting is the honest default."""
        api = _BodyCapturingAPI(quality="")
        api.generate("a desk", "alt")
        assert "quality" not in api.sent

    def test_whitespace_is_not_a_rung(self) -> None:
        api = _BodyCapturingAPI(quality="   ")
        api.generate("a desk", "alt")
        assert "quality" not in api.sent

    def test_the_model_and_size_still_ride_alongside(self) -> None:
        api = _BodyCapturingAPI(model="gpt-image-2.5-flare", size="1536x1024", quality="medium")
        api.generate("a desk", "alt")
        assert api.sent["model"] == "gpt-image-2.5-flare"
        assert api.sent["size"] == "1536x1024"
        assert api.sent["n"] == 1


class TestTheShippedDefaultsAreTheMeasuredOnes:
    """These numbers were measured off the provider's own `usage` block, not taken
    from a blog. If someone changes the model, the price must move with it - the two
    are one decision, and a ledger that bills the old model's price is silently wrong."""

    def test_the_model_default_is_the_measured_winner(self) -> None:
        assert Settings().image_gen_model == "gpt-image-2.5-flare"

    def test_the_quality_default_is_explicit(self) -> None:
        assert Settings().image_gen_quality == "medium"

    def test_the_ledger_bills_what_the_provider_charges(self) -> None:
        """194 input + 343 output tokens at $5/$30 per MTok = $0.0111. The old $0.04
        was gpt-image-1's price and over-billed every image the platform made by 3.6x."""
        measured = 194 / 1e6 * 5.0 + 343 / 1e6 * 30.0
        assert Settings().price_image_per_image == pytest.approx(measured, abs=5e-5)

    def test_the_factory_passes_the_rung_through(self) -> None:
        """A setting nothing reads is a setting that does not exist."""
        import inspect

        from integrations import content_providers

        src = inspect.getsource(content_providers)
        assert "quality=settings.image_gen_quality" in src


# --------------------------------------------------------------------------- #
# The ENCODING. Measured on one generation, identical output tokens either way:
# PNG 1.92 MB, WebP(q82) 0.12 MB. A page carries up to five, so PNG put ~9.6 MB of
# pictures into the largest-contentful-paint of a page whose whole job is to rank.
# --------------------------------------------------------------------------- #
class TestTheEncodingIsRequestedAndCostsNothing:
    def test_the_format_rides_on_the_request(self) -> None:
        api = _BodyCapturingAPI(image_format="webp", compression=82)
        api.generate("a desk", "alt")
        assert api.sent["output_format"] == "webp"
        assert api.sent["output_compression"] == 82

    def test_no_format_sends_neither_field(self) -> None:
        api = _BodyCapturingAPI(image_format="", compression=82)
        api.generate("a desk", "alt")
        assert "output_format" not in api.sent
        assert "output_compression" not in api.sent

    def test_compression_is_withheld_from_png(self) -> None:
        """output_compression is meaningless for a lossless format, and a provider that
        does not know the field rejects the entire call over it."""
        api = _BodyCapturingAPI(image_format="png", compression=82)
        api.generate("a desk", "alt")
        assert api.sent["output_format"] == "png"
        assert "output_compression" not in api.sent

    def test_zero_compression_is_omitted(self) -> None:
        api = _BodyCapturingAPI(image_format="webp", compression=0)
        api.generate("a desk", "alt")
        assert "output_compression" not in api.sent

    def test_the_shipped_default_is_webp(self) -> None:
        assert Settings().image_gen_format == "webp"
        assert Settings().image_gen_compression == 82

    def test_the_factory_passes_the_encoding_through(self) -> None:
        import inspect

        from integrations import content_providers

        src = inspect.getsource(content_providers)
        assert "image_format=settings.image_gen_format" in src
        assert "compression=settings.image_gen_compression" in src


class TestTheStoredNameMatchesTheBytes:
    """The store used to name every file .png regardless of content. The moment the
    provider returned WebP that was a .png full of WebP bytes, served as image/png -
    a broken image on every published page, and nothing would have raised."""

    @staticmethod
    def _magic(kind: str) -> bytes:
        from app.services.content_images import image_suffix  # noqa: F401

        return {
            "png": bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10]),
            "webp": b"RIFF" + bytes(4) + b"WEBPVP8 ",
            "jpeg": bytes([0xFF, 0xD8, 0xFF, 0xE0]),
            "gif": b"GIF89a",
        }[kind]

    @pytest.mark.parametrize(
        ("kind", "suffix"),
        [("png", ".png"), ("webp", ".webp"), ("jpeg", ".jpg"), ("gif", ".gif")],
    )
    def test_the_suffix_is_read_from_the_content(self, kind: str, suffix: str) -> None:
        from app.services.content_images import image_suffix

        assert image_suffix(self._magic(kind)) == suffix

    def test_something_unrecognised_stays_png(self) -> None:
        """Every image made before this existed is a PNG, and its stored name must keep
        resolving."""
        from app.services.content_images import image_suffix

        assert image_suffix(b"not an image at all") == ".png"

    def test_the_host_names_a_webp_file_webp(self, tmp_path: Path) -> None:
        store = LocalContentImageStore(tmp_path, base_url="https://cdn.test")
        url = store.host_png(self._magic("webp"))
        assert url.endswith(".webp")
        assert store.resolve(url.rsplit("/", 1)[-1]) is not None

    def test_the_served_media_type_follows_the_suffix(self) -> None:
        """A hardcoded image/png was correct only while the provider happened to
        return PNG."""
        from app.services.content_images import IMAGE_MEDIA_TYPES

        assert IMAGE_MEDIA_TYPES[".webp"] == "image/webp"
        assert IMAGE_MEDIA_TYPES[".png"] == "image/png"

    def test_the_publish_push_accepts_every_hosted_type(self) -> None:
        """The store can mint a name the WordPress media push then refuses to upload -
        so the two tables have to agree, or the image silently stays on our host."""
        from app.services.content_images import IMAGE_MEDIA_TYPES
        from workers.tasks.content import _IMAGE_CONTENT_TYPES

        for suffix, media in IMAGE_MEDIA_TYPES.items():
            assert _IMAGE_CONTENT_TYPES.get(suffix) == media, suffix

