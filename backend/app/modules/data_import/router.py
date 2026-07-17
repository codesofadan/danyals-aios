"""Data-import module endpoints (Part 8 Phase 2G): the FILE-import pipeline.

No ``frontend/lib/*.ts`` type mirrors this module - the responses are
SERVER-AUTHORITATIVE (``schemas.py`` owns the shape + its own shape/enum tests). The
``GET /data-import/workspace`` adapter emits the ``lib/tools.ts`` ``data_import`` EXTRA
shape (KPIs + the recent-imports table + the CTA), with table columns pinned to
``tests/test_tool_workspace_contract.py``.

Tables owned: ``import_runs`` / ``import_mappings`` / ``search_console_rows`` (migration
``0042_data_import``). Cost-gate dial: NONE, deliberately - this module is KEYLESS. It
imports a file a human already exported; it calls no provider, holds no key and spends
nothing, so there is no dial to gate and no ``GateContext`` anywhere in it. (Live
GSC/GA API integration is explicitly out of contract scope; this file path is the
contracted way that data arrives.)

Access: every route requires the ``data_import`` FEATURE grant. Reads add
``view_reports``; every mutation adds ``manage_clients``.

WHY ``manage_clients`` and not the ``run_research`` module perm: ``run_research`` exists
specifically to gate PAID research spend (see ``rbac/matrix.py`` - "gates the paid
keyword research"), and an import buys nothing, so borrowing it would misdescribe the
action. The closest sibling by NATURE is ``client_onboarding`` - the other keyless,
client-data staff tool - which uses ``require_perm("manage_clients")``, and an import IS
client-data administration: it loads a client's keywords, backlinks, citations and
performance rows. Both keys resolve to exactly the same holder set
(owner/admin/manager), which is byte-for-byte the RLS insert/update policy on 0042 AND
on every target table this module writes into (0018 backlinks/citations, 0035 keywords,
0036 tracked_keywords), so the app gate and the database agree either way and the choice
costs no privilege. ``manage_clients`` IS in ``DEFAULT_ROLE_PERMS``, so it correctly goes
through ``require_perm``; a ModulePermKey would need ``require_module_perm`` instead.

The internal ``client_id`` never leaks (``client`` is the snapshotted name) and neither
does ``stored_path`` (``file`` is the original display name). Every mutation offloads the
blocking psycopg call with ``asyncio.to_thread`` and records an activity entry
(kind=client, entity=client - omitted for an agency-global import, which touches no
client) so the import work keeps each client's context fresh.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.core.auth import CurrentUser, require_feature, require_perm
from app.core.deps import SettingsDep
from app.core.pagination import PageDep
from app.logging_setup import get_logger
from app.modules.data_import.constants import (
    ALLOWED_CONTENT_TYPES,
    ALLOWED_EXTENSIONS,
    TERMINAL_STATUSES,
    ImportSourceType,
    target_for,
)
from app.modules.data_import.repo import ImportRepoDep
from app.modules.data_import.schemas import (
    ImportColumnPreview,
    ImportCommitQueued,
    ImportFieldsResponse,
    ImportMappingCreate,
    ImportMappingResponse,
    ImportMappingSet,
    ImportRunDetail,
    ImportRunResponse,
    ImportStats,
    ImportUploadResponse,
)
from app.modules.data_import.service import (
    SAMPLE_VALUES,
    build_workspace,
    clean_headers,
    extension_of,
    header_signature,
    safe_display_name,
    sniff_kind,
    suggest_mapping,
    validate_mapping,
)
from app.modules.data_import.storage import (
    ImportRejectedError,
    ImportTooLargeError,
    LocalImportStore,
    import_store_from_settings,
    iter_rows,
    read_head,
    write_upload,
)
from app.schemas.tool_workspace import ToolExtraResponse
from app.services.activity import record_activity

logger = get_logger("api.data_import")

router = APIRouter(tags=["data-import"])

# Every tool route requires the fine-grained data_import feature grant (owner is
# all-on). Reads additionally require view_reports; every mutation requires
# manage_clients - held by the leads (owner/admin/manager), mirroring the 0042 RLS
# insert/update policies exactly. See the module docstring for why manage_clients rather
# than the run_research MODULE perm (this module is keyless; run_research gates paid
# spend). manage_clients IS a PermKey, so require_perm is the correct door.
Feature = Annotated[CurrentUser, Depends(require_feature("data_import"))]
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
ManageClients = Annotated[CurrentUser, Depends(require_perm("manage_clients"))]

_RUN_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import run not found")
_CLIENT_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
_NOT_CONFIGURED = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="File imports are not configured (no import root)",
)

# How many header cells' sample values the upload preview reads. Bounded: the preview
# reads only the first data rows, never the whole file.
_PREVIEW_ROWS = 20


def get_import_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the import worker (overridable in tests).

    The Celery task is imported lazily so the API process never pulls in the task module
    just to import this router (mirrors ``get_research_enqueuer``)."""

    def _enqueue(run_id: str) -> None:
        from app.modules.data_import.tasks import run_import

        run_import.delay(run_id)

    return _enqueue


