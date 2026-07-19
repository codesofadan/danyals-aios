"use client";

import EmptyState from "@/components/ui/EmptyState";

// Recent support activity — latest tickets across client accounts.
// The ticketing feed isn't wired into this view yet, so it shows an honest
// "no current data" state instead of fabricated tickets.
export default function SupportActivity() {
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Recent Support Activity</div>
          <div className="cs">Latest tickets across all client accounts</div>
        </div>
      </div>
      <EmptyState
        icon="confirmation_number"
        title="No current data"
        hint="Support tickets will appear here once the ticketing feed is connected."
      />
    </section>
  );
}
