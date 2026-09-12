"""The ring geometry: does a grid describe the service area it claims to?

NO DB, NO network. Pure maths against known coordinates.

**THE MOST IMPORTANT TEST IN THIS FILE** is
``test_longitude_spacing_shrinks_with_latitude``.

A degree of longitude is ~111 km at the equator and ~62 km at Edinburgh, because the
meridians converge. Using the latitude constant for both axes - the shortcut every
naive implementation takes - stretches every grid east-west by 1/cos(lat): a "1 km"
ring drawn in Edinburgh would be 1 km north and 1.8 km east. The heat map would then
describe a service area the business does not have, and the error grows with distance
from the equator, so it is invisible in testing anywhere near it.

The other properties pinned here are the ones that make a run REPRODUCIBLE (the same
grid must probe the same physical points months apart, or two runs cannot be compared)
and PROVIDER-SAFE (a coordinate outside WGS84 bounds fails the whole DataForSEO task,
not just the point).
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from app.modules.grid_tracker.provider import (
    KM_PER_DEG_LAT,
    GridProbeResult,
    _km_per_deg_lng,
    _wrap_lng,
    make_ring_grid,
)
from app.modules.grid_tracker.schemas import MAX_RINGS, MIN_RINGS

pytestmark = pytest.mark.unit

#: The migration this module's geometry must agree with, read rather than restated.
_MIGRATION = (
    Path(__file__).resolve().parents[4] / "db" / "migrations" / "0138_grid_tracker.sql"
)

# Karachi city centre - the market the fixtures elsewhere in this module use.
KARACHI = (24.8607, 67.0011)


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance, as an INDEPENDENT check on the flat-earth offsets the
    grid builder uses. If the two agree at these radii, the approximation is sound
    over a service area; that is the only claim being made."""
    r = 6371.0088
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


class TestPointCount:
    def test_the_count_is_the_formula_the_migration_generates(self) -> None:
        """``0138``'s ``point_count`` is a GENERATED column. The builder must produce
        exactly as many points as that column promises, or the cost estimate an
        operator approves stops matching the number of paid probes actually issued.

        This READS the migration and evaluates its expression rather than re-stating
        the formula here - a hand-copied literal is a second copy of the thing that
        drifts, not a pin on it.
        """
        sql = _MIGRATION.read_text(encoding="utf-8")
        match = re.search(
            r"point_count\s+integer\s+generated\s+always\s+as\s*\((.+?)\)\s*stored",
            sql,
            re.IGNORECASE | re.DOTALL,
        )
        assert match, "0138 no longer declares a generated point_count column"
        expression = match.group(1).strip()
        # The expression is arithmetic over the single column `rings`. Evaluating it
        # against each ring count is what makes this a comparison and not a copy.
        assert set(re.findall(r"[a-z_]+", expression)) == {"rings"}, (
            f"point_count now depends on more than `rings` ({expression!r}); this "
            "test can no longer evaluate it standalone"
        )
        for rings in range(MIN_RINGS, MAX_RINGS + 1):
            expected = eval(expression, {"__builtins__": {}}, {"rings": rings})
            grid = make_ring_grid(
                center_lat=KARACHI[0], center_lng=KARACHI[1], rings=rings, spacing_km=1.5
            )
            assert len(grid) == expected, (
                f"rings={rings}: the builder made {len(grid)} point(s), but 0138's "
                f"generated column promises {expected}"
            )

    def test_the_first_point_is_the_centre(self) -> None:
        grid = make_ring_grid(
            center_lat=KARACHI[0], center_lng=KARACHI[1], rings=2, spacing_km=1.0
        )
        assert grid[0].label == "center"
        assert grid[0].ring == 0
        assert (grid[0].lat, grid[0].lng) == (round(KARACHI[0], 6), round(KARACHI[1], 6))

    def test_every_label_is_unique(self) -> None:
        """``0138`` declares ``unique (run_id, label)``. A duplicate label would make
        the worker's per-point insert collide and lose a probe that was paid for."""
        grid = make_ring_grid(
            center_lat=KARACHI[0], center_lng=KARACHI[1], rings=5, spacing_km=0.5
        )
        labels = [p.label for p in grid]
        assert len(labels) == len(set(labels)) == 41


class TestDistances:
    @pytest.mark.parametrize("spacing", [0.5, 1.5, 5.0])
    def test_each_ring_sits_at_its_nominal_radius(self, spacing: float) -> None:
        """Ring N must be N x spacing from the centre, measured by haversine - not by
        the same flat-earth formula that produced it."""
        grid = make_ring_grid(
            center_lat=KARACHI[0], center_lng=KARACHI[1], rings=3, spacing_km=spacing
        )
        for point in grid[1:]:
            measured = _haversine_km(KARACHI, (point.lat, point.lng))
            expected = spacing * point.ring
            assert measured == pytest.approx(expected, rel=0.02), (
                f"{point.label} sits {measured:.3f} km out, expected {expected:.3f}"
            )

    def test_a_ring_is_actually_round(self) -> None:
        """Every point of one ring is equidistant from the centre. A grid that is
        round in the maths and oval on the map is the cos(lat) bug below."""
        grid = make_ring_grid(
            center_lat=55.9533, center_lng=-3.1883, rings=1, spacing_km=2.0  # Edinburgh
        )
        radii = [_haversine_km((55.9533, -3.1883), (p.lat, p.lng)) for p in grid[1:]]
        assert max(radii) - min(radii) < 0.05, f"ring is not round: {radii}"


