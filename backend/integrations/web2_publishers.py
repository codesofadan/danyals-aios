"""Web 2.0 publish seam (7B-3, expanded 7B-4): the ONLY door to a branded Web 2.0
property.

The publish stage of the off-page pipeline pushes a human-APPROVED, on-topic branded
article to a client's Web 2.0 property carrying ONE editorial backlink to the client's
page. Reachable exclusively through the ``Web2Publisher`` Protocol so the
service/worker layer can meter, cost-log, and diversify it - nothing else calls a
provider directly. Every placement is human-approved authority work (a real, on-topic
post), NEVER link spam.

FIFTY platforms, mirroring the frontend ``Web2Platform`` union (offpage.ts) - the
original 17 the 17 Jul 2026 reference doc tags API-post: Yes, not deprecated, and not a
blockchain/OAuth1/brand-risk case that would need a materially different credential
model (Hive/Steemit need a custody-sensitive private key, not an OAuth token; Gab
carries the doc's own explicit brand-safety warning) - those stay future work - plus 4
more real CMS/site-builder adapters added in a later pass, plus a THIRD pass of 19 more
(pastes/gists/static-hosts, ATProto/fediverse, and 3 honest profile/thin placements):

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
* ``WebflowClient``    - real, Webflow Data API v2, Bearer site token, a two-step
  publish (write the CMS item, then hit the collection's ``/publish`` endpoint so it
  goes live at once).
* ``HubSpotClient``    - real, HubSpot CMS Blog Post API v3, private-app Bearer
  token; needs an existing blog (``content_group_id``) to post into.
* ``DrupalClient``     - real, Drupal core JSON:API (ships in core >= 8.7, no contrib
  module), HTTP Basic with an API-only Drupal user (Basic-auth is exempt from
  Drupal's cookie-session CSRF check, so no separate token handshake).
* ``JoomlaClient``     - real, Joomla's core Web Services API (com_content, Joomla
  4.3+ "API Token"), Bearer token; builds the always-resolvable non-SEF permalink
  since Joomla's response carries no absolute public URL.

THIRD PASS (19 more, Aug 2026) - every one web-verified live/self-serve at build time;
Evernote (developer tokens disabled, OAuth needs a manual up-to-5-day review), Issuu
(API gated to paid tiers AND a document/flipbook content model that does not fit a
plain HTML article without a fragile conversion step), and Nostr long-form/NIP-23
(would need a new, fairly heavy secp256k1-signing dependency to do the BIP-340 Schnorr
signing correctly - reported as skipped rather than hand-rolled) were investigated and
deliberately NOT built - see the migration header for the historical record:

* ``HackMDClient``, ``GitHubGistClient``, ``GitLabSnippetsClient``, ``PasteEeClient``,
  ``NetlifyClient``, ``NeocitiesClient`` - real, plain PAT/API-key Bearer (or
  GitLab's ``PRIVATE-TOKEN``) header + JSON REST, mirroring ``DevToClient``.
* ``PastebinClient`` - real, but the classic ``api_post.php`` endpoint is
  form-encoded and returns a bare TEXT url (not JSON), so it bypasses
  ``request_json`` for its one call, same as ``TelegraPhClient``.
* ``RentryClient`` / ``DpasteClient`` - real, fully ANONYMOUS (no credential at all -
  ``PLATFORM_CREDENTIAL_FIELDS`` is an empty tuple for both); rentry needs a
  CSRF cookie handshake first (an httpx cookie jar), dpaste is a bare POST.
* ``MisskeyClient`` - real, distinct fediverse software from Mastodon (its own
  client, not a Mastodon instance); the access token rides IN THE JSON BODY
  (``i``), never an Authorization header - a documented Misskey quirk.
* ``LemmyClient`` - real, POST .../user/login for a JWT, resolve the target
  community name to an id, then post a LINK post (``url`` = the backlink) into it.
* ``BlueskyClient`` / ``WhiteWindClient`` - real, AT Protocol (App Password ->
  ``createSession`` -> ``createRecord``/``putRecord``); WhiteWind reuses the SAME
  Bluesky account/session to write a ``com.whtwnd.blog.entry`` long-form record
  (a genuine full article, unlike Bluesky's ~300-grapheme post).
* ``DisqusClient`` / ``GravatarClient`` - real, but a THIN PROFILE placement, NOT
  an article (same honesty as Medium's draft-only note) - there is no
  "article" concept on either platform, only one profile/bio the backlink
  lives on; every publish() call just re-asserts that same profile.
* ``PlurkClient`` - real, the one OAuth1 (not OAuth2) platform here - every call
  is individually HMAC-SHA1 signed (hand-rolled, no new OAuth1 dependency for a
  single caller).
* ``PixelfedClient`` - real, Mastodon-compatible REST but REQUIRES an image on
  every post (unlike Mastodon); ``Web2Post`` has no image field, so this client
  takes a fixed brand ``placeholder_image_url``, fetches it once, and uploads it
  as the post's required media.
* ``NotionClient`` - real, creates a genuine Notion page under a pre-existing
  parent - but Notion's API has NO endpoint to flip "Share to web" (verified
  against 2026 docs), so this ALWAYS returns ``verified=False``, same honesty as
  ``GitLabPagesClient``'s CI-pending publish.
* ``MindsClient`` - real, a personal-access-token POST to the account's public
  channel/newsfeed.

FOURTH PASS (10 more, Aug 2026) - research-repository + static-host + legacy-blog +
fediverse platforms, every one web-verified live/self-serve at build time:

* ``ZenodoClient`` - real, Zenodo's deposit REST API, Bearer token. Publish is
  ONE-WAY (a published deposit cannot be edited/re-published through this simple
  flow - only a full new-version workflow supersedes it), so a SECOND
  ``publish()`` call against an already-published ``external_id`` re-fetches and
  returns the SAME record rather than erroring or silently re-publishing.
* ``InternetArchiveClient`` - real, IA's S3-like upload API (s3.us.archive.org).
  Auth is IA's own ``LOW key:secret`` scheme (not AWS SigV4); one publish = one
  new "item" holding a single static HTML file, auto-created via
  ``x-archive-auto-make-bucket``. A documented ``503 SlowDown`` needs no special
  handling - it already falls inside ``HttpProviderClient``'s universal
  ``5xx`` transient range.
* ``OSFClient`` - real, the Open Science Framework's JSON:API v2, Bearer token.
  ``public: true`` is set EXPLICITLY on every create (OSF nodes default private).
* ``FigshareClient`` - real, Figshare API v2, a raw ``token`` auth scheme (not
  Bearer). Two-step publish (create, then a separate explicit
  ``.../publish`` call) mirroring Zenodo's own draft-then-publish design; the
  public URL uses Figshare's stable DOI convention rather than guessing the
  title-slugged web path (not reliably derivable from the API alone).
* ``CodebergPagesClient`` - real, mirrors ``GitHubPagesClient`` almost exactly
  (Codeberg runs Gitea; the Contents API is API-compatible) - the two
  differences are Gitea's own ``token <TOKEN>`` auth header and Codeberg
  Pages' dedicated ``pages`` branch (not ``main``/``gh-pages``).
* ``LivedoorBlogClient`` - real, Livedoor Blog's AtomPub API - the exact same
  protocol as ``HatenaBlogClient`` (reuses its Atom-entry XML builder/parser
  directly), HTTP Basic with a separately-issued AtomPub API key (never the
  account password).
* ``FC2BlogClient`` / ``SeesaaBlogClient`` - real, the shared legacy
  metaWeblog XML-RPC protocol (one ``_MetaWeblogClient`` base, two hosts -
  the same pattern ``_LJProtocolClient`` already establishes for
  LiveJournal/Dreamwidth). ``newPost``/``editPost`` return only a bare post id,
  never a permalink, so both follow up with the protocol's own ``getPost`` to
  read back the host-assigned URL rather than guessing a subdomain pattern.
* ``WarpcastClient`` - real, Farcaster casts via the Neynar API (``x-api-key``
  header, NOT ``Authorization: Bearer``), needing a pre-approved
  ``signer_uuid`` credential (the one-time signer handshake happens outside
  this system, by the account owner).
* ``SourcehutPagesClient`` - real, pages.sr.ht's GraphQL API - a ``publish``
  mutation taking a tarball ``Upload``, built entirely from the stdlib
  (``tarfile`` + ``io.BytesIO``) and sent as a standard GraphQL multipart
  request (no new dependency).

Investigated and DELIBERATELY NOT built this pass (see the migration header for
the historical record): **CodeSandbox** (the modern SDK's sandbox-creation call has
no publicly documented raw HTTP endpoint behind ``CSB_API_KEY``; the older,
keyless "Define API" is a different, legacy code-demo product not gated by any
per-account credential and not a durable article host), **GitBook** (creating a
Space is confirmed, but pushing real page CONTENT into it needs an undocumented
change-request/content-operations flow - only a CLI reference was found, no
verifiable REST shape), **Read the Docs** (a documented project-create call exists,
but "live" requires a connected git repo + a Sphinx/MkDocs build - the same
content-model mismatch that ruled out GitLab Pages' CI dependency, just too severe
to half-support here), and **Hive**/**Steemit** (both need custody-sensitive
secp256k1 transaction signing - the identical "new heavy crypto dependency" bar
that got Nostr dropped last pass; nothing suitable already sits in
``pyproject.toml``, so both stay skipped for the same reason).

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
import hmac
import io
import json
import re
import secrets
import tarfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast, runtime_checkable
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
PLATFORM_WEBFLOW = "Webflow"
PLATFORM_HUBSPOT = "HubSpot CMS"
PLATFORM_DRUPAL = "Drupal"
PLATFORM_JOOMLA = "Joomla"
# Third pass (Aug 2026) - 19 more real clients (see the module docstring above).
PLATFORM_HACKMD = "HackMD"
PLATFORM_GITHUB_GIST = "GitHub Gist"
PLATFORM_GITLAB_SNIPPETS = "GitLab Snippets"
PLATFORM_PASTE_EE = "paste.ee"
PLATFORM_PASTEBIN = "Pastebin.com"
PLATFORM_NETLIFY = "Netlify"
PLATFORM_NEOCITIES = "Neocities"
PLATFORM_RENTRY = "rentry.co"
PLATFORM_DPASTE = "dpaste.org"
PLATFORM_MISSKEY = "Misskey"
PLATFORM_LEMMY = "Lemmy"
PLATFORM_BLUESKY = "Bluesky"
PLATFORM_WHITEWIND = "WhiteWind"
PLATFORM_DISQUS = "Disqus"
PLATFORM_PLURK = "Plurk"
PLATFORM_PIXELFED = "Pixelfed"
PLATFORM_NOTION = "Notion"
PLATFORM_GRAVATAR = "Gravatar"
PLATFORM_MINDS = "Minds"
# Fourth pass (Aug 2026) - 10 more real clients (see the module docstring above).
PLATFORM_ZENODO = "Zenodo"
PLATFORM_INTERNET_ARCHIVE = "Internet Archive"
PLATFORM_OSF = "OSF"
PLATFORM_FIGSHARE = "Figshare"
PLATFORM_CODEBERG_PAGES = "Codeberg Pages"
PLATFORM_LIVEDOOR = "Livedoor Blog"
PLATFORM_FC2 = "FC2 Blog"
PLATFORM_SEESAA = "Seesaa Blog"
PLATFORM_WARPCAST = "Warpcast"
PLATFORM_SOURCEHUT_PAGES = "Sourcehut Pages"

WEB2_PLATFORMS: frozenset[str] = frozenset(
    {
        PLATFORM_WORDPRESS, PLATFORM_BLOGGER, PLATFORM_TUMBLR, PLATFORM_MEDIUM,
        PLATFORM_DEVTO, PLATFORM_WRITEAS, PLATFORM_TELEGRAPH, PLATFORM_MATAROA,
        PLATFORM_GHOST, PLATFORM_MASTODON, PLATFORM_GITHUB_PAGES, PLATFORM_GITLAB_PAGES,
        PLATFORM_MICROBLOG, PLATFORM_HASHNODE, PLATFORM_HATENA, PLATFORM_LIVEJOURNAL,
        PLATFORM_DREAMWIDTH, PLATFORM_WEBFLOW, PLATFORM_HUBSPOT, PLATFORM_DRUPAL,
        PLATFORM_JOOMLA,
        PLATFORM_HACKMD, PLATFORM_GITHUB_GIST, PLATFORM_GITLAB_SNIPPETS, PLATFORM_PASTE_EE,
        PLATFORM_PASTEBIN, PLATFORM_NETLIFY, PLATFORM_NEOCITIES, PLATFORM_RENTRY,
        PLATFORM_DPASTE, PLATFORM_MISSKEY, PLATFORM_LEMMY, PLATFORM_BLUESKY,
        PLATFORM_WHITEWIND, PLATFORM_DISQUS, PLATFORM_PLURK, PLATFORM_PIXELFED,
        PLATFORM_NOTION, PLATFORM_GRAVATAR, PLATFORM_MINDS,
        PLATFORM_ZENODO, PLATFORM_INTERNET_ARCHIVE, PLATFORM_OSF, PLATFORM_FIGSHARE,
        PLATFORM_CODEBERG_PAGES, PLATFORM_LIVEDOOR, PLATFORM_FC2, PLATFORM_SEESAA,
        PLATFORM_WARPCAST, PLATFORM_SOURCEHUT_PAGES,
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
    PLATFORM_WEBFLOW: ("api_token", "collection_id", "site"),
    PLATFORM_HUBSPOT: ("access_token", "content_group_id"),
    PLATFORM_DRUPAL: ("base_url", "username", "password"),
    PLATFORM_JOOMLA: ("base_url", "api_token", "catid"),
    PLATFORM_HACKMD: ("token",),
    PLATFORM_GITHUB_GIST: ("token",),
    PLATFORM_GITLAB_SNIPPETS: ("token",),
    PLATFORM_PASTE_EE: ("api_key",),
    PLATFORM_PASTEBIN: ("api_dev_key",),
    PLATFORM_NETLIFY: ("api_token", "site_id"),
    PLATFORM_NEOCITIES: ("api_key", "sitename"),
    # rentry.co / dpaste.org are fully anonymous - no credential fields at all; a
    # vault row must still exist (even an empty ``{}``) to opt a client into them.
    PLATFORM_RENTRY: (),
    PLATFORM_DPASTE: (),
    PLATFORM_MISSKEY: ("token",),
    PLATFORM_LEMMY: ("username", "password", "community"),
    PLATFORM_BLUESKY: ("identifier", "app_password"),
    PLATFORM_WHITEWIND: ("identifier", "app_password"),
    PLATFORM_DISQUS: ("access_token", "api_key", "username"),
    PLATFORM_PLURK: ("consumer_key", "consumer_secret", "access_token", "access_token_secret"),
    PLATFORM_PIXELFED: ("access_token", "placeholder_image_url"),
    PLATFORM_NOTION: ("integration_token", "parent_page_id"),
    PLATFORM_GRAVATAR: ("api_token", "username"),
    PLATFORM_MINDS: ("access_token",),
    PLATFORM_ZENODO: ("access_token",),
    PLATFORM_INTERNET_ARCHIVE: ("access_key", "secret_key"),
    PLATFORM_OSF: ("access_token",),
    PLATFORM_FIGSHARE: ("access_token",),
    PLATFORM_CODEBERG_PAGES: ("token", "owner", "repo"),
    PLATFORM_LIVEDOOR: ("livedoor_id", "blog_name", "api_key"),
    PLATFORM_FC2: ("blog_id", "username", "password"),
    PLATFORM_SEESAA: ("blog_id", "username", "password"),
    PLATFORM_WARPCAST: ("api_key", "signer_uuid"),
    PLATFORM_SOURCEHUT_PAGES: ("token", "domain"),
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
            # dev.to sits behind Cloudflare, which 403s the default httpx UA; send a
            # browser UA (+ the Forem API Accept type) so the write actually lands.
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/vnd.forem.api-v1+json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                ),
            },
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
        # published_at MUST be set or Mataroa keeps the post as a private DRAFT (the
        # public URL then redirects to the marketing homepage). Stamp today so the
        # placement goes live immediately.
        from datetime import date

        body: dict[str, object] = {
            "title": post.title,
            "body": post.body_html,
            "slug": slug,
            "published_at": date.today().isoformat(),
        }
        if post.external_id:
            data = self.request_json("PATCH", f"/api/posts/{post.external_id}/", json_body=body)
        else:
            data = self.request_json("POST", "/api/posts/", json_body=body)
        returned_slug = str(data.get("slug") or slug)
        # Mataroa serves each post on the ACCOUNT's own subdomain and returns the
        # canonical public URL in ``url`` - the old hardcoded ``mataroa.blog/blog/<slug>``
        # is NOT the live post (it redirects to the marketing homepage). Prefer the
        # returned URL; fall back to the account-agnostic form only if it is absent.
        post_url = str(data.get("url") or f"https://mataroa.blog/blog/{returned_slug}/")
        return Web2PublishResult(post_url=post_url, verified=True, external_id=returned_slug)


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
# Webflow - Data API v2, Bearer site token. A two-step publish: write the CMS item
# (staged), then hit the collection's /publish endpoint so it goes live at once -
# the same two-step honesty as GitHubPagesClient's commit-then-enable-Pages.
# --------------------------------------------------------------------------- #
class WebflowClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the Webflow Data API v2. ``site`` is the
    ``*.webflow.io`` subdomain - Webflow's item response carries no absolute URL, so
    the live permalink has to be built from the account's own site slug.
    ``url_path`` (default ``"blog"``) is the collection's configured slug path; it
    is an optional constructor kwarg, not a required credential, because most
    collections use the same default and forcing it into every vault row would be
    needless friction."""

    provider = "webflow"
    platform = PLATFORM_WEBFLOW

    def __init__(
        self, *, api_token: str, collection_id: str, site: str, url_path: str = "blog", timeout: float = 30.0
    ) -> None:
        if not api_token or not collection_id or not site:
            raise ProviderNotConfiguredError(f"Webflow publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://api.webflow.com/v2",
            headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        self._collection_id = collection_id
        self._site = site
        self._url_path = url_path.strip("/")

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        slug = post.slug or _slugify(post.title)
        field_data: dict[str, object] = {"name": post.title, "slug": slug, "post-body": post.body_html}
        body: dict[str, object] = {"isArchived": False, "isDraft": False, "fieldData": field_data}
        base = f"/collections/{self._collection_id}/items"
        if post.external_id:
            data = self.request_json("PATCH", f"{base}/{post.external_id}", json_body=body)
        else:
            data = self.request_json("POST", base, json_body=body)
        item_id = data.get("id")
        if not item_id:
            raise ProviderCallError("Webflow response missing item id")
        # Creating/updating an item only STAGES it - Webflow requires this second call
        # to actually push the collection live, hence the two-step publish.
        self.request_json("POST", f"{base}/publish", json_body={"itemIds": [str(item_id)]})
        post_url = f"https://{self._site}.webflow.io/{self._url_path}/{slug}"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(item_id))


