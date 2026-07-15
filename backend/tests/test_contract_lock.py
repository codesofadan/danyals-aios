"""Contract lock: every API response model's field set must equal the frontend
TS type it mirrors (``frontend/lib/*.ts``), so the dashboard lights up unchanged.

The API's declared ``response_model`` serializes with ``by_alias=True``, so the
emitted JSON keys are ``serialization_alias`` (camelCase) - which must match the
TS type's field names one-for-one. A drift in EITHER direction fails the build:
a field added/renamed on one side without the other is a broken contract.

This is a static check (no Supabase, no server) - it reads the Pydantic models
and greps the TS type bodies, so it runs in the ordinary unit gate and in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.schemas.activity import ActivityResponse
from app.schemas.audits import AuditResponse
from app.schemas.clients import ClientResponse
from app.schemas.content import ContentJobResponse
from app.schemas.cost import ClientBudgetResponse, CostEntryResponse, DialFeatureResponse
from app.schemas.identity import MemberResponse
from app.schemas.milestones import (
    AutoAdvanceResponse,
    ClientProjectResponse,
    StageResponse,
)
from app.schemas.offpage import (
    BacklinkResponse,
    CitationResponse,
    Web2PropertyResponse,
)
from app.schemas.policy import (
    ChangeEventResponse,
    KBEntryResponse,
    RecommendationResponse,
    SourceResponse,
)
from app.schemas.reports import (
    ReportTypeResponse,
    SyncEventResponse,
    WorkbookResponse,
)
from app.schemas.tasks import TaskResponse
from app.schemas.tiers import TierClientResponse
from app.schemas.upsells import UpsellResponse
from app.schemas.vault import VaultKeyResponse

# Repo root: backend/tests/ -> backend/ -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# response model -> (frontend TS file, exported type name it mirrors)
_CONTRACT: list[tuple[type[BaseModel], str, str]] = [
    (AuditResponse, "frontend/lib/audit.ts", "AuditRow"),
    (TaskResponse, "frontend/lib/data.ts", "Task"),
    (MemberResponse, "frontend/lib/data.ts", "TeamMemberRecord"),
    (ClientResponse, "frontend/lib/data.ts", "ClientRecord"),
    (VaultKeyResponse, "frontend/lib/vault.ts", "VaultKey"),
    (CostEntryResponse, "frontend/lib/cost.ts", "CostEntry"),
    (ClientBudgetResponse, "frontend/lib/cost.ts", "ClientBudget"),
    (DialFeatureResponse, "frontend/lib/cost.ts", "DialFeature"),
    (ActivityResponse, "frontend/lib/data.ts", "Activity"),
    (TierClientResponse, "frontend/lib/tiers.ts", "TierClient"),
    (ContentJobResponse, "frontend/lib/content.ts", "ContentJob"),
    (ClientProjectResponse, "frontend/lib/milestones.ts", "ClientProject"),
    (StageResponse, "frontend/lib/milestones.ts", "Stage"),
    (AutoAdvanceResponse, "frontend/lib/milestones.ts", "AutoAdvance"),
    (UpsellResponse, "frontend/lib/upsells.ts", "Upsell"),
    (BacklinkResponse, "frontend/lib/offpage.ts", "Backlink"),
    (CitationResponse, "frontend/lib/offpage.ts", "Citation"),
    (Web2PropertyResponse, "frontend/lib/offpage.ts", "Web2Property"),
    (SourceResponse, "frontend/lib/policy.ts", "Source"),
    (ChangeEventResponse, "frontend/lib/policy.ts", "ChangeEvent"),
    (KBEntryResponse, "frontend/lib/policy.ts", "KBEntry"),
    (RecommendationResponse, "frontend/lib/policy.ts", "Recommendation"),
    (WorkbookResponse, "frontend/lib/reports.ts", "Workbook"),
    (ReportTypeResponse, "frontend/lib/reports.ts", "ReportType"),
    (SyncEventResponse, "frontend/lib/reports.ts", "SyncEvent"),
]


def _ts_field_names(ts_path: Path, type_name: str) -> set[str]:
    """The top-level field names of ``export type <type_name> = { ... };``."""
    src = ts_path.read_text(encoding="utf-8")
    match = re.search(rf"export type {type_name}\s*=\s*\{{(.*?)\n\}};", src, re.DOTALL)
    assert match, f"TS type {type_name} not found in {ts_path}"
    fields: set[str] = set()
    for line in match.group(1).splitlines():
        fm = re.match(r"\s*(\w+)\??\s*:", line)  # `name:` or `name?:`
        if fm:
            fields.add(fm.group(1))
    assert fields, f"no fields parsed for {type_name}"
    return fields


def _model_emitted_keys(model: type[BaseModel]) -> set[str]:
    """The JSON keys the model emits (serialization_alias wins, like FastAPI)."""
    return {
        field.serialization_alias or field.alias or name
        for name, field in model.model_fields.items()
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model", "ts_file", "ts_type"),
    _CONTRACT,
    ids=[f"{m.__name__}<->{t}" for m, _, t in _CONTRACT],
)
def test_response_model_matches_frontend_type(
    model: type[BaseModel], ts_file: str, ts_type: str
) -> None:
    ts = _ts_field_names(_REPO_ROOT / ts_file, ts_type)
    emitted = _model_emitted_keys(model)
    assert emitted == ts, (
        f"{model.__name__} drifted from {ts_type} ({ts_file}): "
        f"model-only={sorted(emitted - ts)} ts-only={sorted(ts - emitted)}"
    )


@pytest.mark.unit
def test_contract_lock_covers_the_core_response_models() -> None:
    # Guard against silently dropping a mapping (e.g. a refactor renames a model).
    assert len(_CONTRACT) >= 10
    assert len({m for m, _, _ in _CONTRACT}) == len(_CONTRACT)


# --------------------------------------------------------------------------- #
# ENUM-LOCK (§3 / N3): field NAMES matching isn't enough - a model whose
# ``Literal`` values drift from the frontend union (e.g. dropping ``"Medium"`` or
# writing ``"4Ps"`` for ``"4 Ps"``) would still pass the field-name lock above but
# break the dashboard. This turns that discipline into a GATE: for each enum field
# we assert the Python ``Literal`` value set EQUALS the ``lib/*.ts`` union set.
# --------------------------------------------------------------------------- #

# (model, python field name, TS file, exported union type name)
_ENUM_CONTRACT: list[tuple[type[BaseModel], str, str, str]] = [
    (ContentJobResponse, "page_type", "frontend/lib/content.ts", "PageType"),
    (ContentJobResponse, "framework", "frontend/lib/content.ts", "Framework"),
    (ContentJobResponse, "target", "frontend/lib/content.ts", "PublishTarget"),
    (ContentJobResponse, "status", "frontend/lib/content.ts", "JobStatus"),
    # Milestones: Health is SEPARATE from StageStatus (§3) - both are locked.
    (StageResponse, "key", "frontend/lib/milestones.ts", "StageKey"),
    (StageResponse, "status", "frontend/lib/milestones.ts", "StageStatus"),
    (ClientProjectResponse, "health", "frontend/lib/milestones.ts", "Health"),
    # Off-page: every union pinned verbatim - esp. Web2Platform MUST include 'Medium'.
    (BacklinkResponse, "status", "frontend/lib/offpage.ts", "BacklinkStatus"),
    (CitationResponse, "nap", "frontend/lib/offpage.ts", "NapStatus"),
    (CitationResponse, "action", "frontend/lib/offpage.ts", "CitationAction"),
    (Web2PropertyResponse, "platform", "frontend/lib/offpage.ts", "Web2Platform"),
    (Web2PropertyResponse, "verified", "frontend/lib/offpage.ts", "Web2Verified"),
    # Policy Radar: all seven enums locked (one representative field each). Several
    # unions share a label (scope 'global' vs region 'global') but are DISTINCT.
    (SourceResponse, "status", "frontend/lib/policy.ts", "SourceStatus"),
    (ChangeEventResponse, "severity", "frontend/lib/policy.ts", "Severity"),
    (KBEntryResponse, "category", "frontend/lib/policy.ts", "Category"),
    (KBEntryResponse, "region", "frontend/lib/policy.ts", "Region"),
    (RecommendationResponse, "scope", "frontend/lib/policy.ts", "Scope"),
    (RecommendationResponse, "target", "frontend/lib/policy.ts", "TargetModule"),
    (RecommendationResponse, "status", "frontend/lib/policy.ts", "RecStatus"),
    # Reports: the sync-status lifecycle union pinned verbatim.
    (WorkbookResponse, "status", "frontend/lib/reports.ts", "SyncStatus"),
]


def _ts_union_literals(ts_path: Path, type_name: str) -> set[str]:
    """The string literals of ``export type <type_name> = "a" | "b" | ...;``.

    Handles single- and multi-line unions (a leading ``|`` and line breaks are
    fine - we just harvest every double-quoted literal in the RHS up to the ``;``).
    """
    src = ts_path.read_text(encoding="utf-8")
    match = re.search(rf"export type {type_name}\s*=\s*(.*?);", src, re.DOTALL)
    assert match, f"TS union {type_name} not found in {ts_path}"
    literals = set(re.findall(r'"([^"]*)"', match.group(1)))
    assert literals, f"no literals parsed for union {type_name}"
    return literals


def _model_literal_values(model: type[BaseModel], field_name: str) -> set[str]:
    """The ``Literal`` value set of a model field (unwraps ``X | None`` too)."""
    import typing

    ann = model.model_fields[field_name].annotation
    args = typing.get_args(ann)
    # A bare Literal[...]: get_args are the values. A union (e.g. Optional) may nest
    # the Literal; harvest string values from any depth.
    values: set[str] = set()

    def _harvest(t: object) -> None:
        for a in typing.get_args(t):
            if isinstance(a, str):
                values.add(a)
            else:
                _harvest(a)

    if args and all(isinstance(a, str) for a in args):
        values.update(a for a in args if isinstance(a, str))
    else:
        _harvest(ann)
    assert values, f"no Literal values on {model.__name__}.{field_name}"
    return values


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model", "field", "ts_file", "ts_union"),
    _ENUM_CONTRACT,
    ids=[f"{m.__name__}.{f}<->{u}" for m, f, _, u in _ENUM_CONTRACT],
)
def test_enum_field_matches_frontend_union(
    model: type[BaseModel], field: str, ts_file: str, ts_union: str
) -> None:
    ts = _ts_union_literals(_REPO_ROOT / ts_file, ts_union)
    py = _model_literal_values(model, field)
    assert py == ts, (
        f"{model.__name__}.{field} enum drifted from {ts_union} ({ts_file}): "
        f"model-only={sorted(py - ts)} ts-only={sorted(ts - py)}"
    )
