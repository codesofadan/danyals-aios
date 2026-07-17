"""Billing endpoints: the access gates + the wire contract.

No DB, no network, no Celery: the repo is an in-memory fake injected through
``dependency_overrides`` and the feature-grant lookup (the one DB read inside
``require_feature``) is monkeypatched.

Three gates stack on every route, and each is pinned INDEPENDENTLY here - a test that
only ever checks the happy path would not notice one of them vanishing:

1. auth        - swept for the whole app by ``tests/test_route_auth_guard.py``;
                 re-pinned for this module's routes below.
2. billing FEATURE grant - every route.
3. view_reports (reads) / the OWNER-ADMIN role (every mutation).

Gate 3 is the one worth reading twice. Every OTHER module writes with the LEADS set
(owner/admin/manager); billing deliberately does NOT. A manager may run delivery
without being able to issue or settle money, and
``test_a_manager_is_forbidden_from_every_mutation`` is the test that keeps it that way.
It mirrors the ``0043`` RLS write policies exactly.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.modules.billing.repo import get_billing_repo

pytestmark = pytest.mark.unit

_INVOICE_KEYS = {
    "number", "client", "amount", "subtotal", "tax", "currency", "status", "kind",
    "issued", "due", "periodStart", "periodEnd", "notes", "paidAt", "paidMethod",
}
_DETAIL_KEYS = _INVOICE_KEYS | {"lines"}

# (method, path) for every route the module publishes.
_READ_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/v1/billing/invoices"),
    ("GET", "/api/v1/billing/stats"),
    ("GET", "/api/v1/billing/workspace"),
    ("GET", "/api/v1/billing/revenue"),
    ("GET", "/api/v1/billing/invoices/INV-0001"),
]
_WRITE_ROUTES: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "/api/v1/billing/invoices", {"clientId": "cl-secret"}),
    ("PATCH", "/api/v1/billing/invoices/INV-0001", {"notes": "x"}),
    ("POST", "/api/v1/billing/invoices/INV-0001/lines", {"description": "x"}),
    ("DELETE", "/api/v1/billing/invoices/INV-0001/lines/li-1", {}),
    ("POST", "/api/v1/billing/invoices/INV-0001/finalize", {}),
    ("POST", "/api/v1/billing/invoices/INV-0001/mark-paid", {}),
    ("POST", "/api/v1/billing/invoices/INV-0001/void", {}),
    ("POST", "/api/v1/billing/invoices/INV-0001/refund", {}),
]
_ALL_ROUTES = [(m, p) for m, p in _READ_ROUTES] + [(m, p) for m, p, _b in _WRITE_ROUTES]

# The ONLY roles that may touch money (mirrors the 0043 RLS write policies).
_FINANCE = ["owner", "admin"]
# Everyone else - note `manager` is here, NOT in _FINANCE. That is the deliberate
# departure from every other module's owner/admin/manager write set.
_NON_FINANCE_STAFF = ["manager", "specialist", "analyst", "viewer"]


def _message(resp: httpx.Response) -> str:
    """The rejection reason out of the app's global error envelope.

    Every raised ``HTTPException`` is rendered by ``install_error_handlers`` as
    ``{"error": {"type", "message", "request_id"}}`` (invariant #5) - there is no
    top-level ``detail`` key on this app.
    """
    return str(resp.json()["error"]["message"])


def _invoice_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-00000000beef",
        "number": "INV-0001",
        "client_id": "cl-secret",
        "client_name": "Meridian Wealth",
        "status": "draft",
        "kind": "retainer",
        "currency": "USD",
        "issue_date": None,
        "due_date": "2026-08-27",
        "period_start": None,
        "period_end": None,
        "subtotal": Decimal("1400.00"),
        "tax": Decimal("90.00"),
        "total": Decimal("1490.00"),
        "notes": "",
        "paid_at": None,
        "paid_method": "",
    }
    row.update(over)
    return row


def _line_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "li-1", "description": "Growth retainer", "quantity": Decimal("1.00"),
        "unit_amount": Decimal("1400.00"), "line_total": Decimal("1400.00"),
        "sort_order": 0,
    }
    row.update(over)
    return row


class FakeBillingRepo:
    """In-memory stand-in for the RLS-scoped BillingRepo."""

    def __init__(self) -> None:
        self.invoices: list[dict[str, Any]] = []
        self.by_number: dict[str, dict[str, Any]] = {}
        self.lines: dict[str, list[dict[str, Any]]] = {}
        self.client_names: dict[str, str] = {}
        self.mrr = 0
        self.counts = {"open_invoices": 0, "past_due": 0}
        self.revenue: list[dict[str, Any]] = []
        self.list_kwargs: dict[str, Any] | None = None
        self.revenue_kwargs: dict[str, Any] | None = None
        self.created: list[dict[str, Any]] = []
        self.updates: list[tuple[str, dict[str, Any], str]] = []
        self.added_lines: list[tuple[str, list[dict[str, Any]]]] = []
        self.deleted_lines: list[tuple[str, str]] = []
        # Set to make update_invoice return None (the racing-transition path).
        self.conflict = False

    # --- reads ---
    def list_invoices(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_kwargs = kwargs
        return list(self.invoices)

    def get_by_number(self, number: str) -> dict[str, Any] | None:
        return self.by_number.get(number)

    def lines_for(self, invoice_id: str) -> list[dict[str, Any]]:
        return list(self.lines.get(invoice_id, []))

    def subscription_mrr(self) -> int:
        return self.mrr

    def invoice_counts(self) -> dict[str, int]:
        return dict(self.counts)

    def client_name_for(self, client_id: str) -> str | None:
        return self.client_names.get(client_id)

    def revenue_by_period(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.revenue_kwargs = kwargs
        return list(self.revenue)

    # --- mutations ---
    def create_invoice(self, values: dict[str, Any]) -> dict[str, Any] | None:
        self.created.append(values)
        row = _invoice_row(**{k: v for k, v in values.items() if k != "created_by"})
        # A DISTINCT number + id: the DB mints both, and reusing the seeded
        # invoice's id here would let its line items bleed into a new invoice's
        # totals and quietly invalidate every create-total assertion below.
        row["number"] = "INV-0002"
        row["id"] = "00000000-0000-0000-0000-00000000cafe"
        self.by_number["INV-0002"] = row
        return row

    def update_invoice(
        self, number: str, changes: dict[str, Any], expected_status: str
    ) -> dict[str, Any] | None:
        self.updates.append((number, changes, expected_status))
        if self.conflict:
            return None
        row = self.by_number.get(number)
        if row is None or row.get("status") != expected_status:
            return None
        row.update(changes)
        return row

    def set_totals(self, number: str, **totals: Any) -> dict[str, Any] | None:
        return self.update_invoice(number, dict(totals), "draft")

    def add_lines(self, invoice_id: str, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.added_lines.append((invoice_id, lines))
        self.lines.setdefault(invoice_id, []).extend(lines)
        return list(self.lines[invoice_id])

    def delete_line(self, invoice_id: str, line_id: str) -> bool:
        self.deleted_lines.append((invoice_id, line_id))
        existing = self.lines.get(invoice_id, [])
        remaining = [line for line in existing if line.get("id") != line_id]
        self.lines[invoice_id] = remaining
        return len(remaining) != len(existing)


def _user(role: str, uid: str = "00000000-0000-0000-0000-0000000000a1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@aios.dev", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
        client_id="cl-A" if role == "client" else None,
    )


@pytest.fixture
def repo() -> FakeBillingRepo:
    return FakeBillingRepo()


@pytest.fixture
def wire(
    app: FastAPI, repo: FakeBillingRepo, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., None]:
    """Wire the fake repo + an identity + the caller's feature grants.

    ``require_feature`` loads grants from the DB; the loader is patched to an
    in-memory dict so the REAL ``feature_allows`` logic still runs, unstubbed.
    """
    app.dependency_overrides[get_billing_repo] = lambda: repo
    grants: dict[str, str] = {}
    monkeypatch.setattr("app.core.auth._load_feature_grants", lambda _uid: dict(grants))

    def _as(role: str, *, feature: bool = True) -> None:
        grants.clear()
        if feature:
            grants["billing"] = "full"
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


@pytest.fixture
def seeded(repo: FakeBillingRepo) -> FakeBillingRepo:
    """A draft invoice with one line, addressable as INV-0001."""
    row = _invoice_row()
    repo.by_number["INV-0001"] = row
    repo.lines[str(row["id"])] = [_line_row()]
    repo.client_names = {"cl-secret": "Meridian Wealth"}
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
# 2. Gate 2 - the billing FEATURE grant.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_every_route_requires_the_billing_feature(
    client: httpx.AsyncClient, wire: Callable[..., None], method: str, path: str
) -> None:
    # An admin holds BOTH view_reports and the finance role, so an ungranted feature
    # is the only thing that can reject here.
    wire("admin", feature=False)
    resp = await client.request(method, path, json={"clientId": "cl-secret"})
    assert resp.status_code == 403, resp.text
    assert "billing" in _message(resp)


@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_owner_is_all_on_without_any_grant_row(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None],
    method: str, path: str
) -> None:
    # Owner short-circuits require_feature (no grant lookup at all).
    wire("owner", feature=False)
    resp = await client.request(method, path, json={"clientId": "cl-secret"})
    assert resp.status_code != 403, resp.text


async def test_a_view_only_grant_does_not_satisfy_a_full_feature_requirement(
    app: FastAPI, client: httpx.AsyncClient, repo: FakeBillingRepo,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[get_billing_repo] = lambda: repo
    app.dependency_overrides[get_current_user] = lambda: _user("admin")
    monkeypatch.setattr(
        "app.core.auth._load_feature_grants", lambda _uid: {"billing": "view"}
    )
    resp = await client.get("/api/v1/billing/invoices")
    assert resp.status_code == 403  # require_feature defaults to level="full"


# --------------------------------------------------------------------------- #
# 3. Gate 3 - view_reports on reads; OWNER/ADMIN on every mutation.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _READ_ROUTES)
async def test_reads_require_view_reports(
    client: httpx.AsyncClient, wire: Callable[..., None], method: str, path: str
) -> None:
    # A portal client holds NO staff permission. It is granted the feature here on
    # purpose: this pins view_reports as an INDEPENDENT gate, so the read surface
    # stays closed to clients even if a grant row were somehow created for one.
    wire("client")
    resp = await client.request(method, path)
    assert resp.status_code == 403, resp.text
    assert "view_reports" in _message(resp)


@pytest.mark.parametrize(("method", "path", "body"), _WRITE_ROUTES)
async def test_a_manager_is_forbidden_from_every_mutation(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None],
    method: str, path: str, body: dict[str, Any]
) -> None:
    """THE billing-specific access rule: a manager may NOT touch money.

    Every other module lets the LEADS (owner/admin/manager) write. Billing does not:
    a delivery manager can run the work without being able to issue an invoice, mark
    one paid, or void one. This mirrors the ``0043`` RLS write policies
    (``current_app_role() in ('owner','admin')``) exactly - a manager who passed the
    app gate would only be rejected by Postgres with an opaque RLS error instead of a
    clean 403.

    A manager holds view_reports and is granted the feature here, so the ROLE is the
    only thing that can reject - this cannot pass for the wrong reason.
    """
    wire("manager")
    resp = await client.request(method, path, json=body)
    assert resp.status_code == 403, f"a manager must not {method} {path}: {resp.text}"
    assert "role" in _message(resp).lower()
    # ... and nothing was written on the way to being rejected.
    assert seeded.created == [] and seeded.updates == []
    assert seeded.added_lines == [] and seeded.deleted_lines == []


@pytest.mark.parametrize("role", _NON_FINANCE_STAFF)
@pytest.mark.parametrize(("method", "path", "body"), _WRITE_ROUTES)
async def test_no_non_finance_role_may_mutate(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None],
    role: str, method: str, path: str, body: dict[str, Any]
) -> None:
    wire(role)
    resp = await client.request(method, path, json=body)
    assert resp.status_code == 403, f"{role} must not {method} {path}: {resp.text}"
    assert seeded.created == [] and seeded.updates == []


@pytest.mark.parametrize("role", _NON_FINANCE_STAFF)
async def test_non_finance_staff_may_still_read_the_ledger(
    client: httpx.AsyncClient, repo: FakeBillingRepo, wire: Callable[..., None], role: str
) -> None:
    # The role gate covers the WRITES only - a manager/specialist/analyst/viewer keeps
    # the read surface (RLS likewise lets any staff select).
    repo.invoices = [_invoice_row()]
    wire(role)
    assert (await client.get("/api/v1/billing/invoices")).status_code == 200


@pytest.mark.parametrize("role", _FINANCE)
@pytest.mark.parametrize(("method", "path", "body"), _WRITE_ROUTES)
async def test_owner_and_admin_may_mutate(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None],
    role: str, method: str, path: str, body: dict[str, Any]
) -> None:
    wire(role)
    resp = await client.request(method, path, json=body)
    # 409 is a legitimate outcome for a lifecycle route against a draft (e.g.
    # mark-paid); what must NOT happen is a 403.
    assert resp.status_code != 403, f"{role} must be allowed to {method} {path}: {resp.text}"


# --------------------------------------------------------------------------- #
# 4. The internal client_id must NEVER surface.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_client_id_never_appears_in_any_response_body(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None],
    method: str, path: str
) -> None:
    """Every fixture row carries the secret tenant id; no route may echo it back."""
    seeded.invoices = [_invoice_row()]
    seeded.mrr = 28_400
    seeded.counts = {"open_invoices": 3, "past_due": 1}
    seeded.revenue = [{"period": "2026-07", "invoices": 4, "collected": Decimal("5960")}]
    wire("owner")
    # One body that every route accepts: `clientId` for the create, `notes` for the
    # patch, `description` for the line add. 409 is legal for a lifecycle route that
    # cannot move a draft (mark-paid / refund) - what matters is that the response,
    # whatever it is, never echoes the tenant id.
    resp = await client.request(
        method, path, json={"clientId": "cl-secret", "notes": "x", "description": "x"}
    )
    assert resp.status_code in (200, 201, 409), resp.text
    raw = resp.text
    assert "client_id" not in raw and "clientId" not in raw
    assert "cl-secret" not in raw  # not the key NOR the value


async def test_the_client_snapshot_name_is_what_replaces_the_hidden_id(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    """The other half of the contract: hiding ``client_id`` must not mean showing
    NOTHING - the invoice carries the display snapshot."""
    seeded.invoices = [_invoice_row()]
    wire("owner")
    resp = await client.get("/api/v1/billing/invoices")
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["client"] == "Meridian Wealth"


async def test_list_emits_exactly_the_frozen_key_set(
    client: httpx.AsyncClient, repo: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    repo.invoices = [_invoice_row()]
    wire("viewer")
    resp = await client.get("/api/v1/billing/invoices")
    assert resp.status_code == 200
    row = resp.json()[0]
    assert set(row) == _INVOICE_KEYS
    assert row["number"] == "INV-0001"  # the public id, never the uuid
    assert "beef" not in resp.text


async def test_the_detail_emits_the_header_plus_lines(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/billing/invoices/INV-0001")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == _DETAIL_KEYS
    assert len(body["lines"]) == 1
    assert body["lines"][0]["lineTotal"] == 1400.0


# --------------------------------------------------------------------------- #
# 5. Reads: filters, pagination, the stats split.
# --------------------------------------------------------------------------- #
async def test_list_honors_the_page_dep(
    client: httpx.AsyncClient, repo: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/billing/invoices", params={"limit": 5, "offset": 10})
    assert resp.status_code == 200
    assert repo.list_kwargs is not None
    assert repo.list_kwargs["limit"] == 5 and repo.list_kwargs["offset"] == 10


async def test_list_defaults_to_the_capped_page(
    client: httpx.AsyncClient, repo: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    await client.get("/api/v1/billing/invoices")
    assert repo.list_kwargs is not None
    assert repo.list_kwargs["limit"] == 50 and repo.list_kwargs["offset"] == 0


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
async def test_list_rejects_an_out_of_range_page(
    client: httpx.AsyncClient, wire: Callable[..., None], params: dict[str, int]
) -> None:
    wire("viewer")
    assert (await client.get("/api/v1/billing/invoices", params=params)).status_code == 422


async def test_list_passes_every_filter_through_to_the_repo(
    client: httpx.AsyncClient, repo: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get(
        "/api/v1/billing/invoices",
        params={"clientId": "cl-1", "status": "past_due", "kind": "one_off"},
    )
    assert resp.status_code == 200
    assert repo.list_kwargs is not None
    assert repo.list_kwargs["client_id"] == "cl-1"
    assert repo.list_kwargs["status"] == "past_due"
    assert repo.list_kwargs["kind"] == "one_off"


async def test_list_filters_default_to_none_not_a_silent_narrowing(
    client: httpx.AsyncClient, repo: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    await client.get("/api/v1/billing/invoices")
    assert repo.list_kwargs is not None
    for key in ("client_id", "status", "kind"):
        assert repo.list_kwargs[key] is None


@pytest.mark.parametrize("params", [{"status": "chargeback"}, {"kind": "subscription"}])
async def test_list_rejects_an_off_enum_filter(
    client: httpx.AsyncClient, wire: Callable[..., None], params: dict[str, str]
) -> None:
    wire("viewer")
    assert (await client.get("/api/v1/billing/invoices", params=params)).status_code == 422


async def test_stats_reads_mrr_from_the_subscription_table_not_the_ledger(
    client: httpx.AsyncClient, repo: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    """The module's load-bearing rule, pinned at the route edge.

    The fake's ledger holds a 1490 invoice; its subscription MRR is 28,400. The route
    must report the subscription number - it calls ``subscription_mrr`` (a
    ``clients.mrr`` read), never a sum over ``invoices``.
    """
    repo.mrr = 28_400
    repo.counts = {"open_invoices": 3, "past_due": 1}
    repo.invoices = [_invoice_row()]
    wire("analyst")
    resp = await client.get("/api/v1/billing/stats")
    assert resp.status_code == 200
    assert resp.json() == {"mrr": 28_400, "openInvoices": 3, "pastDue": 1}


async def test_workspace_returns_the_tool_extra_shape(
    client: httpx.AsyncClient, repo: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    repo.mrr = 28_400
    repo.counts = {"open_invoices": 3, "past_due": 1}
    repo.invoices = [_invoice_row(status="paid")]
    wire("viewer")
    resp = await client.get("/api/v1/billing/workspace")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"kpis", "table", "primary", "bullets"}
    assert body["table"]["cols"] == ["Client", "Amount", "Due", "Status"]
    assert [k["label"] for k in body["kpis"]] == ["MRR", "Open invoices", "Past due"]
    assert body["primary"] == {"label": "New invoice", "icon": "payments"}


async def test_workspace_asks_the_repo_for_only_the_top_eight(
    client: httpx.AsyncClient, repo: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    await client.get("/api/v1/billing/workspace")
    assert repo.list_kwargs == {"limit": 8, "offset": 0}


async def test_revenue_reports_collected_cash_by_period(
    client: httpx.AsyncClient, repo: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    repo.revenue = [
        {"period": "2026-07", "invoices": 4, "collected": Decimal("5960.00")},
        {"period": "2026-06", "invoices": 3, "collected": Decimal("4470.00")},
    ]
    wire("viewer")
    resp = await client.get("/api/v1/billing/revenue", params={"clientId": "cl-1", "months": 6})
    assert resp.status_code == 200, resp.text
    assert repo.revenue_kwargs == {"client_id": "cl-1", "limit": 6}
    assert resp.json() == [
        {"period": "2026-07", "invoices": 4, "collected": 5960.0},
        {"period": "2026-06", "invoices": 3, "collected": 4470.0},
    ]


async def test_revenue_is_not_the_mrr_number(
    client: httpx.AsyncClient, repo: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    # Two different questions, two different endpoints, two different tables. An
    # operator will expect these to match; they must not be wired to.
    repo.mrr = 28_400
    repo.revenue = [{"period": "2026-07", "invoices": 4, "collected": Decimal("5960.00")}]
    wire("owner")
    revenue = (await client.get("/api/v1/billing/revenue")).json()
    stats = (await client.get("/api/v1/billing/stats")).json()
    assert revenue[0]["collected"] == 5960.0
    assert stats["mrr"] == 28_400  # untouched by the ledger


async def test_revenue_rejects_an_out_of_range_window(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")
    assert (await client.get("/api/v1/billing/revenue", params={"months": 0})).status_code == 422
    assert (await client.get("/api/v1/billing/revenue", params={"months": 61})).status_code == 422


async def test_an_unknown_invoice_is_404(
    client: httpx.AsyncClient, repo: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("owner")
    assert (await client.get("/api/v1/billing/invoices/INV-9999")).status_code == 404


# --------------------------------------------------------------------------- #
# 6. Create: the draft + the server-computed totals.
# --------------------------------------------------------------------------- #
async def test_create_snapshots_the_client_name_and_opens_a_draft(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("admin")
    resp = await client.post(
        "/api/v1/billing/invoices",
        json={"clientId": "cl-secret", "kind": "one_off", "dueDate": "2026-08-27"},
    )
    assert resp.status_code == 201, resp.text
    created = seeded.created[0]
    assert created["client_name"] == "Meridian Wealth"  # resolved server-side
    assert created["client_id"] == "cl-secret"
    assert created["status"] == "draft"  # ALWAYS a draft, never issued on create
    assert created["created_by"] == "00000000-0000-0000-0000-0000000000a1"


async def test_create_computes_the_total_from_the_lines_and_tax(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("admin")
    resp = await client.post(
        "/api/v1/billing/invoices",
        json={
            "clientId": "cl-secret", "tax": 90,
            "lines": [
                {"description": "Retainer", "quantity": 1, "unitAmount": 1000},
                {"description": "Extra pages", "quantity": 2, "unitAmount": 200},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    # The lines the server persisted carry server-computed line totals...
    _invoice_id, lines = seeded.added_lines[0]
    assert [line["line_total"] for line in lines] == [Decimal("1000.00"), Decimal("400.00")]
    # ... and the invoice total is their sum plus tax.
    _number, changes, expected = seeded.updates[-1]
    assert expected == "draft"
    assert changes["subtotal"] == Decimal("1400.00")
    assert changes["total"] == Decimal("1490.00")


async def test_a_client_supplied_total_is_never_written(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    """A caller POSTing a total gets the SERVER's total, not theirs.

    The field does not exist on ``InvoiceCreate`` (``test_schemas`` pins that), so the
    value is dropped at validation - this asserts the whole route end-to-end: nothing
    the caller sent for `total` reaches the repo.
    """
    wire("admin")
    resp = await client.post(
        "/api/v1/billing/invoices",
        json={
            "clientId": "cl-secret", "total": 999_999, "subtotal": 999_999, "amount": 999_999,
            "lines": [{"description": "Retainer", "quantity": 1, "unitAmount": 1000,
                       "lineTotal": 999_999}],
        },
    )
    assert resp.status_code == 201, resp.text
    assert "999999" not in resp.text
    _invoice_id, lines = seeded.added_lines[0]
    assert lines[0]["line_total"] == Decimal("1000.00")  # computed, not supplied
    _number, changes, _expected = seeded.updates[-1]
    assert changes["total"] == Decimal("1000.00")


async def test_create_without_lines_is_a_zero_draft(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("admin")
    resp = await client.post("/api/v1/billing/invoices", json={"clientId": "cl-secret"})
    assert resp.status_code == 201, resp.text
    assert seeded.added_lines == []  # no pointless empty insert
    _number, changes, _expected = seeded.updates[-1]
    assert changes["total"] == Decimal("0.00")


async def test_create_with_an_unknown_client_is_404_and_writes_nothing(
    client: httpx.AsyncClient, repo: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("admin")  # no client_names registered -> invisible/unknown
    resp = await client.post("/api/v1/billing/invoices", json={"clientId": "cl-nope"})
    assert resp.status_code == 404
    assert repo.created == []


async def test_create_requires_a_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("admin")
    assert (await client.post("/api/v1/billing/invoices", json={})).status_code == 422


# --------------------------------------------------------------------------- #
# 7. Patch: DRAFT ONLY.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("issued", ["open", "paid", "past_due", "void", "refunded"])
async def test_patching_a_non_draft_invoice_is_409(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None], issued: str
) -> None:
    """An issued invoice is a document the client has seen - it is frozen.

    The ``0043`` trigger enforces the same freeze at the DB; this 409 is the clean
    answer the API gives first. Correcting an issued invoice means voiding it and
    re-issuing, never editing it.
    """
    seeded.by_number["INV-0001"]["status"] = issued
    wire("admin")
    resp = await client.patch("/api/v1/billing/invoices/INV-0001", json={"notes": "sneaky"})
    assert resp.status_code == 409, resp.text
    assert "draft" in _message(resp).lower()
    assert seeded.updates == []  # nothing was written


async def test_patching_a_draft_updates_it(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("admin")
    resp = await client.patch(
        "/api/v1/billing/invoices/INV-0001", json={"notes": "July retainer", "kind": "one_off"}
    )
    assert resp.status_code == 200, resp.text
    number, changes, expected = seeded.updates[0]
    assert number == "INV-0001" and expected == "draft"
    assert changes == {"notes": "July retainer", "kind": "one_off"}


async def test_patching_the_tax_recomputes_the_total(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("admin")
    resp = await client.patch("/api/v1/billing/invoices/INV-0001", json={"tax": 100})
    assert resp.status_code == 200, resp.text
    # The line is 1400; the new tax is 100 -> the total must follow, not stay at 1490.
    _number, changes, _expected = seeded.updates[-1]
    assert changes["subtotal"] == Decimal("1400.00")
    assert changes["total"] == Decimal("1500.00")


async def test_patch_with_no_fields_is_400(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("admin")
    resp = await client.patch("/api/v1/billing/invoices/INV-0001", json={})
    assert resp.status_code == 400
    assert seeded.updates == []


async def test_patch_of_an_unknown_invoice_is_404(
    client: httpx.AsyncClient, repo: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("admin")
    resp = await client.patch("/api/v1/billing/invoices/INV-9999", json={"notes": "x"})
    assert resp.status_code == 404
    assert repo.updates == []


# --------------------------------------------------------------------------- #
# 8. Lines: draft-only, totals recomputed.
# --------------------------------------------------------------------------- #
async def test_adding_a_line_recomputes_the_total(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("admin")
    resp = await client.post(
        "/api/v1/billing/invoices/INV-0001/lines",
        json={"description": "Extra", "quantity": 2, "unitAmount": 250},
    )
    assert resp.status_code == 201, resp.text
    _invoice_id, lines = seeded.added_lines[0]
    assert lines[0]["line_total"] == Decimal("500.00")  # 2 x 250, computed here
    # subtotal = the existing 1400 line + the new 500; total adds the 90 tax.
    _number, changes, _expected = seeded.updates[-1]
    assert changes["subtotal"] == Decimal("1900.00")
    assert changes["total"] == Decimal("1990.00")


async def test_deleting_a_line_recomputes_the_total(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("admin")
    resp = await client.delete("/api/v1/billing/invoices/INV-0001/lines/li-1")
    assert resp.status_code == 200, resp.text
    assert seeded.deleted_lines == [("00000000-0000-0000-0000-00000000beef", "li-1")]
    # The only line is gone -> subtotal 0, total = the 90 tax.
    _number, changes, _expected = seeded.updates[-1]
    assert changes["subtotal"] == Decimal("0.00")
    assert changes["total"] == Decimal("90.00")
    assert resp.json()["lines"] == []


@pytest.mark.parametrize("issued", ["open", "paid", "past_due", "void", "refunded"])
async def test_line_mutations_on_a_non_draft_are_409(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None], issued: str
) -> None:
    # The lines ARE the billed amount - editing them on an issued invoice would change
    # what was billed. 0043's line guard enforces the same rule at the DB.
    seeded.by_number["INV-0001"]["status"] = issued
    wire("admin")
    add = await client.post(
        "/api/v1/billing/invoices/INV-0001/lines", json={"description": "x"}
    )
    remove = await client.delete("/api/v1/billing/invoices/INV-0001/lines/li-1")
    assert add.status_code == 409 and remove.status_code == 409
    assert seeded.added_lines == [] and seeded.deleted_lines == []


async def test_deleting_an_unknown_line_is_404(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("admin")
    resp = await client.delete("/api/v1/billing/invoices/INV-0001/lines/li-nope")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# 9. The lifecycle routes.
# --------------------------------------------------------------------------- #
async def test_finalize_issues_a_draft(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("admin")
    resp = await client.post("/api/v1/billing/invoices/INV-0001/finalize")
    assert resp.status_code == 200, resp.text
    number, changes, expected = seeded.updates[0]
    assert (number, changes, expected) == ("INV-0001", {"status": "open"}, "draft")
    assert resp.json()["status"] == "open"


async def test_mark_paid_stamps_the_paid_fields(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    seeded.by_number["INV-0001"]["status"] = "open"
    wire("admin")
    resp = await client.post(
        "/api/v1/billing/invoices/INV-0001/mark-paid",
        json={"paidMethod": "bank transfer", "paidAt": "2026-08-20T09:14:00Z"},
    )
    assert resp.status_code == 200, resp.text
    _number, changes, expected = seeded.updates[0]
    assert expected == "open"
    assert changes["status"] == "paid"
    assert changes["paid_method"] == "bank transfer"
    assert changes["paid_at"].isoformat() == "2026-08-20T09:14:00+00:00"


async def test_mark_paid_defaults_paid_at_to_now(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    seeded.by_number["INV-0001"]["status"] = "past_due"
    wire("admin")
    resp = await client.post("/api/v1/billing/invoices/INV-0001/mark-paid", json={})
    assert resp.status_code == 200, resp.text
    _number, changes, expected = seeded.updates[0]
    assert expected == "past_due"  # a past-due invoice can still be settled
    assert changes["paid_at"] is not None
    assert changes["paid_method"] == ""  # free text; blank is legal


async def test_void_and_refund_move_along_their_legal_edges(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    wire("admin")
    voided = await client.post("/api/v1/billing/invoices/INV-0001/void")
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "void"

    seeded.by_number["INV-0001"]["status"] = "paid"
    refunded = await client.post("/api/v1/billing/invoices/INV-0001/refund")
    assert refunded.status_code == 200, refunded.text
    assert refunded.json()["status"] == "refunded"


@pytest.mark.parametrize(
    ("current", "route"),
    [
        # A draft was never issued: no money can have arrived against it.
        ("draft", "mark-paid"), ("draft", "refund"),
        # An open invoice has not been paid, so there is nothing to refund.
        ("open", "refund"), ("open", "finalize"),
        # Settled money is refunded, never voided; and it cannot be re-issued.
        ("paid", "void"), ("paid", "finalize"), ("paid", "mark-paid"),
        ("past_due", "refund"), ("past_due", "finalize"),
        # void / refunded are TERMINAL - nothing leaves them.
        ("void", "finalize"), ("void", "mark-paid"), ("void", "refund"), ("void", "void"),
        ("refunded", "finalize"), ("refunded", "mark-paid"), ("refunded", "void"),
        ("refunded", "refund"),
    ],
)
async def test_every_illegal_lifecycle_move_is_409_and_writes_nothing(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None],
    current: str, route: str
) -> None:
    """The app-side 409 fires BEFORE the DB trigger has to.

    ``0043``'s ``invoices_guard_update`` would reject each of these too - but as an
    opaque Postgres exception. Failing fast here is what makes the API answer cleanly,
    and asserting ``updates == []`` proves we never even reached the database.
    """
    seeded.by_number["INV-0001"]["status"] = current
    wire("admin")
    resp = await client.post(f"/api/v1/billing/invoices/INV-0001/{route}", json={})
    assert resp.status_code == 409, f"{current} -> {route} must be 409: {resp.text}"
    assert "transition" in _message(resp).lower()
    assert seeded.updates == []


@pytest.mark.parametrize("route", ["finalize", "mark-paid", "void", "refund"])
async def test_a_lifecycle_move_on_an_unknown_invoice_is_404(
    client: httpx.AsyncClient, repo: FakeBillingRepo, wire: Callable[..., None], route: str
) -> None:
    wire("admin")
    resp = await client.post(f"/api/v1/billing/invoices/INV-9999/{route}", json={})
    assert resp.status_code == 404
    assert repo.updates == []


# --------------------------------------------------------------------------- #
# 10. Optimistic concurrency.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("route", ["finalize", "void"])
async def test_a_racing_transition_is_409_not_a_silent_overwrite(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None], route: str
) -> None:
    """The repo's guarded UPDATE (``where status = <what we just read>``) matched
    nothing: another operator moved the invoice between our read and our write. That
    must surface as a 409, never as a stale edit applied on top of a status the caller
    never saw."""
    seeded.conflict = True
    wire("admin")
    resp = await client.post(f"/api/v1/billing/invoices/INV-0001/{route}", json={})
    assert resp.status_code == 409
    assert "concurrently" in _message(resp).lower()


async def test_a_racing_finalize_during_a_patch_is_409(
    client: httpx.AsyncClient, seeded: FakeBillingRepo, wire: Callable[..., None]
) -> None:
    seeded.conflict = True
    wire("admin")
    resp = await client.patch("/api/v1/billing/invoices/INV-0001", json={"notes": "x"})
    assert resp.status_code == 409
    assert "concurrently" in _message(resp).lower()
