import type { CSSProperties } from "react";
import { DATASET_META, type SyncEvent } from "@/lib/reports";

const RP_EMPTY: CSSProperties = { padding: "20px", textAlign: "center", color: "var(--muted)" };

type Props = { log: SyncEvent[]; loading?: boolean; error?: string | null };

export default function SyncActivity({ log, loading, error }: Props) {
  const total = log.reduce((s, e) => s + e.rows, 0);
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Sync activity</div>
          <div className="cs">Recent pushes to Google Sheets</div>
        </div>
        <div className="tools">
          <span className="pill-tag ok"><span className="material-symbols-rounded">cloud_done</span>{total.toLocaleString()} rows</span>
        </div>
      </div>

      <div className="rp-log">
        {loading && <div style={RP_EMPTY}>Loading sync activity…</div>}
        {error && !loading && <div style={RP_EMPTY}>Couldn&apos;t load activity — {error}</div>}
        {!loading && !error && log.length === 0 && <div style={RP_EMPTY}>No sync activity yet.</div>}
        {!loading && !error && log.map((e) => {
          const m = DATASET_META[e.dataset];
          return (
            <div className="rp-log-row" key={e.id}>
              <div className="rp-log-ic" style={{ color: m.c, background: `${m.c}1f` }}>
                <span className="material-symbols-rounded">{m.icon}</span>
              </div>
              <div className="rp-log-main">
                <div className="rp-log-line">
                  <b>{e.client}</b>
                  <span className="rp-log-sep">·</span>
                  <span className="rp-log-ds" style={{ color: m.c }}>{m.label}</span>
                </div>
                <div className="rp-log-meta">Pushed {e.rows.toLocaleString()} rows to the workbook</div>
              </div>
              <div className="rp-log-ago">{e.ago}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
