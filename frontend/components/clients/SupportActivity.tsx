"use client";

import { useState } from "react";
import ConvertToTask from "./ConvertToTask";
import ThreadPanel from "@/components/threads/ThreadPanel";
import EmptyState from "@/components/ui/EmptyState";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import type { Ticket } from "@/lib/data";
import { useTickets, useUpdateTicketStatus } from "@/lib/hooks/clients";

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
              {openId === t.id ? (
                <div onClick={(e) => e.stopPropagation()}>
                  <TicketTriage ticket={t} />
                  {/* Not rendered once converted: the request already has its task,
                      and the server refuses a second conversion. */}
                  {!t.taskCode && <ConvertToTask ticket={t} />}
                  <ThreadPanel entity="ticket" code={t.id} />
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// `ReplyBox` used to live here: a single free-text box writing
// `support_tickets.reply`, the one and only answer a ticket could ever hold.
// `ThreadPanel` replaces it with the full conversation, and carries the two things
// the old box could not: an INTERNAL note the client never sees, and a history
// rather than a single overwritable field.
//
// It keeps the behaviour that mattered - a client-visible message still emails the
// client (app/routers/threads.py `_email_client_reply`), which is what
// `POST /tickets/{code}/reply` did. That endpoint and the column remain, so a reply
// sent before threads existed is still readable; migration 0099 copied every one of
// them into its thread.


// Move a request through open -> pending -> resolved.
//
// `PATCH /tickets/{code}/status` and its hook both existed and NOTHING called them:
// an admin could read a client's request and answer it, and had no way to mark it
// dealt with. The client sees the status in their portal, so it stayed "open"
// forever however much work had been done on it.
function TicketTriage({ ticket }: { ticket: Ticket }) {
  const update = useUpdateTicketStatus();
  const [confirmDone, setConfirmDone] = useState(false);
  // Completion is deliberately NOT just the third segment. Resolving a request emails
  // the client and lights up their portal bell, so it is the one outward-facing move
  // on this widget and it gets its own named control that says so before it fires.
  const options: Ticket["status"][] = ["open", "pending"];
  const done = ticket.status === "resolved";

  return (
    <div className="tk-triage">
      <span className="tk-triage-lab">Status</span>
      <div className="seg" role="tablist" aria-label={`Status for ${ticket.id}`}>
        {options.map((s) => (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={ticket.status === s}
            className={ticket.status === s ? "on" : ""}
            disabled={update.isPending || ticket.status === s}
            onClick={() => update.mutate({ code: ticket.id, status: s })}
          >
            {STATUS_LABEL[s] ?? s}
          </button>
        ))}
      </div>

      {done ? (
        <span className="tk-done">
          <span className="material-symbols-rounded">task_alt</span>
          Completed &mdash; the client has been told.
        </span>
      ) : (
        <button
          type="button"
          className="mini-btn"
          disabled={update.isPending}
          onClick={() => setConfirmDone(true)}
          title={`Mark ${ticket.id} complete and tell the client`}
        >
          <span className="material-symbols-rounded">task_alt</span>
          {update.isPending ? "Completing…" : "Mark complete"}
        </button>
      )}

      {update.isError && (
        <span className="tk-triage-err" role="alert">
          Couldn&apos;t update the status.
        </span>
      )}

      {/* The task a request was converted into is NOT shown here, deliberately: the
          link is recorded as an internal message on the request's thread, not as a
          queryable column, so any "the work is done" state rendered on this row would
          be inferred rather than read. The operator marks completion; the platform
          does not guess it. */}
      <ConfirmDialog
        open={confirmDone}
        title={`Mark ${ticket.id} complete?`}
        body="The client is emailed and the request is marked complete in their portal."
        reassurance="You can move it back to open or in-review afterwards if it turns out more work is needed."
        confirmLabel="Mark complete"
        tone="caution"
        pending={update.isPending}
        onCancel={() => setConfirmDone(false)}
        onConfirm={() => {
          setConfirmDone(false);
          update.mutate({ code: ticket.id, status: "resolved" });
        }}
      />
    </div>
  );
}
