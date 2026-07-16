"""Client-onboarding endpoints: the access gates + the wire contract.

No DB, no network, no vault: the repo is an in-memory fake injected through
``dependency_overrides``, the vault seal is a recorder, and the feature-grant lookup
(the one DB read inside ``require_feature``) is monkeypatched.

Three gates stack on every route, and each is pinned INDEPENDENTLY here - a test that
only ever checks the happy path would not notice one of them vanishing:

1. auth            - swept for the whole app by ``tests/test_route_auth_guard.py``;
                     re-pinned for this module's 9 routes below.
2. client_onboarding FEATURE grant - every route.
3. view_reports (reads) / manage_clients (every mutation).

Plus the two module-specific invariants, swept over EVERY route: the internal
``client_id`` never surfaces, and a POSTED SECRET NEVER COMES BACK.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.modules.client_onboarding.repo import get_onboarding_repo
from app.modules.client_onboarding.router import get_credential_sealer, get_milestone_advancer

pytestmark = pytest.mark.unit

_SECRET = "gbp-live-p@ssw0rd-9f2a"

_STEP_KEYS = {
    "id", "stepKey", "label", "client", "status", "owner", "ownerInit", "ownerColor",
    "due", "notes", "verified", "hasCredential", "sortOrder",
}
_RUN_KEYS = {
    "id", "client", "template", "status", "owner", "step", "stepStatus", "progress",
    "target", "steps",
}

# (method, path) for every route the module publishes.
_READ_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/v1/client-onboarding/runs"),
    ("GET", "/api/v1/client-onboarding/stats"),
    ("GET", "/api/v1/client-onboarding/workspace"),
    ("GET", "/api/v1/client-onboarding/steps"),
    ("GET", "/api/v1/client-onboarding/runs/run-1"),
]
_WRITE_ROUTES: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "/api/v1/client-onboarding/runs", {"clientId": "cl-secret"}),
    ("POST", "/api/v1/client-onboarding/runs/run-1/steps/st-1/advance", {"status": "completed"}),
    ("PATCH", "/api/v1/client-onboarding/runs/run-1/steps/st-1", {"notes": "called them"}),
    ("POST", "/api/v1/client-onboarding/runs/run-1/complete", {"force": True}),
]
_ALL_ROUTES = [(m, p) for m, p in _READ_ROUTES] + [(m, p) for m, p, _b in _WRITE_ROUTES]

# The staff roles that hold manage_clients (mirrors the 0040 RLS write policies).
_LEADS = ["owner", "admin", "manager"]
_NON_LEAD_STAFF = ["specialist", "analyst", "viewer"]

# A body that satisfies every write route at once (each ignores the keys it does not
# declare), so the gate sweeps can POST one payload everywhere.
_ANY_BODY: dict[str, Any] = {"clientId": "cl-secret", "status": "completed", "force": True}


def _message(resp: httpx.Response) -> str:
    """The rejection reason out of the app's global error envelope."""
    return str(resp.json()["error"]["message"])


def _step_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "st-1", "run_id": "run-1", "client_id": "cl-secret",
        "client_name": "Orchard Pediatrics", "step_key": "collect_gbp",
        "label": "Collect GBP access", "status": "pending", "owner_user_id": "u-1",
        "owner_name": "Sara Khan", "owner_init": "SK", "owner_color": "#7B69EE",
        "due_date": None, "notes": "", "verified": False, "vault_secret_id": None,
        "sort_order": 2,
    }
    row.update(over)
    return row


def _run_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "run-1", "client_id": "cl-secret", "client_name": "Orchard Pediatrics",
        "template_key": "local_seo_default", "status": "in_progress",
        "owner_user_id": "u-1", "owner_name": "Sara Khan", "target_date": None,
        "completed_at": None,
    }
    row.update(over)
    return row


