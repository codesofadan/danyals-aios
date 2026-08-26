import DataTable from "@/components/ui/DataTable";
import { DATASET_META, STATUS_META, type Workbook, sheetUrl } from "@/lib/reports";

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

      {/* On components/ui/DataTable: the three-branch body, the derived colSpan
          (hand-written here as 7, one column-add away from being wrong) and the
          scroll wrapper all come from the primitive now. */}
      <DataTable
        rows={workbooks}
        rowKey={(w) => w.id}
        query={{ isLoading: loading, isError: Boolean(error) }}
        label="workbooks"
        empty="No client workbooks yet."
        tableClassName="rp-tbl"
        caption="Per-client Google Sheets workbooks"
        columns={[
          { key: "client", header: "Client", className: "rp-client", cell: (w) => w.client },
          {
            key: "sheet",
            header: "Workbook",
            cell: (w) => (
              <a
                className={`rp-sheet-link${sheetUrl(w.sheet) ? "" : " off"}`}
                href={sheetUrl(w.sheet) ?? undefined}
                target={sheetUrl(w.sheet) ? "_blank" : undefined}
                rel={sheetUrl(w.sheet) ? "noopener noreferrer" : undefined}
                aria-label={sheetUrl(w.sheet) ? `Open ${w.client} workbook in Google Sheets` : `${w.client} has no workbook yet`}
              >
                <span className="material-symbols-rounded">table_view</span>
                <span className="rp-mono rp-sheet-id">{w.sheet || "\u2014"}</span>
                <span className="material-symbols-rounded rp-ext">open_in_new</span>
              </a>
            ),
          },
          {
            key: "tabs",
            header: "Tabs synced",
            cell: (w) => (
              <div className="rp-chips">
                {w.tabs.map((d) => (
                  <span key={d} className="rp-chip" style={{ color: DATASET_META[d].c }}>
                    <span className="material-symbols-rounded">{DATASET_META[d].icon}</span>
                    {DATASET_META[d].label}
                  </span>
                ))}
              </div>
            ),
          },
          { key: "rows", header: "Rows", numeric: true, className: "rp-rows", cell: (w) => w.rows.toLocaleString() },
          {
            key: "last",
            header: "Last sync",
            className: "rp-last",
            cell: (w) => (syncing.has(w.id) || w.status === "syncing" ? "syncing\u2026" : w.lastSync),
          },
          {
            key: "status",
            header: "Status",
            cell: (w) => {
              const isSyncing = syncing.has(w.id) || w.status === "syncing";
              const st = STATUS_META[isSyncing ? "syncing" : w.status];
              return (
                <span className={`status-pill ${st.cls}`}>
                  {isSyncing && <span className="material-symbols-rounded rp-spin">progress_activity</span>}
                  {st.label}
                </span>
              );
            },
          },
          {
            key: "act",
            header: "",
            className: "rp-act-col",
            cell: (w) => {
              const isSyncing = syncing.has(w.id) || w.status === "syncing";
              return (
                <button className="ghostbtn rp-syncbtn" onClick={() => onSync(w.id)} disabled={isSyncing}>
                  <span className="material-symbols-rounded">refresh</span>
                  Sync now
                </button>
              );
            },
          },
        ]}
      />
    </section>
  );
}
