"""Privileged operations for the multi-client WordPress Connections registry.

Mirrors the Key Vault seam (app/services/vault.py): the raw credential is sealed
app-layer with AES-256-GCM under ``VAULT_MASTER_KEY`` (reusing ``seal_value`` /
``open_sealed`` verbatim, so there is ONE sealing construction and ONE master key)
and written/read on ``privileged_connection`` (role ``service_role``). The sealed
bytea NEVER leaves the server: the upsert returns only masked metadata, and the one
place a plaintext credential is opened is the server-side publish/test path here.

The three auth methods map to the three publish adapters:

* ``plugin``       - the AIOS Publisher plugin endpoint + a shared ``api_key``
  (``integrations.wordpress_publisher``); the primary, host-independent path.
* ``xmlrpc``       - ``POST /xmlrpc.php`` ``wp.newPost`` with username+password in
  the body (``integrations.wordpress.XmlRpcWordPressPublisher``); the path that
  works on hostile managed hosts that strip auth headers / disable app passwords.
* ``app_password`` - the WP REST v2 API over HTTP Basic
  (``integrations.wordpress.WordPressClient``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.db.database import privileged_connection
from app.logging_setup import get_logger
from app.services.vault import open_sealed, seal_value

logger = get_logger("services.wp_connections")

# Read columns that are safe to return to a client (the sealed secret is EXCLUDED).
_META_COLS = "client_id, site_url, auth_method, username, status, last_tested_at"


@dataclass(frozen=True)
class ResolvedWpConnection:
    """A client's connection with its credential OPENED (server-only).

    Built only on the publish/test path; never serialized to the wire. ``secret`` is
    the plugin api_key (``plugin``) or the password (``xmlrpc`` / ``app_password``).
    """

    client_id: str
    site_url: str
    auth_method: str
    username: str
    secret: str


def upsert_connection(
    *,
    client_id: str,
    site_url: str,
    auth_method: str,
    username: str,
    secret: str | None,
) -> dict[str, Any] | None:
    """Insert or replace a client's connection; returns MASKED metadata (no secret).

    ``secret`` is sealed when provided; when ``None`` (a metadata-only edit) the
    stored ``secret_sealed`` is left unchanged via ``coalesce(excluded, existing)``,
    so changing just the site URL never wipes the credential. The masked metadata
    read-back never selects the sealed bytea.
    """
    sealed = seal_value(secret) if secret is not None else None
    with privileged_connection() as cur:
        cur.execute(
            "insert into public.wp_connections "
            "(client_id, site_url, auth_method, username, secret_sealed) "
            "values (%s, %s, %s, %s, %s) "
            "on conflict (client_id) do update set "
            "  site_url = excluded.site_url, "
            "  auth_method = excluded.auth_method, "
            "  username = excluded.username, "
            "  secret_sealed = coalesce(excluded.secret_sealed, public.wp_connections.secret_sealed), "
            "  updated_at = now() "
            f"returning {_META_COLS}, (secret_sealed is not null) as configured",
            (client_id, site_url, auth_method, username, sealed),
        )
        return cur.fetchone()


def delete_connection(client_id: str) -> bool:
    """Remove a client's connection (best-effort); True when a row was deleted."""
    with privileged_connection() as cur:
        cur.execute(
            "delete from public.wp_connections where client_id = %s returning client_id",
            (client_id,),
        )
        return cur.fetchone() is not None


def set_status(client_id: str, status: str) -> dict[str, Any] | None:
    """Record the latest connectivity-test verdict + last_tested_at; masked read-back."""
    with privileged_connection() as cur:
        cur.execute(
            "update public.wp_connections set status = %s, last_tested_at = now() "
            f"where client_id = %s returning {_META_COLS}, (secret_sealed is not null) as configured",
            (status, client_id),
        )
        return cur.fetchone()


def resolve_connection(client_id: str) -> ResolvedWpConnection | None:
    """Load a client's connection with its credential OPENED (server-only), or None.

    Returns None when there is no connection row OR no sealed credential yet (an
    unconfigured client). A malformed/tampered blob surfaces as a ``VaultSecretError``
    from ``open_sealed`` - the caller (publish/test) catches it and degrades.
    """
    with privileged_connection() as cur:
        cur.execute(
            "select site_url, auth_method, username, secret_sealed "
            "from public.wp_connections where client_id = %s limit 1",
            (client_id,),
        )
        row = cur.fetchone()
    if row is None or row.get("secret_sealed") is None:
        return None
    secret = open_sealed(row["secret_sealed"])
    return ResolvedWpConnection(
        client_id=str(client_id),
        site_url=str(row.get("site_url") or ""),
        auth_method=str(row.get("auth_method") or "plugin"),
        username=str(row.get("username") or ""),
        secret=secret,
    )


def verify_connection(conn: ResolvedWpConnection, settings: Settings) -> tuple[bool, str]:
    """Probe the REAL site with the resolved credential; returns ``(ok, detail)``.

    Non-raising: any construction/network/auth error is a clean ``(False, reason)``
    so the UI can show a red/green without a 500. Sends a browser User-Agent on every
    method (managed hosts' anti-bot layers block non-browser UAs).
    """
    site_url = conn.site_url.strip()
    if not site_url:
        return False, "No site URL configured for this connection"
    ua = settings.wp_connection_browser_ua
    timeout = settings.wp_connection_timeout_seconds
    try:
        if conn.auth_method == "plugin":
            from integrations.wordpress_publisher import WordPressPluginPublisher

            ok = WordPressPluginPublisher(
                site_url=site_url, api_key=conn.secret, user_agent=ua, timeout=timeout
            ).ping()
            return (True, "Reached the AIOS Publisher plugin and the key was accepted") if ok else (
                False,
                "The plugin did not respond OK (check the site URL + api key + plugin install)",
            )
        if conn.auth_method == "xmlrpc":
            from integrations.wordpress import XmlRpcWordPressPublisher

            return XmlRpcWordPressPublisher(
                username=conn.username, app_password=conn.secret, user_agent=ua, timeout=timeout
            ).verify(site_url)
        if conn.auth_method == "app_password":
            from integrations.wordpress import WordPressClient

            return WordPressClient(
                username=conn.username, app_password=conn.secret, user_agent=ua, timeout=timeout
            ).verify(site_url)
    except Exception as exc:  # never raise out of a connectivity probe
        logger.warning("wp_connection_verify_error", method=conn.auth_method)
        return False, f"Connection failed: {type(exc).__name__}"
    return False, f"Unknown auth method: {conn.auth_method}"


def test_connection(client_id: str, settings: Settings) -> tuple[bool, str, dict[str, Any] | None]:
    """Resolve + probe a client's connection and record the verdict.

    Returns ``(ok, detail, updated_metadata)``. An unconfigured client (no row / no
    credential) is ``(False, reason, None)`` with no status write. A tested one gets
    ``status`` set to ``connected`` / ``failed`` + ``last_tested_at`` bumped.
    """
    try:
        conn = resolve_connection(client_id)
    except Exception:
        logger.warning("wp_connection_resolve_failed", client_id=str(client_id))
        return False, "Could not open the stored credential (re-save the connection)", None
    if conn is None:
        return False, "No WordPress credential configured for this client yet", None
    ok, detail = verify_connection(conn, settings)
    updated = set_status(client_id, "connected" if ok else "failed")
    return ok, detail, updated