class FakeRepo:
    """In-memory stand-in for the RLS-scoped OnboardingRepo."""

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.steps: dict[str, list[dict[str, Any]]] = {}
        self.board: list[dict[str, Any]] = []
        self.live: list[dict[str, Any]] = []
        self.stats: dict[str, Any] = {"in_onboarding": 0, "steps_pending": 0, "completed_30d": 0}
        self.client_names: dict[str, str] = {}
        self.staff: dict[str, dict[str, Any]] = {}
        self.active: dict[str, dict[str, Any]] = {}
        self.inserted: list[dict[str, Any]] = []
        self.run_updates: list[tuple[str, dict[str, Any]]] = []
        self.step_updates: list[tuple[str, str, dict[str, Any]]] = []
        self.seeded: list[dict[str, Any]] = []
        self.list_runs_kwargs: dict[str, Any] | None = None
        self.board_kwargs: dict[str, Any] | None = None
        self.steps_for_runs_ids: list[str] | None = None

    def list_runs(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_runs_kwargs = kwargs
        return list(self.runs.values())

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.runs.get(run_id)

    def active_run_for(self, client_id: str) -> dict[str, Any] | None:
        return self.active.get(client_id)

    def insert_run(self, **kwargs: Any) -> dict[str, Any] | None:
        self.inserted.append(kwargs)
        row = _run_row(
            id="run-new", client_id=kwargs["client_id"], client_name=kwargs["client_name"],
            template_key=kwargs["template_key"], owner_name=kwargs["owner_name"],
        )
        self.runs["run-new"] = row
        return row

    def update_run(self, run_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        self.run_updates.append((run_id, changes))
        row = self.runs.get(run_id)
        if row is None:
            return None
        row.update(changes)
        return row

    def list_steps(self, run_id: str) -> list[dict[str, Any]]:
        return list(self.steps.get(run_id, []))

    def steps_for_runs(self, run_ids: list[str]) -> list[dict[str, Any]]:
        self.steps_for_runs_ids = list(run_ids)
        return [row for rid in run_ids for row in self.steps.get(rid, [])]

    def list_board(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.board_kwargs = kwargs
        return list(self.board)

    def live_run_steps(self) -> list[dict[str, Any]]:
        return list(self.live)

    def get_step(self, run_id: str, step_id: str) -> dict[str, Any] | None:
        for row in self.steps.get(run_id, []):
            if row["id"] == step_id:
                return row
        return None

    def seed_steps(
        self, *, run_id: str, client_id: str, client_name: str, steps: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        self.seeded.append({"run_id": run_id, "steps": steps})
        rows = [
            _step_row(id=f"st-{i}", run_id=run_id, client_id=client_id,
                      client_name=client_name, **s)
            for i, s in enumerate(steps, start=1)
        ]
        self.steps.setdefault(run_id, []).extend(rows)
        return rows

    def update_step(
        self, run_id: str, step_id: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        self.step_updates.append((run_id, step_id, changes))
        row = self.get_step(run_id, step_id)
        if row is None:
            return None
        row.update(changes)
        return row

    def onboarding_stats(self) -> dict[str, Any]:
        return dict(self.stats)

    def client_name_for(self, client_id: str) -> str | None:
        return self.client_names.get(client_id)

    def staff_for(self, user_id: str) -> dict[str, Any] | None:
        return self.staff.get(user_id)


def _user(role: str, uid: str = "00000000-0000-0000-0000-0000000000a1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@aios.dev", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
        client_id="cl-A" if role == "client" else None,
    )


@pytest.fixture
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def sealed(app: FastAPI) -> list[dict[str, Any]]:
    """Recorder for the vault seal dep (never touches the real vault or a master key)."""
    calls: list[dict[str, Any]] = []

    def _seal(**kwargs: Any) -> str:
        calls.append(kwargs)
        return "vk-sealed-1"

    app.dependency_overrides[get_credential_sealer] = lambda: _seal
    return calls


@pytest.fixture
def advanced(app: FastAPI) -> list[tuple[str, str]]:
    """Recorder for the milestone hand-off dep."""
    calls: list[tuple[str, str]] = []

    def _advance(user_id: str, client_id: str) -> bool:
        calls.append((user_id, client_id))
        return True

    app.dependency_overrides[get_milestone_advancer] = lambda: _advance
    return calls


@pytest.fixture
def wire(
    app: FastAPI, repo: FakeRepo, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., None]:
    """Wire the fake repo + an identity + the caller's feature grants.

    ``require_feature`` loads grants from the DB; the loader is patched to an
    in-memory dict so the REAL ``feature_allows`` logic still runs, unstubbed.
    """
    app.dependency_overrides[get_onboarding_repo] = lambda: repo
    grants: dict[str, str] = {}
    monkeypatch.setattr("app.core.auth._load_feature_grants", lambda _uid: dict(grants))

    def _as(role: str, *, feature: bool = True) -> None:
        grants.clear()
        if feature:
            grants["client_onboarding"] = "full"
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


@pytest.fixture
def seeded(repo: FakeRepo) -> FakeRepo:
    """A repo carrying one live run + its (abbreviated) checklist."""
    repo.runs["run-1"] = _run_row()
    repo.steps["run-1"] = [
        _step_row(id="st-1", step_key="kickoff", label="Kickoff call & goals",
                  status="completed", sort_order=1),
        _step_row(id="st-2", step_key="collect_gbp", label="Collect GBP access",
                  status="pending", sort_order=2),
    ]
    repo.client_names = {"cl-secret": "Orchard Pediatrics"}
    repo.staff = {"u-2": {"name": "Ayesha Riaz", "avatar_color": "#4D8DF0"}}
    repo.stats = {"in_onboarding": 3, "steps_pending": 7, "completed_30d": 12}
    repo.board = list(repo.steps["run-1"])
    repo.live = list(repo.steps["run-1"])
    return repo


# --------------------------------------------------------------------------- #
# 1. Gate 1 - authentication.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_every_route_rejects_an_unauthenticated_caller(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    # No identity override + no bearer -> 401 before any repo/DB is touched.
    assert (await client.request(method, path)).status_code == 401


# --------------------------------------------------------------------------- #
# 2. Gate 2 - the client_onboarding FEATURE grant.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_every_route_requires_the_client_onboarding_feature(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    method: str, path: str
) -> None:
    # A manager holds BOTH view_reports and manage_clients, so an ungranted feature is
    # the only thing that can reject here.
    wire("manager", feature=False)
    resp = await client.request(method, path, json=_ANY_BODY)
    assert resp.status_code == 403, resp.text
    assert "client_onboarding" in _message(resp)


@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_owner_is_all_on_without_any_grant_row(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    sealed: list[Any], advanced: list[Any], method: str, path: str
) -> None:
    # Owner short-circuits require_feature (no grant lookup at all).
    wire("owner", feature=False)
    resp = await client.request(method, path, json=_ANY_BODY)
    assert resp.status_code != 403, resp.text


async def test_a_view_only_grant_does_not_satisfy_a_full_feature_requirement(
    app: FastAPI, client: httpx.AsyncClient, repo: FakeRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[get_onboarding_repo] = lambda: repo
    app.dependency_overrides[get_current_user] = lambda: _user("manager")
    monkeypatch.setattr(
        "app.core.auth._load_feature_grants", lambda _uid: {"client_onboarding": "view"}
    )
    resp = await client.get("/api/v1/client-onboarding/runs")
    assert resp.status_code == 403  # require_feature defaults to level="full"


# --------------------------------------------------------------------------- #
# 3. Gate 3 - view_reports on reads, manage_clients on writes.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _READ_ROUTES)
async def test_reads_require_view_reports(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    method: str, path: str
) -> None:
    """A portal client holds NO staff permission. It is granted the feature here on
    purpose: this pins view_reports as an INDEPENDENT gate, so the onboarding board
    stays closed to clients even if a grant row were somehow created for one - it
    enumerates which of that client's credentials the agency holds."""
    wire("client")
    resp = await client.request(method, path)
    assert resp.status_code == 403, resp.text
    assert "view_reports" in _message(resp)


@pytest.mark.parametrize("role", _NON_LEAD_STAFF)
@pytest.mark.parametrize(("method", "path", "body"), _WRITE_ROUTES)
async def test_mutations_require_manage_clients(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    sealed: list[Any], advanced: list[Any], role: str, method: str, path: str,
    body: dict[str, Any]
) -> None:
    """Every mutation is LEADS-only. This mirrors the 0040 RLS insert/update policies
    (``current_app_role() in ('owner','admin','manager')``) exactly: a role that passed
    this gate but failed RLS would get an opaque database error instead of a clean 403.
    """
    wire(role)
    resp = await client.request(method, path, json=body)
    assert resp.status_code == 403, f"{role} must not {method} {path}: {resp.text}"
    assert "manage_clients" in _message(resp)
    # ... and nothing was written, sealed, or handed to the lifecycle.
    assert seeded.inserted == [] and seeded.step_updates == [] and seeded.run_updates == []
    assert sealed == [] and advanced == []


@pytest.mark.parametrize("role", _NON_LEAD_STAFF)
async def test_non_lead_staff_may_still_read_the_board(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None], role: str
) -> None:
    # manage_clients gates the WRITES only - a specialist/analyst/viewer keeps the
    # read surface (RLS likewise lets any staff select).
    wire(role)
    assert (await client.get("/api/v1/client-onboarding/steps")).status_code == 200


@pytest.mark.parametrize("role", _LEADS)
@pytest.mark.parametrize(("method", "path", "body"), _WRITE_ROUTES)
async def test_leads_may_mutate(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    sealed: list[Any], advanced: list[Any], role: str, method: str, path: str,
    body: dict[str, Any]
) -> None:
    wire(role)
    resp = await client.request(method, path, json=body)
    assert resp.status_code in (200, 201), f"{role} must {method} {path}: {resp.text}"


# --------------------------------------------------------------------------- #
# 4. The internal client_id must NEVER surface.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_client_id_never_appears_in_any_response_body(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    sealed: list[Any], advanced: list[Any], method: str, path: str
) -> None:
    """Every fixture row carries the secret tenant id; no route may echo it back."""
    wire("owner")
    resp = await client.request(method, path, json=_ANY_BODY)
    assert resp.status_code in (200, 201), resp.text
    raw = resp.text
    assert "client_id" not in raw and "clientId" not in raw
    assert "cl-secret" not in raw  # not the key NOR the value


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/client-onboarding/runs", None),
        ("GET", "/api/v1/client-onboarding/steps", None),
        ("GET", "/api/v1/client-onboarding/runs/run-1", None),
        ("POST", "/api/v1/client-onboarding/runs", {"clientId": "cl-secret"}),
    ],
)
async def test_the_client_snapshot_name_is_what_replaces_the_hidden_id(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    """The other half of the contract: hiding ``client_id`` must not mean showing
    NOTHING - every route whose model carries ``client`` emits the display snapshot."""
    wire("owner")
    resp = await client.request(method, path, json=body)
    assert resp.status_code in (200, 201), resp.text
    payload = resp.json()
    row = payload[0] if isinstance(payload, list) else payload
    assert row["client"] == "Orchard Pediatrics"


# --------------------------------------------------------------------------- #
# 5. THE INVARIANT: a posted secret never comes back.
# --------------------------------------------------------------------------- #
async def test_a_posted_secret_never_appears_in_the_response(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    sealed: list[dict[str, Any]]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/client-onboarding/runs/run-1/steps/st-2/advance",
        json={"status": "completed",
              "credential": {"credentialLabel": "GBP manager login", "secret": _SECRET}},
    )
    assert resp.status_code == 200, resp.text
    assert _SECRET not in resp.text  # not the value...
    assert "secret" not in resp.text.lower()  # ... nor any key that could carry one
    # The ONLY thing the response says about the credential is that one now exists -
    # `hasCredential` is a boolean, deliberately not the secret and not its reference.
    assert resp.json()["hasCredential"] is True
    assert "vk-sealed-1" not in resp.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/client-onboarding/runs/run-1/steps/st-2/advance",
        "/api/v1/client-onboarding/runs/run-1/steps/st-2",
    ],
)
async def test_neither_write_verb_echoes_a_secret(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    sealed: list[dict[str, Any]], path: str
) -> None:
    # advance and PATCH share one write path on purpose - pin both doors anyway.
    wire("manager")
    method = "POST" if path.endswith("/advance") else "PATCH"
    resp = await client.request(
        method, path,
        json={"credential": {"credentialLabel": "CMS admin", "secret": _SECRET}},
    )
    assert resp.status_code == 200, resp.text
    assert _SECRET not in resp.text


