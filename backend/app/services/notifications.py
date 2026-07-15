"""Delivery layer (7F-1): in-app notifications + staff alerts + best-effort email/Slack.

The sibling of ``app/services/activity.py``. Where ``record_activity`` appends one
audit row, ``notify`` delivers one notification and ``raise_alert`` raises one staff
alert. Both are BEST-EFFORT (never raise) - exactly like ``record_activity`` - so a
delivery hiccup (an unreachable pool, a keyless email provider, a Slack outage) can
never fail the mutation that triggered it.

Both write on the PRIVILEGED (service_role, BYPASSRLS) pool, like ``log_activity``,
and for the same reason: a notification/alert is addressed to SOMEONE ELSE than the
actor, so its write must not be gated by the actor's RLS identity - and reading the
RECIPIENT's ``notification_prefs`` (0025; RLS-scoped to ``auth.uid()``) likewise needs
service_role.

Delivery honours the recipient's ``notification_prefs`` (0025 / ``NOTIF_EVENTS``):
when ``kind`` matches a known event key the stored (or default) ``email``/``in_app``
toggles govern which legs fire; an UNKNOWN ``kind`` (e.g. an alert type) delivers
IN-APP ONLY (never email) - alerts escalate loudly via the optional Slack webhook, not
by emailing every lead. The email leg is additionally KEY-GATED: with no
``RESEND_API_KEY`` it is simply skipped and the in-app row still lands.
"""

from __future__ import annotations

import asyncio
from html import escape as html_escape
from typing import Any

from app.config import get_settings
from app.db.database import privileged_connection
from app.logging_setup import get_logger
from app.schemas.settings import NOTIF_EVENTS
from integrations.resend import EmailSender, email_sender_from_settings
from integrations.slack import SlackNotifier, slack_notifier_from_settings

logger = get_logger("app.notifications")

# The default email/in_app toggle per known event (NOTIF_EVENTS is the catalogue).
_DEFAULT_PREFS: dict[str, tuple[bool, bool]] = {
    str(e["key"]): (bool(e["email"]), bool(e["in_app"])) for e in NOTIF_EVENTS
}
# An unknown kind (e.g. an alert type) delivers in-app only - never email.
_UNKNOWN_KIND_PREF: tuple[bool, bool] = (False, True)

# The lead roles that own the alert queue (read + acknowledge). Alerts notify these.
_LEAD_ROLES = ("owner", "admin", "manager")

# Human labels for the alert taxonomy (public.alert_type), used in the notification
# title + Slack line.
_ALERT_LABELS: dict[str, str] = {
    "rank_drop": "Rank drop",
    "lost_link": "Lost backlink",
    "budget": "Budget alert",
}


# --------------------------------------------------------------------------- #
# Preference resolution
# --------------------------------------------------------------------------- #
def _resolve_pref(cur: Any, user_id: str, event_key: str) -> tuple[bool, bool]:
    """The recipient's ``(email, in_app)`` toggles for ``event_key``.

    A stored ``notification_prefs`` row wins; otherwise the ``NOTIF_EVENTS`` default;
    an unknown event key falls back to in-app-only. Read on the caller's privileged
    cursor (service_role) because the row belongs to the RECIPIENT, not the actor.
    """
    default_email, default_in_app = _DEFAULT_PREFS.get(event_key, _UNKNOWN_KIND_PREF)
    cur.execute(
        "select email, in_app from public.notification_prefs "
        "where user_id = %s and event_key = %s",
        (user_id, event_key),
    )
    row = cur.fetchone()
    if not row:
        return default_email, default_in_app
    email = row.get("email")
    in_app = row.get("in_app")
    return (
        bool(email) if email is not None else default_email,
        bool(in_app) if in_app is not None else default_in_app,
    )


# --------------------------------------------------------------------------- #
# In-app notification
# --------------------------------------------------------------------------- #
def _persist_notification(
    user_id: str, kind: str, title: str, body: str
) -> tuple[bool, str] | None:
    """Resolve prefs + (if in-app enabled) write the notification row. Blocking.

    Returns ``(email_enabled, recipient_email)`` so the async caller can fire the
    email leg, or ``None`` when the recipient is unknown (nothing to deliver).
    """
    with privileged_connection() as cur:
        cur.execute("select email from public.users where id = %s", (user_id,))
        urow = cur.fetchone()
        if not urow:
            return None
        address = str(urow.get("email") or "")
        email_enabled, in_app_enabled = _resolve_pref(cur, user_id, kind)
        if in_app_enabled:
            cur.execute(
                "insert into public.notifications (user_id, kind, title, body) "
                "values (%s, %s, %s, %s)",
                (user_id, kind, title, body),
            )
        return email_enabled, address


