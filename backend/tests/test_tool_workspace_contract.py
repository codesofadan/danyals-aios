"""Tool-workspace contract: every ``GET /<tool>/workspace`` adapter must emit the
frontend ``lib/tools.ts`` ``EXTRAS[<tool_key>]`` shape BYTE-FOR-BYTE.

This is the Part-8 tool modules' substitute for ``test_contract_lock.py``. Those
modules are SERVER-AUTHORITATIVE (no ``lib/*.ts`` type mirrors their response
models), so the field-set lock does not apply - but the tool WORKSPACE is still
rendered generically by the dashboard off ``lib/tools.ts``, and the pieces the
renderer depends on positionally MUST match: the table's ``cols`` (a row is a
positional cell list - a reordered/renamed column silently misrenders every row),
the ``kpis[].label`` tiles, and the ``primary`` CTA.

So this file greps ``tools.ts`` (mirroring the TS-parsing technique in
``test_contract_lock.py``) and asserts the live adapter's JSON against it.

ADDING A LATER TOOL MODULE: append ONE entry to ``_TOOL_ADAPTERS`` below - do NOT
write a new bespoke file. Every test here is parametrized over that list, so one
line buys the whole contract sweep for the new module. An entry carries the
``tools.ts`` key, the workspace route, and a ``wire`` callable that installs the
module's fake repo (each module owns a different repo dependency, so the wiring -
and only the wiring - is per-module).

No DB, no network: the repo dependency is faked and the caller is an owner (whose
feature grant short-circuits before any grant lookup).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user

pytestmark = pytest.mark.unit

# Repo root: backend/tests/ -> backend/ -> repo root (as in test_contract_lock.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_TS = _REPO_ROOT / "frontend" / "lib" / "tools.ts"


# --------------------------------------------------------------------------- #
# The tools.ts EXTRAS reader.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ToolExtraTs:
    """The contract-bearing pieces of one ``EXTRAS[key]`` block in ``tools.ts``."""

    kpi_labels: list[str]
    table_title: str
    table_icon: str
    table_cols: list[str]
    primary_label: str
    primary_icon: str


def _extras_block(tool_key: str) -> str:
    """The raw body of ``EXTRAS[<tool_key>]``.

    Blocks are 2-space indented and close on a 2-space-indented ``},`` - the only
    such line inside a block belongs to the block itself, so the non-greedy match
    stops at the right brace.
    """
    src = _TOOLS_TS.read_text(encoding="utf-8")
    match = re.search(rf"^  {tool_key}: \{{$(.*?)^  \}},$", src, re.DOTALL | re.MULTILINE)
    assert match, f"EXTRAS['{tool_key}'] not found in {_TOOLS_TS}"
    return match.group(1)


def _quoted(text: str) -> list[str]:
    """Every double-quoted literal in ``text``, in source order."""
    return re.findall(r'"([^"]*)"', text)


def read_tool_extra(tool_key: str) -> ToolExtraTs:
    """Parse the contract-bearing fields of one ``tools.ts`` EXTRAS block.

    Every sub-parse asserts, so a regex that stops matching (a ``tools.ts``
    reformat, a renamed key) FAILS loudly instead of vacuously passing on empty
    data - the failure mode this whole file exists to prevent.
    """
    block = _extras_block(tool_key)

    # kpis: [ { label: "...", value: "..." }, ... ]  - scoped to the kpis array so
    # the primary CTA's `label` can never be harvested as a KPI tile.
    kpis = re.search(r"kpis:\s*\[(.*?)\n\s*\],", block, re.DOTALL)
    assert kpis, f"kpis array not parsed for '{tool_key}'"
    kpi_labels = re.findall(r'label:\s*"([^"]*)"', kpis.group(1))
    assert kpi_labels, f"no kpi labels parsed for '{tool_key}'"

    # table: { title: "...", icon: "...", cols: [...], rows: [...] }
    table = re.search(r"table:\s*\{(.*?)\n\s*\},", block, re.DOTALL)
    assert table, f"table block not parsed for '{tool_key}'"
    title = re.search(r'title:\s*"([^"]*)"', table.group(1))
    icon = re.search(r'icon:\s*"([^"]*)"', table.group(1))
    cols = re.search(r"cols:\s*\[([^\]]*)\]", table.group(1))
    assert title and icon and cols, f"table title/icon/cols not parsed for '{tool_key}'"
    table_cols = _quoted(cols.group(1))
    assert table_cols, f"no table cols parsed for '{tool_key}'"

    # primary: { label: "...", icon: "..." }
    primary = re.search(r'primary:\s*\{\s*label:\s*"([^"]*)",\s*icon:\s*"([^"]*)"\s*\}', block)
    assert primary, f"primary CTA not parsed for '{tool_key}'"

    return ToolExtraTs(
        kpi_labels=kpi_labels,
        table_title=title.group(1),
        table_icon=icon.group(1),
        table_cols=table_cols,
        primary_label=primary.group(1),
        primary_icon=primary.group(2),
    )


# --------------------------------------------------------------------------- #
# The registry: ONE entry per tool module. Append here; never fork this file.
# --------------------------------------------------------------------------- #
class ToolAdapter(NamedTuple):
    """One module's workspace adapter under contract.

    ``tool_key``  - the ``lib/tools.ts`` EXTRAS key (= the RBAC feature key).
    ``path``      - the live workspace route.
    ``wire``      - installs the module's fake repo on the app; returns nothing.
    """

    tool_key: str
    path: str
    wire: Callable[[FastAPI], None]


def _wire_keyword_research(app: FastAPI) -> None:
    """Fake keyword repo: a two-row bank + non-zero stats (so the table + KPI tiles
    are actually populated - an empty adapter would pass the col lock vacuously)."""
    from app.modules.keyword_research.repo import get_keyword_repo

    class _FakeKeywordRepo:
        def keyword_stats(self) -> dict[str, Any]:
            return {"saved": 640, "clusters": 28, "avg_difficulty": 34.2}

        def list_keywords(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {"keyword": "invisalign cost", "volume": 8100, "difficulty": 42.0,
                 "intent": "Commercial"},
                {"keyword": "realtor near me", "volume": 12400, "difficulty": 55.0,
                 "intent": "Local"},
            ]

    app.dependency_overrides[get_keyword_repo] = _FakeKeywordRepo


def _wire_client_onboarding(app: FastAPI) -> None:
    """Fake onboarding repo: two LIVE runs' worth of steps + non-zero stats (so the
    board + KPI tiles are actually populated - an empty adapter would pass the col
    lock vacuously). The rows carry a ``client_id`` on purpose: the sweep's envelope
    assertions would not notice a leak, so the module's own router test pins that."""
    from app.modules.client_onboarding.repo import get_onboarding_repo

    class _FakeOnboardingRepo:
        def onboarding_stats(self) -> dict[str, Any]:
            return {"in_onboarding": 3, "steps_pending": 7, "completed_30d": 12}

        def live_run_steps(self) -> list[dict[str, Any]]:
            return [
                {"id": "s1", "run_id": "r1", "client_id": "cl-1",
                 "client_name": "Orchard Pediatrics", "step_key": "collect_gbp",
                 "label": "Collect GBP access", "status": "pending", "owner_name": "Sara",
                 "sort_order": 2},
                {"id": "s2", "run_id": "r2", "client_id": "cl-2",
                 "client_name": "Coastline Fit", "step_key": "kickoff",
                 "label": "Kickoff call & goals", "status": "in_progress",
                 "owner_name": "Ayesha", "sort_order": 1},
            ]

    app.dependency_overrides[get_onboarding_repo] = _FakeOnboardingRepo


