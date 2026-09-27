"""Generated images are PUSHED to the client's site, not left as URLs to fetch.

THE FAILURE THIS CLOSES. Every image in a pushed page travelled as a URL for WordPress to
fetch, which silently requires the platform's image host to be reachable FROM the client's
server. In production it is. From a laptop, a private network, or anything behind a VPN it
is not - and the failure is invisible from both ends: the plugin treats a failed sideload
as best-effort, the post lands, the row says "Pushed to WordPress", and every picture on
the page 404s for every visitor. Measured on a real push to a real site.

The properties here are the ones that would let it happen again, and the ones that would
make the fix worse than the problem:

  * our own generated images are sent BY VALUE and the body rewritten to the site's URLs;
  * an image that is NOT ours is never read off this disk and re-uploaded;
  * a site whose plugin has no /media route changes nothing (the previous behaviour);
  * and a path that tries to climb out of the image directory is refused.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from workers.tasks.content import _local_image_path, _push_local_images

pytestmark = pytest.mark.unit

_BASE = "http://127.0.0.1:8010"
_ROUTE = "/api/v1/public/content-images/"
_PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class _Publisher:
    """A site that accepts pushed media. Records what it was given."""

    def __init__(self, *, accepts: bool = True) -> None:
        self.accepts = accepts
        self.uploads: list[tuple[str, str, int]] = []

    def upload_media(
        self, data: bytes, *, filename: str, content_type: str, alt: str = ""
    ) -> str:
        self.uploads.append((filename, content_type, len(data)))
        return f"https://client.example/wp-content/uploads/{filename}" if self.accepts else ""

    def ping(self) -> bool:
        return True

    def publish(self, payload: dict[str, Any]) -> Any:  # pragma: no cover - unused here
        raise AssertionError("publish is not part of this test")


class _OldPlugin:
    """A site running a plugin from before the /media route existed."""

    def ping(self) -> bool:
        return True

    def publish(self, payload: dict[str, Any]) -> Any:  # pragma: no cover - unused here
        raise AssertionError("publish is not part of this test")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        public_file_base_url=_BASE,
        content_image_dir=str(tmp_path),
        vault_master_key="0" * 64,
    )


@pytest.fixture
def image(tmp_path: Path) -> str:
    (tmp_path / "abc123.png").write_bytes(_PNG)
    return f"{_BASE}{_ROUTE}abc123.png"


def _payload(*images: str, featured: str = "") -> dict[str, Any]:
    body = "".join(f'<img src="{u}" alt="a picture">' for u in images)
    payload: dict[str, Any] = {"content": f"<main>{body}</main>", "title": "A page"}
    if featured:
        payload["featured_image_url"] = featured
        payload["og_image_url"] = featured
    return payload


# --------------------------------------------------------------------------- #
def test_our_own_image_is_pushed_and_the_body_rewritten(
    settings: Settings, image: str
) -> None:
    publisher = _Publisher()
    out = _push_local_images(_payload(image), publisher, settings)  # type: ignore[arg-type]

    assert publisher.uploads == [("abc123.png", "image/png", len(_PNG))]
    assert image not in out["content"], "the unreachable URL must be gone"
    assert "https://client.example/wp-content/uploads/abc123.png" in out["content"]


def test_the_featured_and_social_images_are_rewritten_too(
    settings: Settings, image: str
) -> None:
    """They are separate payload fields, and a featured image left pointing at an
    unreachable host is a post whose thumbnail is blank everywhere it is listed."""
    out = _push_local_images(
        _payload(image, featured=image), _Publisher(), settings  # type: ignore[arg-type]
    )
    assert out["featured_image_url"].startswith("https://client.example/")
    assert out["og_image_url"].startswith("https://client.example/")


def test_an_image_that_is_not_ours_is_left_alone(settings: Settings) -> None:
    """A client's own CDN image, or a stock URL a reviewer pasted in, must never be
    read off this server's disk and re-uploaded under the client's brand."""
    foreign = "https://cdn.client.example/hero.jpg"
    publisher = _Publisher()
    out = _push_local_images(_payload(foreign), publisher, settings)  # type: ignore[arg-type]
    assert publisher.uploads == []
    assert out["content"].count(foreign) == 1


def test_a_site_without_the_media_route_publishes_exactly_as_before(
    settings: Settings, image: str
) -> None:
    """An older plugin is not a failure. The page still publishes, with the URLs it
    always had - which is the behaviour this feature is an improvement on, not a
    regression from."""
    payload = _payload(image)
    out = _push_local_images(payload, _OldPlugin(), settings)  # type: ignore[arg-type]
    assert out == payload


def test_a_refused_upload_leaves_that_image_alone(settings: Settings, image: str) -> None:
    out = _push_local_images(_payload(image), _Publisher(accepts=False), settings)  # type: ignore[arg-type]
    assert image in out["content"], "a refused push must not blank the image"


class TestOnlyTheImageDirectoryIsReadable:
    """The URL decides which file is read, and a URL comes off a job row. Nothing may
    make that a way to read an arbitrary file off this server."""

    def test_a_traversal_is_refused(self, settings: Settings) -> None:
        assert _local_image_path(f"{_BASE}{_ROUTE}../../.env", settings) is None

    def test_a_nested_path_is_refused(self, settings: Settings) -> None:
        # The route serves flat, content-addressed names; a slash is never legitimate.
        assert _local_image_path(f"{_BASE}{_ROUTE}sub/dir/x.png", settings) is None

    def test_a_url_on_another_host_is_refused(self, settings: Settings, image: str) -> None:
        elsewhere = f"https://evil.example{_ROUTE}abc123.png"
        assert _local_image_path(elsewhere, settings) is None

    def test_a_missing_file_is_refused(self, settings: Settings) -> None:
        assert _local_image_path(f"{_BASE}{_ROUTE}nothere.png", settings) is None

    def test_the_real_thing_resolves(self, settings: Settings, image: str) -> None:
        path = _local_image_path(image, settings)
        assert path is not None and path.name == "abc123.png"
