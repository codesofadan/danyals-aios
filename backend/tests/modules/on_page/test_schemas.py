"""On-page wire shapes: the SERVER-AUTHORITATIVE contract + the enum tuples.

No ``frontend/lib/*.ts`` type mirrors this module, so ``test_contract_lock``'s
field-set lock does not apply. These tests ARE the equivalent: they freeze the emitted
key set and the enum vocabularies, so a drift is caught here rather than by a
dashboard that quietly renders an empty column.

Two things carry real weight beyond shape:

* **``client_id`` must never reach the wire.** ``client`` is a display SNAPSHOT. A row
  carries the internal id; the response must not.
* **The ``Impact`` labels are the DISPLAY CELL.** ``lib/tools.ts`` renders them
  verbatim, so 'High'/'Med'/'Low' is a contract, not a style choice - and the DB enum
  in 0038 spells them the same way.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.on_page.schemas import (
    AnalysisResponse,
    AnalyzeRequest,
    ApplyBulkRequest,
    ApplyRequest,
    OnPageStats,
    RecommendationDetail,
    RecommendationResponse,
)

pytestmark = pytest.mark.unit

_REC_KEYS = {
    "id", "analysis", "client", "page", "issue", "issueCode", "impact", "status",
    "fixKind", "current", "proposed", "priority", "quickWin", "autoApplicable",
}


def _row(**over):
    row = {
        "id": "rec-1", "analysis_code": "OP-0001", "analysis_status": "done",
        "client_id": "cl-secret", "client_name": "NorthPeak Dental",
        "page_url": "/services/implants", "issue": "Missing meta description",
        "issue_code": "meta_missing", "impact": "High", "status": "open",
        "fix_kind": "meta", "fix_payload": {"proposed_value": "A better description."},
        "current_value": "Old description", "priority_score": Decimal("66.67"),
        "quick_win": True, "detail": {"length": 0},
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# 1. The enum vocabularies (pinned; the DB enums in 0038 must spell them the same).
# --------------------------------------------------------------------------- #
def test_the_impact_labels_are_the_exact_display_cells() -> None:
    from typing import get_args

    from app.modules.on_page.schemas import Impact

    assert get_args(Impact) == ("High", "Med", "Low")


def test_the_status_and_fix_kind_vocabularies_are_pinned() -> None:
    from typing import get_args

    from app.modules.on_page.schemas import AnalysisStatus, FixKind, RecStatus

    assert get_args(AnalysisStatus) == ("queued", "analyzing", "done", "failed", "held")
    assert get_args(RecStatus) == ("open", "applied", "dismissed", "held", "reverted")
    assert get_args(FixKind) == ("title", "meta", "heading", "schema", "content", "manual")


def test_the_schema_enums_match_the_migrations_enums() -> None:
    """The wire vocabulary and the DB vocabulary must agree, or a value that passes
    Pydantic dies on an invalid enum cast in Postgres."""
    from pathlib import Path
    from typing import get_args

    from app.modules.on_page.schemas import AnalysisStatus, FixKind, Impact, RecStatus

    sql = (
        Path(__file__).resolve().parents[3].parent / "db" / "migrations" / "0038_on_page.sql"
    ).read_text(encoding="utf-8")
    for enum_name, literal in (
        ("onpage_analysis_status", AnalysisStatus),
        ("onpage_rec_status", RecStatus),
        ("onpage_impact", Impact),
        ("onpage_fix_kind", FixKind),
    ):
        for value in get_args(literal):
            assert f"'{value}'" in sql, f"{value!r} missing from the {enum_name} enum in 0038"


# --------------------------------------------------------------------------- #
# 2. RecommendationResponse.
# --------------------------------------------------------------------------- #
def test_the_recommendation_emits_exactly_the_contract_keys() -> None:
    body = RecommendationResponse.from_row(_row()).model_dump(by_alias=True)
    assert set(body) == _REC_KEYS


def test_the_internal_client_id_never_reaches_the_wire() -> None:
    body = RecommendationResponse.from_row(_row()).model_dump(by_alias=True)
    assert "cl-secret" not in str(body)
    assert body["client"] == "NorthPeak Dental"  # the snapshot, not the id


def test_the_proposed_value_is_lifted_out_of_the_fix_payload() -> None:
    """The board renders the suggestion without knowing the payload's internals."""
    body = RecommendationResponse.from_row(_row())
    assert body.proposed == "A better description."
    assert body.current == "Old description"  # together, these ARE the preview diff


def test_a_null_current_value_renders_as_an_empty_string_not_none() -> None:
    """NULL means "there was no tag to snapshot". The wire type stays ``str``."""
    assert RecommendationResponse.from_row(_row(current_value=None)).current == ""


def test_a_missing_proposal_renders_as_an_empty_string() -> None:
    assert RecommendationResponse.from_row(_row(fix_payload={})).proposed == ""
    assert RecommendationResponse.from_row(_row(fix_payload=None)).proposed == ""


def test_auto_applicable_is_derived_from_the_fix_kind_never_stored() -> None:
    assert RecommendationResponse.from_row(_row(fix_kind="title")).auto_applicable is True
    assert RecommendationResponse.from_row(_row(fix_kind="manual")).auto_applicable is False


