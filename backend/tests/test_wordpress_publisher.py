"""Unit gate for the AIOS Publisher plugin seam (``integrations.wordpress_publisher``).

Fakes the HTTP client (the real seam extends ``HttpProviderClient``, whose httpx
``Client`` we swap for a recorder) to prove, with NO network:

* ``publish`` POSTs the shared key IN THE BODY (the header-strip bypass) + the payload
  to the plugin's ``/wp-json/aios/v1/publish`` endpoint and parses the result;
* a non-``ok`` / HTTP-error response raises the typed ``WordPressPluginError`` (which
  the publish path swallows);
* ``ping`` is True only on a genuine ``ok`` and False on any failure (never raises);
* ``resolve_plugin_target`` resolves {site_url, api_key} from a source_pack + defaults;
* the offline ``FakeWordPressPluginPublisher`` records the payload + returns URLs.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from integrations.wordpress_publisher import (
    FakeWordPressPluginPublisher,
    PluginPublishResult,
    WordPressPluginError,
    WordPressPluginPublisher,
    WpPluginTarget,
    resolve_plugin_target,
)

pytestmark = pytest.mark.unit


class _FakeResponse:
    """A minimal httpx-response stand-in for ``HttpProviderClient._once``."""

    def __init__(self, status_code: int, payload: dict[str, Any], url: str = "https://x/y") -> None:
        self.status_code = status_code
        self._payload = payload
        self.request = SimpleNamespace(url=url)

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHttpxClient:
    """Records every request and returns a canned response (no network)."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json: Any = None,
        auth: Any = None,
    ) -> _FakeResponse:
        self.calls.append({"method": method, "url": url, "params": params, "json": json, "auth": auth})
        return self._response

    def close(self) -> None:
        return None


def _publisher(response: _FakeResponse, *, api_key: str = "SECRET-KEY") -> tuple[Any, _FakeHttpxClient]:
    pub = WordPressPluginPublisher(site_url="https://site.test/", api_key=api_key)
    fake = _FakeHttpxClient(response)
    pub._client = fake  # swap the real httpx client for the recorder
    return pub, fake


# --------------------------------------------------------------------------- #
# publish: key-in-body + right URL + parsed result
# --------------------------------------------------------------------------- #
def test_publish_posts_key_and_payload_to_the_right_url() -> None:
    pub, fake = _publisher(
        _FakeResponse(
            201,
            {
                "ok": True,
                "post_id": 42,
                "url": "https://site.test/?p=42",
                "edit_url": "https://site.test/wp-admin/post.php?post=42&action=edit",
                "preview_url": "https://site.test/?p=42&preview=true",
                "status": "draft",
            },
        )
    )

    result = pub.publish({"title": "Hi there", "content": "<p>x</p>", "slug": "hi-there", "status": "draft"})

    call = fake.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://site.test/wp-json/aios/v1/publish"
    # The shared key rides in the BODY (primary auth - survives header stripping).
    assert call["json"]["api_key"] == "SECRET-KEY"
    assert call["json"]["title"] == "Hi there"
    assert call["json"]["content"] == "<p>x</p>"
    assert call["auth"] is None  # NOT HTTP Basic - this is the key-in-body path
    # The result is parsed off the response.
    assert isinstance(result, PluginPublishResult)
    assert result.post_id == 42
    assert result.url == "https://site.test/?p=42"
    assert result.edit_url.endswith("action=edit")
    assert result.status == "draft"


def test_publish_strips_none_values_but_always_sends_key() -> None:
    pub, fake = _publisher(_FakeResponse(201, {"ok": True, "post_id": 7, "url": "u", "edit_url": "e", "status": "draft"}))
    pub.publish({"title": "T", "excerpt": None, "slug": "t"})
    body = fake.calls[0]["json"]
    assert "excerpt" not in body  # None dropped
    assert body["api_key"] == "SECRET-KEY"  # key still injected


def test_publish_raises_on_not_ok_response() -> None:
    pub, _fake = _publisher(_FakeResponse(200, {"ok": False, "post_id": 1}))
    with pytest.raises(WordPressPluginError):
        pub.publish({"title": "x"})