# --------------------------------------------------------------------------- #
# HubSpot CMS - Blog Post API v3, private-app Bearer token.
# --------------------------------------------------------------------------- #
class HubSpotClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the HubSpot CMS Blog Post API v3. Auth = a
    private-app Bearer token. ``content_group_id`` (the target blog's id) is a
    required credential field - HubSpot has no "default blog", a post must be
    created against an existing one."""

    provider = "hubspot"
    platform = PLATFORM_HUBSPOT

    def __init__(self, *, access_token: str, content_group_id: str, timeout: float = 30.0) -> None:
        if not access_token or not content_group_id:
            raise ProviderNotConfiguredError(f"HubSpot CMS publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://api.hubapi.com/cms/v3/blogs",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        self._content_group_id = content_group_id

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        slug = post.slug or _slugify(post.title)
        body: dict[str, object] = {
            "name": post.title, "slug": slug, "postBody": post.body_html,
            "contentGroupId": self._content_group_id, "state": "PUBLISHED",
        }
        if post.external_id:
            data = self.request_json("PATCH", f"/posts/{post.external_id}", json_body=body)
        else:
            data = self.request_json("POST", "/posts", json_body=body)
        post_url = str(data.get("url") or "")
        post_id = data.get("id")
        if not post_url:
            raise ProviderCallError("HubSpot response missing post url")
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(post_id) if post_id else None)


# --------------------------------------------------------------------------- #
# Drupal - core JSON:API (ships in core >= 8.7, no contrib module needed).
# --------------------------------------------------------------------------- #
class DrupalClient(HttpProviderClient):
    """Real ``Web2Publisher`` over Drupal core's JSON:API. Auth = HTTP Basic with an
    API-only Drupal user - Basic-auth requests are exempt from Drupal's cookie-
    session CSRF check, so no separate CSRF-token handshake is needed (uses
    ``request_json``'s existing ``auth=`` param rather than hand-rolling a second
    HTTP path). ``content_type`` is the node bundle machine name, an optional
    constructor kwarg defaulting to ``"article"`` (not a required credential -
    most sites publish blog content under the stock article bundle)."""

    provider = "drupal"
    platform = PLATFORM_DRUPAL

    def __init__(
        self, *, base_url: str, username: str, password: str,
        content_type: str = "article", timeout: float = 30.0,
    ) -> None:
        if not base_url or not username or not password:
            raise ProviderNotConfiguredError(f"Drupal publisher unavailable: {_INSTALL_HINT}")
        self._base = base_url.rstrip("/")
        super().__init__(
            base_url=self._base,
            headers={"Content-Type": "application/vnd.api+json", "Accept": "application/vnd.api+json"},
            timeout=timeout,
        )
        self._auth = (username, password)
        self._content_type = content_type

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        attrs: dict[str, object] = {
            "title": post.title,
            "body": {"value": post.body_html, "format": "full_html"},
            "status": True,
        }
        payload: dict[str, Any] = {"data": {"type": f"node--{self._content_type}", "attributes": attrs}}
        if post.external_id:
            payload["data"]["id"] = post.external_id
            data = self.request_json(
                "PATCH", f"/jsonapi/node/{self._content_type}/{post.external_id}",
                json_body=payload, auth=self._auth,
            )
        else:
            data = self.request_json(
                "POST", f"/jsonapi/node/{self._content_type}", json_body=payload, auth=self._auth,
            )
        row = data.get("data") or {}
        node_attrs = row.get("attributes") or {}
        node_id = row.get("id")
        path_field = node_attrs.get("path")
        path_alias = path_field.get("alias") if isinstance(path_field, dict) else None
        internal_nid = node_attrs.get("drupal_internal__nid")
        if path_alias:
            post_url = f"{self._base}{path_alias}"
        elif internal_nid:
            post_url = f"{self._base}/node/{internal_nid}"
        else:
            raise ProviderCallError("Drupal response missing a resolvable node path")
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(node_id) if node_id else None)


# --------------------------------------------------------------------------- #
# Joomla - core Web Services API (com_content, Joomla 4.3+ "API Token").
# --------------------------------------------------------------------------- #
class JoomlaClient(HttpProviderClient):
    """Real ``Web2Publisher`` over Joomla's core Web Services API. Auth = a
    per-user Bearer "API Token" (created under User > Edit > API Token, Joomla
    4.3+). The response carries no absolute public URL - Joomla's SEF routing is
    site-configured and unknowable from here - so this builds the always-
    resolvable non-SEF permalink (``index.php?option=com_content&view=article&
    id=<id>``) rather than guessing a pretty slug URL: the honest choice, exactly
    like ``GitLabPagesClient`` marking itself unverified when it cannot confirm
    something. Here we CAN confirm the article exists and is published, just not
    its pretty URL, so ``verified=True`` with an ugly-but-correct URL is right."""

    provider = "joomla"
    platform = PLATFORM_JOOMLA

    def __init__(self, *, base_url: str, api_token: str, catid: str, timeout: float = 30.0) -> None:
        if not base_url or not api_token or not catid:
            raise ProviderNotConfiguredError(f"Joomla publisher unavailable: {_INSTALL_HINT}")
        self._base = base_url.rstrip("/")
        super().__init__(
            base_url=self._base,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/vnd.api+json",
                "Accept": "application/vnd.api+json",
            },
            timeout=timeout,
        )
        self._catid = catid

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        attrs: dict[str, object] = {
            "title": post.title,
            "alias": post.slug or _slugify(post.title),
            "articletext": post.body_html,
            "catid": self._catid,
            "state": 1,
            "access": 1,
            "language": "*",
        }
        payload: dict[str, object] = {"data": {"type": "articles", "attributes": attrs}}
        path = "/api/index.php/v1/content/articles"
        if post.external_id:
            data = self.request_json("PATCH", f"{path}/{post.external_id}", json_body=payload)
        else:
            data = self.request_json("POST", path, json_body=payload)
        row = data.get("data") or {}
        row_attrs = row.get("attributes") or {}
        article_id = row.get("id") or row_attrs.get("id")
        if not article_id:
            raise ProviderCallError("Joomla response missing article id")
        post_url = f"{self._base}/index.php?option=com_content&view=article&id={article_id}"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(article_id))


# --------------------------------------------------------------------------- #
# HackMD - Bearer PAT, JSON REST. Notes have no separate title field on write,
# so the title is folded into the note's markdown as an H1.
# --------------------------------------------------------------------------- #
class HackMDClient(HttpProviderClient):
    """Real ``Web2Publisher`` over api.hackmd.io (a self-issued Bearer PAT,
    Settings > API). ``readPermission: 'guest'`` makes the note publicly
    viewable at its returned ``publishLink``."""

    provider = "hackmd"
    platform = PLATFORM_HACKMD

    def __init__(self, *, token: str, timeout: float = 30.0) -> None:
        if not token:
            raise ProviderNotConfiguredError(f"HackMD publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://api.hackmd.io/v1",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=timeout,
        )

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        content = f"# {post.title}\n\n{_html_to_text(post.body_html)}\n\n[{post.anchor}]({post.target_url})"
        body: dict[str, object] = {"content": content, "readPermission": "guest", "writePermission": "owner"}
        if post.external_id:
            self.request_json("PATCH", f"/notes/{post.external_id}", json_body=body)
            data = self.request_json("GET", f"/notes/{post.external_id}")
            note_id: object = post.external_id
        else:
            data = self.request_json("POST", "/notes", json_body=body)
            note_id = data.get("id")
        post_url = str(data.get("publishLink") or "")
        if not post_url:
            raise ProviderCallError("HackMD response missing publishLink")
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(note_id) if note_id else None)


# --------------------------------------------------------------------------- #
# GitHub Gist - a PAT Bearer, JSON REST.
# --------------------------------------------------------------------------- #
class GitHubGistClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the GitHub Gist API. A PAT (classic or
    fine-grained, ``gist`` scope) rides as a Bearer token; GitHub renders gist
    content as Markdown, so ``body_html`` is stripped to plain text first (the
    same markdown caveat ``DevToClient`` documents)."""

    provider = "github_gist"
    platform = PLATFORM_GITHUB_GIST

    def __init__(self, *, token: str, timeout: float = 30.0) -> None:
        if not token:
            raise ProviderNotConfiguredError(f"GitHub Gist publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        slug = post.slug or _slugify(post.title)
        content = f"# {post.title}\n\n{_html_to_text(post.body_html)}\n\n[{post.anchor}]({post.target_url})"
        body: dict[str, object] = {
            "description": post.title, "public": True, "files": {f"{slug}.md": {"content": content}},
        }
        if post.external_id:
            data = self.request_json("PATCH", f"/gists/{post.external_id}", json_body=body)
        else:
            data = self.request_json("POST", "/gists", json_body=body)
        post_url = str(data.get("html_url") or "")
        gist_id = data.get("id")
        if not post_url:
            raise ProviderCallError("GitHub Gist response missing html_url")
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(gist_id) if gist_id else None)


# --------------------------------------------------------------------------- #
# GitLab Snippets - a PAT via the PRIVATE-TOKEN header (GitLab's own scheme).
# --------------------------------------------------------------------------- #
class GitLabSnippetsClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the GitLab Snippets API (gitlab.com).
    ``visibility: 'public'`` makes the snippet indexable at its returned
    ``web_url``."""

    provider = "gitlab_snippets"
    platform = PLATFORM_GITLAB_SNIPPETS

    def __init__(self, *, token: str, timeout: float = 30.0) -> None:
        if not token:
            raise ProviderNotConfiguredError(f"GitLab Snippets publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://gitlab.com/api/v4",
            headers={"PRIVATE-TOKEN": token, "Content-Type": "application/json"},
            timeout=timeout,
        )

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        slug = post.slug or _slugify(post.title)
        content = f"# {post.title}\n\n{_html_to_text(post.body_html)}\n\n[{post.anchor}]({post.target_url})"
        body: dict[str, object] = {
            "title": post.title, "file_name": f"{slug}.md", "content": content, "visibility": "public",
        }
        if post.external_id:
            data = self.request_json("PUT", f"/snippets/{post.external_id}", json_body=body)
        else:
            data = self.request_json("POST", "/snippets", json_body=body)
        post_url = str(data.get("web_url") or "")
        snippet_id = data.get("id")
        if not post_url:
            raise ProviderCallError("GitLab Snippets response missing web_url")
        return Web2PublishResult(
            post_url=post_url, verified=True, external_id=str(snippet_id) if snippet_id else None
        )


# --------------------------------------------------------------------------- #
# paste.ee - X-Auth-Token header, JSON REST. No documented edit endpoint.
# --------------------------------------------------------------------------- #
class PasteEeClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the paste.ee API (a self-issued
    ``X-Auth-Token``). paste.ee has no documented edit endpoint, so an
    ``external_id`` is ignored - every ``publish()`` call creates a NEW paste,
    never silently claims to have updated an old one."""

    provider = "paste_ee"
    platform = PLATFORM_PASTE_EE

    def __init__(self, *, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"paste.ee publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://api.paste.ee/v1",
            headers={"X-Auth-Token": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        content = f"{post.title}\n\n{_html_to_text(post.body_html)}\n\n{post.anchor}: {post.target_url}"
        body = {"description": post.title, "sections": [{"name": post.title, "contents": content}]}
        data = self.request_json("POST", "/pastes", json_body=body)
        post_url = str(data.get("link") or "")
        paste_id = data.get("id")
        if not post_url:
            raise ProviderCallError("paste.ee response missing link")
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(paste_id) if paste_id else None)


# --------------------------------------------------------------------------- #
# Pastebin.com - the classic api_post.php: form-encoded, and the response is a
# bare TEXT url (not JSON), so this bypasses request_json for its one call.
# --------------------------------------------------------------------------- #
class PastebinClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the classic Pastebin API. No edit endpoint is
    reachable with just the ``api_dev_key`` (editing needs the paste OWNER's
    separately-logged-in ``api_user_key``, a handshake this client does not
    perform), so ``external_id`` is ignored - every call creates a NEW paste."""

    provider = "pastebin"
    platform = PLATFORM_PASTEBIN
    _ENDPOINT = "https://pastebin.com/api/api_post.php"

    def __init__(self, *, api_dev_key: str, timeout: float = 30.0) -> None:
        if not api_dev_key:
            raise ProviderNotConfiguredError(f"Pastebin.com publisher unavailable: {_INSTALL_HINT}")
        super().__init__(timeout=timeout)
        self._api_dev_key = api_dev_key

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        content = f"{post.title}\n\n{_html_to_text(post.body_html)}\n\n{post.anchor}: {post.target_url}"
        params = {
            "api_dev_key": self._api_dev_key,
            "api_option": "paste",
            "api_paste_code": content,
            "api_paste_name": post.title,
            "api_paste_private": "0",
            "api_paste_expire_date": "N",
        }
        response = self._client.post(self._ENDPOINT, data=params)
        if response.status_code >= 400:
            raise ProviderCallError(f"Pastebin request failed with status {response.status_code}")
        text = response.text.strip()
        if not text.startswith("http"):
            raise ProviderCallError(f"Pastebin error: {text}")
        return Web2PublishResult(post_url=text, verified=True, external_id=None)


# --------------------------------------------------------------------------- #
# Netlify - a PAT + the 'digest' deploy flow (sha1 the file, upload only if the
# digest is not already stored) to push a single static HTML page live.
# --------------------------------------------------------------------------- #
class NetlifyClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the Netlify API. One deploy = one static
    ``index.html`` (mirrors ``_static_page``) REPLACING the whole site's prior
    deploy - this client is meant for one branded property per Netlify site,
    not a multi-page site. ``site_id`` must already exist (created once by
    hand or via the Sites API, out of scope here)."""

    provider = "netlify"
    platform = PLATFORM_NETLIFY

    def __init__(self, *, api_token: str, site_id: str, timeout: float = 30.0) -> None:
        if not api_token or not site_id:
            raise ProviderNotConfiguredError(f"Netlify publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://api.netlify.com/api/v1",
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=timeout,
        )
        self._site_id = site_id

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        content = _static_page(post).encode("utf-8")
        # Content-addressing only (Netlify's own deploy-digest protocol) - not a
        # security use, hence usedforsecurity=False.
        digest = hashlib.sha1(content, usedforsecurity=False).hexdigest()
        data = self.request_json(
            "POST", f"/sites/{self._site_id}/deploys", json_body={"files": {"/index.html": digest}},
        )
        deploy_id = data.get("id")
        required = data.get("required") or []
        if not deploy_id:
            raise ProviderCallError("Netlify response missing deploy id")
        if digest in required:
            response = self._client.put(
                f"/deploys/{deploy_id}/files/index.html",
                content=content,
                headers={"Content-Type": "application/octet-stream"},
            )
            if response.status_code >= 400:
                raise ProviderCallError(f"Netlify file upload failed with status {response.status_code}")
        post_url = str(data.get("ssl_url") or data.get("deploy_ssl_url") or "")
        if not post_url:
            raise ProviderCallError("Netlify response missing ssl_url")
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(deploy_id))


# --------------------------------------------------------------------------- #
# Neocities - a site API key (Bearer) + a multipart upload of one static file.
# --------------------------------------------------------------------------- #
class NeocitiesClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the Neocities API. ``sitename`` is the
    account's own ``{sitename}.neocities.org`` subdomain, needed to build the
    live URL - the upload response carries none."""

    provider = "neocities"
    platform = PLATFORM_NEOCITIES

    def __init__(self, *, api_key: str, sitename: str, timeout: float = 30.0) -> None:
        if not api_key or not sitename:
            raise ProviderNotConfiguredError(f"Neocities publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://neocities.org/api", headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout,
        )
        self._sitename = sitename

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        slug = post.slug or _slugify(post.title)
        filename = f"{slug}.html"
        content = _static_page(post).encode("utf-8")
        response = self._client.post("/upload", files={filename: (filename, content, "text/html")})
        if response.status_code >= 400:
            raise ProviderCallError(f"Neocities upload failed with status {response.status_code}")
        data = response.json()
        if data.get("result") != "success":
            raise ProviderCallError(f"Neocities error: {data.get('message')}")
        post_url = f"https://{self._sitename}.neocities.org/{filename}"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=filename)


# --------------------------------------------------------------------------- #
# rentry.co - fully anonymous (no credential at all); a CSRF cookie handshake.
# --------------------------------------------------------------------------- #
class RentryClient:
    """Real ``Web2Publisher`` over rentry.co's unofficial (but actively
    community-maintained) anonymous posting endpoint - no account, no
    credential at all (``PLATFORM_CREDENTIAL_FIELDS`` is empty for this
    platform). Not an ``HttpProviderClient`` subclass: the flow needs a cookie
    jar (the CSRF token rides in a ``csrftoken`` cookie set by an initial GET),
    which a plain ``httpx.Client`` keeps automatically. An update
    (``external_id`` set, ``"<url>:<edit_code>"``) reuses that SAME edit_code -
    rentry has no account/OAuth, so the edit_code IS the write credential for
    that one page, and the (possibly rotated) edit_code is stored back as the
    new ``external_id``."""

    provider = "rentry"
    platform = PLATFORM_RENTRY
    _BASE = "https://rentry.co"

    def __init__(self, *, timeout: float = 30.0) -> None:
        import httpx

        self._client = httpx.Client(base_url=self._BASE, timeout=timeout, follow_redirects=True)

    def _csrf_token(self) -> str:
        self._client.get("/")
        token = self._client.cookies.get("csrftoken")
        if not token:
            raise ProviderCallError("rentry.co did not set a csrftoken cookie")
        return str(token)

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        text = f"# {post.title}\n\n{_html_to_text(post.body_html)}\n\n[{post.anchor}]({post.target_url})"
        edit_code = None
        if post.external_id and ":" in post.external_id:
            _, _, edit_code = post.external_id.partition(":")
        edit_code = edit_code or secrets.token_hex(8)
        csrf = self._csrf_token()
        response = self._client.post(
            "/api/new",
            data={"csrfmiddlewaretoken": csrf, "text": text, "edit_code": edit_code},
            headers={"Referer": f"{self._BASE}/"},
        )
        if response.status_code >= 400:
            raise ProviderCallError(f"rentry.co request failed with status {response.status_code}")
        data = response.json()
        if data.get("status") != "200":
            raise ProviderCallError(f"rentry.co error: {data.get('errors')}")
        content = data.get("content") or {}
        url = str(content.get("url") or "")
        returned_edit_code = str(content.get("edit_code") or edit_code)
        if not url:
            raise ProviderCallError("rentry.co response missing url")
        full_url = url if url.startswith("http") else f"{self._BASE}/{url}"
        return Web2PublishResult(post_url=full_url, verified=True, external_id=f"{url}:{returned_edit_code}")


# --------------------------------------------------------------------------- #
# dpaste.org - fully anonymous, no key or cookie handshake at all.
# --------------------------------------------------------------------------- #
class DpasteClient:
    """Real ``Web2Publisher`` over dpaste.org's anonymous API - literally no
    key, no cookie, no account (``PLATFORM_CREDENTIAL_FIELDS`` is empty, same as
    ``RentryClient``). No edit endpoint exists, so ``external_id`` is always
    ignored and every ``publish()`` call creates a brand NEW paste."""

    provider = "dpaste"
    platform = PLATFORM_DPASTE
    _BASE = "https://dpaste.org"

    def __init__(self, *, timeout: float = 30.0) -> None:
        import httpx

        self._client = httpx.Client(base_url=self._BASE, timeout=timeout, follow_redirects=True)

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        content = f"{post.title}\n\n{_html_to_text(post.body_html)}\n\n{post.anchor}: {post.target_url}"
        response = self._client.post("/api/", data={"content": content, "format": "url", "expiry_days": "365"})
        if response.status_code >= 400:
            raise ProviderCallError(f"dpaste.org request failed with status {response.status_code}")
        url = response.text.strip()
        if not url.startswith("http"):
            raise ProviderCallError(f"dpaste.org error: {url}")
        return Web2PublishResult(post_url=url, verified=True, external_id=None)


# --------------------------------------------------------------------------- #
# Misskey - distinct fediverse software from Mastodon; the token rides IN THE
# JSON BODY (`i`), never an Authorization header - a documented Misskey quirk.
# --------------------------------------------------------------------------- #
class MisskeyClient(HttpProviderClient):
    """Real ``Web2Publisher`` over a Misskey instance's REST API (misskey.io by
    default; ``instance_url`` is overridable for any Misskey instance). Misskey
    has no note-edit endpoint, so ``external_id`` is ignored - every
    ``publish()`` call creates a NEW note, never claims to update the old one."""

    provider = "misskey"
    platform = PLATFORM_MISSKEY
    _MAX_CHARS = 3000

    def __init__(self, *, token: str, instance_url: str = "https://misskey.io", timeout: float = 30.0) -> None:
        if not token:
            raise ProviderNotConfiguredError(f"Misskey publisher unavailable: {_INSTALL_HINT}")
        self._instance = instance_url.rstrip("/")
        super().__init__(
            base_url=self._instance, headers={"Content-Type": "application/json"}, timeout=timeout,
        )
        self._token = token

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        text = f"{post.title}\n\n{_html_to_text(post.body_html)}\n\n{post.anchor}: {post.target_url}"
        body = {"i": self._token, "text": text[: self._MAX_CHARS]}
        data = self.request_json("POST", "/api/notes/create", json_body=body)
        note = data.get("createdNote") or {}
        note_id = note.get("id")
        if not note_id:
            raise ProviderCallError("Misskey response missing createdNote.id")
        post_url = f"{self._instance}/notes/{note_id}"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(note_id))


# --------------------------------------------------------------------------- #
# Lemmy - login for a JWT, resolve the target community name to an id, then
# post a LINK post (url = the backlink) into it.
# --------------------------------------------------------------------------- #
class LemmyClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the Lemmy REST API v3 (lemmy.world by
    default). The backlink rides as the post's own ``url`` field (a Lemmy link
    post), with the article text as ``body``. An ``external_id`` (an existing
    post id) skips community resolution and PUTs an edit directly."""

    provider = "lemmy"
    platform = PLATFORM_LEMMY

    def __init__(
        self, *, username: str, password: str, community: str,
        base_url: str = "https://lemmy.world", timeout: float = 30.0,
    ) -> None:
        if not username or not password or not community:
            raise ProviderNotConfiguredError(f"Lemmy publisher unavailable: {_INSTALL_HINT}")
        self._base = base_url.rstrip("/")
        super().__init__(base_url=self._base, headers={"Content-Type": "application/json"}, timeout=timeout)
        self._username, self._password, self._community = username, password, community
        self._jwt: str | None = None

    def _login(self) -> None:
        if self._jwt is not None:
            return
        data = self.request_json(
            "POST", "/api/v3/user/login",
            json_body={"username_or_email": self._username, "password": self._password},
        )
        jwt = data.get("jwt")
        if not jwt:
            raise ProviderCallError("Lemmy login response missing jwt")
        self._jwt = str(jwt)
        self._client.headers["Authorization"] = f"Bearer {self._jwt}"

    def _community_id(self) -> int:
        data = self.request_json("GET", "/api/v3/community", params={"name": self._community})
        community = (data.get("community_view") or {}).get("community") or {}
        cid = community.get("id")
        if cid is None:
            raise ProviderCallError(f"Lemmy: community '{self._community}' not found")
        return int(cid)

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        self._login()
        body_text = _html_to_text(post.body_html)
        if post.external_id:
            data = self.request_json(
                "PUT", "/api/v3/post",
                json_body={
                    "post_id": int(post.external_id), "name": post.title,
                    "url": post.target_url, "body": body_text,
                },
            )
        else:
            community_id = self._community_id()
            data = self.request_json(
                "POST", "/api/v3/post",
                json_body={
                    "name": post.title, "url": post.target_url, "body": body_text, "community_id": community_id,
                },
            )
        row = (data.get("post_view") or {}).get("post") or {}
        post_id = row.get("id")
        if not post_id:
            raise ProviderCallError("Lemmy response missing post id")
        post_url = str(row.get("ap_id") or f"{self._base}/post/{post_id}")
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(post_id))


