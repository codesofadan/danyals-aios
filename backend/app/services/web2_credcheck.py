"""Does this credential actually authenticate — right now, before a campaign runs?

THE PROBLEM THIS REMOVES. Until now the only way to learn that a token was wrong was to
run a campaign and watch it fail: the account looked "connected" because the required
fields were non-empty, which proves shape, not validity. A revoked token, a typo, or a
key pasted from the wrong platform all look identical to a completeness check. The
operator finds out after the drafting spend, not before it.

So this makes ONE cheap authenticated read per platform — the account's own profile
endpoint — and reports what the platform said.

THREE OUTCOMES, deliberately, matching the link checker's discipline:

* ``ok``      - the platform accepted the credential.
* ``bad``     - the platform REJECTED it (401/403). Actionable: re-issue the token.
* ``unknown`` - we could not ask (no verifier for this platform, network failure, or an
  unexpected status). NOT a pass and NOT a failure. Collapsing "could not check" into
  either one is how a status board starts lying.

Read-only by construction: every request here is a GET (or a GraphQL query), so a
verification can never create, publish, or modify anything on the account.

PURE CORE: :func:`request_for` builds the request spec from a credential dict with no
network, so the per-platform wiring is unit-tested offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

CheckState = Literal["ok", "bad", "unknown"]


@dataclass(frozen=True)
class VerifyRequest:
    """A single cheap, read-only authenticated call."""

    url: str
    headers: dict[str, str]
    method: str = "GET"
    json_body: dict[str, Any] | None = None
    #: Does this request actually PRESENT the credential? A probe that omits it can only
    #: prove the instance is reachable, and reporting that as "authenticated" is the exact
    #: false success this module exists to remove.
    authenticated: bool = True
    #: True when the HOST came out of the CREDENTIAL (a self-hosted Mastodon, a Drupal
    #: site, a Ghost instance) rather than being a constant in this file.
    #:
    #: THE SSRF SEAM. Every other verifier talks to a fixed vendor host, so the operator
    #: cannot steer it. These are steerable by whoever typed the account's fields: a
    #: `base_url` of `http://169.254.169.254/` would make the SERVER fetch cloud
    #: metadata and hand the body back in `detail`. `check_credential` resolves and
    #: rejects private addresses before any of these are fetched.
    host_from_credential: bool = False
    #: Does this endpoint answer JSON? Nearly all do, and `interpret` treats an HTML body
    #: on a JSON API as "this is not the API any more" - the rule that catches a retired
    #: endpoint quietly serving a docs page.
    #:
    #: Micro.blog's `/account/verify` is the exception: it answers `text/html` with a
    #: bare sentence, on success AND on rejection (a bad token returns 401 with the body
    #: "Invalid token"). Holding it to the JSON rule reported a WORKING credential as
    #: unverifiable - the same false negative, pointed the other way.
    expects_json: bool = True


@dataclass(frozen=True)
class CredCheck:
    state: CheckState = "unknown"
    detail: str = ""
    identity: str = ""      # who the platform says we are, when it tells us

    @property
    def ok(self) -> bool:
        return self.state == "ok"


class Fetcher(Protocol):
    """Perform the request; return (status_code, body_text). Never raises."""

    def __call__(self, req: VerifyRequest) -> tuple[int, str]: ...


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _base(url: str) -> str:
    """A credential-supplied base URL, trailing slash removed."""
    return url.strip().rstrip("/")


#: Platforms we deliberately do NOT verify, each with the reason.
#:
#: WHY THIS EXISTS RATHER THAN LETTING THEM FALL THROUGH. "No verifier for this platform
#: yet" is what every unlisted platform used to say, and it reads as a TODO - so an
#: operator waits for a verifier that is never coming, and an engineer re-investigates
#: the same platform every few months. These four cannot be verified for reasons that
#: will not change, and saying so is a different message from "not built yet".
#:
#: A platform belongs here ONLY when checking is impossible or would breach the module's
#: read-only promise. "Fiddly" is not a reason; see `_WSSE_PLATFORMS`.
UNVERIFIABLE: dict[str, str] = {
    "dpaste.org": (
        "this platform takes no credential at all - posting is anonymous, so there is "
        "nothing to verify"
    ),
    "rentry.co": (
        "this platform takes no credential at all - posting is anonymous, so there is "
        "nothing to verify"
    ),
    "WriteFreely": (
        "the account holds only an instance URL and no credential, so a check could "
        "prove the instance answers but nothing about a login"
    ),
    "Pastebin.com": (
        "Pastebin's API exposes no read-only route that validates a dev key: the only "
        "way to exercise it is to POST a paste, which this check must never do"
    ),
}

#: Platforms whose AtomPub API authenticates with a WSSE header.
#:
#: NOT built here, and the reason is worth stating because it looks like an oversight:
#: a WSSE header is `base64(sha1(nonce + created + secret))`, so it needs a random nonce
#: and the current time. `request_for` is a PURE function - that is what lets every
#: verifier be unit-tested offline without a clock or a network - and threading an
#: injected clock and RNG through it for three platforms would cost the property that
#: makes the other forty testable.
#:
#: They report `unknown` with this reason rather than a bare "not built", so nobody
#: mistakes them for the platforms that simply have no route.
_WSSE_PLATFORMS: dict[str, str] = {
    "Hatena Blog": "hatena_id",
    "Livedoor Blog": "livedoor_id",
    "Seesaa Blog": "username",
}

#: Platforms that authenticate by POSTing a username and password to mint a session.
#:
#: Verifying these means LOGGING IN. That creates a session token on the platform, which
#: is not a content change and not something a person would notice - but it is a write
#: in the sense that it mutates server state, so each one is an explicit decision rather
#: than something the registry does by default.
#:
#: Bluesky and WhiteWind are IN (the AT Protocol has no other way to check an app
#: password, and `createSession` is the documented, expected call). The XML-RPC blogs
#: are OUT: their login endpoints are legacy, unauthenticated-probe-hostile, and a
#: failed attempt counts toward lockout on at least LiveJournal.
_SESSION_LOGIN_REFUSED: dict[str, str] = {
    "LiveJournal": (
        "LiveJournal authenticates over XML-RPC with a challenge/response login, and a "
        "failed attempt counts toward account lockout - so probing it to check a "
        "password risks locking the client out of their own account"
    ),
    "Dreamwidth": (
        "Dreamwidth uses the same XML-RPC challenge/response login as LiveJournal, with "
        "the same lockout risk on a failed probe"
    ),
    "Lemmy": (
        "Lemmy's only credential route is POST /user/login, which mints a session and "
        "counts toward its rate limiter; repeated checks would trip it for the client"
    ),
    "Plurk": (
        "Plurk signs every call with OAuth 1.0a, which needs a nonce, a timestamp and an "
        "HMAC over the request - the same purity cost as WSSE, for one platform"
    ),
    "FC2 Blog": (
        "FC2's XML-RPC endpoint answers 200 with a fault body for a bad password, and "
        "its fault codes are undocumented - so a check could not tell a rejection from "
        "an outage"
    ),
}


def request_for(platform: str, cred: dict[str, str]) -> VerifyRequest | None:
    """The profile-read for a platform, or ``None`` when we have no verifier for it.

    Every endpoint here is the platform's own "who am I" route: the cheapest call that
    proves a token is live, and one that cannot alter anything.
    """
    def g(key: str) -> str:
        return str(cred.get(key) or "").strip()

    if platform == "dev.to" and g("api_key"):
        return VerifyRequest("https://dev.to/api/users/me", {"api-key": g("api_key")})

    if platform == "Hashnode" and g("pat"):
        # GraphQL: a POST, but a read-only query - it creates nothing.
        return VerifyRequest(
            "https://gql.hashnode.com/",
            {"Authorization": g("pat"), "Content-Type": "application/json"},
            method="POST",
            json_body={"query": "{ me { id username } }"},
        )

    if platform in ("GitHub Pages", "GitHub Gist") and g("token"):
        return VerifyRequest(
            "https://api.github.com/user",
            {**_bearer(g("token")), "Accept": "application/vnd.github+json"},
        )

    if platform in ("GitLab Pages", "GitLab Snippets") and g("token"):
        return VerifyRequest("https://gitlab.com/api/v4/user", {"PRIVATE-TOKEN": g("token")})

    if platform == "WordPress.com" and g("oauth_token"):
        return VerifyRequest(
            "https://public-api.wordpress.com/rest/v1.1/me", _bearer(g("oauth_token"))
        )

    if platform == "Tumblr" and g("oauth_token"):
        return VerifyRequest("https://api.tumblr.com/v2/user/info", _bearer(g("oauth_token")))

    if platform == "Blogger" and g("oauth_token"):
        return VerifyRequest(
            "https://www.googleapis.com/blogger/v3/users/self", _bearer(g("oauth_token"))
        )

    if platform == "Ghost" and g("api_url"):
        # Ghost signs a short-lived JWT from the admin key; the publisher owns that
        # logic, so verification stops at reachability of the instance itself.
        #
        # `host_from_credential` matters MORE here than anywhere else, not less. This
        # verifier is unauthenticated, so it is a plain server-side GET to whatever host
        # the account carries - which is the textbook SSRF shape. It predates the flag
        # and was unguarded: an `api_url` of `http://169.254.169.254/` would have had
        # the server read cloud metadata and hand the body back in `detail`.
        return VerifyRequest(
            f"{_base(g('api_url'))}/ghost/api/admin/site/",
            {},
            authenticated=False,
            host_from_credential=True,
        )

    if platform == "Netlify" and g("api_token"):
        return VerifyRequest("https://api.netlify.com/api/v1/user", _bearer(g("api_token")))

    if platform == "Neocities" and g("api_key"):
        return VerifyRequest(
            "https://neocities.org/api/info", {"Authorization": f"Bearer {g('api_key')}"}
        )

    # ---------------------------------------------------------------- #
    # Fixed-host token APIs. Each URL below is the platform's own "who am I"
    # route: the cheapest authenticated read that proves a token is live.
    # ---------------------------------------------------------------- #
    if platform == "Telegra.ph" and g("access_token"):
        # Telegra.ph takes the token as a QUERY parameter, not a header. It is the one
        # verifier here that puts a secret in a URL, which matters because URLs are what
        # get logged: `interpret` never echoes the request, and the fetcher logs nothing.
        return VerifyRequest(
            f"https://api.telegra.ph/getAccountInfo?access_token={g('access_token')}"
            "&fields=%5B%22short_name%22%2C%22author_name%22%5D",
            {},
        )

    if platform == "Micro.blog" and g("token"):
        # Answers text/html, not JSON - see `VerifyRequest.expects_json`.
        return VerifyRequest(
            "https://micro.blog/account/verify", _bearer(g("token")), expects_json=False
        )

    if platform == "Mataroa" and g("api_key"):
        return VerifyRequest("https://mataroa.blog/api/posts/", _bearer(g("api_key")))

    if platform == "HackMD" and g("token"):
        return VerifyRequest("https://api.hackmd.io/v1/me", _bearer(g("token")))

    if platform == "Figshare" and g("access_token"):
        # Figshare's scheme is literally `token <value>`, not Bearer.
        return VerifyRequest(
            "https://api.figshare.com/v2/account",
            {"Authorization": f"token {g('access_token')}"},
        )

    if platform == "Zenodo" and g("access_token"):
        return VerifyRequest(
            "https://zenodo.org/api/deposit/depositions?size=1", _bearer(g("access_token"))
        )

    if platform == "OSF" and g("access_token"):
        return VerifyRequest("https://api.osf.io/v2/users/me/", _bearer(g("access_token")))

    if platform == "Notion" and g("integration_token"):
        # Notion REQUIRES a version header; without it the API 400s, which would read as
        # an inconclusive check rather than a live token.
        return VerifyRequest(
            "https://api.notion.com/v1/users/me",
            {**_bearer(g("integration_token")), "Notion-Version": "2022-06-28"},
        )

    if platform == "Webflow" and g("api_token"):
        return VerifyRequest(
            "https://api.webflow.com/v2/token/authorized_by", _bearer(g("api_token"))
        )

    if platform == "HubSpot CMS" and g("access_token"):
        return VerifyRequest(
            "https://api.hubapi.com/account-info/v3/details", _bearer(g("access_token"))
        )

    if platform == "Storyblok" and g("token") and g("space_id"):
        # Storyblok's management API takes the PAT raw in `Authorization`, no scheme.
        return VerifyRequest(
            f"https://mapi.storyblok.com/v1/spaces/{g('space_id')}",
            {"Authorization": g("token")},
        )

    if platform == "Gravatar" and g("api_token"):
        return VerifyRequest("https://api.gravatar.com/v3/me", _bearer(g("api_token")))

    if platform == "Disqus" and g("api_key") and g("access_token"):
        return VerifyRequest(
            "https://disqus.com/api/3.0/users/details.json"
            f"?api_key={g('api_key')}&access_token={g('access_token')}",
            {},
        )

    if platform == "Write.as" and g("token"):
        return VerifyRequest(
            "https://write.as/api/me", {"Authorization": f"Token {g('token')}"}
        )

    if platform == "paste.ee" and g("api_key"):
        return VerifyRequest(
            "https://api.paste.ee/v1/pastes?perpage=1", {"X-Auth-Token": g("api_key")}
        )

    if platform == "Minds" and g("access_token"):
        return VerifyRequest("https://www.minds.com/api/v2/settings", _bearer(g("access_token")))

    if platform == "Codeberg Pages" and g("token"):
        # Gitea's API, same shape as GitHub's but with Gitea's `token` scheme.
        return VerifyRequest(
            "https://codeberg.org/api/v1/user", {"Authorization": f"token {g('token')}"}
        )

    if platform == "Sourcehut Pages" and g("token"):
        return VerifyRequest(
            "https://meta.sr.ht/query",
            {**_bearer(g("token")), "Content-Type": "application/json"},
            method="POST",
            json_body={"query": "{ me { canonicalName } }"},
        )

    if platform == "Warpcast" and g("api_key") and g("signer_uuid"):
        # Neynar fronts Farcaster. Reading the signer proves BOTH halves: a bad api_key
        # is a 401, and a signer that does not belong to the key is a 404.
        return VerifyRequest(
            f"https://api.neynar.com/v2/farcaster/signer?signer_uuid={g('signer_uuid')}",
            {"api_key": g("api_key"), "x-api-key": g("api_key")},
        )

    if platform == "Internet Archive" and g("access_key") and g("secret_key"):
        # The S3-compatible endpoint accepts the keypair in one header. `check_limit=1`
        # asks only for the rate-limit status, which reads nothing and writes nothing.
        return VerifyRequest(
            "https://s3.us.archive.org/?check_limit=1",
            {"Authorization": f"LOW {g('access_key')}:{g('secret_key')}"},
        )

    if platform == "Sanity" and g("api_token") and g("project_id"):
        return VerifyRequest(
            f"https://{g('project_id')}.api.sanity.io/v1/users/me", _bearer(g("api_token"))
        )

    # ---------------------------------------------------------------- #
    # Credential-supplied hosts. `host_from_credential=True` sends these through
    # the SSRF guard in `check_credential` before anything is fetched.
    # ---------------------------------------------------------------- #
    if platform in ("Mastodon", "Pixelfed") and g("access_token"):
        # Pixelfed implements the Mastodon API, so one verifier serves both. It also
        # MIRRORS ITS PUBLISHER'S DEFAULT: `PixelfedClient` falls back to
        # pixelfed.social when no instance is given, and its account carries no
        # `instance_url` field at all. A verifier that insisted on one would report
        # "missing a field" for every correctly-configured Pixelfed account.
        instance = _base(g("instance_url")) if g("instance_url") else ""
        if not instance:
            if platform == "Mastodon":
                return None  # Mastodon has no default instance; the field is required.
            instance = "https://pixelfed.social"
        return VerifyRequest(
            f"{instance}/api/v1/accounts/verify_credentials",
            _bearer(g("access_token")),
            host_from_credential=bool(g("instance_url")),
        )

    if platform == "Misskey" and g("token"):
        # Misskey's `/api/i` is a POST that READS the current account. The token travels
        # in the body, which is how Misskey's API works - there is no header form.
        instance = _base(g("instance_url")) if g("instance_url") else "https://misskey.io"
        return VerifyRequest(
            f"{instance}/api/i",
            {"Content-Type": "application/json"},
            method="POST",
            json_body={"i": g("token")},
            host_from_credential=bool(g("instance_url")),
        )

    if platform == "Hygraph" and g("token") and g("endpoint"):
        return VerifyRequest(
            _base(g("endpoint")),
            {**_bearer(g("token")), "Content-Type": "application/json"},
            method="POST",
            json_body={"query": "{ __typename }"},
            host_from_credential=True,
        )

    if platform == "Joomla" and g("api_token") and g("base_url"):
        return VerifyRequest(
            f"{_base(g('base_url'))}/api/index.php/v1/users",
            {"X-Joomla-Token": g("api_token"), "Accept": "application/vnd.api+json"},
            host_from_credential=True,
        )

    if platform == "Drupal" and g("username") and g("password") and g("base_url"):
        import base64

        pair = base64.b64encode(
            f"{g('username')}:{g('password')}".encode()
        ).decode("ascii")
        return VerifyRequest(
            f"{_base(g('base_url'))}/jsonapi",
            {"Authorization": f"Basic {pair}", "Accept": "application/vnd.api+json"},
            host_from_credential=True,
        )

    # ---------------------------------------------------------------- #
    # AT Protocol. `createSession` mints a session rather than reading a profile,
    # because an app password has no other route - see `_SESSION_LOGIN_REFUSED`
    # for why that is an explicit decision and not a default.
    # ---------------------------------------------------------------- #
    if platform in ("Bluesky", "WhiteWind") and g("identifier") and g("app_password"):
        return VerifyRequest(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            {"Content-Type": "application/json"},
            method="POST",
            json_body={"identifier": g("identifier"), "password": g("app_password")},
        )

    return None


def interpret(
    status: int, body: str, *, authenticated: bool = True, expects_json: bool = True
) -> CredCheck:
    """Turn a response into a verdict. Pure.

    401/403 is the only signal treated as a definite rejection. A 404 or a 5xx says
    something about the endpoint or the platform's day, not about the token, so it stays
    ``unknown`` rather than being reported as a bad credential the operator would then
    go and needlessly re-issue.

    TWO WAYS A 2xx IS NOT A PASS, both of which used to read as "authenticated":

    * The request never presented the credential (``authenticated=False``). That proves
      the instance answers, nothing more - so it is ``unknown``, not ``ok``.
    * A GraphQL endpoint answers 200 with an ``errors`` array when it REJECTS the token.
      Reading only the status turns a rejection into a pass; this module's own Hashnode
      publisher already checks that array, so the check must too.
    """
    if 300 <= status < 400:
        # The API moved. Following the redirect lands on a marketing or docs page that
        # answers 200, which is how a RETIRED endpoint reads as "authenticated" - the
        # exact failure Hashnode produced when it made its GraphQL API paid-only and
        # 301'd gql.hashnode.com to an announcement page.
        return CredCheck(
            "unknown",
            f"the API endpoint redirected ({status}) - it may have moved or been "
            "retired; this check proves nothing about the credential",
        )
    if 200 <= status < 300:
        rejected = _graphql_error(body)
        if rejected:
            return CredCheck("bad", f"platform rejected the credential ({rejected})")
        if expects_json and body.strip() and not _is_json(body):
            # A JSON API that answers with HTML is not answering as an API.
            return CredCheck(
                "unknown",
                f"the endpoint returned a non-JSON body ({status}) - it is probably not "
                "the API any more; this check proves nothing about the credential",
            )
        if not authenticated:
            return CredCheck(
                "unknown",
                f"instance reachable ({status}), but this check does not present the "
                "credential - it proves nothing about whether the token works",
            )
        return CredCheck("ok", f"authenticated ({status})", _identity(body))
    if status in (401, 403):
        return CredCheck("bad", f"platform rejected the credential ({status})")
    return CredCheck("unknown", f"inconclusive response ({status})")


def _is_json(body: str) -> bool:
    """Does the body parse as JSON? Every verifier here talks to a JSON API."""
    import json as _json

    try:
        _json.loads(body)
    except (TypeError, ValueError):
        return False
    return True


def _graphql_error(body: str) -> str:
    """The first GraphQL error message in a 2xx body, or "" when there is none."""
    import json

    try:
        parsed = json.loads(body or "")
    except (TypeError, ValueError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    errors = parsed.get("errors")
    if not isinstance(errors, list) or not errors:
        return ""
    first = errors[0]
    if isinstance(first, dict):
        return str(first.get("message") or "graphql error")[:120]
    return str(first)[:120]


def _identity(body: str) -> str:
    """Best-effort 'who the platform thinks we are', for the operator's confidence."""
    import json

    try:
        data = json.loads(body)
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    for path in (("username",), ("name",), ("login",),
                 ("data", "me", "username"), ("response", "user", "name"),
                 ("site", "title")):
        node: Any = data
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, str) and node:
            return node[:60]
    return ""


