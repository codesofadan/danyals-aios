"""0115's five invariants, against real Postgres.

THESE RUN AGAINST A LIVE DATABASE ON PURPOSE. Every rule here was Python's word before
0115, and `service_role` is BYPASSRLS - so the only question worth asking is whether the
DATABASE refuses the write, which a fake store cannot answer and a Python mirror of the
predicate answers only about itself.

Each test also carries its NEGATIVE CONTROL - the write that must still succeed. Writing
only the refusals would let a constraint that rejects everything pass as correct, and two
of the hand-run probes for this migration were initially green for exactly the wrong
reason: a scopes payload refused by `expires_at NOT NULL` before the scopes CHECK could
fire, and three malformed specs refused by 0108's URL-host guard because the fixture used
a URL on the wrong host. Both are pinned below with the host/expiry made valid so the
constraint under test is the one that speaks.

Every test runs inside a transaction that is rolled back, so the catalogue is untouched.
"""

from __future__ import annotations

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
            c.execute("select to_regclass('public.directory_specs') as t")
            if c.fetchone()["t"] is None:
                pytest.skip("citation schema not applied (migrations 0106-0115)")
            yield c
        conn.rollback()


def _one(cur: Any, sql: str, *args: Any) -> Any:
    cur.execute(sql, args)
    row = cur.fetchone()
    return None if row is None else next(iter(row.values()))


def _refuses(cur: Any, sql: str, *args: Any) -> str:
    """Run a write that must fail; return the error text. Fails the test if it succeeds.

    The savepoint is what lets one test make several refused writes: in Postgres the
    first error aborts the transaction, and every later statement would then fail with
    "current transaction is aborted" - which would look like a refusal and prove nothing.
    """
    import psycopg

    cur.execute("savepoint probe")
    try:
        cur.execute(sql, args)
    except psycopg.Error as exc:
        cur.execute("rollback to savepoint probe")
        return str(exc)
    cur.execute("rollback to savepoint probe")
    pytest.fail(f"write was ACCEPTED but should have been refused: {sql[:120]}")


# --------------------------------------------------------------------------- #
# 1. One vocabulary for submit_method.
# --------------------------------------------------------------------------- #
def test_no_directory_carries_an_undispatchable_submit_method(cur: Any) -> None:
    """Every active, non-F row routes to an engine or says why it does not.

    Before 0115 there were two names for one concept - `bot:playwright` (127 rows) and a
    bare `playwright` (70 rows) - and `submitter_for` dispatches on the prefix, so the
    bare ones fell through to "no automatable engine". Invisible while the earned
    whitelist is empty, because every bot row blocks anyway; live the day a spec is
    earned.
    """
    stranded = _one(
        cur,
        """
        select count(*) from public.directories
         where active and route <> 'F'
           and submit_method not like 'api:%%'
           and submit_method not like 'bot:%%'
           and submit_method not like 'aggregator:%%'
           and submit_method not in ('manual', 'closed', '')
        """,
    )
    assert stranded == 0, f"{stranded} directories carry a submit_method nothing dispatches"


def test_an_unknown_submit_method_cannot_be_stored(cur: Any) -> None:
    did = _one(cur, "select id from public.directories limit 1")
    err = _refuses(
        cur, "update public.directories set submit_method = 'selenium' where id = %s", did
    )
    assert "directories_submit_method_dispatchable" in err

    # Negative control: a real one still updates.
    cur.execute(
        "update public.directories set submit_method = 'bot:playwright' where id = %s", (did,)
    )
    assert cur.rowcount == 1


# --------------------------------------------------------------------------- #
# 2. A route-F directory cannot be queued.
# --------------------------------------------------------------------------- #
def _route_dir(cur: Any, route: str) -> str:
    d = _one(cur, "select id from public.directories where route = %s limit 1", route)
    if d is None:
        pytest.skip(f"no route-{route} directory in the catalogue")
    return str(d)


@pytest.mark.parametrize("status", ["queued", "submitting", "ready_for_human"])
def test_route_f_cannot_enter_an_acting_status(cur: Any, status: str) -> None:
    """Route F is the hand-verified 'terms prohibit automated access' set. `is_prohibited`
    blocks it in the planner, but the one rule here with a legal consequence should not
    depend on every future caller remembering to ask."""
    fdir = _route_dir(cur, "F")
    err = _refuses(
        cur,
        "insert into public.citations (directory, directory_id, submit_status) "
        "values ('probe-f', %s, %s)",
        fdir,
        status,
    )
    assert "route F" in err


def test_route_f_may_still_exist_as_not_started(cur: Any) -> None:
    """The row must be creatable, or the client report cannot say 'not attempted - terms
    prohibit automated submission'. Silence would be the worse answer."""
    fdir = _route_dir(cur, "F")
    cur.execute(
        "insert into public.citations (directory, directory_id, submit_status) "
        "values ('probe-f-ok', %s, 'not_started') returning id",
        (fdir,),
    )
    assert cur.fetchone()["id"] is not None


