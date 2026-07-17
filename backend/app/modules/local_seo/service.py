"""Local-SEO orchestration - the PURE analysis core + the tool-workspace adapter.

This module is DB-free and network-free (mirrors ``keyword_research.service``): it
takes rows and turns them into verdicts - a profile's completeness score, its NAP
alignment against the citations ledger, the average map rank - all deterministic
given the same inputs. The cost-gated provider calls live in ``tasks.py``; the RLS
reads live in ``repo.py``; this layer just reasons.

Three decisions are load-bearing and each is spelled out where it is made:

* **Completeness** is a fixed, deterministic CHECKLIST (never an AI judgement), so a
  score is reproducible and an operator can see exactly which field cost them points.
* **NAP alignment NORMALIZES before it compares.** "123 Main St." and "123 Main
  Street" are the same address; a naive string compare flags the difference and buries
  the operator in false drift. Normalization is what makes the fix-list trustworthy.
* **Average map rank counts RANKED, ACTIVE rows only** (see ``average_map_rank``).

``build_workspace`` is the ``GET /local-seo/workspace`` adapter: it emits the frontend
``lib/tools.ts`` ``local_seo`` EXTRA shape with table columns pinned EXACTLY to
``["Location", "Client", "Keyword", "Rank"]`` (the tool-workspace contract test
asserts this byte-for-byte).
"""

from __future__ import annotations

import re
from typing import Any, cast

from app.modules.local_seo.schemas import (
    MAP_PACK_SIZE,
    LocalStats,
    NapAlignmentReport,
    NapDirectoryFinding,
    ProfileAuditReport,
)
from app.schemas.tool_workspace import (
    ToolCell,
    ToolCellObj,
    ToolExtraResponse,
    ToolKpi,
    ToolPrimary,
    ToolTable,
)

# --- tool-workspace contract constants (pinned to lib/tools.ts local_seo) ------
WORKSPACE_TABLE_COLS: list[str] = ["Location", "Client", "Keyword", "Rank"]
_WORKSPACE_TABLE_TITLE = "Map-pack rankings"
_WORKSPACE_TABLE_ICON = "storefront"
_WORKSPACE_PRIMARY = ToolPrimary(label="Run local audit", icon="storefront")
_WORKSPACE_BULLETS = [
    "Track local & map-pack rankings",
    "Audit GBP categories & NAP",
    "Monitor citation consistency",
]
_WORKSPACE_ROW_LIMIT = 8

# --- completeness checklist ---------------------------------------------------
# How many secondary categories a profile needs to score the categories point. GBP
# allows up to 9; two is the floor at which a listing reads as deliberately
# categorised rather than defaulted.
MIN_SECONDARY_CATEGORIES = 2

# The checklist, in display order. Each field is worth an EQUAL share of 100, so the
# score moves predictably and no single field can dominate. Adding a field here
# automatically re-weights the score and shows up in `findings` - the audit report and
# the score can never drift apart.
_CHECKLIST: tuple[str, ...] = (
    "primary_category",
    "secondary_categories",
    "hours",
    "website",
    "phone",
    "name",
    "address",
)

# Finding verdicts.
_OK = "ok"
_MISSING = "missing"
_THIN = "thin"  # present but under the bar (e.g. only one secondary category)


# --- NAP normalization --------------------------------------------------------
# Street-type abbreviations -> their canonical long form. Directories legitimately
# disagree about "St."/"Street", and flagging that as drift buries the REAL errors
# (a wrong suite number, a stale phone) in noise. Normalizing both sides first is
# what makes the inconsistent count actionable.
_STREET_FORMS: dict[str, str] = {
    "st": "street",
    "str": "street",
    "rd": "road",
    "ave": "avenue",
    "av": "avenue",
    "blvd": "boulevard",
    "dr": "drive",
    "ln": "lane",
    "ct": "court",
    "pl": "place",
    "sq": "square",
    "pkwy": "parkway",
    "hwy": "highway",
    "ste": "suite",
    "apt": "apartment",
    "fl": "floor",
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "ne": "northeast",
    "nw": "northwest",
    "se": "southeast",
    "sw": "southwest",
}

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")
_DIGITS_RE = re.compile(r"\D")

# A phone is compared on its last N digits: the same line is legitimately written
# +1 (555) 010-9999 / 555-010-9999 / 0555 010 9999, differing only in country code
# and trunk prefix. Ten digits is the significant tail (NANP subscriber + area code).
_PHONE_SIGNIFICANT_DIGITS = 10

