"""SMTP email seam (all-way comms): a second ``EmailSender`` behind stdlib ``smtplib``.

Mirrors the Resend seam's contract EXACTLY (the same ``EmailSender.send`` shape from
``integrations.resend``), so the delivery layer (``app/services/notifications.py``)
holds either impl interchangeably - nothing else changes. It is selected with
``EMAIL_PROVIDER=smtp`` and built by ``email_sender_from_settings``; the operator can
point it at Gmail (``smtp.gmail.com`` :587 STARTTLS, or :465 implicit SSL) or any host.

Contract, identical to ``ResendClient``:

* ``host`` + ``from_email`` are required; a blank one raises ``ProviderNotConfiguredError``
  naming the fix rather than attempting an unaddressed send (the factory avoids this by
  degrading to ``None`` when unconfigured, so a keyless deploy never crashes).
* ``user``/``password`` are optional (an open relay needs neither); when present they are
  passed to ``smtplib.login``. The password is resolved by the caller and passed here
  already extracted - it rides ONLY into ``login`` and is NEVER logged (a call failure is
  reported as ``host:port`` only, never the credential or the message body).
* a transport / auth failure raises ``ProviderCallError``; the delivery layer treats any
  send as best-effort and swallows it, so an SMTP outage can never break a mutation.
"""

from __future__ import annotations

import re
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from app.logging_setup import get_logger
from integrations.errors import ProviderCallError, ProviderNotConfiguredError

logger = get_logger("integrations.smtp_email")

_INSTALL_HINT = (
    "set SMTP_HOST + SMTP_FROM (and SMTP_USER/SMTP_PASSWORD for an authenticated relay "
    "such as Gmail) with EMAIL_PROVIDER=smtp"
)
_SSL_PORT = 465  # implicit TLS from connect; every other port uses STARTTLS
_TAG_RE = re.compile(r"<[^>]+>")


def _html_to_text(html: str) -> str:
    """A crude, dependency-free plain-text fallback from an HTML body.

    Only used when the caller supplies no explicit ``text`` alternative; strips tags
    and collapses whitespace so a text-only client still gets a readable body.
    """
    stripped = _TAG_RE.sub(" ", html)
    return " ".join(stripped.split())


class SmtpEmailSender:
    """Real ``EmailSender`` over stdlib ``smtplib`` (STARTTLS :587 / implicit SSL :465).

    Constructed with an already-extracted password (never a ``SecretStr``); the secret
    is handed only to ``smtplib.login`` and never logged. A blank ``host`` or
    ``from_email`` raises ``ProviderNotConfiguredError`` naming the fix.
    """

    provider = "smtp"

    def __init__(
        self,
        *,
        host: str,
        from_email: str,
        port: int = 587,
        user: str = "",
        password: str = "",
        timeout: float = 15.0,
    ) -> None:
        if not host:
            raise ProviderNotConfiguredError(f"SMTP client unavailable: {_INSTALL_HINT}")
        if not from_email:
            raise ProviderNotConfiguredError(f"SMTP client unavailable: {_INSTALL_HINT}")
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from = from_email
        self._timeout = timeout

    def _build(self, *, to: str, subject: str, html: str, text: str | None) -> EmailMessage:
        """Assemble a multipart/alternative message (plain-text primary + HTML)."""
        msg = EmailMessage()
        msg["From"] = self._from
        msg["To"] = to
        msg["Subject"] = subject
        msg["Message-ID"] = make_msgid()
        # Plain-text is the primary part (a text-only client reads it); the HTML rides
        # as the richer alternative. When no explicit text was given, derive one.
        msg.set_content(text if text is not None else _html_to_text(html))
        if html:
            msg.add_alternative(html, subtype="html")
        return msg

    def _deliver(self, smtp: smtplib.SMTP, msg: EmailMessage) -> None:
        """Authenticate (when credentialed) and hand the message to the server."""
        if self._user and self._password:
            smtp.login(self._user, self._password)
        smtp.send_message(msg)

    def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> str:
        msg = self._build(to=to, subject=subject, html=html, text=text)
        try:
            if self._port == _SSL_PORT:
                with smtplib.SMTP_SSL(self._host, self._port, timeout=self._timeout) as smtp:
                    self._deliver(smtp, msg)
            else:
                with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
                    smtp.starttls()  # upgrade the plaintext connection before auth
                    self._deliver(smtp, msg)
        except (OSError, smtplib.SMTPException) as exc:
            # host:port only - the password + message body are never part of this line.
            raise ProviderCallError(f"SMTP send failed via {self._host}:{self._port}") from exc
        return str(msg["Message-ID"] or "")
