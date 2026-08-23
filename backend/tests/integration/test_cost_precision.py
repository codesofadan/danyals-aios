"""Integration: the money columns can hold the money, asked of a REAL database.

This suite is deliberately not a migration-file grep. A column's type is its creating
migration plus every later ALTER, and this repo has 80+ of them: `client_budgets.cap`
is `integer` in `0006`, `numeric(10,2)` after `0044`, and `numeric(12,6)` after `0083`.
Two sessions got that fact wrong in one day by reading the CREATE TABLE. The only
oracle that cannot be wrong is a built schema, so that is what these tests ask.
See `db/migrations/README.md`, "Reading a column's CURRENT type".

WHAT IT GUARDS. Before `0083`, `cost_log.cost` and `client_budgets.cap`/`.spent` were
`numeric(10,2)`. A DataForSEO Maps grid point costs $0.000600 and an organic rank check
$0.001200, so the platform's two highest-volume line items **both rounded to $0.00 on
the way in** - the ledger reported the grid as free, and the per-client cap could never
trip on it no matter how many ran.

Widening one table without the other is worse than widening neither: the ledger would
report spend the cap cannot see. So the pairing is asserted, not just the precision.

Skips unless DATABASE_ADMIN_URL is set.
"""

from __future__ import annotations

import contextlib
import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.config import get_settings
from app.db.database import build_admin_pool, clear_pools, privileged_connection, set_pools

pytestmark = pytest.mark.integration

#: The real charges this precision exists for. Sourced from R5 §3.2 (DataForSEO's
#: published post-19-September-2025 organic pricing and its Maps pricing).
_GRID_POINT = Decimal("0.000600")
_RANK_CHECK = Decimal("0.001200")

#: Every money column in the platform. They must agree: a charge the ledger can record
#: but the cap cannot accumulate is an enforcement gap, not a rounding detail.
_MONEY_COLUMNS = [
    ("cost_log", "cost"),
    ("client_budgets", "cap"),
    ("client_budgets", "spent"),
    ("job_runs", "cost_usd"),
]


@pytest.fixture
def db() -> Any:
    settings = get_settings()
    if not settings.database_admin_url:
        pytest.skip("local Postgres not configured (DATABASE_ADMIN_URL)")
    pool = build_admin_pool(settings.database_admin_url)
    assert pool is not None
    pool.open()
    set_pools(None, pool)
    client_id = str(uuid.uuid4())
    with privileged_connection(pool=pool) as cur:
        cur.execute(
            "insert into public.clients (id, name, delivery_tier) values (%s, %s, 'free')",
            (client_id, f"Precision Co {client_id[:8]}"),
        )
    try:
        yield client_id
    finally:
        with contextlib.suppress(Exception), privileged_connection(pool=pool) as cur:
            cur.execute("delete from public.cost_log where client_id = %s", (client_id,))
            cur.execute("delete from public.client_budgets where client_id = %s", (client_id,))
            cur.execute("delete from public.clients where id = %s", (client_id,))
        clear_pools()
        pool.close()


def _precision(table: str, column: str) -> tuple[int, int]:
    with privileged_connection() as cur:
        cur.execute(
            "select numeric_precision, numeric_scale from information_schema.columns "
            "where table_schema = 'public' and table_name = %s and column_name = %s",
            (table, column),
        )
        row = cur.fetchone()
    assert row is not None, f"public.{table}.{column} does not exist in the built schema"
    return int(row["numeric_precision"]), int(row["numeric_scale"])


# --------------------------------------------------------------------------- #
# The columns
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("table", "column"), _MONEY_COLUMNS)
def test_every_money_column_holds_six_decimals(db: str, table: str, column: str) -> None:
    """Six decimals, because the platform's commonest charge is $0.000600."""
    precision, scale = _precision(table, column)
    assert scale >= 6, (
        f"public.{table}.{column} has scale {scale}: a ${_GRID_POINT} grid point "
        f"rounds to {'$0.00' if scale == 2 else 'zero'} and the line item looks free"
    )
    assert precision >= 12, f"public.{table}.{column} precision {precision} is too narrow"


def test_the_ledger_and_the_cap_agree(db: str) -> None:
    """The pairing, not just the precision.

    If `cost_log.cost` records what `client_budgets.spent` cannot accumulate, the cap
    silently under-counts the exact traffic it exists to bound - and the ledger looks
    healthy while the enforcement is blind.
    """
    assert _precision("cost_log", "cost") == _precision("client_budgets", "spent")


# --------------------------------------------------------------------------- #
# The behaviour the columns exist for
# --------------------------------------------------------------------------- #
def test_a_sub_cent_charge_survives_the_round_trip(db: str) -> None:
    with privileged_connection() as cur:
        cur.execute(
            "insert into public.cost_log "
            "(client_id, client_name, job_type, provider, cost, cached) "
            "values (%s, 'Precision Co', 'grid', 'dataforseo', %s, false) returning cost",
            (db, _GRID_POINT),
        )
        recorded = cur.fetchone()["cost"]
    assert recorded == _GRID_POINT, (
        f"a ${_GRID_POINT} grid point recorded as ${recorded} - the platform's "
        "highest-volume line item is being logged as free"
    )


def test_sub_cent_charges_accumulate_against_the_cap(db: str) -> None:
    """The defect in one assertion.

    `add_budget_spend` is the SECURITY DEFINER helper the cost gate calls after every
    paid provider call. At numeric(10,2) these three charges accumulated to 0.15 and
    $0.0018 vanished; the cap could run all day on grid traffic and never move.
    """
    charges = [_GRID_POINT, _RANK_CHECK, Decimal("0.150000")]
    with privileged_connection() as cur:
        for amount in charges:
            cur.execute("select public.add_budget_spend(%s::uuid, %s::numeric)", (db, amount))
        cur.execute("select spent from public.client_budgets where client_id = %s", (db,))
        spent = cur.fetchone()["spent"]

    assert spent == sum(charges), (
        f"spent={spent} but the true total is {sum(charges)} - "
        f"${sum(charges) - spent} of real spend is invisible to the per-client cap"
    )


def test_a_thousand_grid_points_are_not_free(db: str) -> None:
    """The volume case, which is the one that actually costs money.

    A single 7x7 grid scan is 49 coordinates; R5 models 58,800 per month at 100
    clients. Rounding each to zero is not a rounding error, it is the whole line item.
    """
    with privileged_connection() as cur:
        for _ in range(1000):
            cur.execute("select public.add_budget_spend(%s::uuid, %s::numeric)", (db, _GRID_POINT))
        cur.execute("select spent from public.client_budgets where client_id = %s", (db,))
        spent = cur.fetchone()["spent"]

    assert spent == _GRID_POINT * 1000 == Decimal("0.600000"), (
        f"1000 grid points accumulated {spent}, expected 0.600000"
    )
