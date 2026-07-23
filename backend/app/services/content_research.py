"""P7A-3: the Content keyword & intent RESEARCH service - the #1 quality lever.

This is the INPUT layer that grounds a content job before a single word is
drafted. Given a target keyword it produces a rich :class:`ResearchBrief` that a
later chunk's generator/QA/worker consumes. The brief answers, from the LIVE
SERP + keyword metrics + a top-10 teardown:

  1. What is the search INTENT (informational / commercial / transactional /
     navigational), read off the SERP shape?
  2. What TERMS must the page cover (1 primary + 3-8 secondary + semantic /
     entity terms mined from organic + PAA + related)?
  3. What CLUSTER (pillar + supporting spokes) owns the topic - so we build a
     topical map, NOT one-off pages?
  4. What FORMAT should we ship (blog / product / tool / video / local /
     comparison), decided from the live SERP BEFORE generation?
  5. What sub-questions does the AI-Overview FAN-OUT imply (folded into the
     question / entity set)?
  6. Which terms are WINNABLE (keyword difficulty x client authority/DA)? DA
     comes from the audit engine's Moz data; when the client is un-audited the
     brief assumes a NEUTRAL DA and flips ``low_confidence`` - never a silent
     no-op.
  7. The top-10 structural TEARDOWN: for the ranking pages, the section
     architecture, table-stakes entities (all cover) vs differentiators (only
     some), a word-count target, schema types, media, and freshness.
  8. A keyword->URL REGISTRY that keeps one primary intent per URL (the
     cannibalization guard).

Design (mirrors ``context_compactor.py``): the analysis core is PURE - no DB, no
network, no hidden globals - and every external touch is an INJECTED seam. The
orchestrator :func:`build_research_brief` receives a :class:`ResearchPort` (in the
worker that is a cost-gated :class:`GatedResearcher`, so the core can never reach a
raw provider) plus a client DA, and returns the brief. Given the
``FakeSerpResearcher`` + a ``FakePageFetcher`` the whole call is deterministic, so
unit tests run with ZERO network.

Hardening baked in:

* **Cost-gate every external call.** :class:`GatedResearcher` fronts the Serper
  SERP pull, the per-keyword metrics, AND the top-10 teardown fetch with the
  Part-2 cost gate (dial feature ``content_research``). A gate block raises
  :class:`ContentSpendBlocked`, which the orchestrator catches to DEGRADE
  (partial / low-confidence brief) - it never crashes.
* **N1 (keyword, geo, serp_date) cache.** The gate caches the SERP + teardown by
  that key (TTL ~24h in prod), so a cluster / city sprint reuses one pull and a
  cache hit costs ~$0 (a gate ``cached`` outcome).
* **N2 SSRF guard on every teardown fetch.** A ranking URL is fetched ONLY after
  ``app/core/security.py``'s guard clears it (never raw httpx); a
  private/loopback/metadata URL is refused. ``socket.getaddrinfo`` blocks, so the
  worker runs this whole sync service off the event loop (``asyncio.to_thread``,
  invariant #2); the real fetcher disables redirects and re-validates.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import median
from typing import Any, Literal, Protocol, cast, runtime_checkable

from app.config import Settings
from app.core.security import is_public_url
from app.logging_setup import get_logger
from app.services import pricing
from app.services.cost_gate import CostGate, GateContext, GateOutcome
from integrations.content_research import KeywordMetrics, SerpResearcher, SerpResult

logger = get_logger("services.content_research")

# The cost-dial feature + provider label these external calls gate/log against.
_FEATURE = "content_research"
_PROVIDER = "Serper"
_JOB_TYPE = "content"

# Defaults (a worker overrides from Settings): the assumed authority when a
# client is un-audited, and how far a keyword's difficulty may exceed the
# client's DA and still be judged winnable (0-100 scale).
_DEFAULT_NEUTRAL_DA = 30.0
_DEFAULT_WINNABLE_STRETCH = 15.0

# Bound the fetched HTML so a hostile / huge page cannot exhaust memory.
_MAX_HTML_CHARS = 2_000_000

Intent = Literal["informational", "commercial", "transactional", "navigational"]
ContentFormat = Literal["blog", "product", "tool", "video", "local", "comparison"]


# --------------------------------------------------------------------------- #
# Intent + format signal dictionaries (reused conceptually from the audit
# engine's semantic_seo analyzer + the A2 keyword-semantic SOP).
# --------------------------------------------------------------------------- #
_INTENT_SIGNALS: dict[Intent, tuple[str, ...]] = {
    "transactional": (
        "buy", "order", "shop", "cart", "checkout", "subscribe", "book now",
        "for sale", "purchase", "rent", "lease", "hire", "quote", "price",
        "pricing", "cost", "cheap", "discount", "deal", "coupon", "$",
    ),
    "commercial": (
        "best", "top", "review", "reviews", "vs", "versus", "compare",
        "comparison", "alternative", "alternatives", "pros and cons",
    ),
    "informational": (
        "what is", "what are", "how to", "how do", "how does", "why", "when",
        "where", "guide", "tutorial", "definition", "meaning", "explained",
        "checklist", "examples", "ideas", "tips", "learn",
    ),
    "navigational": (
        "login", "log in", "sign in", "dashboard", "account", "official site",
        "official website", "homepage", "portal", "download",
    ),
}

# Format signals: matched against the SERP text pool (+ organic hosts for video).
_FORMAT_SIGNALS: dict[ContentFormat, tuple[str, ...]] = {
    "tool": ("calculator", "calculate", "tool", "generator", "converter", "template", "checker"),
    "local": ("near me", "nearby", "in my area", "local", "directions", "open now"),
    "product": ("buy", "for sale", "shop", "order", "add to cart", "in stock", "price", "$"),
    "comparison": ("best", "top ", "vs", "versus", "compare", "comparison", "alternative", "review"),
    "video": ("watch", "video", "youtube"),
}
_VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com", "tiktok.com")

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+){0,3}\b")
_YEAR_RE = re.compile(r"\b(?:20[12]\d|19\d\d)\b")
_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"<h([1-3])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
_JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_MEDIA_RE = re.compile(r"<(?:img|video|picture|iframe|source)\b", re.IGNORECASE)
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "with",
        "by", "at", "is", "are", "be", "this", "that", "your", "you", "near",
        "me", "how", "what", "why", "when", "where", "best", "top", "vs",
    }
)


# --------------------------------------------------------------------------- #
# Pure output types
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TermSet:
    """The keyword coverage plan: 1 primary + 3-8 secondary + semantic/entity
    terms + the question set (PAA + AI-Overview fan-out)."""

    primary: str
    secondary: list[str]
    semantic_entities: list[str]
    questions: list[str]


@dataclass(frozen=True)
class TopicalCluster:
    """A pillar + its supporting spokes - the cluster that OWNS the topic (so we
    build a topical map, not one-off pages)."""

    pillar: str
    primary: str
    supporting: list[str]


@dataclass(frozen=True)
class FormatDecision:
    """The recommended content format decided from the live SERP, its 0-1
    confidence, and the per-format signal scores that drove it."""

    recommended: ContentFormat
    confidence: float
    signals: dict[str, int]


@dataclass(frozen=True)
class TeardownPage:
    """One ranking page's structural fingerprint (extracted from its HTML)."""

    url: str
    position: int
    headings: list[str]
    word_count: int
    entities: list[str]
    schema_types: list[str]
    media_count: int
    has_freshness: bool


