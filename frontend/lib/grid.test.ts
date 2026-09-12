import { describe, expect, it } from "vitest";

import { atrp, coverageSentence, pointLabel, pointTone, solv } from "./grid";
import type { GridPoint, GridRun } from "./grid";

/**
 * The grid's rendering contract: never claim an outcome that was not measured.
 *
 * **THE MOST IMPORTANT TEST IN THIS FILE** is
 * `an in-flight run is not reported as a failure`.
 *
 * `shareTop3` is null whenever nothing has been measured YET - which is true of a
 * queued or running grid exactly as much as of one where every probe errored. The
 * sentence branched on that null alone, so a grid mid-sweep announced
 *
 *     "No point could be measured (25 probes failed)."
 *
 * about a run that had failed nothing. Reported from production on 2026-09-12, and it
 * is this module's own defect class turned on itself: the three-state point contract
 * exists precisely so that "not measured" is never rendered as a measured outcome, and
 * the run-level sentence was doing it anyway.
 *
 * The rest pin the arithmetic that must divide by MEASURED points, never by the grid
 * total - a rate-limited afternoon must not read as a collapsing service area.
 */

function run(over: Partial<GridRun> = {}): GridRun {
  return {
    id: "r1", definitionId: "d1", status: "completed", reason: "",
    shape: "square", gridSize: 5, rings: 2, ringSpacingKm: 1,
    pointsTotal: 25, pointsMeasured: 25, pointsRanked: 10, pointsAbsent: 15,
    pointsError: 0, avgRank: 4.2, shareTop3: 0.4, coverage: "mixed",
    provider: "dataforseo_maps_grid", costUsd: 0.08,
    startedAt: "2026-09-12T23:00:00Z", finishedAt: "2026-09-12T23:02:00Z",
    ...over,
  };
}

function point(over: Partial<GridPoint> = {}): GridPoint {
  return {
    lat: 28.09, lng: -82.73, label: "B2", ring: 0, status: "ranked", rank: 3,
    inMapPack: true, topCompetitors: [], foundUrl: "", error: "", ...over,
  };
}

describe("a run that has not finished has not failed", () => {
  it("an in-flight run is not reported as a failure", () => {
    // The exact production shape: running, nothing measured, nothing errored.
    const s = coverageSentence(
      run({ status: "running", pointsMeasured: 0, pointsRanked: 0, pointsAbsent: 0,
            pointsError: 0, shareTop3: null, avgRank: null }),
    );
    expect(s).toMatch(/measuring/i);
    expect(s).not.toMatch(/failed/i);
    expect(s).not.toMatch(/could not be measured/i);
  });

  it("a queued run says so rather than claiming 0%", () => {
    const s = coverageSentence(
      run({ status: "queued", pointsMeasured: 0, pointsRanked: 0, pointsAbsent: 0,
            pointsError: 0, shareTop3: null, avgRank: null }),
    );
    expect(s).toMatch(/measuring/i);
    expect(s).not.toMatch(/failed/i);
  });

  it("an in-flight run reports PROGRESS once probes have landed", () => {
    const s = coverageSentence(
      run({ status: "running", pointsMeasured: 6, pointsRanked: 2, pointsAbsent: 4,
            pointsError: 1, shareTop3: null }),
    );
    expect(s).toContain("7 of 25");
  });
});

describe("a terminal run says WHY nothing was measured", () => {
  it("a gate block names the gate, not the provider", () => {
    // 25 unreached probes with the spend gate's own reason. An operator sent to check
    // DataForSEO for a switch that is simply off loses an afternoon.
    const s = coverageSentence(
      run({ status: "failed", pointsMeasured: 0, pointsRanked: 0, pointsAbsent: 0,
            pointsError: 25, shareTop3: null, avgRank: null,
            reason: "the spend gate stopped this run after 0 of 25 probe(s)" }),
    );
    expect(s).toContain("spend gate");
    expect(s).toContain("25 probes");
  });

  it("a provider that answered nothing still reads as unmeasured, never as absent", () => {
    const s = coverageSentence(
      run({ status: "failed", pointsMeasured: 0, pointsRanked: 0, pointsAbsent: 0,
            pointsError: 25, shareTop3: null, avgRank: null, reason: "" }),
    );
    expect(s).toMatch(/no point could be measured/i);
    // "not in the pack" would be a measurement claim about 25 unlooked-at points.
    expect(s).not.toMatch(/not in the (map )?pack/i);
  });

  it("a completed run with a real 0% is a MEASUREMENT, not a failure", () => {
    // Measured everywhere, in the pack nowhere. That is a genuine 0 and must read
    // as one - the opposite error to the bug above.
    const s = coverageSentence(
      run({ pointsMeasured: 25, pointsRanked: 0, pointsAbsent: 25, shareTop3: 0,
            avgRank: null }),
    );
    expect(s).toContain("0%");
    expect(s).toContain("25 points measured");
    expect(s).not.toMatch(/failed|could not be measured/i);
  });
});

describe("every ratio divides by what was MEASURED", () => {
  it("a partial run states its denominator", () => {
    const s = coverageSentence(
      run({ pointsTotal: 25, pointsMeasured: 20, pointsRanked: 5, pointsAbsent: 15,
            pointsError: 5, shareTop3: 0.25, status: "degraded" }),
    );
    expect(s).toContain("20 points measured");
    expect(s).toContain("5 of 25 could not be measured");
  });

  it("solv and atrp are null when there is nothing to divide", () => {
    expect(solv(run({ pointsMeasured: 0, shareTop3: null }))).toBeNull();
    expect(atrp(run({ pointsRanked: 0, avgRank: null }))).toBeNull();
  });
});

describe("a point never invents a position", () => {
  it("an unmeasured point is grey, not the worst band", () => {
    expect(pointTone(point({ status: "error", rank: null, error: "timeout" })))
      .toBe("unmeasured");
    expect(pointTone(point({ status: "absent", rank: null }))).toBe("absent");
  });

  it("an unmeasured point's label says unmeasured and carries the reason", () => {
    const l = pointLabel(point({ status: "error", rank: null, error: "rate limited" }));
    expect(l).toMatch(/not measured/i);
    expect(l).toContain("rate limited");
    expect(l).not.toMatch(/#\d/);
  });
});
