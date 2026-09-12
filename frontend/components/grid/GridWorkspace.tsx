"use client";

// ============================================================
// AIOS · Grid tracking workspace (migration 0138)
//
// Two honesty rules drive this layout:
//
// 1. THE PRICE IS SHOWN BEFORE THE BUTTON. One run is `1 + 8*rings` PAID map-pack
//    probes, so every Run control states its probe count, and the create form
//    restates it as the geometry changes. A spend door that does not say what it
//    costs is how a 41-probe run gets clicked casually.
//
// 2. A REFUSAL IS A SENTENCE, NOT A SPINNER. POST .../run answers 202 with
//    `queued:false, held:true` when there is no coordinate-capable provider or the
//    grid is paused. Those are real states with real explanations, so they render as
//    text the operator can act on.
// ============================================================

import { useState } from "react";
import {
  useCreateGrid,
  useGridClients,
  useGridDefinitions,
  useGridLatest,
  useGridRuns,
  useRunGrid,
  useSetGridActive,
} from "@/lib/hooks/grid";
import {
  gridHoldMessage,
  type GridDefinition,
  type GridRunStatus,
} from "@/lib/grid";
import GridHeatMap from "@/components/grid/GridHeatMap";

const RUN_TONE: Record<GridRunStatus, string> = {
  queued: "gs-wait",
  running: "gs-wait",
  completed: "gs-ok",
  degraded: "gs-warn",
  blocked: "gs-warn",
  failed: "gs-bad",
  cancelled: "gs-mute",
};

/** An N×N grid is N² probes - the same formula 0143's generated column uses. */
function pointsFor(size: number): number {
  return size * size;
}

/** The sizes the market offers, with what each costs per run. */
const GRID_SIZES = [3, 5, 7, 9, 11];

