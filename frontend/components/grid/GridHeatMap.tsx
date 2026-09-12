"use client";

// ============================================================
// AIOS · The grid heat map — a REAL map with the probes pinned on it
//
// WHY THIS IS A MAP AND NOT A CHART. The first version plotted the probes as a polar
// rosette in abstract space. It was honest and it was unreadable: every operator
// arrives having used Local Falcon or BrightLocal, where a grid is an N×N block of
// numbered pins laid over the actual streets. Without the map there is nothing to
// anchor "the south-west is weak" to — no neighbourhood, no motorway, no coastline —
// so the picture cannot be acted on or shown to a client.
//
// Tiles are OpenStreetMap raster tiles placed by Web Mercator arithmetic and pins are
// absolutely positioned from their own lat/lng. No mapping library and no API key: the
// projection is fifteen lines, a dependency is a dependency forever, and the tiles are
// the only external request the page makes.
//
// THE ONE RULE THE PALETTE KEEPS. An unmeasured point is GREY and hatched, never red.
// Red reads as "ranking badly"; a point the provider never answered for was not looked
// at, and colouring it as a bad rank is the fabrication the whole module refuses.
// ============================================================

import { useMemo, useState } from "react";
import type { GridPoint, GridRun } from "@/lib/grid";
import { atrp, coverageSentence, pointLabel, pointTone, solv } from "@/lib/grid";

const TILE = 256;

