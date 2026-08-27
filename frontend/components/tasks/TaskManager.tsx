"use client";

import Link from "next/link";

import { Fragment, useMemo, useState } from "react";
import ThreadPanel from "@/components/threads/ThreadPanel";
import { useToast } from "@/components/ui/Toast";
import { useAllTasks, useSetTaskProof } from "@/lib/hooks/tasks";
import { useTeamMembers } from "@/lib/hooks/team";
import {
  TASK_STATUS_META,
  type Task,
  type TaskStatus,
  type TaskPriority,
  type TeamMemberRecord,
} from "@/lib/data";

// The lifecycle order, drawn as a 4-step progress bar per task.
const STEP_ORDER: TaskStatus[] = ["todo", "in_progress", "review", "done"];
// Segment fill colour per current status (CSS tokens; done=green, review=amber…).
const STATUS_COLOR: Record<TaskStatus, string> = {
  todo: "var(--muted)",
  in_progress: "var(--c4)",
  review: "var(--warn)",
  done: "var(--ok)",
};
const PRIORITY_LABEL: Record<TaskPriority, string> = {
  urgent: "Urgent",
  high: "High",
  med: "Medium",
  low: "Low",
};

type StatusFilter = TaskStatus | "all";
type AssigneeFilter = string; // member id, "" (unassigned) or "all"

function LifecycleBar({ status }: { status: TaskStatus }) {
  const step = STEP_ORDER.indexOf(status);
  const meta = TASK_STATUS_META[status];
  return (
    <div className="tm-progress-cell">
      <span className={`status-pill ${meta.cls}`}>{meta.label}</span>
      <div className="tm-progress" aria-label={`Progress: ${meta.label}`}>
        {STEP_ORDER.map((s, i) => (
          <span
            key={s}
            className="tm-step"
            style={i <= step ? { background: STATUS_COLOR[status] } : undefined}
          />
        ))}
      </div>
    </div>
  );
}