@dataclass(frozen=True)
class Teardown:
    """The aggregated top-10 teardown: what the current winners have in common
    (table-stakes) vs where they differ (differentiators), plus the structural
    targets to match/beat and which URLs the SSRF guard refused."""

    pages: list[TeardownPage]
    table_stakes_entities: list[str]
    differentiator_entities: list[str]
    heading_blueprint: list[str]
    word_count_target: int
    schema_types: list[str]
    media_target: int
    freshness_expected: bool
    fetched: int
    refused: list[str]


@dataclass(frozen=True)
class KeywordTarget:
    """A candidate keyword's demand + a winnability verdict for THIS client."""

    keyword: str
    volume: int
    difficulty: float
    winnable: bool
    reason: str


@dataclass(frozen=True)
class WinnabilityReport:
    """The winnability filter (N4): each target keyword judged against the
    client's authority. ``neutral_da_assumed`` flags an un-audited client."""

    client_da: float
    neutral_da_assumed: bool
    targets: list[KeywordTarget]


@dataclass(frozen=True)
class RegistryEntry:
    """A keyword mapped to its intended URL slug + the primary intent that URL
    serves (the cannibalization guard's unit)."""

    keyword: str
    url_slug: str
    intent: Intent


@dataclass(frozen=True)
class ResearchBrief:
    """The full research brief a content job is generated from.

    ``low_confidence`` is set when DA was assumed, the teardown fetched nothing,
    or any external step degraded; ``degraded`` is set when the SERP pull itself
    was gate-blocked (the brief is a shell). ``notes`` records every degrade so
    the reason is visible, never silent.
    """

    keyword: str
    geo: str | None
    serp_date: str
    intent: Intent
    intent_confidence: float
    terms: TermSet
    cluster: TopicalCluster
    content_format: FormatDecision
    fanout: list[str]
    winnability: WinnabilityReport
    teardown: Teardown
    registry: list[RegistryEntry]
    low_confidence: bool
    degraded: bool
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Seams: the page fetcher (network) + the research port (SERP/metrics/teardown)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FetchedPage:
    """A fetched ranking page: final URL, HTML body, and HTTP status."""

    url: str
    html: str
    status: int


