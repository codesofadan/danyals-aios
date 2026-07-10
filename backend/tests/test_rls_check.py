"""P2-1 gate: the RLS coverage checker flags tables without FORCE RLS."""

from __future__ import annotations

import pytest

from app.db.rls_check import TableRow, find_unprotected


@pytest.mark.unit
def test_flags_tables_missing_enable_or_force() -> None:
    rows: list[TableRow] = [
        ("users", True, True),      # protected
        ("clients", True, False),   # RLS on but NOT forced -> owner bypasses
        ("sites", False, False),    # RLS off entirely
    ]
    assert find_unprotected(rows) == ["clients", "sites"]


@pytest.mark.unit
def test_all_protected_returns_empty() -> None:
    rows: list[TableRow] = [("users", True, True), ("clients", True, True)]
    assert find_unprotected(rows) == []


@pytest.mark.unit
def test_allowlist_excludes_named_tables() -> None:
    rows: list[TableRow] = [("schema_migrations", False, False)]
    assert find_unprotected(rows, allowlist=frozenset({"schema_migrations"})) == []


@pytest.mark.unit
def test_empty_catalog_is_clean() -> None:
    assert find_unprotected([]) == []
