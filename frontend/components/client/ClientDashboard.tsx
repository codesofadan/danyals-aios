"use client";

import { dashboardReports } from "@/lib/client";
import { useClient } from "./ClientContext";
import ClientHeader from "./ClientHeader";
import LockableChart from "./LockableChart";

// The client's main dashboard — a grid of report/graph cards. Each card
// the admin granted starts LOCKED behind a padlock; the client pops it to
// play the unlock animation and reveal live, monthly data (à la Search
// Console / Analytics / GMB). Cards that were never granted stay locked.
export default function ClientDashboard() {
  const { grants, unlocked, isGranted } = useClient();

  const total = dashboardReports.length;
  const grantedCount = grants.size;
  const unlockedCount = [...unlocked].filter((k) => isGranted(k)).length;

  // Granted-but-locked cards float to the top so the client sees what's
  // ready to open first; fully-locked (upsell) cards sink to the bottom.
  const ordered = [...dashboardReports].sort((a, b) => rank(isGranted(a.key)) - rank(isGranted(b.key)));

  return (
    <div className="tw cl">
      <ClientHeader
        eyebrow=""
        focus={
          <>
            <span className="cl-focus-k">Your dashboard</span>
            <span className="cl-focus-v">{unlockedCount} of {grantedCount} graphs opened</span>
            <span className="cl-focus-note">
              <span className="material-symbols-rounded">lock_open</span>
              {grantedCount - unlockedCount > 0 ? `${grantedCount - unlockedCount} ready to unlock` : "All your graphs are live"}
            </span>
          </>
        }
      />

      <div className="cl-legend">
        <span className="cl-legend-item"><span className="cl-legend-sw ready" /> Granted — tap to unlock</span>
        <span className="cl-legend-item"><span className="cl-legend-sw live" /> Live — data is showing</span>
        <span className="cl-legend-item"><span className="cl-legend-sw locked" /> Locked — not in your plan</span>
        <span className="cl-legend-count">{grantedCount} / {total} available</span>
      </div>

      <div className="cl-grid">
        {ordered.map((r) => (
          <LockableChart key={r.key} report={r} />
        ))}
      </div>
    </div>
  );
}

function rank(granted: boolean): number {
  return granted ? 0 : 1;
}
