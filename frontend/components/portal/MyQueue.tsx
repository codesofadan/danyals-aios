"use client";

import { useState } from "react";
import {
  TASK_STATUS_META, dueInfo,
  type Task, type TaskStatus,
} from "@/lib/data";
import { cardAction } from "@/lib/portal";

const COLUMNS: { key: TaskStatus; label: string; icon: string }[] = [
  { key: "todo", label: "To do", icon: "radio_button_unchecked" },
  { key: "in_progress", label: "In progress", icon: "bolt" },
  { key: "review", label: "In review", icon: "how_to_reg" },
  { key: "done", label: "Delivered", icon: "task_alt" },
];

const PRIORITY_LABEL: Record<Task["priority"], string> = { urgent: "Urgent", high: "High", med: "Medium", low: "Low" };

function Card({ t, onAdvance }: { t: Task; onAdvance: (id: string) => void }) {
  const due = dueInfo(t.due);
  const action = cardAction(t);
  return (
    <div className="pq-card">
      <span className={`prio-bar ${t.priority}`} title={`${PRIORITY_LABEL[t.priority]} priority`} />
      <div className="pq-card-body">
        <div className="pq-card-title">{t.title}</div>
        <div className="pq-card-meta">
          <span className="task-id">{t.id}</span>
          <span className="dot-sep">·</span>
          <span>{t.client}</span>
        </div>
        <div className="pq-card-foot">
          <span className="task-type">{t.type}</span>
          {t.status !== "done" ? (
            <span className={`pq-due ${due.tone}`}>
              <span className="material-symbols-rounded">schedule</span>{due.label}
            </span>
          ) : (
            <span className="pq-due ok"><span className="material-symbols-rounded">check_circle</span>Delivered</span>
          )}
        </div>
        {action && (
          <button className="pq-action" onClick={() => onAdvance(t.id)}>
            <span className="material-symbols-rounded">{action.icon}</span>{action.label}
          </button>
        )}
        {t.status === "review" && (
          <div className="pq-waiting">
            <span className="material-symbols-rounded">hourglass_top</span>Awaiting sign-off
          </div>
        )}
      </div>
    </div>
  );
}

export default function MyQueue({ tasks, onAdvance }: { tasks: Task[]; onAdvance: (id: string) => void }) {
  const [prio, setPrio] = useState<"all" | "urgent">("all");
  const filtered = prio === "all" ? tasks : tasks.filter((t) => t.priority === "urgent" || t.priority === "high");
  const open = tasks.filter((t) => t.status !== "done").length;

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">view_kanban</span>
          {open} open · {tasks.length} total — drag-free, just tap to advance
        </div>
        <div className="seg" role="tablist" aria-label="Filter queue">
          <button className={prio === "all" ? "on" : undefined} onClick={() => setPrio("all")}>All</button>
          <button className={prio === "urgent" ? "on" : undefined} onClick={() => setPrio("urgent")}>High priority</button>
        </div>
      </div>

      {tasks.length === 0 ? (
        <div className="pt-empty">
          <span className="material-symbols-rounded">inbox</span>
          <div className="pt-empty-t">Nothing assigned yet</div>
          <div className="pt-empty-s">When an admin assigns you a task, it lands here.</div>
        </div>
      ) : (
        <div className="pq-board">
          {COLUMNS.map((col) => {
            const items = filtered.filter((t) => t.status === col.key);
            const meta = TASK_STATUS_META[col.key];
            return (
              <div className="pq-col" key={col.key}>
                <div className={`pq-col-h ${meta.cls}`}>
                  <span className="material-symbols-rounded">{col.icon}</span>
                  <span className="pq-col-l">{col.label}</span>
                  <span className="pq-col-n">{items.length}</span>
                </div>
                <div className="pq-col-list">
                  {items.map((t) => <Card key={t.id} t={t} onAdvance={onAdvance} />)}
                  {items.length === 0 && <div className="pq-col-empty">—</div>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
