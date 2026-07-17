"""Every off-page ``backlinks`` statement must pin ``competitor_id is null``.

WHY THIS EXISTS (a latent landmine, defused by construction rather than by comment):

``0018``'s ``backlinks`` ledger was strictly the CLIENT's own profile - one row per
``(client, ref_domain)``, with no notion of *whose* site the link points at. Part 8's
``competitor_intel`` (``0037``) needed a backlink GAP ("domains linking to my rival but
not to me"), which that shape physically cannot express. Rather than fabricate the fact
(presenting other clients' referring domains as "your competitors' links"), ``0037``
gave the EXISTING ledger the missing dimension: a nullable ``competitor_id`` where

* ``competitor_id IS NULL``  -> what every pre-existing row means: a link to the
  CLIENT's own site (the off-page board's subject), and
* ``competitor_id IS NOT NULL`` -> a COMPETITOR-side link, owned by competitor_intel.

That makes every unpinned off-page query a future bug. It is harmless *today* only
because nothing populates competitor-side rows yet - so the failure would not appear
in any test the day it is introduced; it would appear the day someone funds a
competitor backlink ingest, and it would appear as a CLIENT seeing its rival's links
presented as its own (and, on the toxic-flagger's write path, being asked to disavow
them). A comment cannot prevent that. This sweep can.

It is AUTO-DISCOVERING: it parses ``offpage_repo.py`` and checks every statement that
touches ``public.backlinks``, so a NEW query added later is covered with no edit here.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1] / "app" / "db" / "offpage_repo.py"

# A statement "touches the ledger" if it names the table at all.
_TOUCHES = re.compile(r"\bpublic\.backlinks\b")
# The pin, tolerant of whitespace/newline-joined SQL fragments.
_PINNED = re.compile(r"competitor_id\s+is\s+null", re.IGNORECASE)
# An INSERT is exempt BY CONSTRUCTION, not by oversight: it creates a brand-new
# own-profile row and simply never sets competitor_id, which defaults to NULL. The
# pin is a predicate over EXISTING rows, so it is meaningless in a VALUES clause -
# only SELECT / UPDATE / DELETE can wrongly reach a competitor-side row.
_INSERT = re.compile(r"^\s*insert\s+into\b", re.IGNORECASE)


def _sql_literals(path: Path) -> list[tuple[int, str]]:
    """Every string literal in the module, with its line number.

    AST + implicit-concatenation aware: the repo builds SQL from adjacent string
    literals across lines, so a raw line-by-line grep would see half a predicate and
    a naive `in source` check would match a docstring that merely mentions the table.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.lineno, node.value))
    return out


def _ledger_statements() -> list[tuple[int, str]]:
    """SQL literals that touch public.backlinks (docstrings excluded)."""
    doc_lines = {
        n.lineno
        for n in ast.walk(ast.parse(_REPO.read_text(encoding="utf-8")))
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
        and isinstance(n.value.value, str)
    }
    return [
        (line, text)
        for line, text in _sql_literals(_REPO)
        if _TOUCHES.search(text) and line not in doc_lines and not _INSERT.match(text)
    ]


def test_the_sweep_actually_finds_statements() -> None:
    """Guard-for-the-guard: a parse bug must FAIL loudly, never vacuously pass."""
    found = _ledger_statements()
    assert len(found) >= 4, f"expected several backlinks statements, found {found}"


def test_every_backlinks_statement_pins_the_own_profile() -> None:
    """No off-page query may see a competitor-side row."""
    unpinned: list[tuple[int, str]] = []
    for line, text in _ledger_statements():
        # The statement may be built from concatenated fragments; the pin can live in
        # an adjacent literal, so check the whole call's source region rather than the
        # single fragment. Simplest sound approximation: the module text after this
        # literal's line, bounded to the enclosing statement (~8 lines).
        src = _REPO.read_text(encoding="utf-8").splitlines()
        window = "\n".join(src[max(0, line - 3) : line + 8])
        if not _PINNED.search(window):
            unpinned.append((line, text.strip()[:70]))
    assert not unpinned, (
        "these public.backlinks statements do not pin `competitor_id is null`, so they "
        "would surface a COMPETITOR's links as the client's own the moment a "
        "competitor backlink ingest lands (see 0037):\n"
        + "\n".join(f"  offpage_repo.py:{ln}  {sql}" for ln, sql in unpinned)
    )
