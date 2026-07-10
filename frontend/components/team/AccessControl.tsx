"use client";

import {
  ROLE_ORDER, ROLE_META, permissions,
  type TeamRole, type PermKey,
} from "@/lib/data";

export default function AccessControl({
  rolePerms, onToggle,
}: {
  rolePerms: Record<TeamRole, PermKey[]>;
  onToggle: (role: TeamRole, key: PermKey) => void;
}) {
  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">admin_panel_settings</span>
          Role-based access · toggle a capability to grant or revoke it
        </div>
        <div className="sec-note inline">
          <span className="material-symbols-rounded">lock</span>
          Owner is all-access and locked. Changes are recorded in the activity log.
        </div>
      </div>

      <div className="rbac-wrap">
        <table className="rbac">
          <thead>
            <tr>
              <th className="rbac-cap">Capability</th>
              {ROLE_ORDER.map((r) => (
                <th key={r} className="rbac-role">
                  <span className="rbac-role-name" style={{ color: ROLE_META[r].c }}>{r}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {permissions.map((p) => (
              <tr key={p.key}>
                <td className="rbac-cap">
                  <div className="cap">
                    <span className="cap-ic material-symbols-rounded">{p.icon}</span>
                    <div>
                      <div className="cap-l">{p.label}</div>
                      <div className="cap-d">{p.desc}</div>
                    </div>
                  </div>
                </td>
                {ROLE_ORDER.map((r) => {
                  const on = rolePerms[r].includes(p.key);
                  const locked = r === "Owner";
                  return (
                    <td key={r} className="rbac-cell">
                      <button
                        className={`perm-tog${on ? " on" : ""}${locked ? " locked" : ""}`}
                        onClick={() => !locked && onToggle(r, p.key)}
                        disabled={locked}
                        role="switch"
                        aria-checked={on}
                        aria-label={`${on ? "Revoke" : "Grant"} ${p.label} for ${r}`}
                        title={locked ? "Owner always has full access" : on ? "Granted — click to revoke" : "Not granted — click to grant"}
                        style={on ? { background: ROLE_META[r].c, borderColor: ROLE_META[r].c } : undefined}
                      >
                        <span className="material-symbols-rounded">{on ? "check" : "remove"}</span>
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rbac-legend">
        {ROLE_ORDER.map((r) => (
          <div className="leg" key={r}>
            <span className="leg-dot" style={{ background: ROLE_META[r].c }} />
            <b style={{ color: ROLE_META[r].c }}>{r}</b>
            <span className="leg-d">{ROLE_META[r].desc}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
