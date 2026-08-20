"""Firecrawl render+screenshot seam: the async scrape parses markdown + normalises the
screenshot (URL / data-URI / raw base64) to bounded base64 PNG, degrades to ``None`` on
every failure, and the key-gated factory + the ``FakeFirecrawl`` behave. All with a fake
async http client - NO network."""

from __future__ import annotations

import base64
from typing import Any

import pytest

import integrations.firecrawl as fc
from app.config import Settings
from integrations.errors import ProviderNotConfiguredError
from integrations.firecrawl import (
    FakeFirecrawl,
    FirecrawlClient,
    FirecrawlPage,
    firecrawl_from_settings,
    firecrawl_scrape,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fake async http
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(
        self, *, status_code: int = 200, json_data: Any = None,
        content: bytes = b"", raise_json: bool = False,
    ) -> None:
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self._raise_json = raise_json

    def json(self) -> Any:
        if self._raise_json:
            raise ValueError("not json")
        return self._json


class FakeHttp:
    """Records the POST/GET it receives and returns configured responses (or raises)."""

    def __init__(
        self, *, post_resp: _Resp | None = None, get_resp: _Resp | None = None,
        post_exc: Exception | None = None, get_exc: Exception | None = None,
    ) -> None:
        self.post_resp = post_resp
        self.get_resp = get_resp
        self.post_exc = post_exc
        self.get_exc = get_exc
        self.posts: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []

    async def post(
        self, url: str, *, headers: Any = None, json: Any = None, timeout: Any = None
    ) -> _Resp:
        self.posts.append({"url": url, "headers": headers, "json": json})
        if self.post_exc is not None:
            raise self.post_exc
        assert self.post_resp is not None
        return self.post_resp

    async def get(self, url: str, *, follow_redirects: Any = None, timeout: Any = None) -> _Resp:
        self.gets.append({"url": url, "follow_redirects": follow_redirects})
        if self.get_exc is not None:
            raise self.get_exc
        assert self.get_resp is not None
        return self.get_resp


def _ok_post(data: dict[str, Any]) -> _Resp:
    return _Resp(json_data={"success": True, "data": data})


# --------------------------------------------------------------------------- #
# scrape: happy paths + screenshot normalisation
# --------------------------------------------------------------------------- #
async def test_scrape_parses_markdown_and_fetches_screenshot_url() -> None:
    png = b"\x89PNG-real-bytes"
    http = FakeHttp(
        post_resp=_ok_post({"markdown": "# Home", "screenshot": "https://storage.firecrawl.dev/s.png"}),
        get_resp=_Resp(content=png),
    )
    page = await firecrawl_scrape(
        http, api_key="fc-key", base_url="https://api.firecrawl.dev", url="https://x.com",
        want_screenshot=True,
    )
    assert page is not None
    assert page.markdown == "# Home"
    assert page.screenshot_b64 == base64.b64encode(png).decode("ascii")
    # POST shape: Bearer auth, markdown + FULL-PAGE screenshot (hero->footer, not just the
    # viewport), whole-page chrome (onlyMainContent False).
    post = http.posts[0]
    assert post["url"] == "https://api.firecrawl.dev/v1/scrape"
    assert post["headers"]["Authorization"] == "Bearer fc-key"
    assert post["json"]["formats"] == ["markdown", "screenshot@fullPage"]
    assert post["json"]["onlyMainContent"] is False
    assert post["json"]["url"] == "https://x.com"
    # The screenshot URL was fetched (redirects disabled).
    assert http.gets[0]["url"] == "https://storage.firecrawl.dev/s.png"
    assert http.gets[0]["follow_redirects"] is False


async def test_scrape_data_uri_screenshot_is_stripped_no_fetch() -> None:
    b64 = base64.b64encode(b"abc").decode("ascii")
    http = FakeHttp(post_resp=_ok_post({"markdown": "m", "screenshot": f"data:image/png;base64,{b64}"}))
    page = await firecrawl_scrape(
        http, api_key="k", base_url="https://api.firecrawl.dev", url="https://x.com",
        want_screenshot=True,
    )
    assert page is not None
    assert page.screenshot_b64 == b64
    assert http.gets == []  # a data-URI is inlined, never fetched


async def test_scrape_raw_base64_screenshot_passthrough() -> None:
    b64 = base64.b64encode(b"raw").decode("ascii")
    http = FakeHttp(post_resp=_ok_post({"markdown": "m", "screenshot": b64}))
    page = await firecrawl_scrape(
        http, api_key="k", base_url="https://api.firecrawl.dev", url="https://x.com",
        want_screenshot=True,
    )
    assert page is not None
    assert page.screenshot_b64 == b64


async def test_scrape_without_screenshot_omits_format_and_returns_none_shot() -> None:
    http = FakeHttp(post_resp=_ok_post({"markdown": "m", "screenshot": "https://s/s.png"}))
    page = await firecrawl_scrape(
        http, api_key="k", base_url="https://api.firecrawl.dev", url="https://x.com",
        want_screenshot=False,
    )
    assert page is not None
    assert page.screenshot_b64 is None
    assert http.posts[0]["json"]["formats"] == ["markdown"]
    assert http.gets == []  # never fetched a screenshot


async def test_scrape_flat_shape_without_data_wrapper_tolerated() -> None:
    http = FakeHttp(post_resp=_Resp(json_data={"markdown": "flat"}))
    page = await firecrawl_scrape(
        http, api_key="k", base_url="https://api.firecrawl.dev", url="https://x.com",
        want_screenshot=False,
    )
    assert page is not None
    assert page.markdown == "flat"


async def test_scrape_screenshot_over_cap_dropped_but_markdown_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fc, "_MAX_SCREENSHOT_BYTES", 4)  # tiny cap
    http = FakeHttp(
        post_resp=_ok_post({"markdown": "keep me", "screenshot": "https://s/s.png"}),
        get_resp=_Resp(content=b"way too many bytes for the cap"),
    )
    page = await firecrawl_scrape(
        http, api_key="k", base_url="https://api.firecrawl.dev", url="https://x.com",
        want_screenshot=True,
    )
    assert page is not None
    assert page.markdown == "keep me"
    assert page.screenshot_b64 is None  # over the cap -> dropped (not truncated)


