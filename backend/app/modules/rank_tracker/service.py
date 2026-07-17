"""Rank-tracker orchestration - the PURE analysis core + the tool-workspace adapter +
the N-A subscription cost projection.

This module is DB-free and network-free (mirrors ``keyword_research``'s pure core): it
takes rows and turns them into movement verdicts, KPI tiles, and a priced monthly
commitment - all deterministic given the same inputs. The cost-gated fetch + the DB
writes live in ``tasks.py``; the RLS reads live in ``repo.py``; this layer just reasons.

Three decisions here are deliberate and worth reading before changing them:

1. **Average position counts RANKED rows ONLY** (``latest_position is not null``). An
   unranked keyword has no position to average - and the alternatives are all worse:
   treating it as 0 would make an unranked term look better than #1, and treating it as
   the window floor (100) would make the tile lurch every time a long-tail term drops
   in or out of the top 100. So the tile answers "where do we rank, where we rank",
   and ``tracked`` (which counts everything) is the honest denominator beside it.
   An all-unranked book therefore averages 0.0, which the tile renders as an em-dash.

2. **change = previous_position - latest_position.** Rank is inverted (smaller is
   better), so an IMPROVEMENT is a DECREASE and the subtraction is this way round on
   purpose: 7 -> 3 yields +4 = "up 4 places". Getting this backwards is the classic
   rank-tracker bug - it reports every recovery as a fall.

3. **The N-A commitment gate.** Rank tracking is the platform's first STANDING
   per-client cost (audits/content are on-demand; this runs nightly forever) and the
   CLIENT pays. Gating only the individual check would let the agency commit a client
   to a runaway bill one keyword at a time and only discover it on the invoice. So
   ``project_monthly_cost`` prices the whole active book and ``evaluate_projection``
   refuses an add that would breach the client's remaining budget - at configuration
   time, in the add's own response.

``build_workspace`` is the ``GET /rank-tracker/workspace`` adapter: it emits the
frontend ``lib/tools.ts`` ``rank_tracker`` EXTRA shape with table columns pinned
EXACTLY to ``["Keyword", "Client", "Position", "Change"]`` (the tool-workspace contract
test asserts this byte-for-byte).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.modules.rank_tracker.schemas import (
    RankChange,
    RankCostProjection,
    RankKeywordResponse,
    RankStats,
)
from app.schemas.tool_workspace import (
    ToolCell,
    ToolCellObj,
    ToolExtraResponse,
    ToolKpi,
    ToolPrimary,
    ToolTable,
)

# --- cadence arithmetic -------------------------------------------------------
# The average Gregorian month (365.25 / 12). Using a flat 30 would under-price the
# commitment by ~1.5% every month - small per keyword, real across a 1k-keyword book,
# and always in the direction that surprises the client.
_DAYS_PER_MONTH = 365.25 / 12

# Days between checks per cadence. This IS the schedule the worker advances
# ``next_check_on`` by, so pricing and scheduling can never drift apart.
CADENCE_INTERVAL_DAYS: dict[str, int] = {"daily": 1, "weekly": 7}
_DEFAULT_CADENCE = "weekly"

# --- staleness ----------------------------------------------------------------
# A subscription is STALE when its last successful check is older than this multiple of
# its cadence window. 2x tolerates one missed night (a transient vendor blip) without
# crying wolf, while still surfacing a genuinely stalled tracker within a day or two -
# which is what makes a blocked money-dial visible instead of silent.
STALE_CADENCE_MULTIPLIER = 2.0

# --- tool-workspace contract constants (pinned to lib/tools.ts rank_tracker) ---
WORKSPACE_TABLE_COLS: list[str] = ["Keyword", "Client", "Position", "Change"]
_WORKSPACE_TABLE_TITLE = "Keyword movements"
_WORKSPACE_TABLE_ICON = "trending_up"
_WORKSPACE_PRIMARY = ToolPrimary(label="Add keywords", icon="add")
_WORKSPACE_BULLETS = [
    "Track keyword positions daily",
    "See ranking history & trends",
    "Group keywords by client & intent",
]
_WORKSPACE_ROW_LIMIT = 8

# The arrows the workspace table renders (verbatim from lib/tools.ts rows).
_ARROW_UP = "▲"  # a filled up-triangle: the position IMPROVED
_ARROW_DOWN = "▼"  # a filled down-triangle: the position WORSENED


# --------------------------------------------------------------------------- #
# Movement.
# --------------------------------------------------------------------------- #
def rank_change(previous: int | None, latest: int | None) -> RankChange:
    """The movement from ``previous`` to ``latest``.

    Rank is INVERTED (smaller is better), so the delta is ``previous - latest`` and a
    POSITIVE delta means the keyword climbed. The four ``None`` combinations each mean
    something different and are all distinguished:

    * ``None -> n``  : it ranked for the first time -> ``new``.
    * ``n -> None``  : it fell out of the tracked window -> ``lost``.
    * ``None -> None``: never ranked; there is no movement to report -> ``flat`` 0.
    * ``n -> n``     : no change -> ``flat`` 0.
    """
    if previous is None and latest is None:
        return RankChange(value="0", direction="flat")
    if previous is None:
        return RankChange(value="new", direction="new")
    if latest is None:
        return RankChange(value="lost", direction="lost")
    delta = previous - latest
    if delta == 0:
        return RankChange(value="0", direction="flat")
    return RankChange(value=str(abs(delta)), direction="up" if delta > 0 else "down")


def change_for_row(row: dict[str, Any]) -> RankChange:
    """The movement of one ``tracked_keywords`` row (its denormalised read model)."""
    return rank_change(_opt_int(row.get("previous_position")), _opt_int(row.get("latest_position")))


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Staleness - the visible half of the degrade path.
# --------------------------------------------------------------------------- #
def is_stale(row: dict[str, Any], *, now: datetime | None = None) -> bool:
    """Whether this subscription's nightly check has stalled.

    A gate block (money-dial off, budget cap reached, spend-stop engaged) DEGRADES: no
    provider call, an honest $0, and the position simply stays put. That is the right
    behaviour - but on its own it is INVISIBLE: the board would keep showing last
    week's position as though it were fresh. This is the read-side signal that makes
    the stall legible.

    Only ACTIVE subscriptions can be stale: a paused one is not supposed to be
    checked, so calling it stale would be crying wolf about a deliberate decision. A
    never-checked active row is stale by definition (its check has not landed yet).
    """
    if str(row.get("status") or "") != "active":
        return False
    checked_at = row.get("latest_checked_at")
    if checked_at is None:
        return True
    if not isinstance(checked_at, datetime):
        return False  # unparseable stamp: do not invent a stall
    cadence = str(row.get("cadence") or _DEFAULT_CADENCE)
    window = CADENCE_INTERVAL_DAYS.get(cadence, CADENCE_INTERVAL_DAYS[_DEFAULT_CADENCE])
    reference = now or datetime.now(UTC)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=UTC)
    age_days = (reference - checked_at).total_seconds() / 86_400
    return age_days > window * STALE_CADENCE_MULTIPLIER


def to_response(row: dict[str, Any], *, now: datetime | None = None) -> RankKeywordResponse:
    """One ``tracked_keywords`` row -> the wire shape (movement + staleness computed)."""
    return RankKeywordResponse.from_row(
        row, change=change_for_row(row), stale=is_stale(row, now=now)
    )


# --------------------------------------------------------------------------- #
# KPI maths.
# --------------------------------------------------------------------------- #
def average_position(rows: list[dict[str, Any]]) -> float:
    """The mean position across the RANKED rows only (see this module's docstring).

    Returns 0.0 when nothing ranks - the caller renders that as an em-dash rather than
    as "position 0", which would read as better than #1.
    """
    ranked = [p for p in (_opt_int(r.get("latest_position")) for r in rows) if p is not None]
    if not ranked:
        return 0.0
    return round(sum(ranked) / len(ranked), 1)


def top_three(rows: list[dict[str, Any]]) -> int:
    """How many tracked keywords sit in the top 3 (the positions that earn clicks)."""
    return sum(
        1
        for r in rows
        if (p := _opt_int(r.get("latest_position"))) is not None and p <= 3
    )


def build_stats(rows: list[dict[str, Any]]) -> RankStats:
    """The summary tiles computed from a row set (the pure twin of the repo's SQL
    aggregate - used where the caller already holds the rows, and the reference the
    repo's aggregate is unit-pinned against)."""
    return RankStats(
        tracked=len(rows), avg_position=average_position(rows), top_three=top_three(rows)
    )


# --------------------------------------------------------------------------- #
# N-A: the subscription-time cost projection.
# --------------------------------------------------------------------------- #
def checks_per_month(cadence: str) -> float:
    """How many checks one keyword on ``cadence`` costs per month.

    Derived from the SAME ``CADENCE_INTERVAL_DAYS`` the worker schedules by, so the
    price and the schedule can never drift. daily ~= 30.44, weekly ~= 4.35. An unknown
    cadence prices as the default rather than as free - an unpriced subscription is the
    one that shows up as a surprise on the invoice.
    """
    interval = CADENCE_INTERVAL_DAYS.get(cadence, CADENCE_INTERVAL_DAYS[_DEFAULT_CADENCE])
    return round(_DAYS_PER_MONTH / interval, 4)


def project_monthly_cost(cadence_counts: dict[str, int], cost_per_check: float) -> float:
    """The client's standing monthly rank-tracking bill.

    ``SUM over active keywords of checks_per_month(cadence) x cost_per_check`` - taken
    over ``{cadence: count}`` so the caller can price the CURRENT book, or the book as
    it WOULD BE after an add, with the same function.
    """
    total = sum(
        count * checks_per_month(cadence) * cost_per_check
        for cadence, count in cadence_counts.items()
        if count > 0
    )
    return round(total, 4)


def merge_cadence_counts(current: dict[str, int], adding: dict[str, int]) -> dict[str, int]:
    """The book as it WOULD be after ``adding`` - what the commitment gate prices.

    Pricing only the keywords being added would let a client be walked past their cap
    in small batches, each of which looks affordable on its own.
    """
    merged = dict(current)
    for cadence, count in adding.items():
        merged[cadence] = merged.get(cadence, 0) + count
    return merged


def apply_subscription_change(
    counts: dict[str, int], *, before: tuple[str, str], after: tuple[str, str]
) -> dict[str, int]:
    """The client's ACTIVE book after ONE subscription changes status and/or cadence.

    ``before``/``after`` are ``(status, cadence)`` pairs. Only ACTIVE rows cost
    anything, so a pause removes the row from the book and a resume re-adds it.

    This exists because the add-time gate alone is not a gate. Re-pricing only on ADD
    would leave two ways to raise a client's standing bill without anyone re-checking
    the budget:

    * flip an existing keyword weekly -> daily (SEVEN times the monthly cost), or
    * resume a paused subscription (from $0 back to a full cadence).

    Either one walks straight past a cap that the add was refused for.
    """
    out = dict(counts)
    before_status, before_cadence = before
    after_status, after_cadence = after
    if before_status == "active":
        out[before_cadence] = max(out.get(before_cadence, 0) - 1, 0)
    if after_status == "active":
        out[after_cadence] = out.get(after_cadence, 0) + 1
    return out


def evaluate_projection(
    *,
    client_name: str,
    cadence_counts: dict[str, int],
    cost_per_check: float,
    budget: tuple[float, float] | None,
    provider: str,
    live: bool,
) -> RankCostProjection:
    """Price the client's active book and judge it against their remaining budget.

    ``budget`` is the gate's own ``(cap, spent)`` pair, or ``None`` when the client has
    no budget row. Two cases are deliberately treated as UNCAPPED (``within_budget``
    True): no budget row at all, and ``cap == 0`` - which the 0006 schema documents as
    "0 = uncapped". Inventing a limit where ops set none would block legitimate work.

    When the projected monthly commitment exceeds what is left of the cap, this reports
    ``within_budget=False`` with a message naming both numbers, and the router refuses
    the add. That is the whole point of N-A: the refusal lands at CONFIGURATION time,
    when a human is present to decide, not at 2am on the 40th nightly check.
    """
    tracked = sum(cadence_counts.values())
    monthly = project_monthly_cost(cadence_counts, cost_per_check)
    total_checks = round(
        sum(count * checks_per_month(cadence) for cadence, count in cadence_counts.items()), 2
    )
    cap, spent = (budget if budget is not None else (0.0, 0.0))
    uncapped = budget is None or cap <= 0
    remaining = 0.0 if uncapped else round(max(cap - spent, 0.0), 4)
    within = True if uncapped else monthly <= remaining

    if not live:
        message = (
            f"Rank checks are running on the simulated provider ('{provider}'), so this "
            f"book is projected at $0.00/mo. Configure the live provider's key before "
            f"quoting this commitment to the client."
        )
    elif uncapped:
        message = (
            f"{tracked} active keyword(s) commit {client_name or 'this client'} to about "
            f"${monthly:,.2f}/mo in rank checks. No monthly cap is set for this client."
        )
    elif within:
        message = (
            f"{tracked} active keyword(s) commit {client_name or 'this client'} to about "
            f"${monthly:,.2f}/mo in rank checks, within the ${remaining:,.2f} left of "
            f"their ${cap:,.2f} monthly cap."
        )
    else:
        message = (
            f"Rejected: {tracked} active keyword(s) would commit "
            f"{client_name or 'this client'} to about ${monthly:,.2f}/mo in rank checks, "
            f"but only ${remaining:,.2f} of their ${cap:,.2f} monthly cap is left. "
            f"Raise the cap, reduce the cadence, or track fewer keywords."
        )

    return RankCostProjection(
        client=client_name,
        tracked=tracked,
        daily=cadence_counts.get("daily", 0),
        weekly=cadence_counts.get("weekly", 0),
        checks_per_month=total_checks,
        cost_per_check=round(cost_per_check, 6),
        monthly_cost=monthly,
        budget_cap=round(cap, 2),
        budget_spent=round(spent, 2),
        budget_remaining=remaining,
        within_budget=within,
        provider=provider,
        live=live,
        message=message,
    )


# --------------------------------------------------------------------------- #
# The /workspace adapter (frontend lib/tools.ts rank_tracker EXTRA shape).
# --------------------------------------------------------------------------- #
def _position_cell(position: int | None) -> ToolCell:
    """The Position cell: the number, or an em-dash when unranked (never "0")."""
    return "—" if position is None else str(position)


def _change_cell(change: RankChange) -> ToolCellObj:
    """The Change cell: an arrow + magnitude with a tone.

    ``ok`` for an improvement, ``crit`` for a fall (a lost ranking is a fall too),
    ``info`` for a brand-new ranking, ``mut`` for no movement - matching the
    ``lib/tools.ts`` demo rows (``{v: "▲ 4", tone: "ok"}`` / ``{v: "▼ 3", tone: "crit"}``).
    """
    if change.direction == "up":
        return ToolCellObj(v=f"{_ARROW_UP} {change.value}", tone="ok")
    if change.direction == "down":
        return ToolCellObj(v=f"{_ARROW_DOWN} {change.value}", tone="crit")
    if change.direction == "new":
        return ToolCellObj(v="new", tone="info")
    if change.direction == "lost":
        return ToolCellObj(v="lost", tone="crit")
    return ToolCellObj(v="0", tone="mut")


def _keyword_row(row: dict[str, Any]) -> list[ToolCell]:
    """One workspace table row: [Keyword, Client, Position, Change] with tones."""
    change = change_for_row(row)
    return [
        str(row.get("keyword", "") or ""),
        str(row.get("client_name", "") or ""),
        _position_cell(_opt_int(row.get("latest_position"))),
        _change_cell(change),
    ]


def _avg_position_tile(stats: RankStats) -> str:
    """The Avg. position tile value - an em-dash when nothing ranks, so an empty book
    reads as "no data" rather than as a suspiciously perfect 0.0."""
    return "—" if stats.avg_position <= 0 else f"{stats.avg_position:.1f}"


def build_workspace(stats: RankStats, keywords: list[dict[str, Any]]) -> ToolExtraResponse:
    """Assemble the rank-tracker tool workspace (KPIs + movements table + CTA).

    KPI labels + the primary + the table columns are pinned to ``lib/tools.ts``; the
    columns are EXACTLY ``["Keyword", "Client", "Position", "Change"]`` (the
    tool-workspace contract test enforces byte-identity).
    """
    kpis = [
        ToolKpi(label="Tracked keywords", value=f"{stats.tracked:,}"),
        ToolKpi(label="Avg. position", value=_avg_position_tile(stats)),
        ToolKpi(label="Top-3 keywords", value=str(stats.top_three)),
    ]
    table = ToolTable(
        title=_WORKSPACE_TABLE_TITLE,
        icon=_WORKSPACE_TABLE_ICON,
        cols=list(WORKSPACE_TABLE_COLS),
        rows=[_keyword_row(r) for r in keywords[:_WORKSPACE_ROW_LIMIT]],
    )
    return ToolExtraResponse(
        kpis=kpis, table=table, primary=_WORKSPACE_PRIMARY, bullets=list(_WORKSPACE_BULLETS)
    )


def normalize_keyword(keyword: str) -> str:
    """The case/whitespace-folded form the ``tracked_keywords`` uniqueness key uses.

    "Plumber Karachi" and " plumber   karachi " are ONE subscription - and therefore
    ONE nightly bill - not two. Inner whitespace is collapsed too, so a stray double
    space cannot buy a duplicate.
    """
    return " ".join((keyword or "").split()).lower()
