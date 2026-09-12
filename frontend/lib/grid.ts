// ============================================================
// AIOS · Local search GRID tracking types (migration 0138)
// Mirrors the backend grid_tracker schemas. A new domain file, like lib/gmb.ts.
//
// THE ONE THING TO CARRY OVER FROM THE BACKEND: a point has THREE states, not a
// nullable rank. `ranked` was measured and found; `absent` was measured and not
// found; `error` was NEVER MEASURED. Rendering a null rank as "not ranking" merges
// the last two, and the one that suffers is always the honest gap - a provider
// hiccup then paints as a business losing its service area.
//
// So: read `status`, never the nullability of `rank`. Same for the run-level
// `avgRank` / `shareTop3`, which are null when they are not computable and must
// never render as 0.
// ============================================================

/** A probe's outcome. `error` means unmeasured - it is NOT an absence. */
export type GridPointStatus = "ranked" | "absent" | "error";

/** A run's terminal state, sharing the job contract's vocabulary. */
export type GridRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "degraded"
  | "blocked"
  | "failed"
  | "cancelled";

/**
 * The legend band, derived SERVER-side so every surface bands identically.
 * `unmeasured` is its own band and must not be styled as the worst one - no data
 * is not bad data.
 */
export type GridCoverage = "strong" | "mixed" | "weak" | "absent" | "unmeasured";

/** How a grid's centre was established. */
export type GridCenterSource = "places" | "operator";

/**
 * `square` is an N×N lattice — the shape every tool in this market presents, and what
 * the map draws. `rings` is the original concentric geometry, kept so a grid measured
 * that way is still redrawn as what was actually probed.
 */
export type GridShape = "square" | "rings";

export type GridDefinition = {
  id: string;
  client: string;
  /** The GBP profile's location label - the `[Location]` cell. */
  location: string;
  keyword: string;
  centerLat: number;
  centerLng: number;
  centerSource: GridCenterSource;
  shape: GridShape;
  /** N for an N×N square grid. */
  gridSize: number;
  /**
   * WHICH Google listing a `places`-resolved centre came from, as "Name, Address".
   *
   * Read it. Places matches on business NAME and will cross a continent to do it:
   * measured on this deploy, "Alligator Pools" plus a Karachi address resolved to
   * Miami, Florida - 17 honest probes of the wrong city. Showing the matched listing
   * makes that obvious in the second before a run is paid for.
   */
  centerMatched: string;
  rings: number;
  ringSpacingKm: number;
  /** 1 + 8*rings. What ONE run costs, in paid probes - show it before running. */
  pointCount: number;
  isActive: boolean;
  /** ISO, or "" when this grid has never run. */
  lastRunAt: string;
};

export type GridRun = {
  id: string;
  definitionId: string;
  status: GridRunStatus;
  /** Why a non-completed run ended that way. Always present when it matters. */
  reason: string;
  /** The geometry AS RUN — what was actually probed, not what the grid says today. */
  shape: GridShape;
  gridSize: number;
  rings: number;
  ringSpacingKm: number;
  pointsTotal: number;
  /** ranked + absent. THE DENOMINATOR of every ratio below - never pointsTotal. */
  pointsMeasured: number;
  pointsRanked: number;
  pointsAbsent: number;
  /** Probes the provider never answered. Reported, never folded into a ratio. */
  pointsError: number;
  /** null = nothing ranked. Never 0. */
  avgRank: number | null;
  /** null = nothing measured. Never 0. */
  shareTop3: number | null;
  coverage: GridCoverage;
  provider: string;
  costUsd: number;
  startedAt: string;
  finishedAt: string;
};

export type GridPoint = {
  lat: number;
  lng: number;
  /** 'center' or '<direction>-<ring>', e.g. 'NE-2'. Unique within a run. */
  label: string;
  ring: number;
  status: GridPointStatus;
  /** Present only when status === "ranked". Null for BOTH absent and error. */
  rank: number | null;
  inMapPack: boolean;
  topCompetitors: string[];
  foundUrl: string;
  /** Present only when status === "error". */
  error: string;
};

export type GridRunDetail = {
  run: GridRun;
  points: GridPoint[];
};

/** POST /grid/definitions/{id}/run - an honest hold is not an error. */
export type GridRunQueued = {
  definitionId: string;
  queued: boolean;
  held: boolean;
  reason: string;
  pointCount: number;
};

/** The machine-readable hold reasons, rendered as sentences below. */
export const GRID_HOLD_REASONS: Record<string, string> = {
  grid_paused: "This grid is paused. Resume it to run.",
  no_coordinate_provider:
    "Grid tracking needs a DataForSEO credential — it is the only provider that can " +
    "search from a specific point. Without it a grid would return the same result at " +
    "every point, so it is refused rather than guessed.",
};

export function gridHoldMessage(reason: string): string {
  return GRID_HOLD_REASONS[reason] ?? "This grid could not be queued.";
}