export default function GridWorkspace() {
  const [selected, setSelected] = useState<string>("");
  const [notice, setNotice] = useState<string>("");

  const definitionsQ = useGridDefinitions();
  const definitions = definitionsQ.data ?? [];
  const active = definitions.find((d) => d.id === selected) ?? definitions[0];
  const activeId = active?.id ?? "";

  const latestQ = useGridLatest(activeId, Boolean(activeId));
  const runsQ = useGridRuns(activeId, Boolean(activeId));
  const runGrid = useRunGrid();
  const setActive = useSetGridActive();

  async function onRun(definition: GridDefinition) {
    setNotice("");
    try {
      const result = await runGrid.mutateAsync(definition.id);
      setNotice(
        result.queued
          ? `Queued — ${result.pointCount} probes. The heat map updates when the run finishes.`
          : gridHoldMessage(result.reason),
      );
    } catch (err) {
      // A 409 is the double-click guard, not a failure to report vaguely.
      const message = err instanceof Error ? err.message : "";
      setNotice(
        message.includes("409") || message.toLowerCase().includes("already")
          ? "A run for this grid is already in progress."
          : "That run could not be queued. Nothing was charged.",
      );
    }
  }

  return (
    <>
      <section className="card" style={{ marginBottom: 16 }}>
        <div className="card-h">
          <div>
            <div className="ct">Local search grids</div>
            <div className="cs">
              Where a business ranks in the map pack across its service area — measured
              at each point, never interpolated between them.
            </div>
          </div>
        </div>

        {definitionsQ.isLoading && <div className="gw-empty">Loading grids…</div>}

        {definitionsQ.isError && (
          <div className="sec-note">
            <span className="material-symbols-rounded">error</span>
            <span>Grids could not be loaded.</span>
          </div>
        )}

        {!definitionsQ.isLoading && !definitionsQ.isError && definitions.length === 0 && (
          <div className="gw-empty">
            <div className="gw-empty-t">No grids yet</div>
            <div className="gw-empty-s">
              A grid tracks one keyword at one client location. Create one below — it is
              centred on that location&apos;s own Google listing.
            </div>
          </div>
        )}

        {definitions.length > 0 && (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Location</th>
                  <th>Keyword</th>
                  <th>Client</th>
                  <th className="num">Probes / run</th>
                  <th>Last run</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {definitions.map((d) => (
                  <tr
                    key={d.id}
                    className={d.id === activeId ? "gw-row-on" : undefined}
                    onClick={() => setSelected(d.id)}
                  >
                    <td>
                      <div className="gw-loc">{d.location}</div>
                      <div className="gw-geo">
                        {d.shape === "square"
                          ? `${d.gridSize} × ${d.gridSize} · ${d.ringSpacingKm} km apart`
                          : `${d.rings} ring${d.rings === 1 ? "" : "s"} · ${d.ringSpacingKm} km apart`}
                        {d.centerSource === "operator" && " · centre set by hand"}
                      </div>
                      {/* THE CENTRE, VISIBLE. Places matches on business name and will
                          resolve to a same-named business on another continent - so the
                          matched listing and the coordinates are both shown, and a grid
                          pointed at the wrong city is obvious before it is paid for. */}
                      {d.centerMatched && (
                        <div className="gw-centre" title="The Google listing this grid was centred on">
                          centred on {d.centerMatched}
                        </div>
                      )}
                      <div className="gw-centre">
                        {d.centerLat.toFixed(4)}, {d.centerLng.toFixed(4)}
                      </div>
                    </td>
                    <td>{d.keyword}</td>
                    <td>{d.client}</td>
                    <td className="num">{d.pointCount}</td>
                    <td>
                      {d.lastRunAt ? new Date(d.lastRunAt).toLocaleDateString() : "never"}
                    </td>
                    <td>
                      <div className="gw-actions">
                        <button
                          type="button"
                          className="primary-btn"
                          disabled={runGrid.isPending || !d.isActive}
                          onClick={(e) => {
                            e.stopPropagation();
                            void onRun(d);
                          }}
                          title={
                            d.isActive
                              ? `Run ${d.pointCount} paid probes now`
                              : "This grid is paused"
                          }
                        >
                          {runGrid.isPending ? "Queueing…" : `Run · ${d.pointCount} probes`}
                        </button>
                        <button
                          type="button"
                          className="mini-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            setActive.mutate({ id: d.id, isActive: !d.isActive });
                          }}
                        >
                          {d.isActive ? "Pause" : "Resume"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {notice && (
          <div className="sec-note" style={{ marginTop: 12 }}>
            <span className="material-symbols-rounded">info</span>
            <span>{notice}</span>
          </div>
        )}
      </section>

      {active && (
        <section className="card" style={{ marginBottom: 16 }}>
          <div className="card-h">
            <div>
              <div className="ct">
                {active.keyword} · {active.location}
              </div>
              <div className="cs">
                {latestQ.data
                  ? `Measured ${new Date(latestQ.data.run.finishedAt || latestQ.data.run.startedAt).toLocaleString()} · ${latestQ.data.run.provider}`
                  : "The most recent run of this grid"}
              </div>
            </div>
            {latestQ.data && (
              <div className="tools">
                <span className={`status-pill ${RUN_TONE[latestQ.data.run.status]}`}>
                  {latestQ.data.run.status}
                </span>
              </div>
            )}
          </div>

          {latestQ.isLoading && <div className="gw-empty">Loading the heat map…</div>}

          {/* A grid that has never run has NO heat map. Rendering an empty one would
              read as a business that ranks nowhere. */}
          {latestQ.isError && (
            <div className="gw-empty">
              <div className="gw-empty-t">No heat map yet</div>
              <div className="gw-empty-s">
                This grid has not run. Press Run to measure its {active.pointCount} points.
              </div>
            </div>
          )}

          {latestQ.data && (
            <>
              {latestQ.data.run.reason && (
                <div className="sec-note" style={{ marginBottom: 12 }}>
                  <span className="material-symbols-rounded">warning</span>
                  <span>{latestQ.data.run.reason}</span>
                </div>
              )}
              <GridHeatMap run={latestQ.data.run} points={latestQ.data.points} />
            </>
          )}
        </section>
      )}

      {active && runsQ.data && runsQ.data.length > 1 && (
        <section className="card" style={{ marginBottom: 16 }}>
          <div className="card-h">
            <div>
              <div className="ct">Run history</div>
              <div className="cs">
                Every run of this grid. Coverage is always over the points measured in
                that run, so two rows are comparable only alongside their own denominators.
              </div>
            </div>
          </div>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Status</th>
                  <th className="num">Top-3 coverage</th>
                  <th className="num">Avg position</th>
                  <th className="num">Measured</th>
                  <th className="num">Cost</th>
                </tr>
              </thead>
              <tbody>
                {runsQ.data.map((r) => (
                  <tr key={r.id}>
                    <td>
                      {r.finishedAt || r.startedAt
                        ? new Date(r.finishedAt || r.startedAt).toLocaleString()
                        : "—"}
                    </td>
                    <td>
                      <span className={`status-pill ${RUN_TONE[r.status]}`}>{r.status}</span>
                    </td>
                    <td className="num">
                      {r.shareTop3 === null ? "—" : `${Math.round(r.shareTop3 * 100)}%`}
                    </td>
                    <td className="num">{r.avgRank === null ? "—" : r.avgRank.toFixed(1)}</td>
                    <td className="num">
                      {r.pointsMeasured}/{r.pointsTotal}
                    </td>
                    <td className="num">${r.costUsd.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <CreateGridCard />
    </>
  );
}

function CreateGridCard() {
  const create = useCreateGrid();
  const clientsQ = useGridClients();
  const clients = clientsQ.data ?? [];
  const [clientId, setClientId] = useState("");
  const [keyword, setKeyword] = useState("");
  const [gridSize, setGridSize] = useState(5);
  const [spacing, setSpacing] = useState(1.5);
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [error, setError] = useState("");

  const manualCentre = lat.trim() !== "" || lng.trim() !== "";
  const selected = clients.find((c) => c.id === clientId);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await create.mutateAsync({
        clientId,
        keyword: keyword.trim(),
        shape: "square",
        gridSize,
        ringSpacingKm: spacing,
        ...(manualCentre ? { centerLat: Number(lat), centerLng: Number(lng) } : {}),
      });
      setKeyword("");
      setLat("");
      setLng("");
    } catch (err) {
      const message = err instanceof Error ? err.message : "";
      setError(
        message.includes("422")
          ? "This client has no business profile yet, so its location could not be worked out. Add one in Client Setup — or enter the coordinates below."
          : message.includes("409")
            ? "This client's location already tracks that keyword."
            : "The grid could not be created.",
      );
    }
  }

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Track a new grid</div>
          <div className="cs">
            Pick the client and the keyword. The location, business name, address and
            map centre are taken from the client&apos;s own business profile — the same
            NAP the citation module submits, so the two can never disagree.
          </div>
        </div>
      </div>

      <form className="gw-form" onSubmit={submit}>
        <label className="gw-field">
          <span>Client</span>
          <select
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            required
            disabled={clientsQ.isLoading}
          >
            <option value="">
              {clientsQ.isLoading ? "Loading clients…" : "Choose a client…"}
            </option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.cn}</option>
            ))}
          </select>
        </label>
        <label className="gw-field">
          <span>Keyword</span>
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="emergency dentist"
            required
          />
        </label>
        <label className="gw-field">
          <span>Grid size</span>
          <select value={gridSize} onChange={(e) => setGridSize(Number(e.target.value))}>
            {GRID_SIZES.map((n) => (
              <option key={n} value={n}>
                {n} × {n} ({pointsFor(n)} probes)
              </option>
            ))}
          </select>
        </label>
        <label className="gw-field">
          <span>Point spacing (km)</span>
          <input
            type="number"
            min={0.1}
            max={50}
            step={0.1}
            value={spacing}
            onChange={(e) => setSpacing(Number(e.target.value))}
          />
        </label>

        {/* The override, not the default. Present because a client with no business
            profile - or one whose listing resolves to the wrong city - still needs a
            way through, and an honest escape hatch beats a blocked form. */}
        <label className="gw-field">
          <span>Centre latitude (optional)</span>
          <input value={lat} onChange={(e) => setLat(e.target.value)}
                 placeholder="resolved from the client" />
        </label>
        <label className="gw-field">
          <span>Centre longitude (optional)</span>
          <input value={lng} onChange={(e) => setLng(e.target.value)}
                 placeholder="resolved from the client" />
        </label>

        {selected && (
          <div className="gw-picked">
            <div className="gw-picked-t">{selected.cn}</div>
            <div className="gw-picked-s">
              The location and map centre will be resolved from this client&apos;s
              business profile when you create the grid — check the centre on the board
              afterwards, because a listing search can match a same-named business
              elsewhere.
            </div>
          </div>
        )}

        <div className="gw-form-foot">
          {/* The price, restated as the geometry changes. */}
          <div className="gw-price">
            Each run of this grid is <strong>{pointsFor(gridSize)} paid probes</strong> —
            a {gridSize} × {gridSize} grid spanning{" "}
            {((gridSize - 1) * spacing).toFixed(1).replace(/\.0$/, "")} km edge to edge.
          </div>
          <button type="submit" className="primary-btn" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create grid"}
          </button>
        </div>

        {error && (
          <div className="sec-note">
            <span className="material-symbols-rounded">error</span>
            <span>{error}</span>
          </div>
        )}
      </form>
    </section>
  );
}


