"""Citation-builder orchestration (7B-4): PURE reasoning over catalog rows + a
business profile - no DB, no network (mirrors ``local_seo.service`` /
``web2_pipeline``'s plan stage). The privileged reads/writes live in ``repo.py``;
the actual submit calls live in ``integrations.citation_*``; this layer only
decides WHICH directories a campaign queues, WHAT it will cost, and WHICH engine a
queued row's ``submit_method`` routes to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import Settings
from app.modules.citations.schemas import (
    AUTOMATABLE_TIERS,
    DEFAULT_CAMPAIGN_CAP,
    DEFAULT_MIN_AUTHORITY,
)
from integrations.citation_submitters import CitationJob, CitationSubmitter

# core builds first everywhere, then tier1, then tier2 (the reference plan's build
# order); an unknown authority_tier sorts last with tier2.
_TIER_RANK: dict[str, int] = {"core": 0, "tier1": 1, "tier2": 2}


def is_prohibited(row: dict[str, Any]) -> bool:
    """Whether this directory may NEVER be submitted to by us.

    ``route = 'F'`` is the decision; ``tos_position`` is the evidence behind it. They
    are deliberately separate fields, because Google Business Profile and Apple are
    ``tos_position = 'prohibits'`` as BOT targets while remaining perfectly legitimate
    over their own authenticated APIs - those rows are route 'A' and must stay
    reachable. Blocking on `route` and not on `tos_position` is what keeps both true.

    Yelp, Trustpilot and Houzz publish clauses banning automated ACCESS and RETRIEVAL,
    and a form-filling bot must GET the form before it can fill it - so the clause binds
    us. This is a hard block in the worker, never a warning in the UI.

    Accepts either a catalog row (``route``) or the worker's joined citation row, where
    the directory's route is aliased ``directory_route`` because ``select c.*`` already
    supplies the CITATION's own ``route`` column. Reading a bare ``route`` off the joined
    row would read the citation's copy - which defaults to 'C' - and the guard would
    never fire. ``directory_route`` is preferred whenever it is present."""
    route = row.get("directory_route") if row.get("directory_route") is not None else row.get("route")
    return str(route or "").upper() == "F"


def automatable_directories(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every catalog row a campaign COULD queue - ``manual_only`` is filtered out
    here, once, so no caller has to remember the exclusion. A row fed by another
    aggregator (``submit_method`` starting ``aggregator:fed_by_``) is ALSO excluded:
    there is nothing to submit, it is already covered by seeding the core
    aggregator(s) it is fed from. A ``route = 'F'`` row is excluded because its terms
    forbid automated access outright (see ``is_prohibited``)."""
    return [
        r
        for r in rows
        if r.get("tier") in AUTOMATABLE_TIERS
        and not str(r.get("submit_method") or "").startswith("aggregator:fed_by_")
        and not is_prohibited(r)
    ]


@dataclass
class DirectorySelection:
    """The outcome of applying the reference-plan strategy to a catalog: the ORDERED
    rows to queue, plus a transparent count of what each rule excluded (so a capped or
    filtered batch is never a silent truncation - the counts surface to the operator)."""

    selected: list[dict[str, Any]] = field(default_factory=list)
    excluded_off_vertical: int = 0
    excluded_low_authority: int = 0
    excluded_marketplace: int = 0
    capped: int = 0
    # One record per row NOT selected: {"directory", "reason", "detail"}. The counts
    # above say HOW MANY; this says WHICH and WHY, which is what a client reads when
    # they compare "100 promised" against "45 delivered". A count alone cannot answer
    # "so what happened to Yelp?".
    skipped: list[dict[str, str]] = field(default_factory=list)


def _serves_vertical(row: dict[str, Any], vertical: str | None) -> bool:
    """A directory serves a client when it is GENERAL (no verticals = applies to all)
    or explicitly names the client's vertical. With no resolved vertical we keep only
    general rows - never blast a niche directory at an unknown industry."""
    verticals = row.get("verticals") or []
    if not verticals:
        return True
    return vertical is not None and vertical in verticals


