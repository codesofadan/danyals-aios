"""Data-import pure core: sniffing, fuzzy auto-mapping, ALLOW-LIST validation, coercion.

No DB, no network, no filesystem - the service is pure by construction, so these are
plain function tests.

The single most important test in this module is
``test_validate_mapping_rejects_a_target_outside_the_allow_list`` and its family: the
``column_map``'s target side is the ONE piece of user input that would otherwise decide a
column name, and validation is what stops it. Everything else here protects data quality;
that one protects the database.

The auto-map tests fire the REAL header rows of the exports the agency actually uploads
(Google Search Console, Semrush, Ahrefs) rather than tidy invented ones - a mapper tuned
to invented headers is a mapper that fails on the first real file.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.data_import.constants import TARGETS, target_for
from app.modules.data_import.service import (
    RowError,
    build_workspace,
    clean_headers,
    coerce_row,
    derive_columns,
    extension_of,
    format_compact_count,
    header_signature,
    normalize_header,
    row_is_importable,
    safe_display_name,
    sniff_kind,
    status_cell,
    suggest_mapping,
    validate_mapping,
)

pytestmark = pytest.mark.unit

# The REAL header rows. Verbatim from each vendor's export, punctuation and all.
_GSC_QUERIES = ["Query", "Clicks", "Impressions", "CTR", "Position"]
_GSC_PAGES = ["Page", "Clicks", "Impressions", "CTR", "Position"]
_SEMRUSH_BACKLINKS = [
    "Source url", "Source title", "Target url", "Anchor", "Page ascore", "First seen",
    "Last seen", "Nofollow",
]
_AHREFS_BACKLINKS = ["Referring page URL", "Domain rating", "UR", "Anchor", "First seen"]
_SEMRUSH_KEYWORDS = ["Keyword", "Volume", "Keyword Difficulty", "CPC", "Intent", "Competition"]
_AHREFS_KEYWORDS = ["Keyword", "Volume", "KD", "CPC"]


# --------------------------------------------------------------------------- #
# 1. THE ALLOW-LIST. The injection boundary's enforcement half.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "target_field",
    [
        "password_hash",       # another table's secret
        "client_id",           # the tenant boundary - server-derived, never mappable
        "action",              # server-derived from the NAP rule
        "source",              # the 'import' marker
        "id",
        "created_at",
        "keyword) --",         # a SQL fragment
        "volume; drop table public.keywords",
        "*",
        "",
    ],
)
def test_validate_mapping_rejects_a_target_outside_the_allow_list(target_field: str) -> None:
    """THE test of this module.

    A ``column_map`` names a target COLUMN. If any string could be one, the privileged
    writer would write any column of the target table - and the derived columns
    (``client_id``, ``action``, ``source``) would become user-controlled, which would
    hand a caller another tenant's attribution. Only the names frozen in ``constants``
    are reachable, and a rejection is total: ``ok`` is False and the reason names the
    allow-list.
    """
    verdict = validate_mapping("keywords", {"Some Column": target_field})
    assert not verdict.ok
    assert "is not an importable field" in verdict.message


def test_validate_mapping_rejects_the_injection_even_when_other_columns_are_valid() -> None:
    """A hostile target hidden among legitimate ones must sink the WHOLE map - a
    partial accept would import the good columns and quietly prove the bad one was
    'ignored', which is exactly how such a gap survives a review."""
    verdict = validate_mapping(
        "keywords", {"Keyword": "keyword", "Volume": "volume", "X": "password_hash"}
    )
    assert not verdict.ok
    assert any("password_hash" in e for e in verdict.errors)


def test_validate_mapping_accepts_a_map_naming_only_allow_listed_targets() -> None:
    verdict = validate_mapping(
        "keywords", {"Keyword": "keyword", "Volume": "volume", "KD": "difficulty"}
    )
    assert verdict.ok, verdict.message
    assert verdict.errors == []


def test_validate_mapping_rejects_a_duplicate_target() -> None:
    """Two source columns fighting over one field: the last would silently win, and the
    user would never learn which of their columns was discarded."""
    verdict = validate_mapping("keywords", {"Keyword": "keyword", "Term": "keyword"})
    assert not verdict.ok
    assert any("mapped twice" in e for e in verdict.errors)


def test_validate_mapping_rejects_a_missing_required_field() -> None:
    verdict = validate_mapping("keywords", {"Volume": "volume"})
    assert not verdict.ok
    assert any("'keyword' is required" in e for e in verdict.errors)


def test_validate_mapping_rejects_a_header_the_file_does_not_have() -> None:
    """A stale map from another export would import a column of NULLs and look like it
    worked."""
    verdict = validate_mapping(
        "keywords", {"Keyword": "keyword", "Ghost": "volume"}, ["Keyword", "Volume"]
    )
    assert not verdict.ok
    assert any("not a column in this file" in e for e in verdict.errors)


def test_validate_mapping_rejects_an_empty_map_and_an_unknown_type() -> None:
    assert not validate_mapping("keywords", {}).ok
    assert not validate_mapping("not_a_real_type", {"A": "keyword"}).ok


def test_validate_mapping_rejects_every_map_for_the_staging_only_custom_type() -> None:
    """``custom`` stages only - it has no target table, so its allow-list is EMPTY and
    every mapping fails by construction rather than by a special case someone can
    forget."""
    verdict = validate_mapping("custom", {"Anything": "keyword"})
    assert not verdict.ok
    assert "stage only" in verdict.message


@pytest.mark.parametrize("source_type", sorted(TARGETS))
def test_every_target_field_is_a_real_column_of_its_real_table(source_type: str) -> None:
    """The allow-list must name columns that EXIST: a typo here would not be caught until
    a live import failed with an opaque 42703, after the user had already mapped the
    file. Read straight out of the owning migration rather than restated."""
    from pathlib import Path

    migrations = Path(__file__).resolve().parents[3].parent / "db" / "migrations"
    target = target_for(source_type)
    assert target is not None
    if target.table is None:
        assert target.fields == (), "a staging-only target must have an empty allow-list"
        return
    table = target.table.removeprefix("public.")
    src = "\n".join(p.read_text(encoding="utf-8") for p in sorted(migrations.glob("00*.sql")))
    start = src.index(f"create table if not exists public.{table} (")
    body = src[start : src.index("\n);", start)]
    for column in target.all_columns:
        assert f"\n  {column} " in body or f"\n  {column}  " in body, (
            f"{column} is not a column of {target.table}"
        )


# --------------------------------------------------------------------------- #
# 2. Sniffing - the bytes decide, not the extension.
# --------------------------------------------------------------------------- #
def test_sniff_accepts_a_real_csv_and_tsv() -> None:
    assert sniff_kind(b"Query,Clicks\nplumber,12\n", "csv") == "csv"
    assert sniff_kind(b"Query\tClicks\nplumber\t12\n", "tsv") == "tsv"


def test_sniff_accepts_a_real_xlsx_by_its_zip_signature() -> None:
    assert sniff_kind(b"PK\x03\x04\x14\x00\x00\x00", "xlsx") == "xlsx"


@pytest.mark.parametrize(
    ("head", "label"),
    [
        (b"PK\x03\x04\x14\x00", "a zip archive"),
        (b"%PDF-1.7\n", "a PDF"),
        (b"\x89PNG\r\n\x1a\n", "a PNG"),
        (b"\xff\xd8\xff\xe0", "a JPEG"),
        (b"\x7fELF\x02\x01", "an ELF binary"),
        (b"MZ\x90\x00", "a Windows executable"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1", "a legacy OLE2 .xls"),
        (b"\x1f\x8b\x08", "a gzip"),
        (b"SQLite format 3\x00", "a SQLite database"),
        (b"Query,Clicks\n\x00\x01\x02", "binary with NULs"),
    ],
)
def test_sniff_rejects_a_file_renamed_to_csv(head: bytes, label: str) -> None:
    """The extension is the uploader's CLAIM; the magic bytes are the evidence. A
    ``.csv`` that is really ``{label}`` never reaches the parser."""
    assert sniff_kind(head, "csv") is None, f"{label} was accepted as a .csv"


def test_sniff_rejects_an_xlsx_that_is_not_a_zip() -> None:
    """The inverse lie: a CSV (or anything else) renamed to .xlsx. openpyxl would raise
    on it anyway, but the rejection belongs at the door, not in the worker."""
    assert sniff_kind(b"Query,Clicks\nplumber,12\n", "xlsx") is None


def test_sniff_rejects_an_extension_outside_the_allow_list() -> None:
    for ext in ("exe", "sh", "sql", "xls", "json", ""):
        assert sniff_kind(b"Query,Clicks\n", ext) is None


def test_sniff_accepts_a_legacy_encoded_csv() -> None:
    """Excel still emits cp1252. A real, readable export must not be rejected for it -
    the NUL + magic checks are what exclude binary, not a strict utf-8 decode."""
    assert sniff_kind("Query,Clicks\ncafé,12\n".encode("latin-1"), "csv") == "csv"


def test_extension_of_reads_only_the_last_segment() -> None:
    """A traversal attempt yields no extension at all, so the allow-list rejects it -
    the display name is never a path source anyway, but this is the belt."""
    assert extension_of("export.csv") == "csv"
    assert extension_of("Report.CSV") == "csv"
    assert extension_of("archive.tar.gz") == "gz"
    assert extension_of("../../etc/passwd") == ""
    assert extension_of("/etc/passwd") == ""
    assert extension_of("noext") == ""


def test_safe_display_name_strips_paths_and_bounds_the_length() -> None:
    assert safe_display_name("../../etc/passwd") == "passwd"
    assert safe_display_name("C:\\Windows\\System32\\evil.csv") == "evil.csv"
    assert safe_display_name("a/b/c/report.csv") == "report.csv"
    assert len(safe_display_name("x" * 5000)) == 255
    assert safe_display_name("") == "upload"


# --------------------------------------------------------------------------- #
# 3. Header normalisation + fuzzy auto-map against the REAL exports.
# --------------------------------------------------------------------------- #
def test_normalize_header_folds_case_and_punctuation() -> None:
    assert normalize_header("Page ASCORE") == "page ascore"
    assert normalize_header("  Avg. Position ") == "avg position"
    assert normalize_header("CTR (%)") == "ctr"
    assert normalize_header("Keyword_Difficulty") == "keyword difficulty"
    assert normalize_header(None) == ""


def test_auto_map_reads_a_real_gsc_queries_export() -> None:
    assert suggest_mapping(_GSC_QUERIES, "search_console") == {
        "Query": "query", "Clicks": "clicks", "Impressions": "impressions",
        "CTR": "ctr", "Position": "position",
    }


def test_auto_map_reads_a_real_gsc_pages_export() -> None:
    assert suggest_mapping(_GSC_PAGES, "search_console") == {
        "Page": "page", "Clicks": "clicks", "Impressions": "impressions",
        "CTR": "ctr", "Position": "position",
    }


def test_auto_map_reads_a_real_semrush_backlinks_export() -> None:
    mapped = suggest_mapping(_SEMRUSH_BACKLINKS, "backlinks")
    assert mapped["Source url"] == "ref_domain"
    assert mapped["Anchor"] == "anchor"
    assert mapped["Page ascore"] == "authority"
    assert mapped["First seen"] == "first_seen"


def test_auto_map_reads_a_real_ahrefs_backlinks_export() -> None:
    mapped = suggest_mapping(_AHREFS_BACKLINKS, "backlinks")
    assert mapped["Referring page URL"] == "ref_domain"
    assert mapped["Domain rating"] == "authority"
    assert mapped["Anchor"] == "anchor"
    assert mapped["First seen"] == "first_seen"


def test_auto_map_reads_real_keyword_exports() -> None:
    semrush = suggest_mapping(_SEMRUSH_KEYWORDS, "keywords")
    assert semrush["Keyword"] == "keyword"
    assert semrush["Volume"] == "volume"
    assert semrush["Keyword Difficulty"] == "difficulty"
    assert semrush["CPC"] == "cpc"
    assert semrush["Intent"] == "intent"

    ahrefs = suggest_mapping(_AHREFS_KEYWORDS, "keywords")
    assert ahrefs["KD"] == "difficulty"
    assert ahrefs["Volume"] == "volume"


def test_auto_map_never_claims_one_target_twice() -> None:
    """A suggestion that proposed a duplicate target would be rejected by the very
    validator that is supposed to accept it - so the suggester is valid by construction."""
    headers = ["Keyword", "Query", "Term", "Volume", "Search Volume"]
    mapped = suggest_mapping(headers, "keywords")
    assert len(set(mapped.values())) == len(mapped)
    assert validate_mapping("keywords", mapped, headers).ok


def test_auto_map_prefers_an_exact_alias_over_a_fuzzy_one() -> None:
    """``"Clicks"`` must win ``clicks`` over ``"Clicks (total)"``, which only reaches it
    fuzzily - even though the fuzzy header comes FIRST in the row.

    The exact pass runs over every header before the fuzzy pass runs over any, so the
    cleanest header wins the field regardless of column order. A single-pass matcher
    would bind whichever came first.
    """
    mapped = suggest_mapping(["Clicks (total)", "Clicks"], "search_console")
    assert mapped["Clicks"] == "clicks"
    assert "Clicks (total)" not in mapped  # the target was already claimed exactly


def test_auto_map_is_deterministic_when_two_headers_are_equally_exact() -> None:
    """``"Avg position"`` and ``"Position"`` are BOTH exact aliases of ``position``, so
    there is no cleanest header to prefer - first-in-the-row wins.

    Arbitrary but deterministic, and still VALID (one target, claimed once), which is
    what matters: a suggestion is a starting point a human confirms, and the validator
    would reject it outright if it double-claimed.
    """
    headers = ["Avg position", "Position"]
    mapped = suggest_mapping(headers, "search_console")
    assert mapped == {"Avg position": "position"}
    assert suggest_mapping(list(reversed(headers)), "search_console") == {"Position": "position"}


def test_auto_map_does_not_match_on_substrings() -> None:
    """Word-boundary matching, not ``in``: a substring matcher is what produces the
    classic "Impressions mapped to Position" import bug."""
    mapped = suggest_mapping(["Impressions"], "search_console")
    assert mapped == {"Impressions": "impressions"}


def test_auto_map_suggests_nothing_for_the_staging_only_type() -> None:
    assert suggest_mapping(_GSC_QUERIES, "custom") == {}
    assert suggest_mapping(_GSC_QUERIES, "nope") == {}


def test_auto_map_ignores_columns_it_does_not_recognise() -> None:
    mapped = suggest_mapping(["Keyword", "Some Vendor Nonsense", "Volume"], "keywords")
    assert "Some Vendor Nonsense" not in mapped


def test_header_signature_is_order_insensitive_and_case_insensitive() -> None:
    """Vendors reorder columns between exports while the report stays the same, so the
    saved template must still match."""
    assert header_signature(_GSC_QUERIES) == header_signature(list(reversed(_GSC_QUERIES)))
    assert header_signature(["Query", "Clicks"]) == header_signature(["  query ", "CLICKS"])
    assert header_signature(["Query"]) != header_signature(["Page"])
    assert header_signature([]) == ""


def test_clean_headers_drops_blanks_and_bounds_the_row() -> None:
    assert clean_headers(["Query", "", None, " Clicks "]) == ["Query", "Clicks"]
    assert len(clean_headers([f"c{i}" for i in range(5_000)])) == 200
    assert len(clean_headers(["x" * 5_000])[0]) == 200


# --------------------------------------------------------------------------- #
# 4. Coercion - typed, bounded, honest about failure.
# --------------------------------------------------------------------------- #
def _keywords_map() -> dict[str, str]:
    return {"Keyword": "keyword", "Volume": "volume", "KD": "difficulty", "CPC": "cpc"}


def test_coerce_types_a_clean_keyword_row() -> None:
    target = target_for("keywords")
    assert target is not None
    row = coerce_row(
        target, _keywords_map(),
        {"Keyword": " Dental Implants ", "Volume": "8,100", "KD": "42.5", "CPC": "3.20"},
    )
    assert row == {"keyword": "Dental Implants", "volume": 8100, "difficulty": 42.5, "cpc": 3.2}


def test_coerce_strips_thousands_separators_and_excel_float_ints() -> None:
    target = target_for("keywords")
    assert target is not None
    row = coerce_row(target, _keywords_map(), {"Keyword": "x", "Volume": "12,400.0"})
    assert row["volume"] == 12_400


@pytest.mark.parametrize("bad", ["n/a", "-5", "abc", "1e", "--"])
def test_coerce_rejects_a_non_integer_rather_than_defaulting_to_zero(bad: str) -> None:
    """``or 0`` here would be a silent lie: an unparseable volume would import as a real
    zero and the user would never know a column failed."""
    target = target_for("keywords")
    assert target is not None
    with pytest.raises(RowError) as exc:
        coerce_row(target, _keywords_map(), {"Keyword": "x", "Volume": bad})
    assert exc.value.field_name == "volume"


@pytest.mark.parametrize("bad", ["101", "-1", "200"])
def test_coerce_enforces_the_0_100_bounds_the_db_checks(bad: str) -> None:
    """0018/0035 declare ``check (... between 0 and 100)``. Catching it here makes it ONE
    row error; letting it reach Postgres would raise 23514 and take the whole batch."""
    target = target_for("backlinks")
    assert target is not None
    with pytest.raises(RowError) as exc:
        coerce_row(
            target, {"Domain": "ref_domain", "DR": "authority"}, {"Domain": "a.com", "DR": bad}
        )
    assert exc.value.field_name == "authority"
    assert "between 0 and 100" in exc.value.reason


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("3.41%", 0.0341),
        ("3.41", 0.0341),
        ("0.0341", 0.0341),
        ("100%", 1.0),
        # A REAL zero, not a missing value: a query with impressions and no clicks has a
        # CTR of exactly 0, and dropping it would lose that fact.
        ("0", 0.0),
        ("0%", 0.0),
    ],
)
def test_coerce_ctr_converts_a_percentage_into_the_fraction_the_column_stores(
    cell: str, expected: float
) -> None:
    """GSC ships "3.41%" (and sometimes a bare 3.41); ``search_console_rows.ctr`` is a
    0-1 fraction. Storing 3.41 verbatim would record a 341% click-through rate."""
    target = target_for("search_console")
    assert target is not None
    row = coerce_row(target, {"Query": "query", "CTR": "ctr"}, {"Query": "x", "CTR": cell})
    assert row["ctr"] == expected


def test_coerce_ctr_keeps_a_blank_cell_out_rather_than_calling_it_zero() -> None:
    """The distinction the test above depends on: an EMPTY CTR cell is unknown (leave the
    column to its default), a "0" cell is a measured zero. Conflating them would invent
    a 0% click-through rate for every row a report simply did not measure."""
    target = target_for("search_console")
    assert target is not None
    row = coerce_row(target, {"Query": "query", "CTR": "ctr"}, {"Query": "x", "CTR": "  "})
    assert "ctr" not in row


def test_coerce_ctr_rejects_a_value_that_is_not_a_rate() -> None:
    target = target_for("search_console")
    assert target is not None
    with pytest.raises(RowError):
        coerce_row(target, {"Query": "query", "CTR": "ctr"}, {"Query": "x", "CTR": "5000"})


def test_coerce_position_rejects_zero_because_rank_is_one_based() -> None:
    target = target_for("search_console")
    assert target is not None
    row = coerce_row(
        target, {"Query": "query", "Position": "position"}, {"Query": "x", "Position": "12.4"}
    )
    assert row["position"] == 12.4
    with pytest.raises(RowError):
        coerce_row(
            target, {"Query": "query", "Position": "position"}, {"Query": "x", "Position": "0"}
        )


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("2024-03-15", date(2024, 3, 15)),
        ("2024-03-15T10:00:00Z", date(2024, 3, 15)),
        ("2024/03/15", date(2024, 3, 15)),
        ("03/15/2024", date(2024, 3, 15)),
        ("15 Mar 2024", date(2024, 3, 15)),
        ("Mar 15, 2024", date(2024, 3, 15)),
    ],
)
def test_coerce_date_parses_the_formats_the_real_exports_ship(cell: str, expected: date) -> None:
    target = target_for("backlinks")
    assert target is not None
    row = coerce_row(
        target, {"Domain": "ref_domain", "First seen": "first_seen"},
        {"Domain": "a.com", "First seen": cell},
    )
    assert row["first_seen"] == expected


def test_coerce_date_rejects_an_unparseable_date() -> None:
    target = target_for("backlinks")
    assert target is not None
    with pytest.raises(RowError) as exc:
        coerce_row(
            target, {"Domain": "ref_domain", "First seen": "first_seen"},
            {"Domain": "a.com", "First seen": "last tuesday"},
        )
    assert "not a recognised date" in exc.value.reason


def test_coerce_domain_reduces_a_referring_url_to_its_host() -> None:
    """``backlinks.ref_domain`` is a DOMAIN column, and both vendors export full URLs."""
    target = target_for("backlinks")
    assert target is not None
    for cell, expected in (
        ("https://www.example.com/blog/post?x=1", "example.com"),
        ("http://Example.COM/x", "example.com"),
        ("example.com", "example.com"),
        ("www.example.com", "example.com"),
    ):
        row = coerce_row(target, {"Source url": "ref_domain"}, {"Source url": cell})
        assert row["ref_domain"] == expected


def test_coerce_enum_matches_case_insensitively_but_stores_the_enums_own_spelling() -> None:
    """Postgres enums are case-sensitive: storing "TOXIC" would be a 22P02."""
    target = target_for("backlinks")
    assert target is not None
    row = coerce_row(
        target, {"Domain": "ref_domain", "Status": "status"},
        {"Domain": "a.com", "Status": "TOXIC"},
    )
    assert row["status"] == "toxic"


def test_coerce_enum_rejects_a_value_outside_the_db_enum() -> None:
    target = target_for("backlinks")
    assert target is not None
    with pytest.raises(RowError) as exc:
        coerce_row(
            target, {"Domain": "ref_domain", "Status": "status"},
            {"Domain": "a.com", "Status": "spammy"},
        )
    assert "must be one of" in exc.value.reason


def test_coerce_intent_reuses_the_keyword_modules_own_normaliser() -> None:
    """So an import resolves "commercial investigation" exactly as the research worker
    does - one vocabulary, not two."""
    target = target_for("keywords")
    assert target is not None
    row = coerce_row(
        target, {"Keyword": "keyword", "Intent": "intent"},
        {"Keyword": "x", "Intent": "commercial investigation"},
    )
    assert row["intent"] == "Commercial"


def test_coerce_drops_a_blank_optional_cell_so_the_db_default_applies() -> None:
    """0018's ``anchor text not null default ''`` would REJECT an explicit NULL. Omitting
    the column is what lets the table's own default stand."""
    target = target_for("backlinks")
    assert target is not None
    row = coerce_row(
        target, {"Domain": "ref_domain", "Anchor": "anchor"}, {"Domain": "a.com", "Anchor": "   "}
    )
    assert row == {"ref_domain": "a.com"}
    assert "anchor" not in row