# --------------------------------------------------------------------------- #
# AT Protocol (Bluesky) - shared session handling for BlueskyClient and
# WhiteWindClient, which rides on the SAME account (an App Password), just a
# different XRPC record collection.
# --------------------------------------------------------------------------- #
class _ATProtoClient(HttpProviderClient):
    """Shared AT Protocol session base. ``identifier`` is a handle or email;
    ``app_password`` is a Bluesky App Password (Settings > App Passwords) -
    NEVER the main account password. Logs in once (cached) and rides the
    session's ``accessJwt`` as a bearer header on every subsequent call."""

    platform: str = ""

    def __init__(self, *, identifier: str, app_password: str, timeout: float = 30.0) -> None:
        if not identifier or not app_password:
            raise ProviderNotConfiguredError(f"{self.platform} publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://bsky.social/xrpc", headers={"Content-Type": "application/json"}, timeout=timeout,
        )
        self._identifier = identifier
        self._app_password = app_password
        self._did: str | None = None

    def _session(self) -> str:
        if self._did is not None:
            return self._did
        data = self.request_json(
            "POST", "/com.atproto.server.createSession",
            json_body={"identifier": self._identifier, "password": self._app_password},
        )
        access_jwt, did = data.get("accessJwt"), data.get("did")
        if not access_jwt or not did:
            raise ProviderCallError(f"{self.platform} login response missing accessJwt/did")
        self._client.headers["Authorization"] = f"Bearer {access_jwt}"
        self._did = str(did)
        return self._did


