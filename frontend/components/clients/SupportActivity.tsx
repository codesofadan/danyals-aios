"use client";

import EmptyState from "@/components/ui/EmptyState";
import type { Ticket } from "@/lib/data";
import { useTickets } from "@/lib/hooks/clients";

const PRIORITY_COLOR: Record<Ticket["priority"], string> = {
  urgent: "#D64545",
  high: "#C8871A",
  med: "#5B8DEF",
  low: "#8A8F98",
};
const STATUS_LABEL: Record<Ticket["status"], string> = {
  open: "Open",
  pending: "Pending",
  resolved: "Resolved",
};

// Recent support activity — the LIVE ticket queue (GET /tickets, newest first).
export default function SupportActivity() {
  const ticketsQ = useTickets();
  const tickets = (ticketsQ.data ?? []).slice(0, 6);

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Recent Support Activity</div>
          <div className="cs">Latest tickets across all client accounts</div>
        </div>
      </div>

      {ticketsQ.isLoading ? (
        <div style={{ padding: "1.5rem 0", textAlign: "center", color: "var(--muted)" }}>Loading…</div>
      ) : tickets.length === 0 ? (
        <EmptyState
          icon="confirmation_number"
          title="No tickets"
          hint="Support tickets logged against any client will appear here."
        />
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: "0.55rem" }}>
          {tickets.map((t) => (
            <li key={t.id} style={{ display: "flex", alignItems: "center", gap: "0.7rem" }}>
              <span
                aria-hidden
                style={{ width: 8, height: 8, borderRadius: 999, flex: "0 0 auto", background: PRIORITY_COLOR[t.priority] ?? "#8A8F98" }}
                title={`Priority: ${t.priority}`}
              />
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: "0.88rem", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {t.subject}
                </div>
                <div style={{ color: "var(--muted)", fontSize: "0.78rem" }}>
                  {t.client} · {t.channel} · {t.ago}
                </div>
              </div>
              <span style={{
                fontSize: "0.75rem", fontWeight: 700, padding: "0.15rem 0.55rem", borderRadius: 999,
                border: "1px solid var(--line, #33333322)", color: t.status === "resolved" ? "#2FA36B" : "inherit",
              }}>
                {STATUS_LABEL[t.status] ?? t.status}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