@dataclass(frozen=True)
class TeardownFetch:
    """The teardown fetch result: the parsed ranking pages plus the URLs the SSRF
    guard refused (so the reason is visible, never a silent drop)."""

    pages: list[TeardownPage]
    refused: list[str]


@runtime_checkable
class PageFetcher(Protocol):
    """Fetch one already-SSRF-validated public URL, or ``None`` on any failure.

    Implementations MUST be non-raising (return ``None`` so one bad competitor
    never fails the brief) and bounded by ``timeout``.
    """

    def fetch(self, url: str, *, timeout: float) -> FetchedPage | None: ...


@runtime_checkable
class ResearchPort(Protocol):
    """The single door the pure orchestrator uses for all external research.

    In the worker this is a :class:`GatedResearcher`, so every call is metered by
    the cost gate and cached; the orchestrator can never reach a raw provider.
    """

    def serp(self, keyword: str, geo: str | None = None) -> SerpResult: ...
    def keyword_metrics(self, keyword: str) -> KeywordMetrics: ...
    def teardown(self, urls: list[str], keyword: str, geo: str | None) -> TeardownFetch: ...


class SsrfSafePageFetcher:
    """Real :class:`PageFetcher` over ``httpx`` with the SSRF caller-contract baked
    in: redirects are DISABLED (a 30x cannot bounce to an internal address) and a
    non-200 is dropped. The host is pre-validated by the guard before we get here;
    ``httpx`` is lazy-imported so importing this module stays network-free.
    """

    def __init__(self, *, user_agent: str = "AIOSContentBot/1.0") -> None:
        self._ua = user_agent

    def fetch(self, url: str, *, timeout: float) -> FetchedPage | None:
        try:
            import httpx
        except ImportError:  # pragma: no cover - httpx is a base dep
            logger.warning("page_fetch_no_httpx")
            return None
        try:
            with httpx.Client(
                follow_redirects=False,
                timeout=httpx.Timeout(timeout),
                headers={"User-Agent": self._ua},
            ) as client:
                resp = client.get(url)
        except Exception:  # any transport error degrades to a skip (never fails the brief)
            logger.info("page_fetch_failed", url=str(url).split("?", 1)[0])
            return None
        if resp.status_code != 200:
            return None
        return FetchedPage(url=str(resp.url), html=resp.text[:_MAX_HTML_CHARS], status=resp.status_code)


class FakePageFetcher:
    """Deterministic offline :class:`PageFetcher` - returns canned HTML per URL and
    records every URL it was asked to fetch (so a test can prove the SSRF guard
    kept a private URL from ever reaching it). No network."""

    def __init__(self, pages: Mapping[str, str] | None = None) -> None:
        self._pages = dict(pages or {})
        self.fetched: list[str] = []

    def fetch(self, url: str, *, timeout: float) -> FetchedPage | None:
        self.fetched.append(url)
        html = self._pages.get(url)
        if html is None:
            return None
        return FetchedPage(url=url, html=html, status=200)


# --------------------------------------------------------------------------- #
# The cost-gated research wrapper (mirrors context_cost.GatedSummarizer)
# --------------------------------------------------------------------------- #
class ContentSpendBlocked(RuntimeError):  # noqa: N818 - a control-flow signal the orchestrator degrades on, deliberately not an *Error
    """Raised when the gate denies a content-research call (no external call
    happened). ``outcome`` is the gate's verdict (``skip`` / ``manual`` /
    ``blocked_cap`` / ``blocked_daily``). The orchestrator catches it and returns
    a partial / low-confidence brief instead of crashing."""

    def __init__(self, outcome: GateOutcome) -> None:
        super().__init__(f"content research spend blocked by the cost gate: {outcome}")
        self.outcome: GateOutcome = outcome


