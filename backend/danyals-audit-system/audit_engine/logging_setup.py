"""Structured logging via structlog. PKT timestamps. No PII in logs."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone, timedelta

import structlog

PKT = timezone(timedelta(hours=5), name="PKT")


def _add_pkt_timestamp(_, __, event_dict: dict) -> dict:
    event_dict["ts"] = datetime.now(PKT).isoformat(timespec="seconds")
    return event_dict


def configure(level: str = "INFO") -> None:
    """Idempotent structlog setup. Call once at CLI entry."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            _add_pkt_timestamp,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