def _wire_billing(app: FastAPI) -> None:
    """Fake billing repo: a two-row ledger + non-zero tiles (so the table + KPI tiles
    are actually populated - an empty adapter would pass the col lock vacuously).

    ``subscription_mrr`` and ``invoice_counts`` are SEPARATE reads over separate
    tables by design (MRR is subscription-derived, never invoice-derived), so the
    fake mirrors that split rather than collapsing them into one stats dict.
    """
    from app.modules.billing.repo import get_billing_repo

    class _FakeBillingRepo:
        def subscription_mrr(self) -> int:
            return 28_400  # sum(clients.mrr) - NOT the invoices below

        def invoice_counts(self) -> dict[str, int]:
            return {"open_invoices": 3, "past_due": 1}

        def list_invoices(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {"client_name": "Meridian Wealth", "total": 1490, "due_date": "2026-08-27",
                 "status": "paid"},
                {"client_name": "Atlas Legal", "total": 690, "due_date": "2026-07-05",
                 "status": "past_due"},
            ]

    app.dependency_overrides[get_billing_repo] = _FakeBillingRepo


def _wire_local_seo(app: FastAPI) -> None:
    """Fake local repo: a two-row map-pack board + non-zero stats (so the table + KPI
    tiles are actually populated - an empty adapter would pass the col lock vacuously).

    One row is deliberately UNRANKED (``rank: None``) - the honest "checked, not in
    the pack" state - so the sweep proves the adapter renders it as a real cell rather
    than crashing or inventing a number.
    """
    from app.modules.local_seo.repo import get_local_repo

    class _FakeLocalRepo:
        def local_stats(self) -> dict[str, Any]:
            return {"gbp_profiles": 9, "avg_map_rank": 3.2, "citations": 210}

        def list_rankings(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {"location_label": "Karachi", "client_name": "Verde Cafe",
                 "keyword": "cafe near me", "rank": 2},
                {"location_label": "Lahore", "client_name": "Coastline Fit",
                 "keyword": "gym membership", "rank": None},
            ]

    app.dependency_overrides[get_local_repo] = _FakeLocalRepo


def _wire_on_page(app: FastAPI) -> None:
    """Fake on-page repo: a two-row recommendation board + non-zero stats (so the
    table + KPI tiles are actually populated - an empty adapter would pass the col
    lock vacuously)."""
    from app.modules.on_page.repo import get_on_page_repo

    class _FakeOnPageRepo:
        def stats(self) -> dict[str, Any]:
            return {"analyzed": 214, "open": 41, "applied": 178}

        def list_recommendations(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {"page_url": "/services/implants", "issue": "Missing meta description",
                 "impact": "High", "status": "open"},
                {"page_url": "/blog/whitening", "issue": "H1 not keyword-aligned",
                 "impact": "Med", "status": "applied"},
            ]

    app.dependency_overrides[get_on_page_repo] = _FakeOnPageRepo


# --------------------------------------------------------------------------- #
# The Part 8 Phase 2.5 adapters: the NINE tools fronting Parts 1-9 modules.
#
# These wire the SHARED repos (app/db/*), not a module-private one - the whole point
# of the phase is that no new storage was added. Every fake below carries non-zero
# rows AND non-zero tiles for the same reason the sibling fakes do: an adapter that
# returned nothing would pass the column lock vacuously, which is the failure mode
# this harness exists to prevent.
# --------------------------------------------------------------------------- #
def _wire_technical_audit(app: FastAPI) -> None:
    """Fake audits repo: two crawls - one done, one FAILED (so the sweep sees a real
    ``crit`` tone), plus a scored row the Avg. health tile folds via the module's own
    ``compute_audit_stats``. The rows carry ``client_id`` on purpose: the envelope
    assertions would not notice a leak, so the module's router test pins that."""
    from app.db.audits_repo import get_audits_repo

    class _FakeAuditsRepo:
        def list_audits(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {"id": "a1", "client_id": "cl-1", "client_name": "NorthPeak Dental",
                 "url": "northpeakdental.com", "status": "done", "score": 88,
                 "runtime_seconds": 372, "created_at": "2026-07-16T09:14:00+00:00"},
                {"id": "a2", "client_id": "cl-2", "client_name": "Atlas Legal",
                 "url": "atlaslegal.com", "status": "failed", "score": None,
                 "runtime_seconds": None, "created_at": "2026-07-15T09:14:00+00:00"},
            ]

    app.dependency_overrides[get_audits_repo] = _FakeAuditsRepo


def _wire_backlink_manager(app: FastAPI) -> None:
    """Fake off-page repo: a two-row ledger (one won link, one TOXIC) + non-zero tiles.

    ``referring_domain_count`` and the status breakdown are SEPARATE reads by design
    (the profile size excludes lost links; the breakdown counts every status), so the
    fake mirrors that split rather than deriving one from the other."""
    from app.db.offpage_repo import get_offpage_repo

    class _FakeOffpageRepo:
        def referring_domain_count(self) -> int:
            return 1240

        def backlink_status_counts(self) -> dict[str, int]:
            return {"new": 34, "lost": 12, "toxic": 5}

        def new_backlink_count(self, **kwargs: Any) -> int:
            return 34

        def list_backlinks(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {"client_id": "cl-1", "client_name": "NorthPeak Dental",
                 "ref_domain": "healthline.com", "authority": 91, "status": "new"},
                {"client_id": "cl-3", "client_name": "Verde Cafe",
                 "ref_domain": "spam-links.biz", "authority": 6, "status": "toxic"},
            ]

    app.dependency_overrides[get_offpage_repo] = _FakeOffpageRepo


