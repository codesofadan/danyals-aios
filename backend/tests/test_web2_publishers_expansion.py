"""7B-4 unit gate: the Web 2.0 platform expansion (13 new real clients, the vault-
backed credential factory) - no network, no keys, no vault/DB.

Protocol conformance + construction-time key-gating are pinned for every new client
(mirrors ``test_web2_pipeline.py``'s existing coverage of the original three).
Real HTTP behaviour is pinned for a representative slice via ``httpx.MockTransport``
(the exact pattern ``test_content_providers.py`` already established for the
content-module seams) - enough to prove each platform's auth header/body shape is
wired correctly, not every platform's every edge case.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from integrations.errors import ProviderCallError, ProviderNotConfiguredError
from integrations.web2_credentials import build_publisher, vault_provider_for
from integrations.web2_publishers import (
    PLATFORM_CREDENTIAL_FIELDS,
    PLATFORM_DEVTO,
    PLATFORM_DREAMWIDTH,
    PLATFORM_GHOST,
    PLATFORM_GITHUB_PAGES,
    PLATFORM_GITLAB_PAGES,
    PLATFORM_HASHNODE,
    PLATFORM_HATENA,
    PLATFORM_LIVEJOURNAL,
    PLATFORM_MASTODON,
    PLATFORM_MATAROA,
    PLATFORM_MICROBLOG,
    PLATFORM_TELEGRAPH,
    PLATFORM_WRITEAS,
    WEB2_PLATFORMS,
    DevToClient,
    DreamwidthClient,
    GhostClient,
    GitHubPagesClient,
    GitLabPagesClient,
    HashnodeClient,
    HatenaBlogClient,
    LiveJournalClient,
    MastodonClient,
    MataroaClient,
    MicroBlogClient,
    TelegraPhClient,
    Web2Post,
    Web2Publisher,
    WriteAsClient,
)

pytestmark = pytest.mark.unit

Handler = Callable[[httpx.Request], httpx.Response]

_NEW_PLATFORMS = (
    PLATFORM_DEVTO, PLATFORM_WRITEAS, PLATFORM_TELEGRAPH, PLATFORM_MATAROA, PLATFORM_GHOST,
    PLATFORM_MASTODON, PLATFORM_GITHUB_PAGES, PLATFORM_GITLAB_PAGES, PLATFORM_MICROBLOG,
    PLATFORM_HASHNODE, PLATFORM_HATENA, PLATFORM_LIVEJOURNAL, PLATFORM_DREAMWIDTH,
)


def _post(**over: Any) -> Web2Post:
    body: dict[str, Any] = {
        "title": "Gentle Dental Cleanings",
        "body_html": "<h2>Why it matters</h2><p>Regular cleanings prevent decay.</p>"
        '<a href="https://client.example/services">our services</a>',
        "anchor": "our services", "target_url": "https://client.example/services",
        "slug": "gentle-dental-cleanings", "tags": ("dental",), "external_id": None,
    }
    body.update(over)
    return Web2Post(**body)


def _with_mock(client: Any, handler: Handler) -> None:
    """Swap a real client's httpx client for a MockTransport one, keeping its
    base_url + headers (mirrors tests/test_content_providers.py's helper)."""
    old = client._client
    client._client = httpx.Client(
        base_url=old.base_url, headers=old.headers, transport=httpx.MockTransport(handler)
    )


def _json_response(payload: dict[str, Any], status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


# --------------------------------------------------------------------------- #
# 1. The platform catalog itself.
# --------------------------------------------------------------------------- #
def test_seventeen_platforms_total() -> None:
    assert len(WEB2_PLATFORMS) == 17


def test_every_new_platform_has_credential_fields_documented() -> None:
    for platform in _NEW_PLATFORMS:
        assert platform in PLATFORM_CREDENTIAL_FIELDS
        assert PLATFORM_CREDENTIAL_FIELDS[platform]  # non-empty


# --------------------------------------------------------------------------- #
# 2. Construction-time key-gating: every real client refuses a blank credential.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("ctor", "kwargs"),
    [
        (DevToClient, {"api_key": ""}),
        (TelegraPhClient, {"access_token": ""}),
        (MataroaClient, {"api_key": ""}),
        (GhostClient, {"admin_api_key": "", "api_url": "https://x.ghost.io"}),
        (GhostClient, {"admin_api_key": "not-colon-separated", "api_url": "https://x.ghost.io"}),
        (GitHubPagesClient, {"token": "", "owner": "o", "repo": "r"}),
        (GitLabPagesClient, {"token": "", "project_id": "1"}),
        (HashnodeClient, {"pat": "", "publication_id": "p"}),
        (HatenaBlogClient, {"hatena_id": "", "blog_id": "b", "api_key": "k"}),
    ],
)
def test_a_blank_or_malformed_credential_refuses_to_construct(
    ctor: type, kwargs: dict[str, Any]
) -> None:
    with pytest.raises(ProviderNotConfiguredError):
        ctor(**kwargs)


@pytest.mark.parametrize("ctor", [LiveJournalClient, DreamwidthClient])
def test_journal_clients_refuse_a_blank_username_or_password(ctor: type) -> None:
    with pytest.raises(ProviderNotConfiguredError):
        ctor(username="", password="")
    with pytest.raises(ProviderNotConfiguredError):
        ctor(username="alice", password="")


def test_writeas_and_microblog_never_hard_refuse_construction() -> None:
    # Write.as's anonymous mode and Micro.blog's fixed-target guard both mean these
    # two are NOT key-gated the same way as the others - they must not raise here.
    WriteAsClient(token="", target="")
    MicroBlogClient(oauth_token="tok", target="micro.blog")


# --------------------------------------------------------------------------- #
# 3. Protocol conformance.
# --------------------------------------------------------------------------- #
def test_every_new_client_satisfies_web2publisher() -> None:
    assert isinstance(DevToClient(api_key="k"), Web2Publisher)
    assert isinstance(WriteAsClient(token="t", target="acme"), Web2Publisher)
    assert isinstance(TelegraPhClient(access_token="t"), Web2Publisher)
    assert isinstance(MataroaClient(api_key="k"), Web2Publisher)
    assert isinstance(GhostClient(admin_api_key="abc:646566", api_url="https://x.ghost.io"), Web2Publisher)
    assert isinstance(MastodonClient(oauth_token="t", target="https://mastodon.social"), Web2Publisher)
    assert isinstance(GitHubPagesClient(token="t", owner="o", repo="r"), Web2Publisher)
    assert isinstance(GitLabPagesClient(token="t", project_id="1"), Web2Publisher)
    assert isinstance(MicroBlogClient(oauth_token="t", target="micro.blog"), Web2Publisher)
    assert isinstance(HashnodeClient(pat="t", publication_id="p"), Web2Publisher)
    assert isinstance(HatenaBlogClient(hatena_id="h", blog_id="b", api_key="k"), Web2Publisher)
    assert isinstance(LiveJournalClient(username="u", password="p"), Web2Publisher)
    assert isinstance(DreamwidthClient(username="u", password="p"), Web2Publisher)


# --------------------------------------------------------------------------- #
# 4. Real HTTP behaviour via MockTransport - a representative slice.
# --------------------------------------------------------------------------- #
def test_devto_creates_and_returns_the_live_url() -> None:
    client = DevToClient(api_key="k")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["header"] = request.method, request.headers.get("api-key")
        seen["body"] = json.loads(request.content)
        return _json_response({"id": 42, "url": "https://dev.to/acme/gentle-dental-cleanings"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://dev.to/acme/gentle-dental-cleanings"
    assert result.verified is True and result.external_id == "42"
    assert seen["method"] == "POST" and seen["header"] == "k"
    assert seen["body"]["article"]["tags"] == ["dental"]


def test_devto_updates_when_external_id_is_set() -> None:
    client = DevToClient(api_key="k")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["path"] = request.method, request.url.path
        return _json_response({"id": 42, "url": "https://dev.to/acme/x"})

    _with_mock(client, handler)
    client.publish(client.platform, _post(external_id="42"))
    assert seen["method"] == "PUT" and seen["path"].endswith("/articles/42")


def test_telegraph_has_no_oauth_and_uses_form_params() -> None:
    client = TelegraPhClient(access_token="anon-token")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return _json_response({"ok": True, "result": {"path": "gentle-dental-1", "url": "https://telegra.ph/gentle-dental-1"}})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://telegra.ph/gentle-dental-1"
    assert result.verified is True
    assert seen["path"] == "/createPage"


def test_telegraph_surfaces_a_provider_error_on_ok_false() -> None:
    client = TelegraPhClient(access_token="anon-token")
    _with_mock(client, lambda req: _json_response({"ok": False, "error": "PAGE_ACCESS_DENIED"}))
    with pytest.raises(ProviderCallError):
        client.publish(client.platform, _post())


def test_ghost_signs_a_jwt_with_the_admin_key_and_publishes() -> None:
    client = GhostClient(admin_api_key="abc123:00112233445566778899aabbccddeeff", api_url="https://x.ghost.io")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        return _json_response({"posts": [{"id": "p1", "url": "https://x.ghost.io/gentle-dental/"}]})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://x.ghost.io/gentle-dental/"
    assert seen["auth"].startswith("Ghost ")  # a signed JWT, not a static bearer token


def test_mastodon_folds_title_and_link_into_one_status() -> None:
    client = MastodonClient(oauth_token="t", target="https://mastodon.social")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _json_response({"id": 99, "url": "https://mastodon.social/@acme/99"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://mastodon.social/@acme/99"
    assert "our services" in seen["body"]["status"]
    assert "https://client.example/services" in seen["body"]["status"]


def test_github_pages_commits_a_file_and_ensures_pages_enabled() -> None:
    client = GitHubPagesClient(token="t", owner="acme", repo="site")
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/pages"):
            return _json_response({}, status_code=204)
        return _json_response({"content": {"sha": "abc"}})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://acme.github.io/site/gentle-dental-cleanings/"
    assert result.verified is True
    assert any(m == "PUT" and "/contents/" in p for m, p in calls)
    assert any(p.endswith("/pages") for _m, p in calls)


def test_gitlab_pages_is_never_claimed_live_pending_ci() -> None:
    client = GitLabPagesClient(token="t", project_id="acme/site")
    _with_mock(client, lambda req: _json_response({"file_path": "x"}))
    result = client.publish(client.platform, _post())
    assert result.verified is False  # CI must still run; this client cannot confirm it


def test_hashnode_uses_the_raw_pat_not_bearer_prefixed() -> None:
    client = HashnodeClient(pat="raw-pat-value", publication_id="pub1")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        return _json_response({"data": {"publishPost": {"post": {"id": "h1", "url": "https://acme.hashnode.dev/gentle"}}}})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://acme.hashnode.dev/gentle"
    assert seen["auth"] == "raw-pat-value"  # NOT "Bearer raw-pat-value"


def test_hashnode_surfaces_graphql_errors() -> None:
    client = HashnodeClient(pat="t", publication_id="p")
    _with_mock(client, lambda req: _json_response({"errors": [{"message": "bad publicationId"}]}))
    with pytest.raises(ProviderCallError):
        client.publish(client.platform, _post())


def test_hatena_signs_http_basic_and_parses_the_atom_response() -> None:
    client = HatenaBlogClient(hatena_id="acme", blog_id="acme.hatenablog.com", api_key="k")
    atom = (
        '<?xml version="1.0"?><entry xmlns="http://www.w3.org/2005/Atom">'
        '<id>tag:blog.hatena.ne.jp,2013:blog-acme-12345-67890</id>'
        '<link rel="alternate" href="https://acme.hatenablog.com/entry/1"/></entry>'
    )
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(201, text=atom, headers={"Content-Type": "application/atom+xml"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://acme.hatenablog.com/entry/1"
    assert seen["auth"].startswith("Basic ")  # HTTP Basic, not bearer


def test_journal_protocol_client_calls_postevent_and_builds_the_permalink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LiveJournal/Dreamwidth go over stdlib xmlrpc, not httpx - mock the ServerProxy."""
    fake_proxy = MagicMock()
    fake_proxy.LJ.XMLRPC.postevent.return_value = {"itemid": 7, "anum": 3}
    monkeypatch.setattr("xmlrpc.client.ServerProxy", lambda *_a, **_k: fake_proxy)

    client = LiveJournalClient(username="acme", password="secret")
    result = client.publish(client.platform, _post(external_id=None))
    assert result.external_id == "7"
    assert result.post_url == "https://acme.livejournal.com/1795.html"  # 7*256+3
    called_event = fake_proxy.LJ.XMLRPC.postevent.call_args[0][0]
    assert called_event["password"] == "secret"  # never logged, just asserted here


def test_journal_protocol_client_edits_when_external_id_present(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_proxy = MagicMock()
    fake_proxy.LJ.XMLRPC.editevent.return_value = {"itemid": 7, "anum": 3, "url": "https://acme.dreamwidth.org/7.html"}
    monkeypatch.setattr("xmlrpc.client.ServerProxy", lambda *_a, **_k: fake_proxy)

    client = DreamwidthClient(username="acme", password="secret")
    result = client.publish(client.platform, _post(external_id="7"))
    assert result.post_url == "https://acme.dreamwidth.org/7.html"
    fake_proxy.LJ.XMLRPC.editevent.assert_called_once()
    fake_proxy.LJ.XMLRPC.postevent.assert_not_called()


# --------------------------------------------------------------------------- #
# 5. The vault-backed credential factory (integrations/web2_credentials.py).
# --------------------------------------------------------------------------- #
def test_vault_provider_naming_convention() -> None:
    assert vault_provider_for("WordPress.com") == "web2:WordPress.com"


def test_build_publisher_degrades_to_none_without_a_vault_row() -> None:
    publisher = build_publisher(client_id="cl-1", platform=PLATFORM_DEVTO, lookup=lambda **_k: None)
    assert publisher is None


def test_build_publisher_degrades_to_none_on_malformed_json() -> None:
    publisher = build_publisher(client_id="cl-1", platform=PLATFORM_DEVTO, lookup=lambda **_k: "{not json")
    assert publisher is None


def test_build_publisher_degrades_to_none_on_incomplete_credential() -> None:
    # api_key is required; an empty one raises inside DevToClient.__init__, which the
    # factory catches (not lets crash the worker).
    publisher = build_publisher(
        client_id="cl-1", platform=PLATFORM_DEVTO, lookup=lambda **_k: json.dumps({"api_key": ""})
    )
    assert publisher is None


def test_build_publisher_degrades_to_none_for_medium() -> None:
    # Medium has no builder at all - draft-only, no live publisher can exist.
    publisher = build_publisher(client_id="cl-1", platform="Medium", lookup=lambda **_k: "{}")
    assert publisher is None


def test_build_publisher_constructs_the_real_client_when_the_vault_row_is_complete() -> None:
    seen: dict[str, Any] = {}

    def lookup(*, provider: str, label: str) -> str | None:
        seen["provider"], seen["label"] = provider, label
        return json.dumps({"api_key": "real-key"})

    publisher = build_publisher(client_id="cl-42", platform=PLATFORM_DEVTO, lookup=lookup)
    assert isinstance(publisher, DevToClient)
    assert seen == {"provider": "web2:dev.to", "label": "cl-42"}
