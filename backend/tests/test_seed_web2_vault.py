"""Unit gate for the house-account Web2 vault seeder (``app.cli.seed_web2_vault``).

Covers the pure planning/executing core with injected fakes — no DB, no vault, no
encryption. What is pinned here is the CONTRACT the publish pipeline depends on:
the provider string is exactly ``web2:<Platform>``, the sealed payload is the JSON
``build_publisher`` parses back, existing rows are never touched (idempotency), an
unknown platform never becomes a dead vault row, and an incomplete credential is
seeded-but-flagged (it degrades to hold-at-review downstream, same as absent).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.cli.seed_web2_vault import (
    ACTION_SEED,
    ACTION_SKIP_EXISTS,
    ACTION_SKIP_UNKNOWN,
    build_plan,
    execute_plan,
)
from integrations.web2_publishers import PLATFORM_DEVTO, PLATFORM_MASTODON

pytestmark = pytest.mark.unit

_CLIENTS = [("c-1", "Acme Dental"), ("c-2", "Bright Roofing")]
_HOUSE = {
    PLATFORM_DEVTO: {"api_key": "devto-key"},
    PLATFORM_MASTODON: {"access_token": "tok", "instance_url": "https://mastodon.social"},
}


def test_plan_seeds_every_client_x_platform_with_the_vault_provider_convention() -> None:
    plan = build_plan(_CLIENTS, _HOUSE, lambda provider, label: False)
    assert len(plan) == 4
    assert all(e.action == ACTION_SEED for e in plan)
    assert {e.provider for e in plan} == {"web2:dev.to", "web2:Mastodon"}
    assert {e.client_id for e in plan} == {"c-1", "c-2"}
    assert all(e.missing == () for e in plan)


def test_plan_skips_existing_rows_idempotently() -> None:
    def exists(provider: str, label: str) -> bool:
        return label == "c-1"  # client 1 already fully seeded

    plan = build_plan(_CLIENTS, _HOUSE, exists)
    by_client = {e.client_id: {p.action for p in plan if p.client_id == e.client_id} for e in plan}
    assert by_client["c-1"] == {ACTION_SKIP_EXISTS}
    assert by_client["c-2"] == {ACTION_SEED}


def test_plan_skips_an_unknown_platform_instead_of_writing_a_dead_row() -> None:
    plan = build_plan(_CLIENTS[:1], {"NotARealPlatform": {"token": "x"}}, lambda p, lbl: False)
    assert [e.action for e in plan] == [ACTION_SKIP_UNKNOWN]


def test_plan_flags_missing_required_fields_but_still_seeds() -> None:
    incomplete = {PLATFORM_MASTODON: {"access_token": "tok"}}  # no instance_url
    plan = build_plan(_CLIENTS[:1], incomplete, lambda p, lbl: False)
    assert plan[0].action == ACTION_SEED
    assert plan[0].missing == ("instance_url",)


def test_execute_writes_only_seed_entries_as_client_access_json() -> None:
    written: list[dict[str, Any]] = []

    def add(**kwargs: Any) -> None:
        written.append(kwargs)

    plan = build_plan(_CLIENTS, _HOUSE, lambda provider, label: label == "c-1")
    count = execute_plan(plan, _HOUSE, add)
    assert count == len(written) == 2  # only c-2's two platforms
    assert {w["label"] for w in written} == {"c-2"}
    assert all(w["kind"] == "client_access" for w in written)
    mastodon = next(w for w in written if w["provider"] == "web2:Mastodon")
    assert json.loads(mastodon["secret"]) == _HOUSE[PLATFORM_MASTODON]
