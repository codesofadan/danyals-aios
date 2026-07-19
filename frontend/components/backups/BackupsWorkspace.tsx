"use client";

import { useEffect, useRef, useState } from "react";
import anime from "animejs";
import {
  protectedStores,
  backupConfig,
  storage,
  storageUsedGB,
  resilience,
  type Snapshot,
} from "@/lib/backups";
import { useSnapshots, useBackupConfig, useRunBackup, useRestoreBackup, useUpdateBackupConfig } from "@/lib/hooks/backups";

/* count-up hook (respects reduced motion) */
function useCountUp(target: number, decimals = 0, dur = 1200) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      node.textContent = target.toFixed(decimals);
      return;
    }
    const o = { n: 0 };
    const a = anime({
      targets: o, n: target, duration: dur, easing: "easeOutExpo",
      update: () => { node.textContent = o.n.toFixed(decimals); },
    });
    return () => a.pause();
  }, [target, decimals, dur]);
  return ref;
}

function Kpi({ label, value, decimals = 0, unit, sub, hero }: {
  label: string; value: number; decimals?: number; unit?: string; sub: React.ReactNode; hero?: boolean;
}) {
  const ref = useCountUp(value, decimals);
  return (
    <div className={hero ? "kpi hero" : "kpi"}>
      <div className="ic"><span className="material-symbols-rounded">{hero ? "cloud_done" : "schedule"}</span></div>
      <div className="lab">{label}</div>
      <div className="val"><span ref={ref}>0</span>{unit && <span className="u">{unit}</span>}</div>
      <div className="sub">{sub}</div>
    </div>
  );
}

