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
from app.schemas.cost import ClientBudgetResponse, CostEntryResponse, DialFeatureResponse
from app.schemas.identity import MemberResponse
from app.schemas.tasks import TaskResponse
from app.schemas.tiers import TierClientResponse
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
