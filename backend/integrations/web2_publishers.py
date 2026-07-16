"""Web 2.0 publish seam (7B-3): the ONLY door to a branded Web 2.0 property.

The publish stage of the off-page pipeline pushes a human-APPROVED, on-topic branded
article to a client's Web 2.0 property (a WordPress.com blog, a Blogger blog, a Tumblr
blog) carrying ONE editorial backlink to the client's page. Reachable exclusively
through the ``Web2Publisher`` Protocol so the service/worker layer can meter, cost-log,
and diversify it - nothing else calls a provider directly. Every placement is
human-approved authority work (a real, on-topic post), NEVER link spam.

FOUR platforms, mirroring the frontend ``Web2Platform`` union (offpage.ts):

* ``WordPressComClient`` - real, WordPress.com REST v1.1 over an OAuth2 bearer token.
* ``BloggerClient``      - real, Blogger v3 over an OAuth2 bearer token.
* ``TumblrClient``       - real, Tumblr v2 over an OAuth2 bearer token.
* **Medium is DRAFT-ONLY** - Medium retired its write/publish API, so there is NO live
  Medium publisher. A Medium placement is prepared as a DRAFT (``verified=False``,
  ``draft_only=True``) for a human to paste/publish; the pipeline holds it, never
  claims it is live. ``FakeWeb2Publisher`` models this so the behaviour is testable.

CREDENTIALS ARE PASSED IN, NEVER READ HERE. A Web 2.0 OAuth token is per-account +
per-property and lives in the VAULT (exactly like a WordPress application password);
the SERVICE layer decrypts it (a later chunk) and constructs the real client per
publish. This seam never touches settings or the vault, and never logs the token (it
rides in the ``Authorization`` header, which the shared client keeps out of every log).

``FakeWeb2Publisher`` is the deterministic, offline publisher: a stable post URL derived
from ``platform|account|slug`` (or the given ``external_id`` echoed on update), so the
pipeline + worker suites run fully live with zero external accounts.

FOOTPRINT DIVERSIFICATION (``diversify_footprint``) is the anti-SpamBrain lever: it
varies the platform / account / anchor / timing so a client's placements do not share a
detectable footprint (same anchor, same platform, all at once). It is a PURE,
deterministic selection over the available inventory + the placements already made.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

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
WEB2_PLATFORMS: frozenset[str] = frozenset(
    {PLATFORM_WORDPRESS, PLATFORM_BLOGGER, PLATFORM_TUMBLR, PLATFORM_MEDIUM}
)
# Medium is draft-only (its publish API is retired); the pipeline never marks it live.
DRAFT_ONLY_PLATFORMS: frozenset[str] = frozenset({PLATFORM_MEDIUM})

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


