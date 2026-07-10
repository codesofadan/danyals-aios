"use client";

import { tickets, type Ticket } from "@/lib/data";

const PRIORITY_CLS: Record<Ticket["priority"], string> = {
  urgent: "urgent", high: "high", med: "med", low: "low",
};
const STATUS_CLS: Record<Ticket["status"], string> = {
  open: "warn", pending: "info", resolved: "ok",
};
const CHANNEL_ICON: Record<Ticket["channel"], string> = {
  Email: "mail", Portal: "web", Call: "call", Chat: "chat",
};

export default function SupportActivity() {
  const open = tickets.filter((t) => t.status === "open").length;
  const pending = tickets.filter((t) => t.status === "pending").length;

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Recent Support Activity</div>
          <div className="cs">Latest tickets across all client accounts</div>
        </div>
        <div className="tools">
          <span className="pill-tag warn"><span className="material-symbols-rounded">confirmation_number</span>{open} open</span>
          <span className="pill-tag info"><span className="material-symbols-rounded">schedule</span>{pending} pending</span>
        </div>
      </div>

      <div className="ticket-list">
        {tickets.map((t) => (
          <div className="ticket" key={t.id}>
            <span className={`prio ${PRIORITY_CLS[t.priority]}`} title={`${t.priority} priority`} />
            <div className="tk-main">
              <div className="tk-subject">{t.subject}</div>
              <div className="tk-meta">
                <span className="tk-id">{t.id}</span>
                <span className="tk-dot">·</span>
                <span className="tk-client">{t.client}</span>
                <span className="tk-chan">
                  <span className="material-symbols-rounded">{CHANNEL_ICON[t.channel]}</span>{t.channel}
                </span>
              </div>
            </div>
            <span className={`status-pill ${STATUS_CLS[t.status]}`}>{t.status}</span>
            <span className="tk-ago">{t.ago}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
