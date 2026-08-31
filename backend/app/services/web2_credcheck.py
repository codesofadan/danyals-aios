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
        return VerifyRequest(
            f"{g('api_url').rstrip('/')}/ghost/api/admin/site/", {}, authenticated=False
        )

    if platform == "Netlify" and g("api_token"):
        return VerifyRequest("https://api.netlify.com/api/v1/user", _bearer(g("api_token")))

    if platform == "Neocities" and g("api_key"):
        return VerifyRequest(
            "https://neocities.org/api/info", {"Authorization": f"Bearer {g('api_key')}"}
        )

    return None


def interpret(status: int, body: str, *, authenticated: bool = True) -> CredCheck:
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
        if body.strip() and not _is_json(body):
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


def check_credential(
    platform: str, cred: dict[str, str], fetch: Fetcher | None
) -> CredCheck:
    """Verify one credential. Never raises."""
    if fetch is None:
        return CredCheck("unknown", "no fetcher configured")
    req = request_for(platform, cred)
    if req is None:
        return CredCheck("unknown", "no verifier for this platform yet")
    try:
        status, body = fetch(req)
    except Exception as exc:
        return CredCheck("unknown", f"request failed: {exc!r}"[:160])
    return interpret(status, body, authenticated=req.authenticated)
