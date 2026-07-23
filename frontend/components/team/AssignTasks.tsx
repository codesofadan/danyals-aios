"use client";

import { useState } from "react";
import {
  TASK_TYPES, TASK_STATUS_META,
  type Task, type TeamMemberRecord, type ClientRecord,
  type TaskType, type TaskPriority, type TaskStatus,
} from "@/lib/data";

export type NewTask = {
  title: string;
  client_id: string;
  type: TaskType;
  assignee: string; // assignee user id
  priority: TaskPriority;
  due: string; // ISO YYYY-MM-DD, or "" when unset
};

const PRIORITIES: TaskPriority[] = ["urgent", "high", "med", "low"];
const PRIORITY_LABEL: Record<TaskPriority, string> = { urgent: "Urgent", high: "High", med: "Medium", low: "Low" };
const STATUS_FLOW: TaskStatus[] = ["todo", "in_progress", "review", "done"];

export default function AssignTasks({
  tasks, members, clients, onAssign, onStatusChange,
}: {
  tasks: Task[];
  members: TeamMemberRecord[];
  clients: ClientRecord[];
  onAssign: (t: NewTask) => void;
  onStatusChange: (id: string, s: TaskStatus) => void;
}) {
  // Every eligible staff member is assignable — the backend accepts any non-client
  // assignee, including a member who has been invited but has not yet signed in for
  // the first time. Hiding invited members here is exactly what made newly-added
  // staff vanish from this picker, so they are kept (and tagged) instead.
  const assignable = members;
  const [title, setTitle] = useState("");
  const [clientId, setClientId] = useState("");
  const [type, setType] = useState<TaskType>("Technical Audit");
  const [assignee, setAssignee] = useState(assignable[0]?.id ?? "");
  const [priority, setPriority] = useState<TaskPriority>("med");
  const [due, setDue] = useState("");

  // The backend needs a real client_id (it validates the client exists), so the
  // Client field is a picker over the live roster, not free text.
  const effectiveClientId = clientId || clients[0]?.id || "";
  const valid = title.trim().length > 2 && !!effectiveClientId && !!assignee;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!valid) return;
    onAssign({ title: title.trim(), client_id: effectiveClientId, type, assignee, priority, due });
    setTitle(""); setDue(""); setPriority("med");
  }

  const memberById = new Map(members.map((m) => [m.id, m] as const));

  return (
    <div className="panel-in assign-grid">
      <form className="assign-form" onSubmit={submit}>
        <div className="af-t">New assignment</div>
        <div className="fld">
          <label>Task</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Technical crawl + CWV pass" />
        </div>
        <div className="fld-row">
          <div className="fld">
            <label>Client</label>
            <select
              value={effectiveClientId}
              onChange={(e) => setClientId(e.target.value)}
              disabled={clients.length === 0}
            >
              {clients.length === 0 ? (
                <option value="">No clients yet</option>
              ) : (
                clients.map((c) => <option key={c.id} value={c.id}>{c.cn}</option>)
              )}
            </select>
          </div>
          <div className="fld">
            <label>Type</label>
            <select value={type} onChange={(e) => setType(e.target.value as TaskType)}>
              {TASK_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        </div>
        <div className="fld">
          <label>Assign to</label>
          <select value={assignee} onChange={(e) => setAssignee(e.target.value)}>
            {assignable.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} — {m.title} ({m.activeTasks} active){m.status === "invited" ? " · invited" : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="fld-row">
          <div className="fld">
            <label>Priority</label>
            <div className="prio-pick">
              {PRIORITIES.map((p) => (
                <button type="button" key={p} className={priority === p ? `prio-opt ${p} on` : `prio-opt ${p}`} onClick={() => setPriority(p)}>
                  {PRIORITY_LABEL[p]}
                </button>
              ))}
            </div>
          </div>
          <div className="fld">
            <label>Due <span style={{ color: "var(--muted)" }}>(optional)</span></label>
            <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </div>
        </div>
        <button type="submit" className="primary-btn wide" disabled={!valid}>
          <span className="material-symbols-rounded">assignment_turned_in</span>Assign task
        </button>
      </form>

      <div className="board">
        <div className="board-h">
          <span>Task board</span>
          <span className="board-c">{tasks.filter((t) => t.status !== "done").length} open · {tasks.length} total</span>
        </div>
        <div className="board-list">
          {tasks.map((t) => {
            const m = memberById.get(t.assignee);
            const sm = TASK_STATUS_META[t.status];
            return (
              <div className="task" key={t.id}>
                <span className={`prio-bar ${t.priority}`} title={`${PRIORITY_LABEL[t.priority]} priority`} />
                <div className="task-main">
                  <div className="task-title">{t.title}</div>
                  <div className="task-meta">
                    <span className="task-id">{t.id}</span>
                    <span className="dot-sep">·</span>
                    <span>{t.client}</span>
                    <span className="task-type">{t.type}</span>
                  </div>
                </div>
                <div className="task-assignee">
                  {m ? <span className="av xs" style={{ background: m.c }}>{m.init}</span> : null}
                  <span className="task-due">Due {t.due}</span>
                </div>
                <select
                  className={`task-status ${sm.cls}`}
                  value={t.status}
                  onChange={(e) => onStatusChange(t.id, e.target.value as TaskStatus)}
                  aria-label={`Status for ${t.id}`}
                >
                  {STATUS_FLOW.map((s) => <option key={s} value={s}>{TASK_STATUS_META[s].label}</option>)}
                </select>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
