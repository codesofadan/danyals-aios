"""Data-import repo: the RLS seam, the traversal guard, and the privileged writer's
allow-list.

No DB: ``rls_connection`` / ``privileged_connection`` are patched with a recorder that
captures the SQL + params, so these assert on the STATEMENTS the repo builds - which is
where the SQL rules live. No filesystem beyond ``tmp_path``.

Three properties are pinned here and each is load-bearing:

1. **The seam.** Tenant reads go through ``rls_connection`` bound to the CALLER's id;
   the commit writer goes through ``privileged_connection``. A read that quietly moved
   to the privileged pool would bypass RLS for every caller.
2. **The identifiers.** ``insert_rows`` builds column names by iterating the FROZEN
   allow-list, never the row's keys - so a hostile row key cannot become SQL, and a row
   carrying one is rejected outright.
3. **The traversal guard.** ``resolve``/``path_for`` refuse anything outside the import
   root, so a crafted ``stored_path`` cannot make the worker read ``/etc/passwd``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from psycopg import sql

from app.modules.data_import.constants import target_for
from app.modules.data_import.repo import (
    ImportRepo,
    ImportTargetError,
    ServiceImportStore,
)
from app.modules.data_import.storage import (
    ImportRejectedError,
    ImportTooLargeError,
    LocalImportStore,
    write_upload,
)

pytestmark = pytest.mark.unit

_USER = "11111111-1111-1111-1111-111111111111"


class _Cur:
    """A recording cursor: captures every (query, params) and replays canned rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[Any, Any]] = []
        self._rows = rows if rows is not None else []

    def execute(self, query: Any, params: Any = None) -> None:
        self.calls.append((query, params))

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)

    # --- assertions helpers ---
    @property
    def sql_text(self) -> str:
        """The last statement as text (``sql.Composed`` renders via ``as_string``)."""
        query = self.calls[-1][0]
        return query if isinstance(query, str) else query.as_string(None)

    @property
    def params(self) -> Any:
        return self.calls[-1][1]


class _Conn:
    """A context manager yielding the recording cursor, like the real seams do."""

    def __init__(self, cur: _Cur) -> None:
        self._cur = cur

    def __enter__(self) -> _Cur:
        return self._cur

    def __exit__(self, *exc: Any) -> bool:
        return False


