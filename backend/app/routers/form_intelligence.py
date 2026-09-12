"""The semantic form-mapping endpoint the extension calls.

ITS OWN ROUTER rather than another 100 lines in the 2,300-line citations router: this
is a distinct capability with its own spend, its own durable cache and its own failure
modes, and that file is long enough that a reader cannot hold it.

SCOPED TO CITATIONS ONLY, deliberately. An earlier draft took an ANY-OF floor across
`citation_queue:write` and `web2_queue:write`, on the theory that a Web 2.0 publishing
form is the same problem as a directory form. The owner scoped the feature to citations
(2026-09-12), and the narrower grant is also the better one: a token minted for a Web
2.0 shift has no business spending the citation dial. Least privilege beats a
speculative reuse - and if the Web 2.0 lane ever wants this, widening one dependency
is a smaller change than discovering a grant nobody intended.

Web 2.0 was examined and left out for a real reason, not just scope: publishing
platforms are rich-text editors (contenteditable, markdown panes, editors inside
iframes), and `filler.ts`'s setter does nothing on a contenteditable node. It fails
HONESTLY - the read-back reports the field as unfilled rather than claiming success -
but the lane would need a genuine contenteditable path before the mapping was worth
computing.

THE SPEND. One analysis is one LLM call, cost-gated on the registered `citations` dial
and billed with no client attached: the mapping describes a DIRECTORY's form, not a
client's data, and it is cached for every client thereafter. Charging it to whichever
client happened to be first would make one tenant subsidise the rest.

WHAT IT REFUSES TO DO. It never returns a mapping it could not validate, never invents
a selector, and never reports success for a form it could not map - the operator lands
back on copy buttons, which is where they already were. And it never submits anything:
the extension fills, a person reviews and presses the site's own button.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.auth import CurrentUser, require_role
from app.core.deps import SettingsDep
from app.core.ratelimit import rate_limit
from app.logging_setup import get_logger
from app.modules.citations.operator_auth import require_operator_scope_any
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore
from app.services.form_intelligence import (
    APPLY_THRESHOLD,
    CANONICAL_KEYS,
    IGNORE,
    FormPlan,
    plan_form,
    sanitize,
)
from app.services.form_intelligence import fingerprint as fingerprint_of
from app.services.form_map_store import cached_plan, store_for

logger = get_logger("app.routers.form_intelligence")

router = APIRouter(tags=["form-intelligence"])

# Citation shift only - see the module docstring on why this is not an any-of floor.
OperatorWrite = Annotated[
    CurrentUser,
    Depends(require_operator_scope_any("citation_queue:write")),
]
Lead = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

# An analysis is a paid call on a cache miss. The gate bounds the MONEY; this bounds
# the hammering (a page that re-analysed on every keystroke would pass the gate for a
# long time before anyone noticed).
AnalyzeLimit = Depends(rate_limit("form_analyze", limit=60, per_seconds=3600))

_FEATURE = "citations"
_JOB_TYPE = "form_mapping"


class FieldIn(BaseModel):
    """One field as the extension collected it. Structure only - see the service."""

    selector: str = Field(min_length=1, max_length=2000)
    kind: str = Field(min_length=1, max_length=40)
    name: str = ""
    id: str = ""
    label: str = ""
    placeholder: str = ""
    aria: str = ""
    near: str = ""
    options: list[str] = Field(default_factory=list)
    required: bool = False
    step: int = 0

    model_config = {"extra": "ignore"}


class AnalyzeRequest(BaseModel):
    """`extra: ignore` is load-bearing here: if a future extension build starts sending
    a field's VALUE, it is dropped at the door rather than reaching the sanitizer."""

    url: str = Field(min_length=1, max_length=2000)
    fields: list[FieldIn] = Field(min_length=1)
    directory_id: str | None = Field(default=None, alias="directoryId")

    model_config = {"populate_by_name": True, "extra": "ignore"}


class MappingOut(BaseModel):
    selector: str
    key: str
    confidence: float
    #: Whether the extension may type this WITHOUT the operator confirming it.
    fill: bool


class AnalyzeResponse(BaseModel):
    """The plan, plus everything needed to explain it honestly in the panel."""

    ok: bool
    fingerprint: str
    #: True when this cost nothing - served from the cache.
    cached: bool
    mappings: list[MappingOut]
    #: Mapped but below the confidence bar: offered for review, never auto-typed.
    review_count: int = Field(serialization_alias="reviewCount")
    fill_count: int = Field(serialization_alias="fillCount")
    #: Fields the mapper deliberately refused (honeypots, captchas, consent boxes).
    ignored_count: int = Field(serialization_alias="ignoredCount")
    #: Anything approximated, truncated or dropped. Shown, never swallowed.
    notes: list[str]
    #: Set when no plan could be produced; the panel falls back to copy buttons.
    error: str = ""
    threshold: float = APPLY_THRESHOLD


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _to_response(plan: FormPlan) -> AnalyzeResponse:
    return AnalyzeResponse(
        ok=plan.ok,
        fingerprint=plan.fingerprint,
        cached=plan.cached,
        mappings=[
            MappingOut(selector=m.selector, key=m.key, confidence=round(m.confidence, 3),
                       fill=m.fillable)
            for m in plan.mappings
            if m.key != IGNORE
        ],
        review_count=len(plan.to_review),
        fill_count=len(plan.to_fill),
        ignored_count=sum(1 for m in plan.mappings if m.key == IGNORE),
        notes=list(plan.notes),
        error=plan.error,
    )


