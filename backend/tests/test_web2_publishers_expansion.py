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
    PLATFORM_BLUESKY,
    PLATFORM_CODEBERG_PAGES,
    PLATFORM_CREDENTIAL_FIELDS,
    PLATFORM_DEVTO,
    PLATFORM_DISQUS,
    PLATFORM_DPASTE,
    PLATFORM_DREAMWIDTH,
    PLATFORM_DRUPAL,
    PLATFORM_FC2,
    PLATFORM_FIGSHARE,
    PLATFORM_GHOST,
    PLATFORM_GITHUB_GIST,
    PLATFORM_GITHUB_PAGES,
    PLATFORM_GITLAB_PAGES,
    PLATFORM_GITLAB_SNIPPETS,
    PLATFORM_GRAVATAR,
    PLATFORM_HACKMD,
    PLATFORM_HASHNODE,
    PLATFORM_HATENA,
    PLATFORM_HUBSPOT,
    PLATFORM_INTERNET_ARCHIVE,
    PLATFORM_JOOMLA,
    PLATFORM_LEMMY,
    PLATFORM_LIVEDOOR,
    PLATFORM_LIVEJOURNAL,
    PLATFORM_MASTODON,
    PLATFORM_MATAROA,
    PLATFORM_MICROBLOG,
    PLATFORM_MINDS,
    PLATFORM_MISSKEY,
    PLATFORM_NEOCITIES,
    PLATFORM_NETLIFY,
    PLATFORM_NOTION,
    PLATFORM_OSF,
    PLATFORM_PASTE_EE,
    PLATFORM_PASTEBIN,
    PLATFORM_PIXELFED,
    PLATFORM_PLURK,
    PLATFORM_RENTRY,
    PLATFORM_SEESAA,
    PLATFORM_SOURCEHUT_PAGES,
    PLATFORM_TELEGRAPH,
    PLATFORM_WARPCAST,
    PLATFORM_WEBFLOW,
    PLATFORM_WHITEWIND,
    PLATFORM_WRITEAS,
    PLATFORM_ZENODO,
    WEB2_PLATFORMS,
    BlueskyClient,
    CodebergPagesClient,
    DevToClient,
    DisqusClient,
    DpasteClient,
    DreamwidthClient,
    DrupalClient,
    FC2BlogClient,
    FigshareClient,
    GhostClient,
    GitHubGistClient,
    GitHubPagesClient,
    GitLabPagesClient,
    GitLabSnippetsClient,
    GravatarClient,
    HackMDClient,
    HashnodeClient,
    HatenaBlogClient,
    HubSpotClient,
    InternetArchiveClient,
    JoomlaClient,
    LemmyClient,
    LivedoorBlogClient,
    LiveJournalClient,
    MastodonClient,
    MataroaClient,
    MicroBlogClient,
    MindsClient,
    MisskeyClient,
    NeocitiesClient,
    NetlifyClient,
    NotionClient,
    OSFClient,
    PastebinClient,
    PasteEeClient,
    PixelfedClient,
    PlurkClient,
    RentryClient,
    SeesaaBlogClient,
    SourcehutPagesClient,
    TelegraPhClient,
    WarpcastClient,
    Web2Post,
    Web2Publisher,
    WebflowClient,
    WhiteWindClient,
    WriteAsClient,
    ZenodoClient,
)

pytestmark = pytest.mark.unit

Handler = Callable[[httpx.Request], httpx.Response]