class GatedResearcher:
    """A :class:`ResearchPort` that meters + caches every external research call.

    The SERP pull and per-keyword metrics are PAID Serper calls (estimated cost
    from settings); the top-10 teardown is a set of FREE public-page fetches
    (estimated cost 0) but is still gated so the ``content_research`` dial can
    switch the whole module off/byhand and still SSRF-guarded + cached. Each call
    is keyed by (keyword, geo, serp_date) so a cache hit is a gate ``cached``
    outcome (~$0) that a cluster/city sprint reuses.

    The teardown fetch routes every ranking URL through the SSRF guard
    (``url_gate``, default ``is_public_url``); a refused host is never handed to
    the fetcher. Satisfies ``ResearchPort`` structurally so the pure orchestrator
    can hold ONLY this and never a raw provider.
    """

    def __init__(
        self,
        inner: SerpResearcher,
        fetcher: PageFetcher,
        gate: CostGate,
        *,
        settings: Settings,
        client_id: str | None,
        job_id: str = "",
        serp_date: str | None = None,
        url_gate: Callable[[str], bool] = is_public_url,
    ) -> None:
        self._inner = inner
        self._fetcher = fetcher
        self._gate = gate
        self._settings = settings
        self._client_id = client_id
        self._job_id = job_id
        self._serp_date = serp_date or _today()
        self._url_gate = url_gate

    def _ctx(self, cache_key: str, *, estimated_cost: float) -> GateContext:
        return GateContext(
            feature_key=_FEATURE,
            client_id=self._client_id,
            provider=_PROVIDER,
            estimated_cost=estimated_cost,
            job_id=self._job_id,
            job_type=_JOB_TYPE,
            cache_key=cache_key,
        )

    def serp(self, keyword: str, geo: str | None = None) -> SerpResult:
        ctx = self._ctx(
            f"serp:{keyword}:{geo or ''}:{self._serp_date}",
            estimated_cost=self._settings.content_research_cost_estimate,
        )
        decision = self._gate.evaluate(ctx)
        if decision.outcome == "cached":
            return cast("SerpResult", decision.cached_value)
        if not decision.allowed:
            raise ContentSpendBlocked(decision.outcome)
        result = self._inner.serp(keyword, geo)
        # One paid Serper SERP query -> ACTUAL cost = 1 x the per-query unit price
        # (pricing.py), not the flat estimate that fronted the pre-check.
        self._gate.commit(ctx, pricing.serper_cost(self._settings, queries=1), cache_value=result)
        return result

    def keyword_metrics(self, keyword: str) -> KeywordMetrics:
        ctx = self._ctx(
            f"kwmetrics:{keyword}:{self._serp_date}",
            estimated_cost=self._settings.content_research_cost_estimate,
        )
        decision = self._gate.evaluate(ctx)
        if decision.outcome == "cached":
            return cast("KeywordMetrics", decision.cached_value)
        if not decision.allowed:
            raise ContentSpendBlocked(decision.outcome)
        result = self._inner.keyword_metrics(keyword)
        # One paid Serper keyword-metrics query -> ACTUAL cost = 1 x per-query price.
        self._gate.commit(ctx, pricing.serper_cost(self._settings, queries=1), cache_value=result)
        return result

    def teardown(self, urls: list[str], keyword: str, geo: str | None) -> TeardownFetch:
        # Free fetches (estimated cost 0), but still gated so the dial governs the
        # whole module and the result is cached across a cluster sprint.
        ctx = self._ctx(f"teardown:{keyword}:{geo or ''}:{self._serp_date}", estimated_cost=0.0)
        decision = self._gate.evaluate(ctx)
        if decision.outcome == "cached":
            return cast("TeardownFetch", decision.cached_value)
        if not decision.allowed:
            raise ContentSpendBlocked(decision.outcome)
        result = self._fetch_teardown(urls)
        self._gate.commit(ctx, 0.0, cache_value=result)
        return result

    def _fetch_teardown(self, urls: list[str]) -> TeardownFetch:
        timeout = self._settings.content_teardown_timeout_seconds
        pages: list[TeardownPage] = []
        refused: list[str] = []
        for position, url in enumerate(urls, start=1):
            # N2: the SSRF guard is the ONLY door to a fetch - a private / loopback
            # / metadata host never reaches the fetcher.
            if not self._url_gate(url):
                logger.info("teardown_url_refused", url=str(url).split("?", 1)[0])
                refused.append(url)
                continue
            fetched = self._fetcher.fetch(url, timeout=timeout)
            if fetched is None:
                continue
            pages.append(parse_teardown_page(fetched.url, position, fetched.html))
        return TeardownFetch(pages=pages, refused=refused)


# --------------------------------------------------------------------------- #
# Pure analysis functions
# --------------------------------------------------------------------------- #
def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2]


