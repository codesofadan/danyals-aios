"""Google Cloud Natural Language API client.

Used by Module 3 (Semantic SEO) to enrich entity-coverage and intent
analysis with Google's own entity extractor + category classifier.

Auth: API key via `?key=...` query param (simplest pattern). For service
account auth use GOOGLE_APPLICATION_CREDENTIALS; this client supports the
API-key path only.

Endpoints used:
  POST /v1/documents:analyzeEntities
  POST /v1/documents:classifyText  (requires document >= 20 tokens)
  POST /v1/documents:analyzeSentiment

Pricing (as of 2026, verify in Google Cloud Console):
  - analyzeEntities: free for first 5,000 units / month, then ~$1 / 1,000
  - classifyText: free for first 30,000 units / month
  - 1 unit = up to 1,000 characters

Graceful degrade: if no key is configured, every method returns an empty
result object with `error="GOOGLE_NL_API_KEY not set"` - the analyzer
treats that as `n_a` rather than crashing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from audit_engine.integrations.base import BaseClient
from audit_engine.logging_setup import get_logger

log = get_logger(__name__)

GOOGLE_NL_BASE = "https://language.googleapis.com/v1"


@dataclass
class NLEntity:
    name: str
    type: str                # PERSON | LOCATION | ORGANIZATION | EVENT | WORK_OF_ART | etc
    salience: float          # 0.0 - 1.0; how central to the document
    wikipedia_url: str | None = None
    mid: str | None = None   # Knowledge Graph machine ID
    mention_count: int = 0


@dataclass
class NLCategory:
    name: str                # e.g. "/Business & Industrial/Industrial Materials & Equipment"
    confidence: float        # 0.0 - 1.0


@dataclass
class NLAnalysis:
    """Aggregated NL analysis for one document."""
    entities: list[NLEntity] = field(default_factory=list)
    categories: list[NLCategory] = field(default_factory=list)
    sentiment_score: float | None = None    # -1.0 (neg) to 1.0 (pos)
    sentiment_magnitude: float | None = None
    language: str | None = None
    error: str | None = None

    @property
    def top_entities(self) -> list[NLEntity]:
        return sorted(self.entities, key=lambda e: -e.salience)[:10]

    @property
    def primary_category(self) -> NLCategory | None:
        if not self.categories:
            return None
        return max(self.categories, key=lambda c: c.confidence)


class GoogleNLClient(BaseClient):
    provider_name = "google_nl"
    base_url = GOOGLE_NL_BASE

    def __init__(self, *, api_key: str | None = None, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._enabled = bool(api_key)
        super().__init__(timeout=timeout, max_retries=2, headers={"Content-Type": "application/json"})

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _doc(self, text: str) -> dict[str, Any]:
        # NL API caps documents around 1M bytes; we cap at 100k chars to keep
        # cost predictable.
        return {
            "type": "PLAIN_TEXT",
            "content": (text or "")[:100_000],
            "language": "en",
        }

    async def analyze_entities(self, text: str) -> list[NLEntity]:
        if not self._enabled:
            return []
        if not text or len(text.strip()) < 20:
            return []
        payload = {"document": self._doc(text), "encodingType": "UTF8"}
        try:
            resp = await self.post(f"documents:analyzeEntities?key={self._api_key}", json_body=payload)
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            log.warning("google_nl_entities_failed", error=type(e).__name__)
            return []
        out: list[NLEntity] = []
        for ent in data.get("entities", []) or []:
            md = ent.get("metadata") or {}
            out.append(NLEntity(
                name=str(ent.get("name") or "")[:200],
                type=str(ent.get("type") or "OTHER"),
                salience=float(ent.get("salience") or 0.0),
                wikipedia_url=md.get("wikipedia_url"),
                mid=md.get("mid"),
                mention_count=len(ent.get("mentions") or []),
            ))
        return out

    async def classify_text(self, text: str) -> list[NLCategory]:
        """Classify the document into Google's content taxonomy.
        Requires at least ~20 tokens; returns empty list when text is too thin.
        """
        if not self._enabled:
            return []
        if not text or len(text.strip()) < 80:
            return []
        payload = {"document": self._doc(text)}
        try:
            resp = await self.post(f"documents:classifyText?key={self._api_key}", json_body=payload)
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            # Most common cause: document too short. We treat as n_a, not error.
            log.info("google_nl_classify_skipped", error=type(e).__name__)
            return []
        return [
            NLCategory(name=str(c.get("name") or ""), confidence=float(c.get("confidence") or 0.0))
            for c in (data.get("categories") or [])
        ]

    async def analyze_sentiment(self, text: str) -> tuple[float | None, float | None]:
        """Returns (score, magnitude). Score: -1.0 (negative) to 1.0 (positive)."""
        if not self._enabled or not text or len(text.strip()) < 40:
            return (None, None)
        payload = {"document": self._doc(text), "encodingType": "UTF8"}
        try:
            resp = await self.post(f"documents:analyzeSentiment?key={self._api_key}", json_body=payload)
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            log.warning("google_nl_sentiment_failed", error=type(e).__name__)
            return (None, None)
        doc_sent = (data.get("documentSentiment") or {})
        score = doc_sent.get("score")
        magnitude = doc_sent.get("magnitude")
        return (
            float(score) if score is not None else None,
            float(magnitude) if magnitude is not None else None,
        )

    async def analyze(self, text: str, *, want_categories: bool = True, want_sentiment: bool = False) -> NLAnalysis:
        """One-shot wrapper that fans out entity + classification (+ sentiment).

        Falls back to empty lists for any sub-call that fails. The caller
        always gets a populated NLAnalysis (or one with `error` set if the
        client is disabled).
        """
        if not self._enabled:
            return NLAnalysis(error="GOOGLE_NL_API_KEY not set")
        entities = await self.analyze_entities(text)
        categories: list[NLCategory] = []
        if want_categories:
            categories = await self.classify_text(text)
        s_score = s_mag = None
        if want_sentiment:
            s_score, s_mag = await self.analyze_sentiment(text)
        return NLAnalysis(
            entities=entities,
            categories=categories,
            sentiment_score=s_score,
            sentiment_magnitude=s_mag,
            language="en",
        )
