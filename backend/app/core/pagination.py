"""Offset/limit pagination with hard caps for the DB-backed list endpoints.

A single :data:`PageDep` dependency parses ``?limit=&offset=`` off the query
string, enforcing the hard caps at the edge (``1 <= limit <= 200``, ``offset >=
0``) so no handler can ever ask the database for an unbounded page. The frozen
:class:`Page` value object is threaded into the repos, which translate it to a
supabase-py ``.range(offset, offset + limit - 1)`` (inclusive) window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query


@dataclass(frozen=True)
class Page:
    """A validated pagination window: a hard-capped ``limit`` and an ``offset``."""

    limit: int
    offset: int


def pagination(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page:
    """Dependency: the caller's page window, with the caps enforced by ``Query``."""
    return Page(limit, offset)


PageDep = Annotated[Page, Depends(pagination)]