def _summarizer(settings: Any) -> Any:
    """The LLM seam, or ``None`` when unkeyed. Imported here so the module stays
    importable without the optional AI extra."""
    key = settings.anthropic_api_key
    if not key or not key.get_secret_value():
        return None
    from integrations.llm import AnthropicSummarizer

    return AnthropicSummarizer(
        api_key=key.get_secret_value(),
        model_summary=settings.anthropic_model_summary,
        model_heavy=settings.anthropic_model_heavy,
    )


@router.post(
    "/form-intelligence/analyze",
    response_model=AnalyzeResponse,
    dependencies=[AnalyzeLimit],
)
async def analyze(
    body: AnalyzeRequest,
    settings: SettingsDep,
    user: OperatorWrite,
) -> AnalyzeResponse:
    """Map the open form's fields to canonical business-listing keys.

    Cache first, then the model. A miss that the gate blocks is an honest refusal with
    a reason, NOT an empty plan reported as success - an empty plan renders as "we
    analysed it and there is nothing to fill", which is indistinguishable from a form
    that genuinely needs nothing.
    """
    host = _host_of(body.url)
    if not host:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "a form URL is required")

    raw_fields = [f.model_dump() for f in body.fields]
    digest, notes = await asyncio.to_thread(sanitize, raw_fields)
    if not digest:
        return AnalyzeResponse(
            ok=False, fingerprint="", cached=False, mappings=[], review_count=0,
            fill_count=0, ignored_count=0, notes=notes,
            error="no fillable fields were found on this page",
        )

    fp = await asyncio.to_thread(fingerprint_of, digest, host=host)
    store = store_for(user.id)

    hit = await asyncio.to_thread(cached_plan, store, fp)
    if hit is not None:
        await asyncio.to_thread(store.touch, fp)
        response = _to_response(hit)
        response.notes = [*notes, "served from the cache - this analysis cost nothing"]
        return response

    summarizer = _summarizer(settings)
    if summarizer is None:
        return AnalyzeResponse(
            ok=False, fingerprint=fp, cached=False, mappings=[], review_count=0,
            fill_count=0, ignored_count=0, notes=notes,
            error="the form mapper is not configured on this deploy",
        )

    # The spend gate, BEFORE the call. No client_id: this describes a directory's form,
    # not a client's data, and the result is cached for every client after this one.
    model = settings.anthropic_model_summary
    gate = CostGate(store=PostgresCostStore(), cache=_NullCache())
    ctx = GateContext(
        feature_key=_FEATURE,
        client_id=None,
        provider="anthropic",
        estimated_cost=float(settings.form_mapping_cost_estimate),
        job_id=fp[:16],
        job_type=_JOB_TYPE,
    )
    decision = await asyncio.to_thread(gate.evaluate, ctx)
    if not decision.allowed:
        logger.info("form_mapping_blocked", host=host, outcome=decision.outcome)
        return AnalyzeResponse(
            ok=False, fingerprint=fp, cached=False, mappings=[], review_count=0,
            fill_count=0, ignored_count=0, notes=notes,
            error="form analysis is switched off or over budget right now",
        )

    plan = await asyncio.to_thread(
        plan_form, summarizer, raw_fields, host=host, model=model
    )
    if plan.ok:
        await asyncio.to_thread(gate.commit, ctx, ctx.estimated_cost)
        await asyncio.to_thread(
            store.put, plan, host=host, model=model, directory_id=body.directory_id
        )
    return _to_response(plan)


@router.delete("/form-intelligence/cache/{host}", status_code=status.HTTP_200_OK)
async def purge_host(host: str, user: Lead) -> dict[str, int]:
    """Drop every cached mapping for one host.

    The escape hatch for a directory that changed its form in a way the fingerprint
    could not see - a field that kept its name and label but changed meaning. Lead-only,
    mirroring ``0140``'s delete policy: recomputing costs one inference per form, and
    being wrong costs listings.
    """
    removed = await asyncio.to_thread(store_for(user.id).purge_host, host)
    return {"removed": removed}


@router.get("/form-intelligence/vocabulary", response_model=list[str])
async def vocabulary(_user: OperatorWrite) -> list[str]:
    """The canonical keys the mapper can return.

    Served rather than hardcoded in the extension so the panel's labels and the
    server's validator cannot drift - the same reason the backend owns the list.
    """
    return [*CANONICAL_KEYS, IGNORE]


class _NullCache:
    """The gate's cache seam, unused here: the DURABLE cache is ``form_field_maps``,
    which is checked before the gate is ever consulted, so a second in-memory layer
    would only be able to disagree with it."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None