def _link_facet(text: str, url: str) -> dict[str, Any] | None:
    """An AT Protocol rich-text ``facet`` making ``url`` (if present in
    ``text``) a real clickable link - byte (not character) offsets, per the
    AT Protocol spec."""
    idx = text.find(url)
    if idx < 0:
        return None
    prefix_bytes = len(text[:idx].encode("utf-8"))
    url_bytes = len(url.encode("utf-8"))
    return {
        "index": {"byteStart": prefix_bytes, "byteEnd": prefix_bytes + url_bytes},
        "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
    }


class BlueskyClient(_ATProtoClient):
    """Real ``Web2Publisher`` over the AT Protocol (Bluesky). Folds title + a
    plain-text body + the backlink into one post, capped near Bluesky's
    ~300-grapheme limit (approximated in characters - good enough for the
    ASCII-heavy article text this pipeline produces). An ``external_id`` (the
    record key, ``rkey``) uses ``putRecord`` to overwrite that SAME post in
    place instead of creating a new one - AT Protocol supports this directly,
    unlike most platforms here that have no edit endpoint at all."""

    provider = "bluesky"
    platform = PLATFORM_BLUESKY
    _MAX_CHARS = 300

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        did = self._session()
        text = f"{post.title}\n\n{_html_to_text(post.body_html)}\n\n{post.anchor}: {post.target_url}"
        text = text[: self._MAX_CHARS]
        record: dict[str, object] = {
            "$type": "app.bsky.feed.post", "text": text, "createdAt": datetime.now(UTC).isoformat(),
        }
        facet = _link_facet(text, post.target_url)
        if facet:
            record["facets"] = [facet]
        body: dict[str, object] = {"repo": did, "collection": "app.bsky.feed.post", "record": record}
        if post.external_id:
            body["rkey"] = post.external_id
            data = self.request_json("POST", "/com.atproto.repo.putRecord", json_body=body)
        else:
            data = self.request_json("POST", "/com.atproto.repo.createRecord", json_body=body)
        uri = str(data.get("uri") or "")
        if not uri:
            raise ProviderCallError("Bluesky response missing record uri")
        rkey = uri.rsplit("/", 1)[-1]
        post_url = f"https://bsky.app/profile/{did}/post/{rkey}"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=rkey)