async def test_scrape_screenshot_fetch_failure_keeps_markdown() -> None:
    http = FakeHttp(
        post_resp=_ok_post({"markdown": "still here", "screenshot": "https://s/s.png"}),
        get_exc=RuntimeError("boom"),
    )
    page = await firecrawl_scrape(
        http, api_key="k", base_url="https://api.firecrawl.dev", url="https://x.com",
        want_screenshot=True,
    )
    assert page is not None
    assert page.markdown == "still here"
    assert page.screenshot_b64 is None


# --------------------------------------------------------------------------- #
# scrape: degrade to None
# --------------------------------------------------------------------------- #
async def test_scrape_transport_error_degrades_to_none() -> None:
    http = FakeHttp(post_exc=RuntimeError("connection reset"))
    page = await firecrawl_scrape(
        http, api_key="k", base_url="https://api.firecrawl.dev", url="https://x.com",
        want_screenshot=True,
    )
    assert page is None


async def test_scrape_http_error_degrades_to_none() -> None:
    http = FakeHttp(post_resp=_Resp(status_code=402, json_data={"error": "quota"}))
    page = await firecrawl_scrape(
        http, api_key="k", base_url="https://api.firecrawl.dev", url="https://x.com",
        want_screenshot=True,
    )
    assert page is None


async def test_scrape_non_json_degrades_to_none() -> None:
    http = FakeHttp(post_resp=_Resp(raise_json=True))
    page = await firecrawl_scrape(
        http, api_key="k", base_url="https://api.firecrawl.dev", url="https://x.com",
        want_screenshot=True,
    )
    assert page is None


async def test_scrape_empty_result_degrades_to_none() -> None:
    # No markdown and no screenshot -> nothing usable -> let the caller fall back.
    http = FakeHttp(post_resp=_ok_post({}))
    page = await firecrawl_scrape(
        http, api_key="k", base_url="https://api.firecrawl.dev", url="https://x.com",
        want_screenshot=True,
    )
    assert page is None


# --------------------------------------------------------------------------- #
# FirecrawlClient + factory + FakeFirecrawl
# --------------------------------------------------------------------------- #
async def test_client_scrape_delegates() -> None:
    http = FakeHttp(post_resp=_ok_post({"markdown": "hi"}))
    client = FirecrawlClient(api_key="fc-key", base_url="https://api.firecrawl.dev")
    page = await client.scrape(http, "https://x.com", want_screenshot=False)
    assert page is not None and page.markdown == "hi"
    assert http.posts[0]["headers"]["Authorization"] == "Bearer fc-key"


def test_client_blank_key_raises() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        FirecrawlClient(api_key="", base_url="https://api.firecrawl.dev")


def test_from_settings_keyless_degrades_to_none() -> None:
    settings = Settings(_env_file=None, app_env="dev")
    assert firecrawl_from_settings(settings) is None


def test_from_settings_with_key_builds_client() -> None:
    settings = Settings(_env_file=None, app_env="dev", firecrawl_api_key="fc-key")
    built = firecrawl_from_settings(settings)
    assert isinstance(built, FirecrawlClient)


async def test_fake_firecrawl_behaviour() -> None:
    fake = FakeFirecrawl(page=FirecrawlPage(markdown="# fake", screenshot_b64="c2hvdA=="))
    page = await fake.scrape(object(), "https://x.com", want_screenshot=True)  # type: ignore[arg-type]
    assert page is not None and page.screenshot_b64 == "c2hvdA=="
    assert fake.calls == 1 and fake.last_want_screenshot is True
    # want_screenshot=False drops the screenshot.
    page2 = await fake.scrape(object(), "https://x.com", want_screenshot=False)  # type: ignore[arg-type]
    assert page2 is not None and page2.screenshot_b64 is None
    # A None page exercises the degrade/fallback path.
    empty = FakeFirecrawl(page=None)
    assert await empty.scrape(object(), "https://x.com", want_screenshot=True) is None  # type: ignore[arg-type]
