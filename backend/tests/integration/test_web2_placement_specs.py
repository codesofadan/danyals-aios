"""0136's invariants (web2_placement_specs), against real Postgres.

Same reasoning as test_citation_invariants.py: `service_role` is BYPASSRLS, so the
only rules that bind everyone are the ones the DATABASE enforces - CHECKs and
triggers. Each refusal carries its negative control (the write that must still
succeed), because a constraint that rejects everything is also "green".

Every test runs inside a transaction that is rolled back - the catalogue is untouched.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.integration

_DSN_KEYS = ("DATABASE_MIGRATE_URL", "DATABASE_ADMIN_URL", "DATABASE_URL")


@pytest.fixture
def cur() -> Any:
    """A cursor inside a transaction that is ALWAYS rolled back."""
    dsn = next((os.environ[k] for k in _DSN_KEYS if os.environ.get(k)), None)
    if not dsn:
        pytest.skip(f"no Postgres configured (set one of {', '.join(_DSN_KEYS)})")
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.cursor() as c:
            c.execute("select to_regclass('public.web2_placement_specs') as t")
            if c.fetchone()["t"] is None:
                pytest.skip("0136 not applied")
            yield c
        conn.rollback()


def _refuses(cur: Any, sql: str, *args: Any) -> str:
    """Run a write that must fail; return the error text (savepoint-isolated)."""
    import psycopg

    cur.execute("savepoint probe")
    try:
        cur.execute(sql, args)
    except psycopg.Error as exc:
        cur.execute("rollback to savepoint probe")
        return str(exc)
    cur.execute("rollback to savepoint probe")
    pytest.fail(f"write was ACCEPTED but should have been refused: {sql[:120]}")


def _platform(cur: Any, homepage: str = "https://example-place.com") -> str:
    cur.execute(
        "insert into public.web2_platforms (name, homepage_url) "
        "values (%s, %s) returning id",
        (f"SpecProbe {uuid.uuid4().hex[:10]}", homepage),
    )
    return str(cur.fetchone()["id"])


def _spec_json(editor_url: str = "https://example-place.com/editor/new") -> str:
    return json.dumps({
        "editor_url": editor_url,
        "copy_blocks": [{"key": "title", "label": "Title"}, {"key": "body", "label": "Body"}],
    })


def _insert_spec(cur: Any, platform_id: str, **cols: Any) -> str:
    fixed = {"platform_id": platform_id, "spec": _spec_json()}
    fixed.update(cols)
    names = ", ".join(fixed)
    marks = ", ".join(["%s"] * len(fixed))
    cur.execute(
        f"insert into public.web2_placement_specs ({names}) values ({marks}) returning id",
        list(fixed.values()),
    )
    return str(cur.fetchone()["id"])


def _earn(cur: Any, spec_id: str) -> None:
    cur.execute(
        "update public.web2_placement_specs set "
        "  verified_at = now(), "
        "  first_live_url = 'https://example-place.com/@op/post-1', "
        "  first_live_at = now() "
        "where id = %s",
        (spec_id,),
    )


# --------------------------------------------------------------------------- #
# 1. active is EARNED.
# --------------------------------------------------------------------------- #
def test_active_is_impossible_without_both_halves_of_the_contract(cur: Any) -> None:
    pid = _platform(cur)
    err = _refuses(
        cur,
        "insert into public.web2_placement_specs (platform_id, spec, active) "
        "values (%s, %s, true)",
        pid, _spec_json(),
    )
    assert "active_is_earned" in err

    # Negative control: the honest path works - insert inactive, earn, activate.
    spec_id = _insert_spec(cur, pid)
    _earn(cur, spec_id)
    cur.execute(
        "update public.web2_placement_specs set active = true where id = %s returning active",
        (spec_id,),
    )
    assert cur.fetchone()["active"] is True


def test_a_first_live_url_without_a_date_is_refused_and_vice_versa(cur: Any) -> None:
    pid = _platform(cur)
    err = _refuses(
        cur,
        "insert into public.web2_placement_specs (platform_id, spec, first_live_url) "
        "values (%s, %s, 'https://example-place.com/p/1')",
        pid, _spec_json(),
    )
    assert "first_live_pairing" in err
    err = _refuses(
        cur,
        "insert into public.web2_placement_specs (platform_id, spec, first_live_at) "
        "values (%s, %s, now())",
        pid, _spec_json(),
    )
    assert "first_live_pairing" in err


# --------------------------------------------------------------------------- #
# 2. immutability - a revision is a NEW ROW.
# --------------------------------------------------------------------------- #
def test_the_spec_jsonb_is_immutable_after_insert(cur: Any) -> None:
    pid = _platform(cur)
    spec_id = _insert_spec(cur, pid)
    err = _refuses(
        cur,
        "update public.web2_placement_specs set spec = %s where id = %s",
        _spec_json("https://example-place.com/editor/v2"), spec_id,
    )
    assert "immutable" in err

    # Negative control: non-spec columns still update.
    cur.execute(
        "update public.web2_placement_specs set failure_count = failure_count + 1 "
        "where id = %s returning failure_count",
        (spec_id,),
    )
    assert cur.fetchone()["failure_count"] == 1


def test_the_platform_binding_cannot_be_moved(cur: Any) -> None:
    pid = _platform(cur)
    other = _platform(cur, homepage="https://other-place.com")
    spec_id = _insert_spec(cur, pid)
    err = _refuses(
        cur,
        "update public.web2_placement_specs set platform_id = %s where id = %s",
        other, spec_id,
    )
    assert "immutable" in err


def test_a_recorded_verification_is_write_once(cur: Any) -> None:
    pid = _platform(cur)
    spec_id = _insert_spec(cur, pid)
    _earn(cur, spec_id)
    err = _refuses(
        cur,
        "update public.web2_placement_specs set verified_at = now() - interval '1 day' "
        "where id = %s",
        spec_id,
    )
    assert "cannot be rewritten" in err
    err = _refuses(
        cur,
        "update public.web2_placement_specs set verified_evidence = '{\"laundered\": true}' "
        "where id = %s",
        spec_id,
    )
    assert "fixed once it is recorded" in err
    err = _refuses(
        cur,
        "update public.web2_placement_specs set "
        "first_live_url = 'https://example-place.com/p/other' where id = %s",
        spec_id,
    )
    assert "cannot be rewritten" in err


# --------------------------------------------------------------------------- #
# 3. host pinning (insert + activation; 0114 semantics).
# --------------------------------------------------------------------------- #
def test_the_editor_url_is_pinned_to_the_platform_host(cur: Any) -> None:
    pid = _platform(cur)
    err = _refuses(
        cur,
        "insert into public.web2_placement_specs (platform_id, spec) values (%s, %s)",
        pid, _spec_json("https://evil.example/editor"),
    )
    assert "must belong to the platform host" in err

    # Dot-anchored: a genuine subdomain passes, a suffix-lookalike does not.
    _insert_spec(cur, pid, spec=_spec_json("https://write.example-place.com/new"))
    err = _refuses(
        cur,
        "insert into public.web2_placement_specs (platform_id, spec) values (%s, %s)",
        pid, _spec_json("https://evil-example-place.com/editor"),
    )
    assert "must belong to the platform host" in err


def test_ambiguous_and_ip_literal_editor_urls_are_refused_outright(cur: Any) -> None:
    pid = _platform(cur)
    err = _refuses(
        cur,
        "insert into public.web2_placement_specs (platform_id, spec) values (%s, %s)",
        pid, _spec_json("https://evil.com\\@example-place.com/editor"),
    )
    assert "plain absolute http(s) URL" in err
    err = _refuses(
        cur,
        "insert into public.web2_placement_specs (platform_id, spec) values (%s, %s)",
        pid, _spec_json("https://169.254.169.254/latest"),
    )
    assert "IP literal" in err


def test_a_platform_with_no_homepage_cannot_earn_a_spec(cur: Any) -> None:
    pid = _platform(cur, homepage="")
    err = _refuses(
        cur,
        "insert into public.web2_placement_specs (platform_id, spec) values (%s, %s)",
        pid, _spec_json(),
    )
    assert "no usable homepage_url" in err


def test_the_spec_shape_check_requires_editor_url_and_copy_blocks(cur: Any) -> None:
    pid = _platform(cur)
    err = _refuses(
        cur,
        "insert into public.web2_placement_specs (platform_id, spec) values (%s, %s)",
        pid, json.dumps({"editor_url": "https://example-place.com/e"}),
    )
    assert "spec_is_an_object" in err
    err = _refuses(
        cur,
        "insert into public.web2_placement_specs (platform_id, spec) values (%s, %s)",
        pid, json.dumps({
            "editor_url": "https://example-place.com/e",
            "copy_blocks": [], "fields": "not-a-list",
        }),
    )
    assert "spec_is_an_object" in err


# --------------------------------------------------------------------------- #
# 4. one ACTIVE spec per platform; history accumulates.
# --------------------------------------------------------------------------- #
def test_one_active_per_platform_but_revisions_accumulate(cur: Any) -> None:
    pid = _platform(cur)
    first = _insert_spec(cur, pid)
    _earn(cur, first)
    cur.execute(
        "update public.web2_placement_specs set active = true where id = %s", (first,)
    )
    second = _insert_spec(cur, pid)  # a second INACTIVE revision is history, fine
    _earn(cur, second)
    err = _refuses(
        cur,
        "update public.web2_placement_specs set active = true where id = %s",
        second,
    )
    assert "one_active_per_platform" in err


# --------------------------------------------------------------------------- #
# 5. the catalogue-url-change voider + activation-time re-validation.
# --------------------------------------------------------------------------- #
def test_a_homepage_change_voids_the_earned_state(cur: Any) -> None:
    pid = _platform(cur)
    spec_id = _insert_spec(cur, pid)
    _earn(cur, spec_id)
    cur.execute(
        "update public.web2_placement_specs set active = true where id = %s", (spec_id,)
    )
    cur.execute(
        "update public.web2_platforms set homepage_url = 'https://moved-elsewhere.com' "
        "where id = %s",
        (pid,),
    )
    cur.execute(
        "select active, deactivated_reason from public.web2_placement_specs where id = %s",
        (spec_id,),
    )
    row = cur.fetchone()
    assert row["active"] is False
    assert row["deactivated_reason"] == "platform_url_changed"

    # And the stale binding cannot be RE-ARMED with a plain `set active = true`:
    # activation re-validates the (immutable) spec host against the NEW homepage.
    err = _refuses(
        cur,
        "update public.web2_placement_specs set active = true where id = %s",
        spec_id,
    )
    assert "must belong to the platform host" in err


def test_drift_and_active_cannot_coexist(cur: Any) -> None:
    pid = _platform(cur)
    spec_id = _insert_spec(cur, pid)
    _earn(cur, spec_id)
    cur.execute(
        "update public.web2_placement_specs set active = true where id = %s", (spec_id,)
    )
    err = _refuses(
        cur,
        "update public.web2_placement_specs set drift_detected_at = now() where id = %s",
        spec_id,
    )
    assert "drift_deactivates" in err
    # The honest write: drift + deactivation together (what record_placement_spec_drift does).
    cur.execute(
        "update public.web2_placement_specs set "
        "  active = false, deactivated_reason = 'drift_detected', "
        "  drift_detected_at = now(), drift_selector = 'input[name=title]' "
        "where id = %s returning active",
        (spec_id,),
    )
    assert cur.fetchone()["active"] is False


def test_the_deactivated_reason_vocabulary_is_closed(cur: Any) -> None:
    pid = _platform(cur)
    err = _refuses(
        cur,
        "insert into public.web2_placement_specs (platform_id, spec, deactivated_reason) "
        "values (%s, %s, 'because_reasons')",
        pid, _spec_json(),
    )
    assert "deactivated_reason_known" in err


# --------------------------------------------------------------------------- #
# 6. RLS shape.
# --------------------------------------------------------------------------- #
def test_rls_is_enabled_and_forced_with_the_standard_policies(cur: Any) -> None:
    cur.execute(
        "select relrowsecurity, relforcerowsecurity from pg_class "
        "where oid = 'public.web2_placement_specs'::regclass"
    )
    row = cur.fetchone()
    assert row["relrowsecurity"] is True and row["relforcerowsecurity"] is True
    cur.execute(
        "select polname, polcmd from pg_policy "
        "where polrelid = 'public.web2_placement_specs'::regclass order by polname"
    )
    cmds = {r["polname"]: r["polcmd"] for r in cur.fetchall()}
    assert cmds == {
        "web2_placement_specs_select": "r",
        "web2_placement_specs_insert": "a",
        "web2_placement_specs_update": "w",
    }  # and deliberately NO delete policy - history is append-only under FORCE RLS