class WhiteWindClient(_ATProtoClient):
    """Real ``Web2Publisher`` over WhiteWind (whtwnd.com), an ATProto long-form
    blog service. Reuses the SAME Bluesky/ATProto account (App Password) as
    ``BlueskyClient`` - not a separate signup, just a different XRPC record
    collection (``com.whtwnd.blog.entry``) written to the same PDS and rendered
    as a public HTML article at whtwnd.com. Unlike ``BlueskyClient`` this
    carries the FULL article text - no grapheme cap - the genuine long-form
    counterpart."""

    provider = "whitewind"
    platform = PLATFORM_WHITEWIND

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        did = self._session()
        content = _html_to_text(post.body_html) + f"\n\n[{post.anchor}]({post.target_url})"
        record: dict[str, object] = {
            "$type": "com.whtwnd.blog.entry", "title": post.title, "content": content,
            "createdAt": datetime.now(UTC).isoformat(),
        }
        body: dict[str, object] = {"repo": did, "collection": "com.whtwnd.blog.entry", "record": record}
        if post.external_id:
            body["rkey"] = post.external_id
            data = self.request_json("POST", "/com.atproto.repo.putRecord", json_body=body)
        else:
            data = self.request_json("POST", "/com.atproto.repo.createRecord", json_body=body)
        uri = str(data.get("uri") or "")
        if not uri:
            raise ProviderCallError("WhiteWind response missing record uri")
        rkey = uri.rsplit("/", 1)[-1]
        post_url = f"https://whtwnd.com/{self._identifier}/{rkey}"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=rkey)


# --------------------------------------------------------------------------- #
# Disqus - OAuth2, a THIN PROFILE placement (not an article): there is no
# "post an article" endpoint, only a public profile the backlink lives on.
# --------------------------------------------------------------------------- #
class DisqusClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the Disqus REST API v3. Every ``publish()``
    call OVERWRITES the SAME public profile's ``url``/``about`` fields (there is
    only ever one profile), so ``external_id`` is meaningless here and ignored -
    same honesty as Medium's draft-only note, just for a different reason
    (a profile, not a missing publish API)."""

    provider = "disqus"
    platform = PLATFORM_DISQUS

    def __init__(self, *, access_token: str, api_key: str, username: str, timeout: float = 30.0) -> None:
        if not access_token or not api_key or not username:
            raise ProviderNotConfiguredError(f"Disqus publisher unavailable: {_INSTALL_HINT}")
        super().__init__(base_url="https://disqus.com/api/3.0", timeout=timeout)
        self._access_token, self._api_key, self._username = access_token, api_key, username

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        about = f"{post.title} - {post.anchor}"[:255]
        params = {
            "access_token": self._access_token, "api_key": self._api_key,
            "url": post.target_url, "about": about,
        }
        data = self.request_json("POST", "/users/updateProfile.json", params=params)
        if data.get("code") != 0:
            raise ProviderCallError(f"Disqus error: {data.get('response')}")
        post_url = f"https://disqus.com/by/{self._username}/"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=self._username)


# --------------------------------------------------------------------------- #
# Plurk - the one OAuth1 (not OAuth2) platform here; every call is individually
# HMAC-SHA1 signed (hand-rolled - not worth a whole OAuth1 dependency for one
# caller).
# --------------------------------------------------------------------------- #
def _oauth1_authorization_header(
    *, method: str, url: str, consumer_key: str, consumer_secret: str,
    token: str, token_secret: str, extra_params: dict[str, str],
) -> str:
    """A minimal RFC 5849 OAuth1 HMAC-SHA1 ``Authorization`` header."""
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    all_params = {**oauth_params, **extra_params}
    normalized = "&".join(
        f"{quote(k, safe='')}={quote(str(v), safe='')}" for k, v in sorted(all_params.items())
    )
    base_string = "&".join([method.upper(), quote(url, safe=""), quote(normalized, safe="")])
    signing_key = f"{quote(consumer_secret, safe='')}&{quote(token_secret, safe='')}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()
    oauth_params["oauth_signature"] = signature
    header_params = ", ".join(f'{quote(k, safe="")}="{quote(v, safe="")}"' for k, v in sorted(oauth_params.items()))
    return f"OAuth {header_params}"


_BASE36_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def _to_base36(value: int) -> str:
    """Plurk short-URL ids are base36-encoded (``plurk.com/p/<base36 id>``)."""
    if value == 0:
        return "0"
    digits: list[str] = []
    n = abs(value)
    while n:
        n, remainder = divmod(n, 36)
        digits.append(_BASE36_DIGITS[remainder])
    return "".join(reversed(digits))


class PlurkClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the Plurk API (OAuth1 - see
    ``_oauth1_authorization_header``). Posts to the account's public timeline;
    Plurk has no documented edit-by-API for an existing plurk, so
    ``external_id`` is ignored and every call creates a NEW plurk."""

    provider = "plurk"
    platform = PLATFORM_PLURK
    _ENDPOINT = "https://www.plurk.com/APP/Timeline/plurkAdd"

    def __init__(
        self, *, consumer_key: str, consumer_secret: str,
        access_token: str, access_token_secret: str, timeout: float = 30.0,
    ) -> None:
        if not consumer_key or not consumer_secret or not access_token or not access_token_secret:
            raise ProviderNotConfiguredError(f"Plurk publisher unavailable: {_INSTALL_HINT}")
        super().__init__(timeout=timeout)
        self._consumer_key, self._consumer_secret = consumer_key, consumer_secret
        self._access_token, self._access_token_secret = access_token, access_token_secret

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        content = f"{post.title} - {_html_to_text(post.body_html)[:200]} {post.anchor}: {post.target_url}"
        params = {"content": content[:360], "qualifier": "shares", "lang": "en"}
        self._client.headers["Authorization"] = _oauth1_authorization_header(
            method="POST", url=self._ENDPOINT,
            consumer_key=self._consumer_key, consumer_secret=self._consumer_secret,
            token=self._access_token, token_secret=self._access_token_secret,
            extra_params=params,
        )
        data = self.request_json("POST", self._ENDPOINT, params=params)
        plurk_id = data.get("plurk_id")
        if plurk_id is None:
            raise ProviderCallError("Plurk response missing plurk_id")
        post_url = f"https://www.plurk.com/p/{_to_base36(int(plurk_id))}"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(plurk_id))