async def test_the_secret_goes_to_the_vault_and_only_the_reference_to_the_step(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    sealed: list[dict[str, Any]]
) -> None:
    """The whole security shape of this module in one test: the plaintext reaches the
    vault seal and NOTHING ELSE; the step row receives only the returned reference."""
    wire("manager")
    resp = await client.post(
        "/api/v1/client-onboarding/runs/run-1/steps/st-2/advance",
        json={"credential": {"credentialLabel": "GBP manager login", "secret": _SECRET}},
    )
    assert resp.status_code == 200, resp.text
    # 1. The vault got the plaintext, labelled as a client credential.
    assert sealed[0]["secret"] == _SECRET
    assert sealed[0]["step_key"] == "collect_gbp"
    assert sealed[0]["credential_label"] == "GBP manager login"
    # 2. The step row got the REFERENCE and nothing resembling the secret.
    _run_id, _step_id, changes = seeded.step_updates[0]
    assert changes["vault_secret_id"] == "vk-sealed-1"
    assert _SECRET not in str(changes)
    assert "secret" not in changes
    # 3. The response says only that a credential exists.
    assert resp.json()["hasCredential"] is True


async def test_a_credential_is_rejected_for_a_non_collect_step(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    sealed: list[dict[str, Any]]
) -> None:
    """A credential offered for 'kickoff' is a caller error, not something to quietly
    seal under a misleading label."""
    wire("manager")
    resp = await client.post(
        "/api/v1/client-onboarding/runs/run-1/steps/st-1/advance",  # st-1 = kickoff
        json={"credential": {"credentialLabel": "x", "secret": _SECRET}},
    )
    assert resp.status_code == 400
    assert sealed == []  # nothing was sealed
    assert seeded.step_updates == []  # nothing was written


