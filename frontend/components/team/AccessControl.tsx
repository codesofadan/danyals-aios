"use client";

import {
  ROLE_ORDER, ROLE_META, permissions,
  type TeamRole, type PermKey,
} from "@/lib/data";

// The role×permission matrix is server-side REFERENCE data (GET /rbac/roles):
// versioned platform code with NO per-role persist endpoint (Owner is all-on and
// locked). It is therefore rendered strictly READ-ONLY — a static check/dash grid,
// not interactive switches — so nothing here implies a save that can't happen.
export default function AccessControl({
  rolePerms,
}: {
  rolePerms: Record<TeamRole, PermKey[]>;
}) {
  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">admin_panel_settings</span>
          Role-based access · the capabilities each role includes
        </div>
        <div className="sec-note inline">
          <span className="material-symbols-rounded">lock</span>
          Reference — these are the platform&apos;s fixed role permissions. Owner is all-access.
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
                  return (
                    <td key={r} className="rbac-cell">
                      <span
                        className={`perm-tog${on ? " on" : ""} static`}
                        aria-label={`${p.label}: ${on ? "granted" : "not granted"} for ${r}`}
                        title={on ? "Granted" : "Not granted"}
                        style={on ? { background: ROLE_META[r].c, borderColor: ROLE_META[r].c } : undefined}
                      >
                        <span className="material-symbols-rounded">{on ? "check" : "remove"}</span>
                      </span>
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
