"""Score aggregation. Per-team and overall.

Profile-aware weights. Default = 'general' (Danyal's agency serves every
niche): 30% on-page / 30% technical / 30% off-page / 10% local SEO.
Pass profile='local' for local-market businesses to weight local SEO at 30%.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from audit_engine.db.repository import Finding

SEVERITY_WEIGHT = {"critical": 3.0, "major": 2.0, "minor": 1.0, "info": 0.5}

PROFILE_WEIGHTS = {
    "local":     {"on_page": 0.30, "technical": 0.25, "off_page": 0.15, "local": 0.30},
    "ecommerce": {"on_page": 0.35, "technical": 0.30, "off_page": 0.25, "local": 0.10},
    "saas":      {"on_page": 0.40, "technical": 0.30, "off_page": 0.25, "local": 0.05},
    "content":   {"on_page": 0.45, "technical": 0.25, "off_page": 0.25, "local": 0.05},
    "general":   {"on_page": 0.30, "technical": 0.30, "off_page": 0.30, "local": 0.10},
}


def _team_score(findings: list[dict]) -> float | None:
    """Severity-weighted average of finding scores in 0-100 range."""
    relevant = [f for f in findings if f["status"] not in ("n_a",) and f.get("score") is not None]
    if not relevant:
        return None
    total_weight = 0.0
    weighted_sum = 0.0
    for f in relevant:
        w = SEVERITY_WEIGHT.get(f["severity"], 1.0)
        # finding.score is 0-10; rescale to 0-100.
        weighted_sum += (f["score"] * 10) * w
        total_weight += w
    return round(weighted_sum / total_weight, 1) if total_weight else None


def aggregate(findings: list[dict], *, profile: str = "general") -> dict[str, float | None]:
    by_category: dict[str, list[dict]] = defaultdict(list)
    for f in findings:
        by_category[f["category"]].append(f)

    scores: dict[str, float | None] = {
        "on_page": _team_score(by_category.get("on-page", [])),
        "technical": _team_score(by_category.get("technical", [])),
        "off_page": _team_score(by_category.get("off-page", [])),
        "local": _team_score(by_category.get("local-seo", [])),
    }

    weights = PROFILE_WEIGHTS.get(profile, PROFILE_WEIGHTS["general"])
    parts = []
    total_w = 0.0
    for cat, w in weights.items():
        v = scores.get(cat)
        if v is None:
            continue
        parts.append(v * w)
        total_w += w
    scores["overall"] = round(sum(parts) / total_w, 1) if total_w else None
    return scores
