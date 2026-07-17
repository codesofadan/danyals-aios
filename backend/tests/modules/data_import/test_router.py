"""Data-import endpoints: the access gates, the upload gates, and the two leaks.

No DB, no network, no Celery: the repo is an in-memory fake injected through
``dependency_overrides``, the enqueuer is a recorder, the upload store is a real
``LocalImportStore`` over ``tmp_path``, and the feature-grant lookup (the one DB read
inside ``require_feature``) is monkeypatched.

Three gates stack on every route, and each is pinned INDEPENDENTLY - a test that only
ever checks the happy path would not notice one of them vanishing:

1. auth           - swept for the whole app by ``tests/test_route_auth_guard.py``;
                    re-pinned for this module's 9 routes below.
2. data_import FEATURE grant - every route.
3. view_reports (reads) / manage_clients (every mutation).

Plus the ones unique to an endpoint that accepts a FILE: the extension allow-list, the
declared-MIME allow-list, the content SNIFF, and the size cap - and the two things that
must never appear in a body: ``stored_path`` and ``client_id``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings, get_settings
from app.core.auth import CurrentUser, get_current_user
from app.modules.data_import.repo import get_import_repo
from app.modules.data_import.router import get_import_enqueuer, get_import_store
from app.modules.data_import.storage import LocalImportStore

pytestmark = pytest.mark.unit

_RUN_KEYS = {
    "id", "file", "sourceType", "sourceLabel", "status", "client", "rows", "mapped",
    "errors", "detectedColumns", "columnMap", "created",
}

_SECRET_PATH = "0123456789abcdef0123456789abcdef.csv"
_SECRET_CLIENT = "cl-secret-must-never-leak"

_CSV = b"Keyword,Volume\ndental implants,8100\n"

# (method, path) for every route the module publishes.
_READ_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/v1/data-import/runs"),
    ("GET", "/api/v1/data-import/runs/run-1"),
    ("GET", "/api/v1/data-import/stats"),
    ("GET", "/api/v1/data-import/workspace"),
    ("GET", "/api/v1/data-import/fields?sourceType=keywords"),
    ("GET", "/api/v1/data-import/mappings"),
]
_WRITE_ROUTES: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "/api/v1/data-import/runs/run-1/mapping", {"columnMap": {"Keyword": "keyword"}}),
    ("POST", "/api/v1/data-import/runs/run-1/commit", {}),
    (
        "POST", "/api/v1/data-import/mappings",
        {"name": "t", "sourceType": "keywords", "columnMap": {"Keyword": "keyword"}},
    ),
]
_ALL_ROUTES = [*_READ_ROUTES, *[(m, p) for m, p, _b in _WRITE_ROUTES]]

# The staff roles that hold manage_clients (mirrors the 0042 RLS write policies).
_LEADS = ["owner", "admin", "manager"]
_NON_LEAD_STAFF = ["specialist", "analyst", "viewer"]


def _message(resp: httpx.Response) -> str:
    """The rejection reason out of the app's global error envelope (invariant #5)."""
    return str(resp.json()["error"]["message"])


def _run_row(**over: Any) -> dict[str, Any]:
    """An ``import_runs`` row AS THE REPO RETURNS IT (``select *``), carrying the
    server-only columns - so the leak tests below are not vacuous."""
    row: dict[str, Any] = {
        "id": "run-1",
        "client_id": _SECRET_CLIENT,
        "client_name": "NorthPeak Dental",
        "filename": "keywords.csv",
        "stored_path": _SECRET_PATH,
        "source_type": "keywords",
        "status": "mapping",
        "detected_columns": ["Keyword", "Volume"],
        "column_map": {"Keyword": "keyword"},
        "rows_total": 2,
        "rows_mapped": 2,
        "rows_error": 0,
        "error_sample": [],
        "content_sha256": "abc",
        "uploaded_by": "u-1",
        "created_at": None,
        "updated_at": None,
    }
    row.update(over)
    return row


