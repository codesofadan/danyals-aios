"""Migration 0148 must stay ahead of LangGraph's own checkpoint DDL.

WHY THIS TEST EXISTS. Neither runtime role may CREATE a table in ``public`` -
``0000_local_platform.sql`` grants USAGE only, because DDL belongs to migrations. So
``PostgresSaver.setup()`` cannot provision its own schema here, and 0148 does it instead,
seeding ``checkpoint_migrations`` so ``setup()`` finds nothing left to do.

That seed is a VERSION NUMBER copied out of a third-party package. When a LangGraph
upgrade appends a migration, the seed silently falls behind: ``setup()`` then tries to
run the new DDL, lacks the privilege, raises, and the runtime falls back to an in-memory
checkpointer with a warning. Everything keeps working. Nothing resumes - which, for a
module whose entire justification is resumption, is the worst possible way to fail,
because it looks exactly like success until a worker restarts mid-campaign.

So the guard is here rather than in a comment: a LangGraph upgrade that adds DDL FAILS
THE LOCAL GATE, and the fix is to write the next migration.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip(
    "langgraph.checkpoint.postgres",
    reason="the durable checkpointer is part of the optional [graph] extra",
)

from langgraph.checkpoint.postgres import PostgresSaver

pytestmark = pytest.mark.unit

MIGRATION = (
    Path(__file__).resolve().parents[2] / "db" / "migrations" / "0148_langgraph_checkpoints.sql"
)


def _seeded_max_version(sql: str) -> int:
    """The highest LangGraph migration version 0148 marks as applied."""
    match = re.search(r"generate_series\(\s*0\s*,\s*(\d+)\s*\)", sql)
    assert match, "0148 must seed checkpoint_migrations with a generate_series(0, N)"
    return int(match.group(1))


def test_the_migration_seeds_every_langgraph_checkpoint_version() -> None:
    """The seed must cover LangGraph's full migration list, or ``setup()`` wakes up.

    If this fails after an upgrade: read ``PostgresSaver.MIGRATIONS`` past the seeded
    index, write those statements into a NEW migration (0148 is already applied in
    production and must not be edited), and extend the seed to the new maximum.
    """
    seeded = _seeded_max_version(MIGRATION.read_text(encoding="utf-8"))
    expected = len(PostgresSaver.MIGRATIONS) - 1
    assert seeded == expected, (
        f"0148 seeds checkpoint_migrations up to v{seeded}, but the installed LangGraph "
        f"ships {len(PostgresSaver.MIGRATIONS)} migrations (max v{expected}). "
        "PostgresSaver.setup() will try to run the new DDL, lack the CREATE privilege, "
        "and the runtime will silently fall back to a NON-DURABLE in-memory "
        "checkpointer. Write the next migration."
    )


def test_the_migration_creates_every_table_the_runtime_probes_for() -> None:
    """The probe in ``graph._checkpoint_tables_present`` and the migration must agree.

    They are two lists of table names in two files. If the probe names a table 0148 does
    not create, the runtime concludes the schema is missing and calls ``setup()`` on a
    perfectly good database - falling back to in-memory on the permission error.
    """
    from app.platform.ai.graph import _CHECKPOINT_TABLES

    sql = MIGRATION.read_text(encoding="utf-8")
    for table in _CHECKPOINT_TABLES:
        assert re.search(rf"create table if not exists public\.{table}\b", sql), (
            f"the runtime probes for {table!r} but 0148 does not create it"
        )


def test_every_checkpoint_table_is_rls_enabled_and_forced() -> None:
    """Invariant #10 applies to these tables too, and ``app/db/rls_check.py`` enforces it.

    They hold graph execution state - including drafted article bodies - so "it is only
    infrastructure" is not a reason to leave them open. With no policy at all, FORCE RLS
    makes them default-deny for ``authenticated``: a leaked portal or staff DB credential
    reads nothing. ``service_role`` still writes them, by BYPASSRLS.
    """
    from app.platform.ai.graph import _CHECKPOINT_TABLES

    sql = MIGRATION.read_text(encoding="utf-8")
    for table in _CHECKPOINT_TABLES:
        assert re.search(rf"alter table public\.{table}\s+enable row level security", sql)
        assert re.search(rf"alter table public\.{table}\s+force row level security", sql)


def test_the_migration_grants_no_access_to_the_tenant_role() -> None:
    """``authenticated`` must not appear in 0148's grants.

    Checkpoints are not tenant data and carry no ``client_id`` to scope a policy by, so
    there is no correct policy to write for the tenant role - which makes granting it
    access a decision with no safe follow-up.
    """
    sql = MIGRATION.read_text(encoding="utf-8")
    grants = [line for line in sql.splitlines() if line.strip().lower().startswith("grant")]
    assert grants, "0148 must grant service_role its DML explicitly"
    assert not any("authenticated" in line for line in grants)
    assert not any("anon" in line for line in grants)