def _slug(text: str) -> str:
    """A stable URL slug: lowercase, non-alnum -> single hyphen, trimmed."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "untitled"


def _serp_text_pool(serp: SerpResult, keyword: str) -> str:
    """The lowercased text the intent/format classifiers scan: the keyword +
    every organic title/snippet + the PAA + related searches."""
    parts = [keyword]
    for item in serp.organic:
        parts.append(item.title)
        if item.snippet:
            parts.append(item.snippet)
    parts.extend(serp.people_also_ask)
    parts.extend(serp.related_searches)
    return " ".join(parts).lower()


def classify_intent(serp: SerpResult, keyword: str) -> tuple[Intent, float]:
    """Classify search intent from the SERP shape.

    Counts, per intent, how many of its signal phrases appear anywhere in the
    SERP text pool (presence, not frequency - a keyword-echoing title cannot
    dominate). The winner is the highest count; confidence is its share of all
    matched signals. No signal at all defaults to informational at low
    confidence.
    """
    pool = _serp_text_pool(serp, keyword)
    counts: dict[Intent, int] = dict.fromkeys(_INTENT_SIGNALS, 0)
    for label, signals in _INTENT_SIGNALS.items():
        for phrase in signals:
            if phrase in pool:
                counts[label] += 1
    total = sum(counts.values())
    if total == 0:
        return ("informational", 0.3)
    # Deterministic argmax: highest count, ties broken by the declared order.
    best = max(_INTENT_SIGNALS, key=lambda label: (counts[label], -_intent_rank(label)))
    confidence = round(counts[best] / total, 2)
    return (best, confidence)


def _intent_rank(label: Intent) -> int:
    order: list[Intent] = ["transactional", "commercial", "navigational", "informational"]
    return order.index(label)


def salient_entities(serp: SerpResult, *, limit: int = 8) -> list[str]:
    """Entity salience: the proper nouns that recur across organic titles +
    snippets (an entity in >=2 results is salient), most-frequent first. Falls
    back to nothing when the SERP is empty."""
    counter: Counter[str] = Counter()
    for item in serp.organic:
        text = item.title + " " + (item.snippet or "")
        for noun in {m.group(0) for m in _PROPER_NOUN_RE.finditer(text)}:
            counter[noun] += 1
    salient = [entity for entity, n in counter.most_common() if n >= 2]
    if not salient:  # thin SERP: keep the most common single-mention nouns
        salient = [entity for entity, _ in counter.most_common(limit)]
    return salient[:limit]


def fanout_questions(keyword: str, intent: Intent, serp: SerpResult, *, limit: int = 8) -> list[str]:
    """Decompose the head term into AI-Overview sub-questions.

    Starts from the SERP's own People-Also-Ask (real fan-out), then adds
    deterministic intent-appropriate templates, deduped, capped. These fold into
    the brief's question/entity set."""
    out: list[str] = []
    seen: set[str] = set()

    def add(question: str) -> None:
        key = question.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(question)

    for paa in serp.people_also_ask:
        add(paa)

    templates_by_intent: dict[Intent, tuple[str, ...]] = {
        "informational": (
            f"What is {keyword}?",
            f"How does {keyword} work?",
            f"Why does {keyword} matter?",
            f"What are the benefits of {keyword}?",
        ),
        "commercial": (
            f"What is the best {keyword}?",
            f"How do the top {keyword} options compare?",
            f"What should you look for in {keyword}?",
            f"Is {keyword} worth it?",
        ),
        "transactional": (
            f"How much does {keyword} cost?",
            f"Where can you get {keyword}?",
            f"What is included with {keyword}?",
            f"How do you choose {keyword}?",
        ),
        "navigational": (
            f"How do you access {keyword}?",
            f"What can you do with {keyword}?",
        ),
    }
    for template in templates_by_intent[intent]:
        add(template)
    return out[:limit]


def build_term_set(
    keyword: str, serp: SerpResult, questions: list[str], *, max_secondary: int = 8
) -> TermSet:
    """Assemble the coverage plan.

    Secondary terms come from related searches (deduped, excluding the primary);
    when the SERP is thin we expand with deterministic modifier terms so the
    brief always carries 3-8 secondary targets. Semantic/entity terms are the
    salient SERP entities not already named."""
    primary = keyword.strip()
    primary_key = primary.lower()

    secondary: list[str] = []
    seen: set[str] = {primary_key}
    for related in serp.related_searches:
        rel = related.strip()
        key = rel.lower()
        if rel and key not in seen:
            seen.add(key)
            secondary.append(rel)

    # Thin SERP: expand to at least 3 with stable modifier terms (never invented
    # facts - just standard intent modifiers off the head term).
    for modifier in ("services", "cost", "guide", "near me", "for small business", "examples"):
        if len(secondary) >= 3:
            break
        candidate = f"{primary} {modifier}"
        if candidate.lower() not in seen:
            seen.add(candidate.lower())
            secondary.append(candidate)
    secondary = secondary[:max_secondary]

    entities = [e for e in salient_entities(serp) if e.lower() not in seen]
    return TermSet(
        primary=primary,
        secondary=secondary,
        semantic_entities=entities,
        questions=list(questions),
    )


def cluster_terms(terms: TermSet) -> TopicalCluster:
    """Group the primary + secondary + question subtopics into ONE pillar/cluster
    map that owns the topic (a hub-and-spoke, not one-off pages). The pillar is
    the primary term; the spokes are the secondary terms plus question-derived
    subtopics."""
    supporting: list[str] = list(terms.secondary)
    seen = {s.lower() for s in supporting} | {terms.primary.lower()}
    for question in terms.questions:
        spoke = _question_to_subtopic(question)
        if spoke and spoke.lower() not in seen:
            seen.add(spoke.lower())
            supporting.append(spoke)
    return TopicalCluster(pillar=terms.primary, primary=terms.primary, supporting=supporting)


