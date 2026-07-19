"use client";

import EmptyState from "@/components/ui/EmptyState";

// Client base growth — trailing 12-month account trend.
// No live growth-analytics source is wired yet, so this shows an honest
// "no current data" state instead of a fabricated trend line.
export default function ClientGrowth() {
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Client Base Growth</div>
          <div className="cs">Total active accounts · trailing 12 months</div>
        </div>
      </div>
      <EmptyState
        icon="show_chart"
        title="No current data"
        hint="Client-growth history will appear here once it's tracked from live accounts."
      />
    </section>
  );
}
