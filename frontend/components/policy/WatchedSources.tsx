"use client";

import { useState } from "react";

import { useSpendHalted } from "@/lib/hooks/cost";
import { useGeneratePolicyBrief, useSources } from "@/lib/hooks/policy";
import ConfirmDialog from "@/components/ui/ConfirmDialog";

// What Policy Radar watches, and the control that refreshes the day's brief.
//
// Both endpoints existed with no caller. `GET /policy/sources` meant an operator could
// read the radar's OUTPUT with no way to see what it was actually watching — so a
// missing source looked identical to a quiet week. `POST /policy/generate` meant the
// brief could only ever arrive on the daily beat, which is currently `{}`: nothing was
// scheduled, so in practice it never arrived at all.
//
// Refreshing SPENDS. It enqueues the same Anthropic generator the beat runs, forcing
// past the once-per-day guard, so it is lead-only server-side, confirms first, and is
// disabled while the global spend halt is engaged — the same treatment AskBox gives a
// metered lookup.
export default function WatchedSources() {
  const sourcesQ = useSources();
  const generate = useGeneratePolicyBrief();
  const [confirmRefresh, setConfirmRefresh] = useState(false);
  const { halted } = useSpendHalted();

  const sources = sourcesQ.data ?? [];

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Watched sources</div>
          <div className="cs">What the radar reads, and when the brief last ran</div>
        </div>
        <div className="tools">
          <button
            type="button"
            className="ghostbtn"
            disabled={generate.isPending || halted}
            title={halted ? "API spend is halted" : "Runs the brief generator now (spends)"}
            onClick={() => setConfirmRefresh(true)}
          >
            <span className="material-symbols-rounded">refresh</span>
            {generate.isPending ? "Queued…" : "Refresh brief"}
          </button>
        </div>
      </div>

      {halted && (
        <div className="pr-note">
          <span className="material-symbols-rounded">pause_circle</span>
          API spend is halted, so the brief cannot be refreshed. Resume spend in Cost Controls.
        </div>
      )}
      {generate.isSuccess && !generate.isPending && (
        <div className="pr-note ok">
          <span className="material-symbols-rounded">check_circle</span>
          Queued. New items appear in the feed and the recommendation queue as they land.
        </div>
      )}
      {generate.error instanceof Error && (
        <div className="pr-note err" role="alert">
          <span className="material-symbols-rounded">error</span>
          Couldn&apos;t queue the brief — {generate.error.message}
        </div>
      )}

      {sourcesQ.isLoading ? (
        <div className="pr-note">Loading sources…</div>
      ) : sourcesQ.isError ? (
        <div className="pr-note err" role="alert">Couldn&apos;t load the watched sources.</div>
      ) : sources.length === 0 ? (
        <div className="pr-note">
          <span className="material-symbols-rounded">radar</span>
          No sources are configured — the radar has nothing to read.
        </div>
      ) : (
        <ul className="pr-src-list">
          {sources.map((s) => (
            <li className="pr-src" key={s.id}>
              <span className="material-symbols-rounded">{s.icon || "sensors"}</span>
              <span className="pr-src-main">
                {s.url ? (
                  <a className="pr-src-name" href={s.url} target="_blank" rel="noopener noreferrer">{s.name}</a>
                ) : (
                  <span className="pr-src-name">{s.name}</span>
                )}
                <span className="pr-src-meta">
                  {s.kind}
                  {s.lastChecked ? ` · checked ${s.lastChecked}` : ""}
                  {s.note ? ` · ${s.note}` : ""}
                </span>
              </span>
              {/* `change` means the source moved since the last read — the thing an
                  operator is actually scanning this list for. */}
              <span className={`status-pill ${s.status === "change" ? "warn" : "ok"}`}>
                {s.status === "change" ? "Changed" : "Steady"}
              </span>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={confirmRefresh}
        title="Refresh the daily brief now?"
        body="The brief generator runs immediately and its provider calls spend against the policy budget."
        reassurance="The scheduled run still happens on its own cadence; this is an extra run, not a reschedule."
        confirmLabel="Run and spend"
        tone="caution"
        pending={generate.isPending}
        onCancel={() => setConfirmRefresh(false)}
        onConfirm={() => { setConfirmRefresh(false); generate.mutate(); }}
      />
    </section>
  );
}
