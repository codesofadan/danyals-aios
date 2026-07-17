"""Data-import wire shapes: the frozen key sets, the enum tuples, and the two fields
that must NEVER reach the wire.

These models are SERVER-AUTHORITATIVE (no ``lib/*.ts`` type mirrors them), so there is no
contract-lock file to catch a drift. These tests ARE the lock: they freeze the emitted
key set of every response model and pin each enum tuple against the ``0042`` migration's
``create type``, so an app-vs-database divergence fails here rather than as an opaque
22P02 at runtime.

The load-bearing assertions in this file are the two SWEEPS at the bottom: every response
model in the module is walked, projected from a row that carries ``stored_path`` and
``client_id``, and neither may appear anywhere in the output. Those are the fields whose
leak would matter most and whose leak is easiest to reintroduce - one ``**row`` in a
``from_row`` and both ship.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.modules.data_import.constants import SOURCE_TYPES, STATUSES
from app.modules.data_import.schemas import (
    ImportColumnPreview,
    ImportCommitQueued,
    ImportFieldsResponse,
    ImportMappingResponse,
    ImportRowError,
    ImportRunDetail,
    ImportRunResponse,
    ImportStats,
    ImportUploadResponse,
)

pytestmark = pytest.mark.unit

_MIGRATION = (
    Path(__file__).resolve().parents[3].parent / "db" / "migrations" / "0042_data_import.sql"
)

# The secret + the tenant id, planted in every fixture row below.
_SECRET_PATH = "0123456789abcdef0123456789abcdef.csv"
_SECRET_CLIENT = "cl-00000000-must-never-leak"


def _run_row(**over: object) -> dict[str, object]:
    """An ``import_runs`` row AS THE REPO RETURNS IT - i.e. ``select *``, carrying every
    column including the server-only ones. Projecting from anything less would make the
    leak sweeps below vacuous."""
    row: dict[str, object] = {
        "id": "run-1",
        "client_id": _SECRET_CLIENT,
        "client_name": "NorthPeak Dental",
        "filename": "gsc-export-june.csv",
        "stored_path": _SECRET_PATH,
        "source_type": "search_console",
        "status": "imported",
        "detected_columns": ["Query", "Clicks"],
        "column_map": {"Query": "query", "Clicks": "clicks"},
        "rows_total": 1200,
        "rows_mapped": 1198,
        "rows_error": 2,
        "error_sample": [{"row": 7, "field": "clicks", "value": "n/a", "reason": "not a number"}],
        "content_sha256": "abc123",
        "uploaded_by": "u-1",
        "created_at": datetime(2026, 7, 17, 9, 30, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 17, 9, 31, tzinfo=UTC),
    }
    row.update(over)
    return row


def _mapping_row() -> dict[str, object]:
    return {
        "id": "map-1",
        "name": "GSC queries",
        "source_type": "search_console",
        "source_signature": "deadbeef",
        "column_map": {"Query": "query"},
        "created_by": "u-1",
        "created_at": datetime(2026, 7, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 1, tzinfo=UTC),
    }


# --------------------------------------------------------------------------- #
# 1. The enums vs the migration.
# --------------------------------------------------------------------------- #
def _enum_values(type_name: str) -> tuple[str, ...]:
    """The values of one ``create type ... as enum`` block in 0042."""
    src = _MIGRATION.read_text(encoding="utf-8")
    match = re.search(rf"create type public\.{type_name} as enum\s*\((.*?)\)", src, re.DOTALL)
    assert match, f"{type_name} not found in {_MIGRATION}"
    return tuple(re.findall(r"'([^']+)'", match.group(1)))


def test_migration_file_exists_and_is_parseable() -> None:
    # Guards the reader itself: if this stopped matching, every enum test below would
    # pass vacuously on an empty tuple.
    assert _MIGRATION.is_file(), f"{_MIGRATION} is missing"
    assert _enum_values("import_source_type"), "the enum reader parsed nothing"


def test_source_type_enum_matches_the_migration() -> None:
    assert _enum_values("import_source_type") == SOURCE_TYPES


def test_status_enum_matches_the_migration() -> None:
    assert _enum_values("import_status") == STATUSES


# --------------------------------------------------------------------------- #
# 2. The frozen key sets.
# --------------------------------------------------------------------------- #
def test_run_response_emits_exactly_its_contract_keys() -> None:
    body = ImportRunResponse.from_row(_run_row()).model_dump(by_alias=True)
    assert set(body) == {
        "id", "file", "sourceType", "sourceLabel", "status", "client", "rows",
        "mapped", "errors", "detectedColumns", "columnMap", "created",
    }
    assert body["file"] == "gsc-export-june.csv"
    assert body["sourceLabel"] == "Search Console"
    assert body["client"] == "NorthPeak Dental"


def test_run_detail_adds_only_the_bounded_error_sample() -> None:
    body = ImportRunDetail.from_row(_run_row()).model_dump(by_alias=True)
    base = set(ImportRunResponse.from_row(_run_row()).model_dump(by_alias=True))
    assert set(body) - base == {"errorSample"}
    assert body["errorSample"] == [
        {"row": 7, "field": "clicks", "value": "n/a", "reason": "not a number"}
    ]


def test_run_detail_errors_reports_the_true_total_not_the_sample_length() -> None:
    """A truncated sample must never read as "only N rows were bad": ``errors`` is the
    counter, ``errorSample`` is a bounded illustration of it."""
    row = _run_row(rows_error=9_000, error_sample=[{"row": 1, "field": "clicks", "value": "x", "reason": "bad"}])
    body = ImportRunDetail.from_row(row).model_dump(by_alias=True)
    assert body["errors"] == 9_000
    assert len(body["errorSample"]) == 1


def test_stats_emits_exactly_its_contract_keys() -> None:
    body = ImportStats.from_row(
        {"imports_30d": 18, "rows_mapped": 42_000, "rows_error": 3}
    ).model_dump(by_alias=True)
    assert set(body) == {"imports30d", "rowsMapped", "rowsError"}
    assert body == {"imports30d": 18, "rowsMapped": 42_000, "rowsError": 3}


def test_mapping_response_emits_exactly_its_contract_keys() -> None:
    body = ImportMappingResponse.from_row(_mapping_row()).model_dump(by_alias=True)
    assert set(body) == {"id", "name", "sourceType", "columnMap", "created"}


def test_upload_response_emits_exactly_its_contract_keys() -> None:
    body = ImportUploadResponse(
        run=ImportRunResponse.from_row(_run_row()),
        columns=[ImportColumnPreview(column="Query", samples=["plumber"])],
        suggested={"Query": "query"},
        template=None,
    ).model_dump(by_alias=True)
    assert set(body) == {"run", "columns", "suggested", "template"}


def test_fields_response_publishes_the_allow_list() -> None:
    body = ImportFieldsResponse(
        source_type="keywords", fields=["keyword", "volume"], required=["keyword"]
    ).model_dump(by_alias=True)
    assert set(body) == {"sourceType", "fields", "required"}


def test_commit_queued_emits_exactly_its_contract_keys() -> None:
    body = ImportCommitQueued(id="run-1", queued=True).model_dump(by_alias=True)
    assert set(body) == {"id", "queued", "reason"}


def test_row_error_names_the_column_and_the_offending_value() -> None:
    """The sample exists so a human can FIX the file: a bare count would not tell them
    which column of which row to look at."""
    body = ImportRowError(row=7, field="clicks", value="n/a", reason="not a number").model_dump()
    assert set(body) == {"row", "field", "value", "reason"}


def test_run_response_projects_an_unmapped_run_without_inventing_counts() -> None:
    row = _run_row(status="uploaded", rows_total=0, rows_mapped=0, rows_error=0, column_map={})
    body = ImportRunResponse.from_row(row).model_dump(by_alias=True)
    assert body["status"] == "uploaded"
    assert (body["rows"], body["mapped"], body["errors"]) == (0, 0, 0)
    assert body["columnMap"] == {}


# --------------------------------------------------------------------------- #
# 3. The leak sweeps - the reason this file exists.
# --------------------------------------------------------------------------- #
def _all_response_models() -> list[BaseModel]:
    """Every response model the module can emit, built from rows that carry the secrets.

    Listed explicitly rather than discovered: a model that someone forgets to add here
    is a gap, but a discovery helper that silently found zero models would be a
    vacuously-passing sweep - which is worse.
    """
    run_row = _run_row()
    return [
        ImportRunResponse.from_row(run_row),
        ImportRunDetail.from_row(run_row),
        ImportStats.from_row({"imports_30d": 1, "rows_mapped": 2, "rows_error": 3}),
        ImportMappingResponse.from_row(_mapping_row()),
        ImportFieldsResponse(source_type="keywords", fields=["keyword"], required=["keyword"]),
        ImportCommitQueued(id="run-1", queued=True),
        ImportColumnPreview(column="Query", samples=["plumber"]),
        ImportRowError(row=1, field="clicks", value="x", reason="bad"),
        ImportUploadResponse(
            run=ImportRunResponse.from_row(run_row),
            columns=[ImportColumnPreview(column="Query", samples=["plumber"])],
            suggested={"Query": "query"},
            template=ImportMappingResponse.from_row(_mapping_row()),
        ),
    ]


def test_the_sweep_covers_every_response_model_in_the_module() -> None:
    """Guard the sweep itself: if the module grows a response model, it must be added
    here. Without this, the two leak tests below could quietly stop covering it."""
    import app.modules.data_import.schemas as mod

    declared = {
        name
        for name, obj in vars(mod).items()
        if isinstance(obj, type)
        and issubclass(obj, BaseModel)
        and obj.__module__ == mod.__name__
        and not name.endswith(("Set", "Create"))  # request models: not emitted
    }
    swept = {type(m).__name__ for m in _all_response_models()}
    assert declared == swept, f"response models not covered by the leak sweep: {declared - swept}"


@pytest.mark.parametrize("model", _all_response_models(), ids=lambda m: type(m).__name__)
def test_no_response_model_ever_serializes_the_stored_path(model: BaseModel) -> None:
    """``stored_path`` is SERVER-ONLY.

    It is on every ``import_runs`` row a repo returns (``select *``), so the only thing
    keeping it off the wire is that each ``from_row`` reads an explicit field list. One
    ``**row`` would ship it - and a stored path is the input to any path-taking endpoint
    a future chunk adds. Checked against the SERIALIZED text, not the field names, so a
    path smuggled inside a nested value is caught too.
    """
    dumped = model.model_dump_json(by_alias=True)
    assert "stored_path" not in dumped
    assert "storedPath" not in dumped
    assert _SECRET_PATH not in dumped


@pytest.mark.parametrize("model", _all_response_models(), ids=lambda m: type(m).__name__)
def test_no_response_model_ever_serializes_the_client_id(model: BaseModel) -> None:
    """The internal tenant id never leaks - ``client`` is the snapshotted display name
    (the house rule every module follows)."""
    dumped = model.model_dump_json(by_alias=True)
    assert "client_id" not in dumped
    assert "clientId" not in dumped
    assert _SECRET_CLIENT not in dumped


def test_run_response_field_names_do_not_include_the_server_only_columns() -> None:
    """Belt-and-braces over the serialization sweep: the MODEL itself must not declare
    them, so no future ``model_dump(exclude=...)`` juggling can accidentally re-expose
    one."""
    for model in (ImportRunResponse, ImportRunDetail):
        assert "stored_path" not in model.model_fields
        assert "client_id" not in model.model_fields
        assert "content_sha256" not in model.model_fields
        assert "uploaded_by" not in model.model_fields
