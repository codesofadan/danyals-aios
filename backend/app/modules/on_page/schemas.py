"""On-page request/response models - SERVER-AUTHORITATIVE.

No ``frontend/lib/*.ts`` type mirrors this module, so these shapes are owned here
(unlike the contract-locked Part-2/7 responses). The module's own unit tests freeze
the emitted key set + the ``Impact`` / ``RecStatus`` / ``FixKind`` enum tuples, so a
drift is still caught - this is the server-authoritative equivalent of the contract
lock.

Python attributes stay snake_case; a multi-word wire key re-aliases to camelCase via
``serialization_alias`` (ruff N815 forbids a raw camelCase attribute). The internal
``client_id`` NEVER leaks: ``client`` is the snapshotted display name. The capitalised
``Impact`` labels ARE the display cell the tool workspace renders verbatim.

THE APPLY CONFIRMATION IS PART OF THE CONTRACT. ``Confirmation`` is a STRICT
``Literal[True]`` - not a ``bool`` - so a body without it, or with ``false``, or with
anything Pydantic's lax mode would happily coerce into truth (``1``, ``"true"``),
fails validation and FastAPI answers 422 before the route body ever runs. Applying a
fix REWRITES A LIVE CLIENT PAGE: the affirmative has to be a literal, unambiguous
``true``, never an accidental ``POST`` with an empty body and never a stray truthy
value from a mis-serialised client.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool

# The three impact labels - capitalised = the exact display cell + the DB
# onpage_impact enum. Pinned verbatim (a module unit test asserts the tuple).
Impact = Literal["High", "Med", "Low"]
AnalysisStatus = Literal["queued", "analyzing", "done", "failed", "held"]
RecStatus = Literal["open", "applied", "dismissed", "held", "reverted"]
FixKind = Literal["title", "meta", "heading", "schema", "content", "manual"]

_IMPACTS: frozenset[str] = frozenset({"High", "Med", "Low"})
_REC_STATUSES: frozenset[str] = frozenset(
    {"open", "applied", "dismissed", "held", "reverted"}
)
_FIX_KINDS: frozenset[str] = frozenset(
    {"title", "meta", "heading", "schema", "content", "manual"}
)

def _must_be_true(value: bool) -> bool:
    """Reject ``false``; ``StrictBool`` has already rejected everything non-boolean."""
    if value is not True:
        raise ValueError("confirm must be true to apply a fix to a live site")
    return value


# The live-write affirmative. ``StrictBool`` (not ``bool``) so Pydantic's lax coercion
# cannot turn a truthy `1` or `"true"` into consent to rewrite a client's page, and the
# validator then rejects an explicit `false`. Only a literal JSON `true` is consent.
# (``Literal[True]`` alone would be neater but silently accepts `1`, since Pydantic
# cannot apply `strict` to a literal schema.)
Confirmation = Annotated[StrictBool, AfterValidator(_must_be_true)]


def _f(value: Any, default: float = 0.0) -> float:
    """Coerce a psycopg ``Decimal`` / ``None`` numeric to a plain ``float``."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class RecommendationResponse(BaseModel):
    """One on-page recommendation - a clean, server-authoritative field set.

    ``client`` is the snapshotted display name (the internal ``client_id`` never
    leaks). ``proposed`` is lifted out of ``fix_payload.proposed_value`` so the board
    can render the suggestion without knowing the payload's internals, and ``current``
    is the pre-apply snapshot - together they ARE the preview diff.
    """

    id: str
    analysis: str  # the parent analysis's PUBLIC code (OP-####), never its UUID
    client: str
    page: str
    issue: str
    issue_code: str = Field(serialization_alias="issueCode")
    impact: str
    status: str
    fix_kind: str = Field(serialization_alias="fixKind")
    current: str
    proposed: str
    priority: float
    quick_win: bool = Field(serialization_alias="quickWin")
    auto_applicable: bool = Field(serialization_alias="autoApplicable")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> RecommendationResponse:
        impact = row.get("impact")
        status = row.get("status")
        fix_kind = row.get("fix_kind")
        kind = fix_kind if fix_kind in _FIX_KINDS else "manual"
        payload = _as_dict(row.get("fix_payload"))
        return cls(
            id=str(row.get("id", "")),
            analysis=str(row.get("analysis_code", "") or ""),
            client=str(row.get("client_name", "") or ""),
            page=str(row.get("page_url", "") or ""),
            issue=str(row.get("issue", "") or ""),
            issue_code=str(row.get("issue_code", "") or ""),
            impact=impact if impact in _IMPACTS else "Low",
            status=status if status in _REC_STATUSES else "open",
            fix_kind=kind,
            current=str(row.get("current_value") or ""),
            proposed=str(payload.get("proposed_value") or ""),
            priority=round(_f(row.get("priority_score")), 2),
            quick_win=bool(row.get("quick_win")),
            # Derived, never stored: `manual` fixes are human work by definition.
            auto_applicable=kind != "manual",
        )


