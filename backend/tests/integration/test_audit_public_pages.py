"""The shareable public report link, against a real Postgres.

WHY THIS FILE EXISTS RATHER THAN MORE UNIT TESTS. The endpoint tests in
`tests/test_audits_endpoints.py` drive a FAKE repo, so they pin the route's
behaviour given a repo contract - they cannot pin the SQL. Proven the hard way:
deleting `where published` from the real query left every one of them green,
because none of them ever ran it. The filter is the whole control (an
unpublished page must never be reported as a link), so it is pinned here, where
Postgres is the thing answering.

`AuditsRepo` is RLS-scoped, and `public_audit_pages` admits staff via
`is_staff()`. These tests run the queries on the privileged pool - the same
service_role path the public route uses - because the point under test is the
SQL, not the policy; RLS itself is covered by the dedicated RLS gate.

Skips unless a Postgres with migration 0126 is configured.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

pytestmark = pytest.mark.integration

_DSN_KEYS = ("DATABASE_MIGRATE_URL", "DATABASE_ADMIN_URL", "DATABASE_URL")


@pytest.fixture
def db() -> Any:
    dsn = next((os.environ[k] for k in _DSN_KEYS if os.environ.get(k)), None)
    if not dsn:
        pytest.skip(f"no Postgres configured (set one of {', '.join(_DSN_KEYS)})")
    pytest.importorskip("psycopg_pool")
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    from app.db.database import clear_pools, set_pools

    pool = ConnectionPool(dsn, min_size=1, max_size=2, kwargs={"row_factory": dict_row}, open=True)
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("select to_regclass('public.public_audit_pages')")
            if cur.fetchone()["to_regclass"] is None:
                pytest.skip("public page registry not applied (migration 0126)")
        set_pools(rls=pool, admin=pool)
        yield pool
    finally:
        clear_pools()
        pool.close()


def _audit(url: str = "https://northpeak.example") -> str:
    """A real audit row - `public_audit_pages.audit_id` is a FK."""
    from app.db.database import privileged_connection

    with privileged_connection() as cur:
        cur.execute(
            "insert into public.audits (url, tier, status) "
            "values (%s, 'paid', 'done') returning id",
            (url,),
        )
        return str(cur.fetchone()["id"])


def _page(audit_id: str, *, published: bool) -> str:
    """Mint a page row for `audit_id` and return its slug.

    The slug is DERIVED from the audit's own (fresh) uuid rather than hardcoded:
    `slug` is the primary key and these rows are not torn down between runs, so
    a fixed literal passes once and then fails with a unique violation forever
    after - a test that only works on a clean database is a test that will be
    ignored.
    """
    from app.db.database import privileged_connection

    slug = f"pp-{audit_id.replace('-', '')[:16]}"
    with privileged_connection() as cur:
        cur.execute(
            "insert into public.public_audit_pages (slug, kind, audit_id, published) "
            "values (%s, 'paid', %s, %s)",
            (slug, audit_id, published),
        )
    return slug


def _repo() -> Any:
    from app.db.audits_repo import AuditsRepo

    # The user id only selects the RLS pool binding; these tests run on the
    # privileged pool set above, so any id serves.
    return AuditsRepo("00000000-0000-0000-0000-000000000000")


def test_an_unpublished_page_is_never_returned_as_a_live_link(db: Any) -> None:
    """THE CONTROL. `published_pages` feeds the audit board's links, so a row
    leaking in here becomes a URL an operator pastes into a chat - and it 404s
    for whoever receives it. Re-inject by deleting `where published` from the
    query and this fails."""
    audit_id = _audit()
    _page(audit_id, published=False)

    assert audit_id not in _repo().published_pages()


def test_a_published_page_is_returned_with_its_slug(db: Any) -> None:
    audit_id = _audit()
    slug = _page(audit_id, published=True)

    assert _repo().published_pages().get(audit_id) == slug


def test_public_page_reports_the_row_whatever_its_state(db: Any) -> None:
    """`public_page` is the DETAIL read and deliberately does NOT filter on
    published: the publish endpoint needs to know a page exists in order to
    publish it. The filtering belongs at the point a LINK is rendered, which is
    why the two reads differ."""
    audit_id = _audit()
    slug = _page(audit_id, published=False)

    row = _repo().public_page(audit_id)
    assert row is not None
    assert row["slug"] == slug
    assert row["published"] is False


def test_publishing_flips_the_row_and_makes_the_link_live(db: Any) -> None:
    audit_id = _audit()
    slug = _page(audit_id, published=False)
    repo = _repo()

    row = repo.set_public_page_published(audit_id, published=True)

    assert row is not None and row["published"] is True
    assert repo.published_pages().get(audit_id) == slug


def test_unpublishing_takes_the_link_back_down(db: Any) -> None:
    """A link that has been sent out must be revocable, or publishing is a
    one-way door."""
    audit_id = _audit()
    _page(audit_id, published=True)
    repo = _repo()

    repo.set_public_page_published(audit_id, published=False)

    assert audit_id not in repo.published_pages()


def test_publishing_an_audit_with_no_page_row_updates_nothing(db: Any) -> None:
    """Zero rows updated must come back as None so the route can refuse, rather
    than reporting a success that put no report anywhere."""
    audit_id = _audit()  # no page minted

    assert _repo().set_public_page_published(audit_id, published=True) is None


def test_a_page_dies_with_its_audit(db: Any) -> None:
    """`on delete cascade` in 0126: a deleted audit must not leave a slug
    resolving to a report that no longer exists."""
    from app.db.database import privileged_connection

    audit_id = _audit()
    slug = _page(audit_id, published=True)

    with privileged_connection() as cur:
        cur.execute("delete from public.audits where id = %s", (audit_id,))
        cur.execute(
            "select count(*) as n from public.public_audit_pages where slug = %s",
            (slug,),
        )
        assert cur.fetchone()["n"] == 0
