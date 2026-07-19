"""Web 2.0 publish seam (7B-3, expanded 7B-4): the ONLY door to a branded Web 2.0
property.

The publish stage of the off-page pipeline pushes a human-APPROVED, on-topic branded
article to a client's Web 2.0 property carrying ONE editorial backlink to the client's
page. Reachable exclusively through the ``Web2Publisher`` Protocol so the
service/worker layer can meter, cost-log, and diversify it - nothing else calls a
provider directly. Every placement is human-approved authority work (a real, on-topic
post), NEVER link spam.

SEVENTEEN platforms, mirroring the frontend ``Web2Platform`` union (offpage.ts) - every
one the 17 Jul 2026 reference doc tags API-post: Yes, not deprecated, and not a
blockchain/OAuth1/brand-risk case that would need a materially different credential
model (Hive/Steemit need a custody-sensitive private key, not an OAuth token; Gab
carries the doc's own explicit brand-safety warning) - those stay future work:

* ``WordPressComClient`` / ``BloggerClient`` / ``TumblrClient`` - real, OAuth2 bearer.
* ``DevToClient``      - real, dev.to (Forem) API v1, a plain ``api-key`` header.
* ``WriteAsClient``    - real, Write.as/WriteFreely API, bearer token.
* ``TelegraPhClient``  - real, Telegraph API - no OAuth at all (an ``access_token``
  from ``createAccount``, fully anonymous).
* ``MataroaClient``    - real, Mataroa's documented REST API, bearer token.
* ``GhostClient``      - real, Ghost Admin API - a short-lived JWT signed from the
  ``id:secret`` Admin API key (Publisher tier or self-hosted).
* ``MastodonClient``   - real, Mastodon REST API, OAuth2 bearer (per-instance).
* ``GitHubPagesClient`` / ``GitLabPagesClient`` - real, two-step (commit a file via the
  Contents/Repository-Files API, then ensure Pages is enabled), PAT-based.
* ``MicroBlogClient``  - real, Micropub (IndieWeb standard), bearer token.
* ``HashnodeClient``   - real, Hashnode's GraphQL Public API, a raw (non-Bearer) PAT.
* ``HatenaBlogClient`` - real, Hatena's AtomPub API, HTTP Basic (Hatena ID + API key).
* ``LiveJournalClient`` / ``DreamwidthClient`` - real, the shared LiveJournal-protocol
  XML-RPC API (``LJ.XMLRPC.postevent``), username + password (no OAuth on this legacy
  protocol) - one shared implementation, two hosts.
* **Medium is DRAFT-ONLY** - Medium retired its write/publish API, so there is NO live
  Medium publisher. A Medium placement is prepared as a DRAFT (``verified=False``,
  ``draft_only=True``) for a human to paste/publish; the pipeline holds it, never
  claims it is live. ``FakeWeb2Publisher`` models this so the behaviour is testable.

CREDENTIALS ARE PASSED IN, NEVER READ HERE. A Web 2.0 OAuth token / API key is
per-account + per-property and lives in the VAULT (exactly like a WordPress
application password); ``integrations.web2_credentials`` decrypts it and constructs
the real client per publish (the "later chunk" this docstring used to defer). This
seam never touches settings or the vault, and never logs a secret (it rides in the
``Authorization``/``api-key`` header, which the shared client keeps out of every log).

``FakeWeb2Publisher`` is the deterministic, offline publisher: a stable post URL derived
from ``platform|account|slug`` (or the given ``external_id`` echoed on update), so the
pipeline + worker suites run fully live with zero external accounts.

FOOTPRINT DIVERSIFICATION (``diversify_footprint``) is the anti-SpamBrain lever: it
varies the platform / account / anchor / timing so a client's placements do not share a
detectable footprint (same anchor, same platform, all at once). It is a PURE,
deterministic selection over the available inventory + the placements already made.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote

import jwt as pyjwt  # already a base dependency (pyjwt[crypto]) - signs Ghost's Admin JWT

from app.config import Settings
from app.logging_setup import get_logger
from integrations.errors import ProviderCallError, ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

logger = get_logger("integrations.web2_publishers")

# Platform labels - verbatim from offpage.ts Web2Platform (the DB enum + response).
PLATFORM_WORDPRESS = "WordPress.com"
PLATFORM_BLOGGER = "Blogger"
PLATFORM_TUMBLR = "Tumblr"
PLATFORM_MEDIUM = "Medium"
PLATFORM_DEVTO = "dev.to"
PLATFORM_WRITEAS = "Write.as"
PLATFORM_TELEGRAPH = "Telegra.ph"
PLATFORM_MATAROA = "Mataroa"
PLATFORM_GHOST = "Ghost"
PLATFORM_MASTODON = "Mastodon"
PLATFORM_GITHUB_PAGES = "GitHub Pages"
PLATFORM_GITLAB_PAGES = "GitLab Pages"
PLATFORM_MICROBLOG = "Micro.blog"
PLATFORM_HASHNODE = "Hashnode"
PLATFORM_HATENA = "Hatena Blog"
PLATFORM_LIVEJOURNAL = "LiveJournal"
PLATFORM_DREAMWIDTH = "Dreamwidth"

WEB2_PLATFORMS: frozenset[str] = frozenset(
    {
        PLATFORM_WORDPRESS, PLATFORM_BLOGGER, PLATFORM_TUMBLR, PLATFORM_MEDIUM,
        PLATFORM_DEVTO, PLATFORM_WRITEAS, PLATFORM_TELEGRAPH, PLATFORM_MATAROA,
        PLATFORM_GHOST, PLATFORM_MASTODON, PLATFORM_GITHUB_PAGES, PLATFORM_GITLAB_PAGES,
        PLATFORM_MICROBLOG, PLATFORM_HASHNODE, PLATFORM_HATENA, PLATFORM_LIVEJOURNAL,
        PLATFORM_DREAMWIDTH,
    }
)
# Medium is draft-only (its publish API is retired); the pipeline never marks it live.
DRAFT_ONLY_PLATFORMS: frozenset[str] = frozenset({PLATFORM_MEDIUM})

# The credential SHAPE each real client needs, keyed by platform - what
# ``integrations.web2_credentials`` must parse out of a client's sealed vault JSON
# blob before it can build that platform's real client. Reference data only (no
# behaviour); the vault-lookup factory is the single reader of this dict.
PLATFORM_CREDENTIAL_FIELDS: dict[str, tuple[str, ...]] = {
    PLATFORM_WORDPRESS: ("oauth_token", "site"),
    PLATFORM_BLOGGER: ("oauth_token", "blog_id"),
    PLATFORM_TUMBLR: ("oauth_token", "blog"),
    PLATFORM_DEVTO: ("api_key",),
    PLATFORM_WRITEAS: ("token", "alias"),
    PLATFORM_TELEGRAPH: ("access_token",),
    PLATFORM_MATAROA: ("api_key",),
    PLATFORM_GHOST: ("admin_api_key", "api_url"),
    PLATFORM_MASTODON: ("access_token", "instance_url"),
    PLATFORM_GITHUB_PAGES: ("token", "owner", "repo"),
    PLATFORM_GITLAB_PAGES: ("token", "project_id"),
    PLATFORM_MICROBLOG: ("token",),
    PLATFORM_HASHNODE: ("pat", "publication_id"),
    PLATFORM_HATENA: ("hatena_id", "blog_id", "api_key"),
    PLATFORM_LIVEJOURNAL: ("username", "password"),
    PLATFORM_DREAMWIDTH: ("username", "password"),
}

_INSTALL_HINT = (
    "pass a per-account OAuth token + blog/site id (per-property, from the vault) "
    "to publish a Web 2.0 property"
)


@dataclass(frozen=True)
class Web2Post:
    """The approved article to publish to a Web 2.0 property.

    ``body_html`` is rendered HTML; ``anchor`` -> ``target_url`` is the single editorial
    backlink the whole property exists to carry. ``external_id`` set => idempotent
    UPDATE of that provider post, else CREATE. ``tags`` are optional topical tags.
    """

    title: str
    body_html: str
    anchor: str
    target_url: str
    slug: str | None = None
    tags: tuple[str, ...] = ()
    external_id: str | None = None


@dataclass(frozen=True)
class Web2PublishResult:
    """The result of a publish: the live ``post_url``, whether it is ``verified`` live
    (a real, indexable placement vs a held draft), the provider ``external_id`` (record
    it for idempotent re-publish), and ``draft_only`` (Medium)."""

    post_url: str
    verified: bool
    external_id: str | None = None
    draft_only: bool = False


@runtime_checkable
class Web2Publisher(Protocol):
    """Publish (or, when ``post.external_id`` is set, update) ``post`` on ``platform``."""

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult: ...


# --------------------------------------------------------------------------- #
# Real, OAuth-gated clients (one per live platform).
# --------------------------------------------------------------------------- #
class _OAuthWeb2Client(HttpProviderClient):
    """Shared base for the OAuth2-bearer Web 2.0 clients.

    The bearer token rides in the ``Authorization`` header (never a URL, never a log
    line); the caller (service layer) supplies the decrypted token + the target
    blog/site id. Each subclass declares the single ``platform`` it serves and refuses
    any other (the Protocol takes a platform arg, so a mismatched call fails loudly)."""

    platform: str = ""

    def __init__(self, *, oauth_token: str, target: str, timeout: float = 30.0) -> None:
        if not oauth_token or not target:
            raise ProviderNotConfiguredError(f"{self.platform} publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            headers={"Authorization": f"Bearer {oauth_token}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        self._target = target

    def _guard_platform(self, platform: str) -> None:
        if platform != self.platform:
            raise ProviderCallError(
                f"{self.platform} client cannot publish to {platform}"
            )


class WordPressComClient(_OAuthWeb2Client):
    """Real ``Web2Publisher`` over the WordPress.com REST v1.1 API (hosted WP.com,
    distinct from the self-hosted ``integrations.wordpress`` REST client)."""

    provider = "wordpress_com"
    platform = PLATFORM_WORDPRESS

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        self._guard_platform(platform)
        base = f"https://public-api.wordpress.com/rest/v1.1/sites/{self._target}/posts"
        url = f"{base}/{post.external_id}" if post.external_id else f"{base}/new"
        body: dict[str, object] = {
            "title": post.title,
            "content": post.body_html,
            "status": "publish",
        }
        if post.slug:
            body["slug"] = post.slug
        if post.tags:
            body["tags"] = list(post.tags)
        data = self.request_json("POST", url, json_body=body)
        post_url = str(data.get("URL") or data.get("url") or "")
        external_id = data.get("ID") or data.get("id")
        verified = bool(post_url) and str(data.get("status") or "publish") == "publish"
        if not post_url:
            raise ProviderCallError("WordPress.com response missing post URL")
        return Web2PublishResult(
            post_url=post_url, verified=verified, external_id=str(external_id) if external_id else None
        )


class BloggerClient(_OAuthWeb2Client):
    """Real ``Web2Publisher`` over the Blogger v3 API (OAuth2 bearer). ``target`` is the
    blog id."""

    provider = "blogger"
    platform = PLATFORM_BLOGGER

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        self._guard_platform(platform)
        base = f"https://www.googleapis.com/blogger/v3/blogs/{self._target}/posts"
        body: dict[str, object] = {
            "kind": "blogger#post",
            "title": post.title,
            "content": post.body_html,
        }
        if post.tags:
            body["labels"] = list(post.tags)
        # An existing post id -> PUT (update) that post; else POST to create.
        if post.external_id:
            data = self.request_json("PUT", f"{base}/{post.external_id}", json_body=body)
        else:
            data = self.request_json("POST", base, json_body=body)
        post_url = str(data.get("url") or "")
        external_id = data.get("id")
        if not post_url:
            raise ProviderCallError("Blogger response missing post url")
        # Blogger publishes live by default; a returned url is a live, indexable post.
        return Web2PublishResult(
            post_url=post_url, verified=True, external_id=str(external_id) if external_id else None
        )


class TumblrClient(_OAuthWeb2Client):
    """Real ``Web2Publisher`` over the Tumblr v2 API (OAuth2 bearer). ``target`` is the
    blog identifier (e.g. ``myblog.tumblr.com``)."""

    provider = "tumblr"
    platform = PLATFORM_TUMBLR

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        self._guard_platform(platform)
        base = f"https://api.tumblr.com/v2/blog/{self._target}/post"
        body: dict[str, object] = {
            "type": "text",
            "title": post.title,
            "body": post.body_html,
            "state": "published",
        }
        if post.tags:
            body["tags"] = ",".join(post.tags)
        if post.external_id:
            body["id"] = post.external_id
            base = f"https://api.tumblr.com/v2/blog/{self._target}/post/edit"
        data = self.request_json("POST", base, json_body=body)
        # Tumblr returns {"response": {"id": ..., "id_string": ...}} - no direct URL,
        # so the permalink is derived from the blog + post id.
        response = data.get("response")
        inner = response if isinstance(response, dict) else {}
        raw_id = inner.get("id_string") or inner.get("id") or post.external_id
        if not raw_id:
            raise ProviderCallError("Tumblr response missing post id")
        post_url = f"https://{self._target}/post/{raw_id}"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(raw_id))


# --------------------------------------------------------------------------- #
# Shared small helpers the new platform clients below need (plain-text/HTML/static-
# page rendering + a light Telegraph Node encoder) - kept here rather than importing
# from web2_pipeline, which this integrations seam must not depend on.
# --------------------------------------------------------------------------- #
_TAG_RE = re.compile(r"<[^>]+>")


def _html_to_text(html: str) -> str:
    """Strip HTML to plain text, for platforms with no rich body field (Mastodon's
    status text, the journal-protocol ``event`` field)."""
    text = html.replace("</p>", "\n\n").replace("<br>", "\n").replace("</li>", "\n")
    text = _TAG_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _static_page(post: Web2Post) -> str:
    """A minimal standalone HTML document wrapping the approved article body - what
    GitHub/GitLab Pages actually serve (they publish raw files, not a CMS post)."""
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<title>{post.title}</title></head><body>"
        f"<h1>{post.title}</h1>{post.body_html}</body></html>"
    )


_HTML_A_RE = re.compile(r'<a href="([^"]*)">([^<]*)</a>')
_HTML_BLOCK_RE = re.compile(r"<(h1|h2|h3|p|ul)>(.*?)</\1>", re.DOTALL)
_HTML_LI_RE = re.compile(r"<li>(.*?)</li>", re.DOTALL)
# Telegraph's Node format only understands a narrow tag set; h1/h2 downgrade to the
# closest heading it supports (it has no h1/h2 - h3/h4 are its top two levels).
_TELEGRAPH_TAG: dict[str, str] = {"h1": "h3", "h2": "h3", "h3": "h4", "p": "p"}


def _telegraph_inline_children(html_fragment: str) -> list[Any]:
    """An HTML fragment's inline content as Telegraph Node children: a run of plain
    text with ``<a>`` tags becoming ``{tag:'a', attrs:{href}, children:[text]}``."""
    children: list[Any] = []
    pos = 0
    for m in _HTML_A_RE.finditer(html_fragment):
        if m.start() > pos:
            children.append(html_fragment[pos : m.start()])
        children.append({"tag": "a", "attrs": {"href": m.group(1)}, "children": [m.group(2)]})
        pos = m.end()
    if pos < len(html_fragment):
        children.append(html_fragment[pos:])
    return [c for c in children if c != ""]


def html_to_telegraph_nodes(body_html: str) -> list[Any]:
    """Best-effort HTML -> Telegraph ``content`` Node array (Telegraph's own publish
    format - it does not take raw HTML or Markdown)."""
    nodes: list[Any] = []
    for m in _HTML_BLOCK_RE.finditer(body_html):
        tag, inner = m.group(1), m.group(2)
        if tag == "ul":
            items = [
                {"tag": "li", "children": _telegraph_inline_children(li)}
                for li in _HTML_LI_RE.findall(inner)
            ]
            nodes.append({"tag": "ul", "children": items})
        else:
            nodes.append({"tag": _TELEGRAPH_TAG.get(tag, "p"), "children": _telegraph_inline_children(inner)})
    return nodes or [body_html]


# --------------------------------------------------------------------------- #
# dev.to (Forem) - plain api-key header, JSON REST.
# --------------------------------------------------------------------------- #
class DevToClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the dev.to (Forem) API v1. Auth = an ``api-key``
    header (no OAuth). NOTE: dev.to's ``body_markdown`` field is Markdown, but this
    seam only ever hands clients rendered HTML (``web2_pipeline.publish`` converts
    once, upstream of every platform) - Forem's renderer passes through the common
    inline HTML tags this article uses, so this is a working, if not pixel-perfect,
    fit; a follow-up could add an HTML->Markdown step for markdown-native platforms."""

    provider = "devto"
    platform = PLATFORM_DEVTO
    _MAX_TAGS = 4

    def __init__(self, *, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"dev.to publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://dev.to/api",
            headers={"api-key": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        body = {
            "article": {
                "title": post.title,
                "body_markdown": post.body_html,
                "published": True,
                "tags": list(post.tags)[: self._MAX_TAGS],
            }
        }
        method, url = ("PUT", f"/articles/{post.external_id}") if post.external_id else ("POST", "/articles")
        data = self.request_json(method, url, json_body=body)
        post_url = str(data.get("url") or "")
        article_id = data.get("id")
        if not post_url:
            raise ProviderCallError("dev.to response missing article url")
        return Web2PublishResult(
            post_url=post_url, verified=True, external_id=str(article_id) if article_id else None
        )


# --------------------------------------------------------------------------- #
# Write.as / WriteFreely - bearer token (optional: anonymous posting needs none).
# --------------------------------------------------------------------------- #
class WriteAsClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the Write.as/WriteFreely API. ``target`` is the
    collection alias (the blog lives at ``https://{alias}.write.as``); an empty
    target posts anonymously - Write.as allows this with no bearer token at all, per
    the reference doc (public-by-URL, just not part of a listed/indexed blog)."""

    provider = "writeas"
    platform = PLATFORM_WRITEAS

    def __init__(self, *, token: str = "", target: str = "", timeout: float = 30.0) -> None:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        super().__init__(base_url="https://write.as", headers=headers, timeout=timeout)
        self._target = target

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        base = f"/api/collections/{self._target}/posts" if self._target else "/api/posts"
        url = f"{base}/{post.external_id}" if post.external_id else base
        body = {"title": post.title, "body": post.body_html}
        data = self.request_json("PUT" if post.external_id else "POST", url, json_body=body)
        result = data.get("data") or {}
        slug = str(result.get("slug") or post.slug or "")
        post_id = result.get("id")
        post_url = f"https://{self._target}.write.as/{slug}" if self._target else f"https://write.as/{slug}"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(post_id) if post_id else None)


# --------------------------------------------------------------------------- #
# Telegra.ph - NO OAuth at all (an anonymous access_token from createAccount).
# --------------------------------------------------------------------------- #
class TelegraPhClient:
    """Real ``Web2Publisher`` over the Telegraph API. Not an ``HttpProviderClient``
    subclass (Telegraph takes form-encoded params, not a JSON body + bearer header,
    and has no shared retry need for a single lightweight call) - a tiny direct
    client. ``access_token`` comes from a one-time (anonymous) ``createAccount`` call
    and is stored in the vault exactly like any other credential."""

    provider = "telegraph"
    platform = PLATFORM_TELEGRAPH
    _BASE = "https://api.telegra.ph"
    _MAX_TITLE = 256

    def __init__(self, *, access_token: str, timeout: float = 30.0) -> None:
        if not access_token:
            raise ProviderNotConfiguredError(f"Telegra.ph publisher unavailable: {_INSTALL_HINT}")
        import httpx

        self._token = access_token
        self._client = httpx.Client(base_url=self._BASE, timeout=timeout)

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        content = html_to_telegraph_nodes(post.body_html)
        params: dict[str, str] = {
            "access_token": self._token,
            "title": (post.title or "Untitled")[: self._MAX_TITLE],
            "content": json.dumps(content),
            "return_content": "false",
        }
        path = "/editPage" if post.external_id else "/createPage"
        if post.external_id:
            params["path"] = post.external_id
        response = self._client.post(path, data=params)
        if response.status_code >= 400:
            raise ProviderCallError(f"Telegra.ph request failed with status {response.status_code}")
        data = response.json()
        result = data.get("result") or {}
        if not data.get("ok") or not result.get("url"):
            raise ProviderCallError(f"Telegra.ph error: {data.get('error', 'unknown')}")
        return Web2PublishResult(
            post_url=str(result["url"]), verified=True, external_id=str(result.get("path") or "")
        )


# --------------------------------------------------------------------------- #
# Mataroa - a tiny, documented bearer-token REST API.
# --------------------------------------------------------------------------- #
class MataroaClient(HttpProviderClient):
    """Real ``Web2Publisher`` over Mataroa's documented API (mataroa.blog/api/docs).
    Its ``body`` field is Markdown (same HTML-into-markdown caveat as dev.to)."""

    provider = "mataroa"
    platform = PLATFORM_MATAROA

    def __init__(self, *, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"Mataroa publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://mataroa.blog",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        slug = post.slug or _slugify(post.title)
        body: dict[str, object] = {"title": post.title, "body": post.body_html, "slug": slug}
        if post.external_id:
            data = self.request_json("PATCH", f"/api/posts/{post.external_id}/", json_body=body)
        else:
            data = self.request_json("POST", "/api/posts/", json_body=body)
        returned_slug = str(data.get("slug") or slug)
        return Web2PublishResult(
            post_url=f"https://mataroa.blog/blog/{returned_slug}/", verified=True, external_id=returned_slug
        )


# --------------------------------------------------------------------------- #
# Ghost Admin API - a short-lived JWT signed from the id:secret Admin API key.
# --------------------------------------------------------------------------- #
class GhostClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the Ghost Admin API. Auth = a short-lived JWT
    signed with the Admin API key's secret (``id:secret``, from Ghost Admin >
    Settings > Integrations); Ghost verifies the JWT's ``kid``/signature rather than
    taking a static bearer token, so a fresh token is minted per publish call."""

    provider = "ghost"
    platform = PLATFORM_GHOST
    _TOKEN_TTL_SECONDS = 300

    def __init__(self, *, admin_api_key: str, api_url: str, timeout: float = 30.0) -> None:
        if not admin_api_key or not api_url:
            raise ProviderNotConfiguredError(f"Ghost publisher unavailable: {_INSTALL_HINT}")
        key_id, _, secret_hex = admin_api_key.partition(":")
        if not key_id or not secret_hex:
            raise ProviderNotConfiguredError("Ghost admin_api_key must be in 'id:secret' form")
        self._key_id = key_id
        self._secret = bytes.fromhex(secret_hex)
        super().__init__(base_url=api_url.rstrip("/"), headers={"Content-Type": "application/json"}, timeout=timeout)

    def _token(self) -> str:
        now = int(time.time())
        payload = {"iat": now, "exp": now + self._TOKEN_TTL_SECONDS, "aud": "/admin/"}
        return pyjwt.encode(payload, self._secret, algorithm="HS256", headers={"kid": self._key_id})

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        self._client.headers["Authorization"] = f"Ghost {self._token()}"
        body = {"posts": [{"title": post.title, "html": post.body_html, "status": "published"}]}
        if post.external_id:
            method, url = "PUT", f"/ghost/api/admin/posts/{post.external_id}/?source=html"
        else:
            method, url = "POST", "/ghost/api/admin/posts/?source=html"
        data = self.request_json(method, url, json_body=body)
        posts = data.get("posts") or []
        if not posts:
            raise ProviderCallError("Ghost response missing posts array")
        row = posts[0]
        post_url = str(row.get("url") or "")
        if not post_url:
            raise ProviderCallError("Ghost response missing post url")
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(row.get("id") or ""))


# --------------------------------------------------------------------------- #
# Mastodon - OAuth2 bearer, per-instance.
# --------------------------------------------------------------------------- #
class MastodonClient(_OAuthWeb2Client):
    """Real ``Web2Publisher`` over the Mastodon REST API (per-instance). ``target``
    is the instance base URL (e.g. ``https://mastodon.social``); Mastodon has no
    separate title field, so the title + a plain-text rendering of the body + the
    backlink are folded into one status, capped to the instance's character limit."""

    provider = "mastodon"
    platform = PLATFORM_MASTODON
    _MAX_CHARS = 500  # the default Mastodon toot length; instances may allow more

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        self._guard_platform(platform)
        text = f"{post.title}\n\n{_html_to_text(post.body_html)}\n\n{post.anchor}: {post.target_url}"
        body: dict[str, object] = {"status": text[: self._MAX_CHARS]}
        base = self._target.rstrip("/")
        data = self.request_json("POST", f"{base}/api/v1/statuses", json_body=body)
        post_url = str(data.get("url") or "")
        status_id = data.get("id")
        if not post_url:
            raise ProviderCallError("Mastodon response missing status url")
        return Web2PublishResult(
            post_url=post_url, verified=True, external_id=str(status_id) if status_id else None
        )


# --------------------------------------------------------------------------- #
# GitHub Pages / GitLab Pages - commit a static file via the host's Contents API.
# --------------------------------------------------------------------------- #
class GitHubPagesClient(HttpProviderClient):
    """Real ``Web2Publisher`` over GitHub Pages: a two-step publish - (1) PUT the
    article as a static HTML file via the Contents API (one commit per publish/
    update), (2) best-effort ensure Pages is enabled for the repo. Assumes the repo
    already exists (``owner``/``repo``) and publishes to its ``main`` branch."""

    provider = "github_pages"
    platform = PLATFORM_GITHUB_PAGES

    def __init__(self, *, token: str, owner: str, repo: str, timeout: float = 30.0) -> None:
        if not token or not owner or not repo:
            raise ProviderNotConfiguredError(f"GitHub Pages publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        self._owner, self._repo = owner, repo

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        slug = post.slug or _slugify(post.title)
        api_path = f"/repos/{self._owner}/{self._repo}/contents/{slug}/index.html"
        content_b64 = base64.b64encode(_static_page(post).encode("utf-8")).decode("ascii")
        body: dict[str, object] = {
            "message": f"web2: publish {slug}", "content": content_b64, "branch": "main",
        }
        existing_sha = self._existing_sha(api_path) if post.external_id else None
        if existing_sha:
            body["sha"] = existing_sha
        self.request_json("PUT", api_path, json_body=body)
        self._ensure_pages_enabled()
        post_url = f"https://{self._owner}.github.io/{self._repo}/{slug}/"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=slug)

    def _existing_sha(self, api_path: str) -> str | None:
        try:
            data = self.request_json("GET", api_path)
        except ProviderCallError:
            return None
        sha = data.get("sha")
        return str(sha) if sha else None

    def _ensure_pages_enabled(self) -> None:
        # Best-effort idempotent setup, not the publish itself: a 4xx here (already
        # enabled, or needs a first commit before Pages can be turned on) is safe to
        # swallow rather than fail the whole publish over.
        with contextlib.suppress(ProviderCallError):
            self.request_json(
                "POST", f"/repos/{self._owner}/{self._repo}/pages",
                json_body={"source": {"branch": "main", "path": "/"}},
            )


class GitLabPagesClient(HttpProviderClient):
    """Real ``Web2Publisher`` over GitLab Pages: commits the article as a static file
    via the Repository Files API. The actual PUBLISH is a CI ``pages`` job the
    project owner has already configured (the reference doc's own requirement) -
    this client cannot confirm that pipeline ran, so a placement is recorded
    ``verified=False`` (pending the CI build), never claimed live outright."""

    provider = "gitlab_pages"
    platform = PLATFORM_GITLAB_PAGES

    def __init__(self, *, token: str, project_id: str, timeout: float = 30.0) -> None:
        if not token or not project_id:
            raise ProviderNotConfiguredError(f"GitLab Pages publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://gitlab.com/api/v4",
            headers={"PRIVATE-TOKEN": token, "Content-Type": "application/json"},
            timeout=timeout,
        )
        self._project_id = project_id

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        slug = post.slug or _slugify(post.title)
        file_path = quote(f"public/{slug}/index.html", safe="")
        body = {
            "branch": "main", "content": _static_page(post), "commit_message": f"web2: publish {slug}",
        }
        method = "PUT" if post.external_id else "POST"
        project = quote(self._project_id, safe="")
        self.request_json(method, f"/projects/{project}/repository/files/{file_path}", json_body=body)
        namespace = self._project_id.split("/")[0] if "/" in self._project_id else self._project_id
        post_url = f"https://{namespace}.gitlab.io/{slug}/"
        return Web2PublishResult(post_url=post_url, verified=False, external_id=slug)


# --------------------------------------------------------------------------- #
# Micro.blog - Micropub (the IndieWeb W3C standard); the post URL comes back as a
# Location header, not a JSON body, so this bypasses request_json for the one call.
# --------------------------------------------------------------------------- #
class MicroBlogClient(_OAuthWeb2Client):
    """Real ``Web2Publisher`` over Micro.blog's Micropub endpoint. ``target`` is
    unused (a Micropub token is already scoped to one blog) - pass any non-empty
    placeholder to satisfy the shared base-class constructor."""

    provider = "microblog"
    platform = PLATFORM_MICROBLOG

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        self._guard_platform(platform)
        body = {
            "h": "entry", "name": post.title, "content": post.body_html,
            "category[]": list(post.tags),
        }
        response = self._client.post("https://micro.blog/micropub", data=body)
        if response.status_code >= 400:
            raise ProviderCallError(f"Micro.blog request failed with status {response.status_code}")
        post_url = response.headers.get("Location", "")
        if not post_url:
            raise ProviderCallError("Micro.blog response missing Location header")
        return Web2PublishResult(post_url=post_url, verified=True, external_id=post_url)


# --------------------------------------------------------------------------- #
# Hashnode - GraphQL Public API; auth is the RAW PAT, not `Bearer <token>`.
# --------------------------------------------------------------------------- #
class HashnodeClient(HttpProviderClient):
    """Real ``Web2Publisher`` over Hashnode's GraphQL Public API. Auth = the raw
    Personal Access Token in the Authorization header (a documented Hashnode quirk -
    NOT ``Bearer <token>``); ``publication_id`` identifies which blog the post
    belongs to (Hashnode requires a publication to exist first)."""

    provider = "hashnode"
    platform = PLATFORM_HASHNODE
    _ENDPOINT = "https://gql.hashnode.com"

    def __init__(self, *, pat: str, publication_id: str, timeout: float = 30.0) -> None:
        if not pat or not publication_id:
            raise ProviderNotConfiguredError(f"Hashnode publisher unavailable: {_INSTALL_HINT}")
        super().__init__(headers={"Authorization": pat, "Content-Type": "application/json"}, timeout=timeout)
        self._publication_id = publication_id

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        mutation = (
            "mutation PublishPost($input: PublishPostInput!) { "
            "publishPost(input: $input) { post { id url } } }"
        )
        variables: dict[str, object] = {
            "input": {
                "title": post.title,
                "contentMarkdown": post.body_html,
                "publicationId": self._publication_id,
                "originalArticleURL": post.target_url or None,
                "slug": post.slug,
            }
        }
        data = self.request_json(
            "POST", self._ENDPOINT, json_body={"query": mutation, "variables": variables}
        )
        errors = data.get("errors")
        if errors:
            raise ProviderCallError(f"Hashnode GraphQL error: {errors}")
        post_row = ((data.get("data") or {}).get("publishPost") or {}).get("post") or {}
        post_url = str(post_row.get("url") or "")
        if not post_url:
            raise ProviderCallError("Hashnode response missing post url")
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(post_row.get("id") or ""))


# --------------------------------------------------------------------------- #
# Hatena Blog - AtomPub (RFC 5023); XML, not JSON, so this builds/parses the Atom
# entry directly rather than through request_json.
# --------------------------------------------------------------------------- #
_ATOM_NS = "http://www.w3.org/2005/Atom"
_APP_NS = "http://www.w3.org/2007/app"


def _hatena_entry_xml(post: Web2Post) -> str:
    entry = ET.Element("entry", xmlns=_ATOM_NS)
    ET.SubElement(entry, "title").text = post.title
    content = ET.SubElement(entry, "content", type="text/plain")
    content.text = _html_to_text(post.body_html) + f"\n\n{post.anchor}: {post.target_url}"
    control = ET.SubElement(entry, "app:control", {"xmlns:app": _APP_NS})
    ET.SubElement(control, "app:draft").text = "no"
    return "<?xml version='1.0' encoding='utf-8'?>" + ET.tostring(entry, encoding="unicode")


def _parse_hatena_response(xml_text: str) -> tuple[str | None, str | None]:
    """``(member_id, alternate_link)`` from an AtomPub entry response, or
    ``(None, None)`` on unparseable XML (surfaced by the caller as a clean error)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None, None
    entry_id = root.findtext(f"{{{_ATOM_NS}}}id")
    member_id = entry_id.rsplit("-", 1)[-1] if entry_id else None
    alt_link = None
    for link in root.findall(f"{{{_ATOM_NS}}}link"):
        if link.get("rel") == "alternate":
            alt_link = link.get("href")
            break
    return member_id, alt_link


class HatenaBlogClient(HttpProviderClient):
    """Real ``Web2Publisher`` over Hatena Blog's AtomPub API. Auth = HTTP Basic
    (the Hatena ID + the blog's AtomPub API key, from Blog settings > Advanced)."""

    provider = "hatena"
    platform = PLATFORM_HATENA

    def __init__(self, *, hatena_id: str, blog_id: str, api_key: str, timeout: float = 30.0) -> None:
        if not hatena_id or not blog_id or not api_key:
            raise ProviderNotConfiguredError(f"Hatena Blog publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url=f"https://blog.hatena.ne.jp/{hatena_id}/{blog_id}/atom",
            headers={"Content-Type": "application/atom+xml;type=entry"},
            timeout=timeout,
        )
        self._auth = (hatena_id, api_key)

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        entry = _hatena_entry_xml(post)
        path = f"/entry/{post.external_id}" if post.external_id else "/entry"
        response = self._client.request(
            "PUT" if post.external_id else "POST", path, content=entry.encode("utf-8"), auth=self._auth,
        )
        if response.status_code >= 400:
            raise ProviderCallError(f"Hatena Blog request failed with status {response.status_code}")
        member_id, alt_link = _parse_hatena_response(response.text)
        if not alt_link:
            raise ProviderCallError("Hatena Blog response missing the entry link")
        return Web2PublishResult(post_url=alt_link, verified=True, external_id=member_id or post.external_id)


# --------------------------------------------------------------------------- #
# LiveJournal / Dreamwidth - the shared LiveJournal-protocol XML-RPC API
# (LJ.XMLRPC.postevent); no OAuth, username + password over HTTPS.
# --------------------------------------------------------------------------- #
class _LJProtocolClient:
    """Shared LiveJournal-protocol XML-RPC publisher - the protocol LiveJournal and
    Dreamwidth (and several other legacy journal platforms) share verbatim. This
    simple client sends the password over HTTPS rather than the protocol's optional
    challenge/response MD5 handshake, matching the reference doc's own 'password-
    based XML-RPC, no OAuth' note for both platforms."""

    platform = ""
    _endpoint = ""
    _host = ""

    def __init__(self, *, username: str, password: str) -> None:
        if not username or not password:
            raise ProviderNotConfiguredError(
                f"{self.platform} publisher unavailable: pass a per-account username + "
                "password (per-property, from the vault) to publish a Web 2.0 property"
            )
        self._username = username
        self._password = password

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        import xmlrpc.client as xmlrpc

        proxy = xmlrpc.ServerProxy(self._endpoint)
        event: dict[str, object] = {
            "username": self._username,
            "password": self._password,
            "subject": post.title,
            "event": _html_to_text(post.body_html) + f"\n\n{post.anchor}: {post.target_url}",
            "security": "public",
            "props": {},
        }
        method = proxy.LJ.XMLRPC.postevent
        if post.external_id:
            event["itemid"] = post.external_id
            method = proxy.LJ.XMLRPC.editevent
        try:
            result = method(event)
        except (xmlrpc.Fault, OSError) as exc:
            raise ProviderCallError(f"{self.platform} XML-RPC call failed: {exc}") from exc
        item_id = result.get("itemid")
        if item_id is None:
            raise ProviderCallError(f"{self.platform} response missing itemid")
        post_url = str(result.get("url") or self._permalink(item_id, result.get("anum")))
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(item_id))

    def _permalink(self, item_id: Any, anum: Any) -> str:
        # The journal-protocol permalink formula: ditemid = itemid*256 + anum.
        ditemid = int(item_id) * 256 + int(anum or 0)
        return f"https://{self._username}.{self._host}/{ditemid}.html"


class LiveJournalClient(_LJProtocolClient):
    provider = "livejournal"
    platform = PLATFORM_LIVEJOURNAL
    _endpoint = "https://www.livejournal.com/interface/xmlrpc"
    _host = "livejournal.com"


class DreamwidthClient(_LJProtocolClient):
    provider = "dreamwidth"
    platform = PLATFORM_DREAMWIDTH
    _endpoint = "https://www.dreamwidth.org/interface/xmlrpc"
    _host = "dreamwidth.org"


# --------------------------------------------------------------------------- #
# Deterministic, offline publisher (all platforms; Medium draft-only).
# --------------------------------------------------------------------------- #
class FakeWeb2Publisher:
    """Deterministic, offline ``Web2Publisher`` for the pipeline + worker suites.

    A create derives a stable positive post id + permalink from
    sha256(``platform|account|slug``); an update (``external_id`` set) echoes that id
    back. Medium (and any draft-only platform) returns ``verified=False`` +
    ``draft_only=True`` (its live-publish API is retired), so the pipeline correctly
    HOLDS a Medium placement instead of claiming it is live. No network, so tests +
    degraded runs are reproducible with zero accounts."""

    def __init__(self, *, account: str = "house") -> None:
        self._account = account

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform not in WEB2_PLATFORMS:
            raise ProviderCallError(f"unknown Web 2.0 platform: {platform}")
        slug = post.slug or _slugify(post.title)
        if post.external_id is not None:
            external_id = post.external_id
        else:
            digest = hashlib.sha256(f"{platform}|{self._account}|{slug}".encode()).hexdigest()
            external_id = str(int(digest[:8], 16) % 1_000_000 + 1)
        host = _fake_host(platform, self._account)
        draft_only = platform in DRAFT_ONLY_PLATFORMS
        return Web2PublishResult(
            post_url=f"https://{host}/{slug}",
            verified=not draft_only,  # a draft-only placement is never 'live/verified'
            external_id=external_id,
            draft_only=draft_only,
        )


def _fake_host(platform: str, account: str) -> str:
    hosts = {
        PLATFORM_WORDPRESS: f"{account}.wordpress.com",
        PLATFORM_BLOGGER: f"{account}.blogspot.com",
        PLATFORM_TUMBLR: f"{account}.tumblr.com",
        PLATFORM_MEDIUM: f"medium.com/@{account}",
    }
    return hosts.get(platform, f"{account}.example")


def _slugify(title: str) -> str:
    """A minimal, deterministic slug: lowercased alnum words joined by hyphens."""
    words = ["".join(ch for ch in word if ch.isalnum()) for word in title.lower().split()]
    slug = "-".join(word for word in words if word)
    return slug or "post"


def web2_publisher_from_settings(settings: Settings) -> Web2Publisher | None:
    """The default publisher a WORKER uses, or ``None`` (degraded - hold at review).

    Live Web 2.0 publishing needs a per-account OAuth token that is per-property and
    lives in the VAULT, NOT in settings (mirroring WordPress application passwords). The
    factory has no such credential, so it returns ``None`` and the publish stage HOLDS
    the placement at the review gate until the service layer builds a real per-account
    client from the vault (a later chunk). No secret is ever logged - only the reason."""
    logger.info("web2_publisher_degraded", reason="per_account_oauth_in_vault")
    return None


# --------------------------------------------------------------------------- #
# Footprint diversification (anti-SpamBrain): vary platform/account/anchor/timing.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FootprintChoice:
    """One diversified placement selection: which ``platform`` + ``account`` to post to,
    which ``anchor`` variant to use, and how long to DELAY (seconds) so a client's
    placements are naturally spread rather than posted in a detectable burst."""

    platform: str
    account: str
    anchor: str
    delay_seconds: int


# A day, in seconds - the default spread window a placement is jittered across.
_DAY = 86_400


def diversify_footprint(
    *,
    seed: str,
    platforms: Sequence[str],
    accounts: Sequence[str],
    anchors: Sequence[str],
    existing: Sequence[tuple[str, str]] = (),
    max_delay_seconds: int = 2 * _DAY,
) -> FootprintChoice:
    """Pick a footprint-diversified ``(platform, account, anchor, delay)``.

    PURE + deterministic in ``seed`` (the client + target id): the SAME seed always
    yields the SAME choice, DIFFERENT seeds spread across the inventory. It PREFERS a
    ``(platform, anchor)`` pair not already in ``existing`` (the placements already
    made for this client), so repeated calls do not stack the same anchor on the same
    platform - the anti-SpamBrain lever. Timing is jittered across ``max_delay_seconds``
    so placements do not all fire at once. Falls back to the rotated default when every
    pair is already used (all inventory exhausted). Raises on empty inventory."""
    if not platforms or not accounts or not anchors:
        raise ValueError("diversify_footprint needs at least one platform, account, and anchor")

    used = {(p, a) for p, a in existing}
    h1 = _hash_int(seed, "platform")
    h2 = _hash_int(seed, "account")
    h3 = _hash_int(seed, "anchor")
    h4 = _hash_int(seed, "delay")

    p_off, a_off, n_off = h1 % len(platforms), h2 % len(accounts), h3 % len(anchors)

    chosen_platform = platforms[p_off]
    chosen_anchor = anchors[n_off]
    # Scan platform x anchor in a hash-rotated order for the first UNUSED pair.
    for i in range(len(platforms)):
        platform = platforms[(p_off + i) % len(platforms)]
        for j in range(len(anchors)):
            anchor = anchors[(n_off + j) % len(anchors)]
            if (platform, anchor) not in used:
                chosen_platform, chosen_anchor = platform, anchor
                break
        else:
            continue
        break

    account = accounts[a_off]
    delay = h4 % max(1, max_delay_seconds)
    return FootprintChoice(
        platform=chosen_platform, account=account, anchor=chosen_anchor, delay_seconds=delay
    )


def _hash_int(seed: str, salt: str) -> int:
    """A stable non-negative int from ``seed``+``salt`` (deterministic; no PRNG state)."""
    return int(hashlib.sha256(f"{seed}|{salt}".encode()).hexdigest()[:12], 16)


