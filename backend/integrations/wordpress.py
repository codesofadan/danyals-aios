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

SEO PARITY, AND WHERE IT STOPS. A ``PostDraft`` carries a :class:`SeoFields` built
ONCE by the caller, and every transport pushes as much of it as its protocol allows:

* REST sends ``excerpt``, the ``post_tag`` ids it resolved from the tag names, and the
  SEO-plugin post meta - then CHECKS the returned ``meta`` (see the silent-drop
  paragraph above) rather than trusting the 200. It cannot carry the featured image
  (``featured_media`` takes a media id, and sideloading is unbuilt) or the JSON-LD.
* XML-RPC sends ``post_excerpt``, tags by name via ``terms_names``, and the
  non-protected SEO meta via ``custom_fields``. It cannot carry Yoast's protected
  ``_yoast_wpseo_*`` keys (core's ``add_post_meta`` cap check refuses them), the
  featured image, or the JSON-LD.

Whatever a transport could not carry comes back on ``PublishResult.dropped``, named
with its reason. That list is the point: two of these three transports used to drop
the entire SEO half in silence, so an operator had no way to learn that a client on
``app_password`` or ``xmlrpc`` was getting a bare HTML post.

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

# A current desktop-Chrome User-Agent. Managed hosts' anti-bot layers block
# non-browser UAs (proven on some hosts); every real request here rides this string
# so a hostile host cannot soft-block an otherwise-valid authenticated call.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


# --------------------------------------------------------------------------- #
# The SEO half of a WordPress push - ONE definition, shared by every transport.
# --------------------------------------------------------------------------- #
# THE DEFECT THIS CLOSES: the content worker assembled meta title/description, focus
# keyword, tags, the hero image and the JSON-LD graph for the AIOS Publisher PLUGIN
# payload, while ``PostDraft`` carried five fields (title/content/status/slug/
# wp_post_id) - so a client whose WordPress connection is ``app_password`` or
# ``xmlrpc`` received a bare HTML post with NO SEO metadata at all, and nothing
# anywhere said so. The derivation now happens once (``workers.tasks.content.
# _seo_fields``) and arrives here; each transport carries what its protocol allows
# and NAMES the remainder on ``PublishResult.dropped``, because silently shipping a
# client less than the plugin path delivers is the failure, not the missing field.


@dataclass(frozen=True)
class SeoFields:
    """Protocol-neutral SEO metadata for one post, derived once by the caller.

    Every field is optional and empty-by-default: absent means the job produced
    nothing for it, NOT that a transport dropped it. What a transport could not carry
    is reported separately on :class:`PublishResult` - the two are different facts and
    conflating them would hide the second.

    ``tags`` are NAMES (``post_tag`` terms). The REST API takes term IDs, XML-RPC
    takes names, and the plugin takes names, so the shared shape is the name and each
    transport does its own mapping.
    """

    meta_title: str = ""
    meta_description: str = ""
    focus_keyword: str = ""
    tags: tuple[str, ...] = ()
    featured_image_url: str = ""
    schema_jsonld: str = ""


#: SEO field -> the post-meta keys the two SEO plugins in the field read it from.
#: BOTH families are written on every push because which plugin a client's site runs
#: is not knowable from here; the one that is installed reads its keys and the other
#: family is inert. Verified against each plugin's own meta registration - do not add
#: a key here without checking the plugin actually reads it.
SEO_META_KEYS: dict[str, tuple[str, str]] = {
    "meta_title": ("_yoast_wpseo_title", "rank_math_title"),
    "meta_description": ("_yoast_wpseo_metadesc", "rank_math_description"),
    "focus_keyword": ("_yoast_wpseo_focuskw", "rank_math_focus_keyword"),
}


def seo_meta(seo: SeoFields) -> dict[str, str]:
    """The flat post-meta payload for ``seo``, keyed for both SEO plugins.

    An empty field writes nothing: pushing ``""`` would blank a meta description a
    human had written on the site, which is a silent data loss dressed as an update.
    """
    meta: dict[str, str] = {}
    for field, keys in SEO_META_KEYS.items():
        value = str(getattr(seo, field) or "")
        if not value:
            continue
        for key in keys:
            meta[key] = value
    return meta


@dataclass(frozen=True)
class PostDraft:
    """The content to publish. ``wp_post_id`` set => idempotent UPDATE, else CREATE.

    ``content`` is rendered HTML; ``status`` is the WP post status (``draft`` keeps a
    human-approval step on the WP side, ``publish`` goes live). ``slug`` / ``excerpt``
    are optional; the pipeline supplies them from the job. ``seo`` carries the SEO half
    (see :class:`SeoFields`); ``None`` means the caller had none to send - it is never
    a transport's excuse for dropping one.
    """

    title: str
    content: str
    status: str = "draft"
    slug: str | None = None
    excerpt: str | None = None
    wp_post_id: int | None = None
    seo: SeoFields | None = None


@dataclass(frozen=True)
class PublishResult:
    """The published post's WP id (record it on the job for idempotent re-publish)
    and its public URL.

    ``dropped`` names every piece of :class:`SeoFields` this transport could NOT put
    on the site, each with the reason. It is empty on a full-parity push. The caller
    must surface it: a post that went live carrying none of its SEO metadata is not a
    failure to retry, it is a client quietly receiving less, and only a named note
    lets an operator find that out.
    """

    post_id: int
    url: str
    dropped: tuple[str, ...] = ()

    def dropped_note(self) -> str:
        """One operator-facing sentence for ``dropped``; ``""`` at full parity."""
        if not self.dropped:
            return ""
        return "not carried by this WordPress transport: " + "; ".join(self.dropped)


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


# Reasons a transport reports on PublishResult.dropped. They are constants because
# a test asserts the exact string a client is told, and a reason that drifts from what
# the code actually does is worse than no reason.
_DROP_REST_FEATURED_IMAGE = (
    "featured image (the REST API takes a media id, not a URL - sideloading the file "
    "into the media library is unbuilt)"
)
_DROP_REST_SCHEMA = (
    "schema JSON-LD (the REST API has no field for it - only the AIOS Publisher plugin "
    "injects the graph)"
)
_DROP_XMLRPC_FEATURED_IMAGE = (
    "featured image (wp.newPost takes an attachment id, not a URL - uploading the file "
    "is unbuilt)"
)
_DROP_XMLRPC_SCHEMA = "schema JSON-LD (XML-RPC has no field that carries it)"
_DROP_XMLRPC_PROTECTED_META = (
    "the Yoast meta keys (WordPress refuses protected `_`-prefixed meta over XML-RPC) - "
    "the Rank Math keys were written, so a Yoast-only site shows no SEO title"
)
_DROP_XMLRPC_META_ON_UPDATE = (
    "SEO plugin meta (re-publish could not read the post's existing custom fields, and "
    "writing them blind APPENDS duplicate rows the plugin then ignores)"
)


def _unlanded_seo_meta(sent: dict[str, str], returned: Any) -> list[str]:
    """The SEO fields whose meta was SILENTLY DROPPED by WordPress, one per field.

    WordPress answers 200 and echoes the OLD value for any meta key no plugin
    registered with ``show_in_rest`` (see the module docstring) - so trusting the 2xx
    is how a publish path reports SEO metadata it never wrote. The response to a
    create/update already carries ``meta``, so the check costs no extra call.

    Reported PER FIELD, not per key: both plugin families are always sent, so on a
    Rank Math site the Yoast keys legitimately never land. A field counts as carried
    when AT LEAST ONE of its keys round-tripped, and as dropped only when NO SEO plugin
    took it - which is the real, actionable fact ("this site has no SEO plugin exposing
    these fields to the REST API").
    """
    if not sent:
        return []
    meta = returned if isinstance(returned, dict) else {}
    missing: list[str] = []
    for field, keys in SEO_META_KEYS.items():
        value = sent.get(keys[0])
        if not value:
            continue
        if not any(str(meta.get(key, "")) == value for key in keys):
            missing.append(f"{field} (no SEO plugin on this site registered its meta key with the REST API)")
    return missing


class WordPressClient(HttpProviderClient):
    """Real ``WordPressPublisher`` + ``WordPressEditor`` over the WP REST v2 API.

    Auth is an application password via HTTP Basic (``username`` + ``app_password``),
    handed to ``httpx`` per request and NEVER logged. The caller (service layer)
    supplies the decrypted credential; this class never reads the vault.
    """

    provider = "wordpress"

    def __init__(
        self,
        *,
        username: str,
        app_password: str,
        user_agent: str = BROWSER_UA,
        timeout: float = 30.0,
    ) -> None:
        if not username or not app_password:
            raise ProviderNotConfiguredError(f"WordPress client unavailable: {_INSTALL_HINT}")
        # No base_url: each publish targets a per-call absolute site URL.
        # A managed host in front of WordPress (Hostinger's hcdn, a WAF, some
        # security plugins) intermittently answers an otherwise-valid authenticated
        # REST call with a soft-challenge 403 that clears on an immediate retry, so
        # 403 is transient HERE (not globally) and the publish path gets one extra
        # attempt. A genuine permission-403 (the app password lacks publish rights)
        # still surfaces as ProviderCallError once the attempts are spent. A browser
        # User-Agent rides every call so an anti-bot layer cannot soft-block it.
        super().__init__(
            headers={"Content-Type": "application/json", "User-Agent": user_agent},
            timeout=timeout,
            max_attempts=4,
            transient_statuses=frozenset({403}),
        )
        self._auth = (username, app_password)

    def verify(self, site_url: str) -> tuple[bool, str]:
        """Non-raising credential probe for the connectivity test: read the current
        user (``GET /wp-json/wp/v2/users/me?context=edit``) under HTTP Basic. Returns
        ``(ok, detail)`` so the UI shows a clean red/green without a 500. The detail
        never contains the credential (auth rides the Basic header, kept out of logs)."""
        try:
            data = self.request_json(
                "GET",
                f"{site_url.rstrip('/')}/wp-json/wp/v2/users/me",
                params={"context": "edit"},
                auth=self._auth,
            )
        except ProviderCallError as exc:
            return False, f"REST verify failed: {exc}"
        who = data.get("name") or data.get("slug") or "the account"
        return True, f"Application Password accepted for {who}"

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

    def _term_id(self, base: str, name: str) -> int | None:
        """The ``post_tag`` term id for ``name``, creating the term if needed; ``None``
        when neither is possible (the caller then reports the tag as dropped).

        LOOKUP BEFORE CREATE, deliberately: ``POST /wp/v2/tags`` runs its permission
        check (``manage_categories``) BEFORE it looks at the name, so an author-level
        application password is 403'd even for a tag that already exists. Searching
        first (the collection route is readable) is what lets that credential attach
        existing tags instead of losing all of them.
        """
        found = self._get_enveloped("GET", base, params={"search": name, "per_page": 100})
        if isinstance(found, list):
            for term in found:
                # `search` is a fuzzy LIKE match, so the id is only taken on an exact
                # name match - otherwise "brunch" would silently attach "brunch spots".
                if isinstance(term, dict) and str(term.get("name") or "").strip().lower() == name.lower():
                    term_id = term.get("id")
                    if isinstance(term_id, int):
                        return term_id
        created = self._get_enveloped("POST", base, json_body={"name": name})
        if not isinstance(created, dict):
            return None
        term_id = created.get("id")
        if isinstance(term_id, int):
            return term_id
        # A `term_exists` refusal carries the existing term's id in its error data -
        # the race window between the search above and this create.
        data = created.get("data")
        if isinstance(data, dict) and isinstance(data.get("term_id"), int):
            return int(data["term_id"])
        return None

    def _get_enveloped(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> Any:
        """One WP REST call under ``?_envelope=1``, returning the inner body (or None).

        TWO reasons for the envelope, both structural rather than stylistic:

        1. ``/wp/v2/tags`` is a COLLECTION route and answers with a JSON ARRAY, which
           the shared ``request_json`` rejects by contract ("unexpected JSON shape").
           ``_envelope=1`` (WP core, since 4.4) wraps the payload as
           ``{"body": ..., "status": ..., "headers": ...}`` - an object - so the tag
           lookup rides the SAME retry + never-log-a-secret path as every other call
           instead of reaching around it into httpx.
        2. It turns the expected refusals (403 on create, 400 ``term_exists``) into a
           readable body instead of a raised ``ProviderCallError``, so a tag that
           cannot be created degrades into the drop list rather than aborting a
           publish whose post body is perfectly good.

        The cost is that a genuine 5xx also arrives as HTTP 200 and is NOT retried;
        that is acceptable here and ONLY here - a lost tag is reported, not hidden.
        """
        enveloped = dict(params or {})
        enveloped["_envelope"] = 1
        try:
            payload = self.request_json(method, url, params=enveloped, json_body=json_body, auth=self._auth)
        except ProviderCallError:
            return None
        if "body" not in payload:  # a host that ignores _envelope: unusable, not fatal
            return None
        return payload["body"]

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
        dropped: list[str] = []
        seo = post.seo
        sent_meta: dict[str, str] = {}
        if seo is not None:
            sent_meta = seo_meta(seo)
            if sent_meta:
                body["meta"] = dict(sent_meta)
            if seo.tags:
                base = f"{site_url.rstrip('/')}/wp-json/wp/v2/tags"
                ids: list[int] = []
                unresolved: list[str] = []
                for name in seo.tags:
                    term_id = self._term_id(base, name)
                    if term_id is None:
                        unresolved.append(name)
                    else:
                        ids.append(term_id)
                if ids:
                    # The REST schema for `tags` is an array of INTEGER term ids;
                    # posting names is a rest_invalid_param, which is why they are
                    # resolved above rather than passed through.
                    body["tags"] = ids
                if unresolved:
                    dropped.append(
                        "tags " + ", ".join(unresolved)
                        + " (the term does not exist and this credential may not create one)"
                    )
            if seo.featured_image_url:
                dropped.append(_DROP_REST_FEATURED_IMAGE)
            if seo.schema_jsonld:
                dropped.append(_DROP_REST_SCHEMA)
        # Idempotent: an existing post id -> POST to /posts/{id} (WP treats POST to a
        # single-post route as an update), else POST to /posts to create.
        url = f"{endpoint}/{post.wp_post_id}" if post.wp_post_id else endpoint
        data = self.request_json("POST", url, json_body=body, auth=self._auth)
        post_id = data.get("id")
        link = data.get("link")
        if not isinstance(post_id, int) or not isinstance(link, str):
            raise ProviderCallError("WordPress response missing post id or link")
        dropped.extend(_unlanded_seo_meta(sent_meta, data.get("meta")))
        return PublishResult(post_id=post_id, url=link, dropped=tuple(dropped))


class XmlRpcWordPressPublisher:
    """``WordPressPublisher`` over XML-RPC (``POST /xmlrpc.php`` ``wp.newPost``).

    The path that actually works on HOSTILE managed hosts that strip the
    ``Authorization`` header or disable Application Passwords (the REST app-password
    path 501s / 401s there): the credential rides in the XML request BODY (never a
    header), behind a browser User-Agent that defeats the anti-bot layer. Idempotent
    like the REST seam - a ``PostDraft`` carrying a ``wp_post_id`` edits that post
    (``wp.editPost``), else it creates one (``wp.newPost``).

    HOSTILE-HOST QUIRK this seam survives: some such hosts append stray HTML or
    whitespace AFTER ``</methodResponse>`` (a WAF/cache footer), which breaks a strict
    XML parse; :meth:`_call` trims to the closing tag before unmarshalling so a valid
    response is never misread as malformed. Credentials are PASSED IN, never read here.
    """

    provider = "wordpress_xmlrpc"

    def __init__(
        self,
        *,
        username: str,
        app_password: str,
        user_agent: str = BROWSER_UA,
        timeout: float = 30.0,
    ) -> None:
        if not username or not app_password:
            raise ProviderNotConfiguredError(f"WordPress XML-RPC client unavailable: {_INSTALL_HINT}")
        try:
            import httpx
        except ImportError as exc:  # httpx is a base dep; guard mirrors the HTTP seam
            raise ProviderNotConfiguredError(
                "WordPress XML-RPC client unavailable: install httpx (a base dependency)"
            ) from exc
        self._client = httpx.Client(
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "Accept": "text/xml",
                "User-Agent": user_agent,
            },
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        )
        self._username = username
        self._password = app_password

    @staticmethod
    def _endpoint(site_url: str) -> str:
        return f"{site_url.rstrip('/')}/xmlrpc.php"

    def _call(self, site_url: str, method: str, params: list[Any]) -> Any:
        """Issue one XML-RPC call and return its first return value (or None).

        The credential is marshalled into the XML body by ``xmlrpc.client.dumps``; a
        4xx/5xx is a ``ProviderCallError`` (never echoing the body), and a fault or a
        non-XML body (after trimming a hostile-host footer) is likewise typed."""
        import xmlrpc.client

        body = xmlrpc.client.dumps(tuple(params), methodname=method)
        response = self._client.post(self._endpoint(site_url), content=body.encode("utf-8"))
        if response.status_code >= 400:
            raise ProviderCallError(
                f"wordpress xmlrpc request failed with status {response.status_code}"
            )
        text = response.text
        marker = "</methodResponse>"
        idx = text.find(marker)
        if idx != -1:
            text = text[: idx + len(marker)]  # trim any HTML the host appended after the XML
        try:
            values, _method = xmlrpc.client.loads(text)
        except xmlrpc.client.Fault as fault:
            raise ProviderCallError(f"wordpress xmlrpc fault {fault.faultCode}") from fault
        except Exception as exc:  # a non-XML / truncated body
            raise ProviderCallError("wordpress xmlrpc returned a non-XML body") from exc
        return values[0] if values else None

    def _existing_meta_ids(self, site_url: str, post_id: int) -> dict[str, int] | None:
        """``meta_key -> meta_id`` for a post's existing custom fields, or ``None`` when
        they cannot be read.

        Needed ONLY on the update path, and needed there absolutely: XML-RPC's
        ``set_custom_fields`` calls ``add_post_meta`` for an entry with no ``id``, so
        re-publishing a job would append a SECOND ``rank_math_title`` row rather than
        replace the first. ``get_post_meta(..., true)`` then keeps returning the
        original value - the update looks like it worked and never took effect, and the
        duplicates accumulate one per re-publish. Carrying the meta_id makes the write
        an update in place.
        """
        try:
            raw = self._call(
                site_url,
                "wp.getPost",
                [0, self._username, self._password, post_id, ["custom_fields"]],
            )
        except Exception:
            # Broad on purpose: this read exists only to make the meta write SAFE, so
            # no failure of it - a fault, an unreachable host, a host that does not
            # expose wp.getPost - may turn a publishable post into a raised exception.
            # It degrades into the reported drop list; the editPost below still runs.
            return None
        if not isinstance(raw, dict):
            return None
        fields = raw.get("custom_fields")
        if not isinstance(fields, list):
            return {}
        found: dict[str, int] = {}
        for field in fields:
            if not isinstance(field, dict):
                continue
            key = str(field.get("key") or "")
            try:
                meta_id = int(str(field.get("id")))
            except (TypeError, ValueError):
                continue
            if key and key not in found:
                found[key] = meta_id
        return found

    def publish(self, site_url: str, post: PostDraft) -> PublishResult:
        struct: dict[str, Any] = {
            "post_type": "post",
            # honour the draft's status (the publish path pushes "publish"); anything
            # else lands as a draft a human flips live on WordPress.
            "post_status": "publish" if post.status == "publish" else "draft",
            "post_title": post.title,
            "post_content": post.content,
        }
        if post.slug:
            struct["post_name"] = post.slug
        if post.excerpt:
            struct["post_excerpt"] = post.excerpt
        dropped: list[str] = []
        seo = post.seo
        if seo is not None:
            if seo.tags:
                # `terms_names` is XML-RPC's own by-NAME taxonomy field: it creates a
                # missing term and, on editPost, REPLACES the post's tags - so this is
                # the one field where XML-RPC beats REST, which needs term ids.
                struct["terms_names"] = {"post_tag": list(seo.tags)}
            all_meta = seo_meta(seo)
            # Protected (`_`-prefixed) meta is refused by core on this path:
            # `set_custom_fields` checks `add_post_meta`, which map_meta_cap denies for
            # a protected key unless a plugin registered an `auth_post_meta_*` filter.
            # Sending them anyway would be a write we KNOW is discarded, so they are
            # left out and reported instead.
            writable = {key: value for key, value in all_meta.items() if not key.startswith("_")}
            if len(writable) != len(all_meta):
                dropped.append(_DROP_XMLRPC_PROTECTED_META)
            if writable:
                existing: dict[str, int] | None = {}
                if post.wp_post_id is not None:
                    existing = self._existing_meta_ids(site_url, int(post.wp_post_id))
                if existing is None:
                    dropped.append(_DROP_XMLRPC_META_ON_UPDATE)
                else:
                    struct["custom_fields"] = [
                        {"id": existing[key], "key": key, "value": value}
                        if key in existing
                        else {"key": key, "value": value}
                        for key, value in writable.items()
                    ]
            if seo.featured_image_url:
                dropped.append(_DROP_XMLRPC_FEATURED_IMAGE)
            if seo.schema_jsonld:
                dropped.append(_DROP_XMLRPC_SCHEMA)
        if post.wp_post_id is not None:
            # wp.editPost(blog_id, user, pass, post_id, content_struct) -> bool (idempotent UPDATE)
            self._call(
                site_url,
                "wp.editPost",
                [0, self._username, self._password, int(post.wp_post_id), struct],
            )
            new_id = int(post.wp_post_id)
        else:
            # wp.newPost(blog_id, user, pass, content_struct) -> the new post id (a string)
            raw_id = self._call(
                site_url, "wp.newPost", [0, self._username, self._password, struct]
            )
            try:
                new_id = int(str(raw_id))
            except (TypeError, ValueError) as exc:
                raise ProviderCallError("wordpress xmlrpc returned no usable post id") from exc
        return PublishResult(
            post_id=new_id, url=f"{site_url.rstrip('/')}/?p={new_id}", dropped=tuple(dropped)
        )

    def verify(self, site_url: str) -> tuple[bool, str]:
        """Non-raising probe: ``wp.getUsersBlogs(username, password)`` lists the sites
        the credential may post to. Returns ``(ok, detail)`` for a clean red/green."""
        try:
            self._call(site_url, "wp.getUsersBlogs", [self._username, self._password])
        except ProviderCallError as exc:
            return False, f"XML-RPC verify failed: {exc}"
        except Exception:  # transport error / unreachable host
            return False, "XML-RPC verify failed: the site could not be reached"
        return True, "XML-RPC reachable and the credentials were accepted"


class FakeWordPressPublisher:
    """Deterministic, offline ``WordPressPublisher``.

    An update (``wp_post_id`` set) echoes that id back; a create derives a stable
    positive id from sha256(site + slug/title). The URL is a stable permalink under
    the site. No network, so publish tests + degraded runs are reproducible.

    ``published`` records every ``(site_url, PostDraft)`` it was handed, which is how a
    test proves the caller actually FILLED the draft (the SEO half in particular) - an
    id and a URL come back looking identical whether or not it did. It reports nothing
    dropped: it stands in for a transport with no limits, so a drop seen in a test is
    always one the real transport reported.
    """

    def __init__(self) -> None:
        self.published: list[tuple[str, PostDraft]] = []

    def publish(self, site_url: str, post: PostDraft) -> PublishResult:
        self.published.append((site_url, post))
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
