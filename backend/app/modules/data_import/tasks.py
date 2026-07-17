"""Data-import worker: the streaming commit run + its Celery entry point.

One task, ``run_import``, built on the never-stuck / never-re-raise / idempotent worker
template (``workers.tasks.content`` / ``app.modules.keyword_research.tasks``). There is
NO cost gate here and no provider: an import is a file read, it buys nothing, and it
needs no key. What it does have instead is three failure modes worth naming:

* **Redelivery.** ``task_acks_late`` redelivers on any raise, and half these targets
  (``backlinks``/``citations``) have no natural key to conflict on - so a re-run would
  duplicate every row. The task therefore CLAIMS the run with a conditional UPDATE
  (``uploaded|mapping|validating -> importing``) and no-ops when the claim fails. It
  never re-raises.
* **Size.** The file is STREAMED row by row through ``storage.iter_rows`` (``csv`` over a
  file handle; ``openpyxl`` in ``read_only`` mode), never slurped: a 200MB export must not
  be a 2GB resident list. Rows are written in bounded batches and the error sample is
  capped, so memory is O(1) in the file's length. The readers live in ``storage.py``
  beside the store that owns the file - the upload route previews with the SAME reader,
  and importing it from here would drag Celery into the API process.
* **Bad data.** A row that will not coerce is counted and sampled, not fatal - one bad
  cell in row 40,000 must not discard the other 39,999. The run ends ``partial``.

Terminal states: ``imported`` (everything landed), ``partial`` (some rows rejected),
``failed`` (nothing landed, or a fatal error: no mapping, no file, past the row cap).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.config import Settings, get_settings
from app.logging_setup import get_logger
from app.modules.data_import.constants import ImportTarget, target_for
from app.modules.data_import.repo import (
    ImportTargetError,
    ServiceImportStore,
    service_import_store,
)
from app.modules.data_import.service import (
    RowError,
    clean_headers,
    coerce_row,
    derive_columns,
    row_is_importable,
    validate_mapping,
)
from app.modules.data_import.storage import (
    LocalImportStore,
    import_store_from_settings,
    iter_rows,
)

logger = get_logger("workers.data_import")

# Rows per INSERT. Bounded so one statement's parameter list stays sane (a 500-row x
# 7-column batch is 3,500 bound params, well inside libpq's 65,535 limit) and so a
# streamed import commits progress steadily instead of in one giant transaction.
_BATCH_ROWS = 500
# How many rejected rows are SAMPLED. The bound is the point: a file whose every row is
# malformed would otherwise write a million-entry jsonb blob into the run. rows_error
# still counts them ALL, so a truncated sample never reads as "only 50 were bad".
_ERROR_SAMPLE_MAX = 50


class _FatalError(RuntimeError):
    """A condition that ends the whole run (not one row): no mapping, no file, past the
    row cap. Carries the message the run's status records."""


def _row_dict(headers: list[str], values: list[Any]) -> dict[str, Any]:
    """Zip a data row onto the header row.

    A short row (trailing empties trimmed by the exporter) yields blanks rather than an
    IndexError; a long row's surplus cells are ignored - they have no header, so there is
    nothing they could map to.
    """
    return {h: (values[i] if i < len(values) else None) for i, h in enumerate(headers)}


