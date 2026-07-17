"use client";

import { Fragment, useState } from "react";
import {
  ROLE_ORDER, ROLE_META, STATUS_META,
  type TeamRole,
} from "@/lib/data";
import { useMembers } from "@/lib/hooks/team";
import { Switch, PasswordField, generatePassword } from "./controls";

type LogFn = (action: string, target: string, meta?: string) => void;
type Row = { pass: string; twoFA: boolean; mustReset: boolean; role: TeamRole; active: boolean };

// Members invited during the demo have no seeded credential yet — surface a
// safe placeholder that prompts a first-sign-in reset.
const NEW_CRED = { pass: "Set at first sign-in", twoFA: false, mustReset: true, lastChanged: "—" };

export default function TeamCredentials({ onLog }: { onLog: LogFn }) {
  // The roster is live (GET /admin/users). MISMATCH (recorded): the backend NEVER
  // persists or reveals a member's password (the real credential flow is the
  // Add-Member invite's one-time password, shown once). There is no credential
  // read/reset endpoint, so the per-member password / 2FA / reset here are LOCAL
  // only — real UUID ids never match the demo `teamCredentials` seed, so every row
  // falls back to the "set at first sign-in" placeholder (an honest empty state).
  const membersQ = useMembers();
  const members = membersQ.data ?? [];
  const [rows, setRows] = useState<Record<string, Row>>({});
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [savedId, setSavedId] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  // Merge onto the row currently on screen (the stored edit OR the render fallback)
  // so an edit made before `rows` was ever seeded keeps every other field intact.
  function edit(id: string, cur: Row, patch: Partial<Row>) {
    setRows((prev) => ({ ...prev, [id]: { ...cur, ...prev[id], ...patch } }));
    setDirty((prev) => ({ ...prev, [id]: true }));
  }

  function save(id: string, name: string) {
    setDirty((prev) => ({ ...prev, [id]: false }));
    setOpenId(null);
    setSavedId(id);
    setTimeout(() => setSavedId((s) => (s === id ? null : s)), 1600);
    onLog("updated credentials & access for", name, "Team access");
  }

  function resetPassword(id: string, cur: Row, name: string) {
    edit(id, cur, { pass: generatePassword(), mustReset: true });
    onLog("reset the password for", name, "Team access");
  }

  const muted: React.CSSProperties = { padding: "2.5rem 1rem", textAlign: "center", color: "var(--muted)" };
  if (membersQ.isLoading && members.length === 0) return <div className="panel-in"><div style={muted}>Loading team…</div></div>;
  if (membersQ.isError && members.length === 0)
    return <div className="panel-in"><div style={muted}>Couldn&apos;t load the team — {(membersQ.error as Error)?.message ?? "try again"}.</div></div>;

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">manage_accounts</span>
          {members.length} members · reset passwords, change roles &amp; manage access
        </div>
        <div className="sec-note inline">
          <span className="material-symbols-rounded">shield</span>
          Role changes take effect immediately across the platform.
        </div>
      </div>

      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>Member</th>
              <th>Role</th>
              <th>2FA</th>
              <th>Access</th>
              <th className="ta-r">Password</th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => {
              const r = rows[m.id] ?? { pass: NEW_CRED.pass, twoFA: false, mustReset: true, role: m.role, active: true };
              const isOwner = m.role === "Owner";
              const open = openId === m.id;
              const status = STATUS_META[m.status];
              return (
                <Fragment key={m.id}>
                  <tr>
                    <td>
                      <div className="mem">
                        <span className="av" style={{ background: m.c }}>{m.init}</span>
                        <div className="mem-meta">
                          <div className="mem-name">{m.name}</div>
                          <div className="mem-sub">{m.title} · {m.email}</div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <select
                        className="mini-select"
                        value={r.role}
                        disabled={isOwner}
                        style={{ color: ROLE_META[r.role].c, borderColor: ROLE_META[r.role].c }}
                        onChange={(e) => edit(m.id, r, { role: e.target.value as TeamRole })}
                        aria-label={`Role for ${m.name}`}
                      >
                        {ROLE_ORDER.map((role) => <option key={role} value={role}>{role}</option>)}
                      </select>
                    </td>
                    <td>
                      <Switch checked={r.twoFA} onChange={(v) => edit(m.id, r, { twoFA: v })} disabled={isOwner} label={`2FA for ${m.name}`} />
                    </td>
                    <td>
                      {isOwner ? (
                        <span className="status-dot"><span className="dot" style={{ background: status.c, boxShadow: `0 0 8px ${status.c}` }} />Owner</span>
                      ) : (
                        <label className="access-toggle">
                          <Switch checked={r.active} onChange={(v) => edit(m.id, r, { active: v })} label={`Account access for ${m.name}`} />
                          <span className={r.active ? "acc-on" : "acc-off"}>{r.active ? "Enabled" : "Disabled"}</span>
                        </label>
                      )}
                    </td>
                    <td className="ta-r">
                      <div className="row-actions">
                        {savedId === m.id && <span className="saved-flash sm"><span className="material-symbols-rounded">check_circle</span></span>}
                        {r.mustReset && <span className="pill-tag warn sm" title="User must set a new password at next sign-in"><span className="material-symbols-rounded">priority_high</span>Reset</span>}
                        <button className="mini-btn" onClick={() => setOpenId(open ? null : m.id)} aria-expanded={open}>
                          <span className="material-symbols-rounded">{open ? "expand_less" : "key"}</span>Password
                        </button>
                      </div>
                    </td>
                  </tr>
                  {open && (
                    <tr className="tc-drawer-row">
                      <td colSpan={5}>
                        <div className="tc-drawer">
                          <div className="fld tc-drawer-pass">
                            <label htmlFor={`tp-${m.id}`}>Set / view password for {m.name}</label>
                            <PasswordField id={`tp-${m.id}`} value={r.pass} onChange={(v) => edit(m.id, r, { pass: v })} />
                          </div>
                          <label className="tc-drawer-check">
                            <input type="checkbox" checked={r.mustReset} onChange={(e) => edit(m.id, r, { mustReset: e.target.checked })} />
                            Require change at next sign-in
                          </label>
                          <div className="tc-drawer-actions">
                            <button className="ghostbtn" onClick={() => resetPassword(m.id, r, m.name)}>
                              <span className="material-symbols-rounded">autorenew</span>Generate &amp; force reset
                            </button>
                            <button className="primary-btn sm" disabled={!dirty[m.id]} onClick={() => save(m.id, m.name)}>
                              <span className="material-symbols-rounded">save</span>Save
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
