"use client";

import { useAutoAdvances } from "@/lib/hooks/milestones";

export default function AutoAdvanceFeed() {
  const feedQ = useAutoAdvances();
  const autoAdvances = feedQ.data ?? [];
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Recently auto-advanced</div>
          <div className="cs">Milestones the system moved on its own from job &amp; audit status.</div>
        </div>
        <span className="pill-tag"><span className="material-symbols-rounded">bolt</span>Live</span>
      </div>

      <div className="ms-feed">
        {feedQ.isLoading && <div className="ms-empty">Loading feed…</div>}
        {feedQ.isError && !feedQ.isLoading && (
          <div className="ms-empty">Couldn&apos;t load the feed — {(feedQ.error as Error)?.message ?? "try again"}.</div>
        )}
        {!feedQ.isLoading && !feedQ.isError && autoAdvances.map((a) => (
          <div className="ms-act" key={a.id}>
            <span className={a.flag ? "ms-act-ic flag" : "ms-act-ic"} style={a.flag ? undefined : { color: a.c, background: `${a.c}22` }}>
              <span className="material-symbols-rounded">{a.icon}</span>
            </span>
            <div className="ms-act-main">
              <div className="ms-act-line">
                <span className="ms-act-cl">{a.client}</span>{" "}
                <span className="ms-act-verb">{a.flag ? "flagged at" : "advanced to"}</span>{" "}
                <span className="ms-act-ms">{a.milestone}</span>
              </div>
              <div className="ms-act-trig">
                <span className="material-symbols-rounded">{a.flag ? "flag" : "arrow_outward"}</span>
                {a.trigger}
              </div>
            </div>
            <span className="ms-act-ago">{a.ago}</span>
          </div>
        ))}
        {!feedQ.isLoading && !feedQ.isError && autoAdvances.length === 0 && (
          <div className="ms-empty">No recent auto-advances.</div>
        )}
      </div>
    </section>
  );
}
