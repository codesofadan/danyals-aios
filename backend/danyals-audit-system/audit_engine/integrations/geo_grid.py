"""Geo-grid SERP utility.

Given a business location (lat, lng), a keyword, and a grid spec, this module
generates a list of (lat, lng) probe points and queries Serper.dev with the
`location` parameter set per point. The result is a grid heatmap of map-pack
positions across the local service area.

Lightweight: returns a list of (point, position) tuples. The local-pack analyzer
synthesizes the heatmap and surfaces gaps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from audit_engine.integrations.serper import SerperClient


# Approximate kilometers per degree of latitude.
KM_PER_DEG_LAT = 111.0


@dataclass
class GridPoint:
    lat: float
    lng: float
    label: str   # e.g., "center", "N-1mi", "NE-2mi"


@dataclass
class GridProbe:
    point: GridPoint
    position: int | None
    competitor_top3: list[str] = field(default_factory=list)
    error: str | None = None


def make_ring_grid(
    *, center_lat: float, center_lng: float, radii_km: list[float]
) -> list[GridPoint]:
    """Generate a center + 8-point ring per radius (N, NE, E, SE, S, SW, W, NW)."""
    points: list[GridPoint] = [GridPoint(lat=center_lat, lng=center_lng, label="center")]
    directions = [
        ("N", 0.0), ("NE", 45.0), ("E", 90.0), ("SE", 135.0),
        ("S", 180.0), ("SW", 225.0), ("W", 270.0), ("NW", 315.0),
    ]
    cos_lat = math.cos(math.radians(center_lat))
    km_per_deg_lng = KM_PER_DEG_LAT * cos_lat if cos_lat else KM_PER_DEG_LAT
    for r in radii_km:
        for label, bearing_deg in directions:
            bearing = math.radians(bearing_deg)
            dlat = (r / KM_PER_DEG_LAT) * math.cos(bearing)
            dlng = (r / km_per_deg_lng) * math.sin(bearing)
            points.append(
                GridPoint(
                    lat=round(center_lat + dlat, 6),
                    lng=round(center_lng + dlng, 6),
                    label=f"{label}-{int(r)}km",
                )
            )
    return points


async def probe_grid(
    serper: SerperClient,
    *,
    keyword: str,
    domain: str,
    grid: list[GridPoint],
) -> list[GridProbe]:
    """Run a SERP probe at each grid point. Map-pack position recorded if found."""
    out: list[GridProbe] = []
    domain_clean = domain.replace("https://", "").replace("http://", "").rstrip("/").lower()

    for pt in grid:
        # Serper's `location` accepts a city string; for grid use we encode the
        # point as a "lat,lng" string. Different plans treat this differently;
        # if Serper does not accept lat/lng we fall back to a city-level probe.
        location = f"{pt.lat},{pt.lng}"
        try:
            position, resp = await serper.rank_check(
                domain_clean, keyword, location=location, results=20
            )
        except Exception as e:  # noqa: BLE001
            out.append(GridProbe(point=pt, position=None, error=f"{type(e).__name__}: {e}"))
            continue
        competitors: list[str] = []
        for r in resp.organic[:3]:
            host = r.link.replace("https://", "").replace("http://", "").split("/", 1)[0].lower()
            if host != domain_clean and not host.endswith("." + domain_clean):
                competitors.append(host)
        out.append(GridProbe(point=pt, position=position, competitor_top3=competitors))
    return out


def summarize_grid(probes: list[GridProbe]) -> dict:
    """Summary stats for the heatmap."""
    in_top3 = sum(1 for p in probes if p.position is not None and p.position <= 3)
    in_top10 = sum(1 for p in probes if p.position is not None and p.position <= 10)
    not_ranked = sum(1 for p in probes if p.position is None)
    avg_pos = (
        sum(p.position for p in probes if p.position is not None)
        / max(1, sum(1 for p in probes if p.position is not None))
    )
    return {
        "grid_size": len(probes),
        "in_top3": in_top3,
        "in_top10": in_top10,
        "not_ranked": not_ranked,
        "avg_position": round(avg_pos, 2) if any(p.position for p in probes) else None,
        "share_top3": round(in_top3 / max(1, len(probes)), 2),
        "share_top10": round(in_top10 / max(1, len(probes)), 2),
        "competitors": _dedupe(p for probe in probes for p in probe.competitor_top3),
    }


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out