def test_route_f_cannot_be_promoted_by_update(cur: Any) -> None:
    """The insert guard alone would be bypassable: create it parked, then move it."""
    fdir = _route_dir(cur, "F")
    cid = _one(
        cur,
        "insert into public.citations (directory, directory_id, submit_status) "
        "values ('probe-f-promote', %s, 'not_started') returning id",
        fdir,
    )
    err = _refuses(
        cur, "update public.citations set submit_status = 'queued' where id = %s", cid
    )
    assert "route F" in err


def test_a_route_c_citation_still_queues(cur: Any) -> None:
    """The negative control. A guard that refused every queue would also pass the tests
    above, and would take the whole product down."""
    cdir = _route_dir(cur, "C")
    cur.execute(
        "insert into public.citations (directory, directory_id, submit_status) "
        "values ('probe-c', %s, 'queued') returning id",
        (cdir,),
    )
    assert cur.fetchone()["id"] is not None


# --------------------------------------------------------------------------- #
# 3. The scope vocabulary is closed IN THE DATABASE.
# --------------------------------------------------------------------------- #
def _a_user(cur: Any) -> str:
    u = _one(cur, "select id from public.users limit 1")
    if u is None:
        pytest.skip("no users")
    return str(u)


_TOKEN_INSERT = (
    "insert into public.operator_tokens "
    "  (user_id, token_prefix, token_hash, scopes, expires_at) "
    "values (%s, %s, 'h', %s::jsonb, now() + interval '1 hour')"
)


@pytest.mark.parametrize(
    "scopes",
    [
        '["vault"]',
        '["admin"]',
        '["citation_queue", "admin"]',  # one good scope does not launder a bad one
        '["clients:write"]',
    ],
)
def test_a_scope_outside_the_vocabulary_cannot_be_stored(cur: Any, scopes: str) -> None:
    """`operator_tokens`' header calls containment 'structural, not a matter of which
    routes remember to check'. It was `cap_scopes` in Python and a bare jsonb column -
    app-tier only, which `service_role` bypasses. Now the sentence is true.

    NOTE the `expires_at`: the first hand-run probe omitted it and was refused by the
    NOT NULL constraint, which proved nothing about scopes.
    """
    err = _refuses(cur, _TOKEN_INSERT, _a_user(cur), uuid.uuid4().hex[:8], scopes)
    assert "operator_tokens_scopes_closed" in err


def test_the_real_vocabulary_is_accepted(cur: Any) -> None:
    cur.execute(
        _TOKEN_INSERT + " returning id",
        (_a_user(cur), uuid.uuid4().hex[:8], '["citation_queue", "citation_credential"]'),
    )
    assert cur.fetchone()["id"] is not None


def test_scopes_cannot_be_widened_by_update(cur: Any) -> None:
    """A CHECK applies to UPDATE too - pinned, because an insert-only guard is the exact
    hole 0114's first fix opened (a voided spec re-armed with `set active = true`)."""
    tid = _one(
        cur,
        _TOKEN_INSERT + " returning id",
        _a_user(cur),
        uuid.uuid4().hex[:8],
        '["citation_queue"]',
    )
    err = _refuses(
        cur, "update public.operator_tokens set scopes = '[\"vault\"]'::jsonb where id = %s", tid
    )
    assert "operator_tokens_scopes_closed" in err


# --------------------------------------------------------------------------- #
# 4. The spec shape CHECK matches what the loader dereferences.
# --------------------------------------------------------------------------- #
@pytest.fixture
def spec_dir(cur: Any) -> tuple[str, str]:
    """A directory id and a URL ON ITS OWN HOST.

    The host matters: 0108's guard refuses a spec whose host is not the directory's, and
    it fires FIRST. Three hand-run probes for this section were green against `x.com` and
    proved only that the older guard works.
    """
    row = _one(cur, "select id || '|' || url from public.directories where url <> '' limit 1")
    if row is None:
        pytest.skip("no directory with a url")
    did, url = str(row).split("|", 1)
    host = url.replace("https://", "").replace("http://", "").split("/")[0]
    return did, f"https://{host}/add"


_SPEC_INSERT = "insert into public.directory_specs (directory_id, spec) values (%s, %s::jsonb)"


@pytest.mark.parametrize(
    ("label", "fields", "extra"),
    [
        ("empty fields array fills nothing, silently", "[]", ""),
        ("field with no selector -> KeyError in the loader", '[{"value_key": "business_name"}]', ""),
        ("field with no value_key", '[{"selector": "#n"}]', ""),
        ("empty selector string", '[{"selector": "", "value_key": "business_name"}]', ""),
        ("null selector", '[{"selector": null, "value_key": "business_name"}]', ""),
        ("field is not an object", '["#name"]', ""),
    ],
)
def test_a_spec_the_loader_could_not_read_is_refused(
    cur: Any, spec_dir: tuple[str, str], label: str, fields: str, extra: str
) -> None:
    """`form_spec_from_json` says it does not re-validate because 'the DB already enforced
    the shape'. 0108 enforced four of those seven words. The consequence was not a crash -
    the loader catches and logs - it was an EARNED spec silently vanishing, leaving the
    directory reporting 'no verified spec' forever."""
    did, url = spec_dir
    spec = (
        f'{{"url": "{url}", "submit_selector": "#s", '
        f'"success_indicator": "ok", "fields": {fields}}}'
    )
    err = _refuses(cur, _SPEC_INSERT, did, spec)
    assert "directory_specs_spec_is_an_object" in err, label


