"""Serve a CURRENT OAuth access token to the Web 2.0 publishers - refreshing and
re-sealing as needed.

THE DEFECT THIS CLOSES (live, measured): the Blogger connect flow sealed the REFRESH
token and the publisher sent it verbatim as a Bearer header -> 401 on every publish.
The other honest option - sealing the access token - dies within the hour instead.
Neither single string can work, which is why ``web2_oauth.credential_from_tokens``
now seals a BUNDLE {access_token, refresh_token, expires_at, token_type} and this
service turns that bundle into a working bearer at publish time:

* bundle still fresh (>5 min margin, or no expiry at all) -> hand back the sealed
  access token, no network;
* bundle stale -> POST the platform's refresh grant (client id/secret from settings,
  ``web2_oauth.refresh_payload``), RE-SEAL the updated bundle in place on the
  privileged connection (same vault row, same provider/label), return the new token;
* legacy single-string credential, detected BY SHAPE: a Google-style refresh token
  (the ``1//`` prefix Blogger rows carry) is treated as the refresh half of a bundle
  and upgraded on first use; anything else is a non-expiring PAT and passes through
  UNTOUCHED - rewriting a working WordPress.com token would be repair-by-guess.

HONEST DEGRADATION. A FAILED refresh cannot be papered over with the stale token (it
would just 401 downstream and look like a platform fault). It returns ``None`` - the
publish pipeline HOLDS the placement at needs_review exactly as if the platform were
unconfigured - and this service records what actually happened: the account's health
drops to ``degraded`` (the taxonomy's honest label for "reachable but wrong"; the
CHECK vocabulary deliberately gains no new value), a loud log names the account, and
the lead-notification seam fires with the durable fix - for Blogger that is a USER
action, publishing the Google consent screen to Production, because a Testing-mode
consent screen kills refresh tokens every 7 days and no amount of server code can
out-refresh that.

Every seam (settings, vault lookup, the token POST, the reseal, the clock) is
injectable so the whole decision path unit-tests with zero network and zero vault.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import get_settings
from app.db.database import privileged_connection
from app.logging_setup import get_logger
from app.services.vault import find_secret, mask_secret, seal_value
from app.services.web2_oauth import (
    SPECS,
    parse_token_bundle,
    refresh_payload,
    spec_for,
    token_expires_at,
)

logger = get_logger("app.services.web2_token_refresh")

#: The platforms whose vault credential carries an OAuth bundle (everything with an
#: OAuth spec). The publish worker routes exactly these through `refreshing_lookup`;
#: every other platform's credential is a plain PAT/password the vault serves as-is.
OAUTH_BUNDLE_PLATFORMS: frozenset[str] = frozenset(SPECS)

#: How much life an access token must have LEFT to be served without a refresh. Five
#: minutes: long enough that the token cannot expire mid-publish, short enough that
#: we are not refreshing on every call.
REFRESH_MARGIN = timedelta(minutes=5)

#: Google refresh tokens have carried this prefix for years - it is the shape test
#: that identifies a legacy Blogger row (a bare refresh token sealed by the pre-
#: bundle connect flow) without a version marker.
_GOOGLE_REFRESH_PREFIX = "1//"

#: (url, form) -> parsed JSON token response. Raises on any failure.
PostForm = Callable[[str, dict[str, str]], dict[str, Any]]
#: (provider, label, secret) -> None. Re-seals the credential row in place.
Reseal = Callable[..., None]


@dataclass(frozen=True)
class OAuthAccountRef:
    """The coordinates of one OAuth-backed publishing credential.

    ``vault_label`` is the vault row's label (a ``web2_accounts.id``, or a legacy
    client id for pre-accounts rows); ``account_id`` is the REAL account row when one
    exists - it is where a failed refresh records ``degraded``, and it is empty for
    legacy-labelled rows that have no account to degrade (the log + notification
    still fire)."""

    platform: str
    vault_label: str
    account_id: str = ""

    @property
    def vault_provider(self) -> str:
        return f"web2:{self.platform}"


# --------------------------------------------------------------------------- #
# Default seams (real network / real vault). Injected everywhere in tests.
# --------------------------------------------------------------------------- #
def _post_form(url: str, form: dict[str, str]) -> dict[str, Any]:
    """POST the refresh grant. Raises on any failure; NEVER logs the body or the
    form - both can echo the client secret or a token."""
    import httpx

    resp = httpx.post(url, data=form, timeout=20.0)
    if resp.status_code >= 400:
        raise RuntimeError(f"token refresh failed with status {resp.status_code}")
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError("token refresh returned an unexpected body")
    return payload


def _reseal_vault_row(*, provider: str, label: str, secret: str) -> None:
    """Re-seal the NEWEST (provider, label) vault row in place - the same row
    ``find_secret`` reads, so the refreshed bundle supersedes without a second row
    accumulating per refresh. Runs on the privileged connection like every vault
    write; the plaintext exists only long enough to seal."""
    sealed = seal_value(secret)
    with privileged_connection() as cur:
        cur.execute(
            "update public.vault_keys "
            "set secret_sealed = %s, masked = %s, updated_at = now() "
            "where id = (select id from public.vault_keys "
            "            where provider = %s and label = %s "
            "            order by created_at desc limit 1)",
            (sealed, mask_secret(secret), provider, label),
        )


def _degrade_account(account_id: str) -> None:
    """Record a failed refresh on the account row: ``degraded`` is the taxonomy's
    label for reachable-but-wrong, and the CHECK deliberately gains no 'expired'
    value - the health vocabulary is closed, and this state IS a degradation."""
    with privileged_connection() as cur:
        cur.execute(
            "update public.web2_accounts "
            "set health = 'degraded', health_checked_at = now() where id = %s",
            (account_id,),
        )


def _stale(expires_at: str, now: datetime) -> bool:
    """Whether a bundle's access token is within the refresh margin of expiry.

    An EMPTY expiry means the platform does not expire its tokens - never stale. An
    unparseable one is treated as stale: refreshing a token we cannot reason about
    is the safe direction, serving it is not."""
    text = (expires_at or "").strip()
    if not text:
        return False
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment <= now + REFRESH_MARGIN


def _refresh_failed(account: OAuthAccountRef, reason: str) -> None:
    """A refresh failed: degrade the account, log LOUDLY, tell a lead the durable
    fix. Best-effort on every leg - reporting a failure must never add one."""
    logger.error(
        "web2_oauth_refresh_failed",
        platform=account.platform,
        account_id=account.account_id or account.vault_label,
        reason=reason,
    )
    if account.account_id:
        try:
            _degrade_account(account.account_id)
        except Exception:
            logger.warning("web2_oauth_degrade_write_failed", account_id=account.account_id)
    try:
        from app.services.notifications import notify_leads_sync
    except Exception:
        return
    fix = (
        "Publish the Google consent screen to Production (Testing-mode refresh tokens "
        "die every 7 days), or reconnect the account from the Web 2.0 board."
        if account.platform == "Blogger"
        else "Reconnect the account from the Web 2.0 board."
    )
    try:
        notify_leads_sync(
            "web2_oauth",
            f"{account.platform} publishing credential expired",
            f"The {account.platform} OAuth token could not be refreshed ({reason}). "
            f"Publishing is held, the account is marked degraded. {fix}",
        )
    except Exception:
        logger.warning("web2_oauth_refresh_notify_failed", platform=account.platform)


# --------------------------------------------------------------------------- #
# The core decision path (pure given its seams).
# --------------------------------------------------------------------------- #
def _resolve_credential(
    account: OAuthAccountRef,
    raw: str,
    *,
    settings: Any,
    post: PostForm,
    reseal: Reseal,
    now: datetime,
) -> tuple[str | None, str]:
    """(credential JSON whose token field is a CURRENT plain bearer, that bearer).

    ``(None, "")`` means an expiring credential could not be refreshed - the caller
    must HOLD, not guess. A credential this service has no opinion on (malformed
    JSON, an empty token field, a non-expiring PAT) is returned UNCHANGED so the
    publisher factory applies its own existing refusal/pass-through rules.
    """
    try:
        creds = json.loads(raw)
    except (TypeError, ValueError):
        return (raw, "")  # build_publisher owns the malformed-credential refusal
    if not isinstance(creds, dict):
        return (raw, "")
    spec = spec_for(account.platform)
    token_field = spec.token_field if spec else "oauth_token"
    value = str(creds.get(token_field) or "")
    if not value:
        return (raw, "")  # the constructor's own required-field guard refuses this

    bundle = parse_token_bundle(value)
    if bundle is None:
        if not value.startswith(_GOOGLE_REFRESH_PREFIX):
            # A legacy non-expiring PAT (WordPress.com bearer, a hand-pasted token).
            # It works as-is today; rewriting it would be repair-by-guess.
            return (raw, value)
        # A legacy Blogger-style row: the bare REFRESH token the old connect flow
        # sealed. Sending it as a Bearer is the 401 defect - treat it as the refresh
        # half of a bundle and upgrade the row on this first use.
        bundle = {
            "access_token": "",
            "refresh_token": value,
            "expires_at": "",
            "token_type": "Bearer",
        }
        # Force the refresh below: there is no access token to serve.
        bundle["expires_at"] = (now - timedelta(seconds=1)).isoformat()

    access = bundle.get("access_token") or ""
    if access and not _stale(bundle.get("expires_at") or "", now):
        # Fresh enough: no network, no reseal. The builder still needs a PLAIN
        # bearer, so the bundle is unwrapped for the returned credential only.
        return (json.dumps({**creds, token_field: access}), access)

    refresh_token = bundle.get("refresh_token") or ""
    if not refresh_token:
        _refresh_failed(account, "access token expired and no refresh token is sealed")
        return (None, "")
    url, form = refresh_payload(account.platform, settings, refresh_token=refresh_token)
    if not url:
        _refresh_failed(account, "no OAuth app is registered for this platform")
        return (None, "")
    try:
        tokens = post(url, form)
    except Exception as exc:
        _refresh_failed(account, f"{type(exc).__name__}: {exc}")
        return (None, "")
    new_access = str(tokens.get("access_token") or "")
    if not new_access:
        _refresh_failed(account, "refresh response carried no access_token")
        return (None, "")

    new_bundle = {
        "access_token": new_access,
        # Some platforms rotate the refresh token on use (Tumblr); Google does not
        # return one at all on refresh. Keep the old one unless a new one arrived.
        "refresh_token": str(tokens.get("refresh_token") or "") or refresh_token,
        "expires_at": token_expires_at(tokens),
        "token_type": str(tokens.get("token_type") or "Bearer"),
    }
    try:
        reseal(
            provider=account.vault_provider,
            label=account.vault_label,
            secret=json.dumps({**creds, token_field: json.dumps(new_bundle)}),
        )
    except Exception:
        # The token in hand is real and this publish should use it; the next run
        # simply refreshes again. Logged so a persistently failing reseal is visible.
        logger.warning(
            "web2_oauth_reseal_failed",
            platform=account.platform, vault_label=account.vault_label,
        )
    logger.info("web2_oauth_refreshed", platform=account.platform)
    return (json.dumps({**creds, token_field: new_access}), new_access)


# --------------------------------------------------------------------------- #
# Public API.
# --------------------------------------------------------------------------- #
def fresh_access_token(
    account: OAuthAccountRef,
    *,
    settings: Any = None,
    lookup: Callable[..., str | None] = find_secret,
    post: PostForm = _post_form,
    reseal: Reseal = _reseal_vault_row,
    now: datetime | None = None,
) -> str | None:
    """A CURRENT bearer token for this account, or ``None`` when there is none to
    have (no credential sealed, or an expiring one whose refresh failed - the
    failure path has already degraded/logged/notified by the time this returns)."""
    raw = lookup(provider=account.vault_provider, label=account.vault_label)
    if raw is None:
        return None
    _cred, token = _resolve_credential(
        account, raw,
        settings=settings or get_settings(), post=post, reseal=reseal,
        now=now or datetime.now(UTC),
    )
    return token or None


def refreshing_lookup(
    *,
    platform: str,
    account_id: str = "",
    settings: Any = None,
    base: Callable[..., str | None] = find_secret,
    post: PostForm = _post_form,
    reseal: Reseal = _reseal_vault_row,
    now: datetime | None = None,
) -> Callable[..., str | None]:
    """A drop-in ``SecretLookup`` for ``build_publisher`` that guarantees the OAuth
    token field it hands back is a current PLAIN bearer.

    Same shape as ``find_secret`` (keyword ``provider``/``label``), so the publisher
    factory does not know refresh exists. ``None`` on a failed refresh makes the
    publish HOLD at review - the same honest degradation as a missing credential."""

    def lookup(*, provider: str, label: str) -> str | None:
        raw = base(provider=provider, label=label)
        if raw is None:
            return None
        cred, _token = _resolve_credential(
            OAuthAccountRef(platform=platform, vault_label=label, account_id=account_id),
            raw,
            settings=settings or get_settings(), post=post, reseal=reseal,
            now=now or datetime.now(UTC),
        )
        return cred

    return lookup


__all__ = [
    "OAUTH_BUNDLE_PLATFORMS",
    "REFRESH_MARGIN",
    "OAuthAccountRef",
    "fresh_access_token",
    "refreshing_lookup",
]
