"""P2-2 gate: the RBAC matrix mirrors the frontend and enforces correctly.

These assertions pin the reference data to ``frontend/lib/data.ts`` - if the
product model changes, both must change together.
"""

from __future__ import annotations

import pytest

from app.rbac import matrix as m


@pytest.mark.unit
def test_six_roles_in_priority_order() -> None:
    assert m.ROLE_ORDER == ("owner", "admin", "manager", "specialist", "analyst", "viewer")
    assert {rm.role for rm in m.ROLE_META} == set(m.ROLE_ORDER)


@pytest.mark.unit
def test_eight_permissions_unique() -> None:
    keys = [p.key for p in m.PERMISSIONS]
    assert len(keys) == 8
    assert set(keys) == set(m.PERM_KEYS)
    assert len(set(keys)) == len(keys)


@pytest.mark.unit
def test_seventeen_features_unique_and_grouped() -> None:
    assert len(m.FEATURES) == 17
    assert len(set(m.FEATURE_KEYS)) == 17
    assert {f.group for f in m.FEATURES} == {"Analytics", "Content", "Delivery", "Admin"}


@pytest.mark.unit
def test_default_role_perms_match_frontend() -> None:
    # Verbatim from frontend defaultRolePerms.
    assert m.DEFAULT_ROLE_PERMS["owner"] == frozenset(m.PERM_KEYS)
    assert m.DEFAULT_ROLE_PERMS["admin"] == frozenset(
        {"run_audits", "publish_content", "manage_clients", "assign_tasks", "manage_team", "manage_vault", "view_reports"}
    )
    assert m.DEFAULT_ROLE_PERMS["manager"] == frozenset(
        {"run_audits", "publish_content", "manage_clients", "assign_tasks", "view_reports"}
    )
    assert m.DEFAULT_ROLE_PERMS["specialist"] == frozenset({"run_audits", "publish_content", "view_reports"})
    assert m.DEFAULT_ROLE_PERMS["analyst"] == frozenset({"run_audits", "view_reports"})
    assert m.DEFAULT_ROLE_PERMS["viewer"] == frozenset({"view_reports"})


@pytest.mark.unit
def test_admin_lacks_access_control_but_owner_is_all_on() -> None:
    assert "access_control" not in m.DEFAULT_ROLE_PERMS["admin"]
    # Owner is hard-locked to all-on even if someone edited the map.
    assert m.role_has_perm("owner", "access_control")
    assert not m.role_has_perm("admin", "access_control")
    assert m.perms_for_role("owner") == frozenset(m.PERM_KEYS)


@pytest.mark.unit
def test_role_has_perm_examples() -> None:
    assert m.role_has_perm("viewer", "view_reports")
    assert not m.role_has_perm("viewer", "manage_vault")
    assert m.role_has_perm("manager", "manage_clients")
    assert not m.role_has_perm("manager", "manage_team")
    # perms_for_role must return the ROLE'S own set, not owner's, for a non-owner
    # (kills the `role == "owner"` -> `!=` mutant, which else returns all perms).
    assert m.perms_for_role("viewer") == frozenset({"view_reports"})
    assert m.perms_for_role("manager") == m.DEFAULT_ROLE_PERMS["manager"]


@pytest.mark.unit
def test_client_role_is_outside_the_governance_matrix() -> None:
    """SECURITY invariant: a portal client is NOT staff and holds NO permission.

    (Added to kill mutation survivors: flipping ``is_staff_role``'s ``!=``, the
    ``role == "client"`` early-returns, or the ``return False`` in
    ``role_has_perm`` previously left every test green.)
    """
    assert m.is_staff_role("client") is False
    assert m.is_staff_role("owner") is True
    assert m.is_staff_role("viewer") is True
    assert m.perms_for_role("client") == frozenset()
    for perm in m.PERM_KEYS:
        assert m.role_has_perm("client", perm) is False
    # A client never has grants, so no feature is allowed and every level is off.
    for feat in m.FEATURE_KEYS:
        assert m.effective_feature_level("client", {}, feat) == "off"
        assert not m.feature_allows("client", {}, feat)


@pytest.mark.unit
def test_templates_match_frontend_and_super_is_all_features() -> None:
    by_key = {t.key: t for t in m.TEMPLATES}
    assert set(by_key) == {"seo", "content", "va", "super"}
    assert set(by_key["super"].grants) == set(m.FEATURE_KEYS)
    assert by_key["super"].role == "owner"
    assert by_key["va"].role == "manager"
    assert by_key["seo"].role == "specialist"
    # every granted feature key is a real feature
    for t in m.TEMPLATES:
        assert set(t.grants) <= set(m.FEATURE_KEYS)


@pytest.mark.unit
def test_level_satisfies_ordering() -> None:
    assert m.level_satisfies("full", "view")
    assert m.level_satisfies("full", "full")
    assert m.level_satisfies("view", "view")
    assert not m.level_satisfies("view", "full")
    assert not m.level_satisfies("off", "view")


@pytest.mark.unit
def test_feature_allows_owner_is_all_on() -> None:
    assert m.feature_allows("owner", {}, "billing")
    assert m.feature_allows("owner", {}, "key_vault", "full")


@pytest.mark.unit
def test_feature_allows_uses_overrides_else_off() -> None:
    # No override -> off -> denied.
    assert not m.feature_allows("specialist", {}, "technical_audit")
    # View override does not satisfy a full requirement.
    assert m.feature_allows("specialist", {"technical_audit": "view"}, "technical_audit", "view")
    assert not m.feature_allows("specialist", {"technical_audit": "view"}, "technical_audit", "full")
    assert m.feature_allows("specialist", {"technical_audit": "full"}, "technical_audit", "full")


@pytest.mark.unit
def test_effective_feature_level() -> None:
    assert m.effective_feature_level("owner", {}, "anything") == "full"
    assert m.effective_feature_level("viewer", {}, "billing") == "off"
    assert m.effective_feature_level("viewer", {"billing": "view"}, "billing") == "view"
