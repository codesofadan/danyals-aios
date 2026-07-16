"""P9-5: request/response models for the web in-product AI-assist surface.

``surface`` is a closed set: the dashboard/portal tells the backend WHICH engine a
plain-language request belongs to, and the backend routes + summarizes accordingly.
The response is deliberately small and honest - it carries the summarizer's prose
plus a pointer to the module that owns the REAL workflow (``routed_to`` / ``endpoint``)
and a ``status`` that flips to ``degraded`` (never an error) when the key is absent or
the money-dial blocks the spend.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# The four backend engines the dashboard can address. A value outside this set is a
# 422 at the edge (pydantic), so the router never sees an unknown surface.
AiAssistSurface = Literal["content", "report", "radar", "general"]

AssistStatus = Literal["ok", "degraded"]


class AiAssistRequest(BaseModel):
    """A plain-language assist request from the dashboard/portal.

    ``context_ref`` is an OPTIONAL opaque handle (e.g. a client id or job code) the
    frontend passes so the operator's prompt can name what it is about; it is never
    a credential and never widens RLS - the backend still reads only what the
    caller's own scope allows.
    """

    surface: AiAssistSurface
    prompt: str = Field(min_length=1, max_length=4000)
    context_ref: str | None = Field(default=None, max_length=200)


class AiAssistResponse(BaseModel):
    """The structured assist reply (small + honest).

    ``result`` is the summarizer's bounded prose on the happy path, or a degraded
    stub message when keyless / dial-blocked. ``routed_to`` + ``endpoint`` name the
    module that owns the real heavy workflow (content pipeline, reports, policy
    radar) so the operator can act; ``reason`` is populated only when degraded.
    """

    surface: AiAssistSurface
    status: AssistStatus
    routed_to: str
    endpoint: str
    result: str
    reason: str = ""