def _fake_content_repo() -> Any:
    """The content fake shared by the content_pipeline + publishing adapters (both read
    the SAME 0017 ledger through the same dependency)."""

    class _FakeContentRepo:
        def stats(self) -> dict[str, int]:
            return {"queued": 4, "drafting": 5, "needs_review": 3, "done": 24, "failed": 0}

        def publish_stats(self, **kwargs: Any) -> dict[str, int]:
            return {"scheduled": 5, "failed": 0, "published": 24}

        def list_jobs(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {"client_id": "cl-1", "client_name": "NorthPeak Dental",
                 "topic": "Teeth whitening guide", "stage": "Drafting", "status": "drafting",
                 "words": 1850, "target": "WordPress",
                 "created_at": "2026-07-16T09:00:00+00:00"},
                {"client_id": "cl-4", "client_name": "Atlas Legal",
                 "topic": "What to expect at trial", "stage": "Queued", "status": "queued",
                 "words": 0, "target": "PDF/Markdown",
                 "created_at": "2026-07-15T09:00:00+00:00"},
            ]

    return _FakeContentRepo


def _wire_content_pipeline(app: FastAPI) -> None:
    """Fake content repo: a two-row pipeline (one drafting, one QUEUED with 0 words -
    the honest "not drafted yet" state) + non-zero stats."""
    from app.db.content_repo import get_content_repo

    app.dependency_overrides[get_content_repo] = _fake_content_repo()


def _wire_publishing(app: FastAPI) -> None:
    """Fake content + off-page repos: the publish queue spans BOTH ledgers, so both
    dependencies are wired and each tile must SUM them (pinned below)."""
    from app.db.content_repo import get_content_repo
    from app.db.offpage_repo import get_offpage_repo

    class _FakeWeb2Repo:
        def publish_stats(self, **kwargs: Any) -> dict[str, int]:  # pragma: no cover
            raise AssertionError("the web2 side must use web2_publish_stats")

        def web2_publish_stats(self, **kwargs: Any) -> dict[str, int]:
            return {"scheduled": 1, "failed": 0, "published": 3}

        def list_web2(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {"client_id": "cl-3", "client_name": "Verde Cafe",
                 "topic": "Seasonal menu launch", "platform": "Medium",
                 "status": "published", "created_at": "2026-07-14T09:00:00+00:00"},
            ]

    app.dependency_overrides[get_content_repo] = _fake_content_repo()
    app.dependency_overrides[get_offpage_repo] = _FakeWeb2Repo


def _wire_reporting(app: FastAPI) -> None:
    """Fake reports repo: two pushes + two workbooks (one synced, one erroring - so the
    Sheets-synced tile is a real filter, not a row count) + a non-zero window."""
    from app.db.reports_repo import get_reports_repo

    class _FakeReportsRepo:
        def sync_event_count(self, **kwargs: Any) -> int:
            return 48

        def list_sync_events(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {"id": "e1", "client_name": "NorthPeak Dental", "dataset": "audit",
                 "rows": 120, "synced_at": "2026-06-30T09:00:00+00:00"},
                {"id": "e2", "client_name": "Lumen Realty", "dataset": "content",
                 "rows": 42, "synced_at": "2026-06-28T09:00:00+00:00"},
            ]

        def list_workbooks(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {"id": "w1", "client_name": "NorthPeak Dental", "status": "synced"},
                {"id": "w2", "client_name": "Atlas Legal", "status": "error"},
            ]

    app.dependency_overrides[get_reports_repo] = _FakeReportsRepo


