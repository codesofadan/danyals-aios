"""Slack incoming-webhook seam (7F-1): the optional door to a Slack channel ping.

The delivery layer posts a one-line summary of a raised ALERT to Slack (rank-drop /
lost-link / budget) exclusively through the ``SlackNotifier`` Protocol, so the
service can hold a real webhook client or a fake with the SAME ``post`` shape.

Two impls satisfy the Protocol, mirroring the resend / sheets seams:

* ``SlackWebhookClient`` - real, POSTs ``{"text": ...}`` to an incoming-webhook URL.
  KEY-GATED on ``SLACK_WEBHOOK_URL`` (the URL itself is the secret - it embeds a
  token - so it rides only in the request body/target and is NEVER logged). ``httpx``
  is lazily imported so importing this module stays free at the base gate. A Slack
  webhook replies with the plain-text body ``ok`` (not JSON), so this uses a slim
  post + status check rather than the JSON ``HttpProviderClient``.
* ``FakeSlackNotifier`` - deterministic, in-memory: records every posted message so
  the raise_alert tests can assert the Slack leg fired with zero network/keys.

``slack_notifier_from_settings`` returns a real client when the webhook is present
and degrades to ``None`` otherwise - raise_alert then skips the Slack leg (the alert
row + in-app notifications still land) until the webhook is configured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.logging_setup import get_logger
from integrations.errors import ProviderCallError, ProviderNotConfiguredError

if TYPE_CHECKING:
    from app.config import Settings

logger = get_logger("integrations.slack")

_INSTALL_HINT = "set SLACK_WEBHOOK_URL to an incoming-webhook URL"


@runtime_checkable
class SlackNotifier(Protocol):
    """Post a short plain-text message to a Slack channel. Best-effort at the call
    site: raise_alert swallows any failure so a Slack outage never breaks delivery."""

    def post(self, text: str) -> None: ...


class SlackWebhookClient:
    """Real ``SlackNotifier`` backed by a Slack incoming webhook.

    The webhook URL is the secret (it embeds a token); it is stored on the instance
    and used only as the POST target - never logged. ``httpx`` is lazy-imported so a
    keyless import stays light.
    """

    provider = "slack"

    def __init__(self, *, webhook_url: str, timeout: float = 10.0) -> None:
        if not webhook_url:
            raise ProviderNotConfiguredError(f"Slack notifier unavailable: {_INSTALL_HINT}")
        try:
            import httpx
        except ImportError as exc:  # httpx is a base dep; guard mirrors the other seams
            raise ProviderNotConfiguredError(
                "Slack notifier unavailable: install httpx (a base dependency)"
            ) from exc
        self._httpx = httpx
        self._url = webhook_url
        self._timeout = timeout

    def post(self, text: str) -> None:
        try:
            response = self._httpx.post(
                self._url, json={"text": text}, timeout=self._timeout
            )
        except self._httpx.HTTPError as exc:
            # Never echo the URL (it is the secret) - just the provider + a generic reason.
            logger.error("slack_post_failed", provider=self.provider)
            raise ProviderCallError("Slack webhook post failed") from exc
        if response.status_code >= 400:
            logger.error("slack_post_error", provider=self.provider, status=response.status_code)
            raise ProviderCallError(
                f"Slack webhook post failed with status {response.status_code}"
            )


class FakeSlackNotifier:
    """Deterministic, offline ``SlackNotifier`` for the raise_alert unit tests.

    Every ``post`` appends the message to ``posts`` so a test can assert the Slack
    leg fired (and with what text) with zero network/keys."""

    def __init__(self) -> None:
        self.posts: list[str] = []

    def post(self, text: str) -> None:
        self.posts.append(text)


def slack_notifier_from_settings(settings: Settings) -> SlackNotifier | None:
    """A real ``SlackWebhookClient`` when ``SLACK_WEBHOOK_URL`` is present, else
    ``None``.

    Degrades to ``None`` (never raises) when the webhook is absent - raise_alert then
    skips the Slack leg. The webhook URL (a secret) is never logged.
    """
    webhook = settings.slack_webhook_url
    if not webhook:
        logger.info("slack_notifier_degraded", reason="missing_webhook")
        return None
    try:
        return SlackWebhookClient(webhook_url=webhook.get_secret_value())
    except ProviderNotConfiguredError as exc:
        logger.info("slack_notifier_degraded", reason=str(exc))
        return None
