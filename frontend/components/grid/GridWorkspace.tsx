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
  usePreviewMapsUrl,
  type MapsUrlPreview,
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
  const preview = usePreviewMapsUrl();
  const clientsQ = useGridClients();
  const clients = clientsQ.data ?? [];
  const [clientId, setClientId] = useState("");
  const [keyword, setKeyword] = useState("");
  const [gridSize, setGridSize] = useState(5);
  const [spacing, setSpacing] = useState(1.5);
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [mapsUrl, setMapsUrl] = useState("");
  const [resolved, setResolved] = useState<MapsUrlPreview | null>(null);
  const [mapsError, setMapsError] = useState("");
  const [syncNap, setSyncNap] = useState(false);
  const [error, setError] = useState("");

  const manualCentre = lat.trim() !== "" || lng.trim() !== "";
  const selected = clients.find((c) => c.id === clientId);

  /** Resolve the pasted link and SHOW it. Nothing is created by this. */
  async function checkMapsUrl() {
    setMapsError("");
    setResolved(null);
    setSyncNap(false);
    const value = mapsUrl.trim();
    if (!value) return;
    try {
      setResolved(await preview.mutateAsync(value));
    } catch (err) {
      // The server's 422 detail is written for the operator — it names what to paste
      // instead — so it is shown verbatim rather than replaced with a generic line.
      const message = err instanceof Error ? err.message : "";
      setMapsError(
        message.replace(/^\d+\s*:?\s*/, "") ||
          "That link could not be read. Open the business on Google Maps, press Share, and paste the link it gives you.",
      );
    }
  }

  function clearMapsUrl() {
    setMapsUrl("");
    setResolved(null);
    setMapsError("");
    setSyncNap(false);
  }

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
        // A confirmed link wins over typed coordinates; the server enforces the same
        // precedence, so the two cannot disagree about which centre was used.
        ...(resolved
          ? { mapsUrl: mapsUrl.trim(), syncNap }
          : manualCentre
            ? { centerLat: Number(lat), centerLng: Number(lng) }
            : {}),
      });
      setKeyword("");
      setLat("");
      setLng("");
      clearMapsUrl();
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

        {/* THE ACCURATE PATH. Searching for a business by name is what centres a grid
            on a same-named shop in another country; a pasted link names the listing the
            operator already found with their own eyes, so there is nothing to guess. */}
        <label className="gw-field gw-field-wide">
          <span>Google Maps link (most accurate)</span>
          <div className="gw-paste">
            <input
              value={mapsUrl}
              onChange={(e) => { setMapsUrl(e.target.value); setResolved(null); setMapsError(""); }}
              placeholder="Paste the Share link from the business on Google Maps"
              inputMode="url"
            />
            <button
              type="button"
              className="ghostbtn"
              onClick={checkMapsUrl}
              disabled={preview.isPending || mapsUrl.trim() === ""}
            >
              {preview.isPending ? "Checking…" : "Check"}
            </button>
            {(resolved || mapsError) && (
              <button type="button" className="ghostbtn" onClick={clearMapsUrl}>
                Clear
              </button>
            )}
          </div>
        </label>

        {mapsError && (
          <div className="sec-note gw-field-wide">
            <span className="material-symbols-rounded">error</span>
            <span>{mapsError}</span>
          </div>
        )}

        {resolved && (
          <div className="gw-picked gw-field-wide">
            <div className="gw-picked-t">
              {resolved.identityVerified ? resolved.name : "Location found — business not identified"}
            </div>
            <div className="gw-picked-s">
              {resolved.identityVerified ? (
                <>
                  {resolved.address}
                  {resolved.phone ? ` · ${resolved.phone}` : ""}
                  <br />
                  Centre {resolved.lat.toFixed(6)}, {resolved.lng.toFixed(6)} — taken from
                  this listing&apos;s own pin. Check it is the right business before creating
                  the grid.
                </>
              ) : (
                <>
                  Centre {resolved.lat.toFixed(6)}, {resolved.lng.toFixed(6)}
                  {resolved.precise
                    ? " — the pin from the link."
                    : " — the map view in the link, not a business pin, so it may be off by a street."}
                  <br />
                  {resolved.reason === "no_places_key"
                    ? "The business details could not be looked up (no Places key configured), so only the coordinates are being used."
                    : resolved.reason === "match_too_far"
                      ? "Google returned a business too far from this pin to be the same place, so it was rejected rather than guessed at. The pin itself is still used as the centre."
                      : "The business behind this link could not be looked up, so only the coordinates are being used."}
                </>
              )}
            </div>

            {/* Offered ONLY on a verified identity: writing unknown details to the
                record the citation module submits from would be the worst possible
                reading of a convenience. */}
            {resolved.identityVerified && (
              <label className="gw-check">
                <input
                  type="checkbox"
                  checked={syncNap}
                  onChange={(e) => setSyncNap(e.target.checked)}
                />
                <span>
                  Also update this client&apos;s saved business details from this listing.
                  This is the NAP submitted to directories — only the fields Google
                  returned are written, and nothing is blanked out.
                </span>
              </label>
            )}
          </div>
        )}

        {/* The override, not the default. Present because a client with no business
            profile - or one whose listing resolves to the wrong city - still needs a
            way through, and an honest escape hatch beats a blocked form. */}
        <label className="gw-field">
          <span>Centre latitude (optional)</span>
          <input value={lat} onChange={(e) => setLat(e.target.value)}
                 placeholder={resolved ? "using the Maps link" : "resolved from the client"}
                 disabled={Boolean(resolved)} />
        </label>
        <label className="gw-field">
          <span>Centre longitude (optional)</span>
          <input value={lng} onChange={(e) => setLng(e.target.value)}
                 placeholder={resolved ? "using the Maps link" : "resolved from the client"}
                 disabled={Boolean(resolved)} />
        </label>

        {selected && !resolved && (
          <div className="gw-picked">
            <div className="gw-picked-t">{selected.cn}</div>
            <div className="gw-picked-s">
              The location and map centre will be resolved from this client&apos;s
              business profile when you create the grid — check the centre on the board
              afterwards, because a listing search can match a same-named business
              elsewhere. Pasting the Maps link above skips that search entirely.
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