ImportEnqueuerDep = Annotated[Callable[[str], None], Depends(get_import_enqueuer)]


def get_import_store(settings: SettingsDep) -> LocalImportStore | None:
    """Dependency: the traversal-safe upload store, or ``None`` when unconfigured."""
    return import_store_from_settings(settings)


ImportStoreDep = Annotated[LocalImportStore | None, Depends(get_import_store)]


def _client_entity(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """The context entity an import mutation touches - the CLIENT the run belongs to, or
    unlinked (both ``None``) for an agency-global import."""
    client_id = row.get("client_id")
    return ("client", str(client_id)) if client_id is not None else (None, None)


# --- reads --------------------------------------------------------------------


@router.get("/data-import/runs", response_model=list[ImportRunResponse])
async def list_runs(
    repo: ImportRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
    run_status: Annotated[str | None, Query(alias="status")] = None,
    source_type: Annotated[ImportSourceType | None, Query(alias="sourceType")] = None,
) -> list[ImportRunResponse]:
    """The import ledger (newest first), optionally narrowed by client, status or type."""
    rows = await asyncio.to_thread(
        repo.list_runs,
        client_id=client_id,
        status=run_status,
        source_type=source_type,
        limit=page.limit,
        offset=page.offset,
    )
    return [ImportRunResponse.from_row(r) for r in rows]


@router.get("/data-import/runs/{run_id}", response_model=ImportRunDetail)
async def get_run(
    run_id: str, repo: ImportRepoDep, _feat: Feature, _user: ViewReports
) -> ImportRunDetail:
    """One run + its BOUNDED error sample (what was rejected, which column, why)."""
    row = await asyncio.to_thread(repo.get_run, run_id)
    if row is None:
        raise _RUN_NOT_FOUND
    return ImportRunDetail.from_row(row)


@router.get("/data-import/stats", response_model=ImportStats)
async def import_stats(repo: ImportRepoDep, _feat: Feature, _user: ViewReports) -> ImportStats:
    """The summary tiles: imports in the last 30 days, rows mapped, rows rejected."""
    row = await asyncio.to_thread(repo.import_stats)
    return ImportStats.from_row(row)


@router.get("/data-import/workspace", response_model=ToolExtraResponse)
async def import_workspace(
    repo: ImportRepoDep, _feat: Feature, _user: ViewReports
) -> ToolExtraResponse:
    """The tool workspace (``lib/tools.ts`` ``data_import`` shape): KPI tiles, the
    recent-imports table (cols ``File|Type|Rows|Status``), and the CTA."""
    stats = await asyncio.to_thread(repo.import_stats)
    runs = await asyncio.to_thread(repo.list_runs, limit=8, offset=0)
    return build_workspace(stats, runs)


@router.get("/data-import/fields", response_model=ImportFieldsResponse)
async def import_fields(
    source_type: Annotated[ImportSourceType, Query(alias="sourceType")],
    _feat: Feature,
    _user: ViewReports,
) -> ImportFieldsResponse:
    """The ALLOW-LIST for a source type - the only fields a column map may name.

    Published so the UI's mapping picker is built from the same frozen table the
    validator enforces; the two can never drift apart.
    """
    target = target_for(source_type)
    fields = list(target.field_names) if target else []
    required = [f.name for f in target.fields if f.required] if target else []
    return ImportFieldsResponse(source_type=source_type, fields=fields, required=required)


@router.get("/data-import/mappings", response_model=list[ImportMappingResponse])
async def list_mappings(
    repo: ImportRepoDep,
    _feat: Feature,
    _user: ViewReports,
    source_type: Annotated[ImportSourceType | None, Query(alias="sourceType")] = None,
) -> list[ImportMappingResponse]:
    """The saved mapping templates, optionally for one source type."""
    rows = await asyncio.to_thread(repo.list_mappings, source_type=source_type)
    return [ImportMappingResponse.from_row(r) for r in rows]


# --- mutations ----------------------------------------------------------------


@router.post(
    "/data-import/uploads",
    response_model=ImportUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_import(
    repo: ImportRepoDep,
    files: ImportStoreDep,
    settings: SettingsDep,
    _feat: Feature,
    actor: ManageClients,
    file: Annotated[UploadFile, File()],
    source_type: Annotated[ImportSourceType, Form(alias="sourceType")],
    client_id: Annotated[str | None, Form(alias="clientId")] = None,
) -> ImportUploadResponse:
    """Upload a CSV/TSV/XLSX export: store it, sniff its columns, suggest a mapping.

    Four gates run before a single byte is kept, and each catches something the others
    do not:

    1. **Extension** - must be in the allow-list (``.csv``/``.tsv``/``.xlsx``).
    2. **Declared MIME** - must be in the allow-list. ``application/octet-stream`` is not
       accepted: it is what a client sends when it knows nothing, and honouring it would
       make this gate decorative.
    3. **Content-Length** - refused up front when it already exceeds the cap, so an
       obviously-oversized upload costs zero disk.
    4. **The bytes themselves** - the stream is byte-counted against the cap as it lands
       (a Content-Length is a claim, and a chunked body has none), and the head is
       SNIFFED: a ``.csv`` that is really a ZIP/PDF/ELF, or an ``.xlsx`` that is not a
       ZIP, is deleted and rejected. The extension is what the uploader says; the magic
       bytes are what it is.

    The stored name is GENERATED (``<uuid4hex>.<ext>``) under the traversal-safe root, so
    a crafted filename is never a path - it survives only as ``filename``, a display
    string. A client-scoped upload snapshots the client name (404 if unknown); a
    client-less upload is a valid agency-global import.
    """
    if files is None:
        raise _NOT_CONFIGURED

    display_name = safe_display_name(file.filename or "")
    extension = extension_of(display_name)
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: only {', '.join(sorted(ALLOWED_EXTENSIONS))} are accepted",
        )
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported content type '{content_type or 'unknown'}'",
        )

    max_bytes = int(settings.import_max_file_bytes)
    # The cheap pre-check: the parser already knows the part's size, so refuse an
    # obviously-oversized body before writing anything. The streamed count below is what
    # actually enforces the cap - this only saves the disk write.
    if file.size is not None and file.size > max_bytes:
        raise _too_large(max_bytes)

    client_name = ""
    if client_id:
        resolved = await asyncio.to_thread(repo.client_name_for, client_id)
        if resolved is None:
            raise _CLIENT_NOT_FOUND
        client_name = resolved

    target = target_for(source_type)
    if target is not None and target.requires_client and not client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A {source_type} import requires a client",
        )

    key = files.new_key(extension)
    try:
        size, digest = await write_upload(files, key, file, max_bytes=max_bytes)
    except ImportTooLargeError as exc:
        raise _too_large(max_bytes) from exc
    except ImportRejectedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not size:
        files.delete(key)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The file is empty")

    # SNIFF the stored bytes. This is the gate the extension cannot provide.
    stored = files.resolve(key)
    if stored is None or sniff_kind(await asyncio.to_thread(read_head, stored), extension) is None:
        files.delete(key)
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"The file's contents are not a valid .{extension} file",
        )

    # A parse failure here is the USER's file being unreadable, not a server fault - and
    # the sniff cannot catch every case: a plain ZIP renamed to .xlsx passes it (an xlsx
    # IS a zip). Left unhandled that is a 500 plus an orphaned upload.
    #
    # The cleanup runs OUTSIDE the except block on purpose. Inside it, the live exception
    # (and its traceback) still references the parser's frames - and therefore any file
    # handle they hold - which on Windows makes `unlink` fail silently and orphans the
    # very file we are rejecting. Letting the exception go out of scope first is what
    # makes the delete actually take effect.
    parse_failed = False
    headers: list[str] = []
    previews: dict[str, list[str]] = {}
    try:
        headers, previews = await asyncio.to_thread(_preview, stored)
    except Exception:
        logger.info("data_import_upload_unreadable", extension=extension)
        parse_failed = True
    if parse_failed:
        files.delete(key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The file could not be read as a .{extension} file",
        )
    if not headers:
        files.delete(key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The file has no header row"
        )

    suggested = suggest_mapping(headers, source_type)
    template = await asyncio.to_thread(
        repo.find_mapping_for, source_type, header_signature(headers)
    )
    row = await asyncio.to_thread(
        repo.create_run,
        client_id=client_id or None,
        client_name=client_name,
        filename=display_name,
        stored_path=key,
        source_type=source_type,
        detected_columns=headers,
        column_map=(template or {}).get("column_map") or suggested,
        content_sha256=digest,
        uploaded_by=actor.id,
    )
    if row is None:  # pragma: no cover - an RLS refusal would already have raised
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not record the upload"
        )

    ent_type, ent_id = ("client", client_id) if client_id else (None, None)
    await record_activity(
        actor, kind="client", action=f"uploaded '{display_name}' for import",
        target=client_name, entity_type=ent_type, entity_id=ent_id,
    )
    return ImportUploadResponse(
        run=ImportRunResponse.from_row(row),
        columns=[ImportColumnPreview(column=c, samples=s) for c, s in previews.items()],
        suggested=suggested,
        template=ImportMappingResponse.from_row(template) if template else None,
    )