def test_publish_raises_on_http_error() -> None:
    # A 400 is non-transient -> immediate ProviderCallError -> re-typed as the seam error.
    pub, _fake = _publisher(_FakeResponse(400, {"error": "bad request"}))
    with pytest.raises(WordPressPluginError):
        pub.publish({"title": "x"})


def test_publish_error_message_never_contains_the_key() -> None:
    pub, _fake = _publisher(_FakeResponse(400, {"error": "bad"}), api_key="TOP-SECRET-123")
    with pytest.raises(WordPressPluginError) as excinfo:
        pub.publish({"title": "x"})
    assert "TOP-SECRET-123" not in str(excinfo.value)


# --------------------------------------------------------------------------- #
# ping: True only on ok, False on failure, never raises
# --------------------------------------------------------------------------- #
def test_ping_true_on_ok() -> None:
    pub, fake = _publisher(_FakeResponse(200, {"ok": True}, url="https://site.test/wp-json/aios/v1/ping"))
    assert pub.ping() is True
    call = fake.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "https://site.test/wp-json/aios/v1/ping"
    assert call["params"] == {"api_key": "SECRET-KEY"}  # key via query (stripped from logs)


def test_ping_false_on_auth_error() -> None:
    pub, _fake = _publisher(_FakeResponse(401, {"code": "aios_publisher_forbidden"}))
    assert pub.ping() is False  # never raises


def test_ping_false_on_not_ok() -> None:
    pub, _fake = _publisher(_FakeResponse(200, {"ok": False}))
    assert pub.ping() is False


# --------------------------------------------------------------------------- #
# construction guard
# --------------------------------------------------------------------------- #
def test_construct_without_key_or_site_raises() -> None:
    from integrations.errors import ProviderNotConfiguredError

    with pytest.raises(ProviderNotConfiguredError):
        WordPressPluginPublisher(site_url="", api_key="K")
    with pytest.raises(ProviderNotConfiguredError):
        WordPressPluginPublisher(site_url="https://s.test", api_key="")


# --------------------------------------------------------------------------- #
# resolve_plugin_target / WpPluginTarget
# --------------------------------------------------------------------------- #
def test_resolve_target_from_source_pack_and_key() -> None:
    target = resolve_plugin_target({"wp_site_url": "https://s.test"}, default_api_key="KEY")
    assert isinstance(target, WpPluginTarget)
    assert target.site_url == "https://s.test"
    assert target.api_key == "KEY"


def test_resolve_target_none_without_key() -> None:
    assert resolve_plugin_target({"wp_site_url": "https://s.test"}) is None


def test_resolve_target_none_without_site() -> None:
    assert resolve_plugin_target({}, default_api_key="KEY") is None
    assert resolve_plugin_target(None, default_api_key="KEY") is None


def test_resolve_target_uses_default_site_url() -> None:
    target = resolve_plugin_target({}, default_site_url="https://d.test", default_api_key="KEY")
    assert target is not None
    assert target.site_url == "https://d.test"


def test_wp_plugin_target_builds_a_publisher() -> None:
    target = WpPluginTarget(site_url="https://s.test", api_key="KEY")
    pub = target.publisher()
    assert isinstance(pub, WordPressPluginPublisher)


# --------------------------------------------------------------------------- #
# FakeWordPressPluginPublisher (offline)
# --------------------------------------------------------------------------- #
def test_fake_publisher_records_payload_and_returns_urls() -> None:
    fake = FakeWordPressPluginPublisher(site_url="https://s.test")
    result = fake.publish({"title": "Hello World", "slug": "hello-world", "status": "draft"})
    assert fake.published[0]["title"] == "Hello World"
    assert result.post_id > 0
    assert result.edit_url.startswith("https://s.test/wp-admin/")
    assert result.url.startswith("https://s.test/")
    assert result.status == "draft"


def test_fake_publisher_ping_flag() -> None:
    assert FakeWordPressPluginPublisher(healthy=True).ping() is True
    assert FakeWordPressPluginPublisher(healthy=False).ping() is False