_NEW_PLATFORMS = (
    PLATFORM_DEVTO, PLATFORM_WRITEAS, PLATFORM_TELEGRAPH, PLATFORM_MATAROA, PLATFORM_GHOST,
    PLATFORM_MASTODON, PLATFORM_GITHUB_PAGES, PLATFORM_GITLAB_PAGES, PLATFORM_MICROBLOG,
    PLATFORM_HASHNODE, PLATFORM_HATENA, PLATFORM_LIVEJOURNAL, PLATFORM_DREAMWIDTH,
)
# The 4 newest adapters (real CMS/site-builder clients, added after the original 17).
_NEWEST_PLATFORMS = (PLATFORM_WEBFLOW, PLATFORM_HUBSPOT, PLATFORM_DRUPAL, PLATFORM_JOOMLA)
# Third pass (19 more, Aug 2026) - see web2_publishers.py's module docstring. Two of
# these (rentry.co/dpaste.org) are fully ANONYMOUS - no credential fields at all - so
# they are tracked separately from the "every platform has non-empty credential
# fields" assertion below.
_BATCH3_PLATFORMS = (
    PLATFORM_HACKMD, PLATFORM_GITHUB_GIST, PLATFORM_GITLAB_SNIPPETS, PLATFORM_PASTE_EE,
    PLATFORM_PASTEBIN, PLATFORM_NETLIFY, PLATFORM_NEOCITIES, PLATFORM_MISSKEY, PLATFORM_LEMMY,
    PLATFORM_BLUESKY, PLATFORM_WHITEWIND, PLATFORM_DISQUS, PLATFORM_PLURK, PLATFORM_PIXELFED,
    PLATFORM_NOTION, PLATFORM_GRAVATAR, PLATFORM_MINDS,
)
_ANONYMOUS_PLATFORMS = (PLATFORM_RENTRY, PLATFORM_DPASTE)
# Fourth pass (10 more, Aug 2026) - see web2_publishers.py's module docstring.
_BATCH4_PLATFORMS = (
    PLATFORM_ZENODO, PLATFORM_INTERNET_ARCHIVE, PLATFORM_OSF, PLATFORM_FIGSHARE,
    PLATFORM_CODEBERG_PAGES, PLATFORM_LIVEDOOR, PLATFORM_FC2, PLATFORM_SEESAA,
    PLATFORM_WARPCAST, PLATFORM_SOURCEHUT_PAGES,
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
def test_fifty_platforms_total() -> None:
    assert len(WEB2_PLATFORMS) == 50


def test_every_new_platform_has_credential_fields_documented() -> None:
    for platform in _NEW_PLATFORMS + _NEWEST_PLATFORMS + _BATCH3_PLATFORMS + _BATCH4_PLATFORMS:
        assert platform in PLATFORM_CREDENTIAL_FIELDS
        assert PLATFORM_CREDENTIAL_FIELDS[platform]  # non-empty


def test_anonymous_platforms_have_no_credential_fields() -> None:
    # rentry.co / dpaste.org need no vault credential fields at all - anonymous.
    for platform in _ANONYMOUS_PLATFORMS:
        assert platform in PLATFORM_CREDENTIAL_FIELDS
        assert PLATFORM_CREDENTIAL_FIELDS[platform] == ()


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
        (WebflowClient, {"api_token": "", "collection_id": "c", "site": "s"}),
        (HubSpotClient, {"access_token": "", "content_group_id": "g"}),
        (DrupalClient, {"base_url": "https://x.example", "username": "", "password": "p"}),
        (JoomlaClient, {"base_url": "https://x.example", "api_token": "", "catid": "1"}),
        (HackMDClient, {"token": ""}),
        (GitHubGistClient, {"token": ""}),
        (GitLabSnippetsClient, {"token": ""}),
        (PasteEeClient, {"api_key": ""}),
        (PastebinClient, {"api_dev_key": ""}),
        (NetlifyClient, {"api_token": "", "site_id": "s"}),
        (NeocitiesClient, {"api_key": "", "sitename": "s"}),
        (MisskeyClient, {"token": ""}),
        (LemmyClient, {"username": "", "password": "p", "community": "c"}),
        (BlueskyClient, {"identifier": "", "app_password": "p"}),
        (WhiteWindClient, {"identifier": "", "app_password": "p"}),
        (DisqusClient, {"access_token": "", "api_key": "k", "username": "u"}),
        (
            PlurkClient,
            {"consumer_key": "", "consumer_secret": "cs", "access_token": "at", "access_token_secret": "ats"},
        ),
        (PixelfedClient, {"access_token": "", "placeholder_image_url": "https://cdn.example/brand.jpg"}),
        (NotionClient, {"integration_token": "", "parent_page_id": "p"}),
        (GravatarClient, {"api_token": "", "username": "u"}),
        (MindsClient, {"access_token": ""}),
        (ZenodoClient, {"access_token": ""}),
        (InternetArchiveClient, {"access_key": "", "secret_key": "sk"}),
        (OSFClient, {"access_token": ""}),
        (FigshareClient, {"access_token": ""}),
        (CodebergPagesClient, {"token": "", "owner": "o", "repo": "r"}),
        (LivedoorBlogClient, {"livedoor_id": "", "blog_name": "b", "api_key": "k"}),
        (WarpcastClient, {"api_key": "", "signer_uuid": "s"}),
        (SourcehutPagesClient, {"token": "", "domain": "d"}),
    ],
)
def test_a_blank_or_malformed_credential_refuses_to_construct(
    ctor: type, kwargs: dict[str, Any]
) -> None:
    with pytest.raises(ProviderNotConfiguredError):
        ctor(**kwargs)