def test_coerce_rejects_a_row_whose_required_field_is_blank() -> None:
    """A silent skip would let an import that dropped every keyword report success."""
    target = target_for("keywords")
    assert target is not None
    with pytest.raises(RowError) as exc:
        coerce_row(target, _keywords_map(), {"Keyword": "  ", "Volume": "10"})
    assert exc.value.field_name == "keyword"


def test_row_error_bounds_the_value_it_echoes_back() -> None:
    err = RowError("volume", "x" * 5_000, "not a number")
    assert len(err.value) == 120


# --------------------------------------------------------------------------- #
# 5. Derived columns - server-stamped, never user-reachable.
# --------------------------------------------------------------------------- #
def test_derive_stamps_the_tenant_from_the_run_not_the_file() -> None:
    target = target_for("keywords")
    assert target is not None
    derived = derive_columns(
        target, {"keyword": "x"}, client_id="cl-1", client_name="NorthPeak", run_id="run-1"
    )
    assert derived == {"client_id": "cl-1", "client_name": "NorthPeak", "source": "import"}


def test_derive_uses_the_offpage_modules_own_nap_rule_for_the_citation_action() -> None:
    """``missing -> Submit`` (create the listing), anything else ``-> Update``. Reused
    from ``app.schemas.offpage.action_for`` rather than restated, so an import can never
    contradict the NAP state the same row carries."""
    target = target_for("citations")
    assert target is not None
    for nap, expected in (("missing", "Submit"), ("inconsistent", "Update"), ("consistent", "Update")):
        derived = derive_columns(
            target, {"directory": "Yelp", "nap_status": nap}, client_id="cl-1",
            client_name="X", run_id="run-1",
        )
        assert derived["action"] == expected
    # A row with no NAP cell at all defaults to the column's own default state.
    assert derive_columns(
        target, {"directory": "Yelp"}, client_id="cl-1", client_name="X", run_id="run-1"
    )["action"] == "Submit"


