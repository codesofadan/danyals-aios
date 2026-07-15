"""WordPress-publish seam (P7A-2): the ONLY door to a WordPress site.

The publish stage of the content pipeline pushes an approved draft to a client's
WordPress site over the REST API. Reachable exclusively through the
``WordPressPublisher`` Protocol so the service layer can meter/log it later.

Idempotency is the seam's contract: ``publish`` is UPDATE-or-CREATE. If the
``PostDraft`` already carries a ``wp_post_id`` (a prior publish of the same content
job), the client PATCHES that post; otherwise it CREATEs one. So a retried publish
never spawns duplicate posts - the content job records its ``wp_post_id`` once and
every subsequent publish edits in place.

CREDENTIALS ARE PASSED IN, NEVER READ HERE. A WordPress application password is
per-site + per-user and lives in the vault; the SERVICE layer decrypts it (a later
chunk) and constructs ``WordPressClient(username=..., app_password=...)``. This seam
never touches settings or the vault, and never logs the password (it rides in the
HTTP Basic auth header, which the shared client keeps out of every log line).

Two impls satisfy the Protocol:

* ``WordPressClient`` - real, WP REST v2 over the shared sync ``HttpProviderClient``.
  Credential-gated: empty username/password -> ``ProviderNotConfiguredError``.
* ``FakeWordPressPublisher`` - deterministic, offline: a stable post id derived from
  the site + slug/title (or the given ``wp_post_id`` echoed back on update), so
  publish tests + degraded runs are reproducible with no site.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from integrations.errors import ProviderCallError, ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

_INSTALL_HINT = (
    "pass a WordPress username + application password (per-site, from the vault) "
    "to publish"
)


@dataclass(frozen=True)
class PostDraft:
    """The content to publish. ``wp_post_id`` set => idempotent UPDATE, else CREATE.

    ``content`` is rendered HTML; ``status`` is the WP post status (``draft`` keeps a
    human-approval step on the WP side, ``publish`` goes live). ``slug`` / ``excerpt``
    are optional; the pipeline supplies them from the job.
    """

    title: str
    content: str
    status: str = "draft"
    slug: str | None = None
    excerpt: str | None = None
    wp_post_id: int | None = None


@dataclass(frozen=True)
class PublishResult:
    """The published post's WP id (record it on the job for idempotent re-publish)
    and its public URL."""

    post_id: int
    url: str


@runtime_checkable
class WordPressPublisher(Protocol):
    """Publish (or, when ``post.wp_post_id`` is set, update) a post on ``site_url``."""

    def publish(self, site_url: str, post: PostDraft) -> PublishResult: ...


class WordPressClient(HttpProviderClient):
    """Real ``WordPressPublisher`` over the WP REST v2 API.

    Auth is an application password via HTTP Basic (``username`` + ``app_password``),
    handed to ``httpx`` per request and NEVER logged. The caller (service layer)
    supplies the decrypted credential; this class never reads the vault.
    """

    provider = "wordpress"

    def __init__(self, *, username: str, app_password: str, timeout: float = 30.0) -> None:
        if not username or not app_password:
            raise ProviderNotConfiguredError(f"WordPress client unavailable: {_INSTALL_HINT}")
        # No base_url: each publish targets a per-call absolute site URL.
        super().__init__(headers={"Content-Type": "application/json"}, timeout=timeout)
        self._auth = (username, app_password)

    def publish(self, site_url: str, post: PostDraft) -> PublishResult:
        endpoint = f"{site_url.rstrip('/')}/wp-json/wp/v2/posts"
        body: dict[str, object] = {
            "title": post.title,
            "content": post.content,
            "status": post.status,
        }
        if post.slug:
            body["slug"] = post.slug
        if post.excerpt:
            body["excerpt"] = post.excerpt
        # Idempotent: an existing post id -> POST to /posts/{id} (WP treats POST to a
        # single-post route as an update), else POST to /posts to create.
        url = f"{endpoint}/{post.wp_post_id}" if post.wp_post_id else endpoint
        data = self.request_json("POST", url, json_body=body, auth=self._auth)
        post_id = data.get("id")
        link = data.get("link")
        if not isinstance(post_id, int) or not isinstance(link, str):
            raise ProviderCallError("WordPress response missing post id or link")
        return PublishResult(post_id=post_id, url=link)


class FakeWordPressPublisher:
    """Deterministic, offline ``WordPressPublisher``.

    An update (``wp_post_id`` set) echoes that id back; a create derives a stable
    positive id from sha256(site + slug/title). The URL is a stable permalink under
    the site. No network, so publish tests + degraded runs are reproducible.
    """

    def publish(self, site_url: str, post: PostDraft) -> PublishResult:
        site = site_url.rstrip("/")
        slug = post.slug or _slugify(post.title)
        if post.wp_post_id is not None:
            post_id = post.wp_post_id
        else:
            digest = hashlib.sha256(f"{site}|{slug}".encode()).hexdigest()
            post_id = int(digest[:8], 16) % 1_000_000 + 1  # stable positive id
        return PublishResult(post_id=post_id, url=f"{site}/{slug}")


def _slugify(title: str) -> str:
    """A minimal, deterministic slug: lowercased alnum words joined by hyphens."""
    words = ["".join(ch for ch in word if ch.isalnum()) for word in title.lower().split()]
    slug = "-".join(word for word in words if word)
    return slug or "post"
