"""Data-import request/response models - SERVER-AUTHORITATIVE.

No ``frontend/lib/*.ts`` type mirrors this module, so these shapes are owned here (unlike
the contract-locked Part-2/7 responses). The module's own unit tests freeze the emitted
key set + the enum tuples, so a drift is still caught - the server-authoritative
equivalent of the contract lock.

Python attributes stay snake_case; a multi-word wire key re-aliases to camelCase via
``serialization_alias`` (ruff N815 forbids a raw camelCase attribute).

TWO fields never leave the server, and the schema tests sweep every model here to prove
it:

* ``stored_path`` - where the upload physically lives. It is server-only: exposing it
  hands a caller the input to any future path-taking endpoint, and it has no display
  value whatsoever (``filename``, the original name, is what a human recognises).
* ``client_id`` - the internal tenant id. ``client`` is the snapshotted display name,
  exactly like every other module.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.data_import.constants import (
    SOURCE_TYPE_LABELS,
    ImportSourceType,
    ImportStatus,
)
from app.util.timefmt import format_when

# Bound what a client may post. A column map is per-file and human-authored; 200 entries
# is far past any real export and stops a multi-megabyte jsonb from being posted into a
# run row.
_MAX_MAP_ENTRIES = 200


class ImportRunResponse(BaseModel):
    """One import run - a clean, server-authoritative field set.

    ``file`` is the ORIGINAL upload name (a display string; the server-only
    ``stored_path`` is deliberately absent). ``client`` is the snapshotted display name,
    empty for an agency-global import. ``rows``/``mapped``/``errors`` are the live
    counters the worker streams as it goes, so a long import is observable rather than
    silent.
    """

    id: str
    file: str
    source_type: ImportSourceType = Field(serialization_alias="sourceType")
    source_label: str = Field(serialization_alias="sourceLabel")
    status: ImportStatus
    client: str
    rows: int
    mapped: int
    errors: int
    detected_columns: list[str] = Field(serialization_alias="detectedColumns")
    column_map: dict[str, str] = Field(serialization_alias="columnMap")
    created: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ImportRunResponse:
        """Project an ``import_runs`` row onto the wire shape.

        Reads a fixed, explicit field list - never ``**row`` - so a column added to the
        table later (or ``stored_path``, which is on every row this reads) cannot leak
        by default.
        """
        source_type = str(row.get("source_type") or "custom")
        return cls(
            id=str(row.get("id", "") or ""),
            file=str(row.get("filename", "") or ""),
            source_type=source_type,  # type: ignore[arg-type]  # DB enum; pinned by the schema tests
            source_label=SOURCE_TYPE_LABELS.get(source_type, source_type),
            status=str(row.get("status") or "uploaded"),  # type: ignore[arg-type]  # DB enum
            client=str(row.get("client_name", "") or ""),
            rows=int(row.get("rows_total") or 0),
            mapped=int(row.get("rows_mapped") or 0),
            errors=int(row.get("rows_error") or 0),
            detected_columns=[str(c) for c in (row.get("detected_columns") or [])],
            column_map={str(k): str(v) for k, v in (row.get("column_map") or {}).items()},
            created=format_when(row.get("created_at")),
        )


class ImportRowError(BaseModel):
    """One rejected row in the BOUNDED error sample: which row, which column, why.

    ``value`` is the offending cell, truncated - enough to recognise the mistake without
    echoing an arbitrary-length cell back out.
    """

    row: int
    field: str
    value: str
    reason: str


class ImportRunDetail(ImportRunResponse):
    """One run plus its bounded error sample - the detail view.

    The sample is capped by the WORKER (a million-row bad file yields at most
    ``tasks._ERROR_SAMPLE_MAX`` entries), so this list is bounded at rest, not just on
    the wire. ``errors`` above still reports the true total, so a truncated sample never
    reads as "only 50 rows were bad".
    """

    error_sample: list[ImportRowError] = Field(serialization_alias="errorSample")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ImportRunDetail:
        base = ImportRunResponse.from_row(row)
        sample = [
            ImportRowError(
                row=int(e.get("row") or 0),
                field=str(e.get("field") or ""),
                value=str(e.get("value") or ""),
                reason=str(e.get("reason") or ""),
            )
            for e in (row.get("error_sample") or [])
            if isinstance(e, dict)
        ]
        return cls(**base.model_dump(), error_sample=sample)


class ImportColumnPreview(BaseModel):
    """One detected column + a bounded sample of its values, so a human mapping the file
    can see what is actually in the column rather than guessing from its header."""

    column: str
    samples: list[str]


class ImportUploadResponse(BaseModel):
    """The upload result: the run, what was detected, and the best mapping we can offer.

    ``suggested`` is the fuzzy auto-map; ``template`` names a SAVED mapping whose header
    signature matches this file exactly (last month's export of the same report), which
    the UI can apply with one click. Both are suggestions - neither is persisted until
    the caller posts a mapping.
    """

    run: ImportRunResponse
    columns: list[ImportColumnPreview]
    suggested: dict[str, str]
    template: ImportMappingResponse | None = None


class ImportStats(BaseModel):
    """The data-import summary tiles: runs in the last 30 days, rows successfully
    mapped, and rows rejected."""

    imports_30d: int = Field(serialization_alias="imports30d")
    rows_mapped: int = Field(serialization_alias="rowsMapped")
    rows_error: int = Field(serialization_alias="rowsError")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ImportStats:
        return cls(
            imports_30d=int(row.get("imports_30d") or 0),
            rows_mapped=int(row.get("rows_mapped") or 0),
            rows_error=int(row.get("rows_error") or 0),
        )


class ImportMappingResponse(BaseModel):
    """One saved mapping template."""

    id: str
    name: str
    source_type: ImportSourceType = Field(serialization_alias="sourceType")
    column_map: dict[str, str] = Field(serialization_alias="columnMap")
    created: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ImportMappingResponse:
        return cls(
            id=str(row.get("id", "") or ""),
            name=str(row.get("name", "") or ""),
            source_type=str(row.get("source_type") or "custom"),  # type: ignore[arg-type]  # DB enum
            column_map={str(k): str(v) for k, v in (row.get("column_map") or {}).items()},
            created=format_when(row.get("created_at")),
        )


class ImportFieldsResponse(BaseModel):
    """The allow-list, published: which fields a ``column_map`` may name for a type.

    The UI builds its mapping dropdown from this, so the picker and the validator can
    never disagree - both read the same frozen ``constants`` table.
    """

    source_type: ImportSourceType = Field(serialization_alias="sourceType")
    fields: list[str]
    required: list[str]


class ImportCommitQueued(BaseModel):
    """The accepted-for-import acknowledgement: the run id + that it was queued."""

    id: str
    queued: bool
    reason: str = ""


# --- Request models -----------------------------------------------------------


class ImportMappingSet(BaseModel):
    """POST /data-import/runs/{id}/mapping body: the column map to validate + persist.

    ``column_map`` is ``{source_header: target_field}``. The TARGET side is validated
    against the frozen allow-list before it is stored, so an unknown/duplicate/missing
    target is a 400 at this door - not a surprise in the worker.
    """

    model_config = ConfigDict(populate_by_name=True)

    column_map: dict[str, str] = Field(alias="columnMap", max_length=_MAX_MAP_ENTRIES)


class ImportMappingCreate(BaseModel):
    """POST /data-import/mappings body: save a reusable template.

    ``source_signature`` is optional: pass the signature of the file it was built from
    and a future upload of the same report auto-applies it.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=120)
    source_type: ImportSourceType = Field(alias="sourceType")
    column_map: dict[str, str] = Field(alias="columnMap", max_length=_MAX_MAP_ENTRIES)
    source_signature: str = Field(default="", alias="sourceSignature", max_length=128)