def _wire_task_board(app: FastAPI) -> None:
    """Fake tasks repo: a two-row board (one in progress, one UNASSIGNED - the honest
    empty-assignee state) + a ledger the tiles fold."""
    from app.db.tasks_repo import get_tasks_repo

    board = [
        {"code": "J-2042", "client_id": "cl-1", "client_name": "NorthPeak Dental",
         "title": "Technical crawl + CWV", "status": "in_progress", "assignee_name": "Bilal",
         "updated_at": "2026-07-16T09:00:00+00:00"},
        {"code": "J-2043", "client_id": "cl-3", "client_name": "Verde Cafe",
         "title": "Map-pack fixes", "status": "todo", "assignee_name": "",
         "updated_at": "2026-07-15T09:00:00+00:00"},
    ]

    class _FakeTasksRepo:
        def list_board_tasks(self, **kwargs: Any) -> list[dict[str, Any]]:
            return list(board)

        def list_tasks(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            return list(board)

    app.dependency_overrides[get_tasks_repo] = _FakeTasksRepo


def _wire_client_setup(app: FastAPI) -> None:
    """Fake clients repo: two sites + three clients, one of which has NO site (so the
    Pending-setup tile is a real join, not a constant)."""
    from app.db.clients_repo import get_clients_repo

    class _FakeClientsRepo:
        def list_all_sites(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {"id": "s1", "domain": "northpeakdental.com", "cms_type": "wordpress",
                 "client_name": "NorthPeak Dental", "client_status": "active"},
                {"id": "s2", "domain": "lumenrealty.co", "cms_type": "webflow",
                 "client_name": "Lumen Realty", "client_status": "trial"},
            ]

        def list_clients(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {"id": "cl-1", "name": "NorthPeak Dental", "status": "active"},
                {"id": "cl-2", "name": "Lumen Realty", "status": "trial"},
                {"id": "cl-3", "name": "Orchard Pediatrics", "status": "trial"},
            ]

        def site_counts(self) -> dict[str, int]:
            return {"cl-1": 1, "cl-2": 1}  # cl-3 has none -> pending setup

    app.dependency_overrides[get_clients_repo] = _FakeClientsRepo


def _wire_key_vault(app: FastAPI) -> None:
    """Fake vault repo: two masked metadata rows - one rotated, one never.

    ``list_keys`` is a ``select *``, so the REAL rows carry ``secret_sealed``; this fake
    carries it too (with an unmistakable value) so the sweep exercises the adapter on a
    row shaped like the real one. The key-vault leak tests in
    ``tests/modules/tool_workspaces/`` are what pin that it never surfaces.
    """
    from app.db.vault_repo import get_vault_repo

    class _FakeVaultRepo:
        def list_keys(self) -> list[dict[str, Any]]:
            return [
                {"id": "k1", "provider": "Serper.dev", "label": "Search",
                 "masked": "sk-abc••••••••4cb6", "secret_sealed": b"SEALED-DO-NOT-LEAK",
                 "kind": "api_key", "key_version": 1,
                 "created_at": "2026-01-04T09:00:00+00:00",
                 "updated_at": "2026-05-04T09:00:00+00:00"},
                {"id": "k2", "provider": "Anthropic", "label": "Content AI",
                 "masked": "sk-ant••••••••9911", "secret_sealed": b"SEALED-DO-NOT-LEAK",
                 "kind": "api_key", "key_version": 1,
                 "created_at": "2026-04-02T09:00:00+00:00",
                 "updated_at": "2026-04-02T09:00:00+00:00"},
            ]

    app.dependency_overrides[get_vault_repo] = _FakeVaultRepo


def _wire_team_access(app: FastAPI) -> None:
    """Fake roster reader + team metrics: two members (one active, one INVITED) and the
    7F-3 active-task metric the Tasks column renders."""
    from app.modules.tool_workspaces.router import get_roster_reader
    from app.services.team_metrics import MemberMetrics, get_team_metrics

    def _roster(_caller_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {"id": "u1", "name": "Ayesha Raza", "role": "manager", "status": "active",
             "email": "ayesha@aios.dev", "avatar_color": "#7B69EE", "title": "Manager"},
            {"id": "u2", "name": "Imran Qureshi", "role": "viewer", "status": "invited",
             "email": "imran@aios.dev", "avatar_color": "#4D8DF0", "title": "Viewer"},
        ]

    class _FakeMetrics:
        def member_metrics(self, ids: Any = None) -> dict[str, MemberMetrics]:
            return {"u1": MemberMetrics(active_tasks=6)}  # u2 absent -> all-zero

    app.dependency_overrides[get_roster_reader] = lambda: _roster
    app.dependency_overrides[get_team_metrics] = _FakeMetrics


_TOOL_ADAPTERS: list[ToolAdapter] = [
    ToolAdapter("keyword_research", "/api/v1/keyword-research/workspace", _wire_keyword_research),
    ToolAdapter(
        "client_onboarding", "/api/v1/client-onboarding/workspace", _wire_client_onboarding
    ),
    ToolAdapter("billing", "/api/v1/billing/workspace", _wire_billing),
    ToolAdapter("local_seo", "/api/v1/local-seo/workspace", _wire_local_seo),
    ToolAdapter("on_page", "/api/v1/on-page/workspace", _wire_on_page),
    # Part 8 Phase 2.5 - the nine adapters over the Parts 1-9 modules.
    ToolAdapter("technical_audit", "/api/v1/technical-audit/workspace", _wire_technical_audit),
    ToolAdapter("backlink_manager", "/api/v1/backlink-manager/workspace", _wire_backlink_manager),
    ToolAdapter("content_pipeline", "/api/v1/content-pipeline/workspace", _wire_content_pipeline),
    ToolAdapter("publishing", "/api/v1/publishing/workspace", _wire_publishing),
    ToolAdapter("reporting", "/api/v1/reporting/workspace", _wire_reporting),
    ToolAdapter("task_board", "/api/v1/task-board/workspace", _wire_task_board),
    ToolAdapter("client_setup", "/api/v1/client-setup/workspace", _wire_client_setup),
    ToolAdapter("key_vault", "/api/v1/key-vault/workspace", _wire_key_vault),
    ToolAdapter("team_access", "/api/v1/team-access/workspace", _wire_team_access),
]

_IDS = [a.tool_key for a in _TOOL_ADAPTERS]


def _owner() -> CurrentUser:
    """An owner caller: all-on, so ``require_feature`` short-circuits without the
    grant lookup (which would need a DB)."""
    return CurrentUser(
        id="00000000-0000-0000-0000-0000000000ff", email="owner@aios.dev", role="owner",
        status="active", name="Owner", title="", avatar_color="#7B69EE", phone="",
        two_fa=False,
    )


async def _fetch_workspace(app: FastAPI, client: httpx.AsyncClient, adapter: ToolAdapter) -> Any:
    app.dependency_overrides[get_current_user] = _owner
    adapter.wire(app)
    resp = await client.get(adapter.path)
    assert resp.status_code == 200, f"{adapter.path}: {resp.status_code} {resp.text}"
    return resp.json()


# --------------------------------------------------------------------------- #
# 1. Reader guards - a bad regex must FAIL, never vacuously pass.
# --------------------------------------------------------------------------- #
def test_tools_ts_exists_and_declares_the_extras_map() -> None:
    src = _TOOLS_TS.read_text(encoding="utf-8")
    assert "const EXTRAS: Record<string, ToolExtra>" in src, (
        f"{_TOOLS_TS} no longer declares the EXTRAS map - this reader is parsing "
        "something else entirely"
    )


def test_reader_rejects_an_unknown_tool_key() -> None:
    # Proves the reader MATCHES rather than silently returning empty data: if this
    # ever stopped raising, every contract assertion below would pass vacuously.
    with pytest.raises(AssertionError, match="not found"):
        read_tool_extra("definitely_not_a_real_tool")


@pytest.mark.parametrize("adapter", _TOOL_ADAPTERS, ids=_IDS)
def test_reader_parses_real_data_for_every_registered_tool(adapter: ToolAdapter) -> None:
    ts = read_tool_extra(adapter.tool_key)
    assert ts.kpi_labels and all(ts.kpi_labels), "kpi labels missing/blank"
    assert ts.table_cols and all(ts.table_cols), "table cols missing/blank"
    assert ts.table_title and ts.table_icon, "table title/icon missing"
    assert ts.primary_label and ts.primary_icon, "primary CTA missing"


def test_registry_is_not_empty_and_has_unique_keys() -> None:
    # Guards against a refactor silently emptying the sweep (cf. test_contract_lock).
    assert _TOOL_ADAPTERS, "no tool adapters registered"
    assert len({a.tool_key for a in _TOOL_ADAPTERS}) == len(_TOOL_ADAPTERS)
    assert len({a.path for a in _TOOL_ADAPTERS}) == len(_TOOL_ADAPTERS)


# --------------------------------------------------------------------------- #
# 2. The contract: the live adapter vs tools.ts.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("adapter", _TOOL_ADAPTERS, ids=_IDS)
async def test_workspace_table_cols_are_byte_identical_to_tools_ts(
    app: FastAPI, client: httpx.AsyncClient, adapter: ToolAdapter
) -> None:
    """The strictest lock: a table row is a POSITIONAL cell list, so a renamed or
    reordered column misrenders every row without any other test noticing."""
    body = await _fetch_workspace(app, client, adapter)
    ts = read_tool_extra(adapter.tool_key)
    assert body["table"]["cols"] == ts.table_cols, (
        f"{adapter.tool_key}: workspace cols drifted from tools.ts - "
        f"backend={body['table']['cols']} tools.ts={ts.table_cols}"
    )


@pytest.mark.parametrize("adapter", _TOOL_ADAPTERS, ids=_IDS)
async def test_workspace_kpi_labels_match_tools_ts(
    app: FastAPI, client: httpx.AsyncClient, adapter: ToolAdapter
) -> None:
    body = await _fetch_workspace(app, client, adapter)
    ts = read_tool_extra(adapter.tool_key)
    assert [k["label"] for k in body["kpis"]] == ts.kpi_labels


@pytest.mark.parametrize("adapter", _TOOL_ADAPTERS, ids=_IDS)
async def test_workspace_table_title_icon_and_primary_match_tools_ts(
    app: FastAPI, client: httpx.AsyncClient, adapter: ToolAdapter
) -> None:
    body = await _fetch_workspace(app, client, adapter)
    ts = read_tool_extra(adapter.tool_key)
    assert body["table"]["title"] == ts.table_title
    assert body["table"]["icon"] == ts.table_icon
    assert body["primary"] == {"label": ts.primary_label, "icon": ts.primary_icon}


@pytest.mark.parametrize("adapter", _TOOL_ADAPTERS, ids=_IDS)
async def test_workspace_rows_are_positional_and_match_the_col_count(
    app: FastAPI, client: httpx.AsyncClient, adapter: ToolAdapter
) -> None:
    """Every emitted row must be exactly as wide as ``cols`` and every cell must be
    the ``lib/tools.ts`` ``Cell`` union (a bare string OR ``{v, tone}``)."""
    body = await _fetch_workspace(app, client, adapter)
    tones = {"ok", "info", "warn", "mut", "crit"}
    width = len(body["table"]["cols"])
    rows = body["table"]["rows"]
    assert rows, f"{adapter.tool_key}: fake repo produced no rows - the col lock " \
                 "would pass vacuously"
    for row in rows:
        assert len(row) == width, f"row {row} is not {width} cells wide"
        for cell in row:
            if isinstance(cell, dict):
                assert set(cell) == {"v", "tone"}, f"bad toned cell {cell}"
                assert cell["tone"] in tones, f"unknown tone {cell['tone']}"
            else:
                assert isinstance(cell, str), f"cell {cell!r} is neither str nor {{v,tone}}"


@pytest.mark.parametrize("adapter", _TOOL_ADAPTERS, ids=_IDS)
async def test_workspace_emits_the_tool_extra_envelope(
    app: FastAPI, client: httpx.AsyncClient, adapter: ToolAdapter
) -> None:
    """The envelope is the ``lib/tools.ts`` ``ToolExtra``: kpis + bullets always,
    table + primary optional. Nothing else may appear."""
    body = await _fetch_workspace(app, client, adapter)
    assert set(body) <= {"kpis", "table", "primary", "bullets"}, f"extra keys: {set(body)}"
    assert {"kpis", "bullets"} <= set(body)
    assert body["bullets"] and all(isinstance(b, str) for b in body["bullets"])
    for kpi in body["kpis"]:
        assert set(kpi) <= {"label", "value", "delta", "dir"}
        assert isinstance(kpi["value"], str), "a KPI value is a display STRING"


# --------------------------------------------------------------------------- #
# 3. keyword_research: the pinned literals (Part 8 Phase 2A).
# --------------------------------------------------------------------------- #
# Belt-and-braces over the parametrized sweep: these are the exact values the
# dashboard renders, spelled out so a drift names itself in the failure output
# rather than only showing up as a tools.ts-vs-backend diff.
def test_keyword_research_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("keyword_research")
    assert ts.table_cols == ["Keyword", "Volume", "Difficulty", "Intent"]
    assert ts.kpi_labels == ["Saved keywords", "Clusters", "Avg. difficulty"]
    assert ts.primary_label == "Research keywords"
    assert ts.primary_icon == "search"
    assert ts.table_title == "Opportunity keywords"
    assert ts.table_icon == "search"


def test_keyword_research_service_constant_matches_tools_ts() -> None:
    # The adapter builds from this module constant; pin it to tools.ts directly so a
    # drift is caught even if the route is refactored away.
    from app.modules.keyword_research.service import WORKSPACE_TABLE_COLS

    assert read_tool_extra("keyword_research").table_cols == WORKSPACE_TABLE_COLS


# --------------------------------------------------------------------------- #
# 4. client_onboarding: the pinned literals (Part 8 Phase 2F).
# --------------------------------------------------------------------------- #
def test_client_onboarding_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("client_onboarding")
    assert ts.table_cols == ["Client", "Step", "Owner", "Status"]
    assert ts.kpi_labels == ["In onboarding", "Steps pending", "Completed (30d)"]
    assert ts.primary_label == "Start onboarding"
    assert ts.primary_icon == "person_add"
    assert ts.table_title == "Onboarding"
    assert ts.table_icon == "person_add"


def test_client_onboarding_service_constant_matches_tools_ts() -> None:
    from app.modules.client_onboarding.service import WORKSPACE_TABLE_COLS

    assert read_tool_extra("client_onboarding").table_cols == WORKSPACE_TABLE_COLS


# --------------------------------------------------------------------------- #
# 5. billing: the pinned literals (Part 8 Phase 2H).
# --------------------------------------------------------------------------- #
def test_billing_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("billing")
    assert ts.table_cols == ["Client", "Amount", "Due", "Status"]
    assert ts.kpi_labels == ["MRR", "Open invoices", "Past due"]
    assert ts.primary_label == "New invoice"
    assert ts.primary_icon == "payments"
    assert ts.table_title == "Invoices"
    assert ts.table_icon == "payments"


def test_billing_service_constant_matches_tools_ts() -> None:
    from app.modules.billing.service import WORKSPACE_TABLE_COLS

    assert read_tool_extra("billing").table_cols == WORKSPACE_TABLE_COLS


async def test_billing_mrr_tile_reads_the_subscription_table_not_the_ledger(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """The module's load-bearing scope rule, pinned at the workspace edge.

    The fake ledger bills 1490 + 690 = 2180; the fake subscription book carries an MRR
    of 28,400. The MRR tile must render the SUBSCRIPTION number - if the adapter ever
    starts summing invoices, this tile flips to "$2.2k" and this test names it.
    """
    adapter = next(a for a in _TOOL_ADAPTERS if a.tool_key == "billing")
    body = await _fetch_workspace(app, client, adapter)
    tiles = {k["label"]: k["value"] for k in body["kpis"]}
    assert tiles["MRR"] == "$28.4k"  # sum(clients.mrr), compact-formatted
    assert tiles["MRR"] != "$2.2k"  # ... and emphatically NOT sum(invoices)
    assert tiles["Open invoices"] == "3"  # these two DO come from the ledger
    assert tiles["Past due"] == "1"


# --------------------------------------------------------------------------- #
# 6. local_seo: the pinned literals (Part 8 Phase 2E).
# --------------------------------------------------------------------------- #
def test_local_seo_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("local_seo")
    assert ts.table_cols == ["Location", "Client", "Keyword", "Rank"]
    assert ts.kpi_labels == ["GBP profiles", "Avg. map rank", "Citations"]
    assert ts.primary_label == "Run local audit"
    assert ts.primary_icon == "storefront"
    assert ts.table_title == "Map-pack rankings"
    assert ts.table_icon == "storefront"


def test_local_seo_service_constant_matches_tools_ts() -> None:
    from app.modules.local_seo.service import WORKSPACE_TABLE_COLS

    assert read_tool_extra("local_seo").table_cols == WORKSPACE_TABLE_COLS


# --------------------------------------------------------------------------- #
# 7. on_page: the pinned literals (Part 8 Phase 2D).
# --------------------------------------------------------------------------- #
def test_on_page_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("on_page")
    assert ts.table_cols == ["Page", "Issue", "Impact", "Status"]
    assert ts.kpi_labels == ["Pages analyzed", "Open suggestions", "Applied"]
    assert ts.primary_label == "Analyze page"
    assert ts.primary_icon == "tune"
    assert ts.table_title == "Top recommendations"
    assert ts.table_icon == "tune"


def test_on_page_service_constant_matches_tools_ts() -> None:
    from app.modules.on_page.service import WORKSPACE_TABLE_COLS

    assert read_tool_extra("on_page").table_cols == WORKSPACE_TABLE_COLS


async def test_on_page_workspace_tones_match_the_demo_semantics(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """``tools.ts`` encodes the tone semantics in its demo rows: High reads ``crit``,
    Med reads ``warn``, an Open status reads ``warn`` and an Applied one ``ok``. The
    cols lock cannot see this (tones live inside the cells), so pin it here."""
    adapter = next(a for a in _TOOL_ADAPTERS if a.tool_key == "on_page")
    body = await _fetch_workspace(app, client, adapter)
    high_open, med_applied = body["table"]["rows"]
    assert high_open[2] == {"v": "High", "tone": "crit"}
    assert high_open[3] == {"v": "Open", "tone": "warn"}
    assert med_applied[2] == {"v": "Med", "tone": "warn"}
    assert med_applied[3] == {"v": "Applied", "tone": "ok"}


# --------------------------------------------------------------------------- #
# 8. technical_audit: the pinned literals (Part 8 Phase 2.5).
# --------------------------------------------------------------------------- #
def test_technical_audit_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("technical_audit")
    assert ts.table_cols == ["Site", "Client", "Score", "Issues"]
    assert ts.kpi_labels == ["Sites monitored", "Open issues", "Avg. health"]
    assert ts.primary_label == "Run crawl"
    assert ts.primary_icon == "fact_check"
    assert ts.table_title == "Recent crawls"
    assert ts.table_icon == "troubleshoot"


def test_technical_audit_service_constant_matches_tools_ts() -> None:
    from app.modules.tool_workspaces.service import WORKSPACE_TABLE_COLS_TECHNICAL_AUDIT

    assert read_tool_extra("technical_audit").table_cols == WORKSPACE_TABLE_COLS_TECHNICAL_AUDIT


async def test_technical_audit_health_tile_reuses_the_audits_modules_own_stats(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """The adapter's load-bearing reuse rule, pinned at the workspace edge.

    The fake ledger holds one COMPLETED crawl scoring 88 and one FAILED crawl with no
    score. ``compute_audit_stats`` (which ``GET /audits/stats`` also uses) averages
    completed runs only -> 88%. If this adapter ever starts averaging its own way, the
    unscored failure drags the tile to 44% and this test names it.
    """
    adapter = next(a for a in _TOOL_ADAPTERS if a.tool_key == "technical_audit")
    body = await _fetch_workspace(app, client, adapter)
    tiles = {k["label"]: k["value"] for k in body["kpis"]}
    assert tiles["Avg. health"] == "88%"
    assert tiles["Sites monitored"] == "2"  # distinct urls, not a row count
    # No issue ledger exists anywhere -> the tile must stay an em dash, never a number.
    assert tiles["Open issues"] == "—"


async def test_technical_audit_failed_crawl_reads_crit(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """A failed crawl is the state an operator must see; a done one has no issue count."""
    adapter = next(a for a in _TOOL_ADAPTERS if a.tool_key == "technical_audit")
    body = await _fetch_workspace(app, client, adapter)
    done, failed = body["table"]["rows"]
    assert done[2] == "88"
    assert done[3] == {"v": "—", "tone": "mut"}  # no issue count for a healthy crawl
    assert failed[2] == "—"  # a failed crawl has no score; never a 0
    assert failed[3] == {"v": "Failed", "tone": "crit"}


# --------------------------------------------------------------------------- #
# 9. backlink_manager: the pinned literals (Part 8 Phase 2.5).
# --------------------------------------------------------------------------- #
def test_backlink_manager_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("backlink_manager")
    assert ts.table_cols == ["Domain", "Client", "DR", "Status"]
    assert ts.kpi_labels == ["Referring domains", "New links (30d)", "Toxic flagged"]
    assert ts.primary_label == "Run link sweep"
    assert ts.primary_icon == "hub"
    assert ts.table_title == "Recent links"
    assert ts.table_icon == "hub"


def test_backlink_manager_service_constant_matches_tools_ts() -> None:
    from app.modules.tool_workspaces.service import WORKSPACE_TABLE_COLS_BACKLINK_MANAGER

    assert read_tool_extra("backlink_manager").table_cols == WORKSPACE_TABLE_COLS_BACKLINK_MANAGER


async def test_backlink_manager_tiles_read_the_right_aggregate(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """The profile size is the DISTINCT-domain count (1240), NOT the status breakdown's
    total (34+12+5=51). If the adapter ever starts summing statuses, this names it."""
    adapter = next(a for a in _TOOL_ADAPTERS if a.tool_key == "backlink_manager")
    body = await _fetch_workspace(app, client, adapter)
    tiles = {k["label"]: k["value"] for k in body["kpis"]}
    assert tiles["Referring domains"] == "1,240"
    assert tiles["Referring domains"] != "51"
    assert tiles["New links (30d)"] == "34"  # the WINDOWED count, not status_counts['new']
    assert tiles["Toxic flagged"] == "5"
    won, toxic = body["table"]["rows"]
    assert won[2] == "91"  # DR = the stored authority
    assert won[3] == {"v": "New", "tone": "ok"}
    assert toxic[3] == {"v": "Toxic", "tone": "crit"}


# --------------------------------------------------------------------------- #
# 10. content_pipeline: the pinned literals (Part 8 Phase 2.5).
# --------------------------------------------------------------------------- #
def test_content_pipeline_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("content_pipeline")
    assert ts.table_cols == ["Topic", "Client", "Stage", "Words"]
    assert ts.kpi_labels == ["In pipeline", "Drafting", "Ready for review"]
    assert ts.primary_label == "New content brief"
    assert ts.primary_icon == "article"
    assert ts.table_title == "Content jobs"
    assert ts.table_icon == "article"


def test_content_pipeline_service_constant_matches_tools_ts() -> None:
    from app.modules.tool_workspaces.service import WORKSPACE_TABLE_COLS_CONTENT_PIPELINE

    assert read_tool_extra("content_pipeline").table_cols == WORKSPACE_TABLE_COLS_CONTENT_PIPELINE


async def test_content_pipeline_in_pipeline_tile_excludes_terminal_jobs(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """"In pipeline" counts work still MOVING: queued 4 + drafting 5 + needs_review 3 +
    publishing 0 = 12. The fake's 24 done jobs have left the pipeline and must not be
    counted - a total row count would read 36 and this test names it."""
    adapter = next(a for a in _TOOL_ADAPTERS if a.tool_key == "content_pipeline")
    body = await _fetch_workspace(app, client, adapter)
    tiles = {k["label"]: k["value"] for k in body["kpis"]}
    assert tiles["In pipeline"] == "12"
    assert tiles["In pipeline"] != "36"
    assert tiles["Drafting"] == "5"
    assert tiles["Ready for review"] == "3"
    drafting, queued = body["table"]["rows"]
    assert drafting[2] == {"v": "Drafting", "tone": "info"}
    assert drafting[3] == "1,850"
    assert queued[2] == {"v": "Queued", "tone": "mut"}
    assert queued[3] == "—"  # 0 words = not drafted yet, never a literal "0"


# --------------------------------------------------------------------------- #
# 11. publishing: the pinned literals (Part 8 Phase 2.5).
# --------------------------------------------------------------------------- #
def test_publishing_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("publishing")
    assert ts.table_cols == ["Title", "Client", "Target", "Status"]
    assert ts.kpi_labels == ["Published (30d)", "Scheduled", "Failed"]
    assert ts.primary_label == "Publish"
    assert ts.primary_icon == "rocket_launch"
    assert ts.table_title == "Publish queue"
    assert ts.table_icon == "rocket_launch"


def test_publishing_service_constant_matches_tools_ts() -> None:
    from app.modules.tool_workspaces.service import WORKSPACE_TABLE_COLS_PUBLISHING

    assert read_tool_extra("publishing").table_cols == WORKSPACE_TABLE_COLS_PUBLISHING


async def test_publishing_tiles_sum_both_publish_ledgers(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """The module's load-bearing scope rule: a content job going live and a Web 2.0 post
    going live are BOTH a publish, so every tile sums the two ledgers (content 24+5+0,
    web2 3+1+0). Reading either ledger alone would show 24/5/0 or 3/1/0."""
    adapter = next(a for a in _TOOL_ADAPTERS if a.tool_key == "publishing")
    body = await _fetch_workspace(app, client, adapter)
    tiles = {k["label"]: k["value"] for k in body["kpis"]}
    assert tiles["Published (30d)"] == "27"
    assert tiles["Scheduled"] == "6"
    assert tiles["Failed"] == "0"


async def test_publishing_queue_merges_both_ledgers_newest_first(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Both ledgers land in ONE board ordered by creation, and each keeps its own
    destination vocabulary (a content ``target`` vs a web2 ``platform``) under the one
    ``Target`` column."""
    adapter = next(a for a in _TOOL_ADAPTERS if a.tool_key == "publishing")
    body = await _fetch_workspace(app, client, adapter)
    rows = body["table"]["rows"]
    assert [r[0] for r in rows] == [
        "Teeth whitening guide",   # content, 07-16
        "What to expect at trial",  # content, 07-15
        "Seasonal menu launch",     # web2,    07-14
    ]
    assert rows[0][2] == "WordPress"  # content_jobs.target
    assert rows[2][2] == "Medium"  # web2_properties.platform
    # content 'done' and web2 'published' are the same event: it is live.
    assert rows[2][3] == {"v": "Live", "tone": "ok"}
    assert rows[1][3] == {"v": "Draft", "tone": "mut"}


# --------------------------------------------------------------------------- #
# 12. reporting: the pinned literals (Part 8 Phase 2.5).
# --------------------------------------------------------------------------- #
def test_reporting_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("reporting")
    assert ts.table_cols == ["Report", "Client", "Period", "Status"]
    assert ts.kpi_labels == ["Reports sent (30d)", "Scheduled", "Sheets synced"]
    assert ts.primary_label == "Build report"
    assert ts.primary_icon == "summarize"
    assert ts.table_title == "Recent reports"
    assert ts.table_icon == "summarize"


def test_reporting_service_constant_matches_tools_ts() -> None:
    from app.modules.tool_workspaces.service import WORKSPACE_TABLE_COLS_REPORTING

    assert read_tool_extra("reporting").table_cols == WORKSPACE_TABLE_COLS_REPORTING


async def test_reporting_tiles_are_honest_about_the_missing_schedule(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """0020 stores workbooks + the pushes that HAPPENED; no schedule table exists, so
    "Scheduled" must stay an em dash. "Sheets synced" filters on the synced state (1 of
    2 workbooks), so a plain row count would read 2 and this test names it."""
    adapter = next(a for a in _TOOL_ADAPTERS if a.tool_key == "reporting")
    body = await _fetch_workspace(app, client, adapter)
    tiles = {k["label"]: k["value"] for k in body["kpis"]}
    assert tiles["Reports sent (30d)"] == "48"
    assert tiles["Scheduled"] == "—"
    assert tiles["Sheets synced"] == "1"
    assert tiles["Sheets synced"] != "2"
    audit_push, content_push = body["table"]["rows"]
    # The report is NAMED from the module's own catalogue, not from the raw dataset key.
    assert audit_push[0] == "Audit scores"
    assert content_push[0] == "Content status"
    assert audit_push[2] == "June"  # the push's month
    assert audit_push[3] == {"v": "Sent", "tone": "ok"}


# --------------------------------------------------------------------------- #
# 13. task_board: the pinned literals (Part 8 Phase 2.5).
# --------------------------------------------------------------------------- #
def test_task_board_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("task_board")
    assert ts.table_cols == ["Task", "Client", "Assignee", "Status"]
    assert ts.kpi_labels == ["Open tasks", "In progress", "Done (30d)"]
    assert ts.primary_label == "New task"
    assert ts.primary_icon == "add_task"
    assert ts.table_title == "Team tasks"
    assert ts.table_icon == "checklist"


def test_task_board_service_constant_matches_tools_ts() -> None:
    from app.modules.tool_workspaces.service import WORKSPACE_TABLE_COLS_TASK_BOARD

    assert read_tool_extra("task_board").table_cols == WORKSPACE_TABLE_COLS_TASK_BOARD


async def test_task_board_rows_name_the_assignee_and_flag_the_unassigned(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """The Assignee column renders the JOINED roster name (never the raw uuid), and an
    unassigned task says so rather than rendering an empty cell."""
    adapter = next(a for a in _TOOL_ADAPTERS if a.tool_key == "task_board")
    body = await _fetch_workspace(app, client, adapter)
    in_progress, todo = body["table"]["rows"]
    assert in_progress[2] == "Bilal"
    assert in_progress[3] == {"v": "In progress", "tone": "info"}
    assert todo[2] == "Unassigned"
    assert todo[3] == {"v": "To do", "tone": "mut"}
    tiles = {k["label"]: k["value"] for k in body["kpis"]}
    assert tiles["Open tasks"] == "2"  # neither fake task is done
    assert tiles["In progress"] == "1"
    assert tiles["Done (30d)"] == "0"


# --------------------------------------------------------------------------- #
# 14. client_setup: the pinned literals (Part 8 Phase 2.5).
# --------------------------------------------------------------------------- #
def test_client_setup_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("client_setup")
    assert ts.table_cols == ["Website", "Client", "CMS", "Status"]
    assert ts.kpi_labels == ["Clients", "Websites", "Pending setup"]
    assert ts.primary_label == "Add website"
    assert ts.primary_icon == "add_business"
    assert ts.table_title == "Websites"
    assert ts.table_icon == "add_business"


def test_client_setup_service_constant_matches_tools_ts() -> None:
    from app.modules.tool_workspaces.service import WORKSPACE_TABLE_COLS_CLIENT_SETUP

    assert read_tool_extra("client_setup").table_cols == WORKSPACE_TABLE_COLS_CLIENT_SETUP


async def test_client_setup_pending_tile_counts_clients_with_no_website(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """"Pending setup" is the checkable meaning of not-set-up: of 3 fake clients, only
    cl-3 has no site -> 1. The CMS cell renders the product spelling, not the raw
    lowercase column."""
    adapter = next(a for a in _TOOL_ADAPTERS if a.tool_key == "client_setup")
    body = await _fetch_workspace(app, client, adapter)
    tiles = {k["label"]: k["value"] for k in body["kpis"]}
    assert tiles["Clients"] == "3"
    assert tiles["Websites"] == "2"
    assert tiles["Pending setup"] == "1"
    wp, webflow = body["table"]["rows"]
    assert wp[2] == "WordPress"  # stored 'wordpress'
    assert wp[3] == {"v": "Active", "tone": "ok"}
    assert webflow[2] == "Webflow"
    assert webflow[3] == {"v": "Trial", "tone": "info"}


# --------------------------------------------------------------------------- #
# 15. key_vault: the pinned literals (Part 8 Phase 2.5). THE SENSITIVE ONE - the
# leak proofs live in tests/modules/tool_workspaces/test_key_vault_safety.py.
# --------------------------------------------------------------------------- #
def test_key_vault_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("key_vault")
    assert ts.table_cols == ["Provider", "Scope", "Last rotated", "Status"]
    assert ts.kpi_labels == ["Keys stored", "Integrations", "Rotating soon"]
    assert ts.primary_label == "Add key"
    assert ts.primary_icon == "key"
    assert ts.table_title == "Keys & integrations"
    assert ts.table_icon == "key"


def test_key_vault_service_constant_matches_tools_ts() -> None:
    from app.modules.tool_workspaces.service import WORKSPACE_TABLE_COLS_KEY_VAULT

    assert read_tool_extra("key_vault").table_cols == WORKSPACE_TABLE_COLS_KEY_VAULT


async def test_key_vault_never_invents_a_rotation_warning(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """No rotation cadence/expiry is stored anywhere, so "Rotating soon" must stay an em
    dash: a fabricated rotation warning on a credentials screen is a fiction an operator
    would act on. "Integrations" counts DISTINCT providers."""
    adapter = next(a for a in _TOOL_ADAPTERS if a.tool_key == "key_vault")
    body = await _fetch_workspace(app, client, adapter)
    tiles = {k["label"]: k["value"] for k in body["kpis"]}
    assert tiles["Keys stored"] == "2"
    assert tiles["Integrations"] == "2"
    assert tiles["Rotating soon"] == "—"
    rotated, never = body["table"]["rows"]
    assert rotated[2] == "May 2026"  # updated_at moved past created_at -> rotated
    # An untouched row still carries its INSERT stamp; that is not a rotation.
    assert never[2] == "Never"
    assert never[2] != "Apr 2026"


# --------------------------------------------------------------------------- #
# 16. team_access: the pinned literals (Part 8 Phase 2.5).
# --------------------------------------------------------------------------- #
def test_team_access_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("team_access")
    assert ts.table_cols == ["Member", "Role", "Status", "Tasks"]
    assert ts.kpi_labels == ["Members", "Roles", "Pending invites"]
    assert ts.primary_label == "Invite member"
    assert ts.primary_icon == "group_add"
    assert ts.table_title == "Members"
    assert ts.table_icon == "admin_panel_settings"


def test_team_access_service_constant_matches_tools_ts() -> None:
    from app.modules.tool_workspaces.service import WORKSPACE_TABLE_COLS_TEAM_ACCESS

    assert read_tool_extra("team_access").table_cols == WORKSPACE_TABLE_COLS_TEAM_ACCESS


async def test_team_access_tasks_column_is_the_real_metric(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """The Tasks cell is the 7F-3 active-task metric; a member with no metrics row is
    all-zero (not absent). "Roles" is the governance role SET, not the roles in use -
    two fake members hold two roles, but six roles exist to be granted."""
    from app.rbac import ROLE_ORDER

    adapter = next(a for a in _TOOL_ADAPTERS if a.tool_key == "team_access")
    body = await _fetch_workspace(app, client, adapter)
    tiles = {k["label"]: k["value"] for k in body["kpis"]}
    assert tiles["Members"] == "2"
    assert tiles["Roles"] == str(len(ROLE_ORDER)) == "6"
    assert tiles["Pending invites"] == "1"
    active, invited = body["table"]["rows"]
    assert active[1] == "Manager"  # the capitalized display role
    assert active[2] == {"v": "Active", "tone": "ok"}
    assert active[3] == "6"
    assert invited[2] == {"v": "Invited", "tone": "info"}
    assert invited[3] == "0"  # absent from the metrics map -> all-zero, never blank
