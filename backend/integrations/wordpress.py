"""WordPress-publish seam (P7A-2): the ONLY door to a WordPress site.

The publish stage of the content pipeline pushes an approved draft to a client's
WordPress site over the REST API. Reachable exclusively through the
``WordPressPublisher`` Protocol so the service layer can meter/log it later.

Idempotency is the seam's contract: ``publish`` is UPDATE-or-CREATE. If the
``PostDraft`` already carries a ``wp_post_id`` (a prior publish of the same content
job), the client PATCHES that post; otherwise it CREATEs one. So a retried publish
never spawns duplicate posts - the content job records its ``wp_post_id`` once and
every subsequent publish edits in place.

Part 8 Phase 2D (the on-page optimizer) adds the EDIT half of the seam - the
``WordPressEditor`` Protocol (``get_post`` + ``update_post``) - because applying an
on-page fix is a *surgical* edit of ONE field on an EXISTING post, not a publish:

* ``get_post(site_url, post_id, context="edit")`` is what makes the DRIFT-GUARD and
  the post-write VERIFY possible: we re-read the live value before writing (refusing
  to clobber a hand-edit made after the analysis) and again after writing.
* ``update_post(site_url, post_id, fields=..., meta=...)`` is an idempotent UPDATE of
  the named fields only.

THE WORDPRESS REALITY THIS SEAM CANNOT HIDE: the SEO ``<title>`` and meta
description are NOT native WP REST fields. They are SEO-plugin POST META
(``_yoast_wpseo_title`` / ``_yoast_wpseo_metadesc``, ``rank_math_title`` /
``rank_math_description``), and the REST API **silently drops writes to meta keys
that are not registered with ``show_in_rest``** - returning 200 with the OLD value
and no error whatsoever. A caller that trusts the 200 would report a false success
forever. Hence ``update_post`` returns the re-read post and the caller MUST verify;
the on-page worker holds the fix at ``held("SEO-plugin bridge missing")`` rather
than ever claiming a write that did not land.

CREDENTIALS ARE PASSED IN, NEVER READ HERE. A WordPress application password is
per-site + per-user and lives in the vault; the SERVICE layer decrypts it and
constructs ``WordPressClient(username=..., app_password=...)``. This seam never
touches settings or the vault, and never logs the password (it rides in the HTTP
Basic auth header, which the shared client keeps out of every log line).

Impls:

* ``WordPressClient`` - real, WP REST v2 over the shared sync ``HttpProviderClient``.
  Satisfies BOTH Protocols. Credential-gated: empty username/password ->
  ``ProviderNotConfiguredError``.
* ``FakeWordPressPublisher`` - deterministic, offline: a stable post id derived from
  the site + slug/title (or the given ``wp_post_id`` echoed back on update), so
  publish tests + degraded runs are reproducible with no site.
* ``FakeWordPressEditor`` - deterministic, offline ``WordPressEditor`` over an
  in-memory post store, with a ``drop_meta_keys`` switch that REPRODUCES the
  silent-meta-drop failure above so the on-page worker's verify step is testable
  without a WordPress.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

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


@runtime_checkable
class WordPressEditor(Protocol):
    """Read + surgically update ONE existing post (the on-page apply path).

    ``get_post`` MUST be able to read with ``context='edit'``: the public
    (``context='view'``) representation omits ``meta`` and renders ``title`` /
    ``content`` to HTML, so a drift-guard or a verify built on the view context would
    compare against the wrong bytes. ``update_post`` returns the post AS THE SERVER
    NOW HAS IT so the caller can VERIFY the write actually landed (see the module
    docstring: WP silently drops unregistered meta keys).
    """

    def get_post(self, site_url: str, post_id: int, context: str = ...) -> dict[str, Any]: ...

    def update_post(
        self,
        site_url: str,
        post_id: int,
        *,
        fields: dict[str, Any] | None = ...,
        meta: dict[str, Any] | None = ...,
    ) -> dict[str, Any]: ...


class WordPressClient(HttpProviderClient):
    """Real ``WordPressPublisher`` + ``WordPressEditor`` over the WP REST v2 API.

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

    def _post_endpoint(self, site_url: str, post_id: int) -> str:
        return f"{site_url.rstrip('/')}/wp-json/wp/v2/posts/{post_id}"

    def get_post(self, site_url: str, post_id: int, context: str = "edit") -> dict[str, Any]:
        """Read ONE post. ``context='edit'`` is the default deliberately: only the edit
        representation carries ``meta`` and the RAW title/content, which the on-page
        drift-guard + verify compare against. Requires the credential to have edit
        rights on the post (an app password for an author/editor does)."""
        return self.request_json(
            "GET",
            self._post_endpoint(site_url, post_id),
            params={"context": context},
            auth=self._auth,
        )

    def update_post(
        self,
        site_url: str,
        post_id: int,
        *,
        fields: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Idempotently UPDATE the named fields (and/or SEO-plugin post meta) of an
        EXISTING post; returns the post as the server now has it.

        Idempotent by construction: it targets one ``post_id`` and sets absolute
        values, so re-running it with the same payload is a no-op on the site. An
        empty payload is a plain re-read (never a blind write).

        THE CALLER MUST VERIFY THE RESULT. ``meta`` writes to keys an SEO plugin has
        not registered with ``show_in_rest`` are SILENTLY DROPPED by WordPress: the
        response is 200 and carries the OLD value. Only comparing the returned post
        against what was sent can tell a real write from a no-op.
        """
        body: dict[str, Any] = dict(fields or {})
        if meta:
            body["meta"] = dict(meta)
        if not body:
            return self.get_post(site_url, post_id)
        # WP treats POST to a single-post route as an update (as the publish path does).
        return self.request_json(
            "POST", self._post_endpoint(site_url, post_id), json_body=body, auth=self._auth
        )

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


class FakeWordPressEditor:
    """Deterministic, offline ``WordPressEditor`` over an in-memory post store.

    ``posts`` maps ``post_id -> post dict`` (the WP ``context=edit`` shape: ``title``/
    ``content``/``excerpt`` as ``{"raw": ...}`` sub-objects, plus a flat ``meta``
    dict). Every read returns a DEEP COPY, so a caller that mutates what it read can
    never accidentally "write" to the site - which would hide a real drift bug.

    ``drop_meta_keys`` REPRODUCES THE REAL FAILURE the on-page apply path must survive:
    WordPress silently ignores writes to post-meta keys that no plugin registered with
    ``show_in_rest``, answering 200 with the OLD value. Listing a key here makes this
    fake drop it exactly the same way, with no error - so a test can prove the worker
    VERIFIES the write and holds instead of reporting a false success.
    """

    def __init__(
        self,
        posts: dict[int, dict[str, Any]] | None = None,
        *,
        drop_meta_keys: frozenset[str] | set[str] | None = None,
    ) -> None:
        self.posts: dict[int, dict[str, Any]] = copy.deepcopy(posts or {})
        self.drop_meta_keys: set[str] = set(drop_meta_keys or ())
        self.reads: list[tuple[int, str]] = []
        self.writes: list[tuple[int, dict[str, Any], dict[str, Any]]] = []

    def get_post(self, site_url: str, post_id: int, context: str = "edit") -> dict[str, Any]:
        self.reads.append((post_id, context))
        post = self.posts.get(post_id)
        if post is None:
            raise ProviderCallError(f"WordPress post {post_id} not found")
        return copy.deepcopy(post)

    def update_post(
        self,
        site_url: str,
        post_id: int,
        *,
        fields: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.writes.append((post_id, dict(fields or {}), dict(meta or {})))
        post = self.posts.get(post_id)
        if post is None:
            raise ProviderCallError(f"WordPress post {post_id} not found")
        for key, value in (fields or {}).items():
            # Native fields round-trip through the {"raw": ...} edit shape.
            post[key] = {"raw": value} if isinstance(post.get(key), dict) else value
        stored_meta: dict[str, Any] = post.setdefault("meta", {})
        for key, value in (meta or {}).items():
            if key in self.drop_meta_keys:
                continue  # WP's silent drop: no error, the old value simply stays.
            stored_meta[key] = value
        return copy.deepcopy(post)


def _slugify(title: str) -> str:
    """A minimal, deterministic slug: lowercased alnum words joined by hyphens."""
    words = ["".join(ch for ch in word if ch.isalnum()) for word in title.lower().split()]
    slug = "-".join(word for word in words if word)
    return slug or "post"
