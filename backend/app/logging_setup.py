"""Structlog configuration: console in dev, JSON in prod, request-id aware.

Mirrors ``danyals-audit-system/audit_engine/logging_setup.py`` with two platform
deltas: ``merge_contextvars`` (so the per-request request-id tags every line) and a
JSON renderer in prod. No secret or PII is ever logged.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import cast

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from app.config import Settings

PKT = timezone(timedelta(hours=5), name="PKT")


def _add_pkt_timestamp(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    event_dict["ts"] = datetime.now(PKT).isoformat(timespec="seconds")
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structlog + stdlib logging. Call once at app startup.

    ``force=True`` rebinds the root handler to the current stream on every call,
    which keeps output capture deterministic under tests and is harmless in prod
    (configured once at boot).
    """
    level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)

    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if settings.is_prod
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            _add_pkt_timestamp,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger. The bound request-id (if any) tags every line."""
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger(name))