@pytest.fixture
def rls(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch ``rls_connection`` and record the user id it was bound to."""
    state: dict[str, Any] = {"user_id": None, "cur": _Cur()}

    def _fake(user_id: str) -> _Conn:
        state["user_id"] = user_id
        return _Conn(state["cur"])

    monkeypatch.setattr("app.modules.data_import.repo.rls_connection", _fake)
    return state


@pytest.fixture
def privileged(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch ``privileged_connection`` (the commit writer's seam)."""
    state: dict[str, Any] = {"used": False, "cur": _Cur()}

    def _fake() -> _Conn:
        state["used"] = True
        return _Conn(state["cur"])

    monkeypatch.setattr("app.modules.data_import.repo.privileged_connection", _fake)
    return state


# --------------------------------------------------------------------------- #
# 1. The RLS seam.
# --------------------------------------------------------------------------- #
def test_reads_bind_rls_to_the_callers_own_id(rls: Any) -> None:
    """RLS is bound to the CALLER, so a repo built for user A can never read as user B."""
    ImportRepo(_USER).list_runs(limit=10)
    assert rls["user_id"] == _USER


def test_list_runs_binds_every_filter_as_a_param_never_string_formatted(rls: Any) -> None:
    """The impersonation-review SQL rule: a filter is a VALUE, so it is bound."""
    ImportRepo(_USER).list_runs(
        client_id="cl-1'; drop table public.import_runs; --",
        status="imported",
        source_type="keywords",
        limit=10,
        offset=5,
    )
    text, params = rls["cur"].sql_text, rls["cur"].params
    assert "drop table" not in text
    assert "client_id = %s" in text and "status = %s" in text and "source_type = %s" in text
    assert params[0] == "cl-1'; drop table public.import_runs; --"
    assert params[-2:] == [10, 5]


def test_list_runs_orders_newest_first(rls: Any) -> None:
    """An import ledger is read as a timeline; ``id`` keeps the order stable across ties."""
    ImportRepo(_USER).list_runs()
    assert "order by created_at desc, id" in rls["cur"].sql_text


def test_stats_scopes_all_three_tiles_to_the_same_30_day_window(rls: Any) -> None:
    """Pairing a 30-day run count with an all-time row total would make the tiles
    describe two different periods and quietly overstate the row numbers."""
    ImportRepo(_USER).import_stats()
    text = rls["cur"].sql_text
    assert text.count("interval '30 days'") == 1
    assert "where created_at >= now() - interval '30 days'" in text
    assert "count(*) as imports_30d" in text
    assert "sum(rows_mapped)" in text and "sum(rows_error)" in text


def test_create_run_stores_the_path_and_binds_every_value(rls: Any) -> None:
    ImportRepo(_USER).create_run(
        client_id=None,
        client_name="",
        filename="../../etc/passwd",
        stored_path="deadbeef.csv",
        source_type="keywords",
        detected_columns=["Keyword"],
        column_map={"Keyword": "keyword"},
        content_sha256="abc",
        uploaded_by=_USER,
    )
    text, params = rls["cur"].sql_text, rls["cur"].params
    assert "insert into public.import_runs" in text
    # The hostile filename is a bound VALUE, not SQL text - and it is only ever display.
    assert "passwd" not in text
    assert params[2] == "../../etc/passwd"
    assert params[3] == "deadbeef.csv"


def test_create_mapping_reuses_the_0042_unique_so_a_resave_is_idempotent(rls: Any) -> None:
    """``unique nulls not distinct (source_type, name)``: re-saving a template under the
    same name must UPDATE it, not raise - a save button has to be idempotent."""
    ImportRepo(_USER).create_mapping(
        name="GSC queries", source_type="search_console",
        column_map={"Query": "query"}, source_signature="sig", created_by=_USER,
    )
    text = rls["cur"].sql_text
    assert "on conflict (source_type, name) do update set" in text


def test_find_mapping_for_skips_the_query_entirely_on_an_empty_signature(rls: Any) -> None:
    """An empty signature would match every template that never recorded one."""
    assert ImportRepo(_USER).find_mapping_for("keywords", "") is None
    assert rls["cur"].calls == []


def test_set_mapping_moves_the_run_to_mapping(rls: Any) -> None:
    ImportRepo(_USER).set_mapping("run-1", {"Keyword": "keyword"})
    text = rls["cur"].sql_text
    assert "update public.import_runs set column_map = %s, status = 'mapping'" in text
    assert rls["cur"].params[-1] == "run-1"


# --------------------------------------------------------------------------- #
# 2. The privileged writer + the ALLOW-LIST.
# --------------------------------------------------------------------------- #
def test_commit_writer_uses_the_privileged_seam(privileged: Any) -> None:
    """The worker holds no user JWT and the target tables' RLS insert policies are
    lead-only, so the commit runs on service_role - exactly like 0035's research ingest."""
    target = target_for("keywords")
    assert target is not None
    ServiceImportStore().insert_rows(
        target, [{"keyword": "x", "client_id": "cl-1", "client_name": "N", "source": "import"}]
    )
    assert privileged["used"]


@pytest.mark.parametrize(
    "hostile_column",
    ["password_hash", "id", "created_at", "keyword) --", "drop table public.keywords"],
)
def test_insert_rows_rejects_a_row_carrying_a_column_outside_the_allow_list(
    privileged: Any, hostile_column: str
) -> None:
    """The injection boundary's SECOND, independent gate.

    ``validate_mapping`` already rejects this at the router - so reaching here means
    something upstream is broken, and the store must fail LOUDLY rather than silently
    dropping the column (which would hide the bug) or writing it (which would be the
    vulnerability).
    """
    target = target_for("keywords")
    assert target is not None
    with pytest.raises(ImportTargetError) as exc:
        ServiceImportStore().insert_rows(target, [{"keyword": "x", hostile_column: "boom"}])
    assert hostile_column in str(exc.value)
    assert privileged["cur"].calls == [], "nothing may be executed once a row is rejected"


def test_insert_rows_builds_identifiers_only_from_the_frozen_allow_list(privileged: Any) -> None:
    """The property that makes the injection unreachable: the column list is produced by
    iterating ``target.all_columns`` (literals in ``constants``) and testing membership in
    the row. The row's OWN keys never become identifiers, so there is no path from file
    input to SQL text even if validation were bypassed."""
    target = target_for("keywords")
    assert target is not None
    ServiceImportStore().insert_rows(
        target,
        [{"keyword": "dental implants", "volume": 8100, "client_id": "cl-1",
          "client_name": "N", "source": "import"}],
    )
    text = privileged["cur"].sql_text
    assert 'insert into public.keywords ("keyword", "volume", "client_id", "client_name", "source")' in text
    # Every VALUE is a placeholder; no data is inlined.
    assert "dental implants" not in text
    assert "8100" not in text
    assert privileged["cur"].params == ["dental implants", 8100, "cl-1", "N", "import"]


def test_insert_rows_omits_a_column_no_row_supplies_so_the_db_default_applies(
    privileged: Any,
) -> None:
    """0018's ``anchor text not null default ''`` would REJECT an explicit NULL. Writing
    only the columns actually present is what lets each table's own default stand."""
    target = target_for("backlinks")
    assert target is not None
    ServiceImportStore().insert_rows(
        target, [{"ref_domain": "example.com", "client_id": "cl-1", "client_name": "N"}]
    )
    text = privileged["cur"].sql_text
    assert '"anchor"' not in text
    assert '"first_seen"' not in text
    assert '"ref_domain"' in text


def test_insert_rows_reuses_each_targets_own_uniqueness_key_verbatim(privileged: Any) -> None:
    """The idempotency contract: an ``on conflict`` key invented here would not match the
    table's actual unique index and would raise 42P10 on the first duplicate."""
    keywords = target_for("keywords")
    assert keywords is not None
    ServiceImportStore().insert_rows(keywords, [{"keyword": "x", "client_id": "c", "client_name": "N", "source": "import"}])
    # 0035: unique nulls not distinct (client_id, keyword, geo)
    assert 'on conflict ("client_id", "keyword", "geo") do nothing' in privileged["cur"].sql_text

    rankings = target_for("rankings")
    assert rankings is not None
    ServiceImportStore().insert_rows(
        rankings,
        [{"keyword": "x", "client_id": "c", "client_name": "N", "normalized_keyword": "x"}],
    )
    # 0036: unique nulls not distinct (client_id, normalized_keyword, engine, device,
    # location, language) - a duplicate here would be a duplicate nightly CHARGE.
    assert (
        'on conflict ("client_id", "normalized_keyword", "engine", "device", "location", "language") do nothing'
        in privileged["cur"].sql_text
    )


def test_insert_rows_emits_a_plain_insert_for_an_append_shaped_ledger(privileged: Any) -> None:
    """0018 declares NO unique key on backlinks/citations - they are append-shaped
    monitoring ledgers. Inventing one here would silently change the off-page module's
    semantics, so the run-CLAIM is those targets' idempotency guard instead."""
    for source_type in ("backlinks", "citations", "search_console"):
        target = target_for(source_type)
        assert target is not None
        assert target.conflict == (), f"{source_type} must not claim a uniqueness key"


def test_insert_rows_refuses_the_staging_only_custom_target(privileged: Any) -> None:
    target = target_for("custom")
    assert target is not None
    with pytest.raises(ImportTargetError):
        ServiceImportStore().insert_rows(target, [{"anything": "x"}])


def test_insert_rows_is_a_no_op_on_an_empty_batch(privileged: Any) -> None:
    target = target_for("keywords")
    assert target is not None
    assert ServiceImportStore().insert_rows(target, []) == 0
    assert privileged["cur"].calls == []


def test_claim_run_is_a_conditional_update_not_a_read_then_write(privileged: Any) -> None:
    """The module's idempotency guard. ``acks_late`` redelivers, and two workers reading
    "status = mapping" a millisecond apart would BOTH import the file - so the claim must
    be one UPDATE whose ``where`` is evaluated under the row lock. ``importing`` is
    deliberately not claimable, so a redelivery mid-import is a no-op too."""
    ServiceImportStore().claim_run("run-1")
    text, params = privileged["cur"].sql_text, privileged["cur"].params
    assert "update public.import_runs set status = 'importing'" in text
    assert "where id = %s and status = any(%s)" in text
    assert params[1] == ["uploaded", "mapping", "validating"]
    assert "importing" not in params[1]


def test_finish_run_writes_the_sample_as_bound_jsonb(privileged: Any) -> None:
    ServiceImportStore().finish_run(
        "run-1", status="partial", rows_total=10, rows_mapped=8, rows_error=2,
        error_sample=[{"row": 3, "field": "volume", "value": "n/a", "reason": "bad"}],
    )
    text = privileged["cur"].sql_text
    assert "update public.import_runs set status = %s" in text
    assert "n/a" not in text  # the sample is a bound value, never inlined


def test_target_table_names_are_static_literals_not_input() -> None:
    """A defence-in-depth read of the constants themselves: the table a source_type writes
    into is a frozen literal, so no request can retarget an import at another table."""
    for source_type in ("keywords", "rankings", "backlinks", "citations", "search_console"):
        target = target_for(source_type)
        assert target is not None
        assert target.table is not None
        assert target.table.startswith("public.")
        assert sql.SQL(target.table).as_string(None) == target.table


# --------------------------------------------------------------------------- #
# 3. The traversal guard (storage).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "hostile_key",
    [
        "../../etc/passwd",
        "../../../../../../etc/shadow",
        "/etc/passwd",
        "C:\\Windows\\System32\\config\\SAM",
        "..\\..\\secrets.csv",
        "subdir/x.csv",
        "a/../../b.csv",
        "....//....//etc/passwd",
        "%2e%2e%2fetc%2fpasswd",
        "deadbeef.csv\x00.png",
        "",
        "..",
        ".",
    ],
)
def test_resolve_refuses_any_key_that_escapes_the_import_root(
    tmp_path: Path, hostile_key: str
) -> None:
    """A crafted ``stored_path`` must never make the worker read an arbitrary file.

    Two independent guards stack: the key SHAPE check (a key cannot even spell a
    separator or a dot-segment) and the resolved-prefix check ``audit_artifacts`` uses.
    Either alone would probably do; together they survive a future key-format change.
    """
    store = LocalImportStore(tmp_path)
    assert store.resolve(hostile_key) is None
    with pytest.raises(ImportRejectedError):
        store.path_for(hostile_key)