# A value is PHONE-SHAPED only if it is digits + phone punctuation (no letters) and
# carries enough digits to be a real number. This gate is load-bearing: without it,
# digit-only comparison would reduce "123 Main Street" and "123 Oak Street" both to
# "123" and call two DIFFERENT addresses a cosmetic match - hiding exactly the real
# drift this module exists to surface.
_PHONE_SHAPE_RE = re.compile(r"^[+(]?[\d][\d()\-.\s+]*$")
_MIN_PHONE_DIGITS = 7


def normalize_nap_text(value: str) -> str:
    """Canonicalise a name/address for COMPARISON (never for display).

    Lowercases, strips punctuation, collapses whitespace, and expands street-type
    abbreviations token-by-token, so ``"123 Main St."`` and ``"123 Main Street"``
    both become ``"123 main street"``. Token-wise expansion is deliberate: a
    substring replace would rewrite "Stanley" into "streetanley".
    """
    text = _PUNCT_RE.sub(" ", value.lower())
    tokens = [_STREET_FORMS.get(tok, tok) for tok in _WS_RE.split(text) if tok]
    return " ".join(tokens)


def normalize_phone(value: str) -> str:
    """Canonicalise a phone number for COMPARISON: digits only, last 10 kept.

    Drops formatting, country code and trunk prefix, so ``"+1 (555) 010-9999"`` and
    ``"555-010-9999"`` compare equal. A shorter number is returned as-is (it has no
    prefix to strip), so a genuinely different number never accidentally matches.
    """
    digits = _DIGITS_RE.sub("", value)
    return digits[-_PHONE_SIGNIFICANT_DIGITS:] if len(digits) > _PHONE_SIGNIFICANT_DIGITS else digits


def is_phone_like(value: str) -> bool:
    """Whether ``value`` is PHONE-SHAPED: digits + phone punctuation, no letters, and
    at least ``_MIN_PHONE_DIGITS`` digits.

    The gate that keeps digit-comparison away from addresses. "123 Main Street" is not
    phone-shaped (it has letters), so it is never reduced to its house number.
    """
    text = value.strip()
    if not _PHONE_SHAPE_RE.match(text):
        return False
    return len(_DIGITS_RE.sub("", text)) >= _MIN_PHONE_DIGITS


def nap_values_match(canonical: str, observed: str) -> bool:
    """Whether two NAP values are the SAME value, ignoring cosmetic formatting.

    A phone-vs-phone pair compares on significant DIGITS (formatting varies far more
    than the number itself); everything else compares as normalised TEXT. The two
    paths are exclusive on purpose - digit-comparing an address would make "123 Main
    Street" and "123 Oak Street" match on the house number alone.

    Empty on either side is NOT a match: an unknown value is unverified, not aligned.
    """
    if not canonical.strip() or not observed.strip():
        return False
    if is_phone_like(canonical) and is_phone_like(observed):
        return normalize_phone(canonical) == normalize_phone(observed)
    return normalize_nap_text(canonical) == normalize_nap_text(observed)


# --------------------------------------------------------------------------- #
# Profile completeness (the deterministic checklist).
# --------------------------------------------------------------------------- #
def _checklist_findings(profile: dict[str, Any]) -> dict[str, str]:
    """Run the checklist over one profile row -> ``{field: ok|missing|thin}``."""
    cats = profile.get("secondary_categories")
    secondary = [str(c) for c in cats if str(c).strip()] if isinstance(cats, list) else []
    hours = profile.get("regular_hours")

    if not secondary:
        secondary_verdict = _MISSING
    elif len(secondary) < MIN_SECONDARY_CATEGORIES:
        secondary_verdict = _THIN
    else:
        secondary_verdict = _OK

    def _present(key: str) -> str:
        return _OK if str(profile.get(key) or "").strip() else _MISSING

    return {
        "primary_category": _present("primary_category"),
        "secondary_categories": secondary_verdict,
        "hours": _OK if isinstance(hours, dict) and hours else _MISSING,
        "website": _present("website_uri"),
        "phone": _present("nap_phone"),
        "name": _present("nap_name"),
        "address": _present("nap_address"),
    }


