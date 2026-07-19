"use client";

import EmptyState from "@/components/ui/EmptyState";

// Subscription health — status distribution, tier breakdown, and MRR.
// Not wired to live billing data yet, so it shows an honest "no current data"
// state rather than fabricated account counts and revenue.
export default function SubscriptionStatus() {
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Subscription Status</div>
          <div className="cs">Plan mix &amp; monthly recurring revenue</div>
        </div>
      </div>
      <EmptyState
        icon="donut_small"
        title="No current data"
        hint="Subscription mix and MRR will appear here once billing data is connected."
      />
    </section>
  );
}
