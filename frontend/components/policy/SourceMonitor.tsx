"use client";

import { useSources } from "@/lib/hooks/policy";

export default function SourceMonitor() {
  const sourcesQ = useSources();
  const sources = sourcesQ.data ?? [];
  return (
    <section className="card pr-mon">
      <div className="card-h">
        <div>
          <div className="ct">Source Monitor</div>
          <div className="cs">Official Google surfaces watched on a continuous crawl loop.</div>
        </div>
        <div className="tools">
          <span className="pr-watch">
            <span className="pr-pulse" />
            Watching
          </span>
        </div>
      </div>

      <div className="pr-sources">
        {sourcesQ.isLoading && <div className="pr-empty">Loading sources…</div>}
        {sourcesQ.isError && !sourcesQ.isLoading && (
          <div className="pr-empty">Couldn&apos;t load sources — {(sourcesQ.error as Error)?.message ?? "try again"}.</div>
        )}
        {!sourcesQ.isLoading && !sourcesQ.isError && sources.length === 0 && (
          <div className="pr-empty">No sources are being watched yet.</div>
        )}
        {!sourcesQ.isLoading && !sourcesQ.isError && sources.map((s) => (
          <div className="pr-src" key={s.id}>
            <span className="pr-src-ic">
              <span className="material-symbols-rounded">{s.icon}</span>
            </span>
            <div className="pr-src-main">
              <div className="pr-src-top">
                <span className="pr-src-name">{s.name}</span>
                <span className={`status-pill ${s.status === "ok" ? "ok" : "warn"}`}>
                  {s.status === "ok" ? "OK" : "Change detected"}
                </span>
              </div>
              <div className="pr-src-kind">{s.kind}</div>
              <div className="pr-src-note">{s.note}</div>
              <div className="pr-src-meta">
                <span><span className="material-symbols-rounded">schedule</span>Checked {s.lastChecked}</span>
                <span className="pr-hash"><span className="material-symbols-rounded">tag</span>{s.lastHash}</span>
                <a className="pr-src-link" href={s.url} target="_blank" rel="noreferrer">
                  source<span className="material-symbols-rounded">open_in_new</span>
                </a>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
