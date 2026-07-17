"""Competitor-intel orchestration - the PURE analysis core + the tool-workspace adapter.

This module is DB-free and network-free (mirrors ``keyword_research`` / ``rank_tracker``):
it takes the competitor's ranked set + the client's OWN positions and turns them into gap
verdicts, an overlap percentage, a share-of-voice split and KPI tiles - all deterministic
given the same inputs. The cost-gated fetch + the DB writes live in ``tasks.py``; the RLS
reads live in ``repo.py``; this layer just reasons.

Four decisions here are deliberate and worth reading before changing them:

1. **``client_position is None`` means the client does NOT rank - it is not zero.**
   This is the module's single most important rule and the reason the gap classifier
   tests ``is None`` explicitly rather than leaning on truthiness. A `None` position is
   a PURE gap (``missing``) - the most valuable row the tool produces. Reading it as 0
   would rank a term the client has never touched AHEAD of a #1 they own outright,
   inverting the entire board. Note the client's positions arrive from the Rank
   Tracker's ``tracked_keywords.latest_position``, where NULL ALREADY means "checked,
   not in the top-N" - so the meaning survives the reuse unchanged.

2. **A ``weak`` gap is both a gap and an overlap.** ``keyword_gaps_count`` counts the
   OPPORTUNITIES (missing + untapped + weak - the client is absent, or present but
   behind); ``common_keywords`` counts the INTERSECTION (shared + weak - both rank).
   A weak term is legitimately in both: they measure different things, and collapsing
   them would either hide the terms the client is losing or inflate the overlap.

3. **Overlap is a JACCARD, not a coverage ratio.** ``|Rc & Rk| / |Rc | Rk|`` is
   symmetric, so it answers "how much do these two businesses actually compete" rather
   than "how much of the competitor have we covered" - the latter reads 100% for a
   tiny rival the client happens to fully subsume, which is exactly backwards.

4. **Share of voice is an ESTIMATE built on a MODEL, not a measurement.** See
   ``DEFAULT_CTR_CURVE``.

``build_workspace`` is the ``GET /competitor-intel/workspace`` adapter: it emits the
frontend ``lib/tools.ts`` ``competitor_intel`` EXTRA shape with table columns pinned
EXACTLY to ``["Competitor", "Client", "Keyword gaps", "Overlap"]`` (the tool-workspace
contract test asserts this byte-for-byte).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import urlsplit

from app.modules.competitor_intel.schemas import CompetitorStats
from app.modules.keyword_research.service import opportunity_score
from app.schemas.tool_workspace import (
    ToolCell,
    ToolCellObj,
    ToolExtraResponse,
    ToolKpi,
    ToolPrimary,
    ToolTable,
)

# --- the CTR curve ------------------------------------------------------------
# PROVISIONAL (mirrors the PROVISIONAL R4 QA thresholds in app/services/content_qa.py).
#
# These are an ESTIMATE and must never be presented as truth. There is no public,
# universal, per-position click-through rate: the real curve moves with the query's
# intent, the SERP's feature set (an AI overview or a local pack can halve position
# 1's share), the device, the brand and the vertical. This vector is the industry's
# conventional organic desktop shape - a reasonable default that makes share-of-voice
# COMPARABLE between two domains measured the same way, which is the only claim the
# metric actually needs to support.
#
# It is therefore a NAMED, config-overridable constant (`competitor_intel_ctr_curve`),
# not a magic literal buried in the maths: ops can re-fit it per vertical without a
# code change, and every SoV number this module emits carries `provisional=True` so a
# reader knows what they are holding.
DEFAULT_CTR_CURVE: tuple[float, ...] = (
    0.316, 0.158, 0.096, 0.072, 0.0525, 0.0430, 0.0380, 0.0320, 0.0280, 0.0250,
)

# Every SoV number this module emits is curve-derived, hence an estimate.
PROVISIONAL = True

# --- volume thresholds --------------------------------------------------------
# A `missing` gap with real demand behind it is `untapped` - the subset worth acting
# on first. PROVISIONAL like the curve: it is a triage knob, not a fact about search.
DEFAULT_UNTAPPED_VOLUME = 500

# Auto-discovery's floor: a domain must appear in at least this many of the client's
# tracked SERPs before it is proposed as a competitor. 2 is deliberate - a single
# co-appearance is noise (a directory, a news story, one lucky long-tail), and
# proposing on n=1 would bury the analyst in false rivals.
DEFAULT_MIN_APPEARANCES = 2

# --- tool-workspace contract constants (pinned to lib/tools.ts competitor_intel) ---
WORKSPACE_TABLE_COLS: list[str] = ["Competitor", "Client", "Keyword gaps", "Overlap"]
_WORKSPACE_TABLE_TITLE = "Gap analysis"
_WORKSPACE_TABLE_ICON = "insights"
_WORKSPACE_PRIMARY = ToolPrimary(label="Compare", icon="insights")
_WORKSPACE_BULLETS = [
    "Compare clients to competitors",
    "Read keyword & content gap analysis",
    "Track share of voice",
]
_WORKSPACE_ROW_LIMIT = 8

# The Overlap cell's tone threshold, read off the lib/tools.ts demo rows: 38/45/40%
# render `info` and 22% renders `mut`, so a meaningful overlap starts around here.
_OVERLAP_INFO_THRESHOLD = 30.0


@dataclass(frozen=True)
class GapVerdict:
    """One analysed keyword: the competitor's position, the client's, and the verdict."""

    keyword: str
    volume: int
    difficulty: float
    intent: str | None
    competitor_position: int | None
    # None = the client does NOT rank (a PURE gap). Never 0. See the module docstring.
    client_position: int | None
    gap_type: str
    opportunity: float


@dataclass(frozen=True)
class GapAnalysis:
    """The full result of one gap analysis: the verdicts + the rolled-up read model."""

    gaps: list[GapVerdict] = field(default_factory=list)
    overlap_pct: float = 0.0
    keyword_gaps_count: int = 0
    common_keywords: int = 0

    @property
    def opportunities(self) -> list[GapVerdict]:
        """Only the ACTIONABLE rows (missing/untapped/weak) - what the board leads with."""
        return [g for g in self.gaps if g.gap_type != "shared"]


@dataclass(frozen=True)
class DiscoveredDomain:
    """One auto-discovery candidate: a domain the SERP tally proposes as a rival."""

    domain: str
    appearances: int
    volume: int
    score: int


# --------------------------------------------------------------------------- #
# Domain normalisation.
# --------------------------------------------------------------------------- #
def normalize_domain(value: str) -> str:
    """The folded host form the ``competitors`` uniqueness key uses.

    "BrightSmile.com", "www.brightsmile.com" and "https://brightsmile.com/x?y=1" are
    ONE competitor - and therefore ONE paid analysis - not three. This is 0036's
    ``normalize_keyword`` lesson applied to a domain.

    Accepts a bare domain as well as a full URL: ``urlsplit("example.com/x")`` reads
    the whole string as a PATH and yields an empty host, so a bare domain needs the
    ``//`` prefix before it parses. Returns "" for anything unparseable, which the
    callers treat as "no domain" rather than as a wildcard.
    """
    text = (value or "").strip().lower()
    if not text:
        return ""
    if "//" not in text:
        text = f"//{text}"
    try:
        host = urlsplit(text).hostname or ""
    except ValueError:  # malformed (e.g. a bad IPv6 literal) - not a usable domain
        return ""
    return host[4:] if host.startswith("www.") else host


def _same_domain(url: str, domain: str) -> bool:
    """Whether ``url`` belongs to ``domain`` (exact host or any subdomain).

    Suffix matching is anchored on a leading dot, so ``notexample.com`` can never be
    counted as a hit for ``example.com``.
    """
    target = normalize_domain(domain)
    if not target:
        return False
    host = normalize_domain(url)
    return host == target or host.endswith(f".{target}")


# --------------------------------------------------------------------------- #
# Gap classification.
# --------------------------------------------------------------------------- #
def classify_gap(
    *,
    competitor_position: int | None,
    client_position: int | None,
    volume: int,
    untapped_volume: int = DEFAULT_UNTAPPED_VOLUME,
) -> str:
    """The gap verdict for ONE keyword.

    The ``is None`` test is the load-bearing line in this module (see the module
    docstring): ``client_position`` NULL means the client does not rank AT ALL, and
    every other branch below assumes a real position. Truthiness would fold a
    hypothetical position 0 into "missing"; more importantly it reads as though 0 were
    a legitimate rank, which is the mental model that produces the bug.

    * ``missing``  - the client does not rank. A PURE gap.
    * ``untapped`` - a ``missing`` term with demand >= ``untapped_volume``: the subset
      to act on first. Still a pure gap; the label is triage, not a different fact.
    * ``weak``     - both rank, the competitor is AHEAD (a smaller position wins).
    * ``shared``   - both rank and the client is level or ahead.
    """
    if client_position is None:
        return "untapped" if volume >= untapped_volume else "missing"
    if competitor_position is not None and client_position > competitor_position:
        return "weak"
    return "shared"


def analyze_gaps(
    competitor_ranked: list[Any],
    client_positions: dict[str, int | None],
    *,
    untapped_volume: int = DEFAULT_UNTAPPED_VOLUME,
) -> GapAnalysis:
    """Compare a competitor's ranked set against the client's own positions.

    ``competitor_ranked`` is the provider's ``RankedKeyword`` list (duck-typed so the
    pure core never imports the provider seam). ``client_positions`` maps a
    NORMALISED keyword to the client's position, where the VALUE ``None`` means
    "tracked but not ranking" and an ABSENT key means "not tracked at all" - both of
    which are, for gap purposes, the same fact: the client does not rank. They are
    read through one ``.get(kw)`` precisely so the two cannot drift apart.

    The client's ranked set for the Jaccard is the tracked keywords with a REAL
    position - an unranked tracked keyword is not part of the client's visibility, so
    counting it as overlap would credit them for terms they do not hold.
    """
    verdicts: list[GapVerdict] = []
    competitor_terms: set[str] = set()

    for ranked in competitor_ranked:
        keyword = str(getattr(ranked, "keyword", "") or "").strip()
        if not keyword:
            continue
        key = keyword.lower()
        if key in competitor_terms:
            continue  # the provider listed the term twice; one verdict per keyword
        competitor_terms.add(key)

        competitor_position = _opt_int(getattr(ranked, "position", None))
        client_position = _opt_int(client_positions.get(key))
        volume = _to_int(getattr(ranked, "volume", 0))
        difficulty = _to_float(getattr(ranked, "difficulty", 0.0))
        gap_type = classify_gap(
            competitor_position=competitor_position,
            client_position=client_position,
            volume=volume,
            untapped_volume=untapped_volume,
        )
        verdicts.append(
            GapVerdict(
                keyword=keyword,
                volume=volume,
                difficulty=difficulty,
                intent=_opt_str(getattr(ranked, "intent", None)),
                competitor_position=competitor_position,
                client_position=client_position,
                gap_type=gap_type,
                # REUSED from keyword_research - never a second formula (see
                # gap_opportunity).
                opportunity=gap_opportunity(volume, difficulty, gap_type),
            )
        )

    # The client's RANKED set: a tracked keyword with a real position. Restricted to
    # nothing else - `client_positions` is the whole tracked book, which is exactly
    # what the union needs (terms the client ranks for and the competitor does not).
    client_terms = {kw for kw, pos in client_positions.items() if _opt_int(pos) is not None}
    return GapAnalysis(
        gaps=verdicts,
        overlap_pct=jaccard_overlap(competitor_terms, client_terms),
        # The OPPORTUNITIES: missing + untapped + weak. A `shared` term is not a gap.
        keyword_gaps_count=sum(1 for v in verdicts if v.gap_type != "shared"),
        # The INTERSECTION: shared + weak (both rank). A weak term counts here AND in
        # the gap total above - they measure different things (see the docstring).
        common_keywords=len(competitor_terms & client_terms),
    )


def gap_opportunity(volume: int, difficulty: float, gap_type: str) -> float:
    """A gap's 0-100 opportunity score.

    REUSES ``keyword_research.opportunity_score`` rather than inventing a second
    formula: "how good is this keyword" is one question, and two divergent answers on
    two screens is how a platform loses a user's trust in both. The only competitor-
    specific input is ``relevance``, which that formula takes as a 0-1 seed-closeness
    term. Here the analogue is how ADDRESSABLE the term is:

    * ``missing``/``untapped`` (1.0) - a pure gap: the whole position is winnable.
    * ``weak`` (0.6) - both rank; there is real ground to make up but the client
      already holds some of it, so the marginal prize is smaller.
    * ``shared`` (0.3) - the client is already level or ahead; there is little to win
      and the row exists as overlap evidence, not as a recommendation.
    """
    return opportunity_score(volume, difficulty, _GAP_RELEVANCE.get(gap_type, 0.3))


# The addressability weight per verdict (see gap_opportunity). Named so the scoring
# intent is legible and tunable rather than three magic floats inside a branch.
_GAP_RELEVANCE: dict[str, float] = {
    "missing": 1.0,
    "untapped": 1.0,
    "weak": 0.6,
    "shared": 0.3,
}


def jaccard_overlap(competitor_terms: set[str], client_terms: set[str]) -> float:
    """``|Rc & Rk| / |Rc | Rk| x 100`` - how much two domains actually compete.

    Symmetric by construction (see the module docstring). An empty union is 0.0, not a
    division error and not 100: two domains that rank for nothing do not compete
    perfectly, they simply have no evidence either way.
    """
    union = competitor_terms | client_terms
    if not union:
        return 0.0
    return round(100.0 * len(competitor_terms & client_terms) / len(union), 2)


# --------------------------------------------------------------------------- #
# Share of voice.
# --------------------------------------------------------------------------- #
def ctr_for_position(position: int | None, curve: tuple[float, ...] = DEFAULT_CTR_CURVE) -> float:
    """The estimated click-through rate at ``position`` (see ``DEFAULT_CTR_CURVE``).

    Past the curve's end the rate DECAYS rather than either cutting to zero (which
    would make a page-2 presence worth exactly as much as not ranking at all) or
    holding flat (which would make position 90 as valuable as position 11). An unranked
    or nonsensical position earns 0.0 - the honest reading of "no visibility".
    """
    if position is None or position < 1 or not curve:
        return 0.0
    if position <= len(curve):
        return curve[position - 1]
    # Decay the tail from the curve's last known point: position 11 gets 1/2 of it,
    # 12 gets 1/3, and so on.
    return round(curve[-1] / (position - len(curve) + 1), 6)


def visibility_score(
    positions: dict[str, int | None],
    volumes: dict[str, int],
    *,
    curve: tuple[float, ...] = DEFAULT_CTR_CURVE,
) -> float:
    """``Σ over ranked keywords of volume_k x CTR(rank_k)`` - one domain's estimated
    monthly organic visibility, in clicks.

    Unranked terms contribute 0 through ``ctr_for_position``, so they neither help nor
    corrupt the sum.
    """
    total = 0.0
    for keyword, position in positions.items():
        ctr = ctr_for_position(_opt_int(position), curve)
        if ctr > 0:
            total += float(volumes.get(keyword, 0)) * ctr
    return round(total, 4)


def share_of_voice(
    visibilities: dict[str, float],
) -> dict[str, float]:
    """Each domain's share of the measured market: ``visibility / Σ visibility x 100``.

    ``visibilities`` is ``{domain: visibility}`` over the CLIENT plus their TRACKED
    competitors - the denominator is that set and nothing else, which is the honest
    scope: this is share of the voice we MEASURE, not of the entire internet. An
    all-zero market yields 0.0 for everyone rather than a division error or a
    meaningless even split.
    """
    total = sum(max(v, 0.0) for v in visibilities.values())
    if total <= 0:
        return dict.fromkeys(visibilities, 0.0)
    return {
        domain: round(100.0 * max(v, 0.0) / total, 2) for domain, v in visibilities.items()
    }


# --------------------------------------------------------------------------- #
# Auto-discovery.
# --------------------------------------------------------------------------- #
def discover_competitors(
    serps: list[tuple[str, int, list[str]]],
    *,
    client_domain: str,
    existing_domains: set[str],
    limit: int = 5,
    min_appearances: int = DEFAULT_MIN_APPEARANCES,
) -> list[DiscoveredDomain]:
    """Tally the domains appearing in the client's tracked-keyword SERPs.

    ``serps`` is ``[(keyword, volume, [result_urls])]``. A domain's ``score`` is
    ``appearances x total_volume``: appearances alone would crown a site that shadows
    the client across worthless long-tail, and volume alone would crown a one-hit
    wonder that happened to appear on the single biggest term. The product demands
    BOTH - which is what "competitor" actually means.

    The client's OWN domain and every already-known competitor are excluded: the first
    is not a rival, and the second would re-propose rows the analyst has already ruled
    on (including ones they deliberately parked with ``tracked=false``).
    """
    target = normalize_domain(client_domain)
    known = {normalize_domain(d) for d in existing_domains}
    known.discard("")

    appearances: dict[str, int] = {}
    volumes: dict[str, int] = {}
    for keyword, volume, urls in serps:
        # One credit per DOMAIN per keyword: a rival holding three results on one SERP
        # dominates that term, but it is still one term of evidence, and counting it
        # three times would let a single stacked SERP invent a competitor.
        seen: set[str] = set()
        for url in urls:
            host = normalize_domain(url)
            if not host or host in seen:
                continue
            if host == target or (target and host.endswith(f".{target}")):
                continue  # the client is not their own competitor
            if host in known:
                continue  # already ruled on by an analyst
            seen.add(host)
            appearances[host] = appearances.get(host, 0) + 1
            volumes[host] = volumes.get(host, 0) + max(int(volume), 0)
        del keyword  # only the volume + the URLs matter to the tally

    candidates = [
        DiscoveredDomain(
            domain=host,
            appearances=count,
            volume=volumes.get(host, 0),
            score=count * volumes.get(host, 0),
        )
        for host, count in appearances.items()
        if count >= min_appearances
    ]
    # Score desc, then domain for a stable order across equal scores (so a re-run
    # proposes the same set in the same order rather than shuffling the board).
    candidates.sort(key=lambda c: (-c.score, c.domain))
    return candidates[:limit]


# --------------------------------------------------------------------------- #
# Coercion helpers.
# --------------------------------------------------------------------------- #
def _opt_int(value: Any) -> int | None:
    """Coerce to ``int``, PRESERVING a meaningful ``None`` (the client does not rank).

    An ``or 0`` here would be the module's cardinal sin - see the module docstring.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# --------------------------------------------------------------------------- #
