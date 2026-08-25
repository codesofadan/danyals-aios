"""P2-2 gate: the RBAC model is well formed and enforces correctly.

**These tests never open ``frontend/lib/data.ts``, and no longer claim to.** They
assert the model's SHAPE and its enforcement semantics - six roles, eight unique
permissions, eleven grouped features, owner hard-locked all-on, client outside the
matrix, access levels ordered - by comparing Python against Python.

Two of them used to be called ``..._match_frontend`` and the docstring above used to
say they "pin the reference data to ``frontend/lib/data.ts``". That was not true: the
expected values were re-typed here as Python literals, so this file was a THIRD
hand-written copy of the access matrix rather than a reconciliation of the other two.
It could not have failed on any frontend drift, and on 2026-08-24 fourteen fields had
drifted while every test here stayed green.

The cross-file comparison it implied is now real, and lives in
``test_rbac_single_source.py``. What remains here is what this file can honestly do.
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
def test_features_are_unique_and_grouped() -> None:
    """17 since the six SEO tools were made reachable (2026-08-25); 11 before that.

    The count stays an explicit literal so an ACCIDENTAL addition still trips a test.
    It is not the real guard, though - `test_rbac_single_source.py` parses the
    dashboard's own copy and compares it field by field, which is what catches a
    feature added on one side only.
    """
    assert len(m.FEATURES) == 17
    assert len(set(m.FEATURE_KEYS)) == 17, "a duplicate key would silently shadow a tool"
    assert {f.group for f in m.FEATURES} == {"Analytics", "Content", "Delivery", "Admin"}


@pytest.mark.unit
def test_default_role_perms_are_the_documented_grants() -> None:
    # The eight governance permissions each role holds by default. Compared against
    # the dashboard's copy in test_rbac_single_source.py, not here.
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
def test_templates_are_well_formed_and_super_is_all_features() -> None:
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


# --------------------------------------------------------------------------- #
# Correctness anchors, as distinct from consistency.
#
# `test_rbac_single_source.py` proves the backend and the dashboard hold the SAME
# access matrix. It cannot prove they hold the RIGHT one: a coordinated edit to both
# copies passes it, by construction. Verified 2026-08-24 by granting the Content
# Creator template `key_vault` in matrix.py AND data.ts simultaneously - 47 tests
# passed, including the single-source gate. A consistency gate is not a correctness
# gate, and the templates were anchored to nothing independent.
#
# These anchor the security-relevant shape of the matrix to a stated rule instead.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_only_the_super_template_grants_an_admin_group_feature() -> None:
    """The Admin group is the sensitive one, and only Super Admin may template it in.

    `key_vault`'s own description reads "API keys & integrations - Super Admin only".
    Without this, a template could be handed the key vault by an edit to two files
    that agree with each other, and every existing test would stay green.
    """
    admin_features = {f.key for f in m.FEATURES if f.group == "Admin"}
    assert admin_features == {"key_vault", "billing", "team_access"}, (
        "the Admin feature group changed; confirm the new membership is intended "
        "before widening this anchor"
    )
    for t in m.TEMPLATES:
        granted = set(t.grants) & admin_features
        if t.key == "super":
            assert granted == admin_features, "Super Admin must template in every Admin feature"
        else:
            assert not granted, (
                f"template {t.key!r} grants Admin-group feature(s) {sorted(granted)}. "
                "Only 'super' may. If this is deliberate, it is a product decision that "
                "needs a written record, not a test edit."
            )


@pytest.mark.unit
def test_no_template_out_grants_the_governance_role_it_stamps() -> None:
    """A template must not hand a member a feature their stamped role cannot support.

    `super` stamps `owner` (all-on and locked). Every other template stamps a role that
    holds neither `access_control` nor `manage_vault`, so no such template may grant the
    features those permissions gate.
    """
    gated = {"key_vault": "manage_vault", "team_access": "access_control"}
    for t in m.TEMPLATES:
        for feature, perm in gated.items():
            if feature in t.grants:
                assert m.role_has_perm(t.role, perm), (  # type: ignore[arg-type]
                    f"template {t.key!r} stamps role {t.role!r} and grants {feature!r}, "
                    f"but {t.role!r} does not hold {perm!r} - the grant could never be exercised"
                )
