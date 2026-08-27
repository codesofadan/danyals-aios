"use client";

// One task, in full - the detail page the task board never had.
//
// The board is a list with an inline proof editor; everything deeper (the
// deadline-request trail, the discussion thread, the lifecycle instants) was
// reachable only by hunting through the Team screen's tabs. The DETAIL
// archetype puts one task at one URL: identity and lifecycle in the header,
// one tab per concern, the thread where the work is discussed.

import Link from "next/link";
import type { Task } from "@/lib/data";
import { TASK_STATUS_META, type DeadlineRequest } from "@/lib/data";
import { formatWhen } from "@/lib/format";
import { useAllTasks, useSetTaskProof } from "@/lib/hooks/tasks";
import { useDecideDeadlineRequest, useTaskDeadlineRequests, useTeamMembers } from "@/lib/hooks/team";
import DetailShell from "@/components/ui/DetailShell";
import QueryGuard from "@/components/ui/QueryGuard";
import EmptyState from "@/components/ui/EmptyState";
import ThreadPanel from "@/components/threads/ThreadPanel";
import { TextField } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { useState } from "react";

export default function TaskDetail({ code }: { code: string }) {
  const tasksQ = useAllTasks();
  const membersQ = useTeamMembers();
  const requestsQ = useTaskDeadlineRequests(code);
  const decide = useDecideDeadlineRequest();
  const setProof = useSetTaskProof();
  const toast = useToast();
  const [proofDraft, setProofDraft] = useState<string | null>(null);

  const task: Task | undefined = tasksQ.data?.find((t) => t.id === code);

  if (tasksQ.isError) {
    return (
      <section className="card" style={{ maxWidth: 520, margin: "48px auto", textAlign: "center", padding: 28 }}>
        <div className="ct">Couldn&apos;t load task {code}</div>
        <div className="cs" style={{ marginTop: 8 }}><Link href="/admin/tasks">Back to Tasks</Link></div>
      </section>
    );
  }
  if (tasksQ.isLoading) {
    return <div role="status" style={{ padding: 48, textAlign: "center", color: "var(--muted)" }}>Loading {code}…</div>;
  }
  if (!task) {
    return (
      <section className="card" style={{ maxWidth: 520, margin: "48px auto", textAlign: "center", padding: 28 }}>
        <div className="ct">No task {code}</div>
        <div className="cs" style={{ marginTop: 8 }}>
          It may have been deleted, or the code is mistyped. <Link href="/admin/tasks">Back to Tasks</Link>.
        </div>
      </section>
    );
  }

  const meta = TASK_STATUS_META[task.status];
  const assignee =
    (membersQ.data ?? []).find((m) => m.id === task.assignee)?.name ?? task.assignee;
  const requests: DeadlineRequest[] = requestsQ.data ?? [];
  const pending = requests.filter((r) => r.status === "pending");

  return (
    <DetailShell
      eyebrow="Task"
      title={task.title}
      statusPill={<span className={`status-pill ${meta.cls}`}>{meta.label}</span>}
      facts={[
        { label: "Client", value: task.client },
        { label: "Assignee", value: assignee },
        { label: "Priority", value: task.priority },
        { label: "Due", value: task.due || "—" },
        { label: "Started", value: formatWhen(task.startedAt) || "—" },
        { label: "Completed", value: formatWhen(task.completedAt) || "—" },
      ]}
      actions={
        task.proofUrl ? (
          <a className="ghostbtn" href={task.proofUrl} target="_blank" rel="noopener noreferrer">
            <span className="material-symbols-rounded">open_in_new</span>Open proof
          </a>
        ) : undefined
      }
      tabs={[
        { key: "thread", label: "Discussion", icon: "forum" },
        { key: "deadline", label: "Deadline requests", icon: "schedule", badge: pending.length || undefined },
        { key: "proof", label: "Proof", icon: "verified" },
      ]}
    >
      {(tab) => {
        if (tab === "deadline") {
          return (
            <QueryGuard queries={[requestsQ]} label="deadline requests" minHeight={120}>
              {requests.length === 0 ? (
                <EmptyState icon="schedule" title="No deadline requests" hint="The assignee has not asked to move this task's due date." />
              ) : (
                <div style={{ display: "grid", gap: "var(--s-4)", maxWidth: 640 }}>
                  {requests.map((r) => (
                    <section key={r.id} className="card" style={{ padding: "var(--s-6)" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--s-6)", flexWrap: "wrap" }}>
                        <div>
                          <div style={{ fontWeight: 700, fontSize: "var(--fs-sm)" }}>
                            Move due date to {r.requestedDueDate}
                            <span className="cs" style={{ marginLeft: 6 }}>requested by {r.requestedBy}</span>
                          </div>
                          <div className="cs" style={{ marginTop: 4 }}>{r.reason || "No reason given."}</div>
                        </div>
                        {r.status === "pending" ? (
                          <div style={{ display: "flex", gap: "var(--s-3)" }}>
                            <button
                              type="button" className="primary-btn"
                              disabled={decide.isPending}
                              onClick={() => decide.mutate({ code, requestId: r.id, action: "approve" }, {
                                onSuccess: () => toast.success(`Due date moved to ${r.requestedDueDate}`),
                                onError: (e: unknown) => toast.fromError("Couldn't approve the request", e),
                              })}
                            >Approve</button>
                            <button
                              type="button" className="ghostbtn"
                              disabled={decide.isPending}
                              onClick={() => decide.mutate({ code, requestId: r.id, action: "reject" }, {
                                onSuccess: () => toast.info("Request rejected — the due date stands"),
                                onError: (e: unknown) => toast.fromError("Couldn't reject the request", e),
                              })}
                            >Reject</button>
                          </div>
                        ) : (
                          <span className={`status-pill ${r.status === "approved" ? "ok" : "mut"}`}>{r.status}</span>
                        )}
                      </div>
                    </section>
                  ))}
                </div>
              )}
            </QueryGuard>
          );
        }
        if (tab === "proof") {
          return (
            <section className="card" style={{ padding: "var(--s-7)", maxWidth: 560 }}>
              <TextField
                label="Proof of completion"
                hint="The published URL or delivered report this task produced. Leads can set or clear it; blank clears."
                value={proofDraft ?? task.proofUrl}
                onChange={(e) => setProofDraft(e.target.value)}
                placeholder="https://…"
                inputMode="url"
              />
              <div style={{ marginTop: "var(--s-5)", display: "flex", gap: "var(--s-3)" }}>
                <button
                  type="button" className="primary-btn"
                  disabled={setProof.isPending || proofDraft === null || proofDraft === task.proofUrl}
                  onClick={() => setProof.mutate({ code, proofUrl: (proofDraft ?? "").trim() }, {
                    onSuccess: () => { setProofDraft(null); toast.success(`Proof saved for ${code}`); },
                    onError: (e: unknown) => toast.fromError(`Couldn't save proof for ${code}`, e),
                  })}
                >{setProof.isPending ? "Saving…" : "Save proof"}</button>
                {proofDraft !== null && (
                  <button type="button" className="ghostbtn" onClick={() => setProofDraft(null)}>Discard</button>
                )}
              </div>
            </section>
          );
        }
        return <ThreadPanel entity="task" code={code} clientLinked={Boolean(task.client)} />;
      }}
    </DetailShell>
  );
}