def _question_to_subtopic(question: str) -> str:
    """Strip a question down to a short subtopic phrase (drop leading wh-words +
    trailing punctuation)."""
    text = question.strip().rstrip("?").strip()
    text = re.sub(
        r"^(what is|what are|how does|how do|how much does|why does|why|where can you get|"
        r"where|when|is|how do you choose|how do you access|what can you do with|"
        r"what should you look for in|what is the best|what are the benefits of|"
        r"how do the top|what is included with)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def decide_format(serp: SerpResult, intent: Intent, keyword: str) -> FormatDecision:
    """Inspect the live SERP and recommend the content FORMAT before generation.

    Scores each format from signal presence in the SERP text pool (video also
    counts YouTube/Vimeo/TikTok result hosts), biased by the classified intent,
    and returns the argmax + a 0-1 confidence. With no strong format signal it
    falls back to the intent's natural format (informational -> blog)."""
    pool = _serp_text_pool(serp, keyword)
    scores: dict[str, int] = {str(fmt): 0 for fmt in _FORMAT_SIGNALS}
    for fmt, signals in _FORMAT_SIGNALS.items():
        for phrase in signals:
            if phrase in pool:
                scores[fmt] += 1
    # Video also reads the result hosts (a SERP full of YouTube = video intent).
    video_hosts = sum(
        1 for item in serp.organic if any(host in item.link.lower() for host in _VIDEO_HOSTS)
    )
    scores["video"] += video_hosts

    # Intent biases: nudge the format the intent naturally maps to.
    intent_bias: dict[Intent, ContentFormat] = {
        "transactional": "product",
        "commercial": "comparison",
        "navigational": "blog",
        "informational": "blog",
    }
    biased = intent_bias[intent]
    if biased in scores:
        scores[biased] += 1

    best_fmt = max(scores, key=lambda fmt: (scores[fmt], -_format_rank(fmt)))
    best_score = scores[best_fmt]
    if best_score == 0:
        return FormatDecision(recommended="blog", confidence=0.4, signals=scores)
    total = sum(scores.values())
    confidence = round(0.4 + 0.6 * (best_score / total), 2) if total else 0.4
    return FormatDecision(
        recommended=cast("ContentFormat", best_fmt),
        confidence=min(confidence, 0.99),
        signals=scores,
    )


def _format_rank(fmt: str) -> int:
    order = ["tool", "local", "product", "comparison", "video", "blog"]
    return order.index(fmt) if fmt in order else len(order)


def parse_teardown_page(url: str, position: int, html: str) -> TeardownPage:
    """Extract one ranking page's structural fingerprint from its HTML (stdlib
    regex only - no heavy parser dep): headings (h1-h3), word count, named
    entities, JSON-LD schema @types, media count, and a freshness signal."""
    html = html[:_MAX_HTML_CHARS]
    headings = [re.sub(r"\s+", " ", _TAG_RE.sub("", body)).strip() for _lvl, body in _HEADING_RE.findall(html)]
    headings = [h for h in headings if h]

    text = _TAG_RE.sub(" ", _JSONLD_RE.sub(" ", _SCRIPT_STYLE_RE.sub(" ", html)))
    text = re.sub(r"\s+", " ", text)
    word_count = len(text.split())

    entities = sorted({m.group(0) for m in _PROPER_NOUN_RE.finditer(text)})

    schema_types = _schema_types_from_html(html)
    media_count = len(_MEDIA_RE.findall(html))
    has_freshness = bool(
        {"datePublished", "dateModified"} & set(_JSONLD_KEYS_RE.findall(html))
    ) or bool(_YEAR_RE.search(text[:4000]))

    return TeardownPage(
        url=url,
        position=position,
        headings=headings[:40],
        word_count=word_count,
        entities=entities,
        schema_types=schema_types,
        media_count=media_count,
        has_freshness=has_freshness,
    )


_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_JSONLD_KEYS_RE = re.compile(r'"(datePublished|dateModified)"')


def _schema_types_from_html(html: str) -> list[str]:
    """The set of JSON-LD ``@type`` values declared on the page (best-effort;
    malformed blocks are skipped)."""
    types: set[str] = set()
    for block in _JSONLD_RE.findall(html):
        try:
            data = json.loads(block.strip())
        except (ValueError, TypeError):
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict):
                _collect_types(node.get("@type"), types)
    return sorted(types)


def _collect_types(value: Any, into: set[str]) -> None:
    if isinstance(value, str):
        into.add(value)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                into.add(item)


