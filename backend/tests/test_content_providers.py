"""P7A-2 unit gate: the content provider seams (no network, no keys).

Covers the three new Protocols + their deterministic fakes (SerpResearcher /
ImageGenerator / WordPressPublisher), the key-gated factory (degrades to None
without the writer key; assembles fakes vs real per available key, monkeypatched so
no SDK/network is touched), and the real HTTP seams' behaviour via httpx.MockTransport
(idempotent WP create-vs-update routing, retry on 5xx, secret-safe 4xx errors, key in
header). No AI SDK is installed for the gate - everything here is fakes or mocked HTTP.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.config import Settings
from integrations import content_providers as cp
from integrations.content_providers import (
    ContentProviders,
    content_providers_for_tests,
    content_providers_from_settings,
)
from integrations.content_research import (
    FakeSerpResearcher,
    KeywordMetrics,
    OrganicResult,
    SerperResearcher,
    SerpResearcher,
    SerpResult,
)
from integrations.errors import ProviderCallError, ProviderNotConfiguredError
from integrations.images import (
    FakeImageGenerator,
    GeneratedImage,
    ImageGenerator,
    OpenAIImageGenerator,
)
from integrations.llm import FakeSummarizer
from integrations.wordpress import (
    FakeWordPressPublisher,
    PostDraft,
    PublishResult,
    WordPressClient,
    WordPressPublisher,
)

pytestmark = pytest.mark.unit


Handler = Callable[[httpx.Request], httpx.Response]


def _with_mock(seam: Any, handler: Handler) -> None:
    """Swap a real seam's httpx client for a MockTransport one, KEEPING its base_url
    + headers (so header auth like X-API-KEY / Bearer still rides the request and
    relative paths resolve against the provider host)."""
    old = seam._client
    seam._client = httpx.Client(
        base_url=old.base_url, headers=old.headers, transport=httpx.MockTransport(handler)
    )


# --------------------------------------------------------------------------- #
# Protocol conformance (runtime) - fakes AND the network-free-constructed reals
# --------------------------------------------------------------------------- #
def test_fakes_satisfy_protocols() -> None:
    assert isinstance(FakeSerpResearcher(), SerpResearcher)
    assert isinstance(FakeImageGenerator(), ImageGenerator)
    assert isinstance(FakeWordPressPublisher(), WordPressPublisher)


def test_real_impls_satisfy_protocols() -> None:
    # Construction is network-free; it only builds an httpx.Client.
    assert isinstance(SerperResearcher(api_key="k"), SerpResearcher)
    assert isinstance(OpenAIImageGenerator(api_key="k"), ImageGenerator)
    assert isinstance(WordPressClient(username="u", app_password="p"), WordPressPublisher)


# --------------------------------------------------------------------------- #
# FakeSerpResearcher - deterministic, varies by keyword, bounded metrics
# --------------------------------------------------------------------------- #
def test_fake_serp_deterministic_and_varies() -> None:
    fake = FakeSerpResearcher()
    a = fake.serp("plumber seo", geo="us")
    b = fake.serp("plumber seo", geo="us")
    assert isinstance(a, SerpResult)
    assert a == b  # same keyword -> identical SERP (stable golden tests)
    assert a.geo == "us"
    assert a.organic and all(isinstance(o, OrganicResult) for o in a.organic)
    assert a.people_also_ask and a.related_searches
    # Different keyword -> different digest-derived content (not just the label).
    assert fake.serp("dentist marketing").organic[0].link != a.organic[0].link


def test_fake_serp_metrics_deterministic_and_bounded() -> None:
    fake = FakeSerpResearcher()
    m1 = fake.keyword_metrics("plumber seo")
    m2 = fake.keyword_metrics("plumber seo")
    assert isinstance(m1, KeywordMetrics)
    assert m1 == m2
    assert 0 <= m1.volume < 50_000
    assert 0.0 <= m1.difficulty <= 100.0
    assert fake.keyword_metrics("dentist marketing") != m1  # keyword field differs


# --------------------------------------------------------------------------- #
# FakeImageGenerator - deterministic, alt round-trips
# --------------------------------------------------------------------------- #
def test_fake_image_deterministic_and_alt_roundtrips() -> None:
    gen = FakeImageGenerator()
    i1 = gen.generate("a hero image of a plumber", "Plumber at work")
    i2 = gen.generate("a hero image of a plumber", "Plumber at work")
    assert isinstance(i1, GeneratedImage)
    assert i1 == i2
    assert i1.alt == "Plumber at work"  # caller's alt is authoritative + round-trips
    assert i1.url.endswith(".png")
    assert gen.generate("a different prompt", "Plumber at work").url != i1.url


# --------------------------------------------------------------------------- #
# FakeWordPressPublisher - deterministic create; idempotent update echoes the id
# --------------------------------------------------------------------------- #
def test_fake_wordpress_create_is_deterministic() -> None:
    pub = FakeWordPressPublisher()
    draft = PostDraft(title="My New Page", content="<p>hi</p>")
    r1 = pub.publish("https://site.example/", draft)  # trailing slash normalized
    r2 = pub.publish("https://site.example", draft)
    assert isinstance(r1, PublishResult)
    assert r1 == r2
    assert r1.post_id > 0
    assert r1.url == "https://site.example/my-new-page"


def test_fake_wordpress_update_echoes_id() -> None:
    pub = FakeWordPressPublisher()
    draft = PostDraft(title="Edited", content="<p>x</p>", slug="edited", wp_post_id=4242)
    res = pub.publish("https://site.example", draft)
    assert res.post_id == 4242  # idempotent update keeps the id, never re-creates
    assert res.url == "https://site.example/edited"


# --------------------------------------------------------------------------- #
# Real impls raise a clear error without their key/credential (key check first)
# --------------------------------------------------------------------------- #
def test_real_impls_require_a_key() -> None:
    with pytest.raises(ProviderNotConfiguredError, match="SERPER_API_KEY"):
        SerperResearcher(api_key="")
    with pytest.raises(ProviderNotConfiguredError, match="IMAGE_GEN_API_KEY"):
        OpenAIImageGenerator(api_key="")
    with pytest.raises(ProviderNotConfiguredError, match="application password"):
        WordPressClient(username="", app_password="")
    with pytest.raises(ProviderNotConfiguredError, match="application password"):
        WordPressClient(username="u", app_password="")  # user but no password


# --------------------------------------------------------------------------- #
# Real HTTP seams via MockTransport - no network, exercises the shared client
# --------------------------------------------------------------------------- #
def test_serper_serp_parses_and_sends_key_in_header() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("x-api-key")
        return httpx.Response(
            200,
            json={
                "organic": [
                    {"position": 1, "title": "T1", "link": "https://a", "snippet": "s"},
                    {"title": "T2", "link": "https://b"},  # missing position -> index+1
                ],
                "peopleAlsoAsk": [{"question": "Q1?"}, {"nope": 1}],
                "relatedSearches": [{"query": "rel1"}, {"query": "rel2"}],
            },
        )

    researcher = SerperResearcher(api_key="super-secret")
    _with_mock(researcher, handler)
    result = researcher.serp("kw", geo="us")
    assert seen["key"] == "super-secret"  # key rides in the header, never a URL/log
    assert [o.position for o in result.organic] == [1, 2]
    assert result.people_also_ask == ["Q1?"]  # entries without a question dropped
    assert result.related_searches == ["rel1", "rel2"]


def test_http_retries_transient_5xx_then_succeeds() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 2:
            return httpx.Response(503)  # transient -> retried
        return httpx.Response(200, json={"searchInformation": {"totalResults": "1000000"}})

    researcher = SerperResearcher(api_key="k")
    _with_mock(researcher, handler)
    metrics = researcher.keyword_metrics("kw")
    assert attempts["n"] == 2  # retried once, then succeeded
    assert isinstance(metrics, KeywordMetrics)
    assert metrics.difficulty > 0.0


def test_http_4xx_raises_and_never_leaks_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad request"})

    researcher = SerperResearcher(api_key="super-secret")
    _with_mock(researcher, handler)
    with pytest.raises(ProviderCallError) as exc:
        researcher.serp("kw")
    assert "super-secret" not in str(exc.value)  # secret never in the error text


def test_wordpress_idempotent_create_vs_update_routing() -> None:
    calls: list[str] = []
    auth_seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        auth_seen["header"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": 99, "link": "https://blog.example/hello"})

    client = WordPressClient(username="admin", app_password="app pass word")
    _with_mock(client, handler)

    created = client.publish("https://blog.example", PostDraft(title="Hello", content="<p>hi</p>"))
    assert created.post_id == 99
    assert created.url == "https://blog.example/hello"
    assert calls[-1] == "https://blog.example/wp-json/wp/v2/posts"  # CREATE route
    assert auth_seen["header"].startswith("Basic ")  # app-password via Basic auth

    client.publish(
        "https://blog.example",
        PostDraft(title="Hello", content="<p>hi</p>", wp_post_id=99),
    )
    assert calls[-1] == "https://blog.example/wp-json/wp/v2/posts/99"  # UPDATE route


def test_openai_image_parses_url_and_carries_alt() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": [{"url": "https://cdn.example/img.png"}]})

    gen = OpenAIImageGenerator(api_key="imgkey")
    _with_mock(gen, handler)
    image = gen.generate("a plumber at work", "Plumber alt text")
    assert seen["auth"] == "Bearer imgkey"  # key in the Authorization header
    assert image.url == "https://cdn.example/img.png"
    assert image.alt == "Plumber alt text"  # caller's alt round-trips unchanged


# --------------------------------------------------------------------------- #
# Factory - degrades without the writer key, assembles fakes vs real per key
# --------------------------------------------------------------------------- #
def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_factory_degrades_without_writer_key() -> None:
    assert content_providers_from_settings(_settings()) is None


def test_factory_builds_fakes_for_enrichment_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only the writer key present -> real writer, fake enrichment seams.
    monkeypatch.setattr(cp, "AnthropicSummarizer", lambda **_k: "WRITER")
    bundle = content_providers_from_settings(_settings(anthropic_api_key="ak"))
    assert isinstance(bundle, ContentProviders)
    assert bundle.writer == "WRITER"
    assert isinstance(bundle.serp, FakeSerpResearcher)
    assert isinstance(bundle.images, FakeImageGenerator)
    assert isinstance(bundle.wordpress, FakeWordPressPublisher)
    assert bundle.model_writer == "claude-haiku-4-5"
    assert bundle.model_heavy == "claude-sonnet-5"
    assert bundle.research_cost_estimate == pytest.approx(0.01)
    assert bundle.generate_cost_estimate == pytest.approx(0.15)


def test_factory_selects_real_enrichment_with_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    built: dict[str, object] = {}

    def fake_writer(**kwargs: object) -> object:
        built["writer"] = kwargs
        return "WRITER"

    def fake_serper(**kwargs: object) -> object:
        built["serp"] = kwargs
        return "SERP"

    def fake_image(**kwargs: object) -> object:
        built["images"] = kwargs
        return "IMAGES"

    monkeypatch.setattr(cp, "AnthropicSummarizer", fake_writer)
    monkeypatch.setattr(cp, "SerperResearcher", fake_serper)
    monkeypatch.setattr(cp, "OpenAIImageGenerator", fake_image)

    settings = _settings(
        anthropic_api_key="ak",
        serper_api_key="sk",
        image_gen_api_key="ik",
        image_gen_model="m1",
    )
    bundle = content_providers_from_settings(settings)
    assert isinstance(bundle, ContentProviders)
    assert bundle.writer == "WRITER"
    assert bundle.serp == "SERP"
    assert bundle.images == "IMAGES"
    # WordPress stays the fake even with other keys: per-site app-passwords live in
    # the vault (service layer), never in settings.
    assert isinstance(bundle.wordpress, FakeWordPressPublisher)
    # Decrypted secrets pass through to the clients only, never logged.
    assert built["writer"] == {
        "api_key": "ak",
        "model_summary": "claude-haiku-4-5",
        "model_heavy": "claude-sonnet-5",
    }
    assert built["serp"] == {"api_key": "sk"}
    assert built["images"] == {"api_key": "ik", "model": "m1"}


def test_content_providers_for_tests_returns_fakes() -> None:
    bundle = content_providers_for_tests()
    assert isinstance(bundle.serp, FakeSerpResearcher)
    assert isinstance(bundle.writer, FakeSummarizer)
    assert isinstance(bundle.images, FakeImageGenerator)
    assert isinstance(bundle.wordpress, FakeWordPressPublisher)
    assert bundle.model_writer == "fake-writer"
    assert bundle.research_cost_estimate == pytest.approx(0.01)
