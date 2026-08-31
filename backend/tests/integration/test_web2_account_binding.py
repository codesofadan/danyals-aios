"""A placement must be bound to the account that will publish it (real Postgres).

THE DEFECT THIS EXISTS TO CATCH. ``web2_accounts register`` seals a credential in the
vault under ``label = <web2_accounts.id>``. The publish worker resolves that label from
``web2_properties.account_id`` and, when it is NULL, falls back to the client id. Nothing
on the forward path ever wrote ``account_id`` - ``create_web2`` simply omitted the column -
so the fallback fired every time and looked for a secret under a label nothing was sealed
under. The result was the worst possible shape of failure: the whole campaign planned, N
articles DRAFTED AND PAID FOR, a lead approving them at the human gate, and then every
property bouncing back to ``needs_review`` with "degraded: publisher unconfigured", while
the accounts board and the credential check both reported the account active.

The same NULL also disarmed the per-account pacing ceilings, which key off this column.

These run against real Postgres because the binding is a SQL sub-select: a fake store
would encode whatever the test author believed, which is precisely what went wrong.
"""

from __future__ import annotations

import os
import uuid
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

    pool = ConnectionPool(dsn, min_size=1, max_size=2, kwargs={"row_factory": dict_row}, open=True)
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("select to_regclass('public.web2_accounts')")
            if cur.fetchone()["to_regclass"] is None:
                pytest.skip("web2 accounts schema not applied (migration 0100)")
        yield pool
    finally:
        pool.close()


def _repo_on(cur: Any) -> Any:
    """The REAL repo, with its RLS seam pointed at this cursor."""
    from contextlib import contextmanager

    import app.db.offpage_repo as repo_mod

    @contextmanager
    def _live(_user_id: str | None = None) -> Any:
        yield cur

    repo_mod.rls_connection = _live
    return repo_mod.OffpageRepo("u-integration")


def _client(cur: Any, *, scope: str = "developer") -> str:
    cur.execute(
        "insert into public.clients (name, industry, web2_topical_scope) "
        "values (%s, 'test', %s) returning id",
        (f"acct-binding-{uuid.uuid4().hex[:8]}", scope),
    )
    return str(cur.fetchone()["id"])


def _seal(cur: Any, provider: str, label: str) -> None:
    """A credential row for this account. Content is irrelevant here - EXISTENCE is what
    the connected-set predicate checks."""
    cur.execute(
        "insert into public.vault_keys (provider, label, masked, secret_sealed, kind) "
        "values (%s, %s, '****', %s, 'client_access')",
        (provider, label, b"x" * 40),
    )


def _account(cur: Any, *, platform: str, ownership: str, client_id: str | None,
             health: str = "active", with_credential: bool = True) -> str:
    cur.execute(
        "insert into public.web2_accounts "
        "(platform, ownership, client_id, handle, registration_email, health, "
        " vault_provider, vault_label) "
        "values (%s, %s, %s, %s, 'x@y.test', %s, %s, '') returning id",
        (platform, ownership, client_id, f"h{uuid.uuid4().hex[:8]}", health,
         f"web2:{platform}"),
    )
    account_id = str(cur.fetchone()["id"])
    # Exactly what the CLI does: the vault label IS the account id.
    cur.execute("update public.web2_accounts set vault_label = %s where id = %s",
                (account_id, account_id))
    if with_credential:
        _seal(cur, f"web2:{platform}", account_id)
    return account_id


def _place(repo: Any, client_id: str, platform: str) -> dict[str, Any]:
    return repo.create_web2(
        client_id=client_id, client_name="T", platform=platform, anchor="T",
        target_url="https://example.test/", topic=f"t-{uuid.uuid4().hex[:6]}",
        page_type="blog", framework="Auto", source_pack={},
    )


