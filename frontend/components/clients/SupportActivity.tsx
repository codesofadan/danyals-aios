"use client";

import { useState } from "react";
import EmptyState from "@/components/ui/EmptyState";
import type { Ticket } from "@/lib/data";
import { useReplyToTicket, useTickets } from "@/lib/hooks/clients";

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
  const [openId, setOpenId] = useState<string | null>(null);

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
            <li key={t.id}>
              <div
                style={{ display: "flex", alignItems: "center", gap: "0.7rem", cursor: "pointer" }}
                onClick={() => setOpenId((cur) => (cur === t.id ? null : t.id))}
              >
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
              </div>
              {openId === t.id ? <ReplyBox ticket={t} onDone={() => setOpenId(null)} /> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// Inline free-text reply (POST /tickets/{code}/reply) — the first UI to ever write
// support_tickets.reply. Emails the real message to the client when it's linked.
function ReplyBox({ ticket, onDone }: { ticket: Ticket; onDone: () => void }) {
  const [message, setMessage] = useState("");
  const replyM = useReplyToTicket();

  const send = () => {
    const text = message.trim();
    if (!text) return;
    replyM.mutate(
      { code: ticket.id, message: text },
      { onSuccess: () => { setMessage(""); onDone(); } },
    );
  };

  return (
    <div
      style={{ marginTop: "0.5rem", marginLeft: "1.4rem", display: "grid", gap: "0.4rem" }}
      onClick={(e) => e.stopPropagation()}
    >
      <textarea
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        placeholder={`Reply to ${ticket.client}…`}
        rows={3}
        style={{
          width: "100%", fontSize: "0.85rem", padding: "0.5rem 0.6rem", borderRadius: 8,
          border: "1px solid var(--line, #33333322)", resize: "vertical", fontFamily: "inherit",
        }}
      />
      <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
        <button type="button" className="ghostbtn" onClick={onDone} disabled={replyM.isPending}>
          Cancel
        </button>
        <button type="button" className="primary-btn" onClick={send} disabled={replyM.isPending || !message.trim()}>
          {replyM.isPending ? "Sending…" : "Send reply"}
        </button>
      </div>
      {replyM.isError ? (
        <div style={{ color: "#D64545", fontSize: "0.78rem" }}>Couldn&apos;t send the reply. Try again.</div>
      ) : null}
    </div>
  );
}
