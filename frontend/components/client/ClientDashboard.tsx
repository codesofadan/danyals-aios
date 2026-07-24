"use client";

import Link from "next/link";
import { dashboardReports } from "@/lib/client";
import { useClient } from "./ClientContext";
import ClientHeader from "./ClientHeader";
import LockableChart from "./LockableChart";

// The client's main dashboard — a headline stat strip (real audit figures from
// GET /portal/dashboard) over a grid of report/graph cards. Each card the admin
// granted starts LOCKED behind a padlock; the client pops it to play the reveal
// animation and show the live, monthly data the backend already sent. Cards that
// were never granted stay locked (an upsell to request access).
export default function ClientDashboard() {
  const { grants, unlocked, isGranted, reportViz, latestScore, latestAuditWhen, totalAudits } = useClient();

  const total = dashboardReports.length;
  const grantedCount = grants.size;
  const unlockedCount = [...unlocked].filter((k) => isGranted(k)).length;
  const pending = grantedCount - unlockedCount;

  // Honest header copy for every state: no graphs granted at all is NOT "all live".
  const note =
    grantedCount === 0
      ? "No graphs yet — ask your account manager to share reports"
      : pending > 0
        ? `${pending} ready to reveal`
        : "All your graphs are showing";

  // Keep the static report CATALOG (label/icon/group/desc) but draw each card's
  // live data from the granted viz the backend sent. An ungranted card stays
  // locked and never renders its viz, so its (unused) placeholder is never shown.
  const cards = dashboardReports.map((r) => ({ ...r, viz: reportViz[r.key] ?? r.viz }));

  // Granted-but-locked cards float to the top so the client sees what's
  // ready to open first; fully-locked (upsell) cards sink to the bottom.
  const ordered = [...cards].sort((a, b) => rank(isGranted(a.key)) - rank(isGranted(b.key)));

  return (
    <div className="tw cl">
      <ClientHeader
        focus={
          <>
            <span className="cl-focus-k">Your dashboard</span>
            <span className="cl-focus-v">{unlockedCount} of {grantedCount} graphs open</span>
            <span className="cl-focus-note">
              <span className="material-symbols-rounded">visibility</span>
              {note}
            </span>
          </>
        }
      />

      {/* headline audit figures — always-available real data from the dashboard endpoint */}
      <div className="cl-stats">
        <div className="cl-stat-card">
          <div className="cl-stat-k">Latest audit score</div>
          <div className="cl-stat-big">
            {latestScore ?? "—"}
            {latestScore !== null && <span className="cl-stat-u">/100</span>}
          </div>
          <div className="cl-stat-sub">{latestAuditWhen || "No audits yet"}</div>
        </div>
        <div className="cl-stat-card">
          <div className="cl-stat-k">Audits run</div>
          <div className="cl-stat-big">{totalAudits}</div>
          <div className="cl-stat-sub">
            <Link href="/client/audits" className="cl-stat-link">View your audits →</Link>
          </div>
        </div>
        <div className="cl-stat-card">
          <div className="cl-stat-k">Graphs available</div>
          <div className="cl-stat-big">
            {grantedCount}<span className="cl-stat-u">/{total}</span>
          </div>
          <div className="cl-stat-sub">{unlockedCount} revealed so far</div>
        </div>
      </div>

      <div className="cl-legend">
        <span className="cl-legend-item"><span className="cl-legend-sw ready" /> Granted — tap to reveal</span>
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
