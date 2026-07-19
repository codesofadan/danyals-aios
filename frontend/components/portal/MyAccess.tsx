"use client";

import Link from "next/link";
import {
  accessFeatures, GROUP_COLOR, ROLE_META,
  type FeatureGroup, type TeamMemberRecord,
} from "@/lib/data";
import { usePortal } from "./PortalContext";
import { toolSlug } from "@/lib/tools";

const GROUPS: FeatureGroup[] = ["Analytics", "Content", "Delivery", "Admin"];

export default function MyAccess({ me }: { me: TeamMemberRecord }) {
  const { myGrants } = usePortal();
  const granted = new Set(myGrants);
  const role = ROLE_META[me.role];
  const total = accessFeatures.length;

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">shield_person</span>
          What an admin has unlocked for you — {granted.size} of {total} features · click a tool to open it
        </div>
      </div>

      <div className="ac-role">
        <span className="role-chip" style={{ color: role.c, borderColor: role.c }}>{me.role}</span>
        <span className="ac-role-desc">{role.desc}</span>
      </div>

      {GROUPS.map((g) => {
        const feats = accessFeatures.filter((f) => f.group === g);
        const on = feats.filter((f) => granted.has(f.key)).length;
        return (
          <div className="ac-group" key={g}>
            <div className="ac-group-h">
              <span className="ac-group-dot" style={{ background: GROUP_COLOR[g] }} />
              {g}
              <span className="ac-group-n">{on}/{feats.length}</span>
            </div>
            <div className="ac-grid">
              {feats.map((f) => {
                const has = granted.has(f.key);
                if (has) {
                  return (
                    <Link
                      key={f.key}
                      href={`/team/tools/${toolSlug(f.key)}`}
                      className="ac-chip on"
                      style={{ ["--c" as string]: GROUP_COLOR[g] }}
                      title={`Open ${f.label}`}
                    >
                      <span className="ac-chip-ic material-symbols-rounded">{f.icon}</span>
                      <div className="ac-chip-main">
                        <div className="ac-chip-l">{f.label}</div>
                        <div className="ac-chip-d">{f.desc}</div>
                      </div>
                      <span className="ac-chip-open material-symbols-rounded">arrow_forward</span>
                    </Link>
                  );
                }
                return (
                  <div key={f.key} className="ac-chip off" title="Locked — ask an admin to unlock">
                    <span className="ac-chip-ic material-symbols-rounded">lock</span>
                    <div className="ac-chip-main">
                      <div className="ac-chip-l">{f.label}</div>
                      <div className="ac-chip-d">{f.desc}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}

      <div className="bk-note" style={{ marginTop: 16 }}>
        <span className="material-symbols-rounded">lock</span>
        <span>Need more access? Locked features are granted by an admin from <b>Team Management → Access</b>. Ask your lead to unlock what you need.</span>
      </div>
    </div>
  );
}