def test_derive_folds_the_normalized_keyword_the_rank_uniqueness_key_uses() -> None:
    """0036 dedupes (and therefore BILLS) on ``normalized_keyword``: "Plumber " and
    "plumber" must be ONE subscription, not two."""
    target = target_for("rankings")
    assert target is not None
    derived = derive_columns(
        target, {"keyword": "  Plumber   Karachi "}, client_id="cl-1", client_name="X",
        run_id="run-1",
    )
    assert derived["normalized_keyword"] == "plumber karachi"


def test_derive_links_search_console_rows_back_to_their_run() -> None:
    target = target_for("search_console")
    assert target is not None
    derived = derive_columns(
        target, {"query": "x"}, client_id=None, client_name="", run_id="run-9"
    )
    assert derived["import_run_id"] == "run-9"
    assert derived["client_id"] is None  # an agency-global import is valid


@pytest.mark.parametrize("source_type", sorted(TARGETS))
def test_derive_only_ever_produces_columns_the_target_declares(source_type: str) -> None:
    """The store validates rows against ``all_columns``; a derived column outside
    ``target.derived`` would be rejected there. Pin the invariant at its source."""
    target = target_for(source_type)
    assert target is not None
    derived = derive_columns(
        target, {"keyword": "k", "nap_status": "missing"}, client_id="cl-1",
        client_name="X", run_id="r-1",
    )
    assert set(derived) <= set(target.derived)