def profile_completeness(profile: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Score ONE profile 0-100 and return ``(score, audit)``.

    Deterministic and explainable: each of the ``_CHECKLIST`` fields carries an equal
    share of 100, an ``ok`` field scores full, a ``thin`` one scores half (present but
    under the bar), and a ``missing`` one scores zero. The returned ``audit`` carries
    the per-field findings + the fix-list, so the stored score is always accompanied
    by the reason it is not 100.
    """
    findings = _checklist_findings(profile)
    per_field = 100.0 / len(_CHECKLIST)
    earned = 0.0
    for field in _CHECKLIST:
        verdict = findings[field]
        if verdict == _OK:
            earned += per_field
        elif verdict == _THIN:
            earned += per_field / 2
    score = max(0, min(100, round(earned)))
    missing = [f for f in _CHECKLIST if findings[f] != _OK]
    return score, {"findings": findings, "missing": missing, "score": score}


def build_audit_report(profile: dict[str, Any]) -> ProfileAuditReport:
    """The ``GET /local-seo/profiles/{id}/audit`` payload: the freshly RE-COMPUTED
    completeness + categories.

    Recomputed rather than read off ``completeness_score``: an operator who just
    PATCHed a category must see the effect immediately, not after the next sync.
    """
    score, audit = profile_completeness(profile)
    cats = profile.get("secondary_categories")
    return ProfileAuditReport(
        id=str(profile.get("id", "")),
        location=str(profile.get("location_label", "") or ""),
        client=str(profile.get("client_name", "") or ""),
        completeness=score,
        primary_category=str(profile.get("primary_category", "") or ""),
        secondary_categories=[str(c) for c in cats] if isinstance(cats, list) else [],
        findings=cast("dict[str, str]", audit["findings"]),
        missing=cast("list[str]", audit["missing"]),
    )


# --------------------------------------------------------------------------- #
# NAP alignment vs the EXISTING 0018 citations ledger.
# --------------------------------------------------------------------------- #
def _is_cosmetic(note: str, profile: dict[str, Any]) -> bool:
    """Whether a directory's ``inconsistent`` flag is merely a FORMATTING difference.

    The 0018 ledger's ``nap_status`` is set by an upstream citation provider that
    string-compares; its ``note`` carries the observed listing value. When that
    observed value NORMALIZES equal to one of the profile's canonical NAP fields, the
    listing is actually correct and only its formatting differs - so it is reported as
    cosmetic rather than counted as real drift. A note that carries no comparable
    value (a prose issue description like "Suite # differs") normalizes to nothing
    matching and correctly stays REAL drift, which is the safe direction to err.
    """
    if not note.strip():
        return False
    return any(
        nap_values_match(str(profile.get(key) or ""), note)
        for key in ("nap_name", "nap_address", "nap_phone")
    )


def build_nap_alignment(
    profile: dict[str, Any], citations: list[dict[str, Any]]
) -> NapAlignmentReport:
    """Fold the profile's canonical NAP + its 0018 citation rows into one report.

    The profile is the CANONICAL NAP; each citation row is a directory's verdict
    against it. A row the ledger flagged ``inconsistent`` whose observed value merely
    reformats the canonical value is re-classed as COSMETIC (counted separately, not
    as drift), so the operator's fix-list carries only listings that are actually
    wrong. Pure: no DB, no network.
    """
    findings: list[NapDirectoryFinding] = []
    consistent = inconsistent = missing = cosmetic = 0

    for row in citations:
        status = str(row.get("nap_status", "") or "")
        note = str(row.get("note", "") or "")
        # A cosmetic row is RE-CLASSED to consistent: the listing is correct, only its
        # formatting differs. It is still counted in `cosmetic_only` so the review is
        # auditable rather than silently rewritten.
        is_cosmetic = status == "inconsistent" and _is_cosmetic(note, profile)
        effective = "consistent" if is_cosmetic else status
        if is_cosmetic:
            cosmetic += 1
        if effective == "consistent":
            consistent += 1
        elif effective == "inconsistent":
            inconsistent += 1
        elif effective == "missing":
            missing += 1
        findings.append(
            NapDirectoryFinding(
                directory=str(row.get("directory", "") or ""),
                status=effective,
                note=note,
                cosmetic_only=is_cosmetic,
            )
        )

    nap_complete = all(
        str(profile.get(key) or "").strip() for key in ("nap_name", "nap_address", "nap_phone")
    )
    return NapAlignmentReport(
        id=str(profile.get("id", "")),
        location=str(profile.get("location_label", "") or ""),
        client=str(profile.get("client_name", "") or ""),
        nap_name=str(profile.get("nap_name", "") or ""),
        nap_address=str(profile.get("nap_address", "") or ""),
        nap_phone=str(profile.get("nap_phone", "") or ""),
        directories=findings,
        consistent=consistent,
        inconsistent=inconsistent,
        missing=missing,
        cosmetic_only=cosmetic,
        # Aligned = a complete canonical NAP AND nothing actually wrong out there.
        # Cosmetic rows do not block alignment; that is the point of normalizing.
        aligned=nap_complete and inconsistent == 0 and missing == 0,
    )


# --------------------------------------------------------------------------- #
# Rank maths.
# --------------------------------------------------------------------------- #
def average_map_rank(rows: list[dict[str, Any]]) -> float:
    """The mean position across RANKED, ACTIVE rows.

    THE CHOICE, stated: rows where ``rank is null`` (checked, not in the pack) are
    EXCLUDED, not counted as some penalty value, and inactive rows are excluded too.

    There is no honest number for "not in the pack": substituting a sentinel (say 20)
    would invent data, and counting it as 0 would make falling OUT of the pack improve
    the average. The tile therefore answers "where do we rank WHERE we rank", and the
    unranked rows are visible in their own right on the rankings table. An all-unranked
    (or empty) set averages to 0.0, which the KPI renders as "-".
    """
    ranked = [
        int(r["rank"])
        for r in rows
        if r.get("rank") is not None and r.get("is_active", True)
    ]
    if not ranked:
        return 0.0
    return round(sum(ranked) / len(ranked), 1)


def rank_delta(previous: int | None, current: int | None) -> int:
    """Movement since the last check, POSITIVE = improved (moved toward #1).

    A rank is an inverted scale (1 is best), so the delta is ``previous - current``.
    Either side unknown (a first check, or in/out of the pack) yields 0: we know
    something changed but have no honest magnitude for it, and inventing one would
    show up as a fake win/loss on the client's report.
    """
    if previous is None or current is None:
        return 0
    return previous - current


# --------------------------------------------------------------------------- #
# The /workspace adapter (frontend lib/tools.ts local_seo EXTRA shape).
# --------------------------------------------------------------------------- #
def _rank_tone(rank: int | None) -> str:
    """``ok`` inside the 3-pack, ``warn`` when ranked but outside it, ``mut`` when not
    in the pack at all (there is no number to praise or warn about)."""
    if rank is None:
        return "mut"
    return "ok" if rank <= MAP_PACK_SIZE else "warn"


def _ranking_row(row: dict[str, Any]) -> list[ToolCell]:
    """One workspace table row: [Location, Client, Keyword, Rank] with a Rank tone."""
    rank = row.get("rank")
    rank_int = int(rank) if rank is not None else None
    return [
        str(row.get("location_label", "") or ""),
        str(row.get("client_name", "") or ""),
        str(row.get("keyword", "") or ""),
        # An unranked row shows an em dash, never a fabricated number.
        ToolCellObj(
            v=str(rank_int) if rank_int is not None else "—",
            tone=cast("Any", _rank_tone(rank_int)),
        ),
    ]


def build_workspace(stats: LocalStats, rankings: list[dict[str, Any]]) -> ToolExtraResponse:
    """Assemble the local-SEO tool workspace (KPIs + map-pack table + CTA).

    KPI labels + the primary + the table columns are pinned to ``lib/tools.ts``; the
    columns are EXACTLY ``["Location", "Client", "Keyword", "Rank"]`` (the
    tool-workspace contract test enforces byte-identity). The Citations tile is read
    from the EXISTING 0018 ledger, not from a table this module owns.
    """
    kpis = [
        ToolKpi(label="GBP profiles", value=f"{stats.gbp_profiles:,}"),
        # 0.0 means "nothing ranked yet" - an em dash is honest, "0.0" would read as a
        # rank better than #1.
        ToolKpi(
            label="Avg. map rank",
            value=f"{stats.avg_map_rank:.1f}" if stats.avg_map_rank > 0 else "—",
        ),
        ToolKpi(label="Citations", value=f"{stats.citations:,}"),
    ]
    table = ToolTable(
        title=_WORKSPACE_TABLE_TITLE,
        icon=_WORKSPACE_TABLE_ICON,
        cols=list(WORKSPACE_TABLE_COLS),
        rows=[_ranking_row(r) for r in rankings[:_WORKSPACE_ROW_LIMIT]],
    )
    return ToolExtraResponse(
        kpis=kpis, table=table, primary=_WORKSPACE_PRIMARY, bullets=list(_WORKSPACE_BULLETS)
    )