@router.post("/data-import/runs/{run_id}/mapping", response_model=ImportRunResponse)
async def set_mapping(
    run_id: str,
    body: ImportMappingSet,
    repo: ImportRepoDep,
    _feat: Feature,
    actor: ManageClients,
) -> ImportRunResponse:
    """Validate a column map against the ALLOW-LIST and persist it (-> ``mapping``).

    A map naming a field outside its type's allow-list, mapping one field twice, missing
    a required field, or naming a column this file does not have, is a 400 HERE - the
    worker never sees an unvalidated map, and a target column name can only ever be one
    of the frozen literals in ``constants``.
    """
    run = await asyncio.to_thread(repo.get_run, run_id)
    if run is None:
        raise _RUN_NOT_FOUND
    if str(run.get("status")) in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This import is already {run.get('status')}",
        )

    detected = [str(c) for c in (run.get("detected_columns") or [])]
    verdict = validate_mapping(str(run.get("source_type") or ""), body.column_map, detected)
    if not verdict.ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=verdict.message)

    row = await asyncio.to_thread(repo.set_mapping, run_id, body.column_map)
    if row is None:
        raise _RUN_NOT_FOUND
    ent_type, ent_id = _client_entity(row)
    await record_activity(
        actor, kind="client", action=f"mapped the import '{row.get('filename', '')}'",
        target=str(row.get("client_name", "") or ""), entity_type=ent_type, entity_id=ent_id,
    )
    return ImportRunResponse.from_row(row)