# --------------------------------------------------------------------------- #
# Pixelfed - Mastodon-compatible REST, but REQUIRES an image on every post
# (unlike Mastodon) - a fixed brand placeholder image is uploaded each time.
# --------------------------------------------------------------------------- #
class PixelfedClient(HttpProviderClient):
    """Real ``Web2Publisher`` over Pixelfed's Mastodon-compatible REST API
    (pixelfed.social by default). ``Web2Post`` carries no image field, so this
    client takes a fixed ``placeholder_image_url`` (a brand image), fetches it
    once per publish, and uploads it as the post's required media - the
    documented fix for the structural mismatch between a text-only
    ``Web2Post`` and Pixelfed's image-required timeline."""

    provider = "pixelfed"
    platform = PLATFORM_PIXELFED
    _MAX_CHARS = 500

    def __init__(
        self, *, access_token: str, placeholder_image_url: str,
        instance_url: str = "https://pixelfed.social", timeout: float = 30.0,
    ) -> None:
        if not access_token or not placeholder_image_url:
            raise ProviderNotConfiguredError(
                "Pixelfed publisher unavailable: pass a per-account access token + a brand "
                "placeholder_image_url (Pixelfed requires an image on every post)"
            )
        super().__init__(
            base_url=instance_url.rstrip("/"),
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        )
        self._placeholder_image_url = placeholder_image_url

    def _upload_placeholder_media(self) -> str:
        image = self._client.get(self._placeholder_image_url)
        if image.status_code >= 400:
            raise ProviderCallError(f"Pixelfed placeholder image fetch failed with status {image.status_code}")
        response = self._client.post("/api/v2/media", files={"file": ("brand.jpg", image.content, "image/jpeg")})
        if response.status_code >= 400:
            raise ProviderCallError(f"Pixelfed media upload failed with status {response.status_code}")
        media_id = response.json().get("id")
        if not media_id:
            raise ProviderCallError("Pixelfed media upload response missing id")
        return str(media_id)

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        media_id = self._upload_placeholder_media()
        text = f"{post.title}\n\n{_html_to_text(post.body_html)}\n\n{post.anchor}: {post.target_url}"
        body = {"status": text[: self._MAX_CHARS], "media_ids": [media_id]}
        data = self.request_json("POST", "/api/v1/statuses", json_body=body)
        post_url = str(data.get("url") or "")
        status_id = data.get("id")
        if not post_url:
            raise ProviderCallError("Pixelfed response missing status url")
        return Web2PublishResult(
            post_url=post_url, verified=True, external_id=str(status_id) if status_id else None
        )


# --------------------------------------------------------------------------- #
# Notion - creates a genuine page, but the API has NO endpoint to flip "Share
# to web" (verified against 2026 docs) - a human must do that, so this ALWAYS
# returns verified=False, the same honesty as GitLabPagesClient's CI-pending
# publish.
# --------------------------------------------------------------------------- #
class NotionClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the Notion API (api.notion.com). Creates a
    page nested under a pre-existing ``parent_page_id`` the integration has
    access to (Notion's API cannot create a page at the workspace root), with
    the article rendered as paragraph blocks. A human must still open the page
    and toggle "Share to web" before it is a live, indexable placement -
    ``verified`` is always ``False`` here, never claimed live."""

    provider = "notion"
    platform = PLATFORM_NOTION
    _NOTION_VERSION = "2022-06-28"

    def __init__(self, *, integration_token: str, parent_page_id: str, timeout: float = 30.0) -> None:
        if not integration_token or not parent_page_id:
            raise ProviderNotConfiguredError(f"Notion publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://api.notion.com/v1",
            headers={
                "Authorization": f"Bearer {integration_token}",
                "Notion-Version": self._NOTION_VERSION,
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        self._parent_page_id = parent_page_id

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        text = _html_to_text(post.body_html) + f"\n\n{post.anchor}: {post.target_url}"
        blocks: list[dict[str, object]] = [
            {
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk[:2000]}}]},
            }
            for chunk in text.split("\n\n") if chunk.strip()
        ]
        if post.external_id:
            self.request_json(
                "PATCH", f"/blocks/{post.external_id}/children", json_body={"children": blocks}
            )
            page_id: object = post.external_id
            data = self.request_json("GET", f"/pages/{post.external_id}")
        else:
            body: dict[str, object] = {
                "parent": {"page_id": self._parent_page_id},
                "properties": {"title": {"title": [{"text": {"content": post.title}}]}},
                "children": blocks,
            }
            data = self.request_json("POST", "/pages", json_body=body)
            page_id = data.get("id")
        if not page_id:
            raise ProviderCallError("Notion response missing page id")
        post_url = str(data.get("url") or f"https://notion.so/{str(page_id).replace('-', '')}")
        return Web2PublishResult(post_url=post_url, verified=False, external_id=str(page_id))


# --------------------------------------------------------------------------- #
# Gravatar - OAuth2 Bearer, a THIN PROFILE placement (not an article): same
# honesty as DisqusClient, for the same reason (only one profile, ever).
# --------------------------------------------------------------------------- #
class GravatarClient(HttpProviderClient):
    """Real ``Web2Publisher`` over Gravatar's REST API (api.gravatar.com/v3).
    Updates the profile's ``description`` + a public ``links`` entry carrying
    the backlink; ``external_id``/update is meaningless (one profile, ever) and
    every ``publish()`` call re-asserts the same fields. ``username`` builds
    the public profile URL directly rather than trusting it back in the
    response."""

    provider = "gravatar"
    platform = PLATFORM_GRAVATAR

    def __init__(self, *, api_token: str, username: str, timeout: float = 30.0) -> None:
        if not api_token or not username:
            raise ProviderNotConfiguredError(f"Gravatar publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://api.gravatar.com/v3",
            headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        self._username = username

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        body = {
            "description": f"{post.title}: {post.anchor}"[:200],
            "links": [{"label": post.anchor[:50], "url": post.target_url}],
        }
        self.request_json("PATCH", "/me", json_body=body)
        post_url = f"https://gravatar.com/{self._username}"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=self._username)


# --------------------------------------------------------------------------- #
# Minds - a personal-access-token Bearer POST to the account's public channel.
# --------------------------------------------------------------------------- #
class MindsClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the Minds API (a self-serve personal access
    token, Settings > API); posts a text activity to the account's public
    channel/newsfeed timeline."""

    provider = "minds"
    platform = PLATFORM_MINDS

    def __init__(self, *, access_token: str, timeout: float = 30.0) -> None:
        if not access_token:
            raise ProviderNotConfiguredError(f"Minds publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://www.minds.com/api/v3",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=timeout,
        )

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        text = f"{post.title}\n\n{_html_to_text(post.body_html)}\n\n{post.anchor}: {post.target_url}"
        data = self.request_json("POST", "/newsfeed/activity", json_body={"message": text})
        entity = data.get("entity") or {}
        guid = entity.get("guid") or data.get("guid")
        if not guid:
            raise ProviderCallError("Minds response missing activity guid")
        post_url = f"https://www.minds.com/newsfeed/{guid}"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(guid))


# =============================================================================
# FOURTH PASS (10 more, Aug 2026) - see the module docstring above for the full
# rationale + what was deliberately skipped this round.
# =============================================================================

