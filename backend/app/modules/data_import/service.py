"""Data-import orchestration - the PURE core + the tool-workspace adapter.

DB-free, network-free, filesystem-free (mirrors ``keyword_research``'s pure core): it
takes header strings and cell strings and turns them into a validated mapping and typed
rows - deterministic given the same inputs. The streaming read + the DB writes live in
``tasks.py``; the RLS reads live in ``repo.py``; the traversal-safe store lives in
``storage.py``; this layer just reasons.

Four things here carry real semantics worth reading before changing them:

1. **Validation is the injection boundary's enforcement half.** ``validate_mapping``
   rejects a ``column_map`` whose TARGET names anything outside ``constants``' frozen
   allow-list. This is the single most important function in the module: without it a
   ``column_map`` would name an arbitrary column and the privileged writer would write
   it. It also rejects duplicate targets (two source columns silently fighting over one
   field) and a missing required field.

2. **Sniffing does not trust the extension.** ``sniff_kind`` reads the magic bytes. A
   ``.csv`` that is really a ZIP/PDF/ELF is rejected, and so is an ``.xlsx`` that is not
   a ZIP - the extension is the uploader's claim, the bytes are the evidence.

3. **Coercion is honest about failure.** A cell that cannot become its column's type is
   a ROW ERROR carrying the field + the offending value, never a silent 0. ``or 0`` on a
   position or a CTR would fabricate data the client is judged on.

4. **CTR arrives as a percentage and the column is a fraction.** GSC ships "3.41%" (and
   sometimes a bare 3.41); ``search_console_rows.ctr`` is numeric(6,4) holding 0.0341.
   ``_coerce_ctr`` converts rather than storing a 341% click-through rate.

``build_workspace`` is the ``GET /data-import/workspace`` adapter: it emits the frontend
``lib/tools.ts`` ``data_import`` EXTRA shape with table columns pinned EXACTLY to
``["File", "Type", "Rows", "Status"]`` (the tool-workspace contract test asserts this
byte-for-byte).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from urllib.parse import urlsplit

from app.modules.data_import.constants import (
    SOURCE_TYPE_LABELS,
    ImportTarget,
    TargetField,
    allowed_fields,
    target_for,
)
from app.schemas.offpage import action_for
from app.schemas.tool_workspace import (
    ToolCell,
    ToolCellObj,
    ToolExtraResponse,
    ToolKpi,
    ToolPrimary,
    ToolTable,
)
from integrations.keyword_data import normalize_intent

# --- tool-workspace contract constants (pinned to lib/tools.ts data_import) ---
WORKSPACE_TABLE_COLS: list[str] = ["File", "Type", "Rows", "Status"]
_WORKSPACE_TABLE_TITLE = "Recent imports"
_WORKSPACE_TABLE_ICON = "upload_file"
_WORKSPACE_PRIMARY = ToolPrimary(label="Upload file", icon="upload_file")
_WORKSPACE_BULLETS = [
    "Upload CSV / Excel exports",
    "Map columns to fields",
    "Validate & import in bulk",
]
_WORKSPACE_ROW_LIMIT = 8

# How many distinct cell values the upload preview shows per detected column. Bounded:
# a preview is for a human to recognise the file, not to stream it back.
SAMPLE_VALUES = 3
# How many header cells / how long a header may be. A crafted 10k-column file must not
# turn a preview into a DoS.
MAX_COLUMNS = 200
MAX_HEADER_LEN = 200

_WS_RE = re.compile(r"[^a-z0-9]+")
# Thousands separators as the real exports ship them: a comma, ordinary whitespace,
# and the two Unicode spaces a spreadsheet actually emits - U+00A0 NO-BREAK SPACE
# (Excel, most European locales) and U+202F NARROW NO-BREAK SPACE (fr-FR). Both are
# written as ESCAPES rather than pasted: an invisible literal in a character class is
# unreviewable, and a reader cannot tell it from a plain space. A RAW string keeps both
# escapes intact for ``re`` to parse (it understands \s and \uXXXX alike).
_NUM_CLEAN_RE = re.compile(r"[,\s\u00a0\u202f]")

# Magic-byte prefixes that are definitively NOT a spreadsheet the module reads as text.
# ZIP is listed separately because it IS xlsx's signature (an xlsx is a zip).
_ZIP_MAGIC = b"PK\x03\x04"
_BINARY_MAGICS: tuple[bytes, ...] = (
    b"%PDF",              # PDF
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"\xff\xd8\xff",      # JPEG
    b"GIF8",              # GIF
    b"\x7fELF",           # ELF executable
    b"MZ",                # DOS/PE executable
    b"\xd0\xcf\x11\xe0",  # OLE2 (legacy .xls / .doc) - not xlsx, not text
    b"\x1f\x8b",          # gzip
    b"BZh",               # bzip2
    b"Rar!",              # RAR
    b"SQLite format 3",   # SQLite database
)


# --------------------------------------------------------------------------- #
# Header normalisation + fingerprinting
# --------------------------------------------------------------------------- #
def normalize_header(raw: Any) -> str:
    """Fold a header cell to its comparison form: lowercase, punctuation -> space,
    whitespace collapsed, trimmed.

    ``"Page ASCORE"`` -> ``"page ascore"``; ``"Avg. Position"`` -> ``"avg position"``;
    ``"CTR (%)"`` -> ``"ctr"``. This is what the alias tables in ``constants`` are
    written against, so a vendor's punctuation churn never breaks auto-mapping.
    """
    text = str(raw or "").strip().lower()
    return _WS_RE.sub(" ", text).strip()


def header_signature(headers: list[str]) -> str:
    """A stable fingerprint of a file's header ROW - the key a saved template matches on.

    Order-insensitive (sorted) because vendors reorder columns between exports while the
    report stays the same; normalized so case/punctuation churn does not miss. Hashed so
    a signature is a bounded, index-friendly string rather than a whole header row.
    """
    parts = sorted({normalize_header(h) for h in headers if normalize_header(h)})
    if not parts:
        return ""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def clean_headers(raw: list[Any]) -> list[str]:
    """The detected column list: trimmed display headers, blanks dropped, bounded.

    Headers are kept in their ORIGINAL display form (that is what the user maps against
    in the UI and what ``column_map``'s keys are); only the comparison form is folded.
    """
    out: list[str] = []
    for cell in raw[:MAX_COLUMNS]:
        text = str(cell).strip() if cell is not None else ""
        if text:
            out.append(text[:MAX_HEADER_LEN])
    return out


# --------------------------------------------------------------------------- #
# Sniffing - the bytes decide, not the extension
# --------------------------------------------------------------------------- #
def sniff_kind(head: bytes, extension: str) -> str | None:
    """The file's REAL kind (``csv`` | ``tsv`` | ``xlsx``), or ``None`` to reject.

    The extension is the uploader's CLAIM; these bytes are the evidence, and they must
    agree:

    * a ZIP header is an xlsx - and only legal when the claim was ``.xlsx``;
    * an ``.xlsx`` claim with no ZIP header is a lie (a renamed CSV, or worse);
    * any other known binary magic, or a NUL byte, or bytes that are not decodable
      text, is not a delimited text file whatever it is called.
    """
    ext = extension.lower().lstrip(".")
    if ext not in ("csv", "tsv", "xlsx"):
        return None
    if head.startswith(_ZIP_MAGIC):
        # An xlsx IS a zip. A .csv that is a zip is not a csv.
        return "xlsx" if ext == "xlsx" else None
    if ext == "xlsx":
        return None  # claimed xlsx, but not a zip container
    if any(head.startswith(magic) for magic in _BINARY_MAGICS):
        return None
    if b"\x00" in head:
        return None  # NULs never appear in a delimited text export
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        try:
            head.decode("latin-1")
        except UnicodeDecodeError:
            return None
        # latin-1 decodes ANY byte, so it is not proof of text on its own; the NUL +
        # magic checks above are what actually excluded binary. A legacy-encoded CSV
        # (Excel still emits cp1252) is a real, readable file and is accepted.
    return "tsv" if ext == "tsv" else "csv"


def extension_of(filename: str) -> str:
    """The lowercase extension of a DISPLAY filename, without the dot ('' if none).

    Reads only the last dot of the last path segment, so ``"../../etc/passwd"`` yields
    ``""`` (rejected by the allow-list) and ``"a.tar.gz"`` yields ``"gz"``.
    """
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def safe_display_name(filename: str) -> str:
    """The ORIGINAL name reduced to a bounded, path-free DISPLAY string.

    This never builds a path (the store generates its own name), so this is about not
    rendering a 4KB name or a directory tree into a table cell - not about traversal.
    """
    base = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return base[:255] or "upload"


# --------------------------------------------------------------------------- #
# Auto-suggest mapping
# --------------------------------------------------------------------------- #
def suggest_mapping(headers: list[str], source_type: str) -> dict[str, str]:
    """Best-effort ``{source_header: target_field}`` for a sniffed header row.

    Two passes, and the order matters: an EXACT normalized alias hit wins before any
    fuzzy hit, so ``"Position"`` binds to ``position`` even though ``"Page"`` is a
    prefix of nothing and ``"Avg position"`` would also fuzzily reach it. A target is
    claimed at most once (first header wins), which keeps the suggestion valid by
    construction - it can never propose the duplicate-target mapping that validation
    would then reject.

    ``custom`` (and any unknown type) has an empty allow-list, so it suggests nothing.
    """
    target = target_for(source_type)
    if target is None or not target.fields:
        return {}

    normalized = [(h, normalize_header(h)) for h in headers]
    mapping: dict[str, str] = {}
    claimed: set[str] = set()

    for exact in (True, False):
        for header, norm in normalized:
            if not norm or header in mapping:
                continue
            hit = _match_field(norm, target.fields, claimed, exact=exact)
            if hit is not None:
                mapping[header] = hit.name
                claimed.add(hit.name)
    return mapping


def _match_field(
    norm: str, fields: tuple[TargetField, ...], claimed: set[str], *, exact: bool
) -> TargetField | None:
    """The field whose alias set matches ``norm``, or ``None``.

    Exact pass: the normalized header IS an alias (or the field's own name). Fuzzy pass:
    the header is an alias with a vendor suffix/prefix bolted on (``"clicks (total)"``
    normalizes to ``"clicks total"``), matched on whole WORDS so ``"page"`` can never
    match inside ``"pages crawled"``'s neighbour ``"ascore"`` - substring matching here
    is what produces the classic "Impressions mapped to Position" import bug.
    """
    for f in fields:
        if f.name in claimed:
            continue
        candidates = (f.name.replace("_", " "), *f.aliases)
        if exact:
            if norm in candidates:
                return f
            continue
        words = norm.split()
        for alias in candidates:
            alias_words = alias.split()
            if _contains_words(words, alias_words):
                return f
    return None


def _contains_words(words: list[str], alias_words: list[str]) -> bool:
    """Whether ``alias_words`` appears as a contiguous WORD run inside ``words``."""
    n = len(alias_words)
    if not n or n > len(words):
        return False
    return any(words[i : i + n] == alias_words for i in range(len(words) - n + 1))


# --------------------------------------------------------------------------- #
# Mapping validation - the allow-list's enforcement half
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MappingVerdict:
    """The verdict on one ``column_map``: valid, plus every reason it is not."""

    ok: bool
    errors: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        return "; ".join(self.errors)


def validate_mapping(
    source_type: str, column_map: dict[str, str], detected_columns: list[str] | None = None
) -> MappingVerdict:
    """Validate ``{source_header: target_field}`` against the frozen allow-list.

    THE security-critical function of this module. Rejects, in order:

    1. an unknown/staging-only source_type (``custom``'s allow-list is empty, so every
       mapping for it fails here rather than by a special case);
    2. an empty map (there is nothing to import);
    3. a TARGET outside the allow-list - the injection attempt. A ``column_map`` can
       never name ``password_hash``, ``client_id``, ``action`` or any other column: only
       the names frozen in ``constants`` are reachable, and the derived columns are
       deliberately absent from ``fields`` so user input cannot claim them either;
    4. a duplicate target (two source columns fighting over one field - the last write
       would silently win);
    5. a missing required field;
    6. a source header that was never detected in the file (a stale map from another
       export - it would import a column of NULLs and look like it worked).
    """
    errors: list[str] = []
    target = target_for(source_type)
    if target is None:
        return MappingVerdict(False, [f"Unknown import type '{source_type}'"])
    allowed = allowed_fields(source_type)
    if not allowed:
        return MappingVerdict(
            False, [f"'{source_type}' imports stage only - they have no target fields"]
        )
    if not column_map:
        return MappingVerdict(False, ["The column map is empty"])

    seen: dict[str, str] = {}
    for header, field_name in column_map.items():
        if field_name not in allowed:
            # The injection boundary. Name the allow-list, never echo the attempt back
            # into anything but this message.
            errors.append(
                f"'{field_name}' is not an importable field for {source_type} "
                f"(allowed: {', '.join(allowed)})"
            )
            continue
        if field_name in seen:
            errors.append(
                f"'{field_name}' is mapped twice (from '{seen[field_name]}' and '{header}')"
            )
            continue
        seen[field_name] = header

    for f in target.fields:
        if f.required and f.name not in seen:
            errors.append(f"'{f.name}' is required for a {source_type} import")

    if detected_columns is not None:
        known = set(detected_columns)
        errors.extend(
            f"'{header}' is not a column in this file"
            for header in column_map
            if header not in known
        )

    return MappingVerdict(not errors, errors)


# --------------------------------------------------------------------------- #
# Per-row coercion
# --------------------------------------------------------------------------- #
class RowError(ValueError):
    """One cell could not become its target column's type. Carries the field + value so
    the bounded error sample can tell a human WHICH column of WHICH row to fix."""

    def __init__(self, field_name: str, value: Any, reason: str) -> None:
        super().__init__(f"{field_name}: {reason}")
        self.field_name = field_name
        self.value = "" if value is None else str(value)[:120]
        self.reason = reason


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clean_number(value: Any) -> str:
    """Strip thousands separators / NBSPs / stray currency + percent marks."""
    return _NUM_CLEAN_RE.sub("", _text(value).replace("$", "").replace("%", ""))


def _coerce_int(f: TargetField, value: Any) -> int | None:
    raw = _clean_number(value)
    if not raw:
        return None
    try:
        # via Decimal so "1,234.0" (Excel's float-ified integer) parses instead of
        # blowing up int(), and "1.9" truncates rather than silently rounding up.
        parsed = int(Decimal(raw))
    except (InvalidOperation, ValueError) as exc:
        raise RowError(f.name, value, "not a whole number") from exc
    if parsed < 0:
        raise RowError(f.name, value, "must not be negative")
    return parsed


def _coerce_score(f: TargetField, value: Any) -> float | None:
    """A 0-100 column (authority / spam / difficulty). The DB has a CHECK for this, so
    an out-of-range cell is a ROW error here rather than a transaction-killing 23514
    that would take the whole batch down with it."""
    raw = _clean_number(value)
    if not raw:
        return None
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise RowError(f.name, value, "not a number") from exc
    if not 0 <= parsed <= 100:
        raise RowError(f.name, value, "must be between 0 and 100")
    return round(parsed, 2)


def _coerce_numeric(f: TargetField, value: Any) -> float | None:
    raw = _clean_number(value)
    if not raw:
        return None
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise RowError(f.name, value, "not a number") from exc
    if parsed < 0:
        raise RowError(f.name, value, "must not be negative")
    return round(parsed, 2)


def _coerce_ctr(f: TargetField, value: Any) -> float | None:
    """GSC's CTR -> the fraction ``search_console_rows.ctr`` (numeric(6,4)) stores.

    "3.41%" -> 0.0341. A bare 3.41 is ALSO a percentage: a CTR is by definition <= 1, so
    a value above 1 can only be percent-scaled, and dividing is strictly better than
    recording a 341% click-through rate. Above 100 nothing sensible remains -> row error.
    """
    text = _text(value)
    if not text:
        return None
    raw = _clean_number(value)
    if not raw:
        return None
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise RowError(f.name, value, "not a number") from exc
    if parsed < 0:
        raise RowError(f.name, value, "must not be negative")
    if text.endswith("%") or parsed > 1:
        parsed /= 100.0
    if parsed > 1:
        raise RowError(f.name, value, "is not a click-through rate (over 100%)")
    return round(parsed, 4)


def _coerce_position(f: TargetField, value: Any) -> float | None:
    """A SERP position (numeric(6,2)). 0 is not a position - rank is 1-based - and a
    value past the deepest window we ever read is a parse accident, not a ranking."""
    raw = _clean_number(value)
    if not raw:
        return None
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise RowError(f.name, value, "not a number") from exc
    if not 0 < parsed <= 1000:
        raise RowError(f.name, value, "is not a SERP position")
    return round(parsed, 2)


_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",   # ISO - GSC, Ahrefs, Semrush all export this
    "%Y/%m/%d",
    "%m/%d/%Y",   # US / Excel default locale
    "%d %b %Y",   # "15 Mar 2024"
    "%b %d, %Y",  # "Mar 15, 2024"
)


def _coerce_date(f: TargetField, value: Any) -> date | None:
    """Parse an export's date cell.

    ``DD/MM/YYYY`` is DELIBERATELY not in the format list: it is indistinguishable from
    ``MM/DD/YYYY`` for the first twelve days of a month, so accepting both would silently
    mis-date ~40% of a European export. An unparseable date is an honest row error.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if not text:
        return None
    iso = text.replace("Z", "+00:00")
    try:  # ISO 8601 datetimes ("2024-03-15T10:00:00Z") reduce to their date
        return datetime.fromisoformat(iso).date()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise RowError(f.name, value, "not a recognised date")


def _coerce_enum(f: TargetField, value: Any) -> str | None:
    """Match a cell against the column's enum, case-insensitively. The stored value is
    always the enum's OWN spelling (Postgres enums are case-sensitive)."""
    text = _text(value)
    if not text:
        return None
    lowered = text.lower()
    for allowed in f.enum_values:
        if lowered == allowed.lower():
            return allowed
    raise RowError(f.name, value, f"must be one of: {', '.join(f.enum_values)}")


def _coerce_intent(f: TargetField, value: Any) -> str | None:
    """The 0035 ``search_intent`` enum, via the keyword module's OWN normaliser - so an
    import resolves "commercial investigation" exactly as the research worker does."""
    text = _text(value)
    if not text:
        return None
    label = normalize_intent(text)
    if label is None:
        raise RowError(f.name, value, f"must be one of: {', '.join(f.enum_values)}")
    return label


def _coerce_domain(f: TargetField, value: Any) -> str | None:
    """Reduce a referring URL to its host - ``backlinks.ref_domain`` is a DOMAIN column.

    Semrush exports "Source url" and Ahrefs "Referring page URL": both are full URLs. A
    bare domain passes through unchanged; a "www." prefix is dropped so the same site
    does not appear twice in the profile.
    """
    text = _text(value)
    if not text:
        return None
    host = urlsplit(text if "//" in text else f"//{text}").hostname or ""
    host = host.strip().lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        raise RowError(f.name, value, "not a domain or URL")
    return host


_COERCERS: dict[str, Any] = {
    "text": lambda f, v: _text(v) or None,
    "domain": _coerce_domain,
    "int": _coerce_int,
    "score": _coerce_score,
    "numeric": _coerce_numeric,
    "ctr": _coerce_ctr,
    "position": _coerce_position,
    "date": _coerce_date,
    "enum": _coerce_enum,
    "intent": _coerce_intent,
}


def coerce_row(
    target: ImportTarget, column_map: dict[str, str], raw: dict[str, Any]
) -> dict[str, Any]:
    """Map + type one file row onto its target's columns. Raises :class:`RowError`.

    Iterates the ``column_map`` (already allow-list-validated), coerces each cell, and
    DROPS the keys whose cell was blank - so an unmapped/empty optional column keeps the
    database's own default (``anchor text not null default ''``) instead of being
    overwritten with a NOT-NULL-violating NULL.

    A required field that coerces to nothing is a row error, not a silent skip: an
    import that quietly drops the keyword column would look successful and import
    nothing.
    """
    out: dict[str, Any] = {}
    for header, field_name in column_map.items():
        f = target.field(field_name)
        if f is None:  # unreachable via a validated map; a defensive no-op
            continue
        value = _coerce(f, raw.get(header))
        if value is not None:
            out[field_name] = value

    for f in target.fields:
        if f.required and f.name not in out:
            raise RowError(f.name, raw.get(_header_for(column_map, f.name)), "is required but empty")
    return out


def _coerce(f: TargetField, value: Any) -> Any:
    coercer = _COERCERS.get(f.kind)
    if coercer is None:  # unreachable: kinds are a Literal, coerced at construction
        return _text(value) or None
    return coercer(f, value)


def _header_for(column_map: dict[str, str], field_name: str) -> str:
    return next((h for h, t in column_map.items() if t == field_name), field_name)


def normalize_keyword(keyword: str) -> str:
    """The case/whitespace-folded form 0036's uniqueness key (and therefore the BILL)
    uses. Mirrors ``rank_tracker.service.normalize_keyword`` - "Plumber " and "plumber"
    are ONE subscription, not two."""
    return " ".join(str(keyword or "").lower().split())


def derive_columns(
    target: ImportTarget,
    row: dict[str, Any],
    *,
    client_id: str | None,
    client_name: str,
    run_id: str,
) -> dict[str, Any]:
    """The SERVER-stamped columns for one coerced row - never from the ``column_map``.

    This is why tenant attribution and the enum invariants are not user-reachable:
    ``client_id``/``client_name`` come from the RUN (the router resolved and snapshotted
    them), ``action`` from the off-page module's own NAP rule, ``normalized_keyword``
    from the keyword itself, and ``source='import'`` is a fixed marker. Only the columns
    named in ``target.derived`` are ever produced.
    """
    out: dict[str, Any] = {}
    derived = set(target.derived)
    if "client_id" in derived:
        out["client_id"] = client_id
    if "client_name" in derived:
        out["client_name"] = client_name
    if "import_run_id" in derived:
        out["import_run_id"] = run_id
    if "action" in derived:
        # The off-page module's EXISTING rule (app/schemas/offpage.action_for):
        # missing -> Submit (create the listing), else Update (fix drift / re-verify).
        out["action"] = action_for(str(row.get("nap_status") or "missing"))
    if "normalized_keyword" in derived:
        out["normalized_keyword"] = normalize_keyword(str(row.get("keyword") or ""))
    for name, value in target.fixed:
        if name in derived:
            out[name] = value
    return out


def row_is_importable(target: ImportTarget, row: dict[str, Any]) -> bool:
    """Whether a coerced row carries enough to be worth writing.

    Only ``search_console`` needs this: a GSC export is either a Queries report or a
    Pages report, so NEITHER column can be marked required, yet a row with neither is an
    empty row (a totals footer, a blank line) and must not become a ghost record.
    """
    if target.source_type == "search_console":
        return bool(row.get("query") or row.get("page"))
    return True


# --------------------------------------------------------------------------- #
# The /workspace adapter (frontend lib/tools.ts data_import EXTRA shape).
# --------------------------------------------------------------------------- #
def format_compact_count(value: int) -> str:
    """A KPI count tile as ``lib/tools.ts`` renders it: ``42k`` / ``1.2m``.

    Trailing ``.0`` is dropped (42_000 -> "42k", not "42.0k") to match the demo tile.
    Only the row-count tile uses this; an exact row count still ships on the run.
    """
    number = int(value or 0)
    for cutoff, suffix in ((1_000_000, "m"), (1_000, "k")):
        if abs(number) >= cutoff:
            scaled = f"{number / cutoff:.1f}".removesuffix(".0")
            return f"{scaled}{suffix}"
    return f"{number:,}"


def status_cell(status: str, rows_error: int) -> ToolCellObj:
    """The Status cell, matching the ``tools.ts`` demo semantics exactly: an imported
    run reads ``Imported``/ok, a partial one names the damage (``3 errors``/warn), a
    failed one reads ``Failed``/crit, and a run still in flight is ``mut`` - in-flight is
    not a verdict, and toning it ok/warn would assert one."""
    if status == "imported":
        return ToolCellObj(v="Imported", tone="ok")
    if status == "partial":
        count = int(rows_error or 0)
        return ToolCellObj(v=f"{count} error{'' if count == 1 else 's'}", tone="warn")
    if status == "failed":
        return ToolCellObj(v="Failed", tone="crit")
    return ToolCellObj(v=status.capitalize(), tone="mut")


def _run_row(row: dict[str, Any]) -> list[ToolCell]:
    """One workspace table row: [File, Type, Rows, Status].

    ``File`` is the ORIGINAL display filename - never ``stored_path``, which no adapter,
    response model or log line in this module ever touches.
    """
    source_type = str(row.get("source_type") or "")
    return [
        str(row.get("filename") or ""),
        SOURCE_TYPE_LABELS.get(source_type, source_type or "—"),
        f"{int(row.get('rows_total') or 0):,}",
        cast("ToolCell", status_cell(str(row.get("status") or ""), int(row.get("rows_error") or 0))),
    ]


def build_workspace(stats: dict[str, Any], runs: list[dict[str, Any]]) -> ToolExtraResponse:
    """Assemble the data-import tool workspace (KPIs + the recent-imports table + CTA).

    KPI labels + the primary + the table columns are pinned to ``lib/tools.ts``; the
    columns are EXACTLY ``["File", "Type", "Rows", "Status"]`` (the tool-workspace
    contract test enforces byte-identity).

    The ``tools.ts`` demo shows a delta on the Errors tile; this adapter emits NONE. A
    delta needs a prior-window baseline to be true, and the module keeps no such
    baseline - a fabricated arrow on an error count is worse than no arrow.
    """
    kpis = [
        ToolKpi(label="Imports (30d)", value=f"{int(stats.get('imports_30d') or 0):,}"),
        ToolKpi(label="Rows mapped", value=format_compact_count(int(stats.get("rows_mapped") or 0))),
        ToolKpi(label="Errors", value=f"{int(stats.get('rows_error') or 0):,}"),
    ]
    table = ToolTable(
        title=_WORKSPACE_TABLE_TITLE,
        icon=_WORKSPACE_TABLE_ICON,
        cols=list(WORKSPACE_TABLE_COLS),
        rows=[_run_row(r) for r in runs[:_WORKSPACE_ROW_LIMIT]],
    )
    return ToolExtraResponse(
        kpis=kpis, table=table, primary=_WORKSPACE_PRIMARY, bullets=list(_WORKSPACE_BULLETS)
    )
