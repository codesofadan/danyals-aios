"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { DashboardReport } from "@/lib/client";
import { reportColor } from "@/lib/client";
import MiniChart from "./MiniChart";
import { useClient } from "./ClientContext";

type Phase = "locked" | "unlockable" | "unlocking" | "unlocked";
const UNLOCK_MS = 1500;

// A single dashboard report card with three faces:
//   · locked      — not granted by the admin. Grayed out behind a padlock;
//                   the client can only request access.
//   · unlockable  — granted but not yet opened. A glowing padlock the client
//                   pops to reveal the data.
//   · unlocking   — the transition: the padlock springs open, a green success
//                   wash sweeps the card, then the real chart draws in.
//   · unlocked    — the live, themed visualization.
export default function LockableChart({ report }: { report: DashboardReport }) {
  const router = useRouter();
  const { clientId, isGranted, isUnlocked, unlock } = useClient();
  const granted = isGranted(report.key);
  const accent = reportColor(report);

  const initial: Phase = !granted ? "locked" : isUnlocked(report.key) ? "unlocked" : "unlockable";
  const [phase, setPhase] = useState<Phase>(initial);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Re-sync to the signed-in client (the demo switcher can change it, and
  // each client has its own grants + unlocked set).
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    setPhase(!granted ? "locked" : isUnlocked(report.key) ? "unlocked" : "unlockable");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId, report.key]);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  function startUnlock() {
    if (phase !== "unlockable") return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) { unlock(report.key); setPhase("unlocked"); return; }
    setPhase("unlocking");
    timer.current = setTimeout(() => { unlock(report.key); setPhase("unlocked"); }, UNLOCK_MS);
  }

  return (
    <section
      className={`cl-chart ${phase}`}
      style={{ ["--accent" as string]: accent }}
      aria-label={report.label}
    >
      <header className="cl-chart-h">
        <span className="cl-chart-ic material-symbols-rounded">{report.icon}</span>
        <div className="cl-chart-tt">
          <div className="cl-chart-t">{report.label}</div>
          <div className="cl-chart-grp">{report.group}</div>
        </div>
        <ChartBadge phase={phase} />
      </header>

      {phase === "unlocked" ? (
        <div className="cl-chart-live">
          <div className="cl-chart-read">
            <div className="cl-chart-num">{report.viz.headline}{report.viz.unit && <span className="u">{report.viz.unit}</span>}</div>
            {report.viz.delta && (
              <span className={`cl-chart-delta ${report.viz.up ? "up" : "down"}`}>
                <span className="material-symbols-rounded">{report.viz.up ? "trending_up" : "trending_down"}</span>
                {report.viz.delta}
              </span>
            )}
          </div>
          <div className="cl-chart-cap">{report.viz.caption}</div>
          <MiniChart id={report.key} accent={accent} viz={report.viz} />
        </div>
      ) : (
        <div className="cl-chart-locked">
          {/* blurred placeholder skeleton behind the padlock */}
          <div className="cl-lock-skeleton" aria-hidden>
            <span /><span /><span /><span /><span /><span />
          </div>

          <button
            type="button"
            className="cl-lock"
            onClick={granted ? startUnlock : () => router.push("/client/requests")}
            disabled={phase === "unlocking"}
            title={granted ? "Tap to unlock this graph" : "Locked — request access from your account manager"}
          >
            <span className="cl-lock-badge">
              <span className="cl-lock-icon material-symbols-rounded">
                {phase === "unlocking" ? "lock_open" : "lock"}
              </span>
            </span>
            <span className="cl-lock-txt">
              {phase === "unlocking" ? "Unlocking…" : granted ? "Tap to unlock" : "Locked"}
            </span>
            <span className="cl-lock-sub">
              {granted ? report.desc : "Not included in your plan — request access"}
            </span>
          </button>

          {/* green success wash that sweeps across on unlock */}
          {phase === "unlocking" && (
            <div className="cl-unlock-fx" aria-hidden>
              <span className="cl-unlock-ring" />
              <span className="cl-unlock-ring d2" />
              <span className="cl-unlock-check material-symbols-rounded">check</span>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function ChartBadge({ phase }: { phase: Phase }) {
  if (phase === "unlocked") {
    return (
      <span className="cl-chart-badge live">
        <span className="cl-live-dot" />Live
      </span>
    );
  }
  if (phase === "unlocking") {
    return <span className="cl-chart-badge unlocking"><span className="material-symbols-rounded">lock_open</span>Unlocking</span>;
  }
  if (phase === "unlockable") {
    return <span className="cl-chart-badge ready"><span className="material-symbols-rounded">lock_open</span>Ready</span>;
  }
  return <span className="cl-chart-badge locked"><span className="material-symbols-rounded">lock</span>Locked</span>;
}
