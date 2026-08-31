"use client";

// ============================================================
// AIOS · ConvertToTask — turning a client's request into assigned work.
//
// THE LOOP THIS CLOSES. A client raised a request and it stopped there: a row, an
// email to the operator inbox, and a widget. There was no path from a request to the
// team's queue at all, so whether it became work depended on somebody remembering.
//
// SHARED, not copied. It is reached from two places - the Clients page feed, where a
// request is first read, and the Task Manager's Client Requests view, where the work
// is managed. Two implementations of "convert this request" would be two chances for
// the tenant, the title or the priority to be resolved differently.
// ============================================================

import { useState } from "react";
import { useConvertTicketToTask } from "@/lib/hooks/clients";
import { useTeamMembers } from "@/lib/hooks/team";
import { TASK_TYPES, type TaskType, type Ticket } from "@/lib/data";

// Turn a request into work somebody is assigned.
//
// THE LOOP THIS CLOSES. A client raised a request and it stopped here: a row, an
// email to the operator inbox, and this widget. There was no path from a request to
// the team's queue at all, so whether it became work depended on somebody
// remembering. Now it is one action, and the request records which task it became.
export default function ConvertToTask({ ticket }: { ticket: Ticket }) {
  const [open, setOpen] = useState(false);
  const [assignee, setAssignee] = useState("");
  const [type, setType] = useState<TaskType>("Technical Audit");
  const membersQ = useTeamMembers();
  const convert = useConvertTicketToTask();

  const members = membersQ.data ?? [];
  const chosen = assignee || members[0]?.id || "";

  if (!open) {
    return (
      <button type="button" className="tk-convert" onClick={() => setOpen(true)}>
        <span className="material-symbols-rounded">add_task</span>Create task from this request
      </button>
    );
  }

  return (
    <div className="tk-convert-form">
      <label className="tk-convert-fld">
        <span>Assign to</span>
        <select value={chosen} onChange={(e) => setAssignee(e.target.value)} disabled={membersQ.isLoading}>
          {members.map((m) => (
            <option key={m.id} value={m.id}>{m.name}</option>
          ))}
        </select>
      </label>
      <label className="tk-convert-fld">
        <span>Type</span>
        <select value={type} onChange={(e) => setType(e.target.value as TaskType)}>
          {TASK_TYPES.map((tt) => (
            <option key={tt} value={tt}>{tt}</option>
          ))}
        </select>
      </label>
      <div className="tk-convert-actions">
        <button type="button" className="ghostbtn" onClick={() => setOpen(false)}>Cancel</button>
        <button
          type="button"
          className="primary-btn"
          disabled={!chosen || convert.isPending}
          onClick={() =>
            convert.mutate(
              { code: ticket.id, assignee_id: chosen, type, priority: ticket.priority },
              { onSuccess: () => setOpen(false) },
            )
          }
        >
          <span className="material-symbols-rounded">add_task</span>
          {convert.isPending ? "Creating…" : "Create task"}
        </button>
      </div>
      {/* The title is intentionally not editable here: it defaults to the request's own
          subject server-side, and retyping it is how a task and its request drift apart. */}
      <div className="tk-convert-hint">
        Titled &ldquo;{ticket.subject}&rdquo;, for {ticket.client}. The request will record which task it became.
      </div>
      {convert.error instanceof Error && (
        <div className="tk-triage-err" role="alert">Couldn&apos;t create the task — {convert.error.message}</div>
      )}
    </div>
  );
}
