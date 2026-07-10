"""Per-request request-id middleware.

Reads an inbound ``X-Request-ID`` (or generates one), binds it into structlog's
contextvars so every log line on this request carries it, echoes it back on the
response, and stores it on ``request.state``.

Storing on ``request.state`` is REQUIRED: an unhandled exception is handled by
Starlette's outer ``ServerErrorMiddleware`` *after* this middleware's ``finally``
has already cleared the contextvars, so the 500 handler can no longer read the
id from the log context -- it reads ``request.state.request_id`` instead (the id
survives because it lives in the shared ASGI ``scope``).
"""

from __future__ import annotations

from uuid import uuid4

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a request-id to the log context, ``request.state``, and the response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        request.state.request_id = rid
        structlog.contextvars.bind_contextvars(request_id=rid)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = rid
            return response
        finally:
            structlog.contextvars.clear_contextvars()
