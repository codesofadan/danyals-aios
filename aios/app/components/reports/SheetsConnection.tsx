import { sheetsConnection } from "@/lib/reports";

export default function SheetsConnection() {
  const c = sheetsConnection;
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Sheets connection</div>
          <div className="cs">Service account, master workbook &amp; write-buffer</div>
        </div>
        <div className="tools">
          <span className="status-pill ok">Connected</span>
        </div>
      </div>

      {/* service account */}
      <div className="rp-conn">
        <div className="rp-conn-ic ok"><span className="material-symbols-rounded">verified_user</span></div>
        <div className="rp-conn-main">
          <div className="rp-conn-lab">Service account</div>
          <div className="rp-conn-val rp-mono">{c.accountShort}</div>
          <div className="rp-conn-meta">Project <b>{c.project}</b> · scope {c.scope}</div>
        </div>
        <span className="rp-dot ok" title="Authenticated" />
      </div>

      {/* master workbook */}
      <div className="rp-conn">
        <div className="rp-conn-ic"><span className="material-symbols-rounded">tab_group</span></div>
        <div className="rp-conn-main">
          <div className="rp-conn-lab">Master workbook</div>
          <div className="rp-conn-val">{c.master.name}</div>
          <div className="rp-conn-meta rp-mono">{c.master.sheet} · {c.master.tabs} tabs</div>
        </div>
        <a className="rp-sheet-btn" href="#" aria-label="Open master workbook">
          <span className="material-symbols-rounded">open_in_new</span>
        </a>
      </div>

      {/* redis write-buffer */}
      <div className="rp-conn">
        <div className="rp-conn-ic"><span className="material-symbols-rounded">bolt</span></div>
        <div className="rp-conn-main">
          <div className="rp-conn-lab">Write-buffer</div>
          <div className="rp-conn-val">{c.buffer.label}</div>
          <div className="rp-conn-meta">
            <b>{c.buffer.queued}</b> queued · <b>{c.buffer.flushedToday.toLocaleString()}</b> flushed today
          </div>
        </div>
        <span className="status-pill ok">Healthy</span>
      </div>

      <div className="rp-conn-foot">
        <span className="material-symbols-rounded">lock</span>
        Credentials live in the encrypted key vault — never in the client bundle.
      </div>
    </section>
  );
}