/**
 * The colour a point renders as. Deliberately not a continuous ramp:
 *  - `error` is GREY, never red. Red reads as "ranking badly"; this point was
 *    never measured, and painting it as a bad rank is the fabrication the whole
 *    module refuses.
 *  - `absent` is the worst MEASURED outcome.
 */
export function pointTone(point: GridPoint): "top3" | "top10" | "deep" | "absent" | "unmeasured" {
  if (point.status === "error") return "unmeasured";
  if (point.status === "absent") return "absent";
  const rank = point.rank ?? 0;
  if (rank <= 3) return "top3";
  if (rank <= 10) return "top10";
  return "deep";
}

/** What a point says when you hover it. Never invents a position. */
export function pointLabel(point: GridPoint): string {
  if (point.status === "error") return `${point.label}: not measured — ${point.error}`;
  if (point.status === "absent") return `${point.label}: not in the map pack`;
  return `${point.label}: #${point.rank}`;
}

/**
 * The coverage figure as a sentence, WITH its denominator.
 * A bare "50%" invites reading it as coverage of the whole grid; over a partially
 * measured run it is coverage of what was actually seen, and the difference is the
 * entire point of the three-state contract.
 */
export function coverageSentence(run: GridRun): string {
  // A RUN THAT HAS NOT FINISHED HAS NOT FAILED.
  //
  // `shareTop3` is null whenever nothing has been measured YET, which is true of a
  // queued or running grid as much as of one where every probe errored. Treating the
  // two alike made an in-flight run announce "No point could be measured (25 probes
  // failed)" - reported from production on 2026-09-12, on a grid that was mid-sweep
  // and had failed nothing. That is the module's own defect class turned on itself:
  // claiming a measurement outcome that never happened.
  if (run.status === "queued" || run.status === "running") {
    const done = run.pointsMeasured + run.pointsError;
    return done === 0
      ? `Measuring ${run.pointsTotal} point${run.pointsTotal === 1 ? "" : "s"}...`
      : `Measuring - ${done} of ${run.pointsTotal} probes done.`;
  }
  if (run.shareTop3 === null) {
    // Terminal with nothing measured. WHY matters: a provider that answered nothing
    // and a spend gate that refused before the first probe send an operator to
    // completely different places, and the run records which.
    if (run.pointsError === 0) {
      return run.reason
        ? `Nothing was measured - ${run.reason}`
        : "Nothing was measured on this run.";
    }
    const failed = `${run.pointsError} probe${run.pointsError === 1 ? "" : "s"}`;
    return run.reason
      ? `No point could be measured (${failed} unanswered) - ${run.reason}`
      : `No point could be measured (${failed} failed).`;
  }
  const pct = Math.round(run.shareTop3 * 100);
  const base =
    `In the top 3 at ${pct}% of the ${run.pointsMeasured} point${run.pointsMeasured === 1 ? "" : "s"} measured`;
  return run.pointsError > 0
    ? `${base} — ${run.pointsError} of ${run.pointsTotal} could not be measured.`
    : `${base}.`;
}

/**
 * A client LOCATION a grid can be centred on, from `GET /local-seo/profiles`.
 *
 * The grid module owns no location ledger - `0039_local_seo` does, and this reads it.
 * Forking a second list of client locations is how two surfaces come to disagree about
 * where a business is.
 */
export type GridLocationOption = {
  id: string;
  client: string;
  location: string;
  napName: string;
  napAddress: string;
  placeId: string;
};

/** How a location reads in the picker: "Karachi — Acme Dental". */
export function locationLabel(p: GridLocationOption): string {
  const name = p.napName || p.client;
  return p.location && name ? `${p.location} — ${name}` : p.location || name || p.id;
}

/**
 * Whether this location can have its grid centre resolved automatically.
 *
 * The server resolves a centre from the business's own Google listing, which needs
 * something to search WITH. A profile with neither a name nor an address cannot be
 * resolved, and saying so in the picker is better than letting the operator submit and
 * receive a 422 they then have to interpret.
 */
export function canResolveCentre(p: GridLocationOption): boolean {
  return Boolean((p.napName || p.client).trim() && p.napAddress.trim());
}

/**
 * SoLV — Share of Local Voice: the proportion of MEASURED points where the business
 * sits in the top 3.
 *
 * Reported under this name because that is the name the market uses; relabelling the
 * same arithmetic would make our report incomparable with the one a client already
 * receives from elsewhere. `null` when nothing was measured — which is a different
 * claim from 0%, and must never render as one.
 */
export function solv(run: GridRun): number | null {
  return run.shareTop3;
}

/**
 * ATRP — Average Total Rank Position, over RANKED points only.
 *
 * A point where the business is absent has no position to average. Folding it in as a
 * sentinel (21, or the pack size) would report a number the provider never gave, and
 * would make a business that ranks #1 in a small pocket look worse than one that
 * ranks #15 everywhere.
 */
export function atrp(run: GridRun): number | null {
  return run.avgRank;
}
