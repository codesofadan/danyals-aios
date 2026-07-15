"""Resend email seam (7F-1): the ONLY door to transactional email.

The delivery layer (``app/services/notifications.py``) sends a notification email
exclusively through the ``EmailSender`` Protocol, so the service can hold a real
Resend client or a fake with the SAME ``send`` shape - nothing else calls the API.

Two impls satisfy the Protocol, mirroring the content / sheets seams exactly:

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


def email_sender_from_settings(settings: Settings) -> EmailSender | None:
    """A real ``ResendClient`` when ``RESEND_API_KEY`` is present, else ``None``.

    Degrades to ``None`` (never raises) when the key is absent OR no ``from`` sender
    is configured - the delivery layer then skips the email leg (in-app still lands).
    No secret is ever logged; the degraded path logs only the reason.
    """
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