def test_a_spec_missing_success_indicator_is_refused(cur: Any, spec_dir: tuple[str, str]) -> None:
    did, url = spec_dir
    spec = (
        f'{{"url": "{url}", "submit_selector": "#s", '
        f'"fields": [{{"selector": "#n", "value_key": "business_name"}}]}}'
    )
    err = _refuses(cur, _SPEC_INSERT, did, spec)
    assert "directory_specs_spec_is_an_object" in err


def test_a_well_formed_spec_is_still_accepted(cur: Any, spec_dir: tuple[str, str]) -> None:
    """The negative control that makes the six refusals above mean something."""
    did, url = spec_dir
    spec = (
        f'{{"url": "{url}", "submit_selector": "#s", "success_indicator": "ok", '
        f'"fields": [{{"selector": "#n", "value_key": "business_name"}}]}}'
    )
    cur.execute(_SPEC_INSERT + " returning id", (did, spec))
    assert cur.fetchone()["id"] is not None


# --------------------------------------------------------------------------- #
# 5. The failed-seal rollback actually deletes - and only the unsealed row.
# --------------------------------------------------------------------------- #
@pytest.fixture
def as_operator(cur: Any) -> Any:
    """Run as the `authenticated` role with an identity, exactly as `rls_connection` does.

    Superuser would bypass RLS and this whole section would prove nothing - the defect
    IS a missing policy.
    """
    uid = _one(
        cur,
        "select id from public.users where role in ('owner','admin','manager') "
        "and status <> 'suspended' limit 1",
    )
    if uid is None:
        pytest.skip("no lead user to act as")
    cur.execute("set local role authenticated")
    cur.execute("select set_config('app.user_id', %s, true)", (str(uid),))
    return str(uid)


def _account(cur: Any, uid: str, email: str) -> None:
    cid = _one(cur, "select id from public.clients limit 1")
    did = _one(cur, "select id from public.directories limit 1")
    if cid is None:
        pytest.skip("no clients")
    cur.execute(
        "insert into public.citation_accounts "
        "  (client_id, directory_id, registration_email, created_by) values (%s, %s, %s, %s)",
        (cid, did, email, uid),
    )


def test_an_unsealed_account_can_be_rolled_back(cur: Any, as_operator: str) -> None:
    """0111 gave this table SELECT, INSERT and UPDATE policies and no DELETE policy. Under
    FORCE ROW LEVEL SECURITY a DELETE with no policy is NOT an error - it matches zero
    rows and reports success - so the rollback in `create_account_with_credential` did
    nothing, and the credential-less row it existed to remove then blocked the retry via
    the unique (client_id, directory_id) constraint."""
    _account(cur, as_operator, "rollback-probe@example.com")
    cur.execute(
        "delete from public.citation_accounts where registration_email = %s",
        ("rollback-probe@example.com",),
    )
    assert cur.rowcount == 1


def test_a_sealed_account_cannot_be_deleted(cur: Any, as_operator: str) -> None:
    """The policy is narrower than the others on purpose: a sealed account is a record of
    a login that exists in the world, and deleting it orphans the vault entry it points
    at. Rotation and disablement are UPDATEs."""
    _account(cur, as_operator, "sealed-probe@example.com")
    cur.execute(
        "update public.citation_accounts set credential_sealed_at = now() "
        "where registration_email = %s",
        ("sealed-probe@example.com",),
    )
    cur.execute(
        "delete from public.citation_accounts where registration_email = %s",
        ("sealed-probe@example.com",),
    )
    assert cur.rowcount == 0, "a sealed account must not be deletable"


# --------------------------------------------------------------------------- #
# The claim is the last moment before a person acts.
# --------------------------------------------------------------------------- #
def test_a_directory_flipped_to_route_f_stops_being_handed_out(
    cur: Any, as_operator: str
) -> None:
    """0115's trigger stops a route-F row ENTERING the queue. It cannot stop a directory
    from BECOMING route F while a row already waits there - and it will: `tos_checked_at`
    exists precisely because terms are researched over time, one directory at a time.

    Without the join in `claim_next`, the queue would keep offering a directory we have
    since learned forbids the submission, and the operator would have no way to know.
    """
    cdir = _route_dir(cur, "C")
    cid = _one(
        cur,
        "insert into public.citations (directory, directory_id, submit_status) "
        "values ('probe-flip', %s, 'ready_for_human') returning id",
        cdir,
    )
    claimable = """
        select count(*) from public.citations c
          left join public.directories d on d.id = c.directory_id
         where c.id = %s and c.submit_status = 'ready_for_human'
           and coalesce(d.route, 'C') <> 'F'
    """
    assert _one(cur, claimable, cid) == 1, "a route-C row must be claimable to start with"

    cur.execute("update public.directories set route = 'F' where id = %s", (cdir,))
    assert _one(cur, claimable, cid) == 0, (
        "once the directory is route F the waiting row must stop being offered"
    )