@router.post(
    "/data-import/runs/{run_id}/commit",
    response_model=ImportCommitQueued,
    status_code=status.HTTP_202_ACCEPTED,
)
async def commit_run(
    run_id: str,
    repo: ImportRepoDep,
    _feat: Feature,
    actor: ManageClients,
    enqueue: ImportEnqueuerDep,
) -> ImportCommitQueued:
    """Enqueue the import: stream the file, map it, and write it into the target table.

    Re-validates the persisted map (the allow-list gate, again - the worker re-runs it
    too, since it is the last door before the privileged writer) and refuses a run that
    is already terminal. The work itself is the worker's: it claims the run atomically,
    so a double-click enqueues twice but imports once.
    """
    run = await asyncio.to_thread(repo.get_run, run_id)
    if run is None:
        raise _RUN_NOT_FOUND
    run_status = str(run.get("status") or "")
    if run_status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"This import is already {run_status}"
        )
    if run_status == "importing":
        # Already claimed and draining. Honest no-op rather than a second enqueue.
        return ImportCommitQueued(id=run_id, queued=False, reason="the import is already running")

    source_type = str(run.get("source_type") or "")
    column_map = {str(k): str(v) for k, v in (run.get("column_map") or {}).items()}
    verdict = validate_mapping(source_type, column_map)
    if not verdict.ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=verdict.message)

    enqueue(run_id)
    ent_type, ent_id = _client_entity(run)
    await record_activity(
        actor, kind="client", action=f"imported '{run.get('filename', '')}'",
        target=str(run.get("client_name", "") or ""), entity_type=ent_type, entity_id=ent_id,
    )
    return ImportCommitQueued(id=run_id, queued=True)