def unverifiable_reason(platform: str) -> str:
    """Why this platform is not checkable, or "" when it is.

    Three different "we did not check" situations, kept apart because an operator does
    something different about each: nothing to check (`UNVERIFIABLE`), a route we chose
    not to build (`_WSSE_PLATFORMS`), and a route we chose not to CALL because calling
    it would cost the client something (`_SESSION_LOGIN_REFUSED`).
    """
    if platform in UNVERIFIABLE:
        return UNVERIFIABLE[platform]
    if platform in _WSSE_PLATFORMS:
        return (
            f"{platform} authenticates its AtomPub API with a WSSE header, which needs a "
            "nonce and a clock; no automated check is wired for it, so confirm the "
            "credential by publishing a draft"
        )
    if platform in _SESSION_LOGIN_REFUSED:
        return _SESSION_LOGIN_REFUSED[platform]
    return ""


def check_credential(
    platform: str, cred: dict[str, str], fetch: Fetcher | None
) -> CredCheck:
    """Verify one credential. Never raises."""
    if fetch is None:
        return CredCheck("unknown", "no fetcher configured")
    req = request_for(platform, cred)
    if req is None:
        # A NAMED reason beats "not built yet" wherever we have one. The distinction is
        # the operator's next action: wait for engineering, supply a missing field, or
        # accept that this platform can never be checked.
        named = unverifiable_reason(platform)
        if named:
            return CredCheck("unknown", named[:400])
        return CredCheck(
            "unknown",
            "this account is missing a field the check needs, or no verifier is wired "
            "for this platform yet",
        )
    if req.host_from_credential:
        # THE HOST CAME OUT OF THE CREDENTIAL, so the operator chose where this server
        # connects. Resolved and rejected here rather than at the fetcher, because the
        # fetcher is a thin seam the tests replace - putting the guard there would mean
        # every fake fetcher silently opted out of it.
        from app.core.security import PrivateAddressError, validate_public_host

        try:
            validate_public_host(req.url)
        except PrivateAddressError as exc:
            return CredCheck(
                "bad",
                f"this account's host is not a public address ({exc}); it is refused "
                "rather than fetched, because a check must never be pointed at "
                "internal infrastructure",
            )
        except Exception:
            return CredCheck("unknown", "this account's host could not be resolved")
    try:
        status, body = fetch(req)
    except Exception as exc:
        return CredCheck("unknown", f"request failed: {exc!r}"[:160])
    return interpret(
        status, body, authenticated=req.authenticated, expects_json=req.expects_json
    )
