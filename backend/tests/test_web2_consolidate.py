"""The ledger move must never guess. Pure tests over `plan()` with fake cursors.

WHAT THIS PROTECTS. Moving placements between databases is exactly where a tool is
tempted to be helpful: invent the missing client, or re-point a live placement at
whichever account looks close enough. Both silently misattribute work that is already
published under someone's name. `plan()` refuses instead, and says why.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.cli.web2_consolidate import plan

pytestmark = pytest.mark.unit


class _Cur:
    """A cursor that answers each query from a queue of canned result sets."""

    def __init__(self, results: list[list[dict[str, Any]]]) -> None:
        self._results = results
        self._next: list[dict[str, Any]] = []

    def execute(self, *_args: Any, **_kw: Any) -> None:
        self._next = self._results.pop(0) if self._results else []

    def fetchall(self) -> list[dict[str, Any]]:
        return self._next


def _property(**over: Any) -> dict[str, Any]:
    row = {
        "id": "w2-1", "client_id": "src-cl", "src_client": "Acme", "platform": "dev.to",
        "topic": "a topic", "post_url": "https://dev.to/acme/a-topic",
        "account_id": "src-acct", "status": "published",
    }
    row.update(over)
    return row


def _target(clients: list[dict[str, Any]], accounts: list[dict[str, Any]],
            existing: list[dict[str, Any]]) -> _Cur:
    return _Cur([clients, accounts, existing])


def test_a_placement_moves_when_its_client_and_account_both_exist() -> None:
    source = _Cur([[_property()]])
    target = _target(
        [{"id": "tgt-cl", "name": "Acme"}],
        [{"id": "tgt-acct", "platform": "dev.to", "client_name": "Acme"}],
        [],
    )
    movable, problems = plan(source, target)
    assert problems == []
    assert len(movable) == 1
    assert movable[0]["_client_id"] == "tgt-cl"
    assert movable[0]["_account_id"] == "tgt-acct", "must re-point at the TARGET's account"


def test_an_unknown_client_is_refused_rather_than_invented() -> None:
    source = _Cur([[_property(src_client="Nobody Ltd")]])
    target = _target([{"id": "tgt-cl", "name": "Acme"}], [], [])
    movable, problems = plan(source, target)
    assert movable == []
    assert any("no client of that name" in p for p in problems)


def test_a_missing_account_is_refused_rather_than_guessed() -> None:
    """Re-pointing a LIVE placement at the wrong account misattributes every future
    publish through it, and the URL is already out in the world under a client's name."""
    source = _Cur([[_property()]])
    target = _target([{"id": "tgt-cl", "name": "Acme"}], [], [])  # no accounts at all
    movable, problems = plan(source, target)
    assert movable == []
    assert any("does not exist in the target" in p for p in problems)
    assert any("credential is NOT copied" in p for p in problems)


def test_a_placement_already_in_the_target_is_skipped() -> None:
    """Idempotent: the command is re-run after fixing a mapping, and must not duplicate
    a live URL into the ledger twice."""
    source = _Cur([[_property()]])
    target = _target(
        [{"id": "tgt-cl", "name": "Acme"}],
        [{"id": "tgt-acct", "platform": "dev.to", "client_name": "Acme"}],
        [{"u": "https://dev.to/acme/a-topic", "client_name": "Acme",
          "platform": "dev.to", "topic": "a topic"}],
    )
    movable, problems = plan(source, target)
    assert movable == []
    assert problems == []