def test_rentry_and_dpaste_never_hard_refuse_construction() -> None:
    # Fully anonymous - no credential to be blank in the first place.
    RentryClient()
    DpasteClient()


@pytest.mark.parametrize("ctor", [LiveJournalClient, DreamwidthClient])
def test_journal_clients_refuse_a_blank_username_or_password(ctor: type) -> None:
    with pytest.raises(ProviderNotConfiguredError):
        ctor(username="", password="")
    with pytest.raises(ProviderNotConfiguredError):
        ctor(username="alice", password="")


@pytest.mark.parametrize("ctor", [FC2BlogClient, SeesaaBlogClient])
def test_metaweblog_clients_refuse_a_blank_blog_id_or_credential(ctor: type) -> None:
    with pytest.raises(ProviderNotConfiguredError):
        ctor(blog_id="", username="alice", password="secret")
    with pytest.raises(ProviderNotConfiguredError):
        ctor(blog_id="42", username="", password="secret")
    with pytest.raises(ProviderNotConfiguredError):
        ctor(blog_id="42", username="alice", password="")


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
    assert isinstance(WebflowClient(api_token="t", collection_id="c", site="s"), Web2Publisher)
    assert isinstance(HubSpotClient(access_token="t", content_group_id="g"), Web2Publisher)
    assert isinstance(
        DrupalClient(base_url="https://x.example", username="u", password="p"), Web2Publisher
    )
    assert isinstance(
        JoomlaClient(base_url="https://x.example", api_token="t", catid="1"), Web2Publisher
    )


def test_batch3_clients_satisfy_web2publisher() -> None:
    assert isinstance(HackMDClient(token="t"), Web2Publisher)
    assert isinstance(GitHubGistClient(token="t"), Web2Publisher)
    assert isinstance(GitLabSnippetsClient(token="t"), Web2Publisher)
    assert isinstance(PasteEeClient(api_key="k"), Web2Publisher)
    assert isinstance(PastebinClient(api_dev_key="k"), Web2Publisher)
    assert isinstance(NetlifyClient(api_token="t", site_id="s"), Web2Publisher)
    assert isinstance(NeocitiesClient(api_key="k", sitename="s"), Web2Publisher)
    assert isinstance(RentryClient(), Web2Publisher)
    assert isinstance(DpasteClient(), Web2Publisher)
    assert isinstance(MisskeyClient(token="t"), Web2Publisher)
    assert isinstance(LemmyClient(username="u", password="p", community="c"), Web2Publisher)
    assert isinstance(BlueskyClient(identifier="i", app_password="p"), Web2Publisher)
    assert isinstance(WhiteWindClient(identifier="i", app_password="p"), Web2Publisher)
    assert isinstance(DisqusClient(access_token="t", api_key="k", username="u"), Web2Publisher)
    assert isinstance(
        PlurkClient(consumer_key="ck", consumer_secret="cs", access_token="at", access_token_secret="ats"),
        Web2Publisher,
    )
    assert isinstance(
        PixelfedClient(access_token="t", placeholder_image_url="https://cdn.example/brand.jpg"), Web2Publisher
    )
    assert isinstance(NotionClient(integration_token="t", parent_page_id="p"), Web2Publisher)
    assert isinstance(GravatarClient(api_token="t", username="u"), Web2Publisher)
    assert isinstance(MindsClient(access_token="t"), Web2Publisher)


