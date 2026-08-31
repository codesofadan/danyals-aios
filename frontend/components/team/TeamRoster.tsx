"use client";

import Link from "next/link";

import { useState } from "react";
import {
  ROLE_META, STATUS_META,
  type TeamMemberRecord, type TeamRole,
} from "@/lib/data";
import AddMemberWizard from "./AddMemberWizard";
import CredentialCell from "./CredentialCell";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useToast, describeError } from "@/components/ui/Toast";
import { useReactivateMember, useSuspendMember } from "@/lib/hooks/team";

export type NewMember = {
  name: string;
  email: string;
  title: string;
  role: TeamRole;
  color: string;
  template?: string; // role template label, or "Custom"
  features?: string[]; // granted accessFeatures.key[]
  username?: string; // one-time portal login shown in the wizard
  password?: string; // one-time portal password shown in the wizard
};

function RoleChip({ role }: { role: TeamRole }) {
  const c = ROLE_META[role].c;
  return <span className="role-chip" style={{ color: c, borderColor: c }}>{role}</span>;
}

function StatusDot({ status }: { status: TeamMemberRecord["status"] }) {
  // Team members are real staff, not pending invites — show provisioned ("invited")
  // accounts as Active in the roster rather than a perpetual "Invited".
  const shown = status === "invited" ? "active" : status;
  const s = STATUS_META[shown];
  return (
    <span className="status-dot">
      <span className="dot" style={{ background: s.c, boxShadow: `0 0 8px ${s.c}` }} />
      {s.label}
    </span>
  );
}

export default function TeamRoster({ members, onAdd }: { members: TeamMemberRecord[]; onAdd: (m: NewMember) => void }) {
  const [open, setOpen] = useState(false);
  const suspend = useSuspendMember();
  const reactivate = useReactivateMember();
  const toast = useToast();
  // Removing a person closes their access; it does NOT delete their record, so the
  // work they did stays attributed. The dialog says so — an operator who expects a
  // hard delete needs to know the history survives, not discover it later.
  const [removing, setRemoving] = useState<{ id: string; name: string } | null>(null);

  function handleAdd(m: NewMember) {
    onAdd(m);
    setOpen(false);
  }

  function confirmRemove() {
    if (!removing) return;
    const name = removing.name;
    suspend.mutate(
      { userId: removing.id, reason: "removed from the team" },
      {
        onSuccess: (res) => {
          toast.success(
            `${name} removed`,
            res.tokens_revoked
              ? "Access is closed and their live sessions have ended."
              : "Access is closed. The session cache did not respond, so any token they hold is refused by the database rather than the cache.",
          );
          setRemoving(null);
        },
        onError: (e: unknown) => {
          toast.error("Couldn't remove the member", describeError(e));
          setRemoving(null);
        },
      },
    );
  }

  function handleRestore(m: TeamMemberRecord) {
    reactivate.mutate(m.id, {
      onSuccess: () => toast.success(`${m.name} restored`, "They can sign in again."),
      onError: (e: unknown) => toast.error("Couldn't restore the member", describeError(e)),
    });
  }

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">groups</span>
          {members.length} members{members.length === 200 ? " (first 200)" : ""} · {members.filter((m) => m.status === "active").length} active now
        </div>
        <button className="primary-btn" onClick={() => setOpen(true)}>
          <span className="material-symbols-rounded">person_add</span>Add team member
        </button>
      </div>

      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>Member</th>
              <th>Role</th>
              <th>Status</th>
              <th className="num">Active tasks</th>
              <th className="num">Utilization</th>
              <th>Login &amp; password</th>
              <th className="num">Actions</th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.id}>
                <td>
                  <div className="mem">
                    <span className="av" style={{ background: m.c }}>{m.init}</span>
                    <div className="mem-meta">
                      <div className="mem-name"><Link href={`/admin/team/${m.id}`} title={`Open ${m.name} in full`}>{m.name}</Link></div>
                      <div className="mem-sub">{m.title} · {m.email}</div>
                    </div>
                  </div>
                </td>
                <td><RoleChip role={m.role} /></td>
                <td><StatusDot status={m.status} /></td>
                <td className="num">{m.activeTasks}</td>
                <td className="num">
                  <div className="util">
                    <div className="util-bar"><span style={{ width: `${m.utilization}%`, background: m.c }} /></div>
                    <span className="util-n">{m.utilization}%</span>
                  </div>
                </td>
                <td><CredentialCell userId={m.id} /></td>
                <td className="num">
                  {m.status === "suspended" ? (
                    <button
                      className="cd-manage"
                      onClick={() => handleRestore(m)}
                      disabled={reactivate.isPending}
                      title={`Restore ${m.name}'s access`}
                    >
                      <span className="material-symbols-rounded">restart_alt</span>Restore
                    </button>
                  ) : (
                    <button
                      className="cd-manage danger"
                      onClick={() => setRemoving({ id: m.id, name: m.name })}
                      disabled={suspend.isPending}
                      title={`Remove ${m.name} from the team`}
                    >
                      <span className="material-symbols-rounded">person_remove</span>Remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && <AddMemberWizard onClose={() => setOpen(false)} onAdd={handleAdd} />}
      <ConfirmDialog
        open={removing !== null}
        title={`Remove ${removing?.name ?? "this member"} from the team?`}
        body="Their access closes immediately and every session they have open ends. They can no longer sign in to the portal."
        reassurance="Their record and the work they did stay in the ledger — tasks they completed keep their name on them, and you can restore access later."
        confirmLabel="Remove member"
        tone="danger"
        pending={suspend.isPending}
        onCancel={() => setRemoving(null)}
        onConfirm={confirmRemove}
      />
    </div>
  );
}
