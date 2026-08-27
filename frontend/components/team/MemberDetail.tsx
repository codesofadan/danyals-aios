"use client";

// One team member: who they are, how they are doing, what they carry.
//
// The Team screen is five tabs over the whole roster; a single person's record
// - their live metrics and their current queue - had no URL. Assign/review
// stay on the board and in the queue; this is the page a lead LINKS when the
// conversation is about one person's load.

import Link from "next/link";
import { useState } from "react";
import { TASK_STATUS_META, type Task, type TeamMemberRecord } from "@/lib/data";
import {
  useMembers,
  useRevealCredentials,
  useSetPassword,
  useTasks,
  type MemberCredentials,
} from "@/lib/hooks/team";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useToast, describeError } from "@/components/ui/Toast";
import DetailShell from "@/components/ui/DetailShell";
import QueryGuard from "@/components/ui/QueryGuard";
import DataTable from "@/components/ui/DataTable";
import EmptyState from "@/components/ui/EmptyState";

export default function MemberDetail({ memberId }: { memberId: string }) {
  const membersQ = useMembers();
  const tasksQ = useTasks();
  const member: TeamMemberRecord | undefined = membersQ.data?.find((m) => m.id === memberId);

  if (membersQ.isError) {
    return (
      <section className="card" style={{ maxWidth: 520, margin: "48px auto", textAlign: "center", padding: 28 }}>
        <div className="ct">Couldn&apos;t load the roster</div>
        <div className="cs" style={{ marginTop: 8 }}><Link href="/admin/team">Back to Team</Link></div>
      </section>
    );
  }
  if (membersQ.isLoading) {
    return <div role="status" style={{ padding: 48, textAlign: "center", color: "var(--muted)" }}>Loading member…</div>;
  }
  if (!member) {
    return (
      <section className="card" style={{ maxWidth: 520, margin: "48px auto", textAlign: "center", padding: 28 }}>
        <div className="ct">No member with this id</div>
        <div className="cs" style={{ marginTop: 8 }}><Link href="/admin/team">Back to Team</Link></div>
      </section>
    );
  }

  const mine = (tasksQ.data ?? []).filter((t: Task) => t.assignee === memberId);
  const open = mine.filter((t) => t.status !== "done");

  return (
    <DetailShell
      eyebrow="Team member"
      title={member.name}
      statusPill={<span className={`status-pill ${member.status === "active" ? "ok" : "mut"}`}>{member.status}</span>}
      facts={[
        { label: "Title", value: member.title || "—" },
        { label: "Role", value: member.role },
        { label: "Email", value: member.email },
        { label: "Joined", value: member.joined },
        { label: "On-time", value: `${member.onTime}%` },
        { label: "Utilization", value: `${member.utilization}%` },
        { label: "QA pass", value: `${member.quality}%` },
      ]}
      tabs={[
        { key: "queue", label: "Their queue", icon: "view_kanban", badge: open.length || undefined },
        { key: "delivered", label: "Delivered", icon: "task_alt" },
        { key: "access", label: "Sign-in access", icon: "key" },
      ]}
    >
      {(tab) => {
        if (tab === "access") return <AccessTab member={member} />;
        const rows = tab === "queue" ? open : mine.filter((t) => t.status === "done");
        return (
          <QueryGuard queries={[tasksQ]} label={`${member.name}'s tasks`} minHeight={140}>
            {rows.length === 0 ? (
              <EmptyState
                icon={tab === "queue" ? "inbox" : "task_alt"}
                title={tab === "queue" ? "Nothing in their queue" : "Nothing delivered yet"}
                hint={tab === "queue" ? "Every assigned task is done." : "Completed tasks will list here."}
              />
            ) : (
              <DataTable
                rows={rows}
                rowKey={(t) => t.id}
                label="tasks"
                columns={[
                  {
                    key: "code", header: "Code",
                    cell: (t) => <Link href={`/admin/tasks/${t.id}`}><strong>{t.id}</strong></Link>,
                  },
                  { key: "title", header: "Task", cell: (t) => t.title },
                  { key: "client", header: "Client", cell: (t) => t.client },
                  {
                    key: "status", header: "Status",
                    cell: (t) => (
                      <span className={`status-pill ${TASK_STATUS_META[t.status].cls}`}>
                        {TASK_STATUS_META[t.status].label}
                      </span>
                    ),
                  },
                  { key: "due", header: "Due", cell: (t) => t.due || "—" },
                ]}
              />
            )}
          </QueryGuard>
        );
      }}
    </DetailShell>
  );
}

// The single-member slice of the credential flows TeamCredentials carries for
// the whole roster (that component stays parked - it is roster-shaped). Same
// real endpoints: reveal the sealed copy, rotate the password. Nothing here is
// fetched until asked for, and a rotation confirms - it signs the person out.
function AccessTab({ member }: { member: TeamMemberRecord }) {
  const toast = useToast();
  const reveal = useRevealCredentials();
  const rotate = useSetPassword();
  const [creds, setCreds] = useState<MemberCredentials | null>(null);
  const [shown, setShown] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const doReveal = () =>
    reveal.mutate(member.id, {
      onSuccess: (c) => { setCreds(c); setShown(true); },
      onError: (e: unknown) => toast.error("Couldn't reveal credentials", describeError(e)),
    });

  return (
    <section className="card" style={{ padding: "var(--s-7)", maxWidth: 560 }}>
      <div className="ct">Sign-in access</div>
      <div className="cs" style={{ margin: "6px 0 16px" }}>
        The password is sealed server-side; revealing fetches it once and shows it only to you.
      </div>
      <div className="fld">
        <label>Username</label>
        <input readOnly value={creds?.username ?? member.email} />
      </div>
      <div className="fld" style={{ marginTop: 10 }}>
        <label>Password</label>
        <input
          readOnly
          type={shown && creds ? "text" : "password"}
          value={creds?.password ?? "••••••••••••"}
          aria-label={shown && creds ? "Password, revealed" : "Password, hidden"}
        />
        {creds && creds.password === null ? (
          <div className="cs" style={{ marginTop: 6 }}>
            No sealed copy was captured for this account — reset to set one.
          </div>
        ) : null}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        {!shown ? (
          <button type="button" className="ghostbtn" onClick={doReveal} disabled={reveal.isPending}>
            {reveal.isPending ? "Revealing…" : "Reveal password"}
          </button>
        ) : (
          <button type="button" className="ghostbtn" onClick={() => setShown(false)}>Hide</button>
        )}
        <button type="button" className="danger-btn" onClick={() => setConfirming(true)} disabled={rotate.isPending}>
          {rotate.isPending ? "Resetting…" : "Reset password"}
        </button>
      </div>
      <ConfirmDialog
        open={confirming}
        title={`Reset ${member.name}\u2019s password?`}
        body="A new password is generated and sealed; their current one stops working immediately."
        reassurance="Their account, tasks and history are untouched - only the sign-in secret changes."
        confirmLabel="Reset password"
        tone="danger"
        pending={rotate.isPending}
        onCancel={() => setConfirming(false)}
        onConfirm={() =>
          rotate.mutate(
            { userId: member.id },
            {
              onSuccess: (c) => { setCreds(c); setShown(true); setConfirming(false); toast.success("Password reset", "The new password is shown below - hand it over securely."); },
              onError: (e: unknown) => { setConfirming(false); toast.error("Couldn't reset the password", describeError(e)); },
            },
          )
        }
      />
    </section>
  );
}
