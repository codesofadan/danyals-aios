"use client";

import { useRouter } from "next/navigation";
import type { DashboardReport } from "@/lib/client";
import { reportColor } from "@/lib/client";
import MiniChart from "./MiniChart";
import { useClient } from "./ClientContext";

// A single dashboard report card with TWO faces:
//   · granted   - the live, themed visualization, shown immediately.
//   · ungranted - not included in this client's plan. A padlock that links to
//                 the requests page so they can ask their account manager.
//
// There used to be a third and fourth face: a granted card started closed behind
// a padlock the client had to tap, played a 1.5s reveal animation, and remembered
// per-tenant in localStorage which cards had been popped. That was a game, not a
// portal. It also read as an access decision it never was - the grant is the
// admin's, already made server-side, and the backend only ever sends viz data for
// keys it has granted. Making the client tap a lock to see data they were already
// entitled to added a step and implied a permission that had already been given.
export default function LockableChart({ report }: { report: DashboardReport }) {
  const router = useRouter();
  const { isGranted, isPlaceholder } = useClient();
  const granted = isGranted(report.key);
  const sample = isPlaceholder(report.key);
  const accent = reportColor(report);

  return (
    <section
      className={`cl-chart ${granted ? "unlocked" : "locked"}`}
      style={{ ["--accent" as string]: accent }}
      aria-label={report.label}
    >
      <header className="cl-chart-h">
        <span className="cl-chart-ic material-symbols-rounded">{report.icon}</span>
        <div className="cl-chart-tt">
          <div className="cl-chart-t">{report.label}</div>
          <div className="cl-chart-grp">{report.group}</div>
        </div>
        <ChartBadge granted={granted} sample={sample} />
      </header>

      {granted ? (
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
            onClick={() => router.push("/client/requests")}
            title="Not included in your plan - request access from your account manager"
          >
            <span className="cl-lock-badge">
              <span className="cl-lock-icon material-symbols-rounded">lock</span>
            </span>
            <span className="cl-lock-txt">Not in your plan</span>
            <span className="cl-lock-sub">Request access from your account manager</span>
          </button>
        </div>
      )}
    </section>
  );
}

function ChartBadge({ granted, sample }: { granted: boolean; sample?: boolean }) {
  if (!granted) {
    return <span className="cl-chart-badge locked"><span className="material-symbols-rounded">lock</span>Locked</span>;
  }
  // A backend-flagged placeholder series is representative sample data - it
  // must never be presented to a paying client as "Live".
  if (sample) {
    return (
      <span className="cl-chart-badge sample" title="Representative preview - live data appears as this service ramps up" style={{ background: "rgba(255,180,60,.12)", color: "#c8871a", borderColor: "rgba(200,135,26,.35)" }}>
        <span className="material-symbols-rounded" style={{ fontSize: "0.85em" }}>science</span>Preview
      </span>
    );
  }
  return (
    <span className="cl-chart-badge live">
      <span className="cl-live-dot" />Live
    </span>
  );
}