def test_a_placement_is_bound_to_the_clients_own_account(db: Any) -> None:
    """The defect: this was NULL, so publish looked up the wrong vault label."""
    with db.connection() as conn, conn.cursor() as cur:
        repo = _repo_on(cur)
        client_id = _client(cur)
        account_id = _account(cur, platform="dev.to", ownership="per_client",
                              client_id=client_id)

        row = _place(repo, client_id, "dev.to")

        assert row is not None
        assert str(row["account_id"]) == account_id, (
            "the placement must carry the account whose vault label holds the credential"
        )
        # And that id is what the worker will hand the vault.
        cur.execute("select vault_label from public.web2_accounts where id = %s", (account_id,))
        assert str(cur.fetchone()["vault_label"]) == str(row["account_id"])
        conn.rollback()


def test_another_clients_account_is_never_bound(db: Any) -> None:
    """Ownership is load-bearing: a per_client platform must not borrow a stranger's
    account, or one agency identity ends up behind every client's links."""
    with db.connection() as conn, conn.cursor() as cur:
        repo = _repo_on(cur)
        mine, theirs = _client(cur), _client(cur)
        _account(cur, platform="dev.to", ownership="per_client", client_id=theirs)

        row = _place(repo, mine, "dev.to")

        assert row["account_id"] is None, (
            "another client's account must never be bound to this client's placement"
        )
        conn.rollback()


def test_a_suspended_account_is_not_bound(db: Any) -> None:
    """A credential that no longer logs in is not a credential."""
    with db.connection() as conn, conn.cursor() as cur:
        repo = _repo_on(cur)
        client_id = _client(cur)
        _account(cur, platform="dev.to", ownership="per_client", client_id=client_id,
                 health="suspended")

        row = _place(repo, client_id, "dev.to")

        assert row["account_id"] is None
        conn.rollback()


def test_the_board_and_the_placement_agree(db: Any) -> None:
    """The two callers share one ownership rule, so they cannot drift: whatever the
    board calls connected must be exactly what a placement can bind to."""
    with db.connection() as conn, conn.cursor() as cur:
        repo = _repo_on(cur)
        client_id = _client(cur)
        _account(cur, platform="dev.to", ownership="per_client", client_id=client_id)

        connected = repo.connected_platforms_for(client_id)
        assert "dev.to" in connected

        for platform in sorted(connected):
            row = _place(repo, client_id, platform)
            assert row["account_id"] is not None, (
                f"the board reports {platform} connected, but a placement bound no account"
            )
        conn.rollback()


def test_an_account_with_no_sealed_credential_is_not_connected(db: Any) -> None:
    """MEASURED on the canonical database 2026-08-30: six platforms reported ELIGIBLE
    while not one credential resolved.

    An account ROW is not a credential. Registration writes the row first and seals the
    secret second, so a half-finished registration leaves a row with nothing behind it.
    Counting that as connected lets a campaign be planned, DRAFTED AND PAID FOR, and
    approved - and every publish then fails with "publisher unconfigured".
    """
    with db.connection() as conn, conn.cursor() as cur:
        repo = _repo_on(cur)
        client_id = _client(cur)
        _account(cur, platform="dev.to", ownership="per_client", client_id=client_id,
                 with_credential=False)

        assert repo.connected_platforms_for(client_id) == set(), (
            "an account with no sealed credential must not count as connected"
        )
        row = _place(repo, client_id, "dev.to")
        assert row["account_id"] is None
        conn.rollback()


def test_sealing_the_credential_is_what_makes_it_connected(db: Any) -> None:
    """The other direction, so the guard cannot pass by refusing everything."""
    with db.connection() as conn, conn.cursor() as cur:
        repo = _repo_on(cur)
        client_id = _client(cur)
        account_id = _account(cur, platform="dev.to", ownership="per_client",
                              client_id=client_id, with_credential=False)
        assert repo.connected_platforms_for(client_id) == set()

        _seal(cur, "web2:dev.to", account_id)

        assert repo.connected_platforms_for(client_id) == {"dev.to"}
        assert str(_place(repo, client_id, "dev.to")["account_id"]) == account_id
        conn.rollback()