def analyze_teardown(pages: list[TeardownPage], refused: list[str]) -> Teardown:
    """Aggregate the fetched ranking pages into the teardown targets.

    Table-stakes entities are covered by NEAR-ALL competitors (they are the price
    of entry); differentiators are covered by some but not all (the opportunity /
    the gap). Word-count + media targets are the competitor medians; the heading
    blueprint is the most-shared section architecture; freshness is expected when
    a majority of winners carry a date signal."""
    if not pages:
        return Teardown(
            pages=[],
            table_stakes_entities=[],
            differentiator_entities=[],
            heading_blueprint=[],
            word_count_target=0,
            schema_types=[],
            media_target=0,
            freshness_expected=False,
            fetched=0,
            refused=list(refused),
        )

    n = len(pages)
    entity_pages: Counter[str] = Counter()
    for page in pages:
        for entity in set(page.entities):
            entity_pages[entity] += 1
    table_threshold = max(2, _ceil(0.7 * n))
    table_stakes = sorted(e for e, c in entity_pages.items() if c >= table_threshold)
    differentiators = sorted(e for e, c in entity_pages.items() if 2 <= c < table_threshold)

    heading_blueprint = _ordered_by_frequency(h for page in pages for h in page.headings)

    schema_types = sorted({t for page in pages for t in page.schema_types})
    word_counts = [page.word_count for page in pages]
    media_counts = [page.media_count for page in pages]
    fresh = sum(1 for page in pages if page.has_freshness)

    return Teardown(
        pages=pages,
        table_stakes_entities=table_stakes,
        differentiator_entities=differentiators,
        heading_blueprint=heading_blueprint[:15],
        word_count_target=int(median(word_counts)),
        schema_types=schema_types,
        media_target=int(median(media_counts)),
        freshness_expected=fresh * 2 >= n,
        fetched=n,
        refused=list(refused),
    )