/** The proof-link cell: an "Open proof" link when set, plus a lead's inline add/edit. */
function ProofCell({ task }: { task: Task }) {
  const setProof = useSetTaskProof();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(task.proofUrl);

  function save() {
    const value = draft.trim();
    if (value === task.proofUrl) {
      setEditing(false);
      return;
    }
    setProof.mutate(
      { code: task.id, proofUrl: value },
      {
        onSuccess: () => {
          setEditing(false);
          toast.success(`Proof saved for ${task.id}`);
        },
        // "Save failed" told the operator nothing: not whether it was a
        // permission problem, a bad URL or a dropped connection. The API's own
        // reason travels now, and an error toast does not auto-dismiss.
        onError: (err) => toast.fromError(`Couldn't save proof for ${task.id}`, err),
      },
    );
  }

  if (editing) {
    return (
      <div className="tm-proof">
        <div className="tm-proof-edit">
          <input
            type="url"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="https://…"
            aria-label={`Proof link for ${task.id}`}
            onKeyDown={(e) => {
              if (e.key === "Enter") save();
              if (e.key === "Escape") {
                setDraft(task.proofUrl);
                setEditing(false);
              }
            }}
          />
          <button
            type="button"
            className="tm-iconbtn save"
            onClick={save}
            disabled={setProof.isPending}
            title="Save proof link"
            aria-label="Save proof link"
          >
            <span className="material-symbols-rounded">check</span>
          </button>
          <button
            type="button"
            className="tm-iconbtn"
            onClick={() => {
              setDraft(task.proofUrl);
              setEditing(false);
            }}
            title="Cancel"
            aria-label="Cancel"
          >
            <span className="material-symbols-rounded">close</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="tm-proof">
      {task.proofUrl ? (
        <a className="tm-proof-link" href={task.proofUrl} target="_blank" rel="noreferrer" title={task.proofUrl}>
          <span className="material-symbols-rounded">open_in_new</span>
          Open proof
        </a>
      ) : (
        <span className="tm-proof-none">No proof</span>
      )}
      <button
        type="button"
        className="tm-iconbtn"
        onClick={() => {
          setDraft(task.proofUrl);
          setEditing(true);
        }}
        title={task.proofUrl ? "Edit proof link" : "Add proof link"}
        aria-label={task.proofUrl ? "Edit proof link" : "Add proof link"}
      >
        <span className="material-symbols-rounded">{task.proofUrl ? "edit" : "add_link"}</span>
      </button>
    </div>
  );
}

function AssigneeCell({ member, id }: { member: TeamMemberRecord | undefined; id: string }) {
  if (!id) return <span className="tm-assignee none">Unassigned</span>;
  if (!member) {
    return (
      <span className="tm-assignee">
        <span className="av" style={{ background: "var(--muted)" }}>?</span>
        <span>{id}</span>
      </span>
    );
  }
  return (
    <span className="tm-assignee">
      <span className="av" style={{ background: member.c }}>{member.init}</span>
      <span>{member.name}</span>
    </span>
  );
}

export default function TaskManager() {
  const [discussId, setDiscussId] = useState<string | null>(null);
  const tasksQ = useAllTasks();
  const membersQ = useTeamMembers();

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [assigneeFilter, setAssigneeFilter] = useState<AssigneeFilter>("all");

  const tasks = useMemo(() => tasksQ.data ?? [], [tasksQ.data]);
  const members = useMemo(() => membersQ.data ?? [], [membersQ.data]);
  const memberById = useMemo(
    () => new Map(members.map((m) => [m.id, m] as const)),
    [members],
  );

  // Assignee options: every member that owns a task, plus an Unassigned bucket if any.
  const assigneeOptions = useMemo(() => {
    const ids = new Set(tasks.map((t) => t.assignee));
    const opts = members.filter((m) => ids.has(m.id));
    return { opts, hasUnassigned: ids.has("") };
  }, [tasks, members]);

  const filtered = useMemo(
    () =>
      tasks.filter((t) => {
        if (statusFilter !== "all" && t.status !== statusFilter) return false;
        if (assigneeFilter !== "all" && t.assignee !== assigneeFilter) return false;
        return true;
      }),
    [tasks, statusFilter, assigneeFilter],
  );

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">All team tasks</div>
          <div className="cs">
            Every task assigned across the team — live status, owner and the proof-of-completion link.
          </div>
        </div>
      </div>

      <div className="tm-filters">
        <label className="tm-filter">
          Status
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}>
            <option value="all">All statuses</option>
            {STEP_ORDER.map((s) => (
              <option key={s} value={s}>{TASK_STATUS_META[s].label}</option>
            ))}
          </select>
        </label>
        <label className="tm-filter">
          Assignee
          <select value={assigneeFilter} onChange={(e) => setAssigneeFilter(e.target.value)}>
            <option value="all">Everyone</option>
            {assigneeOptions.opts.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
            {assigneeOptions.hasUnassigned && <option value="">Unassigned</option>}
          </select>
        </label>
        <span className="tm-filter-count">
          {filtered.length} of {tasks.length} {tasks.length === 1 ? "task" : "tasks"}
        </span>
      </div>

      {tasksQ.isLoading ? (
        <div className="tm-muted">Loading tasks…</div>
      ) : tasksQ.isError ? (
        <div className="tm-muted">Could not load tasks. Please retry.</div>
      ) : tasks.length === 0 ? (
        <div className="tm-muted">No tasks yet. Assign work from Team Management and it appears here.</div>
      ) : filtered.length === 0 ? (
        <div className="tm-muted">No tasks match these filters.</div>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Job</th>
                <th>Task</th>
                <th>Client</th>
                <th>Type</th>
                <th>Assignee</th>
                <th>Priority</th>
                <th>Progress</th>
                <th>Due</th>
                <th>Proof</th>
                <th aria-label="Discussion" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => (
                <Fragment key={t.id}>
                <tr>
                  <td><Link href={`/admin/tasks/${t.id}`} title={`Open ${t.id} in full`}><strong>{t.id}</strong></Link></td>
                  <td>{t.title}</td>
                  <td>{t.client || "—"}</td>
                  <td>{t.type}</td>
                  <td><AssigneeCell member={memberById.get(t.assignee)} id={t.assignee} /></td>
                  <td><span className={`tm-prio ${t.priority}`}>{PRIORITY_LABEL[t.priority]}</span></td>
                  <td><LifecycleBar status={t.status} /></td>
                  <td>{t.due || "—"}</td>
                  <td><ProofCell task={t} /></td>
                  <td>
                    <button
                      type="button"
                      className="tm-iconbtn"
                      onClick={() => setDiscussId((cur) => (cur === t.id ? null : t.id))}
                      title={discussId === t.id ? "Hide discussion" : `Discuss ${t.id}`}
                      aria-label={discussId === t.id ? "Hide discussion" : `Discuss ${t.id}`}
                      aria-expanded={discussId === t.id}
                    >
                      <span className="material-symbols-rounded">forum</span>
                    </button>
                  </td>
                </tr>
                {discussId === t.id && (
                  <tr className="tm-thread-row">
                    <td colSpan={10}>
                      {/* Where a lead SEES what the team asked. Without this the queue
                          side of the conversation would have no counterpart and a
                          specialist's question would go nowhere. */}
                      <ThreadPanel entity="task" code={t.id} clientLinked={!!t.client} />
                    </td>
                  </tr>
                )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