class RecommendationDetail(RecommendationResponse):
    """The preview/diff view: the list row PLUS the evidence behind it.

    ``detail`` carries the detector's evidence (measured value, the threshold it
    breached); ``analysisStatus`` tells the reviewer whether the parent analysis is
    still running (so a stale-looking board explains itself).
    """

    detail: dict[str, Any]
    analysis_status: str = Field(serialization_alias="analysisStatus")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> RecommendationDetail:
        base = RecommendationResponse.from_row(row)
        return cls(
            **base.model_dump(),
            detail=_as_dict(row.get("detail")),
            analysis_status=str(row.get("analysis_status", "") or ""),
        )


class AnalysisResponse(BaseModel):
    """One analysed page. ``code`` is the PUBLIC OP-#### badge (never a UUID)."""

    code: str
    client: str
    page: str
    keyword: str
    status: str
    score: float
    open_count: int = Field(serialization_alias="openCount")
    applied_count: int = Field(serialization_alias="appliedCount")
    error: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> AnalysisResponse:
        score = _as_dict(row.get("score"))
        return cls(
            code=str(row.get("code", "")),
            client=str(row.get("client_name", "") or ""),
            page=str(row.get("page_url", "") or ""),
            keyword=str(row.get("target_keyword", "") or ""),
            status=str(row.get("status", "") or ""),
            score=round(_f(score.get("total")), 1),
            open_count=int(row.get("open_count", 0) or 0),
            applied_count=int(row.get("applied_count", 0) or 0),
            # Server-side failure detail is a short, already-sanitised marker.
            error=str(row.get("error") or ""),
        )


class OnPageStats(BaseModel):
    """The board summary tiles: pages analysed, still-open suggestions, applied."""

    analyzed: int
    open: int
    applied: int

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> OnPageStats:
        return cls(
            analyzed=int(row.get("analyzed", 0) or 0),
            open=int(row.get("open", 0) or 0),
            applied=int(row.get("applied", 0) or 0),
        )


# --- Request models -----------------------------------------------------------


class AnalyzeRequest(BaseModel):
    """POST /on-page/analyze body: queue ONE page for analysis.

    ``page_url`` must be a PUBLIC http(s) URL - the route SSRF-validates it (off the
    event loop) before anything is queued, so an internal address can never reach the
    fetcher. ``source_audit_id`` maps an existing 363-check audit run's on-page
    findings instead of re-detecting them.
    """

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(alias="clientId")
    page_url: str = Field(alias="pageUrl", min_length=1, max_length=2000)
    target_keyword: str = Field(default="", alias="targetKeyword", max_length=200)
    site_id: str | None = Field(default=None, alias="siteId")
    source_audit_id: str | None = Field(default=None, alias="sourceAuditId")


class AnalysisQueuedResponse(BaseModel):
    """The accepted-for-analysis acknowledgement: the new OP-#### code + queued."""

    code: str
    queued: bool


class ApplyRequest(BaseModel):
    """POST /on-page/recommendations/{id}/apply body.

    ``confirm`` is a STRICT ``Literal[True]``: a missing, false, or merely-truthy value
    is a 422 from Pydantic BEFORE the route runs. This is a live-site write - the
    confirmation is the contract, not a nicety.

    ``force`` re-snapshots and proceeds THROUGH the drift-guard. It exists for the
    case where a lead has looked at the page, seen the hand-edit, and decided ours
    wins anyway; it is never the default and it is lead-only like the apply itself.
    """

    model_config = ConfigDict(populate_by_name=True)

    confirm: Confirmation
    force: bool = False


class ApplyBulkRequest(BaseModel):
    """POST /on-page/recommendations/apply-bulk body: apply many in one call.

    Same ``confirm`` contract as the single apply. ``manual`` recommendations are
    SKIPPED with a reason rather than failing the batch - a human still has to do
    those, and one un-appliable id must not block the other 19.
    """

    model_config = ConfigDict(populate_by_name=True)

    ids: list[str] = Field(min_length=1, max_length=50)
    confirm: Confirmation
    force: bool = False


class ApplyResultResponse(BaseModel):
    """The verdict of ONE apply/revert: the recommendation + what actually happened.

    ``state`` is the honest outcome vocabulary - ``applied`` / ``reverted`` /
    ``noop`` (already applied; idempotent) / ``held`` (we could not safely write:
    no credential, or the SEO-plugin meta bridge silently dropped it) / ``blocked``
    (the drift-guard refused) / ``failed``. ``reason`` is human-readable.
    """

    id: str
    state: str
    reason: str
    recommendation: RecommendationResponse | None = None


class ApplyBulkResponse(BaseModel):
    """The bulk verdict: per-id results + the applied/skipped tallies."""

    applied: int
    skipped: int
    results: list[ApplyResultResponse]
