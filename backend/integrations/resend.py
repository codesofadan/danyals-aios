"""Resend email seam (7F-1) + the ``EmailSender`` Protocol and the shared factory.

The delivery layer (``app/services/notifications.py``) sends a notification email
exclusively through the ``EmailSender`` Protocol, so the service can hold a real
Resend client, an SMTP client (``integrations.smtp_email``), or a fake - all with the
SAME ``send`` shape. ``email_sender_from_settings`` is the single factory every call
site uses; it dispatches on ``EMAIL_PROVIDER`` (``resend`` | ``smtp`` | ``none``), so
switching the whole platform to Gmail SMTP is one env var, no code change.

Two impls satisfy the Protocol here (a third, ``SmtpEmailSender``, lives alongside),
mirroring the content / sheets seams exactly:

* ``ResendClient`` - real, backed by the Resend REST API over the shared
  ``HttpProviderClient`` (retry + secret-safe error logging). KEY-GATED on
  ``RESEND_API_KEY`` (+ a verified ``RESEND_FROM_EMAIL`` sender); the key rides in an
  ``Authorization`` header and is NEVER logged. Absent key -> ``ProviderNotConfiguredError``
  naming the fix (the factory avoids this by degrading to ``None`` keyless).
* ``FakeEmailSender`` - deterministic, in-memory: records every send and returns a
  stable synthetic message id, so the notify() email-path tests run with zero keys.

``email_sender_from_settings`` returns a real client when the key is present and
degrades to ``None`` otherwise - the service then skips the email leg (in-app still
lands) until the key arrives, exactly as the SheetStore holds without its credential.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.logging_setup import get_logger
from integrations.errors import ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient
from integrations.smtp_email import SmtpEmailSender

if TYPE_CHECKING:
    from app.config import Settings

logger = get_logger("integrations.resend")

_INSTALL_HINT = "set RESEND_API_KEY (and RESEND_FROM_EMAIL to a verified sender)"
# Resend REST base + the transactional-send endpoint.
_BASE_URL = "https://api.resend.com"
_SEND_PATH = "/emails"


@runtime_checkable
class EmailSender(Protocol):
    """Send one transactional email, returning the provider message id.

    ``html`` is the rendered body; ``text`` is an optional plain-text alternative.
    Raises ``ProviderCallError`` on a non-transient provider rejection (the caller
    in the delivery layer treats any failure as best-effort and swallows it).
    """

    def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> str: ...


class ResendClient:
    """Real ``EmailSender`` backed by Resend's REST API (Bearer-key auth).

    The key is resolved by the caller and passed here already extracted; it rides in
    the ``Authorization`` header (never a URL, never logged). A blank key raises
    ``ProviderNotConfiguredError`` naming the fix rather than sending unauthenticated.
    """

    provider = "resend"

    def __init__(self, *, api_key: str, from_email: str, timeout: float = 15.0) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"Resend client unavailable: {_INSTALL_HINT}")
        if not from_email:
            raise ProviderNotConfiguredError(f"Resend client unavailable: {_INSTALL_HINT}")
        self._from = from_email
        # The shared sync client owns retry/backoff + stripped-path error logging; the
        # key is sealed into the Authorization header and never echoed.
        self._http = HttpProviderClient(
            base_url=_BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> str:
        body: dict[str, object] = {
            "from": self._from,
            "to": [to],
            "subject": subject,
            "html": html,
        }
        if text is not None:
            body["text"] = text
        payload = self._http.request_json("POST", _SEND_PATH, json_body=body)
        return str(payload.get("id", ""))


@dataclass
class SentEmail:
    """One captured send (FakeEmailSender), for assertions in the notify() tests."""

    to: str
    subject: str
    html: str
    text: str | None = None


@dataclass
class FakeEmailSender:
    """Deterministic, offline ``EmailSender`` for the delivery-layer unit tests.

    Every ``send`` is appended to ``sent`` and returns a stable ``fake-email-<n>``
    id, so a test can prove the email leg fired (or did not) with zero network/keys.
    """

    sent: list[SentEmail] = field(default_factory=list)

    def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> str:
        self.sent.append(SentEmail(to=to, subject=subject, html=html, text=text))
        return f"fake-email-{len(self.sent)}"


def _smtp_sender_from_settings(settings: Settings) -> EmailSender | None:
    """A real ``SmtpEmailSender`` when ``SMTP_HOST`` is set, else ``None`` (degraded).

    The From: header falls back to ``SMTP_USER`` when ``SMTP_FROM`` is blank; the
    password (a Gmail app-password) is extracted here and passed already-revealed - it
    is never logged. A blank host degrades to ``None`` (the email leg is skipped),
    mirroring the keyless Resend path.
    """
    if not settings.smtp_host:
        logger.info("email_sender_degraded", reason="missing_smtp_host")
        return None
    password = (
        settings.smtp_password.get_secret_value() if settings.smtp_password else ""
    )
    from_email = settings.smtp_from or settings.smtp_user
    try:
        return SmtpEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            user=settings.smtp_user,
            password=password,
            from_email=from_email,
        )
    except ProviderNotConfiguredError as exc:
        logger.info("email_sender_degraded", reason=str(exc))
        return None


def email_sender_from_settings(settings: Settings) -> EmailSender | None:
    """The configured ``EmailSender`` (Resend or SMTP), or ``None`` when degraded.

    Dispatches on ``EMAIL_PROVIDER``: ``"smtp"`` builds an ``SmtpEmailSender`` (Gmail /
    any host), ``"none"`` disables the email leg outright, and ``"resend"`` (the
    default) builds a ``ResendClient``. EVERY path degrades to ``None`` (never raises)
    when its credential/host is absent - the delivery layer then skips the email leg
    (in-app still lands). No secret is ever logged; the degraded path logs only the
    reason.
    """
    provider = settings.email_provider
    if provider == "none":
        logger.info("email_sender_degraded", reason="provider_none")
        return None
    if provider == "smtp":
        return _smtp_sender_from_settings(settings)
    key = settings.resend_api_key
    if not key:
        logger.info("email_sender_degraded", reason="missing_key")
        return None
    try:
        return ResendClient(
            api_key=key.get_secret_value(), from_email=settings.resend_from_email
        )
    except ProviderNotConfiguredError as exc:
        logger.info("email_sender_degraded", reason=str(exc))
        return None