# --------------------------------------------------------------------------- #
# Zenodo - deposit REST API, Bearer token. Publish is ONE-WAY - a published
# deposit cannot be edited/re-published through this simple flow (only a full
# new-version workflow supersedes it), so a SECOND publish() call against an
# already-published external_id re-fetches and returns the SAME record.
# --------------------------------------------------------------------------- #
class ZenodoClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the Zenodo REST API (zenodo.org/api). Creates
    a deposition with metadata, then calls the separate ``actions/publish`` step
    to make it live - Zenodo's own two-step design (a draft deposit is private
    until explicitly published). Because a published deposit's metadata cannot
    be edited through this simple flow (a genuine update needs Zenodo's full
    new-version workflow), a SECOND ``publish()`` call against an already-set
    ``external_id`` is treated as already-done: this re-fetches and returns the
    EXISTING record rather than attempting an unsupported "update" or erroring."""

    provider = "zenodo"
    platform = PLATFORM_ZENODO
    _DEFAULT_CREATOR = "Editorial Team"

    def __init__(self, *, access_token: str, creator_name: str = "", timeout: float = 30.0) -> None:
        if not access_token:
            raise ProviderNotConfiguredError(f"Zenodo publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://zenodo.org/api",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        self._creator_name = creator_name or self._DEFAULT_CREATOR

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        if post.external_id:
            # Already published once - re-fetch the SAME record rather than
            # guessing at an unsupported second publish.
            data = self.request_json("GET", f"/deposit/depositions/{post.external_id}")
            return self._result_from(data)
        description = post.body_html + f'<p><a href="{post.target_url}">{post.anchor}</a></p>'
        metadata: dict[str, object] = {
            "title": post.title,
            "description": description,
            "upload_type": "publication",
            "publication_type": "other",
            "creators": [{"name": self._creator_name}],
        }
        created = self.request_json("POST", "/deposit/depositions", json_body={"metadata": metadata})
        deposit_id = created.get("id")
        if not deposit_id:
            raise ProviderCallError("Zenodo response missing deposition id")
        published = self.request_json("POST", f"/deposit/depositions/{deposit_id}/actions/publish")
        return self._result_from(published)

    def _result_from(self, data: dict[str, Any]) -> Web2PublishResult:
        links = data.get("links") or {}
        post_url = str(links.get("record_html") or links.get("html") or "")
        deposit_id = data.get("id")
        if not post_url or not deposit_id:
            raise ProviderCallError("Zenodo response missing a record url/id")
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(deposit_id))


# --------------------------------------------------------------------------- #
# Internet Archive - S3-like upload API (a distinct protocol from AWS S3: the
# item ("bucket") is auto-created on first PUT via a dedicated header, and auth
# is IA's own non-standard "LOW key:secret" scheme, not AWS SigV4).
# --------------------------------------------------------------------------- #
class InternetArchiveClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the Internet Archive's S3-like upload API
    (s3.us.archive.org). One publish = one new "item" (``bucket``) holding a
    single static HTML file - ``x-archive-auto-make-bucket: 1`` creates the item
    on first upload, so no separate provisioning step is needed. IA item
    identifiers are GLOBAL (not per-account), so the optional ``item_prefix``
    constructor kwarg lets a client namespace its slugs and avoid colliding with
    an unrelated existing item of the same bare slug.

    A documented ``503 SlowDown`` (IA's own back-pressure response) needs no
    extra ``transient_statuses`` opt-in - it already falls inside
    ``HttpProviderClient``'s universal ``500 <= status < 600`` transient range,
    so it retries with backoff for free; nothing further to wire here."""

    provider = "internet_archive"
    platform = PLATFORM_INTERNET_ARCHIVE

    def __init__(
        self, *, access_key: str, secret_key: str, item_prefix: str = "", timeout: float = 30.0,
    ) -> None:
        if not access_key or not secret_key:
            raise ProviderNotConfiguredError(f"Internet Archive publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://s3.us.archive.org",
            headers={"Authorization": f"LOW {access_key}:{secret_key}"},
            timeout=timeout,
        )
        self._item_prefix = item_prefix.strip("-")

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        slug = post.slug or _slugify(post.title)
        bucket = f"{self._item_prefix}-{slug}" if self._item_prefix else slug
        filename = f"{slug}.html"
        content = _static_page(post).encode("utf-8")
        response = self._client.put(
            f"/{bucket}/{filename}",
            content=content,
            headers={"Content-Type": "text/html", "x-archive-auto-make-bucket": "1"},
        )
        if response.status_code >= 400:
            raise ProviderCallError(f"Internet Archive upload failed with status {response.status_code}")
        post_url = f"https://archive.org/details/{bucket}"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=bucket)


# --------------------------------------------------------------------------- #
# OSF (Open Science Framework) - JSON:API v2, Bearer token. `public: true` MUST
# be set explicitly - a created node defaults to PRIVATE otherwise, which would
# silently produce an unreachable "placement".
# --------------------------------------------------------------------------- #
class OSFClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the OSF (Open Science Framework) v2 API
    (api.osf.io), JSON:API format. Creates a public project node carrying the
    article as its description + the backlink - OSF nodes have no rich body
    field, so the full article renders as plain text (the same trade-off
    ``HackMDClient``/``GitHubGistClient`` document for their markdown-only
    bodies)."""

    provider = "osf"
    platform = PLATFORM_OSF

    def __init__(self, *, access_token: str, timeout: float = 30.0) -> None:
        if not access_token:
            raise ProviderNotConfiguredError(f"OSF publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://api.osf.io/v2",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/vnd.api+json",
                "Accept": "application/vnd.api+json",
            },
            timeout=timeout,
        )

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        description = _html_to_text(post.body_html) + f"\n\n{post.anchor}: {post.target_url}"
        attrs: dict[str, object] = {
            "title": post.title, "category": "project", "public": True, "description": description[:1000],
        }
        payload: dict[str, Any] = {"data": {"type": "nodes", "attributes": attrs}}
        if post.external_id:
            payload["data"]["id"] = post.external_id
            data = self.request_json("PATCH", f"/nodes/{post.external_id}/", json_body=payload)
        else:
            data = self.request_json("POST", "/nodes/", json_body=payload)
        row = data.get("data") or {}
        node_id = row.get("id")
        post_url = str((row.get("links") or {}).get("html") or "")
        if not node_id or not post_url:
            raise ProviderCallError("OSF response missing node id/url")
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(node_id))


# --------------------------------------------------------------------------- #
# Figshare - REST API v2. Auth is `token <ACCESS_TOKEN>` (Figshare's own scheme,
# not Bearer). Two-step publish: create (a draft by default) then an explicit
# publish call - mirrors Zenodo's own two-step design.
# --------------------------------------------------------------------------- #
class FigshareClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the Figshare API v2 (api.figshare.com).
    Creating/publishing an article both return only a bare ``{"location": url}``
    (never the full row), so the article id is parsed off the trailing path
    segment. The public citation URL uses Figshare's stable DOI convention
    (``doi.org/10.6084/m9.figshare.<id>``) rather than guessing the
    title-slugged ``figshare.com/articles/...`` web path, which is not
    reliably derivable from the API response alone. An update
    (``external_id`` set) edits the article then re-publishes it - Figshare's
    own documented workflow for revising an already-published item."""

    provider = "figshare"
    platform = PLATFORM_FIGSHARE

    def __init__(self, *, access_token: str, timeout: float = 30.0) -> None:
        if not access_token:
            raise ProviderNotConfiguredError(f"Figshare publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://api.figshare.com/v2",
            headers={"Authorization": f"token {access_token}", "Content-Type": "application/json"},
            timeout=timeout,
        )

    def _location_id(self, data: dict[str, Any]) -> str:
        location = str(data.get("location") or "")
        if not location:
            raise ProviderCallError("Figshare response missing location")
        return location.rstrip("/").rsplit("/", 1)[-1]

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        description = post.body_html + f'<p><a href="{post.target_url}">{post.anchor}</a></p>'
        body: dict[str, object] = {"title": post.title, "description": description}
        if post.external_id:
            article_id = post.external_id
            self.request_json("PUT", f"/account/articles/{article_id}", json_body=body)
        else:
            created = self.request_json("POST", "/account/articles", json_body=body)
            article_id = self._location_id(created)
        published = self.request_json("POST", f"/account/articles/{article_id}/publish")
        public_id = self._location_id(published)
        post_url = f"https://doi.org/10.6084/m9.figshare.{public_id}"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=article_id)


# --------------------------------------------------------------------------- #
# Codeberg Pages - mirrors GitHubPagesClient almost exactly: Codeberg runs
# Gitea, whose Contents API is API-compatible with GitHub's, but Gitea's own
# auth scheme is `Authorization: token <TOKEN>` (not `Bearer`), and Codeberg
# Pages serves off a dedicated `pages` branch (not `main`/`gh-pages`).
# --------------------------------------------------------------------------- #
class CodebergPagesClient(HttpProviderClient):
    """Real ``Web2Publisher`` over Codeberg (Gitea) - commits the article as a
    static HTML file to the repo's ``pages`` branch via the Contents API
    (best-effort repo creation first, exactly like ``GitHubPagesClient``).
    Public URL is the per-project Codeberg Pages form,
    ``https://{owner}.codeberg.page/{slug}/``. Assumes the repo either already
    exists WITH a ``pages`` branch, or does not exist yet (so ``auto_init``
    creates that branch directly) - the same "assumes prior setup" honesty
    ``GitHubPagesClient`` already documents for its own repo."""

    provider = "codeberg_pages"
    platform = PLATFORM_CODEBERG_PAGES
    _BRANCH = "pages"

    def __init__(self, *, token: str, owner: str, repo: str, timeout: float = 30.0) -> None:
        if not token or not owner or not repo:
            raise ProviderNotConfiguredError(f"Codeberg Pages publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://codeberg.org/api/v1",
            headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        self._owner, self._repo = owner, repo

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        self._ensure_repo()
        slug = post.slug or _slugify(post.title)
        api_path = f"/repos/{self._owner}/{self._repo}/contents/{slug}/index.html"
        content_b64 = base64.b64encode(_static_page(post).encode("utf-8")).decode("ascii")
        body: dict[str, object] = {
            "message": f"web2: publish {slug}", "content": content_b64, "branch": self._BRANCH,
        }
        existing_sha = self._existing_sha(api_path) if post.external_id else None
        if existing_sha:
            body["sha"] = existing_sha
        self.request_json("PUT", api_path, json_body=body)
        post_url = f"https://{self._owner}.codeberg.page/{slug}/"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=slug)

    def _existing_sha(self, api_path: str) -> str | None:
        try:
            data = self.request_json("GET", f"{api_path}?ref={self._BRANCH}")
        except ProviderCallError:
            return None
        sha = data.get("sha")
        return str(sha) if sha else None

    def _ensure_repo(self) -> None:
        # Best-effort idempotent setup, not the publish itself - a 4xx here (repo
        # already exists) is safe to swallow, same as GitHubPagesClient's Pages toggle.
        with contextlib.suppress(ProviderCallError):
            self.request_json(
                "POST", "/user/repos",
                json_body={"name": self._repo, "auto_init": True, "default_branch": self._BRANCH},
            )