export default function BackupsWorkspace() {
  const snapshotsQ = useSnapshots();
  const configQ = useBackupConfig();
  const runBackupM = useRunBackup();
  const restoreM = useRestoreBackup();
  const updateConfigM = useUpdateBackupConfig();

  const list = snapshotsQ.data ?? [];
  // Fall back to the seed config shape while GET /backups/config is in flight.
  const cfg = configQ.data ?? backupConfig;

  const [filter, setFilter] = useState<"All" | "Nightly" | "Manual">("All");

  const [nightlyOn, setNightlyOn] = useState(cfg.nightlyOn);
  const [offsiteOn, setOffsiteOn] = useState(cfg.offsiteOn);
  // Reflect the fetched config in the local toggle view once it arrives (a refetch
  // never clobbers a pending edit — the toggle handlers below write straight through
  // to PUT /backups/config, so the query becomes authoritative again on success).
  useEffect(() => {
    if (configQ.data) {
      setNightlyOn(configQ.data.nightlyOn);
      setOffsiteOn(configQ.data.offsiteOn);
    }
  }, [configQ.data]);

  function toggleNightly() {
    const next = !nightlyOn;
    setNightlyOn(next);
    updateConfigM.mutate({ nightlyOn: next }, { onError: () => setNightlyOn(!next) });
  }
  function toggleOffsite() {
    const next = !offsiteOn;
    setOffsiteOn(next);
    updateConfigM.mutate({ offsiteOn: next }, { onError: () => setOffsiteOn(!next) });
  }

  const [restoreTarget, setRestoreTarget] = useState<Snapshot | null>(null);
  const [restore, setRestore] = useState<{ ts: string; id: string; phase: "running" | "done" | "error" } | null>(null);
  const [animDone, setAnimDone] = useState(false);
  const barRef = useRef<HTMLElement>(null);

  const shown = list.filter((s) => filter === "All" || s.type === filter);
  const freeGB = Math.max(0, storage.totalGB - storageUsedGB);

  // Run a manual backup now → POST /backups/run; the ledger + config refetch on
  // success and the new row appears in the history table.
  const runBackup = () => {
    if (runBackupM.isPending) return;
    runBackupM.mutate({ type: "Manual", scope: "Database" });
  };

  // Confirmed restore → the real POST fires immediately; the progress banner is a
  // cosmetic minimum-duration wrapper around it. Whichever finishes LAST (the
  // animation or the request) drives the transition to done/error below, so a
  // slow request never gets cut off by an early "done".
  const confirmRestore = () => {
    if (!restoreTarget) return;
    setAnimDone(false);
    setRestore({ ts: restoreTarget.ts, id: restoreTarget.id, phase: "running" });
    setRestoreTarget(null);
    restoreM.mutate({ id: restoreTarget.id });
  };
  useEffect(() => {
    if (restore?.phase !== "running") return;
    const bar = barRef.current;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !bar) { setAnimDone(true); return; }
    const a = anime({ targets: bar, width: ["0%", "100%"], duration: 2800, easing: "easeInOutQuad", complete: () => setAnimDone(true) });
    return () => a.pause();
  }, [restore?.phase]);
  useEffect(() => {
    if (restore?.phase !== "running" || !animDone) return;
    if (restoreM.isSuccess) setRestore((r) => (r ? { ...r, phase: "done" } : r));
    else if (restoreM.isError) setRestore((r) => (r ? { ...r, phase: "error" } : r));
    // else still pending — the bar holds at 100% until the request settles.
  }, [animDone, restore?.phase, restoreM.isSuccess, restoreM.isError]);

  return (
    <>
      {/* KPI row */}
      <section className="kpis">
        <Kpi hero label="Last successful backup" value={cfg.lastBackupAgoH} unit="h ago"
          sub={<><span className="delta up"><span className="material-symbols-rounded">check_circle</span>OK</span> Nightly · Today 02:00</>} />
        <Kpi label="Next scheduled backup" value={cfg.nextBackupInH} unit="h"
          sub={<>Tonight · {cfg.nightlyTime}</>} />
        <Kpi label="Snapshots retained" value={cfg.retained}
          sub={<>{cfg.retentionDays}-day rolling window</>} />
        <Kpi label="Storage used" value={storageUsedGB} decimals={1} unit="GB"
          sub={<>of {storage.totalGB} GB VPS volume</>} />
      </section>

      {/* restore progress banner */}
      {restore && (
        <div className={`bk-banner${restore.phase === "done" ? " done" : restore.phase === "error" ? " error" : ""}`}>
          <span className="material-symbols-rounded">
            {restore.phase === "done" ? "task_alt" : restore.phase === "error" ? "error" : "settings_backup_restore"}
          </span>
          {restore.phase === "running" ? (
            <>
              <span className="bt">Restoring from {restore.ts}…</span>
              <span className="bp"><i ref={barRef} /></span>
            </>
          ) : restore.phase === "done" ? (
            <>
              <span className="bt">Restore complete — data restored from {restore.ts}.</span>
              <button className="bk-btn2" onClick={() => setRestore(null)}>Dismiss</button>
            </>
          ) : (
            <>
              <span className="bt">
                Restore failed — {(restoreM.error as Error)?.message ?? "try again"}.
              </span>
              <button className="bk-btn2" onClick={() => setRestore(null)}>Dismiss</button>
            </>
          )}
        </div>
      )}

      <div className="row">
        {/* Backup history */}
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">Backup History</div>
              <div className="cs">Automated nightly + on-demand snapshots · {cfg.retained} retained</div>
            </div>
            <div className="tools">
              <div className="seg">
                {(["All", "Nightly", "Manual"] as const).map((f) => (
                  <button key={f} className={filter === f ? "on" : undefined} onClick={() => setFilter(f)}>{f}</button>
                ))}
              </div>
              <button className="bk-runbtn" onClick={runBackup} disabled={runBackupM.isPending}>
                <span className={`material-symbols-rounded${runBackupM.isPending ? " spin" : ""}`}>{runBackupM.isPending ? "progress_activity" : "backup"}</span>
                {runBackupM.isPending ? "Backing up…" : "Run backup now"}
              </button>
            </div>
          </div>

          <div className="bk-table-wrap">
            <table className="bk-table">
              <thead>
                <tr>
                  <th>Snapshot</th><th>Type</th><th>Scope</th><th>Size</th><th>Duration</th><th>Status</th><th></th>
                </tr>
              </thead>
              <tbody>
                {snapshotsQ.isLoading && (
                  <tr><td colSpan={7} style={{ padding: 16, color: "var(--muted)" }}>Loading snapshots…</td></tr>
                )}
                {snapshotsQ.isError && !snapshotsQ.isLoading && (
                  <tr><td colSpan={7} style={{ padding: 16, color: "var(--warn, #A96913)" }}>
                    Couldn&apos;t load snapshots — {(snapshotsQ.error as Error)?.message ?? "try again"}.
                  </td></tr>
                )}
                {!snapshotsQ.isLoading && !snapshotsQ.isError && shown.map((s) => (
                  <tr key={s.id}>
                    <td className="ts">{s.ts}</td>
                    <td><span className={`bk-type ${s.type}`}>{s.type}</span></td>
                    <td>{s.scope}</td>
                    <td className="mono">{s.size}</td>
                    <td className="mono">{s.duration}</td>
                    <td>
                      <span className={`bk-status ${s.status}`}>
                        <span className="dot" />
                        {s.status === "success" ? "Success" : s.status === "running" ? "Running" : "Failed"}
                      </span>
                    </td>
                    <td>
                      <div className="bk-actions">
                        <button className="bk-ico" title="Restore this snapshot"
                          disabled={s.status !== "success"} onClick={() => setRestoreTarget(s)}>
                          <span className="material-symbols-rounded">settings_backup_restore</span>
                        </button>
                        <button className="bk-ico" title="Download" disabled={s.status !== "success"}>
                          <span className="material-symbols-rounded">download</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!snapshotsQ.isLoading && !snapshotsQ.isError && shown.length === 0 && (
                  <tr><td colSpan={7} style={{ padding: 16, color: "var(--muted)" }}>No snapshots yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {runBackupM.isError && (
            <div className="bk-note warn-note">
              <span className="material-symbols-rounded">error</span>
              <span>Couldn&apos;t start the backup — {(runBackupM.error as Error)?.message ?? "try again"}.</span>
            </div>
          )}
        </section>

        {/* What's protected */}
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">What&apos;s Protected</div>
              <div className="cs">Included in every snapshot</div>
            </div>
          </div>
          <div className="bk-stores">
            {protectedStores.map((st) => (
              <div key={st.key} className={st.included ? "bk-store" : "bk-store off"}>
                <span className="med"><span className="material-symbols-rounded">{st.icon}</span></span>
                <div className="info">
                  <div className="nm">{st.name}</div>
                  <div className="ds">{st.desc}</div>
                </div>
                <div className="rt">
                  <div className="sz">{st.size}</div>
                  <div className={`inc ${st.included ? "yes" : "no"}`}>{st.included ? "Included" : "Excluded"}</div>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="row b">
        {/* Schedule & retention */}
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">Schedule &amp; Retention</div>
              <div className="cs">Automated nightly backups, agency-controlled</div>
            </div>
          </div>

          <div className="bk-setting">
            <div className="bk-st">
              <div className="bk-st-t">Nightly backups</div>
              <div className="bk-st-d">Runs every night at {cfg.nightlyTime}</div>
            </div>
            <button className={`bk-switch${nightlyOn ? " on" : ""}`} aria-pressed={nightlyOn}
              aria-label="Toggle nightly backups" onClick={toggleNightly} disabled={updateConfigM.isPending} />
          </div>
          <div className="bk-setting">
            <div className="bk-st">
              <div className="bk-st-t">Off-site copy</div>
              <div className="bk-st-d">Mirror snapshots to object storage (add later)</div>
            </div>
            <button className={`bk-switch${offsiteOn ? " on" : ""}`} aria-pressed={offsiteOn}
              aria-label="Toggle off-site copy" onClick={toggleOffsite} disabled={updateConfigM.isPending} />
          </div>
          <div className="bk-setting">
            <div className="bk-st">
              <div className="bk-st-t">Retention window</div>
              <div className="bk-st-d">Older snapshots are pruned automatically</div>
            </div>
            <div className="bk-st-v">{cfg.retentionDays} days</div>
          </div>
          <div className="bk-setting">
            <div className="bk-st">
              <div className="bk-st-t">Restore last tested</div>
              <div className="bk-st-d">Documented restore runbook verified</div>
            </div>
            <div className="bk-st-v">{cfg.restoreTested}</div>
          </div>

          {!nightlyOn && (
            <div className="bk-note warn-note">
              <span className="material-symbols-rounded">warning</span>
              <span>Nightly backups are <b>off</b>. New data will not be protected until you turn them back on.</span>
            </div>
          )}
          <div className="bk-note">
            <span className="material-symbols-rounded">verified_user</span>
            <span><b>You own all of it.</b> The server and every snapshot live in your name — you choose to keep or turn off backups at any time.</span>
          </div>
        </section>

        {/* Storage & resilience */}
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">Storage &amp; Resilience</div>
              <div className="cs">VPS volume · artifacts stored locally</div>
            </div>
          </div>

          <div className="bk-usage">
            <span className="u1">{storageUsedGB.toFixed(1)} GB</span>
            <span className="u2">used of {storage.totalGB} GB · {freeGB.toFixed(1)} GB free</span>
          </div>
          <div className="bk-meter">
            <div className="bk-bar">
              {storage.segments.map((sg) => (
                <span key={sg.key} className="bk-seg" style={{ width: `${(sg.gb / storage.totalGB) * 100}%`, background: sg.color }} />
              ))}
            </div>
            <div className="bk-lg">
              {storage.segments.map((sg) => (
                <span key={sg.key}><i style={{ background: sg.color }} />{sg.label} · {sg.gb} GB</span>
              ))}
              <span><i style={{ background: "rgba(33,27,41,.06)" }} />Free · {freeGB.toFixed(1)} GB</span>
            </div>
          </div>

          <div className="bk-check">
            {resilience.map((r) => (
              <div className="ci" key={r}>
                <span className="material-symbols-rounded">check_circle</span>
                <span>{r}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* human-confirmed restore modal */}
      {restoreTarget && (
        <div className="modal-overlay" onClick={() => setRestoreTarget(null)}>
          <div className="modal-panel bk-modal" role="dialog" aria-modal="true" aria-label="Confirm restore" onClick={(e) => e.stopPropagation()}>
            <div className="bk-modal-head">
              <div>
                <div className="ey">Documented restore</div>
                <h2>Restore this snapshot?</h2>
              </div>
              <button className="modal-x" onClick={() => setRestoreTarget(null)} aria-label="Cancel">
                <span className="material-symbols-rounded">close</span>
              </button>
            </div>
            <div className="snapline"><span className="k">Snapshot</span><span className="v">{restoreTarget.ts}</span></div>
            <div className="snapline"><span className="k">Scope</span><span className="v">{restoreTarget.scope}</span></div>
            <div className="snapline"><span className="k">Size</span><span className="v">{restoreTarget.size}</span></div>
            <div className="warn">
              <span className="material-symbols-rounded">warning</span>
              <p>Restoring replaces current data with this snapshot. Like every client-facing change, this is a human-confirmed step and is written to the activity log.</p>
            </div>
            <div className="bk-modal-foot">
              <button className="bk-btn2" onClick={() => setRestoreTarget(null)}>Cancel</button>
              <button className="bk-btn2 danger" onClick={confirmRestore}>
                <span className="material-symbols-rounded">settings_backup_restore</span>Restore now
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