def test_resolve_returns_a_real_file_inside_the_root(tmp_path: Path) -> None:
    """The guard must not be so strict it rejects the store's own keys - a traversal
    guard that refuses everything passes every attack test and ships nothing."""
    store = LocalImportStore(tmp_path)
    key = store.new_key("csv")
    (tmp_path / key).write_bytes(b"Query,Clicks\n")
    resolved = store.resolve(key)
    assert resolved is not None
    assert resolved.read_bytes() == b"Query,Clicks\n"
    assert resolved.parent == tmp_path.resolve()


def test_resolve_returns_none_for_a_well_formed_key_with_no_file(tmp_path: Path) -> None:
    store = LocalImportStore(tmp_path)
    assert store.resolve(store.new_key("csv")) is None


def test_new_key_never_derives_the_name_from_the_upload(tmp_path: Path) -> None:
    """The stored name is GENERATED. The only name on offer is attacker-controlled, so it
    is not used at all - which is why no traversal payload can ever BE a path here."""
    store = LocalImportStore(tmp_path)
    key = store.new_key("csv")
    assert key.endswith(".csv")
    assert len(key) == 36  # 32 hex + '.' + 'csv'
    assert key != store.new_key("csv")  # unique per upload


def test_new_key_rejects_an_extension_outside_the_allow_list(tmp_path: Path) -> None:
    store = LocalImportStore(tmp_path)
    for ext in ("exe", "sh", "php", "sql", ""):
        with pytest.raises(ImportRejectedError):
            store.new_key(ext)