# --------------------------------------------------------------------------- #
# Livedoor Blog - AtomPub (RFC 5023), the exact same protocol as
# HatenaBlogClient - reuses its Atom-entry XML builder/parser directly (only
# the endpoint + the Basic-auth credential differ: Livedoor's password slot is
# a separately-issued AtomPub API key, never the account login password).
# --------------------------------------------------------------------------- #
class LivedoorBlogClient(HttpProviderClient):
    """Real ``Web2Publisher`` over Livedoor Blog's AtomPub API. Auth = HTTP
    Basic with the Livedoor ID + the blog's own AtomPub API key (issued
    separately under blog settings, NOT the account password)."""

    provider = "livedoor_blog"
    platform = PLATFORM_LIVEDOOR

    def __init__(self, *, livedoor_id: str, blog_name: str, api_key: str, timeout: float = 30.0) -> None:
        if not livedoor_id or not blog_name or not api_key:
            raise ProviderNotConfiguredError(f"Livedoor Blog publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url=f"https://livedoor.blogcms.jp/atompub/{blog_name}",
            headers={"Content-Type": "application/atom+xml;type=entry"},
            timeout=timeout,
        )
        self._auth = (livedoor_id, api_key)

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        entry = _hatena_entry_xml(post)
        path = f"/article/{post.external_id}" if post.external_id else "/article"
        response = self._client.request(
            "PUT" if post.external_id else "POST", path, content=entry.encode("utf-8"), auth=self._auth,
        )
        if response.status_code >= 400:
            raise ProviderCallError(f"Livedoor Blog request failed with status {response.status_code}")
        member_id, alt_link = _parse_hatena_response(response.text)
        if not alt_link:
            raise ProviderCallError("Livedoor Blog response missing the entry link")
        return Web2PublishResult(post_url=alt_link, verified=True, external_id=member_id or post.external_id)


# --------------------------------------------------------------------------- #
# FC2 Blog / Seesaa Blog - the shared legacy metaWeblog XML-RPC protocol
# (metaWeblog.newPost/editPost/getPost); no OAuth, username + password. One
# shared base, mirroring how _LJProtocolClient is shared by LiveJournal/
# Dreamwidth for their own shared legacy protocol.
# --------------------------------------------------------------------------- #
class _MetaWeblogClient:
    """Shared metaWeblog XML-RPC publisher - the protocol FC2 Blog and Seesaa
    Blog (and several other legacy Japanese blog hosts) implement verbatim.
    ``newPost``/``editPost`` return only a bare post id, never a permalink, so
    this always follows up with the protocol's own ``getPost`` to read back the
    real, host-assigned ``permaLink``/``link`` - safer than guessing a
    subdomain-based URL pattern per host."""

    platform = ""
    _endpoint = ""

    def __init__(self, *, blog_id: str, username: str, password: str) -> None:
        if not blog_id or not username or not password:
            raise ProviderNotConfiguredError(
                f"{self.platform} publisher unavailable: pass a per-account blog id + "
                "username + password (per-property, from the vault) to publish a Web 2.0 property"
            )
        self._blog_id, self._username, self._password = blog_id, username, password

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        import xmlrpc.client as xmlrpc

        proxy = xmlrpc.ServerProxy(self._endpoint)
        content_struct: dict[str, object] = {
            "title": post.title,
            "description": post.body_html + f'<p><a href="{post.target_url}">{post.anchor}</a></p>',
        }
        try:
            if post.external_id:
                proxy.metaWeblog.editPost(post.external_id, self._username, self._password, content_struct, True)
                post_id: Any = post.external_id
            else:
                post_id = proxy.metaWeblog.newPost(
                    self._blog_id, self._username, self._password, content_struct, True
                )
            fetched = cast(
                "dict[str, Any]", proxy.metaWeblog.getPost(post_id, self._username, self._password)
            )
        except (xmlrpc.Fault, OSError) as exc:
            raise ProviderCallError(f"{self.platform} XML-RPC call failed: {exc}") from exc
        post_url = str(fetched.get("permaLink") or fetched.get("link") or "")
        if not post_url:
            raise ProviderCallError(f"{self.platform} response missing a permalink")
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(post_id))


class FC2BlogClient(_MetaWeblogClient):
    provider = "fc2_blog"
    platform = PLATFORM_FC2
    _endpoint = "http://blog.fc2.com/xmlrpc.php"


class SeesaaBlogClient(_MetaWeblogClient):
    provider = "seesaa_blog"
    platform = PLATFORM_SEESAA
    # The SSL endpoint is preferred over the plain-HTTP blog.seesaa.jp/rpc one.
    _endpoint = "https://ssl.seesaa.jp/blog/rpc"


# --------------------------------------------------------------------------- #
# Warpcast (via Neynar) - Farcaster casts. Auth is an `x-api-key` header (NOT
# `Authorization: Bearer`); a pre-approved `signer_uuid` rides in the JSON body.
# --------------------------------------------------------------------------- #
class WarpcastClient(HttpProviderClient):
    """Real ``Web2Publisher`` over the Neynar API's Farcaster cast endpoint.
    ``signer_uuid`` must already be approved by the account owner (a one-time
    handshake outside this system - Neynar's signer-approval flow); this client
    only ever casts with an ALREADY-approved signer. The public permalink uses
    Warpcast's documented short-hash convention (``0x`` + the first 4 bytes/8
    hex chars of the cast hash); if the response is missing the author's
    username (needed to build that permalink), this returns ``verified=False``
    with a conversation-id fallback URL rather than guessing."""

    provider = "warpcast_neynar"
    platform = PLATFORM_WARPCAST
    _MAX_CHARS = 320

    def __init__(self, *, api_key: str, signer_uuid: str, timeout: float = 30.0) -> None:
        if not api_key or not signer_uuid:
            raise ProviderNotConfiguredError(f"Warpcast publisher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url="https://api.neynar.com/v2/farcaster",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )
        self._signer_uuid = signer_uuid

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        text = f"{post.title}\n\n{_html_to_text(post.body_html)}\n\n{post.target_url}"
        body: dict[str, object] = {
            "signer_uuid": self._signer_uuid,
            "text": text[: self._MAX_CHARS],
            "embeds": [{"url": post.target_url}],
        }
        data = self.request_json("POST", "/cast", json_body=body)
        cast = data.get("cast") or {}
        cast_hash = cast.get("hash")
        if not cast_hash:
            raise ProviderCallError("Warpcast/Neynar response missing cast hash")
        author = cast.get("author") or {}
        username = author.get("username")
        raw_hash = str(cast_hash)
        short_hash = raw_hash[2:10] if raw_hash.startswith("0x") else raw_hash[:8]
        if username:
            post_url = f"https://warpcast.com/{username}/0x{short_hash}"
            verified = True
        else:
            # Cannot build the real per-user permalink without a username - an
            # honest fallback, never a guessed URL.
            post_url = f"https://warpcast.com/~/conversations/{raw_hash}"
            verified = False
        return Web2PublishResult(post_url=post_url, verified=verified, external_id=raw_hash)


# --------------------------------------------------------------------------- #
# Sourcehut Pages - a GraphQL `publish` mutation taking a tarball Upload; the
# tarball is built entirely from the stdlib (tarfile + io.BytesIO) and sent as
# a standard GraphQL multipart request (operations + map + file part) - no new
# dependency needed.
# --------------------------------------------------------------------------- #
def _build_pages_tarball(post: Web2Post) -> bytes:
    """A minimal ``.tar.gz`` containing one ``index.html`` (regular file, mode
    644, no symlinks) - exactly the shape pages.sr.ht's ``publish`` mutation
    documents as its accepted ``content`` upload."""
    buf = io.BytesIO()
    content = _static_page(post).encode("utf-8")
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="index.html")
        info.size = len(content)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class SourcehutPagesClient(HttpProviderClient):
    """Real ``Web2Publisher`` over pages.sr.ht's GraphQL API
    (``POST https://pages.sr.ht/query``). The ``publish(domain, content)``
    mutation updates the site if ``domain`` already exists on this account, or
    creates it - so ``external_id`` needs no separate branch, every call is the
    same request. Sent as a standard GraphQL multipart request (the
    ``graphql-multipart-request-spec`` - an ``operations`` JSON part, a ``map``
    JSON part, and the file part), which ``httpx``'s ``files=``/``data=``
    already produces without any extra library."""

    provider = "sourcehut_pages"
    platform = PLATFORM_SOURCEHUT_PAGES
    _ENDPOINT = "https://pages.sr.ht/query"
    _MUTATION = (
        "mutation Publish($domain: String!, $content: Upload!) { "
        "publish(domain: $domain, content: $content) { id domain } }"
    )

    def __init__(self, *, token: str, domain: str, timeout: float = 30.0) -> None:
        if not token or not domain:
            raise ProviderNotConfiguredError(f"Sourcehut Pages publisher unavailable: {_INSTALL_HINT}")
        super().__init__(headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
        self._domain = domain

    def publish(self, platform: str, post: Web2Post) -> Web2PublishResult:
        if platform != self.platform:
            raise ProviderCallError(f"{self.platform} client cannot publish to {platform}")
        tarball = _build_pages_tarball(post)
        operations = json.dumps(
            {"query": self._MUTATION, "variables": {"domain": self._domain, "content": None}}
        )
        map_ = json.dumps({"0": ["variables.content"]})
        response = self._client.post(
            self._ENDPOINT,
            data={"operations": operations, "map": map_},
            files={"0": ("site.tar.gz", tarball, "application/gzip")},
        )
        if response.status_code >= 400:
            raise ProviderCallError(f"Sourcehut Pages request failed with status {response.status_code}")
        data = response.json()
        if data.get("errors"):
            raise ProviderCallError(f"Sourcehut Pages GraphQL error: {data['errors']}")
        site = (data.get("data") or {}).get("publish") or {}
        domain = site.get("domain")
        if not domain:
            raise ProviderCallError("Sourcehut Pages response missing domain")
        post_url = f"https://{domain}/"
        return Web2PublishResult(post_url=post_url, verified=True, external_id=str(site.get("id") or domain))


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


