"""The Web 2.0 similarity candidate query, against a real Postgres.

This file exists because of a defect that ONLY a real database could show, and that
every unit test in the suite happily passed over.

The candidate query ended `order by id, shared desc limit 200`. `distinct on (id)`
forces `id` to lead the inner ORDER BY, so the outer limit kept the 200 lowest random
UUIDs - an arbitrary subset. Once a client's corpus exceeded the limit, a byte-exact
duplicate whose row happened to sort high was silently discarded, `evaluate` scored 200
non-matches, and the gate returned `pass` on an identical article. Measured on a
251-document corpus: the duplicate was absent from the result and the verdict was clean.

It degraded AS THE CORPUS GREW - worst exactly where the gate matters most - which is
the failure this module's own migration header calls "the worst possible failure for a
safety control (it would look installed and be partial)".

Skips unless a Postgres with migrations 0100-0102 is configured.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.integration

_DSN_KEYS = ("DATABASE_MIGRATE_URL", "DATABASE_ADMIN_URL", "DATABASE_URL")

# Deliberately ABOVE the query's 200-row cap: below it, the truncation cannot bite and
# the test would pass against the defect it exists to catch.
_DECOYS = 250

_BASE = (
    "# Emergency Drain Unblocking Guide\n\n"
    "The engineer arrives with a jetting unit and a survey camera, clears the blockage, "
    "then films the run again so the customer can confirm the pipe is genuinely clear "
    "before the visit is signed off and the invoice is raised.\n"
)


@pytest.fixture
def store() -> Any:
    dsn = next((os.environ[k] for k in _DSN_KEYS if os.environ.get(k)), None)
    if not dsn:
        pytest.skip(f"no Postgres configured (set one of {', '.join(_DSN_KEYS)})")
    pytest.importorskip("psycopg_pool")
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    from app.db.database import clear_pools, set_pools
    from app.db.offpage_repo import ServiceOffpageStore

    pool = ConnectionPool(dsn, min_size=1, max_size=2, kwargs={"row_factory": dict_row}, open=True)
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("select to_regclass('public.web2_doc_fingerprints')")
            if cur.fetchone()["to_regclass"] is None:
                pytest.skip("web2 similarity schema not applied (migrations 0100-0102)")
        set_pools(rls=pool, admin=pool)
        yield ServiceOffpageStore()
    finally:
        clear_pools()
        pool.close()


def _seed(store: Any, client_id: str) -> tuple[str, Any]:
    """A corpus of `_DECOYS` near-identical documents plus one EXACT duplicate.

    The decoys all share sampled hashes with the probe, so they genuinely compete for
    the 200 candidate slots - a corpus of unrelated documents would leave room for the
    duplicate and prove nothing.
    """
    from app.db.database import privileged_connection
    from app.services.web2_similarity import fingerprint

    with privileged_connection() as cur:
        cur.execute("delete from public.web2_doc_fingerprints")
        cur.execute(
            "insert into public.clients (id, name) values (%s, %s) on conflict do nothing",
            (client_id, "Similarity Corpus"),
        )

    def _property() -> str:
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.web2_properties "
                "(client_id, client_name, platform, post_url, anchor, verified) "
                "values (%s, 'Corpus', 'Blogger', '', 'a', 'pending') returning id",
                (client_id,),
            )
            return str(cur.fetchone()["id"])

    for i in range(_DECOYS):
        fp = fingerprint(body_md=f"{_BASE}\nExtra note number {i}.\n", client_name="C", geo="G")
        store.record_web2_fingerprint(
            web2_id=_property(), client_id=client_id, account_id=None, platform="Blogger",
            body_sha256=fp.body_sha256, shingle_hashes=list(fp.body_hashes),
            heading_hashes=list(fp.heading_hashes), sampled_hashes=list(fp.sampled),
            anchor_norm="", status_at_capture="published",
        )

    # The duplicate's FINGERPRINT id is pinned to the maximum uuid, deliberately.
    # `gen_random_uuid()` would place it at a random position, so under the defective
    # uuid-ordered LIMIT it landed in the surviving 200 about four times in five and the
    # guard passed over the bug it exists to catch. Pinning it to the very end makes the
    # truncation deterministic: with the defect it is ALWAYS dropped, without it never.
    dup = fingerprint(body_md=_BASE, client_name="C", geo="G")
    dup_id = _property()
    max_fp_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    with privileged_connection() as cur:
        cur.execute(
            "insert into public.web2_doc_fingerprints "
            "(id, web2_id, client_id, account_id, platform, body_sha256, shingle_hashes, "
            " shingle_count, heading_hashes, anchor_norm, status_at_capture) "
            "values (%s, %s, %s, null, 'Blogger', %s, %s, %s, %s, '', 'published')",
            (
                max_fp_id, dup_id, client_id, dup.body_sha256, list(dup.body_hashes),
                len(dup.body_hashes), list(dup.heading_hashes),
            ),
        )
        cur.executemany(
            "insert into public.web2_shingle_index (shingle_hash, fingerprint_id) "
            "values (%s, %s) on conflict do nothing",
            [(h, max_fp_id) for h in dup.sampled],
        )
    return dup_id, dup


def test_an_exact_duplicate_survives_a_corpus_larger_than_the_candidate_cap(store: Any) -> None:
    """The regression. The exact-duplicate branch is documented as unconditional, so it
    must never be one of the rows the LIMIT throws away."""
    client_id = str(uuid.uuid4())
    dup_id, dup = _seed(store, client_id)

    rows = store.web2_similarity_candidates(
        sampled_hashes=list(dup.sampled), body_sha256=dup.body_sha256,
        client_id=client_id, account_id=None, platform="Blogger",
        exclude_web2_id=str(uuid.uuid4()),
    )
    assert len(rows) > 0
    assert any(str(r["web2_id"]) == dup_id for r in rows), (
        "the exact duplicate was truncated away by the candidate limit - the gate would "
        "return `pass` on an identical article"
    )


def test_the_exact_match_sorts_first_so_it_can_never_be_truncated(store: Any) -> None:
    """Ordering by relevance rather than by uuid is what makes the guarantee hold at any
    corpus size; pinning the sentinel keeps that from being quietly reverted."""
    client_id = str(uuid.uuid4())
    dup_id, dup = _seed(store, client_id)

    rows = store.web2_similarity_candidates(
        sampled_hashes=list(dup.sampled), body_sha256=dup.body_sha256,
        client_id=client_id, account_id=None, platform="Blogger",
        exclude_web2_id=str(uuid.uuid4()),
    )
    assert str(rows[0]["web2_id"]) == dup_id
    assert rows[0]["shared"] == 2147483647  # the exact-match sentinel


def test_the_gate_returns_block_on_that_corpus(store: Any) -> None:
    """End to end: the query feeding the real scorer yields a BLOCK, not just a row."""
    from app.config import Settings
    from app.services import web2_gate

    client_id = str(uuid.uuid4())
    _dup_id, _dup = _seed(store, client_id)

    outcome = web2_gate.evaluate_draft(
        store,
        Settings(_env_file=None),  # type: ignore[call-arg]
        web2_id=str(uuid.uuid4()),
        row={"client_id": client_id, "platform": "Blogger", "anchor": "a", "account_id": None},
        body_md=_BASE,
        client_name="C",
        geo="G",
    )
    assert outcome.verdict == "block"
    assert outcome.code.startswith("sim_block:body_sha256:")
