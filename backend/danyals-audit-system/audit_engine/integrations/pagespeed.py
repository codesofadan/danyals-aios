"""Google PageSpeed Insights API client (free).

Endpoint: https://www.googleapis.com/pagespeedonline/v5/runPagespeed
Pulls both lab (Lighthouse) and field (CrUX) data when available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from audit_engine.integrations.base import BaseClient
from audit_engine.logging_setup import get_logger

log = get_logger(__name__)

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
Strategy = Literal["mobile", "desktop"]
Category = Literal["performance", "accessibility", "best-practices", "seo", "pwa"]


#: Unit suffixes CrUX appends to a metric name. They describe the unit, not the
#: metric, so two names for one measurement differ only by these.
_METRIC_SUFFIXES = ("_ms", "_score", "_s")


def canonical_metric(name: str) -> str:
    """One identifier per metric, whatever shape PageSpeed used.

    CrUX returns ``LARGEST_CONTENTFUL_PAINT_MS``; Lighthouse returns
    ``largest-contentful-paint``. Code matching either one silently misses the
    other, which is how Largest Contentful Paint and Cumulative Layout Shift
    came to be reported as "not measured" on every audit while the response
    contained both.
    """
    key = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    for suffix in _METRIC_SUFFIXES:
        if key.endswith(suffix):
            key = key[: -len(suffix)]
            break
    return key


@dataclass(frozen=True)
class CWVMetric:
    name: str
    value: float | None
    unit: str
    percentile: float | None
    rating: str | None  # GOOD | NEEDS_IMPROVEMENT | POOR | None
    #: Canonical identifier, comparable across the field and lab shapes.
    #: Appended last with a default so positional construction still works.
    key: str = ""


@dataclass(frozen=True)
class PageSpeedResult:
    url: str
    strategy: Strategy
    lighthouse_scores: dict[str, float]
    field_metrics: list[CWVMetric]
    lab_metrics: list[CWVMetric]
    opportunities: list[dict[str, Any]]
    diagnostics: list[dict[str, Any]]
    fetch_time: str | None
    error: str | None = None
    #: EVERY Lighthouse audit, keyed by id, whether it passed or failed.
    #: opportunities/diagnostics keep only failing rows, so a check reading
    #: them cannot tell "this passed" from "we did not look" - and reporting
    #: the second as the first is the exact failure this audit system exists
    #: to avoid. Appended last with a default so positional construction and
    #: every existing test keep working.
    audits: dict[str, dict[str, Any]] = field(default_factory=dict)


class PageSpeedClient(BaseClient):
    provider_name = "pagespeed"
    base_url = PSI_ENDPOINT

    def __init__(self, *, api_key: str | None = None, timeout: float = 60.0) -> None:
        # PSI runs Lighthouse server-side; 30-60s is normal.
        super().__init__(timeout=timeout, max_retries=2)
        self._api_key = api_key

    async def analyze(
        self,
        url: str,
        *,
        strategy: Strategy = "mobile",
        categories: tuple[Category, ...] = ("performance", "seo", "accessibility", "best-practices"),
    ) -> PageSpeedResult:
        params: dict[str, Any] = {"url": url, "strategy": strategy}
        for c in categories:
            params.setdefault("category", []).append(c) if isinstance(
                params.get("category"), list
            ) else params.update({"category": [c]})
        # PSI expects repeated 'category=' params; httpx handles lists natively.
        if self._api_key:
            params["key"] = self._api_key

        try:
            resp = await self.get(PSI_ENDPOINT, params=params)
            data = resp.json()
        except Exception as e:
            log.error("psi_fetch_failed", url=url, error=type(e).__name__)
            return PageSpeedResult(
                url=url,
                strategy=strategy,
                lighthouse_scores={},
                field_metrics=[],
                lab_metrics=[],
                opportunities=[],
                diagnostics=[],
                fetch_time=None,
                error=f"{type(e).__name__}: {e}",
            )

        return self._parse(url, strategy, data)

    @staticmethod
    def _parse(url: str, strategy: Strategy, data: dict[str, Any]) -> PageSpeedResult:
        lighthouse = data.get("lighthouseResult") or {}
        loading = data.get("loadingExperience") or {}

        scores: dict[str, float] = {}
        for cat_id, cat in (lighthouse.get("categories") or {}).items():
            score = cat.get("score")
            if score is not None:
                scores[cat_id] = round(float(score) * 100, 1)

        field_metrics = []
        for k, v in (loading.get("metrics") or {}).items():
            field_metrics.append(
                CWVMetric(
                    name=k,
                    value=v.get("percentile"),
                    unit="ms" if "TIME" in k or "PAINT" in k else "score",
                    percentile=v.get("percentile"),
                    rating=v.get("category"),
                    key=canonical_metric(k),
                )
            )

        lab_metrics = []
        audits = (lighthouse.get("audits") or {})
        for audit_id in (
            "largest-contentful-paint",
            "cumulative-layout-shift",
            "first-contentful-paint",
            "total-blocking-time",
            "speed-index",
            "interactive",
            "server-response-time",
            "experimental-interaction-to-next-paint",
        ):
            audit = audits.get(audit_id)
            if not audit:
                continue
            lab_metrics.append(
                CWVMetric(
                    name=audit_id,
                    value=audit.get("numericValue"),
                    unit=audit.get("numericUnit") or "ms",
                    percentile=None,
                    rating=audit.get("scoreDisplayMode"),
                    key=canonical_metric(audit_id),
                )
            )

        # Opportunities = audits with details.type == "opportunity" and score < 1
        opportunities = []
        diagnostics = []
        all_audits: dict[str, dict[str, Any]] = {}
        for audit_id, audit in audits.items():
            details = audit.get("details") or {}
            score = audit.get("score")
            row = {
                "id": audit_id,
                "title": audit.get("title"),
                "description": audit.get("description"),
                "score": score,
                "displayValue": audit.get("displayValue"),
                "numericValue": audit.get("numericValue"),
            }
            all_audits[audit_id] = {
                **row,
                "scoreDisplayMode": audit.get("scoreDisplayMode"),
                # Row counts only: the full details blob can be megabytes and
                # would be carried into evidence_json and then a client PDF.
                "items": len(details.get("items") or []),
                "overallSavingsMs": details.get("overallSavingsMs"),
                "overallSavingsBytes": details.get("overallSavingsBytes"),
            }
            if details.get("type") == "opportunity" and score is not None and score < 1:
                opportunities.append(row)
            elif details.get("type") == "table" and score is not None and score < 1:
                diagnostics.append(row)

        return PageSpeedResult(
            url=url,
            strategy=strategy,
            lighthouse_scores=scores,
            field_metrics=field_metrics,
            lab_metrics=lab_metrics,
            opportunities=opportunities,
            diagnostics=diagnostics,
            fetch_time=lighthouse.get("fetchTime"),
            audits=all_audits,
        )
