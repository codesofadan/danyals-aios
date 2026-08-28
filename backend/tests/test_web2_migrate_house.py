"""The legacy-vault reconciliation's grouping decision (R2-07).

One property carries this file: **sharing is detected from the DECRYPTED secret, not
from the row.** The retired seeder expressed "these clients share a login" as "these
clients each have a row", so the only way to recover the truth is to compare plaintexts.
Getting this wrong in either direction is a real harm:

* a shared login misread as per-client leaves the correlation in place while the
  dashboard reports it as safely isolated - the original defect, now with a green tick;
* a per-client login misread as shared freezes a client's own property for no reason.

``build_plan`` is pure (no DB, no vault), so the decision is tested directly.
"""

from __future__ import annotations

import pytest

from app.cli.web2_migrate_house import (
    OWNERSHIP_HOUSE,
    OWNERSHIP_PER_CLIENT,
    LegacyRow,
    build_plan,
    fingerprint,
)

pytestmark = pytest.mark.unit

_HOUSE_SECRET = '{"api_key": "one-shared-house-key"}'


def _row(client: str, platform: str = "dev.to", secret: str = _HOUSE_SECRET) -> LegacyRow:
    return LegacyRow(
        vault_id=f"v-{client}-{platform}", platform=platform, client_id=client, secret=secret
    )


def test_one_secret_across_many_clients_becomes_a_single_house_account() -> None:
    plan = build_plan([_row("cl-1"), _row("cl-2"), _row("cl-3")])
    assert len(plan) == 1
    account = plan[0]
    assert account.ownership == OWNERSHIP_HOUSE
    assert account.shared is True
    assert account.client_id is None  # a house account names no client (0100's CHECK)
    assert account.client_ids == ["cl-1", "cl-2", "cl-3"]


def test_a_secret_unique_to_one_client_becomes_a_per_client_account() -> None:
    plan = build_plan([_row("cl-1", secret='{"api_key": "only-mine"}')])
    assert len(plan) == 1
    assert plan[0].ownership == OWNERSHIP_PER_CLIENT
    assert plan[0].shared is False
    assert plan[0].client_id == "cl-1"


def test_shared_and_unique_secrets_on_one_platform_split_correctly() -> None:
    """The realistic state: most clients on the fanned-out house key, one client whose
    credential was later rotated by hand. The rotated one must NOT be dragged into the
    house account."""
    plan = build_plan(
        [_row("cl-1"), _row("cl-2"), _row("cl-9", secret='{"api_key": "rotated-by-hand"}')]
    )
    assert len(plan) == 2
    house = [a for a in plan if a.shared]
    solo = [a for a in plan if not a.shared]
    assert len(house) == 1 and house[0].client_ids == ["cl-1", "cl-2"]
    assert len(solo) == 1 and solo[0].client_id == "cl-9"


def test_two_rows_for_the_same_client_are_still_one_per_client_account() -> None:
    """A re-seed or a rotation leaves two rows for one client. Row COUNT is not the
    test - distinct CLIENT count is - or every rotated credential would be misreported
    as a shared house login."""
    plan = build_plan([_row("cl-1"), _row("cl-1")])
    assert len(plan) == 1
    assert plan[0].ownership == OWNERSHIP_PER_CLIENT
    assert plan[0].client_ids == ["cl-1"]


def test_the_same_secret_on_different_platforms_is_not_one_account() -> None:
    """An identical credential string on two platforms is a coincidence (or a reused
    password), not a single account - grouping is per (platform, secret)."""
    plan = build_plan([_row("cl-1", platform="dev.to"), _row("cl-1", platform="Mataroa")])
    assert len(plan) == 2
    assert {a.platform for a in plan} == {"dev.to", "Mataroa"}


def test_differing_secrets_are_never_grouped() -> None:
    plan = build_plan(
        [_row("cl-1", secret='{"api_key": "a"}'), _row("cl-2", secret='{"api_key": "b"}')]
    )
    assert len(plan) == 2
    assert all(a.ownership == OWNERSHIP_PER_CLIENT for a in plan)


def test_whitespace_differences_are_a_different_secret() -> None:
    """Exact plaintext equality is the rule. Two credentials that differ only in
    formatting are different bytes and are treated as different logins - this is the
    conservative direction (it never claims isolation that is not there)."""
    a = fingerprint('{"api_key": "x"}')
    b = fingerprint('{"api_key":"x"}')
    assert a != b


def test_a_house_handle_names_the_platform_and_a_per_client_handle_is_a_placeholder() -> None:
    """The per-client handle is deliberately a placeholder the operator must correct:
    the real handle already exists on the platform and cannot be inferred, and writing
    a guess would put a false fact in the registry."""
    house = build_plan([_row("cl-1"), _row("cl-2")])[0]
    solo = build_plan([_row("cl-1", secret='{"api_key": "solo"}')])[0]
    assert house.handle == "aios-house-dev-to"
    assert solo.handle.startswith("legacy-dev-to-")


def test_an_empty_input_plans_nothing() -> None:
    assert build_plan([]) == []