# --------------------------------------------------------------------------- #
# 6. THE INVARIANT: `verified` never flips automatically.
# --------------------------------------------------------------------------- #
async def test_collecting_a_credential_does_not_verify_it(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    sealed: list[dict[str, Any]]
) -> None:
    """The researched agency rule - "test every login". A collected credential is NOT
    a verified one: sealing proves a secret was TYPED, not that it WORKS."""
    wire("manager")
    resp = await client.post(
        "/api/v1/client-onboarding/runs/run-1/steps/st-2/advance",
        json={"status": "completed",
              "credential": {"credentialLabel": "GBP", "secret": _SECRET}},
    )
    assert resp.status_code == 200, resp.text
    _run_id, _step_id, changes = seeded.step_updates[0]
    assert "verified" not in changes  # the seal did NOT touch the flag
    assert resp.json()["verified"] is False


async def test_verified_flips_only_on_an_explicit_confirmation(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.patch(
        "/api/v1/client-onboarding/runs/run-1/steps/st-2", json={"verified": True}
    )
    assert resp.status_code == 200, resp.text
    _run_id, _step_id, changes = seeded.step_updates[0]
    assert changes == {"verified": True}
    assert resp.json()["verified"] is True


async def test_verified_can_be_revoked(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    # An access test that later stops working must be expressible.
    seeded.steps["run-1"][1]["verified"] = True
    wire("manager")
    resp = await client.patch(
        "/api/v1/client-onboarding/runs/run-1/steps/st-2", json={"verified": False}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["verified"] is False


async def test_completing_a_step_does_not_verify_it_either(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    await client.post(
        "/api/v1/client-onboarding/runs/run-1/steps/st-2/advance", json={"status": "completed"}
    )
    _run_id, _step_id, changes = seeded.step_updates[0]
    assert "verified" not in changes


# --------------------------------------------------------------------------- #
# 7. Reads: shapes, filters, pagination.
# --------------------------------------------------------------------------- #
async def test_list_runs_emits_exactly_the_frozen_key_set(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/client-onboarding/runs")
    assert resp.status_code == 200
    row = resp.json()[0]
    assert set(row) == _RUN_KEYS
    assert row["client"] == "Orchard Pediatrics"  # the snapshot, not the id
    assert row["step"] == "Collect GBP access"  # the derived current step
    assert row["progress"] == 50


async def test_list_steps_emits_exactly_the_frozen_key_set(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/client-onboarding/steps")
    assert resp.status_code == 200
    assert set(resp.json()[0]) == _STEP_KEYS


async def test_run_detail_carries_the_full_checklist(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/client-onboarding/runs/run-1")
    assert resp.status_code == 200
    assert len(resp.json()["steps"]) == 2


async def test_a_list_response_omits_the_full_checklist_but_keeps_the_derived_step(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    """Deriving the current step needs the checklist; SHIPPING 11 steps x 50 runs to
    render a board does not."""
    wire("viewer")
    row = (await client.get("/api/v1/client-onboarding/runs")).json()[0]
    assert row["steps"] == []
    assert row["step"] == "Collect GBP access"  # ... still derived


async def test_the_board_fetches_every_checklist_in_one_round_trip(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    """Two queries for the whole page, not one per run (mirrors the milestones board):
    an N+1 here would scale with the number of clients being onboarded."""
    seeded.runs["run-2"] = _run_row(id="run-2", client_name="Coastline Fit")
    seeded.steps["run-2"] = [_step_row(id="st-9", run_id="run-2", status="pending")]
    wire("viewer")
    resp = await client.get("/api/v1/client-onboarding/runs")
    assert resp.status_code == 200
    # ONE steps_for_runs call carrying BOTH run ids.
    assert seeded.steps_for_runs_ids == ["run-1", "run-2"]


async def test_run_detail_404_for_an_unknown_run(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    assert (await client.get("/api/v1/client-onboarding/runs/run-nope")).status_code == 404


async def test_stats_shape(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("analyst")
    resp = await client.get("/api/v1/client-onboarding/stats")
    assert resp.status_code == 200
    assert resp.json() == {"inOnboarding": 3, "stepsPending": 7, "completed30d": 12}


async def test_workspace_returns_the_tool_extra_shape(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/client-onboarding/workspace")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"kpis", "table", "primary", "bullets"}
    assert body["table"]["cols"] == ["Client", "Step", "Owner", "Status"]
    assert [k["label"] for k in body["kpis"]] == [
        "In onboarding", "Steps pending", "Completed (30d)"
    ]
    assert body["primary"] == {"label": "Start onboarding", "icon": "person_add"}


async def test_list_runs_honors_the_page_dep(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    await client.get("/api/v1/client-onboarding/runs", params={"limit": 5, "offset": 10})
    assert seeded.list_runs_kwargs is not None
    assert seeded.list_runs_kwargs["limit"] == 5 and seeded.list_runs_kwargs["offset"] == 10


async def test_list_runs_defaults_to_the_capped_page(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    await client.get("/api/v1/client-onboarding/runs")
    assert seeded.list_runs_kwargs is not None
    assert seeded.list_runs_kwargs["limit"] == 50 and seeded.list_runs_kwargs["offset"] == 0


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
async def test_lists_reject_an_out_of_range_page(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    params: dict[str, int]
) -> None:
    # The hard caps are enforced at the edge - no handler can ask for an unbounded page.
    wire("viewer")
    assert (
        await client.get("/api/v1/client-onboarding/steps", params=params)
    ).status_code == 422


async def test_the_board_passes_its_status_filter_through(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/client-onboarding/steps", params={"status": "pending"})
    assert resp.status_code == 200
    assert seeded.board_kwargs is not None
    assert seeded.board_kwargs["status"] == "pending"


async def test_filters_default_to_none_not_a_silent_narrowing(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    await client.get("/api/v1/client-onboarding/steps")
    await client.get("/api/v1/client-onboarding/runs")
    assert seeded.board_kwargs is not None and seeded.board_kwargs["status"] is None
    assert seeded.list_runs_kwargs is not None and seeded.list_runs_kwargs["status"] is None


@pytest.mark.parametrize(
    ("path", "bogus"),
    [
        ("/api/v1/client-onboarding/steps", "done"),
        ("/api/v1/client-onboarding/runs", "finished"),
    ],
)
async def test_lists_reject_an_off_enum_status_filter(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    path: str, bogus: str
) -> None:
    wire("viewer")
    assert (await client.get(path, params={"status": bogus})).status_code == 422


# --------------------------------------------------------------------------- #
# 8. Starting a run.
# --------------------------------------------------------------------------- #
async def test_create_run_seeds_the_eleven_step_template(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post("/api/v1/client-onboarding/runs", json={"clientId": "cl-secret"})
    assert resp.status_code == 201, resp.text
    assert len(seeded.seeded[0]["steps"]) == 11
    assert len(resp.json()["steps"]) == 11
    assert resp.json()["steps"][0]["label"] == "Kickoff call & goals"


async def test_create_run_snapshots_the_client_name(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post("/api/v1/client-onboarding/runs", json={"clientId": "cl-secret"})
    assert resp.status_code == 201, resp.text
    assert seeded.inserted[0]["client_name"] == "Orchard Pediatrics"  # resolved server-side
    assert resp.json()["client"] == "Orchard Pediatrics"


async def test_create_run_defaults_the_owner_to_the_actor(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    # Somebody is accountable from minute one - the person who started it, by default.
    wire("manager")
    await client.post("/api/v1/client-onboarding/runs", json={"clientId": "cl-secret"})
    assert seeded.inserted[0]["owner_name"] == "Op"
    assert seeded.inserted[0]["owner_user_id"] == "00000000-0000-0000-0000-0000000000a1"


async def test_create_run_snapshots_an_explicit_owner(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/client-onboarding/runs", json={"clientId": "cl-secret", "ownerUserId": "u-2"}
    )
    assert resp.status_code == 201, resp.text
    assert seeded.inserted[0]["owner_name"] == "Ayesha Riaz"  # resolved server-side


async def test_create_run_rejects_a_non_staff_owner(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    # staff_for excludes portal clients in SQL; an unknown/ineligible owner is a 404.
    wire("manager")
    resp = await client.post(
        "/api/v1/client-onboarding/runs", json={"clientId": "cl-secret", "ownerUserId": "u-nope"}
    )
    assert resp.status_code == 404
    assert seeded.inserted == []


async def test_create_run_unknown_client_is_404_and_writes_nothing(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post("/api/v1/client-onboarding/runs", json={"clientId": "cl-nope"})
    assert resp.status_code == 404
    assert seeded.inserted == []


async def test_create_run_is_409_when_the_client_is_already_onboarding(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    """One live run per client (the 0040 partial unique index): a second start is a
    clean conflict, never a duplicate checklist next to the real one."""
    seeded.active["cl-secret"] = _run_row()
    wire("manager")
    resp = await client.post("/api/v1/client-onboarding/runs", json={"clientId": "cl-secret"})
    assert resp.status_code == 409
    assert seeded.inserted == []


async def test_create_run_is_409_when_the_index_wins_the_race(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch
) -> None:
    # The app-side check races; the index cannot. A None insert is still a 409.
    monkeypatch.setattr(seeded, "insert_run", lambda **_k: None)
    wire("manager")
    resp = await client.post("/api/v1/client-onboarding/runs", json={"clientId": "cl-secret"})
    assert resp.status_code == 409


async def test_create_run_records_the_template_it_seeded_from(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    await client.post("/api/v1/client-onboarding/runs", json={"clientId": "cl-secret"})
    assert seeded.inserted[0]["template_key"] == "local_seo_default"


async def test_create_run_requires_a_client_id(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    assert (await client.post("/api/v1/client-onboarding/runs", json={})).status_code == 422


# --------------------------------------------------------------------------- #
# 9. Step edits.
# --------------------------------------------------------------------------- #
async def test_patch_sets_notes_and_due_date(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.patch(
        "/api/v1/client-onboarding/runs/run-1/steps/st-2",
        json={"notes": "left a voicemail", "dueDate": "2026-08-14"},
    )
    assert resp.status_code == 200, resp.text
    _r, _s, changes = seeded.step_updates[0]
    assert changes["notes"] == "left a voicemail"
    assert str(changes["due_date"]) == "2026-08-14"


async def test_advance_stamps_completed_at_with_the_status(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    """"When did this land?" must not have to be inferred from updated_at, which any
    later edit moves."""
    wire("manager")
    await client.post(
        "/api/v1/client-onboarding/runs/run-1/steps/st-2/advance", json={"status": "completed"}
    )
    _r, _s, changes = seeded.step_updates[0]
    assert changes["status"] == "completed"
    assert changes["completed_at"] is not None


async def test_moving_a_step_back_out_of_completed_clears_completed_at(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    await client.post(
        "/api/v1/client-onboarding/runs/run-1/steps/st-2/advance", json={"status": "blocked"}
    )
    _r, _s, changes = seeded.step_updates[0]
    assert changes["completed_at"] is None  # a stale timestamp would be a lie


async def test_patch_reassigns_and_resnapshots_the_owner(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.patch(
        "/api/v1/client-onboarding/runs/run-1/steps/st-2", json={"ownerUserId": "u-2"}
    )
    assert resp.status_code == 200, resp.text
    _r, _s, changes = seeded.step_updates[0]
    assert changes["owner_name"] == "Ayesha Riaz"
    assert changes["owner_init"] == "AR"  # derived server-side
    assert changes["owner_color"] == "#4D8DF0"
    assert resp.json()["owner"] == "Ayesha Riaz"


async def test_patch_null_owner_unassigns_the_step(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.patch(
        "/api/v1/client-onboarding/runs/run-1/steps/st-2", json={"ownerUserId": None}
    )
    assert resp.status_code == 200, resp.text
    _r, _s, changes = seeded.step_updates[0]
    # An explicit null UNASSIGNS (and clears the snapshot) - it is not "no change".
    assert changes == {
        "owner_user_id": None, "owner_name": "", "owner_init": "", "owner_color": ""
    }


async def test_patch_rejects_a_non_staff_owner(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.patch(
        "/api/v1/client-onboarding/runs/run-1/steps/st-2", json={"ownerUserId": "u-nope"}
    )
    assert resp.status_code == 404
    assert seeded.step_updates == []


async def test_patch_with_no_fields_is_400(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.patch("/api/v1/client-onboarding/runs/run-1/steps/st-2", json={})
    assert resp.status_code == 400
    assert seeded.step_updates == []


async def test_patch_unknown_step_is_404(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.patch(
        "/api/v1/client-onboarding/runs/run-1/steps/st-nope", json={"notes": "x"}
    )
    assert resp.status_code == 404
    assert seeded.step_updates == []


async def test_a_step_from_another_run_is_404_not_an_edit_to_the_wrong_client(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    """The run/step pair is validated together - a step id borrowed from another
    client's checklist must not be editable through this run's URL."""
    seeded.runs["run-2"] = _run_row(id="run-2", client_name="Coastline Fit")
    wire("manager")
    resp = await client.patch(
        "/api/v1/client-onboarding/runs/run-2/steps/st-2", json={"notes": "x"}
    )
    assert resp.status_code == 404
    assert seeded.step_updates == []


async def test_patch_rejects_an_off_enum_status(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.patch(
        "/api/v1/client-onboarding/runs/run-1/steps/st-2", json={"status": "done"}
    )
    assert resp.status_code == 422


async def test_patch_null_notes_normalises_to_empty(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    await client.patch("/api/v1/client-onboarding/runs/run-1/steps/st-2", json={"notes": None})
    _r, _s, changes = seeded.step_updates[0]
    # The column is NOT NULL with a '' default, so a null clears rather than writing NULL.
    assert changes == {"notes": ""}


# --------------------------------------------------------------------------- #
# 10. Completing a run.
# --------------------------------------------------------------------------- #
async def test_complete_refuses_while_steps_are_outstanding(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    advanced: list[Any]
) -> None:
    """"Onboarded" must mean the access is actually in hand - otherwise the whole
    module is decoration."""
    wire("manager")
    resp = await client.post("/api/v1/client-onboarding/runs/run-1/complete", json={})
    assert resp.status_code == 422
    assert "Collect GBP access" in resp.text  # it NAMES what is missing
    assert seeded.run_updates == [] and advanced == []


async def test_complete_succeeds_once_every_step_is_resolved(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    advanced: list[Any]
) -> None:
    for step in seeded.steps["run-1"]:
        step["status"] = "completed"
    wire("manager")
    resp = await client.post("/api/v1/client-onboarding/runs/run-1/complete", json={})
    assert resp.status_code == 200, resp.text
    _run_id, changes = seeded.run_updates[0]
    assert changes["status"] == "completed"
    assert changes["completed_at"] is not None
    assert resp.json()["status"] == "completed"


async def test_a_skipped_step_does_not_block_completion(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    advanced: list[Any]
) -> None:
    seeded.steps["run-1"][0]["status"] = "completed"
    seeded.steps["run-1"][1]["status"] = "skipped"  # deliberately not applicable
    wire("manager")
    assert (
        await client.post("/api/v1/client-onboarding/runs/run-1/complete", json={})
    ).status_code == 200


async def test_force_completes_an_unfinished_run(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    advanced: list[Any]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/client-onboarding/runs/run-1/complete", json={"force": True}
    )
    assert resp.status_code == 200, resp.text
    assert seeded.run_updates[0][1]["status"] == "completed"


async def test_complete_advances_the_milestone_lifecycle(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    advanced: list[tuple[str, str]]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/client-onboarding/runs/run-1/complete", json={"force": True}
    )
    assert resp.status_code == 200, resp.text
    # Handed off under the completing lead's identity, for the run's client.
    assert advanced == [("00000000-0000-0000-0000-0000000000a1", "cl-secret")]


async def test_a_milestone_failure_does_not_fail_the_completion(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE best-effort contract, end-to-end through the REAL service: a broken
    milestones layer must not fail a completion that has already happened.

    This deliberately does NOT override the advancer dep - it breaks the milestones
    repo underneath the real ``advance_onboarding_milestone``, so the swallow being
    tested is the production one rather than a fake standing in for it."""

    def _boom(_user_id: str) -> Any:
        raise RuntimeError("milestones pool is down")

    monkeypatch.setattr("app.db.milestones_repo.MilestonesRepo", _boom)
    wire("manager")
    resp = await client.post(
        "/api/v1/client-onboarding/runs/run-1/complete", json={"force": True}
    )
    assert resp.status_code == 200, resp.text  # the completion stands
    assert seeded.run_updates[0][1]["status"] == "completed"


async def test_complete_unknown_run_is_404(
    client: httpx.AsyncClient, seeded: FakeRepo, wire: Callable[..., None],
    advanced: list[Any]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/client-onboarding/runs/run-nope/complete", json={"force": True}
    )
    assert resp.status_code == 404
    assert seeded.run_updates == [] and advanced == []


# --------------------------------------------------------------------------- #
# 11. The client-create hook (the seam into app/routers/clients.py).
# --------------------------------------------------------------------------- #
class _FakeClientsRepo:
    """The minimum of ``ClientsRepo`` that POST /clients touches."""

    def __init__(self) -> None:
        self.clients: dict[str, dict[str, Any]] = {}

    def insert_client(self, row: dict[str, Any]) -> dict[str, Any]:
        record = {"id": "cl-new", **row}
        self.clients["cl-new"] = record
        return record

    def site_counts(self) -> dict[str, int]:
        return {}


@pytest.fixture
def clients_repo(app: FastAPI) -> _FakeClientsRepo:
    from app.db.clients_repo import get_clients_repo

    repo = _FakeClientsRepo()
    app.dependency_overrides[get_clients_repo] = lambda: repo
    app.dependency_overrides[get_current_user] = lambda: _user("manager")
    return repo


async def test_creating_a_client_seeds_its_onboarding_run(
    client: httpx.AsyncClient, clients_repo: _FakeClientsRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new client must not be able to exist without an activation checklist - that
    is how onboarding gets forgotten and how a client goes missing from the KPI."""
    seeds: list[tuple[str, str, str]] = []

    class _HookRepo(FakeRepo):
        def active_run_for(self, client_id: str) -> dict[str, Any] | None:
            return None

    hook_repo = _HookRepo()
    monkeypatch.setattr(
        "app.modules.client_onboarding.service.OnboardingRepo", lambda _uid: hook_repo
    )
    resp = await client.post("/api/v1/clients", json={"cn": "Verde Cafe"})
    assert resp.status_code == 201, resp.text
    # The run was opened for the NEW client, seeded from the code template.
    assert hook_repo.inserted[0]["client_id"] == "cl-new"
    assert hook_repo.inserted[0]["client_name"] == "Verde Cafe"
    assert len(hook_repo.seeded[0]["steps"]) == 11
    assert seeds == []  # (no stray writes)


async def test_the_seed_runs_under_the_creating_leads_identity(
    client: httpx.AsyncClient, clients_repo: _FakeClientsRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No BYPASSRLS: the 0040 insert policy applies exactly as for a manual start.
    bound: list[str] = []

    def _factory(user_id: str) -> FakeRepo:
        bound.append(user_id)
        return FakeRepo()

    monkeypatch.setattr("app.modules.client_onboarding.service.OnboardingRepo", _factory)
    await client.post("/api/v1/clients", json={"cn": "Verde Cafe"})
    assert bound == ["00000000-0000-0000-0000-0000000000a1"]


async def test_a_seeding_failure_still_creates_the_client(
    client: httpx.AsyncClient, clients_repo: _FakeClientsRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE best-effort contract, through the REAL service: the client was already
    written and acknowledged, so failing the creation because a convenience
    side-effect failed would be strictly worse than a missing run a lead can start by
    hand (mirrors ``record_activity``'s never-raise discipline).

    This breaks the layer UNDERNEATH the hook rather than stubbing the hook itself, so
    the swallow under test is the production one."""

    def _boom(_uid: str) -> Any:
        raise RuntimeError("db pool is down")

    monkeypatch.setattr("app.modules.client_onboarding.service.OnboardingRepo", _boom)
    resp = await client.post("/api/v1/clients", json={"cn": "Verde Cafe"})
    assert resp.status_code == 201, resp.text  # the client stands
    assert resp.json()["cn"] == "Verde Cafe"
    assert len(clients_repo.clients) == 1


async def test_a_client_create_never_seeds_a_second_live_run(
    client: httpx.AsyncClient, clients_repo: _FakeClientsRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook_repo = FakeRepo()
    hook_repo.active["cl-new"] = _run_row()
    monkeypatch.setattr(
        "app.modules.client_onboarding.service.OnboardingRepo", lambda _uid: hook_repo
    )
    resp = await client.post("/api/v1/clients", json={"cn": "Verde Cafe"})
    assert resp.status_code == 201, resp.text
    assert hook_repo.inserted == []  # nothing next to the live run
