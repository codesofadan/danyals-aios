"""Global error handling: one JSON envelope for every error path.

Each handler emits ``{"error": {"type", "message", "request_id"}}`` plus an
``X-Request-ID`` response header. The request-id is read from ``request.state``
(set by ``RequestIDMiddleware``) because the unhandled-exception path runs in
Starlette's outer ``ServerErrorMiddleware`` after the request contextvars have
been cleared.

The 500 message is always generic: we never leak ``str(exc)`` or the exception
class to the client, but we log the full exception server-side.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.logging_setup import get_logger

REQUEST_ID_HEADER = "X-Request-ID"

logger = get_logger("app.errors")


def _request_id(request: Request) -> str | None:
    """Read the request-id stashed on ``request.state`` by ``RequestIDMiddleware``."""
    rid: str | None = getattr(request.state, "request_id", None)
    return rid


def _error_response(
    *,
    status_code: int,
    error_type: str,
    message: str,
    request_id: str | None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"type": error_type, "message": message, "request_id": request_id}
    if extra:
        error.update(extra)
    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    """Register the unhandled / HTTP / validation error handlers on ``app``."""

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        rid = _request_id(request)
        # Full detail server-side only; the client gets a generic message.
        logger.error("unhandled_exception", exc_info=exc, request_id=rid)
        return _error_response(
            status_code=500,
            error_type="internal_error",
            message="Internal Server Error",
            request_id=rid,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        rid = _request_id(request)
        return _error_response(
            status_code=exc.status_code,
            error_type="http_error",
            message=str(exc.detail),
            request_id=rid,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        rid = _request_id(request)
        return _error_response(
            status_code=422,
            error_type="validation_error",
            message="Request validation failed",
            request_id=rid,
            extra={"details": exc.errors()},
        )