class _FakeUpload:
    """A chunked upload source (the ``UploadSource`` protocol), no Starlette needed."""

    def __init__(self, data: bytes, chunk: int = 8) -> None:
        self._data = data
        self._chunk = chunk
        self._pos = 0

    async def read(self, size: int = -1) -> bytes:
        take = self._chunk if size == -1 else min(size, self._chunk)
        out = self._data[self._pos : self._pos + take]
        self._pos += len(out)
        return out


async def test_write_upload_streams_and_returns_the_digest(tmp_path: Path) -> None:
    import hashlib

    store = LocalImportStore(tmp_path)
    key = store.new_key("csv")
    payload = b"Query,Clicks\nplumber,12\n" * 100
    size, digest = await write_upload(store, key, _FakeUpload(payload), max_bytes=1_000_000)
    assert size == len(payload)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert (tmp_path / key).read_bytes() == payload


async def test_write_upload_enforces_the_cap_on_the_stream_and_cleans_up(tmp_path: Path) -> None:
    """The cap is enforced as bytes LAND, not from a Content-Length: a header is a claim
    and a chunked body has none. The partial file is removed, so a hostile upload costs
    the cap plus one chunk of disk and nothing more."""
    store = LocalImportStore(tmp_path)
    key = store.new_key("csv")
    with pytest.raises(ImportTooLargeError):
        await write_upload(store, key, _FakeUpload(b"x" * 5_000), max_bytes=100)
    assert not (tmp_path / key).exists()
    assert list(tmp_path.iterdir()) == []


async def test_write_upload_cleans_up_when_the_stream_itself_fails(tmp_path: Path) -> None:
    """A half-written file must never be left behind for the worker to parse as if it
    were the whole export."""

    class _Broken:
        async def read(self, size: int = -1) -> bytes:
            raise OSError("connection reset")

    store = LocalImportStore(tmp_path)
    key = store.new_key("csv")
    with pytest.raises(OSError, match="connection reset"):
        await write_upload(store, key, _Broken(), max_bytes=1_000)
    assert not (tmp_path / key).exists()


def test_delete_never_raises_on_a_hostile_or_missing_key(tmp_path: Path) -> None:
    """Cleanup failing must not mask the reason we are cleaning up."""
    store = LocalImportStore(tmp_path)
    store.delete("../../etc/passwd")
    store.delete(store.new_key("csv"))
    store.delete("")


def test_store_from_settings_degrades_to_none_when_unconfigured() -> None:
    from app.config import Settings
    from app.modules.data_import.storage import import_store_from_settings

    assert import_store_from_settings(Settings(_env_file=None, app_env="dev")) is None
    configured = Settings(_env_file=None, app_env="dev", import_artifact_dir="/tmp/imports")
    assert import_store_from_settings(configured) is not None