def _email_html(title: str, body: str) -> str:
    """A minimal, injection-safe HTML body (values escaped; server-generated anyway)."""
    return f"<h2>{html_escape(title)}</h2><p>{html_escape(body)}</p>"


async def notify(
    user_id: str,
    kind: str,
    title: str,
    body: str = "",
    *,
    email_sender: EmailSender | None = None,
) -> None:
    """Best-effort: deliver one notification to ``user_id``. Never raises.

    Honours the recipient's ``notification_prefs`` for ``kind``: writes an in-app row
    when ``in_app`` is enabled, and sends an email when ``email`` is enabled AND an
    email provider is configured (key-gated; ``email_sender`` may be injected, else it
    is built from settings). A missing recipient, a keyless provider, or a send failure
    are all swallowed to a warning - delivery can never break the caller's mutation.
    """
    try:
        result = await asyncio.to_thread(_persist_notification, user_id, kind, title, body)
    except Exception:
        logger.warning("notify_failed", kind=kind)
        return
    if result is None:
        return  # unknown recipient
    email_enabled, address = result
    if not email_enabled or not address:
        return
    sender = email_sender if email_sender is not None else email_sender_from_settings(get_settings())
    if sender is None:
        return  # keyless -> email leg skipped (in-app already landed)
    try:
        await asyncio.to_thread(
            sender.send, to=address, subject=title, html=_email_html(title, body), text=body
        )
    except Exception:
        logger.warning("notify_email_failed", kind=kind)


# --------------------------------------------------------------------------- #
# Staff alert
# --------------------------------------------------------------------------- #
def _persist_alert(
    client_id: str, type_: str, severity: str, detail: str
) -> tuple[str, list[str]] | None:
    """Write the alert row + return ``(client_name, lead_user_ids)``. Blocking.

    Returns ``None`` when the client is unknown (an alert without its client is
    meaningless). The lead ids are the active owner/admin/manager users the alert
    should notify. ``type_`` is cast to the ``alert_type`` enum in SQL.
    """
    with privileged_connection() as cur:
        cur.execute("select name from public.clients where id = %s", (client_id,))
        crow = cur.fetchone()
        if not crow:
            return None
        client_name = str(crow.get("name") or "")
        cur.execute(
            "insert into public.alerts (client_id, type, severity, detail) "
            "values (%s, %s::public.alert_type, %s, %s)",
            (client_id, type_, severity, detail),
        )
        cur.execute(
            "select id from public.users "
            "where role in ('owner', 'admin', 'manager') and status <> 'invited'",
        )
        lead_ids = [str(r["id"]) for r in cur.fetchall()]
    return client_name, lead_ids


def _alert_title(type_: str, client_name: str) -> str:
    """The notification/Slack title for an alert (label + client)."""
    label = _ALERT_LABELS.get(type_, "Alert")
    return f"{label}: {client_name}" if client_name else label


async def raise_alert(
    client_id: str,
    type: str,  # the module contract names this arg `type` (the alert taxonomy)
    severity: str,
    detail: str,
    *,
    email_sender: EmailSender | None = None,
    slack: SlackNotifier | None = None,
) -> None:
    """Best-effort: raise a staff alert + notify the leads who own the queue. Never raises.

    Writes the alert row, then delivers an in-app notification to every active lead
    (owner/admin/manager) and posts a one-line escalation to Slack when a webhook is
    configured (key-gated; ``slack`` may be injected). An unknown client, an
    unreachable pool, or a Slack outage are all swallowed to a warning - raising an
    alert can never break the caller's mutation.
    """
    try:
        context = await asyncio.to_thread(_persist_alert, client_id, type, severity, detail)
    except Exception:
        logger.warning("raise_alert_failed", type=type)
        return
    if context is None:
        return  # unknown client
    client_name, lead_ids = context
    title = _alert_title(type, client_name)

    for uid in lead_ids:
        # kind = the alert type: it is NOT a NOTIF_EVENTS key, so it delivers in-app
        # only (never email) - the loud escalation channel is Slack, below.
        await notify(uid, kind=type, title=title, body=detail, email_sender=email_sender)

    notifier = slack if slack is not None else slack_notifier_from_settings(get_settings())
    if notifier is None:
        return
    try:
        await asyncio.to_thread(notifier.post, f"[{severity}] {title} - {detail}")
    except Exception:
        logger.warning("raise_alert_slack_failed", type=type)