def select_campaign_directories(
    rows: list[dict[str, Any]],
    *,
    vertical: str | None = None,
    cap: int | None = DEFAULT_CAMPAIGN_CAP,
    min_authority: int | None = DEFAULT_MIN_AUTHORITY,
    include_marketplaces: bool = False,
) -> DirectorySelection:
    """Apply the reference-plan selection to already-automatable rows: match the
    client's vertical, drop the sub-DA spam tail, optionally exclude lead-gen
    marketplaces, order by build-tier then authority, and cap the batch.

    Ordering: authority_tier (core -> tier1 -> tier2) then authority DESC (a scored
    row outranks a lower-scored one; an UNSCORED row - authority NULL - sorts after
    scored rows within its tier rather than being dropped) then name for stability.
    Every exclusion is counted, so ``cap`` and the filters are transparent, not silent.
    """
    result = DirectorySelection()
    kept: list[dict[str, Any]] = []

    def _skip(row: dict[str, Any], reason: str, detail: str = "") -> None:
        result.skipped.append(
            {"directory": str(row.get("name") or ""), "reason": reason, "detail": detail}
        )

    for row in rows:
        if not _serves_vertical(row, vertical):
            result.excluded_off_vertical += 1
            _skip(row, "off_vertical", f"serves {', '.join(row.get('verticals') or [])}")
            continue
        if not include_marketplaces and bool(row.get("is_marketplace")):
            result.excluded_marketplace += 1
            _skip(row, "marketplace_not_opted_in", "lead-gen marketplace; operator must opt in")
            continue
        da = row.get("authority")
        if min_authority is not None and da is not None and int(da) < min_authority:
            result.excluded_low_authority += 1
            _skip(row, "below_authority_floor", f"authority {da} < {min_authority}")
            continue
        kept.append(row)

    def _sort_key(r: dict[str, Any]) -> tuple[int, int, str]:
        rank = _TIER_RANK.get(str(r.get("authority_tier") or "tier2"), 2)
        da = r.get("authority")
        # higher DA first -> negate; unscored (None) -> 0 so it sits just below any
        # positive-DA row in the same tier but above genuinely low-DA ones.
        da_key = -int(da) if da is not None else 0
        return (rank, da_key, str(r.get("name") or ""))

    kept.sort(key=_sort_key)

    if cap and cap > 0 and len(kept) > cap:
        result.capped = len(kept) - cap
        for row in kept[cap:]:
            _skip(row, "over_campaign_cap", f"batch capped at {cap}; queued in a later campaign")
        kept = kept[:cap]

    result.selected = kept
    return result


# The reasons a catalog row never reaches a campaign. `select_campaign_directories`
# emits the client-specific ones; `catalog_skips` below emits the ones that are true of
# the directory itself, whoever the client is.
SKIP_REASON_LABELS: dict[str, str] = {
    "prohibited_by_terms": "the directory's terms forbid automated submission",
    "fed_by_aggregator": "covered by an aggregator we already submit to - no separate listing",
    "not_automatable": "no automated submission path; handled by a human",
    "off_vertical": "serves industries this client is not in",
    "marketplace_not_opted_in": "a paid lead-gen marketplace; not built without opt-in",
    "below_authority_floor": "authority below the floor we build to",
    "over_campaign_cap": "beyond this campaign's size cap; queued in a later one",
}


# The upstream sources a `aggregator:fed_by_*` row is fed from. Matched LONGEST-FIRST,
# because the source names contain underscores themselves - a naive
# `replace("_", ", ")` turns `fed_by_data_axle_foursquare` into the nonsense
# "data, axle, foursquare", which is what a client would then read in their report.
_FED_BY_SOURCES: tuple[tuple[str, str], ...] = (
    ("data_axle", "Data Axle"),
    ("foursquare", "Foursquare"),
    ("neustar", "Neustar"),
)


def _fed_by_label(submit_method: str) -> str:
    """"aggregator:fed_by_data_axle_foursquare" -> "Data Axle, Foursquare"."""
    rest = submit_method.replace("aggregator:fed_by_", "")
    found = [label for token, label in _FED_BY_SOURCES if token in rest]
    return ", ".join(found) if found else rest.replace("_", " ")