def execute_import(
    store: ServiceImportStore,
    files: LocalImportStore | None,
    settings: Settings,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Stream one import run into its target table. Never raises.

    Claims the run (a redelivered/terminal run is a no-op), re-validates the persisted
    mapping against the allow-list, then streams -> coerces -> batches -> inserts,
    updating the counters as it goes. The mapping is re-validated HERE and not only at
    the router because this is the last gate before the privileged writer, and the run
    row could have been written by an older/other code path.
    """
    run = store.claim_run(run_id)
    if run is None:
        # Not claimable: already importing, already terminal, or gone. A redelivery
        # lands here and must do NOTHING - re-running would duplicate every row on the
        # targets that have no natural key.
        current = store.get_run(run_id)
        status = str(current.get("status")) if current else "missing"
        logger.info("data_import_noop", run_id=run_id, status=status)
        return {"state": "noop", "status": status, "reason": "not claimable (idempotent)"}

    state = _ImportState(run_id)
    try:
        return _run(store, files, settings, run=run, state=state)
    except _FatalError as fatal:
        return _fail(store, state, reason=str(fatal))
    except Exception as exc:  # never re-raise: acks_late would redeliver = double insert
        logger.exception("data_import_crashed", run_id=run_id)
        return _fail(store, state, reason=f"worker error: {exc!r}"[:300])


class _ImportState:
    """The run's live counters + its BOUNDED error sample."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.total = 0
        self.mapped = 0
        self.errors = 0
        self.sample: list[dict[str, Any]] = []

    def reject(self, row_number: int, field: str, value: str, reason: str) -> None:
        """Count a rejected row; sample it only while the sample is under its cap."""
        self.errors += 1
        if len(self.sample) < _ERROR_SAMPLE_MAX:
            self.sample.append(
                {"row": row_number, "field": field, "value": value, "reason": reason}
            )


def _run(
    store: ServiceImportStore,
    files: LocalImportStore | None,
    settings: Settings,
    *,
    run: dict[str, Any],
    state: _ImportState,
) -> dict[str, Any]:
    """The happy-path composition (resolve -> validate -> stream -> batch -> finish)."""
    source_type = str(run.get("source_type") or "")
    target = target_for(source_type)
    if target is None or target.table is None:
        raise _FatalError(f"'{source_type}' imports stage only - there is no target table")

    if files is None:
        raise _FatalError("no import store configured")
    path = files.resolve(str(run.get("stored_path") or ""))
    if path is None:
        # Either the key escapes the root (rejected by the store's traversal guard) or
        # the file is gone. Both are fatal and neither is worth distinguishing to a user.
        raise _FatalError("the uploaded file is unavailable")

    column_map = {str(k): str(v) for k, v in (run.get("column_map") or {}).items()}
    verdict = validate_mapping(source_type, column_map)
    if not verdict.ok:
        raise _FatalError(f"invalid column map: {verdict.message}")

    client_id = str(run["client_id"]) if run.get("client_id") else None
    if target.requires_client and client_id is None:
        # 0036's tracked_keywords.client_id is NOT NULL: a rankings import with no client
        # would fail at the constraint mid-batch. Say so cleanly instead.
        raise _FatalError(f"a {source_type} import requires a client")
    client_name = str(run.get("client_name") or "")
    max_rows = int(settings.import_max_rows)

    rows = iter_rows(path)
    headers = _read_headers(rows)
    batch: list[dict[str, Any]] = []

    for values in rows:
        if state.total >= max_rows:
            raise _FatalError(f"the file exceeds the {max_rows:,} row limit")
        if not any(v is not None and str(v).strip() for v in values):
            continue  # a blank separator line - not a row, not an error
        state.total += 1
        row_number = state.total + 1  # +1: the header row is line 1 to a human
        try:
            coerced = coerce_row(target, column_map, _row_dict(headers, values))
        except RowError as err:
            state.reject(row_number, err.field_name, err.value, err.reason)
            continue
        if not row_is_importable(target, coerced):
            state.reject(row_number, "row", "", "the row carries no importable value")
            continue
        coerced.update(
            derive_columns(
                target, coerced, client_id=client_id, client_name=client_name,
                run_id=state.run_id,
            )
        )
        batch.append(coerced)
        if len(batch) >= _BATCH_ROWS:
            _flush(store, target, batch, state)

    _flush(store, target, batch, state)
    return _finish(store, state)


def _read_headers(rows: Iterator[list[Any]]) -> list[str]:
    """Consume the header row off the stream (it is the first row)."""
    try:
        first = next(rows)
    except StopIteration:
        raise _FatalError("the file is empty") from None
    headers = clean_headers(first)
    if not headers:
        raise _FatalError("the file has no header row")
    return headers


def _flush(
    store: ServiceImportStore, target: ImportTarget, batch: list[dict[str, Any]], state: _ImportState
) -> None:
    """Write one batch and stream the counters. Empties ``batch`` in place.

    A batch that the DB rejects wholesale (a constraint the coercion did not model) is
    counted as errors rather than crashing the run: the other batches still land, and
    the sample names the failure. The alternative - re-raising - would redeliver the task
    and re-insert every batch that already succeeded.
    """
    if not batch:
        return
    try:
        written = store.insert_rows(target, batch)
        state.mapped += written
    except ImportTargetError:
        raise  # a programming error, not data: let the fatal handler mark the run failed
    except Exception as exc:
        logger.warning("data_import_batch_failed", run_id=state.run_id, error=repr(exc))
        for _ in batch:
            state.reject(0, "row", "", f"the database rejected this batch: {exc!r}"[:200])
    finally:
        batch.clear()
    store.update_progress(
        state.run_id, rows_total=state.total, rows_mapped=state.mapped, rows_error=state.errors
    )


def _finish(store: ServiceImportStore, state: _ImportState) -> dict[str, Any]:
    """Write the terminal verdict.

    ``imported`` only when everything landed. ``partial`` when some rows were rejected
    but others landed. ``failed`` when NOTHING landed - an import that wrote zero rows
    did not partially succeed, whatever the reason, and calling it ``partial`` would put
    a warn tone on a total failure.
    """
    if state.total == 0:
        return _fail(store, state, reason="the file has no data rows")
    if state.mapped == 0:
        return _fail(store, state, reason="every row was rejected")
    status = "partial" if state.errors else "imported"
    store.finish_run(
        state.run_id, status=status, rows_total=state.total, rows_mapped=state.mapped,
        rows_error=state.errors, error_sample=state.sample,
    )
    logger.info(
        "data_import_done", run_id=state.run_id, status=status, rows=state.total,
        mapped=state.mapped, errors=state.errors,
    )
    return {
        "state": status, "status": status, "rows": state.total,
        "mapped": state.mapped, "errors": state.errors,
    }


def _fail(store: ServiceImportStore, state: _ImportState, *, reason: str) -> dict[str, Any]:
    """Mark the run ``failed`` - never leave it stuck at ``importing``.

    The fail-write is itself guarded: even this must not raise out of the task, or
    acks_late would redeliver a run whose rows may already be written.
    """
    sample = [*state.sample, {"row": 0, "field": "", "value": "", "reason": reason}][
        :_ERROR_SAMPLE_MAX
    ]
    try:
        store.finish_run(
            state.run_id, status="failed", rows_total=state.total, rows_mapped=state.mapped,
            rows_error=state.errors, error_sample=sample,
        )
    except Exception:
        logger.warning("data_import_fail_write_failed", run_id=state.run_id)
    logger.info("data_import_failed", run_id=state.run_id, reason=reason)
    return {
        "state": "failed", "status": "failed", "reason": reason, "rows": state.total,
        "mapped": state.mapped, "errors": state.errors,
    }


# --------------------------------------------------------------------------- #
# Celery entry point (thin; import the app after the pure core, per the template)
# --------------------------------------------------------------------------- #
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


@celery_app.task(name="run_import")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def run_import(run_id: str) -> dict[str, Any]:
    """Entry point: wire the privileged store + the traversal-safe file store and stream
    the import.

    Wraps the core in a guard so the task NEVER re-raises (a redelivery would re-insert
    rows the targets cannot dedupe); a failure is returned as a ``failed`` result dict.
    """
    settings = get_settings()
    try:
        return execute_import(
            service_import_store(),
            import_store_from_settings(settings),
            settings,
            run_id=run_id,
        )
    except Exception:
        logger.exception("run_import_task_failed", run_id=run_id)
        return {"state": "failed", "status": "failed", "reason": "task failed"}
