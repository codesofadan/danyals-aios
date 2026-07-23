"use client";

import { useState } from "react";
import {
  ROLE_META, STATUS_META,
  type TeamMemberRecord, type TeamRole,
} from "@/lib/data";
import AddMemberWizard from "./AddMemberWizard";
import CredentialCell from "./CredentialCell";

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

  function handleAdd(m: NewMember) {
    onAdd(m);
    setOpen(false);
  }

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">groups</span>
          {members.length} members · {members.filter((m) => m.status === "active").length} active now
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
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.id}>
                <td>
                  <div className="mem">
                    <span className="av" style={{ background: m.c }}>{m.init}</span>
                    <div className="mem-meta">
                      <div className="mem-name">{m.name}</div>
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
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && <AddMemberWizard onClose={() => setOpen(false)} onAdd={handleAdd} />}
    </div>
  );
}