class FakeImportRepo:
    """In-memory stand-in for the RLS-scoped ImportRepo."""

    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []
        self.stats: dict[str, Any] = {"imports_30d": 0, "rows_mapped": 0, "rows_error": 0}
        self.by_id: dict[str, dict[str, Any]] = {}
        self.client_names: dict[str, str] = {}
        self.mappings: list[dict[str, Any]] = []
        self.template: dict[str, Any] | None = None
        self.created: list[dict[str, Any]] = []
        self.mapped: list[tuple[str, dict[str, str]]] = []
        self.saved: list[dict[str, Any]] = []
        self.list_kwargs: dict[str, Any] | None = None

    def list_runs(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_kwargs = kwargs
        return list(self.runs)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.by_id.get(run_id)

    def import_stats(self) -> dict[str, Any]:
        return dict(self.stats)

    def client_name_for(self, client_id: str) -> str | None:
        return self.client_names.get(client_id)

    def list_mappings(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.mappings)

    def find_mapping_for(self, source_type: str, signature: str) -> dict[str, Any] | None:
        return self.template

    def create_run(self, **kwargs: Any) -> dict[str, Any]:
        self.created.append(kwargs)
        return _run_row(
            status="uploaded",
            filename=kwargs["filename"],
            stored_path=kwargs["stored_path"],
            source_type=kwargs["source_type"],
            client_id=kwargs["client_id"],
            client_name=kwargs["client_name"],
            detected_columns=kwargs["detected_columns"],
            column_map=kwargs["column_map"],
        )

    def set_mapping(self, run_id: str, column_map: dict[str, str]) -> dict[str, Any] | None:
        self.mapped.append((run_id, column_map))
        row = self.by_id.get(run_id)
        return {**row, "column_map": column_map, "status": "mapping"} if row else None

    def create_mapping(self, **kwargs: Any) -> dict[str, Any]:
        self.saved.append(kwargs)
        return {
            "id": "map-1", "name": kwargs["name"], "source_type": kwargs["source_type"],
            "column_map": kwargs["column_map"], "source_signature": kwargs["source_signature"],
            "created_at": None,
        }


def _user(role: str = "owner") -> CurrentUser:
    return CurrentUser(
        id="00000000-0000-0000-0000-0000000000ff", email=f"{role}@aios.dev", role=role,  # type: ignore[arg-type]
        status="active", name=role.title(), title="", avatar_color="#7B69EE", phone="",
        two_fa=False,
    )


@pytest.fixture
def repo() -> FakeImportRepo:
    return FakeImportRepo()


@pytest.fixture
def files(tmp_path: Path) -> LocalImportStore:
    return LocalImportStore(tmp_path)


@pytest.fixture
def enqueued() -> list[str]:
    return []


@pytest.fixture
def wired(
    app: FastAPI, repo: FakeImportRepo, files: LocalImportStore, enqueued: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    """The module wired to fakes, as an OWNER (whose feature grant short-circuits)."""
    app.dependency_overrides[get_current_user] = lambda: _user("owner")
    app.dependency_overrides[get_import_repo] = lambda: repo
    app.dependency_overrides[get_import_store] = lambda: files
    app.dependency_overrides[get_import_enqueuer] = lambda: enqueued.append
    monkeypatch.setattr(
        "app.core.auth._load_feature_grants", lambda user_id: {"data_import": "full"}
    )
    return app


def _as(app: FastAPI, role: str) -> None:
    app.dependency_overrides[get_current_user] = lambda: _user(role)


# --------------------------------------------------------------------------- #
# 1. The access gates.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_every_route_requires_authentication(
    app: FastAPI, client: httpx.AsyncClient, method: str, path: str
) -> None:
    """Re-pinned per-module even though ``test_route_auth_guard`` sweeps the whole app:
    that sweep proves the app has no unguarded route; this proves THIS module's routes
    are the ones being guarded."""
    resp = await client.request(method, path, json={})
    assert resp.status_code == 401


@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_every_route_requires_the_data_import_feature_grant(
    wired: FastAPI, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch,
    method: str, path: str,
) -> None:
    _as(wired, "admin")  # not owner: owner is all-on and would short-circuit the check
    monkeypatch.setattr("app.core.auth._load_feature_grants", lambda user_id: {"data_import": "off"})
    resp = await client.request(method, path, json={"columnMap": {"Keyword": "keyword"}})
    assert resp.status_code == 403
    assert "data_import" in _message(resp)


@pytest.mark.parametrize(("method", "path", "body"), _WRITE_ROUTES)
@pytest.mark.parametrize("role", _NON_LEAD_STAFF)
async def test_mutations_reject_a_staff_role_without_manage_clients(
    wired: FastAPI, client: httpx.AsyncClient, method: str, path: str,
    body: dict[str, Any], role: str,
) -> None:
    """The app gate mirrors the 0042 RLS insert/update policy exactly
    (``owner|admin|manager``). A specialist HOLDS the data_import feature (the SEO role
    template grants it) yet must not write - so this is the gate that actually stops
    them, and getting it wrong would surface as an opaque RLS error, not a clean 403."""
    _as(wired, role)
    resp = await client.request(method, path, json=body)
    assert resp.status_code == 403
    assert "manage_clients" in _message(resp)


@pytest.mark.parametrize("role", _LEADS)
async def test_mutations_admit_every_lead_role(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo, role: str
) -> None:
    """The other half of the gate: a gate that rejected everyone would pass the test
    above and ship a broken module."""
    _as(wired, role)
    repo.by_id["run-1"] = _run_row()
    resp = await client.post(
        "/api/v1/data-import/runs/run-1/mapping", json={"columnMap": {"Keyword": "keyword"}}
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize(("method", "path"), _READ_ROUTES)
async def test_reads_admit_a_viewer(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo, method: str, path: str
) -> None:
    _as(wired, "viewer")
    repo.by_id["run-1"] = _run_row()
    resp = await client.request(method, path)
    assert resp.status_code == 200, resp.text


async def test_a_portal_client_can_never_reach_the_module(
    wired: FastAPI, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An import ledger names other tenants' files, so clients get NO select policy in
    0042 at all - and the app gate refuses them before the DB is ever asked."""
    _as(wired, "client")
    monkeypatch.setattr("app.core.auth._load_feature_grants", lambda user_id: {})
    resp = await client.get("/api/v1/data-import/runs")
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# 2. The UPLOAD gates - the endpoint takes a FILE.
# --------------------------------------------------------------------------- #
def _upload(
    content: bytes = _CSV, *, name: str = "keywords.csv", mime: str = "text/csv",
    source_type: str = "keywords", client_id: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"sourceType": source_type}
    if client_id is not None:
        data["clientId"] = client_id
    return {"files": {"file": (name, content, mime)}, "data": data}


async def test_a_valid_upload_is_stored_sniffed_and_auto_mapped(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo, files: LocalImportStore
) -> None:
    resp = await client.post("/api/v1/data-import/uploads", **_upload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body) == {"run", "columns", "suggested", "template"}
    assert set(body["run"]) == _RUN_KEYS
    assert body["run"]["file"] == "keywords.csv"
    assert body["suggested"] == {"Keyword": "keyword", "Volume": "volume"}
    assert body["columns"] == [
        {"column": "Keyword", "samples": ["dental implants"]},
        {"column": "Volume", "samples": ["8100"]},
    ]
    # The bytes actually landed under the controlled root, under a GENERATED name.
    key = repo.created[0]["stored_path"]
    stored = files.resolve(key)
    assert stored is not None and stored.read_bytes() == _CSV


@pytest.mark.parametrize(
    ("name", "mime"),
    [
        ("evil.exe", "application/octet-stream"),
        ("evil.sh", "text/plain"),
        ("dump.sql", "text/plain"),
        ("legacy.xls", "application/vnd.ms-excel"),
        ("data.json", "application/json"),
        ("noextension", "text/csv"),
        ("../../etc/passwd", "text/csv"),
    ],
)
async def test_upload_rejects_an_extension_outside_the_allow_list(
    wired: FastAPI, client: httpx.AsyncClient, files: LocalImportStore, tmp_path: Path,
    name: str, mime: str,
) -> None:
    resp = await client.post("/api/v1/data-import/uploads", **_upload(name=name, mime=mime))
    assert resp.status_code == 415
    assert list(tmp_path.iterdir()) == [], "a rejected upload must leave nothing on disk"


@pytest.mark.parametrize(
    "mime",
    ["application/octet-stream", "application/json", "image/png", "application/x-sh", ""],
)
async def test_upload_rejects_a_content_type_outside_the_allow_list(
    wired: FastAPI, client: httpx.AsyncClient, tmp_path: Path, mime: str
) -> None:
    """``application/octet-stream`` is deliberately NOT accepted: it is what a client
    sends when it knows nothing about the file, so honouring it would make this gate
    decorative."""
    resp = await client.post("/api/v1/data-import/uploads", **_upload(mime=mime))
    assert resp.status_code == 415
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("payload", "label"),
    [
        (b"PK\x03\x04\x14\x00\x00\x00evil", "a zip archive"),
        (b"%PDF-1.7\n1 0 obj", "a PDF"),
        (b"\x89PNG\r\n\x1a\n\x00\x00", "a PNG"),
        (b"\x7fELF\x02\x01\x01\x00", "an ELF binary"),
        (b"MZ\x90\x00\x03\x00", "a Windows executable"),
        (b"Keyword,Volume\n\x00\x01\x02\x03", "binary with NULs"),
    ],
)
async def test_upload_sniffs_the_bytes_and_rejects_a_renamed_file(
    wired: FastAPI, client: httpx.AsyncClient, tmp_path: Path, payload: bytes, label: str
) -> None:
    """DO NOT TRUST THE EXTENSION. The name says ``.csv`` and the MIME says ``text/csv``;
    only the magic bytes reveal it is really ``{label}``. The partial write is cleaned up,
    so a rejected upload leaves nothing behind."""
    resp = await client.post("/api/v1/data-import/uploads", **_upload(payload))
    assert resp.status_code == 415, f"{label} was accepted as a .csv"
    assert "not a valid" in _message(resp)
    assert list(tmp_path.iterdir()) == []


async def test_upload_rejects_a_csv_renamed_to_xlsx(
    wired: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    """The inverse lie: openpyxl would raise on it in the worker; the rejection belongs at
    the door."""
    resp = await client.post(
        "/api/v1/data-import/uploads",
        **_upload(name="x.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )
    assert resp.status_code == 415
    assert list(tmp_path.iterdir()) == []


async def test_upload_rejects_an_oversized_file_and_stores_nothing(
    wired: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    """The cap is enforced on the STREAM as bytes land (a Content-Length is a claim, and
    a chunked body has none), so the partial write is removed and a hostile upload costs
    the cap plus one chunk of disk."""
    wired.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, app_env="dev", import_max_file_bytes=64
    )
    big = b"Keyword,Volume\n" + b"x,1\n" * 500
    resp = await client.post("/api/v1/data-import/uploads", **_upload(big))
    assert resp.status_code == 413
    assert "limit" in _message(resp)
    assert list(tmp_path.iterdir()) == [], "an oversized upload must leave nothing on disk"


async def test_upload_accepts_a_file_right_at_the_cap(
    wired: FastAPI, client: httpx.AsyncClient
) -> None:
    """A cap that rejected everything would pass the test above and ship a dead endpoint."""
    wired.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, app_env="dev", import_max_file_bytes=len(_CSV)
    )
    resp = await client.post("/api/v1/data-import/uploads", **_upload())
    assert resp.status_code == 201, resp.text


async def test_upload_rejects_a_plain_zip_renamed_to_xlsx(
    wired: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    """The gap the SNIFF alone cannot close, and a real bug found while building this.

    An xlsx IS a zip, so a zip of holiday photos named ``.xlsx`` passes every byte check -
    and openpyxl then raises ``KeyError: [Content_Types].xml`` deep inside the preview.
    Unhandled that is a 500 AND an orphaned upload sitting in the import root. It must be
    a clean 400 with the file removed.
    """
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("photo.txt", "not a spreadsheet")
    resp = await client.post(
        "/api/v1/data-import/uploads",
        **_upload(
            buf.getvalue(), name="x.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    )
    assert resp.status_code == 400
    assert "could not be read" in _message(resp)
    assert list(tmp_path.iterdir()) == [], "an unreadable upload must not be left on disk"


async def test_upload_accepts_a_real_xlsx(
    wired: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    """The other half of the test above: the xlsx path must actually WORK - a gate that
    rejected every workbook would pass every rejection test and ship a dead format."""
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["Keyword", "Volume"])
    ws.append(["dental implants", 8100])
    buf = io.BytesIO()
    wb.save(buf)

    resp = await client.post(
        "/api/v1/data-import/uploads",
        **_upload(
            buf.getvalue(), name="keywords.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["suggested"] == {"Keyword": "keyword", "Volume": "volume"}
    assert resp.json()["columns"][0] == {"column": "Keyword", "samples": ["dental implants"]}


async def test_upload_rejects_an_empty_file(
    wired: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    resp = await client.post("/api/v1/data-import/uploads", **_upload(b""))
    assert resp.status_code == 400
    assert list(tmp_path.iterdir()) == []


async def test_upload_rejects_a_file_with_no_header_row(
    wired: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    resp = await client.post("/api/v1/data-import/uploads", **_upload(b"\n\n"))
    assert resp.status_code == 400
    assert list(tmp_path.iterdir()) == []


async def test_upload_never_derives_the_stored_name_from_the_filename(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo, tmp_path: Path
) -> None:
    """A crafted filename is never a path: the store MINTS the name. The hostile string
    survives only as ``filename``, a display value, reduced to its basename."""
    resp = await client.post(
        "/api/v1/data-import/uploads", **_upload(name="..\\..\\..\\evil.csv")
    )
    assert resp.status_code == 201, resp.text
    key = repo.created[0]["stored_path"]
    assert key.endswith(".csv") and "/" not in key and "\\" not in key and ".." not in key
    assert repo.created[0]["filename"] == "evil.csv"  # basename only, display-only
    assert [p.name for p in tmp_path.iterdir()] == [key]


async def test_upload_404s_an_unknown_client_rather_than_snapshotting_a_blank(
    wired: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    resp = await client.post("/api/v1/data-import/uploads", **_upload(client_id="cl-nope"))
    assert resp.status_code == 404
    assert list(tmp_path.iterdir()) == [], "a rejected upload must not leave the file behind"


async def test_upload_snapshots_the_client_name_for_a_client_scoped_import(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo
) -> None:
    repo.client_names["cl-1"] = "NorthPeak Dental"
    resp = await client.post("/api/v1/data-import/uploads", **_upload(client_id="cl-1"))
    assert resp.status_code == 201, resp.text
    assert repo.created[0]["client_name"] == "NorthPeak Dental"
    assert resp.json()["run"]["client"] == "NorthPeak Dental"


async def test_upload_allows_an_agency_global_import(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo
) -> None:
    """0035's bank is client-NULLABLE: filling it with unassigned keywords is valid."""
    resp = await client.post("/api/v1/data-import/uploads", **_upload())
    assert resp.status_code == 201, resp.text
    assert repo.created[0]["client_id"] is None


async def test_upload_refuses_a_rankings_import_without_a_client(
    wired: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    """0036's ``tracked_keywords.client_id`` is NOT NULL - a tracked keyword is a standing
    per-client bill, so there is no agency-global rankings import."""
    resp = await client.post("/api/v1/data-import/uploads", **_upload(source_type="rankings"))
    assert resp.status_code == 400
    assert "requires a client" in _message(resp)
    assert list(tmp_path.iterdir()) == []


async def test_upload_applies_a_matching_saved_template(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo
) -> None:
    """Next month's export of the same report maps itself."""
    repo.template = {
        "id": "map-1", "name": "Semrush keywords", "source_type": "keywords",
        "column_map": {"Keyword": "keyword"}, "source_signature": "sig", "created_at": None,
    }
    resp = await client.post("/api/v1/data-import/uploads", **_upload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["template"]["name"] == "Semrush keywords"
    assert repo.created[0]["column_map"] == {"Keyword": "keyword"}  # the template won


async def test_upload_503s_when_no_import_root_is_configured(
    wired: FastAPI, client: httpx.AsyncClient
) -> None:
    """A keyless module still has a configuration seam: an unconfigured root DEGRADES to
    a clean 503, never a crash and never a silent write to some default directory."""
    wired.dependency_overrides[get_import_store] = lambda: None
    resp = await client.post("/api/v1/data-import/uploads", **_upload())
    assert resp.status_code == 503
    assert "not configured" in _message(resp)


async def test_upload_rejects_an_unknown_source_type(
    wired: FastAPI, client: httpx.AsyncClient
) -> None:
    resp = await client.post("/api/v1/data-import/uploads", **_upload(source_type="nonsense"))
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# 3. Mapping + commit.
# --------------------------------------------------------------------------- #
async def test_mapping_rejects_a_target_outside_the_allow_list_at_the_edge(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo
) -> None:
    """The injection boundary AT THE DOOR: the worker never sees an unvalidated map."""
    repo.by_id["run-1"] = _run_row()
    resp = await client.post(
        "/api/v1/data-import/runs/run-1/mapping",
        json={"columnMap": {"Keyword": "keyword", "Volume": "password_hash"}},
    )
    assert resp.status_code == 400
    assert "not an importable field" in _message(resp)
    assert repo.mapped == [], "nothing may be persisted once a map is rejected"


async def test_mapping_rejects_a_header_the_file_does_not_have(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo
) -> None:
    repo.by_id["run-1"] = _run_row()
    resp = await client.post(
        "/api/v1/data-import/runs/run-1/mapping",
        json={"columnMap": {"Keyword": "keyword", "Ghost": "volume"}},
    )
    assert resp.status_code == 400
    assert "not a column in this file" in _message(resp)


async def test_mapping_persists_a_valid_map(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo
) -> None:
    repo.by_id["run-1"] = _run_row()
    resp = await client.post(
        "/api/v1/data-import/runs/run-1/mapping",
        json={"columnMap": {"Keyword": "keyword", "Volume": "volume"}},
    )
    assert resp.status_code == 200, resp.text
    assert repo.mapped == [("run-1", {"Keyword": "keyword", "Volume": "volume"})]
    assert resp.json()["status"] == "mapping"


async def test_mapping_404s_an_unknown_run(wired: FastAPI, client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/data-import/runs/nope/mapping", json={"columnMap": {"Keyword": "keyword"}}
    )
    assert resp.status_code == 404


@pytest.mark.parametrize("terminal", ["imported", "partial", "failed"])
async def test_mapping_409s_a_terminal_run(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo, terminal: str
) -> None:
    """Re-mapping a finished import would imply the already-written rows would change."""
    repo.by_id["run-1"] = _run_row(status=terminal)
    resp = await client.post(
        "/api/v1/data-import/runs/run-1/mapping", json={"columnMap": {"Keyword": "keyword"}}
    )
    assert resp.status_code == 409


async def test_commit_enqueues_the_worker(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo, enqueued: list[str]
) -> None:
    repo.by_id["run-1"] = _run_row()
    resp = await client.post("/api/v1/data-import/runs/run-1/commit", json={})
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"id": "run-1", "queued": True, "reason": ""}
    assert enqueued == ["run-1"]


async def test_commit_refuses_an_unmapped_run(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo, enqueued: list[str]
) -> None:
    repo.by_id["run-1"] = _run_row(status="uploaded", column_map={})
    resp = await client.post("/api/v1/data-import/runs/run-1/commit", json={})
    assert resp.status_code == 400
    assert enqueued == []


async def test_commit_refuses_the_staging_only_custom_type(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo, enqueued: list[str]
) -> None:
    """``custom`` stages only - there is no target table to commit into."""
    repo.by_id["run-1"] = _run_row(source_type="custom", column_map={"A": "keyword"})
    resp = await client.post("/api/v1/data-import/runs/run-1/commit", json={})
    assert resp.status_code == 400
    assert "stage only" in _message(resp)
    assert enqueued == []


@pytest.mark.parametrize("terminal", ["imported", "partial", "failed"])
async def test_commit_409s_a_terminal_run(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo, enqueued: list[str],
    terminal: str,
) -> None:
    repo.by_id["run-1"] = _run_row(status=terminal)
    resp = await client.post("/api/v1/data-import/runs/run-1/commit", json={})
    assert resp.status_code == 409
    assert enqueued == []


async def test_commit_is_an_honest_no_op_while_the_import_is_already_running(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo, enqueued: list[str]
) -> None:
    """A double-click must not enqueue a second run. (The worker's claim would no-op it
    anyway - this just says so plainly instead of queueing work that does nothing.)"""
    repo.by_id["run-1"] = _run_row(status="importing")
    resp = await client.post("/api/v1/data-import/runs/run-1/commit", json={})
    assert resp.status_code == 202
    assert resp.json()["queued"] is False
    assert enqueued == []


async def test_saving_a_template_validates_it_against_the_allow_list(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo
) -> None:
    """A template is validated at SAVE time, not only at use: an invalid one would
    otherwise auto-apply to a matching file months later and fail far from the mistake."""
    resp = await client.post(
        "/api/v1/data-import/mappings",
        json={"name": "t", "sourceType": "keywords", "columnMap": {"K": "password_hash"}},
    )
    assert resp.status_code == 400
    assert repo.saved == []


async def test_saving_a_valid_template_persists_it(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo
) -> None:
    resp = await client.post(
        "/api/v1/data-import/mappings",
        json={"name": "Semrush keywords", "sourceType": "keywords",
              "columnMap": {"Keyword": "keyword"}, "sourceSignature": "sig"},
    )
    assert resp.status_code == 201, resp.text
    assert set(resp.json()) == {"id", "name", "sourceType", "columnMap", "created"}
    assert repo.saved[0]["source_signature"] == "sig"


async def test_fields_publishes_the_allow_list_the_validator_enforces(
    wired: FastAPI, client: httpx.AsyncClient
) -> None:
    """The UI's picker and the validator read the SAME frozen table, so they cannot
    drift apart."""
    resp = await client.get("/api/v1/data-import/fields?sourceType=keywords")
    assert resp.status_code == 200
    body = resp.json()
    assert body["fields"] == ["keyword", "volume", "difficulty", "cpc", "intent", "geo"]
    assert body["required"] == ["keyword"]
    assert "client_id" not in body["fields"]  # derived columns are never mappable
    assert "source" not in body["fields"]


async def test_fields_reports_the_staging_only_type_as_having_none(
    wired: FastAPI, client: httpx.AsyncClient
) -> None:
    resp = await client.get("/api/v1/data-import/fields?sourceType=custom")
    assert resp.status_code == 200
    assert resp.json()["fields"] == []


# --------------------------------------------------------------------------- #
# 4. Reads + the two leaks.
# --------------------------------------------------------------------------- #
async def test_list_runs_emits_the_frozen_key_set(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo
) -> None:
    repo.runs = [_run_row()]
    resp = await client.get("/api/v1/data-import/runs")
    assert resp.status_code == 200
    assert set(resp.json()[0]) == _RUN_KEYS


async def test_list_runs_is_page_bounded(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo
) -> None:
    """No handler may ask the database for an unbounded page."""
    await client.get("/api/v1/data-import/runs?limit=10&offset=20")
    assert repo.list_kwargs is not None
    assert (repo.list_kwargs["limit"], repo.list_kwargs["offset"]) == (10, 20)
    resp = await client.get("/api/v1/data-import/runs?limit=500")
    assert resp.status_code == 422  # past the hard cap


async def test_run_detail_returns_the_bounded_error_sample(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo
) -> None:
    repo.by_id["run-1"] = _run_row(
        status="partial", rows_error=9_000,
        error_sample=[{"row": 3, "field": "volume", "value": "n/a", "reason": "not a number"}],
    )
    resp = await client.get("/api/v1/data-import/runs/run-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["errorSample"] == [
        {"row": 3, "field": "volume", "value": "n/a", "reason": "not a number"}
    ]
    assert body["errors"] == 9_000  # the true total, not the sample length


async def test_run_detail_404s_an_unknown_run(wired: FastAPI, client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/data-import/runs/nope")).status_code == 404


async def test_stats_emits_the_frozen_key_set(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo
) -> None:
    repo.stats = {"imports_30d": 18, "rows_mapped": 42_000, "rows_error": 3}
    resp = await client.get("/api/v1/data-import/stats")
    assert resp.json() == {"imports30d": 18, "rowsMapped": 42_000, "rowsError": 3}


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/data-import/runs",
        "/api/v1/data-import/runs/run-1",
        "/api/v1/data-import/workspace",
    ],
)
async def test_no_response_body_ever_carries_the_stored_path(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo, path: str
) -> None:
    """``stored_path`` is on every row the repo returns (``select *``), so the only thing
    keeping it off the wire is that each projection reads an explicit field list."""
    repo.runs = [_run_row()]
    repo.by_id["run-1"] = _run_row()
    resp = await client.get(path)
    assert resp.status_code == 200
    assert _SECRET_PATH not in resp.text
    assert "stored_path" not in resp.text
    assert "storedPath" not in resp.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/data-import/runs",
        "/api/v1/data-import/runs/run-1",
        "/api/v1/data-import/workspace",
    ],
)
async def test_no_response_body_ever_carries_the_client_id(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo, path: str
) -> None:
    repo.runs = [_run_row()]
    repo.by_id["run-1"] = _run_row()
    resp = await client.get(path)
    assert resp.status_code == 200
    assert _SECRET_CLIENT not in resp.text
    assert "client_id" not in resp.text
    assert "clientId" not in resp.text


async def test_the_upload_response_carries_neither_secret(
    wired: FastAPI, client: httpx.AsyncClient, repo: FakeImportRepo
) -> None:
    """The upload response is the one body built right beside the freshly-minted key, so
    it is the likeliest place for the path to slip out."""
    repo.client_names["cl-1"] = "NorthPeak Dental"
    resp = await client.post("/api/v1/data-import/uploads", **_upload(client_id="cl-1"))
    assert resp.status_code == 201, resp.text
    key = repo.created[0]["stored_path"]
    assert key not in resp.text
    assert "stored_path" not in resp.text
    assert "cl-1" not in resp.text
    assert resp.json()["run"]["file"] == "keywords.csv"