# --------------------------------------------------------------------------- #
# deliver_site: whole-site delivery (plugin 1.9.0)
# --------------------------------------------------------------------------- #
_MANIFEST: dict[str, Any] = {
    "ok": True,
    "pages": [{"slug": "home", "ok": True, "id": 11, "created": True,
               "elementor": True, "url": "https://site.test/home/"}],
    "parents": 1,
    "menu": {"built": True, "menu_id": 7, "items": 1, "assigned": True, "held": ""},
    "front_page": {"changed": True, "page_id": 11},
}


def test_deliver_site_posts_the_plan_to_the_site_route() -> None:
    pub, fake = _publisher(_FakeResponse(200, _MANIFEST))
    pub.deliver_site({"pages": [{"slug": "home"}], "status": "draft"})
    call = fake.calls[-1]
    assert call["url"] == "https://site.test/wp-json/aios/v1/site"
    assert call["json"]["api_key"] == "SECRET-KEY", "key rides the BODY, never stripped"
    assert call["json"]["pages"][0]["slug"] == "home"


def test_deliver_site_returns_the_manifest_verbatim() -> None:
    """NOT reduced to a boolean. A delivery can partly succeed - one page failing while
    forty-nine land - and collapsing that to False throws away which one, while
    collapsing it to True hides it entirely."""
    pub, _fake = _publisher(_FakeResponse(200, _MANIFEST))
    out = pub.deliver_site({"pages": [{"slug": "home"}]})
    assert out["parents"] == 1
    assert out["menu"]["items"] == 1
    assert out["front_page"]["page_id"] == 11


def test_an_older_plugin_is_named_rather_than_reported_as_a_transport_failure() -> None:
    """"the site was not delivered" is not actionable; "this site runs a plugin without
    /site" tells the operator exactly what to do."""
    pub, _fake = _publisher(_FakeResponse(404, {"code": "rest_no_route"}))
    with pytest.raises(WordPressPluginError, match=r"1\.9\.0 or newer"):
        pub.deliver_site({"pages": [{"slug": "home"}]})


def test_a_non_ok_manifest_raises() -> None:
    pub, _fake = _publisher(_FakeResponse(200, {"ok": False}))
    with pytest.raises(WordPressPluginError):
        pub.deliver_site({"pages": [{"slug": "home"}]})


def test_the_error_never_echoes_the_key() -> None:
    pub, _fake = _publisher(_FakeResponse(500, {"error": "boom"}), api_key="SUPER-SECRET")
    with pytest.raises(WordPressPluginError) as exc:
        pub.deliver_site({"pages": [{"slug": "home"}]})
    assert "SUPER-SECRET" not in str(exc.value)


class TestTheFakeBehavesLikeTheRealAssembler:
    """A fake that always succeeds lets a caller ship code that never handles a partial
    delivery."""

    def _fake(self) -> Any:
        from integrations.wordpress_publisher import FakeWordPressPluginPublisher

        return FakeWordPressPluginPublisher(site_url="https://site.test")

    def test_a_page_with_no_slug_is_dropped_exactly_as_the_plugin_drops_it(self) -> None:
        out = self._fake().deliver_site(
            {"pages": [{"slug": "home"}, {"title": "no slug"}]}
        )
        assert len(out["pages"]) == 1

    def test_the_front_page_only_changes_when_the_plan_names_one(self) -> None:
        out = self._fake().deliver_site({"pages": [{"slug": "home"}]})
        assert out["front_page"]["changed"] is False

    def test_a_named_front_page_changes(self) -> None:
        out = self._fake().deliver_site(
            {"pages": [{"slug": "home"}], "front_page_slug": "home"}
        )
        assert out["front_page"]["changed"] is True

    def test_ids_are_stable_across_runs(self) -> None:
        a = self._fake().deliver_site({"pages": [{"slug": "home"}]})
        b = self._fake().deliver_site({"pages": [{"slug": "home"}]})
        assert a["pages"][0]["id"] == b["pages"][0]["id"]

    def test_it_records_what_it_was_asked_to_deliver(self) -> None:
        fake = self._fake()
        fake.deliver_site({"pages": [{"slug": "home"}]})
        assert fake.delivered and fake.delivered[0]["pages"][0]["slug"] == "home"