def _ceil(value: float) -> int:
    return -int(-value // 1)


def _ordered_by_frequency(items: Iterable[str]) -> list[str]:
    """Dedupe (case-insensitively) preserving a most-frequent-first, then
    first-seen order - the shared section architecture across competitors."""
    counter: Counter[str] = Counter()
    first_seen: dict[str, tuple[int, str]] = {}
    for index, raw in enumerate(items):
        key = raw.lower().strip()
        if not key:
            continue
        counter[key] += 1
        if key not in first_seen:
            first_seen[key] = (index, raw.strip())
    ordered = sorted(counter, key=lambda k: (-counter[k], first_seen[k][0]))
    return [first_seen[k][1] for k in ordered]


def assess_winnability(
    metrics: list[KeywordMetrics],
    client_da: float | None,
    *,
    neutral_da: float = _DEFAULT_NEUTRAL_DA,
    winnable_stretch: float = _DEFAULT_WINNABLE_STRETCH,
) -> WinnabilityReport:
    """The winnability filter (N4): judge each keyword's difficulty against the
    client's authority. A keyword is winnable when the client's DA (plus a
    realistic stretch) meets or exceeds its difficulty. A missing DA falls back
    to a NEUTRAL authority and marks the report so the brief goes low-confidence -
    never a silent no-op."""
    neutral_assumed = client_da is None
    da = neutral_da if client_da is None else client_da

    targets: list[KeywordTarget] = []
    for metric in metrics:
        gap = metric.difficulty - da
        winnable = (da + winnable_stretch) >= metric.difficulty
        if winnable:
            reason = f"KD {metric.difficulty:.0f} within reach of DA {da:.0f} (gap {gap:+.0f})"
        else:
            reason = f"KD {metric.difficulty:.0f} above DA {da:.0f} (gap {gap:+.0f}) - build authority first"
        targets.append(
            KeywordTarget(
                keyword=metric.keyword,
                volume=metric.volume,
                difficulty=metric.difficulty,
                winnable=winnable,
                reason=reason,
            )
        )
    return WinnabilityReport(client_da=da, neutral_da_assumed=neutral_assumed, targets=targets)


def build_registry(terms: TermSet, intent: Intent) -> list[RegistryEntry]:
    """Map the primary + secondary keywords to intended URL slugs with one
    primary intent per URL. The secondary spokes CONSOLIDATE onto the pillar's
    slug (same intent) rather than each getting a one-off page - that
    consolidation IS the cannibalization guard."""
    pillar_slug = _slug(terms.primary)
    entries = [RegistryEntry(keyword=terms.primary, url_slug=pillar_slug, intent=intent)]
    for secondary in terms.secondary:
        entries.append(RegistryEntry(keyword=secondary, url_slug=pillar_slug, intent=intent))
    return entries


def cannibalization_conflicts(entries: list[RegistryEntry]) -> list[str]:
    """The cannibalization guard: any URL slug claimed by more than one intent is
    a conflict (two pages competing for the same URL/intent). Returns the
    offending slugs (empty = clean)."""
    intents_by_slug: dict[str, set[Intent]] = {}
    for entry in entries:
        intents_by_slug.setdefault(entry.url_slug, set()).add(entry.intent)
    return sorted(slug for slug, intents in intents_by_slug.items() if len(intents) > 1)


# --------------------------------------------------------------------------- #
# The orchestrator
# --------------------------------------------------------------------------- #
def build_research_brief(
    keyword: str,
    *,
    researcher: ResearchPort,
    geo: str | None = None,
    client_da: float | None = None,
    serp_date: str | None = None,
    max_secondary: int = 8,
    max_teardown: int = 10,
    neutral_da: float = _DEFAULT_NEUTRAL_DA,
    winnable_stretch: float = _DEFAULT_WINNABLE_STRETCH,
) -> ResearchBrief:
    """Produce the full :class:`ResearchBrief` for one target keyword.

    Every external touch goes through the injected (cost-gated) ``researcher``; a
    gate block on any step DEGRADES that part - the SERP pull blocking yields a
    shell brief (``degraded``), a teardown/metrics block drops that section and
    flips ``low_confidence`` - but the call NEVER crashes. Given the fakes the
    whole function is deterministic.
    """
    date = serp_date or _today()
    notes: list[str] = []

    # Step 1: the SERP pull grounds everything. A block here => a shell brief.
    try:
        serp = researcher.serp(keyword, geo)
    except ContentSpendBlocked as blocked:
        notes.append(f"serp pull blocked by cost gate ({blocked.outcome})")
        return _degraded_brief(keyword, geo, date, client_da, neutral_da, notes)

    # Steps 2-5: pure analysis off the SERP shape.
    intent, intent_confidence = classify_intent(serp, keyword)
    fanout = fanout_questions(keyword, intent, serp)
    terms = build_term_set(keyword, serp, fanout, max_secondary=max_secondary)
    cluster = cluster_terms(terms)
    fmt = decide_format(serp, intent, keyword)

    # Step 7: the top-10 teardown - the SSRF-guarded fetch + refused list both
    # come from the researcher (which owns the guard), so the orchestrator does
    # no network of its own.
    ranking_urls = [item.link for item in serp.organic[:max_teardown] if item.link]
    fetch = TeardownFetch(pages=[], refused=[])
    try:
        fetch = researcher.teardown(ranking_urls, keyword, geo)
    except ContentSpendBlocked as blocked:
        notes.append(f"teardown blocked by cost gate ({blocked.outcome})")
    teardown = analyze_teardown(fetch.pages, fetch.refused)
    if teardown.fetched == 0:
        notes.append("teardown fetched no pages")

    # Step 6: winnability over the primary + secondary terms (each a gated,
    # cached metrics call). A block drops the section but does not crash.
    winnability = _winnability_for(
        researcher, terms, client_da, neutral_da, winnable_stretch, notes
    )

    # Step 8: the keyword->URL registry (one primary intent per URL).
    registry = build_registry(terms, intent)

    low_confidence = (
        winnability.neutral_da_assumed
        or teardown.fetched == 0
        or len(terms.secondary) < 3
        or bool(notes)
    )
    return ResearchBrief(
        keyword=keyword,
        geo=geo,
        serp_date=date,
        intent=intent,
        intent_confidence=intent_confidence,
        terms=terms,
        cluster=cluster,
        content_format=fmt,
        fanout=fanout,
        winnability=winnability,
        teardown=teardown,
        registry=registry,
        low_confidence=low_confidence,
        degraded=False,
        notes=notes,
    )


def _winnability_for(
    researcher: ResearchPort,
    terms: TermSet,
    client_da: float | None,
    neutral_da: float,
    winnable_stretch: float,
    notes: list[str],
) -> WinnabilityReport:
    """Gather metrics for the primary + secondary terms and run the winnability
    filter. A gate block stops collecting (degrade) and flags the note."""
    metrics: list[KeywordMetrics] = []
    for term in [terms.primary, *terms.secondary]:
        try:
            metrics.append(researcher.keyword_metrics(term))
        except ContentSpendBlocked as blocked:
            notes.append(f"keyword metrics blocked by cost gate ({blocked.outcome})")
            break
    return assess_winnability(
        metrics, client_da, neutral_da=neutral_da, winnable_stretch=winnable_stretch
    )


def _degraded_brief(
    keyword: str,
    geo: str | None,
    date: str,
    client_da: float | None,
    neutral_da: float,
    notes: list[str],
) -> ResearchBrief:
    """A shell brief when the SERP pull itself is gate-blocked: enough structure
    for the caller to HOLD the job and report 'degraded', never a crash."""
    primary = keyword.strip()
    terms = TermSet(primary=primary, secondary=[], semantic_entities=[], questions=[])
    return ResearchBrief(
        keyword=keyword,
        geo=geo,
        serp_date=date,
        intent="informational",
        intent_confidence=0.0,
        terms=terms,
        cluster=TopicalCluster(pillar=primary, primary=primary, supporting=[]),
        content_format=FormatDecision(recommended="blog", confidence=0.0, signals={}),
        fanout=[],
        winnability=assess_winnability([], client_da, neutral_da=neutral_da),
        teardown=analyze_teardown([], []),
        registry=build_registry(terms, "informational"),
        low_confidence=True,
        degraded=True,
        notes=notes,
    )