def test_batch4_clients_satisfy_web2publisher() -> None:
    assert isinstance(ZenodoClient(access_token="t"), Web2Publisher)
    assert isinstance(InternetArchiveClient(access_key="ak", secret_key="sk"), Web2Publisher)
    assert isinstance(OSFClient(access_token="t"), Web2Publisher)
    assert isinstance(FigshareClient(access_token="t"), Web2Publisher)
    assert isinstance(CodebergPagesClient(token="t", owner="o", repo="r"), Web2Publisher)
    assert isinstance(LivedoorBlogClient(livedoor_id="l", blog_name="b", api_key="k"), Web2Publisher)
    assert isinstance(FC2BlogClient(blog_id="1", username="u", password="p"), Web2Publisher)
    assert isinstance(SeesaaBlogClient(blog_id="1", username="u", password="p"), Web2Publisher)
    assert isinstance(WarpcastClient(api_key="k", signer_uuid="s"), Web2Publisher)
    assert isinstance(SourcehutPagesClient(token="t", domain="d"), Web2Publisher)


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


def test_webflow_writes_the_item_then_publishes_it() -> None:
    client = WebflowClient(api_token="t", collection_id="col1", site="acme")
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/publish"):
            return _json_response({"itemIds": ["item1"]})
        return _json_response({"id": "item1"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://acme.webflow.io/blog/gentle-dental-cleanings"
    assert result.verified is True and result.external_id == "item1"
    assert any(m == "POST" and p.endswith("/items") for m, p in calls)
    assert any(m == "POST" and p.endswith("/publish") for m, p in calls)


def test_hubspot_creates_a_post_against_the_content_group() -> None:
    client = HubSpotClient(access_token="t", content_group_id="grp1")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["auth"] = request.method, request.headers.get("Authorization", "")
        seen["body"] = json.loads(request.content)
        return _json_response({"id": 55, "url": "https://acme.hubspotpagebuilder.com/blog/gentle"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://acme.hubspotpagebuilder.com/blog/gentle"
    assert result.verified is True and result.external_id == "55"
    assert seen["method"] == "POST" and seen["auth"] == "Bearer t"
    assert seen["body"]["contentGroupId"] == "grp1"


def test_drupal_signs_http_basic_and_resolves_the_node_path() -> None:
    client = DrupalClient(base_url="https://acme.example", username="api-bot", password="secret")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["auth"] = request.method, request.headers.get("Authorization", "")
        seen["path"] = request.url.path
        return _json_response(
            {
                "data": {
                    "id": "node-uuid-1",
                    "attributes": {"path": {"alias": "/gentle-dental-cleanings"}},
                }
            }
        )

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://acme.example/gentle-dental-cleanings"
    assert result.verified is True and result.external_id == "node-uuid-1"
    assert seen["method"] == "POST" and seen["path"] == "/jsonapi/node/article"
    assert seen["auth"].startswith("Basic ")  # HTTP Basic, not bearer


def test_joomla_falls_back_to_the_non_sef_permalink() -> None:
    client = JoomlaClient(base_url="https://acme.example", api_token="t", catid="7")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["auth"] = request.method, request.headers.get("Authorization", "")
        seen["path"] = request.url.path
        return _json_response({"data": {"id": "12", "attributes": {}}})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://acme.example/index.php?option=com_content&view=article&id=12"
    assert result.verified is True and result.external_id == "12"
    assert seen["method"] == "POST" and seen["path"] == "/api/index.php/v1/content/articles"
    assert seen["auth"] == "Bearer t"


# --------------------------------------------------------------------------- #
# 4b. Batch3 real HTTP behaviour via MockTransport - one test per new client.
# --------------------------------------------------------------------------- #
def test_hackmd_creates_a_public_note() -> None:
    client = HackMDClient(token="t")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return _json_response({"id": "note1", "publishLink": "https://hackmd.io/@acme/note1"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://hackmd.io/@acme/note1"
    assert seen["auth"] == "Bearer t"
    assert seen["body"]["readPermission"] == "guest"


def test_github_gist_creates_a_public_gist() -> None:
    client = GitHubGistClient(token="t")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _json_response({"id": "g1", "html_url": "https://gist.github.com/acme/g1"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://gist.github.com/acme/g1"
    assert seen["body"]["public"] is True


def test_gitlab_snippets_creates_a_public_snippet() -> None:
    client = GitLabSnippetsClient(token="t")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["header"] = request.headers.get("PRIVATE-TOKEN")
        return _json_response({"id": 5, "web_url": "https://gitlab.com/-/snippets/5"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://gitlab.com/-/snippets/5"
    assert seen["header"] == "t"


def test_paste_ee_creates_a_paste_and_ignores_external_id() -> None:
    client = PasteEeClient(api_key="k")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("X-Auth-Token")
        return _json_response({"id": "p1", "link": "https://paste.ee/p/p1"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id="ignored"))
    assert result.post_url == "https://paste.ee/p/p1"
    assert seen["auth"] == "k"


def test_pastebin_uses_form_params_and_returns_a_bare_text_url() -> None:
    client = PastebinClient(api_dev_key="k")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(200, text="https://pastebin.com/abc123")

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://pastebin.com/abc123"
    assert "api_dev_key=k" in seen["body"]


def test_netlify_uploads_the_file_only_when_the_digest_is_required() -> None:
    client = NetlifyClient(api_token="t", site_id="site1")
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/deploys") and request.method == "POST":
            body = json.loads(request.content)
            digest = body["files"]["/index.html"]
            return _json_response({"id": "deploy1", "required": [digest], "ssl_url": "https://acme.netlify.app"})
        return httpx.Response(200, json={"id": "index.html"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://acme.netlify.app"
    assert any(m == "PUT" and "/files/index.html" in p for m, p in calls)


def test_neocities_uploads_a_static_file() -> None:
    client = NeocitiesClient(api_key="k", sitename="acme")
    _with_mock(client, lambda req: _json_response({"result": "success"}))
    result = client.publish(client.platform, _post())
    assert result.post_url.startswith("https://acme.neocities.org/")


def test_rentry_fetches_a_csrf_cookie_then_posts_anonymously() -> None:
    client = RentryClient()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/":
            return httpx.Response(200, headers={"set-cookie": "csrftoken=tok123; Path=/"})
        return _json_response(
            {"status": "200", "content": {"url": "https://rentry.co/abc123", "edit_code": "xyz"}}
        )

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://rentry.co/abc123"
    assert result.external_id == "https://rentry.co/abc123:xyz"
    assert calls[0] == "GET /"


def test_dpaste_is_fully_anonymous_and_returns_a_bare_url() -> None:
    client = DpasteClient()
    _with_mock(client, lambda req: httpx.Response(200, text="https://dpaste.org/abc123\n"))
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://dpaste.org/abc123"


def test_misskey_puts_the_token_in_the_json_body_not_a_header() -> None:
    client = MisskeyClient(token="t")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth_header"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return _json_response({"createdNote": {"id": "n1"}})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://misskey.io/notes/n1"
    assert seen["auth_header"] is None
    assert seen["body"]["i"] == "t"


def test_lemmy_logs_in_resolves_the_community_then_posts_a_link_post() -> None:
    client = LemmyClient(username="u", password="p", community="seo")
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v3/user/login":
            return _json_response({"jwt": "jwt1"})
        if request.url.path == "/api/v3/community":
            return _json_response({"community_view": {"community": {"id": 7}}})
        return _json_response({"post_view": {"post": {"id": 99, "ap_id": "https://lemmy.world/post/99"}}})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://lemmy.world/post/99"
    assert any(p == "/api/v3/user/login" for _m, p in calls)
    assert any(p == "/api/v3/community" for _m, p in calls)


def test_bluesky_logs_in_then_creates_a_record_with_a_link_facet() -> None:
    client = BlueskyClient(identifier="acme.bsky.social", app_password="app-pass")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("createSession"):
            return _json_response({"accessJwt": "jwt1", "did": "did:plc:acme"})
        seen["body"] = json.loads(request.content)
        return _json_response({"uri": "at://did:plc:acme/app.bsky.feed.post/abc123"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://bsky.app/profile/did:plc:acme/post/abc123"
    assert seen["body"]["record"]["facets"][0]["features"][0]["uri"] == "https://client.example/services"


def test_whitewind_reuses_the_bluesky_session_for_a_long_form_entry() -> None:
    client = WhiteWindClient(identifier="acme.bsky.social", app_password="app-pass")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("createSession"):
            return _json_response({"accessJwt": "jwt1", "did": "did:plc:acme"})
        seen["body"] = json.loads(request.content)
        return _json_response({"uri": "at://did:plc:acme/com.whtwnd.blog.entry/xyz789"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://whtwnd.com/acme.bsky.social/xyz789"
    assert seen["body"]["collection"] == "com.whtwnd.blog.entry"


def test_disqus_updates_the_profile_url_field() -> None:
    client = DisqusClient(access_token="t", api_key="k", username="acme")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return _json_response({"code": 0, "response": {}})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://disqus.com/by/acme/"
    assert seen["params"]["url"] == "https://client.example/services"


def test_plurk_signs_oauth1_and_builds_a_base36_url() -> None:
    client = PlurkClient(
        consumer_key="ck", consumer_secret="cs", access_token="at", access_token_secret="ats"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization", "").startswith("OAuth ")
        return _json_response({"plurk_id": 46656})  # 46656 == 36**3 -> base36 "1000"

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://www.plurk.com/p/1000"


def test_pixelfed_uploads_the_placeholder_image_before_posting() -> None:
    client = PixelfedClient(access_token="t", placeholder_image_url="https://cdn.example/brand.jpg")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cdn.example":
            return httpx.Response(200, content=b"fake-jpeg-bytes")
        if request.url.path.endswith("/media"):
            return _json_response({"id": "media1"})
        return _json_response({"id": 5, "url": "https://pixelfed.social/p/acme/5"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://pixelfed.social/p/acme/5"


def test_notion_creates_a_page_but_is_never_claimed_verified() -> None:
    client = NotionClient(integration_token="t", parent_page_id="parent1")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _json_response({"id": "page1", "url": "https://notion.so/page1"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://notion.so/page1"
    assert result.verified is False  # a human must still flip "Share to web"
    assert seen["body"]["parent"]["page_id"] == "parent1"


def test_gravatar_updates_the_profile_and_builds_the_public_url() -> None:
    client = GravatarClient(api_token="t", username="acme")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return _json_response({})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://gravatar.com/acme"
    assert seen["auth"] == "Bearer t"
    assert seen["body"]["links"][0]["url"] == "https://client.example/services"


def test_minds_posts_an_activity_to_the_public_channel() -> None:
    client = MindsClient(access_token="t")
    _with_mock(client, lambda req: _json_response({"entity": {"guid": "guid1"}}))
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://www.minds.com/newsfeed/guid1"


# --------------------------------------------------------------------------- #
# 4c. Batch4 real HTTP behaviour via MockTransport - one test per new client.
# --------------------------------------------------------------------------- #
def test_zenodo_creates_then_publishes_a_deposition() -> None:
    client = ZenodoClient(access_token="t")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/actions/publish"):
            return _json_response(
                {"id": 42, "links": {"record_html": "https://zenodo.org/records/42"}}
            )
        return _json_response({"id": 42, "links": {}})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://zenodo.org/records/42"
    assert result.external_id == "42"
    assert any(p.endswith("/deposit/depositions") for p in calls)
    assert any(p.endswith("/actions/publish") for p in calls)


def test_zenodo_second_publish_call_refetches_instead_of_republishing() -> None:
    client = ZenodoClient(access_token="t")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["path"] = request.method, request.url.path
        return _json_response({"id": 42, "links": {"record_html": "https://zenodo.org/records/42"}})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id="42"))
    assert result.post_url == "https://zenodo.org/records/42"
    assert seen["method"] == "GET" and seen["path"].endswith("/deposit/depositions/42")


def test_internet_archive_puts_a_static_file_with_the_low_auth_scheme() -> None:
    client = InternetArchiveClient(access_key="ak", secret_key="sk")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["auto_make_bucket"] = request.headers.get("x-archive-auto-make-bucket")
        return httpx.Response(200)

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://archive.org/details/gentle-dental-cleanings"
    assert seen["auth"] == "LOW ak:sk"
    assert seen["auto_make_bucket"] == "1"


def test_osf_creates_a_public_node() -> None:
    client = OSFClient(access_token="t")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _json_response(
            {"data": {"id": "abc12", "links": {"html": "https://osf.io/abc12/"}}}
        )

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://osf.io/abc12/"
    assert result.external_id == "abc12"
    assert seen["body"]["data"]["attributes"]["public"] is True


def test_figshare_creates_then_publishes_and_uses_the_doi_url() -> None:
    client = FigshareClient(access_token="t")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        if request.url.path.endswith("/publish"):
            return _json_response({"location": "https://api.figshare.com/v2/articles/999"})
        return _json_response({"location": "https://api.figshare.com/v2/account/articles/123"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://doi.org/10.6084/m9.figshare.999"
    assert result.external_id == "123"
    assert seen["auth"] == "token t"  # Figshare's own scheme, not Bearer


def test_codeberg_pages_commits_a_file_to_the_pages_branch() -> None:
    client = CodebergPagesClient(token="t", owner="acme", repo="site")
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/repos"):
            return _json_response({}, status_code=201)
        return _json_response({"content": {"sha": "abc"}})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://acme.codeberg.page/gentle-dental-cleanings/"
    assert any(m == "POST" and p.endswith("/repos") for m, p in calls)
    assert any(m == "PUT" and "/contents/" in p for m, p in calls)


def test_livedoor_blog_signs_http_basic_and_reuses_the_hatena_atom_parser() -> None:
    client = LivedoorBlogClient(livedoor_id="acme", blog_name="acmeblog", api_key="k")
    atom = (
        '<?xml version="1.0"?><entry xmlns="http://www.w3.org/2005/Atom">'
        '<id>tag:blog.livedoor.com,2013:acme-12345-67890</id>'
        '<link rel="alternate" href="https://acme.livedoor.blogcms.jp/archives/1.html"/></entry>'
    )
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(201, text=atom, headers={"Content-Type": "application/atom+xml"})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://acme.livedoor.blogcms.jp/archives/1.html"
    assert seen["auth"].startswith("Basic ")


def test_fc2_and_seesaa_metaweblog_clients_fetch_the_real_permalink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_proxy = MagicMock()
    fake_proxy.metaWeblog.newPost.return_value = "77"
    fake_proxy.metaWeblog.getPost.return_value = {"permaLink": "https://acme.blog.fc2.com/blog-entry-77.html"}
    monkeypatch.setattr("xmlrpc.client.ServerProxy", lambda *_a, **_k: fake_proxy)

    client = FC2BlogClient(blog_id="42", username="acme", password="secret")
    result = client.publish(client.platform, _post(external_id=None))
    assert result.post_url == "https://acme.blog.fc2.com/blog-entry-77.html"
    assert result.external_id == "77"
    fake_proxy.metaWeblog.newPost.assert_called_once()
    call_args = fake_proxy.metaWeblog.newPost.call_args[0]
    assert call_args[0] == "42" and call_args[1] == "acme" and call_args[2] == "secret"
    assert call_args[4] is True  # publish=True
    fake_proxy.metaWeblog.getPost.assert_called_once_with("77", "acme", "secret")


def test_seesaa_metaweblog_client_edits_when_external_id_present(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_proxy = MagicMock()
    fake_proxy.metaWeblog.getPost.return_value = {"link": "https://acme.seesaa.net/article/1.html"}
    monkeypatch.setattr("xmlrpc.client.ServerProxy", lambda *_a, **_k: fake_proxy)

    client = SeesaaBlogClient(blog_id="42", username="acme", password="secret")
    result = client.publish(client.platform, _post(external_id="9"))
    assert result.post_url == "https://acme.seesaa.net/article/1.html"
    fake_proxy.metaWeblog.editPost.assert_called_once()
    fake_proxy.metaWeblog.newPost.assert_not_called()


def test_warpcast_casts_via_neynar_with_the_xapikey_header() -> None:
    client = WarpcastClient(api_key="k", signer_uuid="s")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["header"] = request.headers.get("x-api-key")
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return _json_response(
            {"cast": {"hash": "0x1234567890abcdef", "author": {"username": "acme"}}}
        )

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://warpcast.com/acme/0x12345678"
    assert result.verified is True
    assert seen["header"] == "k" and seen["auth"] is None
    assert seen["body"]["signer_uuid"] == "s"


def test_warpcast_marks_unverified_without_a_username() -> None:
    client = WarpcastClient(api_key="k", signer_uuid="s")
    _with_mock(client, lambda req: _json_response({"cast": {"hash": "0xabc123", "author": {}}}))
    result = client.publish(client.platform, _post())
    assert result.verified is False
    assert "0xabc123" in result.post_url


def test_sourcehut_pages_sends_a_graphql_multipart_tarball() -> None:
    client = SourcehutPagesClient(token="t", domain="client.srht.site")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["content_type"] = request.headers.get("Content-Type", "")
        return _json_response({"data": {"publish": {"id": "site1", "domain": "client.srht.site"}}})

    _with_mock(client, handler)
    result = client.publish(client.platform, _post())
    assert result.post_url == "https://client.srht.site/"
    assert result.external_id == "site1"
    assert seen["auth"] == "Bearer t"
    assert "multipart/form-data" in seen["content_type"]


def test_sourcehut_pages_surfaces_graphql_errors() -> None:
    client = SourcehutPagesClient(token="t", domain="client.srht.site")
    _with_mock(client, lambda req: _json_response({"errors": [{"message": "domain taken"}]}))
    with pytest.raises(ProviderCallError):
        client.publish(client.platform, _post())


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


def test_build_publisher_wires_a_batch4_platform_end_to_end() -> None:
    # Proves the factory correctly wires one of the 10 new platforms, not just the
    # pre-existing dev.to case above.
    publisher = build_publisher(
        client_id="cl-7", platform=PLATFORM_ZENODO, lookup=lambda **_k: json.dumps({"access_token": "real"})
    )
    assert isinstance(publisher, ZenodoClient)


def test_build_publisher_degrades_to_none_for_an_incomplete_batch4_credential() -> None:
    publisher = build_publisher(
        client_id="cl-7", platform=PLATFORM_CODEBERG_PAGES,
        lookup=lambda **_k: json.dumps({"token": "", "owner": "acme", "repo": "site"}),
    )
    assert publisher is None
