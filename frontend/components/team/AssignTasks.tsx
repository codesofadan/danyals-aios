"use client";

import { useState } from "react";
import {
  TASK_TYPES, TASK_STATUS_META,
  type Task, type TeamMemberRecord, type TaskType, type TaskPriority, type TaskStatus,
} from "@/lib/data";

export type NewTask = {
  title: string;
  client: string;
  type: TaskType;
  assignee: string;
  priority: TaskPriority;
  due: string;
};

const PRIORITIES: TaskPriority[] = ["urgent", "high", "med", "low"];
const PRIORITY_LABEL: Record<TaskPriority, string> = { urgent: "Urgent", high: "High", med: "Medium", low: "Low" };
const STATUS_FLOW: TaskStatus[] = ["todo", "in_progress", "review", "done"];

export default function AssignTasks({
  tasks, members, onAssign, onStatusChange,
}: {
  tasks: Task[];
  members: TeamMemberRecord[];
  onAssign: (t: NewTask) => void;
  onStatusChange: (id: string, s: TaskStatus) => void;
}) {
  const assignable = members.filter((m) => m.status !== "invited");
  const [title, setTitle] = useState("");
  const [client, setClient] = useState("");
  const [type, setType] = useState<TaskType>("Technical Audit");
  const [assignee, setAssignee] = useState(assignable[0]?.id ?? "");
  const [priority, setPriority] = useState<TaskPriority>("med");
  const [due, setDue] = useState("");

  const valid = title.trim().length > 2 && client.trim().length > 1 && assignee && due.trim();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!valid) return;
    onAssign({ title: title.trim(), client: client.trim(), type, assignee, priority, due: due.trim() });
    setTitle(""); setClient(""); setDue(""); setPriority("med");
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
            <input value={client} onChange={(e) => setClient(e.target.value)} placeholder="NorthPeak Dental" />
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
              <option key={m.id} value={m.id}>{m.name} — {m.title} ({m.activeTasks} active)</option>
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
            <label>Due</label>
            <input value={due} onChange={(e) => setDue(e.target.value)} placeholder="Jul 16" />
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
