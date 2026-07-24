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
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.db.database import DatabaseNotConfiguredError
from app.logging_setup import get_logger
from app.services.cost_gate import SPEND_HALTED_CODE, SpendHaltedError

REQUEST_ID_HEADER = "X-Request-ID"

logger = get_logger("app.errors")


class ErrorCode:
    """The stable, machine-readable codes emitted as the envelope ``type``.

    Clients may branch on these; treat them as a versioned contract (add, do not
    silently repurpose). ``http_error`` covers any raised ``HTTPException`` - its
    numeric ``status`` conveys the specific case (401/403/404/409/...).
    """

    INTERNAL = "internal_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    HTTP = "http_error"
    VALIDATION = "validation_error"
    # The global API-spend halt refusal (owner/admin kill-switch is engaged). Emitted
    # as a 402 so a caller/UI can branch on it distinctly from a plain 403/http_error.
    SPEND_HALTED = SPEND_HALTED_CODE


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
            error_type=ErrorCode.INTERNAL,
            message="Internal Server Error",
            request_id=rid,
        )

    @app.exception_handler(DatabaseNotConfiguredError)
    async def _db_not_configured_handler(
        request: Request, exc: DatabaseNotConfiguredError
    ) -> JSONResponse:
        # A dependency needs the local Postgres pool but its DSN is unconfigured:
        # 503, not a 500.
        return _error_response(
            status_code=503,
            error_type=ErrorCode.SERVICE_UNAVAILABLE,
            message="A required backend service is not configured",
            request_id=_request_id(request),
        )

    @app.exception_handler(SpendHaltedError)
    async def _spend_halted_handler(request: Request, exc: SpendHaltedError) -> JSONResponse:
        # The global API-spend halt is engaged: a typed 402 refusal with the stable
        # machine code so the frontend surfaces "API spend is halted" consistently and
        # never mistakes it for a transient failure. No provider call was made.
        return _error_response(
            status_code=exc.status_code,
            error_type=ErrorCode.SPEND_HALTED,
            message=exc.message,
            request_id=_request_id(request),
            extra={"reason": exc.reason},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        rid = _request_id(request)
        return _error_response(
            status_code=exc.status_code,
            error_type=ErrorCode.HTTP,
            message=str(exc.detail),
            request_id=rid,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        rid = _request_id(request)
        # jsonable_encoder mirrors FastAPI's own default handler: a validator that
        # raises ValueError leaves the raw exception in each error's ``ctx``, which
        # plain ``json.dumps`` cannot serialize - encode it to primitives first.
        return _error_response(
            status_code=422,
            error_type=ErrorCode.VALIDATION,
            message="Request validation failed",
            request_id=rid,
            extra={"details": jsonable_encoder(exc.errors())},
        )
