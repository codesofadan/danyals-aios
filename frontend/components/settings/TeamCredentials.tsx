"use client";

import { Fragment, useState } from "react";
import { ROLE_META } from "@/lib/data";
import { useMembers, useRevealCredentials, useSetPassword, type MemberCredentials } from "@/lib/hooks/team";
import { PasswordField } from "./controls";

type LogFn = (action: string, target: string, meta?: string) => void;

export default function TeamCredentials({ onLog }: { onLog: LogFn }) {
  // The roster is live (GET /admin/users). Passwords are sealed server-side
  // (AES-256-GCM) and handled through REAL endpoints only:
  //   • reveal  → GET  /admin/users/{id}/credentials  (useRevealCredentials)
  //   • rotate  → POST /admin/users/{id}/password      (useSetPassword)
  // There is deliberately no role-change / enable-disable control here — the
  // backend exposes no such route, so we never render a switch that persists nothing.
  const membersQ = useMembers();
  const members = membersQ.data ?? [];
  const reveal = useRevealCredentials();
  const setPw = useSetPassword();

  const [openId, setOpenId] = useState<string | null>(null);
  const [creds, setCreds] = useState<Record<string, MemberCredentials>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [err, setErr] = useState<{ id: string; msg: string } | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);

  function doReveal(id: string) {
    setBusyId(id);
    setErr(null);
    reveal.mutate(id, {
      onSuccess: (c) => { setCreds((p) => ({ ...p, [id]: c })); setBusyId(null); },
      onError: (e) => { setErr({ id, msg: (e as Error)?.message ?? "Couldn't reveal credentials." }); setBusyId(null); },
    });
  }

  function doReset(id: string, name: string) {
    setBusyId(id);
    setErr(null);
    setPw.mutate(
      { userId: id },
      {
        onSuccess: (c) => {
          setCreds((p) => ({ ...p, [id]: c }));
          setBusyId(null);
          setSavedId(id);
          setTimeout(() => setSavedId((s) => (s === id ? null : s)), 1800);
          onLog("reset the sign-in password for", name, "Team access");
        },
        onError: (e) => { setErr({ id, msg: (e as Error)?.message ?? "Couldn't reset the password." }); setBusyId(null); },
      },
    );
  }

  function toggleDrawer(id: string) {
    const next = openId === id ? null : id;
    setOpenId(next);
    if (next && !creds[id]) doReveal(id); // auto-reveal the sealed copy on open
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
          {members.length} members · reveal or reset a member&apos;s sign-in password
        </div>
        <div className="sec-note inline">
          <span className="material-symbols-rounded">shield</span>
          Passwords are sealed (AES-256-GCM) and revealed on demand. A reset generates a new one to share with the member.
        </div>
      </div>

      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>Member</th>
              <th>Role</th>
              <th className="ta-r">Sign-in password</th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => {
              const open = openId === m.id;
              const c = creds[m.id];
              const busy = busyId === m.id;
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
                      <span className="role-chip" style={{ color: ROLE_META[m.role].c, borderColor: ROLE_META[m.role].c }}>{m.role}</span>
                    </td>
                    <td className="ta-r">
                      <div className="row-actions">
                        {savedId === m.id && <span className="saved-flash sm"><span className="material-symbols-rounded">check_circle</span></span>}
                        <button className="mini-btn" onClick={() => toggleDrawer(m.id)} aria-expanded={open}>
                          <span className="material-symbols-rounded">{open ? "expand_less" : "key"}</span>Password
                        </button>
                      </div>
                    </td>
                  </tr>
                  {open && (
                    <tr className="tc-drawer-row">
                      <td colSpan={3}>
                        <div className="tc-drawer">
                          {busy && !c ? (
                            <div className="op-muted">Revealing…</div>
                          ) : err?.id === m.id ? (
                            <div className="fld-err">{err.msg}</div>
                          ) : c ? (
                            <>
                              <div className="fld tc-drawer-pass">
                                <label htmlFor={`tl-${m.id}`}>Sign-in login</label>
                                <input id={`tl-${m.id}`} value={c.username ?? c.email} readOnly spellCheck={false} />
                              </div>
                              <div className="fld tc-drawer-pass">
                                <label htmlFor={`tp-${m.id}`}>Password for {m.name}</label>
                                {c.available && c.password ? (
                                  <PasswordField id={`tp-${m.id}`} value={c.password} />
                                ) : (
                                  <div className="op-muted">No stored password yet — reset to generate one the member can sign in with.</div>
                                )}
                              </div>
                            </>
                          ) : null}
                          <div className="tc-drawer-actions">
                            <button className="ghostbtn" onClick={() => doReset(m.id, m.name)} disabled={busy}>
                              <span className="material-symbols-rounded">autorenew</span>
                              {busy ? "Working…" : "Generate new password"}
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
