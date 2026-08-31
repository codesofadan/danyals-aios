"use client";

// ============================================================
// AIOS · Client requests — the queue a client's ask arrives in.
//
// The flow already worked end to end: a client raises a request, an admin converts
// it to a task, a team member is assigned and emailed, notes and replies live on the
// request's thread. What it had no HOME. Requests were a six-row widget on the
// Clients page, and the work they became was on the task board, and nothing joined
// the two - the connection existed only as a sentence inside a thread message.
//
// So this is not a second request system. It is the same tickets, on the surface
// where the work is managed, now that `support_tickets.task_id` (0117) makes "which
// request became which task, and how far along is it?" a query instead of a reading
// exercise.
// ============================================================

import { useMemo, useState } from "react";
import Link from "next/link";
import { useTickets, useUpdateTicketStatus } from "@/lib/hooks/clients";
import { TASK_STATUS_META, type Ticket, type TaskStatus } from "@/lib/data";
import ThreadPanel from "@/components/threads/ThreadPanel";
import ConvertToTask from "@/components/clients/ConvertToTask";

const STATUS_LABEL: Record<Ticket["status"], string> = {
  open: "Open",
  pending: "In review",
  resolved: "Resolved",
};

const PRIORITY_COLOR: Record<Ticket["priority"], string> = {
  urgent: "var(--crit)",
  high: "var(--warn)",
  med: "var(--c4)",
  low: "var(--muted)",
};

type Filter = "needs_action" | "converted" | "all";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "needs_action", label: "Needs action" },
  { key: "converted", label: "In progress" },
  { key: "all", label: "All" },
];

function TaskLink({ ticket }: { ticket: Ticket }) {
  if (!ticket.taskCode) return null;
  const meta = TASK_STATUS_META[(ticket.taskStatus ?? "todo") as TaskStatus];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <Link href="/admin/tasks" className="tm-code" style={{ fontWeight: 700 }}>
        {ticket.taskCode}
      </Link>
      {meta && <span className={`status-pill ${meta.cls}`}>{meta.label}</span>}
      {ticket.taskAssignee && (
        <span style={{ fontSize: 12, color: "var(--muted)" }}>{ticket.taskAssignee}</span>
      )}
    </span>
  );
}

export default function ClientRequests() {
  const ticketsQ = useTickets();
  const updateStatus = useUpdateTicketStatus();
  const [filter, setFilter] = useState<Filter>("needs_action");
  const [openId, setOpenId] = useState<string | null>(null);

  const tickets = useMemo(() => ticketsQ.data ?? [], [ticketsQ.data]);
  const rows = useMemo(
    () =>
      tickets.filter((t) => {
        if (filter === "all") return true;
        // "Needs action" is the working definition of a queue: unresolved, and
        // nobody has been given the work yet.
        if (filter === "needs_action") return t.status !== "resolved" && !t.taskCode;
        return Boolean(t.taskCode) && t.status !== "resolved";
      }),
    [tickets, filter],
  );

  const waiting = tickets.filter((t) => t.status !== "resolved" && !t.taskCode).length;

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Client requests</div>
          <div className="cs">
            What clients have asked for, and the work it became. Converting one assigns
            it to a team member and emails them; the conversation stays on the request.
          </div>
        </div>
        <div className="seg">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              className={filter === f.key ? "on" : undefined}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
              {f.key === "needs_action" && waiting > 0 ? ` (${waiting})` : ""}
            </button>
          ))}
        </div>
      </div>

      {ticketsQ.isLoading ? (
        <div className="cs" style={{ padding: 18 }}>Loading requests…</div>
      ) : ticketsQ.isError ? (
        // A failed fetch is not an empty queue. Saying "nothing to action" to an
        // operator whose clients are waiting is the worse of the two errors.
        <div style={{ padding: 18, color: "var(--crit)", fontWeight: 600, fontSize: 13 }}>
          Couldn&rsquo;t load client requests.{" "}
          <button type="button" className="ghostbtn" onClick={() => void ticketsQ.refetch()}>
            Retry
          </button>
        </div>
      ) : rows.length === 0 ? (
        <div className="cs" style={{ padding: 18 }}>
          {filter === "needs_action"
            ? "Nothing waiting. Every open request has been assigned to someone."
            : filter === "converted"
              ? "No requests currently being worked on."
              : "No client requests yet."}
        </div>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {rows.map((t) => {
            const open = openId === t.id;
            return (
              <li key={t.id} style={{ borderTop: "1px solid var(--line)" }}>
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => setOpenId(open ? null : t.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") setOpenId(open ? null : t.id);
                  }}
                  style={{
                    display: "flex", alignItems: "center", gap: 12,
                    padding: "12px 16px", cursor: "pointer",
                  }}
                >
                  <span
                    aria-hidden
                    style={{
                      width: 8, height: 8, borderRadius: 999, flex: "0 0 auto",
                      background: PRIORITY_COLOR[t.priority],
                    }}
                    title={`Priority: ${t.priority}`}
                  />
                  <span style={{ minWidth: 0, flex: 1 }}>
                    <span style={{ display: "block", fontWeight: 600, fontSize: 14 }}>
                      {t.subject}
                    </span>
                    <span style={{ display: "block", color: "var(--muted)", fontSize: 12.5 }}>
                      {t.id} · {t.client} · {t.ago}
                    </span>
                  </span>
                  <TaskLink ticket={t} />
                  <span className="status-pill mut">{STATUS_LABEL[t.status]}</span>
                </div>

                {open && (
                  <div style={{ padding: "0 16px 16px" }} onClick={(e) => e.stopPropagation()}>
                    {/* Not yet assigned to anyone: converting is the next step. */}
                    {!t.taskCode && <ConvertToTask ticket={t} />}

                    {/* The work is done but the client's request is still open. The
                        nudge is deliberate rather than an auto-resolve: closing a
                        request notifies the client, and that should be somebody's
                        decision, not a side effect of a task board. */}
                    {t.taskCode && t.taskStatus === "done" && t.status !== "resolved" && (
                      <div
                        style={{
                          display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
                          border: "1px solid var(--line)", borderRadius: 10,
                          padding: "10px 12px", marginBottom: 12, fontSize: 13,
                        }}
                      >
                        <span>
                          <b>{t.taskCode} is done.</b> Mark this request complete? The
                          client is notified.
                        </span>
                        <button
                          type="button"
                          className="primary-btn"
                          disabled={updateStatus.isPending}
                          onClick={() => updateStatus.mutate({ code: t.id, status: "resolved" })}
                        >
                          Mark resolved
                        </button>
                      </div>
                    )}

                    <ThreadPanel entity="ticket" code={t.id} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