def test_search_console_rows_need_a_query_or_a_page() -> None:
    """A GSC export is EITHER a Queries report or a Pages report, so neither column can
    be required - but a row with neither is a totals footer or a blank, not a record."""
    target = target_for("search_console")
    assert target is not None
    assert row_is_importable(target, {"query": "plumber"})
    assert row_is_importable(target, {"page": "/services"})
    assert not row_is_importable(target, {"clicks": 5})


# --------------------------------------------------------------------------- #
# 6. The workspace adapter.
# --------------------------------------------------------------------------- #
def test_workspace_emits_the_pinned_columns_and_tiles() -> None:
    ws = build_workspace(
        {"imports_30d": 18, "rows_mapped": 42_000, "rows_error": 3},
        [{"filename": "a.csv", "source_type": "keywords", "rows_total": 3_200,
          "rows_error": 0, "status": "imported"}],
    )
    assert ws.table is not None
    assert ws.table.cols == ["File", "Type", "Rows", "Status"]
    assert [k.label for k in ws.kpis] == ["Imports (30d)", "Rows mapped", "Errors"]
    assert [k.value for k in ws.kpis] == ["18", "42k", "3"]


def test_workspace_never_invents_a_kpi_delta() -> None:
    """``tools.ts``'s demo shows a delta on the Errors tile; the module keeps no
    prior-window baseline, so emitting one would be a fabricated trend arrow."""
    ws = build_workspace({"imports_30d": 1, "rows_mapped": 2, "rows_error": 3}, [])
    assert all(k.delta is None and k.dir is None for k in ws.kpis)