class TestLongitudeConvergence:
    def test_longitude_spacing_shrinks_with_latitude(self) -> None:
        """THE BUG THIS MODULE'S GEOMETRY EXISTS TO AVOID.

        At the equator a degree of longitude is ~111 km; at 60N it is ~55 km. An
        implementation that ignores this draws a grid stretched east-west by
        1/cos(lat) - 2x at 60 degrees - and the resulting heat map describes an area
        the business does not serve.
        """
        assert _km_per_deg_lng(0.0) == pytest.approx(KM_PER_DEG_LAT, rel=1e-6)
        assert _km_per_deg_lng(60.0) == pytest.approx(KM_PER_DEG_LAT / 2, rel=0.01)
        assert _km_per_deg_lng(-60.0) == pytest.approx(KM_PER_DEG_LAT / 2, rel=0.01)

    def test_the_east_point_is_not_stretched_at_high_latitude(self) -> None:
        """The regression the constant-per-degree shortcut would produce: E-1 landing
        far outside its ring while N-1 sits correctly on it."""
        grid = make_ring_grid(
            center_lat=60.0, center_lng=10.0, rings=1, spacing_km=3.0
        )
        by_label = {p.label: p for p in grid}
        north = _haversine_km((60.0, 10.0), (by_label["N-1"].lat, by_label["N-1"].lng))
        east = _haversine_km((60.0, 10.0), (by_label["E-1"].lat, by_label["E-1"].lng))
        assert north == pytest.approx(3.0, rel=0.02)
        assert east == pytest.approx(3.0, rel=0.02)
        # The naive version would put E-1 at ~6 km. Pin the ratio, not just the value.
        assert abs(east - north) < 0.1

    def test_a_polar_centre_stays_finite(self) -> None:
        """cos(89.999) is ~0, so an unclamped divisor produces infinities and the
        provider rejects the whole task. No local business is here; the clamp is a
        safety rail so bad input degrades to a small grid, not to a crash."""
        grid = make_ring_grid(center_lat=89.999, center_lng=0.0, rings=1, spacing_km=1.0)
        assert all(math.isfinite(p.lat) and math.isfinite(p.lng) for p in grid)
        assert all(-90.0 <= p.lat <= 90.0 for p in grid)
        assert all(-180.0 <= p.lng <= 180.0 for p in grid)


class TestProviderSafety:
    def test_coordinates_never_leave_wgs84_bounds(self) -> None:
        """DataForSEO rejects a task whose ``location_coordinate`` is out of range -
        and it rejects the TASK, so one bad point would cost the whole probe."""
        for lat, lng in [(89.5, 179.9), (-89.5, -179.9), (0.0, 180.0)]:
            grid = make_ring_grid(center_lat=lat, center_lng=lng, rings=2, spacing_km=10.0)
            for p in grid:
                assert -90.0 <= p.lat <= 90.0, f"{p.label} lat {p.lat}"
                assert -180.0 <= p.lng <= 180.0, f"{p.label} lng {p.lng}"

    def test_longitude_wraps_across_the_antimeridian(self) -> None:
        """A grid centred at 179.8E has eastern points past 180. They wrap to -179.x
        rather than becoming 180.4, which is not a longitude."""
        assert _wrap_lng(180.4) == pytest.approx(-179.6)
        assert _wrap_lng(-180.4) == pytest.approx(179.6)
        assert _wrap_lng(0.0) == pytest.approx(0.0)
        grid = make_ring_grid(center_lat=0.0, center_lng=179.8, rings=1, spacing_km=50.0)
        east = next(p for p in grid if p.label == "E-1")
        assert east.lng < 0, "an eastern point past the antimeridian must wrap negative"

    def test_the_grid_is_reproducible(self) -> None:
        """Two builds of the same definition give identical coordinates, which is what
        makes a March run and a September run comparable point-for-point."""
        args = {"center_lat": KARACHI[0], "center_lng": KARACHI[1], "rings": 3, "spacing_km": 1.25}
        assert make_ring_grid(**args) == make_ring_grid(**args)  # type: ignore[arg-type]


class TestProbeResultStates:
    """The three-state contract, at the dataclass rather than at the database."""

    def test_only_ranked_and_absent_count_as_measured(self) -> None:
        assert GridProbeResult(status="ranked", rank=3).measured is True
        assert GridProbeResult(status="absent").measured is True
        assert GridProbeResult(status="error", error="timeout").measured is False

    def test_in_map_pack_is_the_top_three_and_needs_a_rank(self) -> None:
        assert GridProbeResult(status="ranked", rank=3).in_map_pack is True
        assert GridProbeResult(status="ranked", rank=4).in_map_pack is False
        # An error can never be "in the pack", whatever else it carries.
        assert GridProbeResult(status="error", error="timeout").in_map_pack is False
