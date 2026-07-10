"""Sentry initialization (DSN-gated, opt-in).

If ``SENTRY_DSN`` is unset this is a no-op, so local/dev runs never phone home.
``sentry_sdk`` is imported lazily so the SDK is only touched when enabled.
"""

from __future__ import annotations

from app.config import Settings
from app.logging_setup import get_logger

logger = get_logger("app.observability")


def init_sentry(settings: Settings) -> None:
    """Initialize Sentry only when a DSN is configured; otherwise do nothing."""
    if not settings.sentry_dsn:
        return

    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.app_env,
        send_default_pii=False,
        traces_sample_rate=0.0,
    )
    logger.info("sentry_initialized", environment=settings.app_env)