/** Web Mercator world pixel for a coordinate at a zoom level. */
function project(lat: number, lng: number, z: number): { x: number; y: number } {
  const scale = TILE * 2 ** z;
  const sin = Math.sin((lat * Math.PI) / 180);
  return {
    x: ((lng + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale,
  };
}

const TONE_CLASS: Record<ReturnType<typeof pointTone>, string> = {
  top3: "gp-top3",
  top10: "gp-top10",
  deep: "gp-deep",
  absent: "gp-absent",
  unmeasured: "gp-unmeasured",
};

export default function GridHeatMap({
  run,
  points,
}: {
  run: GridRun;
  points: GridPoint[];
}) {
  const [open, setOpen] = useState<GridPoint | null>(null);
  const width = 560;
  const height = 420;

  const view = useMemo(() => {
    if (points.length === 0) return null;
    const lats = points.map((p) => p.lat);
    const lngs = points.map((p) => p.lng);
    const bounds = {
      north: Math.max(...lats), south: Math.min(...lats),
      east: Math.max(...lngs), west: Math.min(...lngs),
    };
    // The largest zoom at which the whole grid still fits, with room for the pins
    // themselves so an edge marker is never half off the map.
    const pad = 56;
    let zoom = 16;
    for (; zoom > 2; zoom -= 1) {
      const nw = project(bounds.north, bounds.west, zoom);
      const se = project(bounds.south, bounds.east, zoom);
      if (se.x - nw.x <= width - pad && se.y - nw.y <= height - pad) break;
    }
    const centreLat = (bounds.north + bounds.south) / 2;
    const centreLng = (bounds.east + bounds.west) / 2;
    const centre = project(centreLat, centreLng, zoom);
    // The world-pixel rect the viewport shows, so a lat/lng becomes a CSS offset.
    const originX = centre.x - width / 2;
    const originY = centre.y - height / 2;
    const tiles: { key: string; src: string; left: number; top: number }[] = [];
    const firstTileX = Math.floor(originX / TILE);
    const firstTileY = Math.floor(originY / TILE);
    const span = 2 ** zoom;
    for (let tx = firstTileX; tx * TILE < originX + width; tx += 1) {
      for (let ty = firstTileY; ty * TILE < originY + height; ty += 1) {
        // Wrap x around the world; clamp y (there is no tile above the pole).
        const wrappedX = ((tx % span) + span) % span;
        if (ty < 0 || ty >= span) continue;
        tiles.push({
          key: `${zoom}/${wrappedX}/${ty}`,
          src: `https://tile.openstreetmap.org/${zoom}/${wrappedX}/${ty}.png`,
          left: tx * TILE - originX,
          top: ty * TILE - originY,
        });
      }
    }
    return { zoom, originX, originY, tiles };
  }, [points, width, height]);

  if (!view) {
    return (
      <div className="gw-empty">
        <div className="gw-empty-t">No probes in this run</div>
      </div>
    );
  }

  const placed = points.map((p) => {
    const world = project(p.lat, p.lng, view.zoom);
    return { point: p, left: world.x - view.originX, top: world.y - view.originY };
  });

  const measuredPct = run.pointsTotal > 0
    ? Math.round((run.pointsMeasured / run.pointsTotal) * 100)
    : 0;
  const solvValue = solv(run);
  const atrpValue = atrp(run);

  return (
    <div className="gm-wrap">
      <div className="gm-map" style={{ width, height }}>
        {/* The map itself. `loading="lazy"` is deliberate: a 7×7 grid can pull two
            dozen tiles and none of them are needed before the card is scrolled to. */}
        {view.tiles.map((t) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={t.key}
            src={t.src}
            alt=""
            width={TILE}
            height={TILE}
            loading="lazy"
            className="gm-tile"
            style={{ left: t.left, top: t.top }}
          />
        ))}

        {placed.map(({ point, left, top }) => (
          <button
            key={point.label}
            type="button"
            className={`gm-pin ${TONE_CLASS[pointTone(point)]}`}
            style={{ left, top }}
            title={pointLabel(point)}
            onClick={() => setOpen(point)}
            aria-label={pointLabel(point)}
          >
            {/* A dash for a measured absence, "?" for a point nobody looked at, and
                NEVER a number for either - any digit here would be invented. */}
            {point.status === "ranked" ? point.rank : point.status === "absent" ? "–" : "?"}
          </button>
        ))}

        <div className="gm-attrib">© OpenStreetMap contributors</div>
      </div>

      <div className="gm-side">
        <div className="gm-headline">{coverageSentence(run)}</div>

        <div className="gm-stats">
          {/* SoLV and ATRP are the two figures this market reports, under those names.
              Inventing our own labels for the same arithmetic would make our report
              incomparable with the one the client already receives. */}
          <div className="gm-stat">
            <span className="gm-stat-n">
              {solvValue === null ? "—" : `${Math.round(solvValue * 100)}%`}
            </span>
            <span className="gm-stat-l">
              SoLV
              <em>share of local voice — points in the top 3</em>
            </span>
          </div>
          <div className="gm-stat">
            <span className="gm-stat-n">{atrpValue === null ? "—" : atrpValue.toFixed(1)}</span>
            <span className="gm-stat-l">
              ATRP
              <em>
                {atrpValue === null
                  ? "nothing ranked"
                  : `average position over ${run.pointsRanked} ranked`}
              </em>
            </span>
          </div>
          <div className="gm-stat">
            <span className="gm-stat-n">
              {run.pointsMeasured}/{run.pointsTotal}
            </span>
            <span className="gm-stat-l">
              Measured
              <em>{measuredPct}% of the grid</em>
            </span>
          </div>
        </div>

        <ul className="gm-legend">
          <li><i className="gp-top3" />1–3</li>
          <li><i className="gp-top10" />4–10</li>
          <li><i className="gp-deep" />11+</li>
          <li><i className="gp-absent" />Not in the pack</li>
          <li><i className="gp-unmeasured" />Not measured</li>
        </ul>

        {open && (
          <div className="gm-detail">
            <div className="gm-detail-h">
              <b>{open.label}</b>
              <button type="button" className="mini-btn" onClick={() => setOpen(null)}>
                Close
              </button>
            </div>
            <div className="gm-detail-s">{pointLabel(open)}</div>
            {open.status === "error" && (
              <div className="gm-detail-s">
                This point was never measured, so it counts toward neither figure above.
              </div>
            )}
            {open.topCompetitors.length > 0 && (
              <>
                <div className="gm-detail-lbl">In the pack here</div>
                <ol className="gm-detail-list">
                  {open.topCompetitors.map((name, i) => (
                    <li key={`${name}-${i}`}>{name}</li>
                  ))}
                </ol>
              </>
            )}
            <div className="gm-detail-s">
              {open.lat.toFixed(5)}, {open.lng.toFixed(5)}
            </div>
          </div>
        )}

        {run.pointsError > 0 && (
          <div className="sec-note gm-caveat">
            <span className="material-symbols-rounded">info</span>
            <span>
              {run.pointsError} of {run.pointsTotal} points could not be measured, so they
              are shown as no-data rather than counted as missing rankings. Both figures
              above are over the {run.pointsMeasured} that were.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
