"""P9-5: ``POST /ai/assist`` - the web Dashboard/Portal in-product AI surface.

The web twin of the local skills: the dashboard/portal calls OUR backend, which
calls Claude through the existing summarizer seam under the existing cost gate. The
client NEVER holds an Anthropic key. Staff-only (``view_reports`` - held by all six
staff roles, never a portal client, so a client is 403'd off the whole surface,
mirroring content/reports/policy). RLS is untouched: this adds a summarizer, not a
new data path.

Key-gated + cost-gated: a missing key or a dial/budget block DEGRADES (200,
``status='degraded'``) rather than crashing, and the gate is never bypassed. The
heavy per-module generation is NOT here - ``/ai/assist`` interprets + routes to the
module that owns the real workflow; see ``app/services/ai_assist.py`` for the pure,
injected core.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, require_perm
from app.core.deps import SettingsDep
from app.schemas.ai_assist import AiAssistRequest, AiAssistResponse
from app.services.ai_assist import build_assist_gate, build_assist_summarizer, run_assist
from app.services.cost_gate import CostGate
from integrations.llm import Summarizer

router = APIRouter(tags=["ai"])

# All six staff roles hold view_reports; a portal client does NOT. This confines the
# whole /ai surface to staff (clients 403), exactly like the reports/content surfaces.
StaffAssist = Annotated[CurrentUser, Depends(require_perm("view_reports"))]


def get_assist_summarizer(settings: SettingsDep) -> Summarizer | None:
    """Dependency: the key-gated summarizer (or ``None`` degraded). Overridable in tests."""
    return build_assist_summarizer(settings)


def get_assist_gate() -> CostGate:
    """Dependency: the real cost gate over the Postgres store. Overridable in tests."""
    return build_assist_gate()


SummarizerDep = Annotated[Summarizer | None, Depends(get_assist_summarizer)]
GateDep = Annotated[CostGate, Depends(get_assist_gate)]


@router.post("/ai/assist", response_model=AiAssistResponse)
async def ai_assist(
    body: AiAssistRequest,
    _user: StaffAssist,
    settings: SettingsDep,
    summarizer: SummarizerDep,
    gate: GateDep,
) -> AiAssistResponse:
    """Route a plain-language request to the right engine + return a structured reply.

    The blocking summarize + the (sync) gate store run off the event loop via
    ``to_thread``. On a keyless deploy or a money-dial block the reply is 200 with
    ``status='degraded'`` - the gate is never bypassed and no client key is involved.
    """

    def _run() -> AiAssistResponse:
        result = run_assist(
            body.surface,
            body.prompt,
            body.context_ref,
            summarizer=summarizer,
            gate=gate,
            settings=settings,
        )
        return AiAssistResponse(
            surface=result.surface,
            status=result.status,
            routed_to=result.routed_to,
            endpoint=result.endpoint,
            result=result.result,
            reason=result.reason,
        )

    return await asyncio.to_thread(_run)
