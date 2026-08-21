"use client";

import ScheduledJobs from "./ScheduledJobs";

// Reports Library is trimmed to Scheduled Jobs only (per operator request) — the
// Websites / per-client workbook / sync activity / what-gets-synced / Sheets
// connection sub-sections are removed. Scheduled Jobs are currently disabled
// manually; nothing here toggles that setting.
export default function ReportsWorkspace() {
  return (
    <div className="row-single">
      <ScheduledJobs />
    </div>
  );
}