# The /workspace adapter (frontend lib/tools.ts competitor_intel EXTRA shape).
# --------------------------------------------------------------------------- #
def _overlap_cell(overlap: float) -> ToolCellObj:
    """The Overlap cell: a percentage with a tone.

    ``info`` once the overlap is meaningful, ``mut`` below that - matching the
    ``lib/tools.ts`` demo rows (38%/45%/40% read ``info``; 22% reads ``mut``). A
    genuinely non-competing rival still RENDERS, at 0% and muted: hiding it would
    silently answer "who do we compete with" by omission.
    """
    tone = "info" if overlap >= _OVERLAP_INFO_THRESHOLD else "mut"
    return ToolCellObj(v=f"{round(overlap)}%", tone=cast("Any", tone))


def _competitor_row(row: dict[str, Any]) -> list[ToolCell]:
    """One workspace table row: [Competitor, Client, Keyword gaps, Overlap]."""
    return [
        str(row.get("domain", "") or ""),
        str(row.get("client_name", "") or ""),
        str(_to_int(row.get("keyword_gaps_count", 0))),
        _overlap_cell(_to_float(row.get("overlap_pct", 0.0))),
    ]


def build_workspace(
    stats: CompetitorStats, competitors: list[dict[str, Any]]
) -> ToolExtraResponse:
    """Assemble the competitor-intel tool workspace (KPIs + gap table + CTA).

    KPI labels + the primary + the table columns are pinned to ``lib/tools.ts``; the
    columns are EXACTLY ``["Competitor", "Client", "Keyword gaps", "Overlap"]`` (the
    tool-workspace contract test enforces byte-identity).

    NO KPI DELTA is emitted. ``tools.ts``'s demo tile carries ``delta: "4%", dir: "up"``
    on Share of voice, but this module stores no historical SoV baseline, so any delta
    here would be invented. An absent delta renders as a plain tile; a fabricated one
    would render as a trend the agency could be asked to explain.
    """
    kpis = [
        ToolKpi(label="Competitors tracked", value=f"{stats.tracked:,}"),
        ToolKpi(label="Keyword gaps", value=f"{stats.keyword_gaps:,}"),
        ToolKpi(label="Share of voice", value=f"{round(stats.share_of_voice)}%"),
    ]
    table = ToolTable(
        title=_WORKSPACE_TABLE_TITLE,
        icon=_WORKSPACE_TABLE_ICON,
        cols=list(WORKSPACE_TABLE_COLS),
        rows=[_competitor_row(r) for r in competitors[:_WORKSPACE_ROW_LIMIT]],
    )
    return ToolExtraResponse(
        kpis=kpis, table=table, primary=_WORKSPACE_PRIMARY, bullets=list(_WORKSPACE_BULLETS)
    )
