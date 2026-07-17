"use client";

import { SEV_META } from "@/lib/policy";
import { useChanges } from "@/lib/hooks/policy";

export default function ChangeFeed() {
  const changesQ = useChanges();
  const changeEvents = changesQ.data ?? [];
  return (
    <section className="card pr-feed">
      <div className="card-h">
        <div>
          <div className="ct">Change Events</div>
          <div className="cs">Diffs the watcher flagged, newest first.</div>
        </div>
        <div className="tools">
          <span className="panel-hint"><span className="material-symbols-rounded">bolt</span>{changeEvents.length} · 7d</span>
        </div>
      </div>

      <div className="pr-events">
        {changesQ.isLoading && <div className="pr-empty">Loading change events…</div>}
        {changesQ.isError && !changesQ.isLoading && (
          <div className="pr-empty">Couldn&apos;t load change events — {(changesQ.error as Error)?.message ?? "try again"}.</div>
        )}
        {!changesQ.isLoading && !changesQ.isError && changeEvents.length === 0 && (
          <div className="pr-empty">No changes detected yet.</div>
        )}
        {!changesQ.isLoading && !changesQ.isError && changeEvents.map((e) => {
          const sev = SEV_META[e.severity];
          return (
            <div className="pr-event" key={e.id}>
              <span className={`pr-dot pr-sev-${sev.cls}`} title={sev.label} />
              <div className="pr-event-body">
                <div className="pr-event-top">
                  <span className="pr-event-src">{e.sourceName}</span>
                  <span className={`pr-sev pr-sev-${sev.cls}`}>{sev.label}</span>
                </div>
                <div className="pr-event-sum">{e.summary}</div>
                <div className="pr-event-ago">
                  <span className="material-symbols-rounded">schedule</span>Detected {e.detected}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
