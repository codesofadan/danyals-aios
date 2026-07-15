"""Google Sheets seam (7D): the ONLY door to a Google Sheets workbook.

v1 reporting runs on Google Sheets via a SERVICE ACCOUNT. The operational store
(``app/services/sheetstore.py``) buffers module writes in Redis and, on flush, emits
ONE batched ``spreadsheets.values.batchUpdate`` per workbook - quota-safe. That call
is reachable exclusively through the ``SheetsClient`` Protocol so the SheetStore can
hold a real client or a fake with the SAME read/write shape.

Two impls satisfy the Protocol, mirroring the content/context seams exactly:

* ``GoogleSheetsClient`` - real, backed by the Sheets API v4. KEY-GATED on a
  service-account credential JSON (``GOOGLE_SHEETS_SA_JSON``); the ``google-*`` client
  libs are LAZILY imported (an OPTIONAL extra, absent from the base install so the
  gate stays light). Absent creds/libs -> ``ProviderNotConfiguredError`` naming the
  fix. The credential JSON (which carries a private key) is NEVER logged; only the
  non-secret ``client_email`` / ``project_id`` are exposed for the connection panel.
* ``FakeSheetsClient`` - deterministic, in-memory: records every ``batch_update`` into
  a per-spreadsheet/per-tab store and counts the calls, so SheetStore batching tests
  run fully live with zero creds.

``sheets_client_from_settings`` assembles the real client when a credential is
present and degrades to ``None`` otherwise (or when the libs are missing) - the
SheetStore then runs in a HELD/degraded mode until the key lands, exactly as the
context compactor holds its watermark.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from app.logging_setup import get_logger
from integrations.errors import ProviderCallError, ProviderNotConfiguredError

if TYPE_CHECKING:
    from app.config import Settings

logger = get_logger("integrations.sheets")

_INSTALL_HINT = (
    "install the sheets extra (google-api-python-client + google-auth) and set "
    "GOOGLE_SHEETS_SA_JSON to a service-account credential JSON"
)
# The Sheets API scope the service account writes with (spreadsheets read/write).
_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
# batchUpdate valueInputOption: RAW writes cells exactly as given (no locale parsing).
_VALUE_INPUT_OPTION = "RAW"


@dataclass(frozen=True)
class SheetRange:
    """One tab's worth of rows to write in a batched update.

    ``tab`` is the sheet tab title; ``rows`` is row-major cell values (each inner list
    is one row). The store anchors the write at ``{tab}!A1`` and the API fills down.
    """

    tab: str
    rows: list[list[Any]]


@runtime_checkable
class SheetsClient(Protocol):
    """Write to a Google Sheets workbook. ONE batched call per flush (quota-safe).

    ``batch_update`` applies EVERY range to ``spreadsheet_id`` in a single API round
    trip and returns the total number of rows written. An empty ``ranges`` is a no-op
    returning 0.
    """

    def batch_update(self, spreadsheet_id: str, ranges: list[SheetRange]) -> int: ...


def _rows_in(ranges: list[SheetRange]) -> int:
    """Total rows across every range (the batch's write size)."""
    return sum(len(r.rows) for r in ranges)


class GoogleSheetsClient:
    """Real ``SheetsClient`` backed by the Sheets API v4 (service-account auth).

    The credential JSON is parsed once at construction (lazily importing the google
    client libs); a genuinely absent lib/credential raises
    ``ProviderNotConfiguredError`` naming the fix. The private key never leaves this
    object and is never logged - only ``service_account_email`` / ``project_id`` (both
    non-secret) are exposed for the connection panel.
    """

    def __init__(self, *, credentials_json: str, timeout: float = 30.0) -> None:
        if not credentials_json:
            raise ProviderNotConfiguredError(f"Google Sheets client unavailable: {_INSTALL_HINT}")
        try:
            info = json.loads(credentials_json)
        except ValueError as exc:
            # Never echo the raw JSON (it carries the private key) - just the reason.
            raise ProviderNotConfiguredError(
                "Google Sheets client unavailable: GOOGLE_SHEETS_SA_JSON is not valid JSON"
            ) from exc
        if not isinstance(info, dict):
            raise ProviderNotConfiguredError(
                "Google Sheets client unavailable: GOOGLE_SHEETS_SA_JSON must be a JSON object"
            )
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:  # libs are an optional extra, absent from base install
            raise ProviderNotConfiguredError(
                f"Google Sheets client unavailable: {_INSTALL_HINT}"
            ) from exc
        # Non-secret identity metadata for the connection panel (never the key).
        self.service_account_email: str = str(info.get("client_email", ""))
        self.project_id: str = str(info.get("project_id", ""))
        self._timeout = timeout
        try:
            credentials = service_account.Credentials.from_service_account_info(
                info, scopes=list(_SCOPES)
            )
            # cache_discovery=False avoids a noisy file-cache warning + a disk write.
            service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        except Exception as exc:
            # A malformed credential (missing private key, bad type, ...). Never echo
            # the JSON - just name the setting to fix.
            raise ProviderNotConfiguredError(
                "Google Sheets client unavailable: GOOGLE_SHEETS_SA_JSON is not a valid "
                "service-account credential"
            ) from exc
        self._values = service.spreadsheets().values()

    def batch_update(self, spreadsheet_id: str, ranges: list[SheetRange]) -> int:
        if not ranges:
            return 0
        data = [
            {"range": f"{r.tab}!A1", "values": [list(row) for row in r.rows]}
            for r in ranges
        ]
        body = {"valueInputOption": _VALUE_INPUT_OPTION, "data": data}
        try:
            response = self._values.batchUpdate(
                spreadsheetId=spreadsheet_id, body=body
            ).execute(num_retries=3)
        except Exception as exc:  # any transport / API error -> a clean seam error
            # The URL/body are never logged (they could echo cell data); only the id.
            logger.error("sheets_batch_update_failed", spreadsheet_id=spreadsheet_id)
            raise ProviderCallError("Google Sheets batchUpdate failed") from exc
        updated = response.get("totalUpdatedRows") if isinstance(response, dict) else None
        try:
            return int(updated) if updated is not None else _rows_in(ranges)
        except (TypeError, ValueError):
            return _rows_in(ranges)


class FakeSheetsClient:
    """Deterministic, in-memory ``SheetsClient`` for the SheetStore batching tests.

    Every ``batch_update`` is recorded into ``store[spreadsheet_id][tab]`` (rows
    appended) and ``calls`` counts the API round trips, so a test can prove that N
    buffered writes flush in exactly ONE batched call. No network.
    """

    def __init__(self) -> None:
        self.store: dict[str, dict[str, list[list[Any]]]] = {}
        self.calls: int = 0
        self.batches: list[tuple[str, list[SheetRange]]] = []

    def batch_update(self, spreadsheet_id: str, ranges: list[SheetRange]) -> int:
        if not ranges:
            return 0
        self.calls += 1
        self.batches.append((spreadsheet_id, list(ranges)))
        book = self.store.setdefault(spreadsheet_id, {})
        for r in ranges:
            book.setdefault(r.tab, []).extend(list(row) for row in r.rows)
        return _rows_in(ranges)


@dataclass(frozen=True)
class SheetsConnectionInfo:
    """The (non-secret) identity of a configured Sheets service account, or the empty
    degraded form when no credential is present."""

    connected: bool
    service_account_email: str = ""
    project_id: str = ""
    scope: str = "spreadsheets · drive.file"


def sheets_client_from_settings(settings: Settings) -> SheetsClient | None:
    """A real ``GoogleSheetsClient`` when a credential is present, else ``None``.

    Degrades to ``None`` (never raises) when the credential is absent OR the google
    client libs are not installed - the SheetStore then runs HELD until the key lands.
    No secret is ever logged; the degraded path logs only the reason.
    """
    creds = settings.google_sheets_sa_json
    if not creds:
        logger.info("sheets_client_degraded", reason="missing_credentials")
        return None
    try:
        return GoogleSheetsClient(credentials_json=creds.get_secret_value())
    except ProviderNotConfiguredError as exc:
        logger.info("sheets_client_degraded", reason=str(exc))
        return None


def connection_info_from_settings(settings: Settings) -> SheetsConnectionInfo:
    """The connection panel's service-account identity (non-secret) from settings.

    Returns the degraded (``connected=False``) form when no credential resolves - so
    the connection endpoint can render the panel without ever touching the key.
    """
    client = sheets_client_from_settings(settings)
    if not isinstance(client, GoogleSheetsClient):
        return SheetsConnectionInfo(connected=False)
    return SheetsConnectionInfo(
        connected=True,
        service_account_email=client.service_account_email,
        project_id=client.project_id,
    )