@router.post(
    "/data-import/mappings",
    response_model=ImportMappingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_mapping(
    body: ImportMappingCreate, repo: ImportRepoDep, _feat: Feature, actor: ManageClients
) -> ImportMappingResponse:
    """Save a reusable mapping template (validated against the same allow-list).

    A template is validated at SAVE time, not only at use: an invalid one saved today
    would otherwise auto-apply itself to a matching file months later and fail there,
    far from the mistake.
    """
    verdict = validate_mapping(body.source_type, body.column_map)
    if not verdict.ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=verdict.message)
    row = await asyncio.to_thread(
        repo.create_mapping,
        name=body.name,
        source_type=body.source_type,
        column_map=body.column_map,
        source_signature=body.source_signature,
        created_by=actor.id,
    )
    if row is None:  # pragma: no cover - an RLS refusal would already have raised
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not save the mapping"
        )
    await record_activity(
        actor, kind="client", action=f"saved the import mapping '{body.name}'", target=body.name,
    )
    return ImportMappingResponse.from_row(row)


# --- helpers ------------------------------------------------------------------


def _too_large(max_bytes: int) -> HTTPException:
    # HTTP_413_CONTENT_TOO_LARGE is the current Starlette spelling; the older
    # HTTP_413_REQUEST_ENTITY_TOO_LARGE alias is deprecated. Same 413 either way.
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"The file exceeds the {max_bytes:,} byte limit",
    )


def _preview(path: Path) -> tuple[list[str], dict[str, list[str]]]:
    """The header row + a BOUNDED sample of each column's values.

    Reads at most ``_PREVIEW_ROWS`` data rows through the SAME streaming reader the
    worker uses (``storage.iter_rows``), so a 200MB upload previews in constant memory
    and constant time - and so the preview can never disagree with the import about what
    the file's columns are. Blocking; offloaded.
    """
    rows = iter_rows(path)
    try:
        headers = clean_headers(next(rows))
    except StopIteration:
        return [], {}
    if not headers:
        return [], {}

    samples: dict[str, list[str]] = {h: [] for h in headers}
    for _, values in zip(range(_PREVIEW_ROWS), rows, strict=False):
        for i, header in enumerate(headers):
            cell = str(values[i]).strip() if i < len(values) and values[i] is not None else ""
            bucket = samples[header]
            if cell and len(bucket) < SAMPLE_VALUES and cell not in bucket:
                bucket.append(cell[:120])
    return headers, samples
