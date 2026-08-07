"""Fire-on-publish: a JUST-PUBLISHED content page's live URL is enqueued for indexing.

NO broker: ``submit_urls_for_indexing.delay`` is monkeypatched to a recorder, so this
proves ``_fire_indexing_best_effort`` (called from the publish TASK entry point) only
fires on a live-URL publish, links the client, and never raises.
"""

from __future__ import annotations

from typing import Any

import pytest

from workers.tasks.content import PublishOutcome, _fire_indexing_best_effort

pytestmark = pytest.mark.unit


class FakeStore:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def load(self, code: str) -> dict[str, Any] | None:
        return self._row

    def update(self, code: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        return None


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []
    from app.modules.indexing import tasks as t

    monkeypatch.setattr(
        t.submit_urls_for_indexing, "delay", lambda *a, **k: calls.append((a, k))
    )
    return calls


def test_published_url_is_enqueued_with_client(enqueued: list[tuple[Any, ...]]) -> None:
    store = FakeStore({"client_id": "cl-9"})
    outcome = PublishOutcome("C-1", "done", "published", url="https://acme.example/a")
    _fire_indexing_best_effort(store, outcome)  # type: ignore[arg-type]
    assert enqueued == [(( ["https://acme.example/a"], None, "cl-9"), {})]


def test_degraded_artifact_publish_has_no_url_so_nothing_fires(
    enqueued: list[tuple[Any, ...]],
) -> None:
    store = FakeStore({"client_id": "cl-9"})
    # A degraded/artifact publish carries no live URL.
    outcome = PublishOutcome("C-2", "done", "degraded", url="")
    _fire_indexing_best_effort(store, outcome)  # type: ignore[arg-type]
    assert enqueued == []


def test_blocked_or_failed_publish_does_not_fire(enqueued: list[tuple[Any, ...]]) -> None:
    store = FakeStore({"client_id": "cl-9"})
    _fire_indexing_best_effort(store, PublishOutcome("C-3", "publishing", "noop", url=""))  # type: ignore[arg-type]
    _fire_indexing_best_effort(store, PublishOutcome("C-4", "failed", "failed", url=""))  # type: ignore[arg-type]
    assert enqueued == []


def test_no_client_row_still_fires_without_client(enqueued: list[tuple[Any, ...]]) -> None:
    store = FakeStore(None)  # row gone -> client_id None, url still indexed
    outcome = PublishOutcome("C-5", "done", "published", url="https://acme.example/x")
    _fire_indexing_best_effort(store, outcome)  # type: ignore[arg-type]
    assert enqueued == [(( ["https://acme.example/x"], None, None), {})]
