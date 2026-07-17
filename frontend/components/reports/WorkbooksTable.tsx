import type { CSSProperties } from "react";
import { DATASET_META, STATUS_META, type Workbook } from "@/lib/reports";

const RP_EMPTY: CSSProperties = { padding: "20px", textAlign: "center", color: "var(--muted)" };

type Props = {
  workbooks: Workbook[];
  syncing: Set<string>;
  onSync: (id: string) => void;
  onSyncAll: () => void;
  loading?: boolean;
  error?: string | null;
};

export default function WorkbooksTable({ workbooks, syncing, onSync, onSyncAll, loading, error }: Props) {
  const anySyncing = syncing.size > 0;
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Per-client workbooks</div>
          <div className="cs">One Google Sheets workbook per client — audit, content &amp; milestone tabs</div>
        </div>
        <div className="tools">
          <button className="ghostbtn" onClick={onSyncAll} disabled={anySyncing || loading || workbooks.length === 0}>
            <span className="material-symbols-rounded">sync</span>
            {anySyncing ? "Syncing…" : "Sync all"}
          </button>
        </div>
      </div>

      <div className="tbl-wrap rp-tbl-wrap">
        <table className="tbl rp-tbl">
          <thead>
            <tr>
              <th>Client</th>
              <th>Workbook</th>
              <th>Tabs synced</th>
              <th className="num">Rows</th>
              <th>Last sync</th>
              <th>Status</th>
              <th className="rp-act-col"></th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={7} style={RP_EMPTY}>Loading workbooks…</td></tr>
            )}
            {error && !loading && (
              <tr><td colSpan={7} style={RP_EMPTY}>Couldn&apos;t load workbooks — {error}</td></tr>
            )}
            {!loading && !error && workbooks.length === 0 && (
              <tr><td colSpan={7} style={RP_EMPTY}>No client workbooks yet.</td></tr>
            )}
            {!loading && !error && workbooks.map((w) => {
              const isSyncing = syncing.has(w.id) || w.status === "syncing";
              const st = STATUS_META[isSyncing ? "syncing" : w.status];
              return (
                <tr key={w.id}>
                  <td className="rp-client">{w.client}</td>
                  <td>
                    <a className="rp-sheet-link" href="#" aria-label={`Open ${w.client} workbook`}>
                      <span className="material-symbols-rounded">table_view</span>
                      <span className="rp-mono rp-sheet-id">{w.sheet}</span>
                      <span className="material-symbols-rounded rp-ext">open_in_new</span>
                    </a>
                  </td>
                  <td>
                    <div className="rp-chips">
                      {w.tabs.map((d) => (
                        <span key={d} className="rp-chip" style={{ color: DATASET_META[d].c }}>
                          <span className="material-symbols-rounded">{DATASET_META[d].icon}</span>
                          {DATASET_META[d].label}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="num rp-rows">{w.rows.toLocaleString()}</td>
                  <td className="rp-last">{isSyncing ? "syncing…" : w.lastSync}</td>
                  <td>
                    <span className={`status-pill ${st.cls}`}>
                      {isSyncing && <span className="material-symbols-rounded rp-spin">progress_activity</span>}
                      {st.label}
                    </span>
                  </td>
                  <td className="rp-act-col">
                    <button className="ghostbtn rp-syncbtn" onClick={() => onSync(w.id)} disabled={isSyncing}>
                      <span className="material-symbols-rounded">refresh</span>
                      Sync now
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
