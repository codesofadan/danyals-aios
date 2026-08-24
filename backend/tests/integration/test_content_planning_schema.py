"""P2: the planning schema's invariants, against a real Postgres.

These are the properties that CANNOT be checked without a database, because they are
enforced by triggers, partial unique indexes and FK actions rather than by Python.
Every one was verified by hand while authoring migrations 0084-0092; this file is what
keeps them true afterwards.

The riskiest by far is the guard-trigger interaction. `content_jobs` carries
`content_jobs_guard_update`, a SECURITY DEFINER BEFORE-UPDATE trigger that binds ALL
THREE actors including the worker pool - service_role bypasses POLICIES but NOT
TRIGGERS. Migration 0090 adds columns the worker must be able to write, and a wrong
assumption there surfaces only at runtime, as `illegal system content transition`, on
a real client's job.

Skips unless a Postgres is configured, matching the other integration tests.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

pytestmark = pytest.mark.integration

_DSN_KEYS = ("DATABASE_MIGRATE_URL", "DATABASE_ADMIN_URL", "DATABASE_URL")


def _dsn() -> str:
    for key in _DSN_KEYS:
        if os.environ.get(key):
            return os.environ[key]
    pytest.skip(f"no Postgres configured (set one of {', '.join(_DSN_KEYS)})")
    raise AssertionError("unreachable")


@pytest.fixture
def db() -> Any:
    psycopg = pytest.importorskip("psycopg")
    conn = psycopg.connect(_dsn(), autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("select to_regclass('public.content_engagements')")
            if cur.fetchone()[0] is None:
                pytest.skip("planning schema not applied (migrations 0084+)")
        yield conn
    finally:
        conn.close()


def _engagement(cur: Any, shape: str = "single_page") -> str:
    cur.execute(
        "insert into public.content_engagements (shape, name) values (%s, 'test') returning id",
        (shape,),
    )
    return cur.fetchone()[0]


def _job(cur: Any) -> str:
    cur.execute(
        "insert into public.content_jobs (page_type, topic, framework, target, status) "
        "values ('service','t','AIDA','WordPress','queued') returning id"
    )
    return cur.fetchone()[0]


# --------------------------------------------------------------------------- #
# The guard trigger - the reason 0090 was the risky migration
# --------------------------------------------------------------------------- #
def test_the_worker_can_write_the_new_columns_on_a_same_status_update(db: Any) -> None:
    """The pipeline streams cost/words/stage into a job WITHOUT changing status. The
    new planning columns must ride that same write, or they are unreachable from the
    only actor that would set them."""
    with db.cursor() as cur:
        cur.execute("select auth.uid() is null")
        assert cur.fetchone()[0], "this session is not on the worker branch"

        job, eng = _job(cur), _engagement(cur)
        cur.execute(
            "update public.content_jobs set engagement_id=%s, qa_weighted_total=87.5, "
            "experience_slots_missing=3 where id=%s",
            (eng, job),
        )
        cur.execute(
            "select engagement_id, qa_weighted_total, experience_slots_missing "
            "from public.content_jobs where id=%s",
            (job,),
        )
        assert cur.fetchone() == (eng, 87.5, 3)


def test_a_legal_pipeline_advance_still_works_with_the_new_columns(db: Any) -> None:
    with db.cursor() as cur:
        job = _job(cur)
        cur.execute(
            "update public.content_jobs set status='drafting', qa_weighted_total=91 where id=%s",
            (job,),
        )
        cur.execute("select status from public.content_jobs where id=%s", (job,))
        assert cur.fetchone()[0] == "drafting"


def test_the_guard_still_refuses_an_illegal_transition(db: Any) -> None:
    """0090 must not have WEAKENED the guard. A migration that adds columns and
    accidentally relaxes a lifecycle rule would pass every other test here."""
    psycopg = pytest.importorskip("psycopg")
    with db.cursor() as cur:
        job = _job(cur)
        cur.execute("update public.content_jobs set status='drafting' where id=%s", (job,))
        with pytest.raises(psycopg.errors.RaiseException, match="illegal system content transition"):
            cur.execute("update public.content_jobs set status='done' where id=%s", (job,))


def test_deleting_an_engagement_does_not_delete_the_job_ledger(db: Any) -> None:
    """ON DELETE SET NULL, deliberately. Cascading here would destroy delivered work
    because someone tidied up a planning record."""
    with db.cursor() as cur:
        job, eng = _job(cur), _engagement(cur)
        cur.execute("update public.content_jobs set engagement_id=%s where id=%s", (eng, job))
        cur.execute("delete from public.content_engagements where id=%s", (eng,))
        cur.execute("select engagement_id from public.content_jobs where id=%s", (job,))
        assert cur.fetchone() == (None,), "the job should survive with a nulled link"


# --------------------------------------------------------------------------- #
# Constraints that turn a judgement call into an enforced rule
# --------------------------------------------------------------------------- #
def test_two_nodes_cannot_target_the_same_primary_keyword(db: Any) -> None:
    """Cannibalisation as a UNIQUE CONSTRAINT rather than a report. Case-insensitive,
    because "AC Repair Austin" and "ac repair austin" compete for one query."""
    psycopg = pytest.importorskip("psycopg")
    with db.cursor() as cur:
        eng = _engagement(cur, "page_set")
        cur.execute(
            "insert into public.topical_maps (engagement_id) values (%s) returning id", (eng,)
        )
        map_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.topical_map_nodes (map_id, primary_keyword) values (%s, %s)",
            (map_id, "AC Repair Austin"),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "insert into public.topical_map_nodes (map_id, primary_keyword) values (%s, %s)",
                (map_id, "ac repair austin"),
            )


def test_a_client_can_have_only_one_active_brand_kit(db: Any) -> None:
    """Versioned history, one current truth. Two active kits would make "which design
    is this page built to" unanswerable."""
    psycopg = pytest.importorskip("psycopg")
    with db.cursor() as cur:
        cur.execute("insert into public.clients (name) values ('BrandKit Co') returning id")
        client = cur.fetchone()[0]
        cur.execute(
            "insert into public.brand_kits (client_id, version, active) values (%s,1,true)",
            (client,),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "insert into public.brand_kits (client_id, version, active) values (%s,2,true)",
                (client,),
            )
        # An inactive prior version is fine - that is the point of versioning.
        cur.execute(
            "insert into public.brand_kits (client_id, version, active) values (%s,2,false)",
            (client,),
        )


