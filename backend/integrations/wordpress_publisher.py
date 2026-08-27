"""AIOS Publisher plugin seam: the host-independent WordPress push.

The ordinary ``integrations.wordpress`` seam publishes over the WP REST v2 API with
an Application Password (HTTP Basic). That path is UNUSABLE on hosts that strip the
Authorization header, disable Application Passwords (the endpoint 501s), and run an
anti-bot layer that blocks non-browser requests - the real situation on some managed
hosts (Hostinger + a WAF). This seam is the bypass: it talks to the companion
``AIOS Publisher`` WordPress PLUGIN's OWN endpoint (``/wp-json/aios/v1/publish``)
authenticated by a SHARED KEY carried in the JSON REQUEST BODY (primary - the body
is never stripped) plus an ``X-AIOS-Key`` header (secondary). No Authorization
header, no Application Password, no XML-RPC.

Reachable exclusively through the ``PluginPublisher`` Protocol so the service layer
can meter/log it and unit tests can inject a fake.

* ``WordPressPluginPublisher`` - real, over the shared sync ``HttpProviderClient``.
  Sends a BROWSER User-Agent (the anti-bot layer blocks non-browser UAs - proven),
  a bounded timeout, and the key in the body. NEVER logs the key (auth rides in the
  body/headers, which the shared client keeps out of every log line). A call failure
  raises the typed ``WordPressPluginError`` - which the publish caller SWALLOWS
  (best-effort: a push failure must never crash the approve).
* ``FakeWordPressPluginPublisher`` - deterministic, offline: a stable post id +
  permalink/edit URL derived from the site + slug/title, so push tests + degraded
  runs are reproducible with no site.

CREDENTIALS ARE PASSED IN, NEVER READ HERE. The per-client ``site_url`` + plugin
``api_key`` are resolved by the SERVICE layer (from the job's ``source_pack`` + the
Key Vault, or the single-site settings default) and handed to the constructor; this
seam never touches settings, the DB, or the vault. ``WpPluginTarget`` +
``resolve_plugin_target`` are the small, pure config-resolution helpers the service
layer composes with the vault lookup.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from integrations.errors import ProviderCallError, ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

# The anti-bot layer on some managed hosts blocks non-browser User-Agents (proven on
# spotino.org). A current desktop-Chrome UA sails through; the caller can override it
# from settings if a site needs a different string.
DEFAULT_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_INSTALL_HINT = (
    "pass the AIOS Publisher site_url + api_key (per-site, from the Key Vault or the "
    "WP_PLUGIN_* settings default) to push"
)


class WordPressPluginError(RuntimeError):
    """An AIOS Publisher push failed (a non-2xx / malformed / not-ok response).

    The message NEVER contains the api_key or a response body - only the provider
    name + a short reason - because auth rides in the body/headers, not the URL. The
    publish caller catches this and degrades (best-effort), never crashing the approve.
    """


@dataclass(frozen=True)
class PluginPublishResult:
    """The plugin's response to a push: the created post's id + the URLs to show the
    operator (the live permalink, the wp-admin edit link, and a preview link) and the
    status the post landed in (``draft`` by default - a human publishes it on WP)."""

    post_id: int
    url: str
    edit_url: str
    status: str
    preview_url: str = ""


@runtime_checkable
class PluginPublisher(Protocol):
    """Push a content payload to a site's AIOS Publisher plugin, or probe it."""

    def ping(self) -> bool: ...

    def publish(self, payload: dict[str, Any]) -> PluginPublishResult: ...

    def deliver_site(self, plan: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class WpPluginTarget:
    """A resolved per-client plugin target: the site URL + the shared API key.

    The service layer builds this from the job's ``source_pack`` (non-secret site
    reference) + the vault-revealed key (or the settings default), then calls
    :meth:`publisher` to get a ready seam. The key stays a plain field here (never
    logged); it only ever leaves this object into the request body.
    """

    site_url: str
    api_key: str

    def publisher(
        self, *, user_agent: str = DEFAULT_BROWSER_UA, timeout: float = 30.0
    ) -> WordPressPluginPublisher:
        return WordPressPluginPublisher(
            site_url=self.site_url, api_key=self.api_key, user_agent=user_agent, timeout=timeout
        )


def resolve_plugin_target(
    source_pack: dict[str, Any] | None,
    *,
    default_site_url: str = "",
    default_api_key: str = "",
) -> WpPluginTarget | None:
    """Resolve a ``WpPluginTarget`` from a job's ``source_pack`` + defaults, or None.

    ``site_url`` comes from the source_pack's ``wp_site_url`` / ``site_url`` (the
    router seeds it from the client's site) falling back to ``default_site_url``. The
    ``api_key`` is NEVER seeded into the source_pack (it is a secret) - the caller
    passes it as ``default_api_key`` after revealing it from the vault (or the
    single-site settings default). A missing site_url OR key returns None (the
    publish path then keeps its existing behavior - unchanged).
    """
    pack = source_pack or {}
    site_url = str(pack.get("wp_site_url") or pack.get("site_url") or default_site_url or "").strip()
    api_key = str(default_api_key or "").strip()
    if not site_url or not api_key:
        return None
    return WpPluginTarget(site_url=site_url, api_key=api_key)


class WordPressPluginPublisher(HttpProviderClient):
    """Real ``PluginPublisher`` over the AIOS Publisher plugin's ``aios/v1`` REST API.

    Auth is the shared key in the JSON body (primary) + the ``X-AIOS-Key`` header
    (secondary); a BROWSER User-Agent defeats the host anti-bot layer. The caller
    (service layer) supplies the decrypted key; this class never reads the vault.
    """

    provider = "aios_publisher"

    def __init__(
        self,
        *,
        site_url: str,
        api_key: str,
        user_agent: str = DEFAULT_BROWSER_UA,
        timeout: float = 30.0,
    ) -> None:
        if not site_url or not api_key:
            raise ProviderNotConfiguredError(f"AIOS Publisher client unavailable: {_INSTALL_HINT}")
        # 403 is transient HERE (as with the WordPress client): a WAF / anti-bot
        # layer intermittently soft-challenges a valid request with a 403 that clears
        # on retry. 401 stays hard (a genuine key mismatch must not be retried).
        super().__init__(
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": user_agent,
                "X-AIOS-Key": api_key,
            },
            timeout=timeout,
            max_attempts=4,
            transient_statuses=frozenset({403}),
        )
        self._site_url = site_url.rstrip("/")
        self._api_key = api_key

    def _endpoint(self, route: str) -> str:
        return f"{self._site_url}/wp-json/aios/v1/{route}"

    def ping(self) -> bool:
        """Probe the plugin endpoint + key. Returns True only on a genuine ``ok``
        response; any failure (bad key, unreachable, wrong response) is False - never
        raises, so a connectivity test in the UI can show a clean red/green."""
        try:
            # GET carries no body, so the key rides the query (stripped from logs by
            # the shared client) + the X-AIOS-Key header - robust to header stripping.
            data = self.request_json("GET", self._endpoint("ping"), params={"api_key": self._api_key})
        except ProviderCallError:
            return False
        return data.get("ok") is True

    def capabilities(self) -> dict[str, Any]:
        """What this site can render, from ``/ping``'s ``capabilities`` object.

        The replica builder asks this BEFORE emitting, so it can use a client's
        Elementor Pro (or any third-party widget pack) instead of assuming the free
        tier for everyone. Never raises: an unreachable site or an older plugin that
        does not report a registry returns ``{}``, and the builder falls back to the
        conservative free vocabulary rather than guessing upward.
        """
        try:
            data = self.request_json(
                "GET", self._endpoint("ping"), params={"api_key": self._api_key}
            )
        except ProviderCallError:
            return {}
        caps = data.get("capabilities")
        return dict(caps) if isinstance(caps, dict) else {}

    def publish(self, payload: dict[str, Any]) -> PluginPublishResult:
        """Push a content payload to the plugin and return its result.

        The api_key is injected into the body here (primary auth); the caller passes
        only the content fields. A non-2xx / malformed / not-``ok`` response raises
        :class:`WordPressPluginError` (the message never contains the key or a body).
        """
        body: dict[str, Any] = {k: v for k, v in payload.items() if v is not None}
        body["api_key"] = self._api_key  # primary auth: in the body (never stripped)
        try:
            data = self.request_json("POST", self._endpoint("publish"), json_body=body)
        except ProviderCallError as exc:
            # Re-type as the seam's error WITHOUT echoing the payload/key.
            raise WordPressPluginError(f"AIOS Publisher push failed: {exc}") from exc
        if data.get("ok") is not True:
            raise WordPressPluginError("AIOS Publisher push returned a non-ok response")
        post_id = data.get("post_id")
        if not isinstance(post_id, int):
            raise WordPressPluginError("AIOS Publisher response missing a post id")
        return PluginPublishResult(
            post_id=post_id,
            url=str(data.get("url") or ""),
            edit_url=str(data.get("edit_url") or ""),
            status=str(data.get("status") or "draft"),
            preview_url=str(data.get("preview_url") or ""),
        )

    def deliver_site(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Deliver a WHOLE SITE plan - pages, hierarchy, menu, front page - in one call.

        Requires plugin 1.9.0. An older plugin has no `/site` route and answers 404,
        which surfaces as a `WordPressPluginError` naming the version rather than as an
        opaque transport failure: "the site was not delivered" is not actionable, and
        "this site is running a plugin without /site" is.

        Returns the plugin's manifest verbatim. Deliberately NOT reduced to a single
        boolean: a delivery can partly succeed - one page failing to write while
        forty-nine land - and collapsing that to False would throw away the only record
        of which one, while collapsing it to True would hide it entirely.
        """
        body: dict[str, Any] = dict(plan)
        body["api_key"] = self._api_key  # primary auth: in the body (never stripped)
        try:
            data = self.request_json("POST", self._endpoint("site"), json_body=body)
        except ProviderCallError as exc:
            text = str(exc)
            if "404" in text:
                raise WordPressPluginError(
                    "this site's AIOS Publisher has no /site route; whole-site delivery "
                    "needs plugin 1.9.0 or newer"
                ) from exc
            raise WordPressPluginError(f"AIOS Publisher site delivery failed: {exc}") from exc
        if data.get("ok") is not True:
            raise WordPressPluginError("AIOS Publisher site delivery returned a non-ok response")
        return data


class FakeWordPressPluginPublisher:
    """Deterministic, offline ``PluginPublisher`` for unit tests + degraded runs.

    ``publish`` derives a stable positive post id from sha256(site + slug/title) and
    returns stable permalink/edit URLs under the site; ``ping`` returns a configurable
    flag. Records every pushed payload so a test can assert the key+fields it sent.
    No network, so results are reproducible with no site.
    """

    def __init__(self, *, site_url: str = "https://example.test", healthy: bool = True) -> None:
        self._site_url = site_url.rstrip("/")
        self._healthy = healthy
        self.published: list[dict[str, Any]] = []
        self.delivered: list[dict[str, Any]] = []

    def ping(self) -> bool:
        return self._healthy

    def deliver_site(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Mirror the plugin's own manifest shape, including its refusals.

        Written to behave like the REAL assembler rather than to succeed: a page with
        no slug is dropped exactly as `aios_publisher_upsert_page` drops it, and the
        front page only "changes" when the plan named one. A fake that always succeeds
        would let a caller ship code that never handles a partial delivery.
        """
        self.delivered.append(plan)
        pages = [p for p in (plan.get("pages") or []) if isinstance(p, dict)]
        rows: list[dict[str, Any]] = []
        ids: dict[str, int] = {}
        for page in pages:
            slug = str(page.get("slug") or "").strip()
            if not slug:
                continue
            post_id = 1 + int(
                hashlib.sha256(f"{self._site_url}/{slug}".encode()).hexdigest()[:8], 16
            ) % 100_000
            ids[slug] = post_id
            rows.append({
                "slug": slug, "ok": True, "id": post_id, "created": True,
                "elementor": bool(str(page.get("elementor_data") or "").strip()),
                "url": f"{self._site_url}/{slug}/",
            })
        menu = plan.get("menu") or {}
        front = str(plan.get("front_page_slug") or "")
        return {
            "ok": True,
            "pages": rows,
            "parents": sum(
                1 for p in pages
                if str(p.get("parent_slug") or "") and str(p.get("parent_slug")) in ids
            ),
            "menu": {
                "built": bool(menu.get("name")),
                "menu_id": 7,
                "items": sum(1 for p in pages if p.get("in_menu", True) and p.get("slug")),
                "assigned": bool(menu.get("location")),
                "held": "",
            },
            "front_page": (
                {"changed": True, "page_id": ids[front]}
                if front in ids
                else {"changed": False, "reason": "not requested"}
            ),
        }

    def publish(self, payload: dict[str, Any]) -> PluginPublishResult:
        self.published.append(dict(payload))
        slug = str(payload.get("slug") or payload.get("title") or "post")
        digest = hashlib.sha256(f"{self._site_url}|{slug}".encode()).hexdigest()
        post_id = int(digest[:8], 16) % 1_000_000 + 1  # stable positive id
        status = str(payload.get("status") or "draft")
        return PluginPublishResult(
            post_id=post_id,
            url=f"{self._site_url}/?p={post_id}",
            edit_url=f"{self._site_url}/wp-admin/post.php?post={post_id}&action=edit",
            status=status,
            preview_url=f"{self._site_url}/?p={post_id}&preview=true",
        )