def test_workspace_bounds_the_table_to_eight_rows() -> None:
    runs = [
        {"filename": f"{i}.csv", "source_type": "keywords", "rows_total": 1,
         "rows_error": 0, "status": "imported"}
        for i in range(50)
    ]
    ws = build_workspace({"imports_30d": 50, "rows_mapped": 50, "rows_error": 0}, runs)
    assert ws.table is not None
    assert len(ws.table.rows) == 8


def test_status_cell_tones_match_the_demo_semantics() -> None:
    assert (status_cell("imported", 0).v, status_cell("imported", 0).tone) == ("Imported", "ok")
    assert status_cell("partial", 3).v == "3 errors"
    assert status_cell("partial", 3).tone == "warn"
    assert status_cell("partial", 1).v == "1 error"  # not "1 errors"
    assert status_cell("failed", 0).tone == "crit"
    # An in-flight run is not a verdict: toning it ok/warn would assert one.
    assert status_cell("importing", 0).tone == "mut"


def test_compact_count_matches_the_demo_tile() -> None:
    assert format_compact_count(42_000) == "42k"  # not "42.0k"
    assert format_compact_count(1_250) == "1.2k"
    assert format_compact_count(2_000_000) == "2m"
    assert format_compact_count(940) == "940"
    assert format_compact_count(0) == "0"