def catalog_skips(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Why each catalog row is not automatable, for rows `automatable_directories`
    drops. These reasons belong to the DIRECTORY, not to the client, so they are the
    same in every client's report - and every one of them must still be REPORTED, or a
    client comparing a promised count against a delivered one has nowhere to look.

    A prohibited row is reported WITH its clause and source URL: "we did not submit to
    Yelp, here is the sentence that says we must not" is a far better answer than a
    silently shorter list."""
    out: list[dict[str, str]] = []
    for row in rows:
        name = str(row.get("name") or "")
        if is_prohibited(row):
            out.append(
                {
                    "directory": name,
                    "reason": "prohibited_by_terms",
                    "detail": str(row.get("tos_source_url") or ""),
                    "clause": str(row.get("tos_clause") or ""),
                }
            )
        elif str(row.get("submit_method") or "").startswith("aggregator:fed_by_"):
            out.append(
                {
                    "directory": name,
                    "reason": "fed_by_aggregator",
                    "detail": f"fed by {_fed_by_label(str(row.get('submit_method') or ''))}",
                }
            )
        elif row.get("tier") not in AUTOMATABLE_TIERS:
            out.append(
                {
                    "directory": name,
                    "reason": "not_automatable",
                    "detail": f"tier={row.get('tier')}",
                }
            )
    return out


def is_live_directory_response(status_code: int | None) -> bool:
    """Whether an HTTP status from a catalog URL health-check means the directory is
    still LIVE (reference plan step 7: "verify live at submission - directory churn is
    high, many 2019-era entries are parked or dead"). A 2xx/3xx (redirects to a live
    page) is live; a 4xx/5xx or an unreachable host (None) is treated as dead so the
    row can be deactivated rather than wasting a submission attempt on a parked domain.
    A 403/429 (bot-blocked but alive) is the one grey area - treated as LIVE, since the
    domain answered, to avoid deactivating a real directory that merely refused a HEAD.
    """
    if status_code is None:
        return False
    if status_code in (403, 429):
        return True
    return 200 <= status_code < 400


def estimate_campaign_cost(rows: list[dict[str, Any]], settings: Settings) -> float:
    """The R5 pre-check total for a batch of directory rows, BEFORE any submit runs -
    a lead sees this total up front rather than discovering the spend after the fact.
    (The ``citations`` dial actually defaults to ``api`` — a recorded client decision;
    the per-row cost gate inside the worker is what bounds the spend.)

    An ``api``/``aggregator`` row prices at the Data Axle Add estimate, which is **0.0
    until a real rate card is on file**. That is not a claim those submissions are free -
    it is that they are BLOCKED (``settings.data_axle_submits_enabled`` is False), so
    they contribute nothing because they will not run. The moment a price is configured
    the estimate becomes real and the batch total moves with it. The old
    ``citation_api_cost_estimate`` was deleted with the Bing/Foursquare submitters: it
    priced calls to endpoints that return 404."""
    total = 0.0
    for row in rows:
        tier = row.get("tier")
        if tier in ("api", "aggregator"):
            total += settings.data_axle_add_cost_estimate
        elif tier == "bot_fillable":
            total += settings.citation_bot_cost_estimate
        elif tier == "captcha_assisted":
            total += settings.citation_captcha_cost_estimate
    return round(total, 4)


def submit_method_label(directory: dict[str, Any]) -> str:
    """The ``submit_method`` string stored on a queued citation row - copied
    verbatim from the catalog so the worker's dispatch (``submitter_for`` below)
    only ever has to read the citation row, never re-join the catalog to redecide."""
    return str(directory.get("submit_method") or "")


def submitter_for(
    submit_method: str,
    *,
    api_submitters: dict[str, CitationSubmitter],
    bot: CitationSubmitter | None,
    signup_bot: CitationSubmitter | None = None,
) -> tuple[CitationSubmitter | None, str]:
    """Pick the engine one queued row's ``submit_method`` routes to.

    Returns ``(submitter, reason)`` - ``reason`` is only meaningful when
    ``submitter`` is ``None`` (why nothing could be dispatched: an unconfigured
    engine, or a directory that needs no separate action at all). Never raises -
    an unrecognised ``submit_method`` is a clean "no engine", not a crash.

    ``bot:signup`` routes to the account-creation+email-verify engine (``signup_bot``,
    ``integrations.citation_signup``); the plain ``bot:``/``aggregator:`` public-form
    path (``bot``) is unchanged. ``bot:signup`` is matched BEFORE the generic ``bot:``
    prefix so a signup directory never falls through to the no-signup engine.
    """
    if submit_method.startswith("aggregator:fed_by_"):
        return None, "no action needed - covered by seeding the core aggregator(s)"
    if submit_method.startswith("api:"):
        key = submit_method.split(":", 1)[1]
        sub = api_submitters.get(key)
        if sub is not None:
            return sub, ""
        return None, f"no API submitter configured for {key!r}"
    if submit_method.startswith("bot:signup"):
        if signup_bot is not None:
            return signup_bot, ""
        return None, "signup bot not configured (no IMAP mailbox / mail domain / Playwright)"
    if submit_method.startswith("aggregator:") or submit_method.startswith("bot:"):
        if bot is not None:
            return bot, ""
        return None, "Playwright bot not installed/configured"
    # `manual` and `closed` are DECISIONS, not gaps, and they read differently to an
    # operator: the first means a human submits this one, the second means the directory
    # takes no submissions at all. Before 0115 both fell through to "no automatable
    # engine for submit_method='manual'", which reads as a bug in the dispatcher rather
    # than the catalogue saying what it meant.
    if submit_method == "manual":
        return None, "manual submission only - queued for an operator"
    if submit_method == "closed":
        return None, "directory is closed to new submissions"
    return None, f"no automatable engine for submit_method={submit_method!r}"


# --------------------------------------------------------------------------- #
# Where a row goes when the machine cannot submit it.
#
# THE DEFECT THIS CLOSES. `ready_for_human` has existed since 0064, 0110 indexed it, and
# `CitationQueueRepo.claim` selects on it - but MEASURED 2026-08-30, no code path in this
# repo ever wrote it. Every unautomatable row went to `blocked` and stopped there, so the
# operator queue, its seven routes, the Chrome extension and the pairing page all read a
# status that nothing produced. The human path - the ONLY path that works today, with zero
# earned specs and no aggregator credentials - had no input.
#
# `blocked` and `ready_for_human` are genuinely different facts and the distinction is the
# product: `blocked` means NOBODY should act, `ready_for_human` means a machine cannot but
# a person can, in their own browser, in their own session. Collapsing them loses the
# 176 bot-tier directories that a human can work by hand today.
# --------------------------------------------------------------------------- #

# Reasons where a human in a real browser is exactly the right answer. Each one means the
# ENGINE is missing or unverified - never that the submission itself is unwanted.
_HUMAN_WORKABLE_REASONS: frozenset[str] = frozenset({
    "no_engine",         # no dispatcher for this method, or the engine is unconfigured
    "no_verified_spec",  # the bot has no earned spec; a person does not need one
    "captcha",           # a workflow boundary by policy - the operator solves it themselves
    "waf_403",           # the site refused a scripted client; a real session is not scripted
    "account_gated",     # the form needs a login the operator holds
})

# Reasons where handing the row to a person would be wrong, not merely unhelpful.
_NOT_HUMAN_WORKABLE_REASONS: frozenset[str] = frozenset({
    "tos_prohibits",   # route F. A human retrieving the form is the same prohibited act.
    "fed_by_aggregator",  # nothing to submit - the listing arrives via the core feed
    "no_nap",          # there is no business profile to submit; fix the data, not the row
    "price_unknown",   # an unpriced Add is a SPEND decision for a lead, not queue work
})

# ONE KNOWN AMBIGUOUS ROW, left as human work deliberately. `BuildZoom`
# (`aggregator:contractor_license_autogen`) says "Profiles auto-created from public
# contractor-license records", which MIGHT mean there is nothing to submit - or might mean
# a profile can be claimed. R1 hand-verified 12 directories and this was not one of them,
# so calling it `closed` here would be a guess dressed as a fact, which is the failure this
# module was rebuilt to remove. An operator opening it once and finding out costs about
# thirty seconds and produces a real answer to record.


def disposition_for_block(reason_code: str) -> str:
    """``'ready_for_human'`` or ``'blocked'`` for a row the machine could not submit.

    Unknown reasons fall to ``blocked``, deliberately. A new failure mode should not
    silently start generating human work whose value nobody has assessed - and a row
    sitting in `blocked` with an honest reason is visible, whereas a queue full of items
    an operator cannot actually complete destroys trust in the queue itself.
    """
    if reason_code in _HUMAN_WORKABLE_REASONS:
        return "ready_for_human"
    return "blocked"


# --------------------------------------------------------------------------- #
# NAP bridge: derive a submission business_profile from the client's own NAP
# (client_business_profiles, 0051). PURE - the repo does the actual insert.
# --------------------------------------------------------------------------- #
def derive_business_profile_fields(client_nap: dict[str, Any]) -> dict[str, Any]:
    """Map a ``client_business_profiles`` row (the client's identity captured at
    creation) onto the column dict for a ``business_profiles`` SUBMISSION row.

    The primary category leads the ordered ``categories`` list (a listing form fills
    the primary first), then the extras. ``label``/``is_primary`` mark it the client's
    canonical location. This is why "No business profile yet for this client" no longer
    dead-ends: the citation-builder derives its first submission profile from the NAP the
    wizard already collected, instead of demanding the operator re-enter it."""
    primary = str(client_nap.get("primary_category") or "").strip()
    extras = [str(c).strip() for c in (client_nap.get("extra_categories") or []) if str(c).strip()]
    categories = ([primary] if primary else []) + [c for c in extras if c != primary]
    hours = client_nap.get("hours")
    return {
        "label": "Primary",
        "business_name": str(client_nap.get("business_name") or ""),
        "address_line1": str(client_nap.get("address_line1") or ""),
        "address_line2": str(client_nap.get("address_line2") or ""),
        "city": str(client_nap.get("city") or ""),
        "region": str(client_nap.get("region") or ""),
        "postal_code": str(client_nap.get("postal_code") or ""),
        # GLOBAL, not US, when the market was never set.
        #
        # MEASURED 2026-08-30 with a Lahore business: an unset market defaulted to US, so
        # the campaign selected 138 US+GLOBAL directories and queued an operator to submit
        # a Pakistani business to YellowPages.com, Chamber of Commerce and BBB. That is
        # the fabrication class this module exists to remove - asserting a fact (this is a
        # US business) that nothing established.
        #
        # The asymmetry decides it: a WRONG listing is worse than a missing one. A US
        # directory entry for a Lahore business is NAP pollution - precisely the harm a
        # citation campaign is supposed to prevent - whereas GLOBAL-only is merely less
        # coverage, and the gap report says so by name. A US client whose market was never
        # recorded now sees a shorter list and an operator sets the market; a non-US client
        # no longer gets listings that should never have existed.
        "market": str(client_nap.get("market") or "GLOBAL"),
        "phone": str(client_nap.get("phone") or ""),
        "website_url": str(client_nap.get("website_url") or ""),
        "categories": categories,
        "hours": dict(hours) if isinstance(hours, dict) else {},
        "is_primary": True,
    }


# --------------------------------------------------------------------------- #
# Gap analysis: what is already cited vs what the catalog says is still missing.
# PURE (no DB, no network) so the whole decision is unit-testable.
# --------------------------------------------------------------------------- #
# A citation row DEDUPES its directory (keeps it out of `missing`) when it is in-flight
# or done; a blocked/failed/never-started+missing row does NOT (retryable - still a gap).
# `drifted` counts as done: the listing EXISTS, its NAP has merely gone stale, so the fix
# is a correction and not a fresh build. `delisted` does NOT: the listing is gone, and
# that directory is an open gap again.
#
# DONE vs IN-FLIGHT is the 2026-09-01 lesson. These used to be one set, so a row stuck
# at `queued` forever (no worker consumed its task) counted as COVERED and its directory
# rendered "built" - 45 refused rows read as 45 built listings. In-flight now dedupes
# (never re-offered to a campaign) but is REPORTED as its own thing, and an in-flight row
# whose `updated_at` has gone stale is reported as STUCK, never as coverage.
_DONE_SUBMIT: frozenset[str] = frozenset({"submitted", "verified", "live", "drifted"})
_IN_FLIGHT_SUBMIT: frozenset[str] = frozenset({"queued", "submitting"})
_COVERING_SUBMIT: frozenset[str] = _DONE_SUBMIT | _IN_FLIGHT_SUBMIT

#: An in-flight row older than this is STUCK. The dispatcher classifies a row in under a
#: second and a Playwright submit runs minutes, so a quarter hour of silence means the
#: pipeline, not the work.
DEFAULT_STUCK_AFTER_MINUTES = 15
# ONLY `live` earns a place in `live_urls`. `submitted` means a form was sent and nothing
# has confirmed a listing came back: Data Axle runs teleresearch for up to three business
# days, Apple returns state SUBMITTED, GBP needs verification before it appears at all,
# and a form bot only ever knows that a page changed. A row reaches `live` when
# services/citation_liveness.py has FETCHED live_url and found the business in it.
_LIVE_SUBMIT: frozenset[str] = frozenset({"live"})
_COVERING_NAP: frozenset[str] = frozenset({"consistent", "inconsistent"})


# Directory-name matching lives in a leaf module (app/services/directory_names.py):
# the off-page repo needs it too, and reaching it through `app.modules.citations`
# created an import cycle that only bit the worker. Re-exported so callers here read
# naturally.
from app.services.directory_names import canonical_norm  # noqa: E402


def _norm_directory(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())





def _row_covers(row: dict[str, Any]) -> bool:
    """Whether an existing citation counts as DELIVERED coverage of its directory. A
    monitoring row that FOUND a listing (nap consistent/inconsistent) covers it; a
    submission row that is done (submitted/verified/live/drifted) covers it; a
    blocked/failed row is an open gap; an in-flight row is neither (its caller reports
    it separately)."""
    submit = str(row.get("submit_status") or "not_started")
    nap = str(row.get("nap_status") or "")
    if submit in _DONE_SUBMIT:
        return True
    if submit in _IN_FLIGHT_SUBMIT:
        return False
    return submit not in ("failed", "blocked") and nap in _COVERING_NAP


def _mark_covered(row: dict[str, Any], ids: set[str], names: set[str]) -> None:
    did = row.get("directory_id")
    if did:
        ids.add(str(did))
    name = str(row.get("directory") or "")
    if name:
        names.add(canonical_norm(name))


def _is_stale(row: dict[str, Any], now: datetime | None, stuck_after_minutes: int) -> bool:
    """Whether an in-flight row has sat unmoved past the threshold. Without `now` (a
    caller that does not care about staleness) nothing is stale - the answer is then
    "unknown", and unknown must not read as stuck."""
    if now is None:
        return False
    updated = row.get("updated_at")
    if not isinstance(updated, datetime):
        return False
    anchored = updated if updated.tzinfo else updated.replace(tzinfo=UTC)
    return (now - anchored) >= timedelta(minutes=stuck_after_minutes)


@dataclass
class CitationGap:
    """The reconciliation of a client's existing citations against the automatable
    catalog: what is covered, what is still MISSING (the build target), the live listing
    URLs already earned, and an honest per-status tally."""

    existing_count: int = 0
    covered_count: int = 0
    # In-flight (queued/submitting, fresh): deduped from `missing` but NOT covered.
    in_flight_count: int = 0
    # In-flight rows whose updated_at went stale - the "no worker is consuming this"
    # signal, listed by name so an operator can say WHICH directories are wedged.
    stuck: list[dict[str, str]] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)
    live_urls: list[dict[str, str]] = field(default_factory=list)
    by_submit_status: dict[str, int] = field(default_factory=dict)
    by_nap_status: dict[str, int] = field(default_factory=dict)
    # Every catalog row NOT in `missing` and NOT already covered, each with a reason.
    # This is a required output, not a nicety: without it a shorter-than-promised list
    # is indistinguishable from a system that quietly failed.
    skipped: list[dict[str, str]] = field(default_factory=list)


def compute_citation_gap(
    *,
    directories: list[dict[str, Any]],
    existing_citations: list[dict[str, Any]],
    vertical: str | None = None,
    cap: int | None = DEFAULT_CAMPAIGN_CAP,
    min_authority: int | None = DEFAULT_MIN_AUTHORITY,
    include_marketplaces: bool = False,
    now: datetime | None = None,
    stuck_after_minutes: int = DEFAULT_STUCK_AFTER_MINUTES,
) -> CitationGap:
    """Reconcile existing citations against the catalog and report the gap.

    (a) analyse existing citations - count them + tally where they stand (per submit and
        per NAP status), and collect the live listing URLs already earned;
    (b) compute MISSING directories - apply the SAME reference-plan selection a campaign
        uses (vertical match, spam-tail floor, marketplace gate, build-order sort, cap),
        then subtract every directory already COVERED (matched by directory_id, else by
        normalized name so a legacy monitoring row with no directory_id still counts).

    The result's ``missing`` is exactly what "build only the missing ones" should queue,
    in build order (core -> tier1 -> tier2)."""
    gap = CitationGap(existing_count=len(existing_citations))

    covered_ids: set[str] = set()
    covered_names: set[str] = set()
    for row in existing_citations:
        submit = str(row.get("submit_status") or "not_started")
        nap = str(row.get("nap_status") or "unknown")
        gap.by_submit_status[submit] = gap.by_submit_status.get(submit, 0) + 1
        gap.by_nap_status[nap] = gap.by_nap_status.get(nap, 0) + 1
        # live_url ONLY. `proof_url` is a screenshot key (0045 documents it as
        # "screenshot/receipt") and the Playwright bot used to return an absolute server
        # filesystem path for it, so reading it here published /var/lib/... strings to
        # operators under the heading "Live listings already earned". The two columns are
        # different facts and NEITHER may ever be populated from the other.
        live = str(row.get("live_url") or "")
        if submit in _LIVE_SUBMIT and live:
            gap.live_urls.append(
                {"directory": str(row.get("directory") or ""), "url": live, "status": submit}
            )
        if submit in _IN_FLIGHT_SUBMIT:
            # Dedupes (a campaign must not double-queue it) but is NOT coverage: nothing
            # has been delivered. Stale in-flight is reported by name - it is the exact
            # signature of a dispatch nobody is consuming.
            gap.in_flight_count += 1
            if _is_stale(row, now, stuck_after_minutes):
                gap.stuck.append(
                    {"directory": str(row.get("directory") or ""), "status": submit}
                )
            _mark_covered(row, covered_ids, covered_names)
        elif _row_covers(row):
            gap.covered_count += 1
            _mark_covered(row, covered_ids, covered_names)

    candidates = automatable_directories(directories)
    # SUBTRACT WHAT IS COVERED, THEN CAP. The order is the whole correctness of this
    # number.
    #
    # It used to run the other way: the selection capped to 45 first, and covered rows
    # were removed from that 45 afterwards. So `missing` depended on whether a client's
    # existing listings happened to land inside the top 45 of the catalog. Four
    # covered directories inside it gave 41; the same four outside it gave 45 - with
    # `covered_count` reading 4 either way. That is exactly the 4/4/45 -> 4 built/41
    # missing drift QA reported between two runs of the same audit: not the catalog
    # changing, but the same four listings matching on one run and not the next.
    #
    # Capping AFTER the subtraction means the cap does what it says - "the next 45 to
    # build" - and the number only moves when the coverage or the catalog really does.
    selection = select_campaign_directories(
        candidates,
        vertical=vertical,
        cap=None,
        min_authority=min_authority,
        include_marketplaces=include_marketplaces,
    )
    remaining = [
        d
        for d in selection.selected
        if str(d.get("id")) not in covered_ids
        and canonical_norm(str(d.get("name") or "")) not in covered_names
    ]
    if cap is not None and cap > 0 and len(remaining) > cap:
        # The overflow is a DEFERRAL, not an exclusion - these are still missing, they
        # are simply not in this batch. Recorded so a shorter-than-expected list is
        # never indistinguishable from a silent failure (the same contract the other
        # skips keep).
        for row in remaining[cap:]:
            selection.skipped.append(
                {
                    "directory": str(row.get("name") or ""),
                    "reason": "over_campaign_cap",
                    "detail": f"batch capped at {cap}; queued in a later campaign",
                }
            )
        remaining = remaining[:cap]
    gap.missing = remaining
    # The full "why not" ledger: directory-level reasons (prohibited / fed by an
    # aggregator / not automatable) plus the client-specific ones the selection made.
    # A row already covered is not a skip - it was built, so it is not missing either.
    gap.skipped = [
        s
        for s in (*catalog_skips(directories), *selection.skipped)
        if canonical_norm(s.get("directory", "")) not in covered_names
    ]
    return gap


# --------------------------------------------------------------------------- #
# Audit plan: the geo/niche/generic view, PRIORITIZED Generic -> Country -> Niche,
# each directory tagged built|missing. PURE - reuses select_campaign_directories +
# compute_citation_gap (no new ranking); the router feeds it catalog + citation rows.
# --------------------------------------------------------------------------- #
@dataclass
class AuditPlan:
    """Three prioritized buckets of directories with a built|missing verdict each:
    ``generic`` (GLOBAL core, built first everywhere), ``country`` (the client's own
    market's general directories), ``niche`` (vertical-specific ones). Each bucket is
    in the same build order ``select_campaign_directories`` produces."""

    generic: list[dict[str, Any]] = field(default_factory=list)
    country: list[dict[str, Any]] = field(default_factory=list)
    niche: list[dict[str, Any]] = field(default_factory=list)


def build_audit_plan(
    *,
    directories: list[dict[str, Any]],
    existing_citations: list[dict[str, Any]],
    vertical: str | None = None,
    min_authority: int | None = DEFAULT_MIN_AUTHORITY,
    include_marketplaces: bool = False,
    now: datetime | None = None,
    stuck_after_minutes: int = DEFAULT_STUCK_AFTER_MINUTES,
) -> AuditPlan:
    """Group the client's relevant catalog into Generic -> Country -> Niche and tag each
    directory built | missing | in_flight | stuck.

    Reuses the EXISTING selection + gap logic rather than re-ranking: the ordered
    universe is ``select_campaign_directories`` (no cap - the whole plan is shown), and a
    directory is MISSING iff it is in ``compute_citation_gap``'s missing set (which
    subtracts everything a covering citation already earned) - so everything else in the
    universe is BUILT. Bucketing: a directory that names verticals is NICHE; else a GLOBAL
    one is GENERIC; else (the client's own market) it is COUNTRY. Degrade-safe: no citation
    records simply means every directory reports ``missing``."""
    candidates = automatable_directories(directories)
    selection = select_campaign_directories(
        candidates,
        vertical=vertical,
        cap=None,  # show the whole plan, not a capped campaign batch
        min_authority=min_authority,
        include_marketplaces=include_marketplaces,
    )
    gap = compute_citation_gap(
        directories=directories,
        existing_citations=existing_citations,
        vertical=vertical,
        cap=None,
        min_authority=min_authority,
        include_marketplaces=include_marketplaces,
        now=now,
        stuck_after_minutes=stuck_after_minutes,
    )
    missing_ids = {str(d.get("id")) for d in gap.missing}

    # Which directories have an IN-FLIGHT (or stale in-flight) row. A queued row must
    # never tag its directory "built" - that is how 45 refused rows once rendered as 45
    # built listings.
    in_flight_keys: set[str] = set()
    stuck_keys: set[str] = set()
    stuck_names = {canonical_norm(x["directory"]) for x in gap.stuck}
    for c in existing_citations:
        if str(c.get("submit_status") or "") not in _IN_FLIGHT_SUBMIT:
            continue
        keys = {str(c["directory_id"])} if c.get("directory_id") else set()
        name = canonical_norm(str(c.get("directory") or ""))
        if name:
            keys.add(name)
        target = stuck_keys if name in stuck_names else in_flight_keys
        target |= keys

    def _status_of(row: dict[str, Any]) -> str:
        keys = {str(row.get("id")), canonical_norm(str(row.get("name") or ""))}
        if keys & stuck_keys:
            return "stuck"
        if keys & in_flight_keys:
            return "in_flight"
        return "missing" if str(row.get("id")) in missing_ids else "built"

    plan = AuditPlan()
    for row in selection.selected:
        row = {**row, "_status": _status_of(row)}
        if row.get("verticals"):
            plan.niche.append(row)
        elif str(row.get("market")) == "GLOBAL":
            plan.generic.append(row)
        else:
            plan.country.append(row)
    return plan


def summarize_campaign_rows(
    rows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    stuck_after_minutes: int = DEFAULT_STUCK_AFTER_MINUTES,
) -> dict[str, Any]:
    """Pure rollup of a campaign's citation rows: per-status counts, per-reason counts
    for the held rows, the stuck tally, and the live URLs. The board renders exactly
    this; computing it from the rows means the campaign record can never disagree
    with them."""
    by_status: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    stuck = 0
    live_urls: list[dict[str, str]] = []
    for row in rows:
        submit = str(row.get("submit_status") or "not_started")
        by_status[submit] = by_status.get(submit, 0) + 1
        reason = str(row.get("blocked_reason") or "")
        if reason and submit in ("blocked", "ready_for_human"):
            by_reason[reason] = by_reason.get(reason, 0) + 1
        if submit in _IN_FLIGHT_SUBMIT and _is_stale(row, now, stuck_after_minutes):
            stuck += 1
        live = str(row.get("live_url") or "")
        if submit in _LIVE_SUBMIT and live:
            live_urls.append(
                {"directory": str(row.get("directory") or ""), "url": live, "status": submit}
            )
    return {
        "by_status": by_status,
        "by_blocked_reason": by_reason,
        "stuck": stuck,
        "live_urls": live_urls,
    }


def job_from_row(row: dict[str, Any]) -> CitationJob:
    """Build the engine-facing ``CitationJob`` from a joined citation+directory+
    business_profile row (see ``repo.load_citation_with_directory``)."""
    categories = row.get("bp_categories")
    payment_types = row.get("bp_payment_types")
    hours = row.get("bp_hours")
    year = row.get("bp_year_founded")
    return CitationJob(
        directory_name=str(row.get("directory_name") or row.get("directory") or ""),
        directory_url=str(row.get("directory_url") or ""),
        market=str(row.get("directory_market") or "US"),
        submit_method=str(row.get("submit_method") or ""),
        business_name=str(row.get("bp_business_name") or ""),
        address_line1=str(row.get("bp_address_line1") or ""),
        address_line2=str(row.get("bp_address_line2") or ""),
        city=str(row.get("bp_city") or ""),
        region=str(row.get("bp_region") or ""),
        postal_code=str(row.get("bp_postal_code") or ""),
        phone=str(row.get("bp_phone") or ""),
        website_url=str(row.get("bp_website_url") or ""),
        categories=tuple(categories) if isinstance(categories, list) else (),
        external_ref=str(row["external_ref"]) if row.get("external_ref") else None,
        client_id=str(row["client_id"]) if row.get("client_id") else "",
        description=str(row.get("bp_description") or ""),
        email=str(row.get("bp_email") or ""),
        logo_url=str(row.get("bp_logo_url") or ""),
        facebook_url=str(row.get("bp_facebook_url") or ""),
        instagram_url=str(row.get("bp_instagram_url") or ""),
        linkedin_url=str(row.get("bp_linkedin_url") or ""),
        year_founded=int(year) if year is not None else None,
        payment_types=tuple(payment_types) if isinstance(payment_types, list) else (),
        tagline=str(row.get("bp_tagline") or ""),
        service_area=str(row.get("bp_service_area") or ""),
        hours=dict(hours) if isinstance(hours, dict) else {},
    )


# --------------------------------------------------------------------------- #
# NAP change fan-out: when the canonical record moves, the listings are stale.
# PURE - the caller does the reads and writes.
# --------------------------------------------------------------------------- #
# The canonical fields a listing actually asserts. Editing any of these makes every
# already-built listing disagree with us; editing `description` or `logo_url` does not,
# so those are recorded as history but flag nothing. Flagging on every field would train
# operators to ignore the flag, which is the same as not having one.
NAP_CRITICAL_FIELDS: tuple[str, ...] = (
    "business_name",
    "address_line1",
    "address_line2",
    "city",
    "region",
    "postal_code",
    "phone",
    "website_url",
)

# A listing can only go stale if it EXISTS. `live` and `drifted` are the two states in
# which we believe there is a real listing out there carrying the old value; everything
# else is either not built yet, already known-gone, or still in flight.
_STALEABLE_SUBMIT: frozenset[str] = frozenset({"live", "drifted"})


def diff_nap_fields(
    before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, str]]:
    """Which canonical fields actually changed, as change-event rows.

    Compares only the fields a listing asserts, and only reports a REAL change: a value
    that arrives as ``None`` where it was ``""`` (or the reverse) is the same absence
    expressed differently, and raising a correction for every citation over that would
    be noise indistinguishable from a real move."""
    events: list[dict[str, str]] = []
    for field_name in NAP_CRITICAL_FIELDS:
        if field_name not in after:
            continue
        old = str(before.get(field_name) or "").strip()
        new = str(after.get(field_name) or "").strip()
        if old != new:
            events.append({"field": field_name, "old_value": old, "new_value": new})
    return events


def citations_needing_correction(rows: list[dict[str, Any]]) -> list[str]:
    """The ids of citations that are now stale because our canonical NAP moved.

    Only listings we believe EXIST are flagged. A `submitted` row is not flagged: nothing
    has confirmed a listing came back, so there may be nothing out there to correct - and
    if one does appear it will be checked against the NEW canonical NAP anyway, which is
    the right comparison. Flagging it now would invent work that may never exist."""
    return [
        str(r.get("id"))
        for r in rows
        if str(r.get("submit_status") or "") in _STALEABLE_SUBMIT and r.get("id")
    ]