def test_a_keyword_appears_once_per_plan_case_insensitively(db: Any) -> None:
    """Counting "AC Repair" and "ac repair" separately would inflate every cluster."""
    psycopg = pytest.importorskip("psycopg")
    with db.cursor() as cur:
        eng = _engagement(cur, "page_set")
        cur.execute(
            "insert into public.keyword_plans (engagement_id) values (%s) returning id", (eng,)
        )
        plan = cur.fetchone()[0]
        cur.execute(
            "insert into public.keyword_plan_terms (plan_id, keyword, source) "
            "values (%s,'AC Repair','dataforseo')",
            (plan,),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "insert into public.keyword_plan_terms (plan_id, keyword, source) "
                "values (%s,'ac repair','dataforseo')",
                (plan,),
            )


def test_a_deliverable_must_belong_to_something(db: Any) -> None:
    """Without the check a row can be orphaned from both parents and become
    unreachable while still occupying storage."""
    psycopg = pytest.importorskip("psycopg")
    with db.cursor() as cur, pytest.raises(psycopg.errors.CheckViolation):
        cur.execute(
            "insert into public.content_deliverables (kind, artifact_key) "
            "values ('content_pdf','x')"
        )


def test_estimated_metrics_are_distinguishable_from_measured_ones(db: Any) -> None:
    """The column that ends the fabrication. A derived number is still allowed - it
    just can never again be mistaken for vendor data."""
    with db.cursor() as cur:
        eng = _engagement(cur, "page_set")
        cur.execute(
            "insert into public.keyword_plans (engagement_id) values (%s) returning id", (eng,)
        )
        plan = cur.fetchone()[0]
        cur.executemany(
            "insert into public.keyword_plan_terms (plan_id, keyword, volume, source, estimated) "
            "values (%s,%s,%s,%s,%s)",
            [
                (plan, "real kw", 1200, "dataforseo", False),
                (plan, "guessed kw", 900, "serp_derived", True),
            ],
        )
        cur.execute(
            "select count(*) from public.keyword_plan_terms where plan_id=%s and estimated=false",
            (plan,),
        )
        assert cur.fetchone()[0] == 1