def test_a_decimal_priority_is_coerced_to_a_plain_float() -> None:
    """psycopg returns numeric columns as ``Decimal``, which is not JSON-serializable."""
    body = RecommendationResponse.from_row(_row())
    assert body.priority == 66.67
    assert isinstance(body.priority, float)


def test_an_unknown_impact_or_status_falls_back_rather_than_raising() -> None:
    """A response model must never 500 the read path over a value it did not expect."""
    assert RecommendationResponse.from_row(_row(impact="Bogus")).impact == "Low"
    assert RecommendationResponse.from_row(_row(status="bogus")).status == "open"
    assert RecommendationResponse.from_row(_row(fix_kind="bogus")).fix_kind == "manual"


def test_the_analysis_is_named_by_its_public_code_never_its_uuid() -> None:
    assert RecommendationResponse.from_row(_row()).analysis == "OP-0001"


# --------------------------------------------------------------------------- #
# 3. RecommendationDetail (the preview/diff view).
# --------------------------------------------------------------------------- #
def test_the_detail_view_adds_evidence_and_the_analysis_status() -> None:
    body = RecommendationDetail.from_row(_row()).model_dump(by_alias=True)
    assert set(body) == _REC_KEYS | {"detail", "analysisStatus"}
    assert body["detail"] == {"length": 0}
    assert body["analysisStatus"] == "done"
    assert "cl-secret" not in str(body)


def test_the_detail_view_tolerates_a_non_dict_detail() -> None:
    assert RecommendationDetail.from_row(_row(detail=None)).detail == {}


# --------------------------------------------------------------------------- #
# 4. AnalysisResponse / OnPageStats.
# --------------------------------------------------------------------------- #
def test_the_analysis_shape_and_snapshot() -> None:
    body = AnalysisResponse.from_row({
        "code": "OP-0001", "client_id": "cl-secret", "client_name": "NorthPeak Dental",
        "page_url": "/p", "target_keyword": "kw", "status": "done",
        "score": {"total": 82.5}, "open_count": 3, "applied_count": 1, "error": None,
    }).model_dump(by_alias=True)
    assert set(body) == {
        "code", "client", "page", "keyword", "status", "score", "openCount",
        "appliedCount", "error",
    }
    assert "cl-secret" not in str(body)
    assert body["score"] == 82.5
    assert body["error"] == ""  # NULL renders as "", never None


def test_an_analysis_without_a_score_yet_reads_zero() -> None:
    body = AnalysisResponse.from_row({"code": "OP-1", "status": "queued", "score": {}})
    assert body.score == 0.0


def test_the_stats_tiles_default_to_zero_on_an_empty_board() -> None:
    assert OnPageStats.from_row({}).model_dump() == {"analyzed": 0, "open": 0, "applied": 0}


# --------------------------------------------------------------------------- #
# 5. The request models - the live-write confirmation contract.
# --------------------------------------------------------------------------- #
def test_apply_requires_a_literal_true_confirmation() -> None:
    assert ApplyRequest(confirm=True).force is False
    with pytest.raises(ValueError, match="confirm"):
        ApplyRequest()  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        ApplyRequest(confirm=False)  # type: ignore[arg-type]


@pytest.mark.parametrize("truthy", [1, "true", "yes", [1]])
def test_a_merely_truthy_confirmation_is_rejected(truthy: object) -> None:
    """Pydantic's lax mode would coerce ``1`` into ``True``. Consent to rewrite a live
    client page must be a literal boolean ``true``, not something truthy-adjacent."""
    with pytest.raises(ValueError):
        ApplyRequest(confirm=truthy)  # type: ignore[arg-type]


def test_apply_bulk_bounds_the_id_list() -> None:
    assert ApplyBulkRequest(ids=["a"], confirm=True).ids == ["a"]
    with pytest.raises(ValueError):
        ApplyBulkRequest(ids=[], confirm=True)
    with pytest.raises(ValueError):
        ApplyBulkRequest(ids=["a"] * 51, confirm=True)
    with pytest.raises(ValueError):
        ApplyBulkRequest(ids=["a"])  # type: ignore[call-arg]


def test_the_analyze_request_takes_camel_case_aliases() -> None:
    body = AnalyzeRequest.model_validate({
        "clientId": "cl-1", "pageUrl": "https://np.example/p",
        "targetKeyword": "invisalign cost", "siteId": "site-1", "sourceAuditId": "au-1",
    })
    assert body.client_id == "cl-1"
    assert body.page_url == "https://np.example/p"
    assert body.target_keyword == "invisalign cost"
    assert body.source_audit_id == "au-1"


def test_the_analyze_request_requires_a_client_and_a_page() -> None:
    with pytest.raises(ValueError):
        AnalyzeRequest.model_validate({"clientId": "cl-1"})
    with pytest.raises(ValueError):
        AnalyzeRequest.model_validate({"pageUrl": "https://np.example/p"})
    with pytest.raises(ValueError):
        AnalyzeRequest.model_validate({"clientId": "cl-1", "pageUrl": ""})


def test_the_analyze_request_bounds_the_url_and_keyword_lengths() -> None:
    with pytest.raises(ValueError):
        AnalyzeRequest.model_validate({"clientId": "c", "pageUrl": "h" * 2001})
    with pytest.raises(ValueError):
        AnalyzeRequest.model_validate(
            {"clientId": "c", "pageUrl": "https://x.example", "targetKeyword": "k" * 201}
        )
