"""P3: the planning store, against a real Postgres.

The store runs on `privileged_connection` (service_role, BYPASSRLS) because the
pipeline is a Celery process with no user JWT. That is a real privilege, so its
behaviour is worth pinning rather than assuming - particularly the parts where the
database, not Python, is doing the work: case-insensitive dedup, derived dossier
status, and the shingle intersection.

Skips unless a Postgres with migrations 0084+ is configured.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

pytestmark = pytest.mark.integration

_DSN_KEYS = ("DATABASE_MIGRATE_URL", "DATABASE_ADMIN_URL", "DATABASE_URL")


@pytest.fixture
def store() -> Any:
    dsn = next((os.environ[k] for k in _DSN_KEYS if os.environ.get(k)), None)
    if not dsn:
        pytest.skip(f"no Postgres configured (set one of {', '.join(_DSN_KEYS)})")
    pytest.importorskip("psycopg_pool")
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    from app.db.database import clear_pools, set_pools
    from app.modules.content_planning.repo import ContentPlanningStore

    pool = ConnectionPool(dsn, min_size=1, max_size=2, kwargs={"row_factory": dict_row}, open=True)
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("select to_regclass('public.content_engagements')")
            if cur.fetchone()["to_regclass"] is None:
                pytest.skip("planning schema not applied (migrations 0084+)")
        set_pools(rls=pool, admin=pool)
        yield ContentPlanningStore()
    finally:
        clear_pools()
        pool.close()


def test_a_new_engagement_blocks_drafting_until_it_is_ready(store: Any) -> None:
    """The hard halt as a property of the row, not a convention someone remembers."""
    eng = store.create_engagement(shape="full_site", name="t", page_target=50)
    assert eng.blocks_drafting
    store.set_engagement_status(eng.id, "ready")
    assert not store.get_engagement(eng.id).blocks_drafting


def test_the_same_keyword_in_different_case_is_stored_once(store: Any) -> None:
    """Counting "AC Repair" and "ac repair" separately would inflate every cluster and
    the client-facing volume totals with it."""
    from app.modules.content_planning.schemas import KeywordTerm

    eng = store.create_engagement(shape="page_set")
    plan = store.create_keyword_plan(engagement_id=eng.id, seed_terms=["ac repair"])
    store.add_keyword_terms(plan, [
        KeywordTerm(keyword="emergency ac repair", source="dataforseo", estimated=False, volume=1300),
        KeywordTerm(keyword="Emergency AC Repair", source="dataforseo", estimated=False, volume=9),
    ])
    assert len(store.keyword_terms(plan)) == 1


def test_measured_terms_can_be_isolated_from_derived_ones(store: Any) -> None:
    """A derived figure may exist; a client-facing report must be able to exclude it."""
    from app.modules.content_planning.schemas import KeywordTerm

    eng = store.create_engagement(shape="page_set")
    plan = store.create_keyword_plan(engagement_id=eng.id, seed_terms=["x"])
    store.add_keyword_terms(plan, [
        KeywordTerm(keyword="real", source="dataforseo", estimated=False, volume=1300),
        KeywordTerm(keyword="guessed", source="serp_derived", estimated=True, volume=900),
    ])
    assert [t.keyword for t in store.keyword_terms(plan, measured_only=True)] == ["real"]
    assert len(store.keyword_terms(plan)) == 2


def test_dossier_status_is_derived_from_the_slots(store: Any) -> None:
    """Derived, never asserted by a caller: a status a caller can set is a status that
    drifts from the rows, and this one gates drafting."""
    eng = store.create_engagement(shape="page_set")
    d = store.get_or_create_dossier(engagement_id=eng.id, cluster_key="hvac")

    store.upsert_slot(dossier_id=d.id, slot_key="founding_date", answer="2011")
    store.upsert_slot(dossier_id=d.id, slot_key="license_permit")
    assert store.refresh_dossier_status(d.id) == "partial"

    reread = store.get_or_create_dossier(engagement_id=eng.id, cluster_key="hvac")
    assert not reread.complete
    assert [s.slot_key for s in reread.unanswered] == ["license_permit"]
    # Only ANSWERED slots become proof signals - an unanswered slot is a question.
    assert reread.proof_signals() == frozenset({"founding_date"})

    store.upsert_slot(dossier_id=d.id, slot_key="license_permit", answer="C-20 1043382")
    assert store.refresh_dossier_status(d.id) == "complete"
    assert store.get_or_create_dossier(engagement_id=eng.id, cluster_key="hvac").complete


def test_an_artifact_alone_answers_a_slot(store: Any) -> None:
    """A dated photo or a licence document IS the evidence. Demanding prose alongside
    it would reject exactly the first-party artifacts the gate wants."""
    eng = store.create_engagement(shape="page_set")
    d = store.get_or_create_dossier(engagement_id=eng.id, cluster_key="c")
    store.upsert_slot(dossier_id=d.id, slot_key="photo", artifact_url="https://x/crew.jpg")
    assert store.refresh_dossier_status(d.id) == "complete"


def test_the_shingle_gate_finds_a_near_identical_outline(store: Any) -> None:
    """The query the shingle table exists for. A SQL intersection rather than a Python
    set comparison, because comparing against every prior page in a vertical cannot
    hold those sets in memory."""
    eng = store.create_engagement(shape="full_site")
    map_id = store.create_map(engagement_id=eng.id)
    node = store.add_node(map_id=map_id, primary_keyword="ac repair austin")

    hashes = frozenset(range(500_000, 500_060))
    store.record_shingles(hashes=hashes, node_id=node.id, vertical="home-services")

    same = store.find_overlaps(hashes=hashes, vertical="home-services")
    assert same and same[0].shared == 60 and same[0].jaccard == pytest.approx(1.0)

    assert store.find_overlaps(
        hashes=frozenset(range(900_000, 900_060)), vertical="home-services"
    ) == []


def test_the_shingle_gate_ignores_a_different_vertical(store: Any) -> None:
    """A plumber's page and a dentist's page sharing phrasing is not doorway abuse;
    two plumbers' pages sharing it is. The vertical scope is what separates them."""
    eng = store.create_engagement(shape="full_site")
    map_id = store.create_map(engagement_id=eng.id)
    node = store.add_node(map_id=map_id, primary_keyword="x")
    hashes = frozenset(range(600_000, 600_040))
    store.record_shingles(hashes=hashes, node_id=node.id, vertical="legal")
    assert store.find_overlaps(hashes=hashes, vertical="medical-dental") == []


def test_doctrine_usage_records_the_cache_accounting(store: Any) -> None:
    """The row that turns cache economics from a model into a measurement - my own
    token estimate was 30% low against what the API actually billed."""
    eng = store.create_engagement(shape="single_page")
    store.record_doctrine_usage(
        stage="draft", model="claude-sonnet-5", chunk_ids=["CLAUDE.md#prime-directive"],
        dropped_chunk_ids=[], engagement_id=eng.id, input_tokens=234,
        cache_write_tokens=74_580, cache_read_tokens=0, cost=0.2837,
    )
